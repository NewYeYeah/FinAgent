from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from finagent.agents.domain import AgentAction, AgentRunContext, ToolMode
from finagent.agents.tools.memory import ResearchMemoryToolDependencies, build_research_memory_tools
from finagent.domain.assets import AssetId
from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentResult, ExperimentSpec
from finagent.memory import (
    FailureCategory,
    FailureStage,
    HypothesisDisposition,
    LineageEdge,
    LineageRelation,
    MemoryNode,
    MemoryNodeType,
    ResearchHypothesisRevision,
    ResearchMemoryService,
    SQLiteResearchMemoryStore,
)


NOW = datetime(2026, 8, 25, 4, 0, tzinfo=timezone.utc)


def _memory(tmp_path):
    store = SQLiteResearchMemoryStore(tmp_path / "memory.sqlite")
    return store, ResearchMemoryService(store)


def _spec(
    experiment_id: str,
    hypothesis: str = "short term price momentum predicts next day cross sectional returns",
    order: int = 3,
) -> ExperimentSpec:
    dataset = ArtifactRef("dataset", ArtifactType.DATASET, "v1", "d" * 64)
    code = ArtifactRef("code", ArtifactType.CODE, "v1", "c" * 64)
    return ExperimentSpec(
        experiment_id=experiment_id,
        hypothesis=hypothesis,
        dataset=dataset,
        code=code,
        universe=(AssetId("AAA"), AssetId("BBB")),
        parameters={"order": order},
        seed=7,
    )


def test_hypothesis_revisions_are_append_only(tmp_path):
    store, memory = _memory(tmp_path)
    first = memory.create_hypothesis(
        "hyp-mom",
        "short term price momentum predicts next day returns",
        "test a simple continuation effect",
        NOW,
        tags=("Momentum", "short-term"),
    )
    second = memory.revise_hypothesis(
        "hyp-mom",
        "short term cross sectional momentum predicts next day returns after costs",
        "retain the mechanism but make cost sensitivity explicit",
        NOW + timedelta(minutes=1),
        disposition=HypothesisDisposition.SUPPORTED,
    )
    assert first.revision == 1
    assert second.revision == 2
    assert store.hypothesis_history("hyp-mom") == (first, second)
    with pytest.raises(ValueError, match="append-only"):
        store.register_hypothesis_revision(
            ResearchHypothesisRevision(
                "hyp-mom",
                4,
                "illegal skipped revision",
                "revision three does not exist",
                NOW + timedelta(minutes=2),
            )
        )


def test_memory_nodes_and_edges_are_immutable(tmp_path):
    store, _ = _memory(tmp_path)
    a = MemoryNode(MemoryNodeType.ARTIFACT, "a", "artifact-a", NOW)
    b = MemoryNode(MemoryNodeType.EXPERIMENT, "b", "experiment-b", NOW)
    store.register_node(a)
    store.register_node(a)
    store.register_node(b)
    edge = LineageEdge(a.key, b.key, LineageRelation.USES, NOW)
    store.register_edge(edge)
    store.register_edge(edge)
    with pytest.raises(ValueError, match="immutable"):
        store.register_node(MemoryNode(MemoryNodeType.ARTIFACT, "a", "changed", NOW))
    assert store.edges_for(a.key, direction="out") == (edge,)


def test_end_to_end_lineage_links_research_to_paper_evidence(tmp_path):
    _, memory = _memory(tmp_path)
    memory.create_hypothesis(
        "hyp-1",
        "short term price momentum predicts next day cross sectional returns",
        "test continuation after costs",
        NOW,
        tags=("momentum",),
    )
    spec = _spec("exp-1")
    memory.register_experiment("hyp-1", spec, NOW + timedelta(minutes=1))
    result = ExperimentResult("run-1", {"net_sharpe": 1.1}, True, notes="governed result")
    memory.register_result("exp-1", result, NOW + timedelta(minutes=2))
    snapshot = memory.register_operational_outcome(
        source_key="result:run-1",
        outcome_type=MemoryNodeType.PORTFOLIO_SNAPSHOT,
        outcome_id="snapshot-1",
        label="paper portfolio health snapshot",
        observed_at=NOW + timedelta(minutes=3),
        metrics={"level": "ok"},
        relation=LineageRelation.INFORMED,
    )
    memory.register_operational_outcome(
        source_key=snapshot.key,
        outcome_type=MemoryNodeType.PAPER_ORDER,
        outcome_id="order-1",
        label="paper order",
        observed_at=NOW + timedelta(minutes=4),
        metrics={"filled_quantity": 10},
        relation=LineageRelation.EXECUTED_AS,
    )
    summary = memory.summary("hyp-1")
    assert summary.node_counts["experiment"] == 1
    assert summary.node_counts["result"] == 1
    assert summary.node_counts["portfolio_snapshot"] == 1
    assert summary.node_counts["paper_order"] == 1
    assert summary.truncated is False


def test_failure_taxonomy_is_queryable_and_linked(tmp_path):
    _, memory = _memory(tmp_path)
    memory.create_hypothesis("hyp-fail", "high turnover alpha survives costs", "test cost fragility", NOW)
    spec = _spec("exp-fail", "high turnover alpha survives costs")
    memory.register_experiment("hyp-fail", spec, NOW + timedelta(minutes=1))
    failure = memory.record_failure(
        failure_id="failure-1",
        category=FailureCategory.TURNOVER,
        stage=FailureStage.VALIDATION,
        summary="net return disappears after turnover costs",
        observed_at=NOW + timedelta(minutes=2),
        hypothesis_id="hyp-fail",
        experiment_id="exp-fail",
        related_node_keys=("experiment:exp-fail",),
    )
    summary = memory.summary("hyp-fail")
    assert summary.failures == (failure,)
    assert summary.node_counts["failure"] == 1
    assert memory.store.failures(category=FailureCategory.TURNOVER) == (failure,)


def test_duplicate_hypothesis_detection_is_deterministic(tmp_path):
    _, memory = _memory(tmp_path)
    memory.create_hypothesis(
        "hyp-momentum",
        "short term price momentum predicts next day cross sectional returns",
        "continuation",
        NOW,
        tags=("momentum", "cross-sectional"),
    )
    memory.create_hypothesis(
        "hyp-reversal",
        "large overnight gaps mean revert over the next week",
        "reversal",
        NOW + timedelta(seconds=1),
        tags=("reversal",),
    )
    matches = memory.find_similar_hypotheses(
        "short term price momentum predicts next day returns",
        tags=("momentum", "cross-sectional"),
    )
    assert matches[0].entity_id == "hyp-momentum"
    assert matches[0].score > matches[1].score


def test_experiment_similarity_uses_signature_not_display_id(tmp_path):
    _, memory = _memory(tmp_path)
    memory.create_hypothesis("hyp-exp", "short term price momentum predicts next day cross sectional returns", "test", NOW)
    original = _spec("exp-original")
    memory.register_experiment("hyp-exp", original, NOW + timedelta(minutes=1))
    candidate = _spec("exp-candidate")
    matches = memory.find_similar_experiments(candidate)
    assert matches[0].entity_id == "exp-original"
    assert matches[0].score == pytest.approx(1.0)


def test_budget_policy_never_expands_and_blocks_near_duplicate(tmp_path):
    _, memory = _memory(tmp_path)
    statement = "short term price momentum predicts next day cross sectional returns"
    memory.create_hypothesis("hyp-budget", statement, "existing evidence", NOW, tags=("momentum",))
    spec = _spec("exp-budget", statement)
    memory.register_experiment("hyp-budget", spec, NOW + timedelta(minutes=1))
    memory.register_result(
        "exp-budget",
        ExperimentResult("run-budget", {"net_sharpe": 1.4}, True),
        NOW + timedelta(minutes=2),
    )
    duplicate = memory.recommend_budget(
        statement=statement,
        requested_max_experiments=8,
        tags=("momentum",),
    )
    assert duplicate.recommended_max_experiments == 0
    existing = memory.recommend_budget(
        statement="a completely different volatility hypothesis",
        requested_max_experiments=3,
        hypothesis_id="hyp-budget",
    )
    assert existing.supporting_result_count == 1
    assert existing.recommended_max_experiments <= existing.requested_max_experiments


def test_bounded_lineage_summary_reports_truncation(tmp_path):
    store, memory = _memory(tmp_path)
    memory.create_hypothesis("hyp-bound", "bounded memory summaries prevent prompt flooding", "test bounds", NOW)
    previous = "hypothesis:hyp-bound"
    for index in range(6):
        node = MemoryNode(
            MemoryNodeType.ARTIFACT,
            f"artifact-{index}",
            f"artifact-{index}",
            NOW + timedelta(seconds=index + 1),
        )
        store.register_node(node)
        store.register_edge(
            LineageEdge(previous, node.key, LineageRelation.PRODUCED, node.created_at)
        )
        previous = node.key
    summary = memory.summary("hyp-bound", max_nodes=3)
    assert len(summary.graph.nodes) == 3
    assert summary.truncated is True


def test_agent_memory_tools_are_read_only_and_bounded(tmp_path):
    _, memory = _memory(tmp_path)
    memory.create_hypothesis("hyp-tool", "momentum persists after costs", "tool evidence", NOW, tags=("momentum",))
    tools = build_research_memory_tools(ResearchMemoryToolDependencies(memory))
    assert len(tools) == 6
    assert all(tool.spec.mode is ToolMode.READ for tool in tools)
    assert {tool.spec.action for tool in tools} == {
        AgentAction.LIST_RESEARCH_HYPOTHESES,
        AgentAction.INSPECT_RESEARCH_HYPOTHESIS,
        AgentAction.FIND_SIMILAR_HYPOTHESES,
        AgentAction.INSPECT_RESEARCH_LINEAGE,
        AgentAction.INSPECT_RESEARCH_FAILURES,
        AgentAction.RECOMMEND_RESEARCH_BUDGET,
    }
    context = AgentRunContext("run-memory", "task-memory", "test", NOW, max_tool_calls=10)
    list_tool = next(tool for tool in tools if tool.spec.action is AgentAction.LIST_RESEARCH_HYPOTHESES)
    output = list_tool.invoke({"limit": 1}, context)
    assert output["hypotheses"][0]["hypothesis_id"] == "hyp-tool"
    budget_tool = next(tool for tool in tools if tool.spec.action is AgentAction.RECOMMEND_RESEARCH_BUDGET)
    budget = budget_tool.invoke(
        {"statement": "momentum persists after costs", "requested_max_experiments": 5},
        context,
    )
    assert budget["recommended_max_experiments"] <= 5
    assert budget["budget_expanded"] is False

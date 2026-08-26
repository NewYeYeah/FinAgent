from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from finagent.agents.domain import AgentAction, AgentRunContext
from finagent.agents.tools.memory import ResearchMemoryToolDependencies, build_research_memory_tools
from finagent.domain.assets import AssetId
from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentResult, ExperimentSpec
from finagent.memory import (
    AgentResearchMemoryView,
    EvidenceVisibility,
    FailureCategory,
    FailureStage,
    ResearchMemoryService,
    SQLiteMemoryVisibilityStore,
    SQLiteResearchMemoryStore,
)


NOW = datetime(2026, 8, 26, 3, 0, tzinfo=timezone.utc)


def _system(tmp_path):
    store = SQLiteResearchMemoryStore(tmp_path / "memory.sqlite")
    memory = ResearchMemoryService(store)
    visibility = SQLiteMemoryVisibilityStore(store.path)
    return store, memory, visibility


def _spec(experiment_id: str) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=experiment_id,
        hypothesis="short horizon momentum persists after costs",
        dataset=ArtifactRef("dataset", ArtifactType.DATASET, "v1", "d" * 64),
        code=ArtifactRef("code", ArtifactType.CODE, "v1", "c" * 64),
        universe=(AssetId("AAA"), AssetId("BBB")),
        parameters={"order": 1},
        seed=7,
    )


def _evidence(memory: ResearchMemoryService):
    memory.create_hypothesis(
        "hyp-vis",
        "short horizon momentum persists after costs",
        "visibility test",
        NOW,
        tags=("momentum",),
    )
    memory.register_experiment("hyp-vis", _spec("exp-vis"), NOW + timedelta(minutes=1))
    development = memory.register_result(
        "exp-vis",
        ExperimentResult("run-development", {"net_sharpe": 0.8}, True),
        NOW + timedelta(minutes=2),
    )
    holdout = memory.register_result(
        "exp-vis",
        ExperimentResult("run-holdout", {"net_sharpe": 2.5}, True),
        NOW + timedelta(minutes=3),
    )
    return development, holdout


def test_sealed_holdout_remains_in_audit_store_but_is_hidden_from_agent_view(tmp_path):
    store, memory, visibility = _system(tmp_path)
    development, holdout = _evidence(memory)
    visibility.bind(
        development.key,
        EvidenceVisibility.DEVELOPMENT,
        program_id="program-a",
        recorded_at=NOW + timedelta(minutes=2),
    )
    visibility.bind(
        holdout.key,
        EvidenceVisibility.SEALED_HOLDOUT,
        program_id="program-a",
        recorded_at=NOW + timedelta(minutes=3),
    )

    # The immutable evidence remains present for deterministic audit/promotion code.
    assert store.get_node(holdout.key) == holdout
    assert memory.summary("hyp-vis").node_counts["result"] == 2

    program_a = AgentResearchMemoryView(memory, visibility, program_id="program-a")
    summary_a = program_a.summary("hyp-vis")
    assert summary_a.node_counts["result"] == 1
    assert {node.key for node in summary_a.graph.nodes} == {
        "hypothesis:hyp-vis",
        "experiment:exp-vis",
        development.key,
    }
    assert summary_a.truncated

    with pytest.raises(PermissionError, match="not visible"):
        program_a.traverse(holdout.key)

    # A different program cannot consume another program's development evidence either.
    program_b = AgentResearchMemoryView(memory, visibility, program_id="program-b")
    summary_b = program_b.summary("hyp-vis")
    assert "result" not in summary_b.node_counts


def test_hidden_holdout_result_cannot_inflate_agent_budget_supporting_evidence(tmp_path):
    _, memory, visibility = _system(tmp_path)
    development, holdout = _evidence(memory)
    visibility.bind(
        development.key,
        EvidenceVisibility.DEVELOPMENT,
        program_id="program-a",
        recorded_at=NOW + timedelta(minutes=2),
    )
    visibility.bind(
        holdout.key,
        EvidenceVisibility.SEALED_HOLDOUT,
        program_id="program-a",
        recorded_at=NOW + timedelta(minutes=3),
    )

    program_a = AgentResearchMemoryView(memory, visibility, program_id="program-a")
    recommendation = program_a.recommend_budget(
        statement="a distinct volatility regime hypothesis",
        requested_max_experiments=4,
        hypothesis_id="hyp-vis",
    )
    assert recommendation.supporting_result_count == 1

    program_b = AgentResearchMemoryView(memory, visibility, program_id="program-b")
    recommendation_b = program_b.recommend_budget(
        statement="a distinct volatility regime hypothesis",
        requested_max_experiments=4,
        hypothesis_id="hyp-vis",
    )
    assert recommendation_b.supporting_result_count == 0


def test_failure_visibility_is_program_scoped_and_holdout_failures_are_hidden(tmp_path):
    _, memory, visibility = _system(tmp_path)
    memory.create_hypothesis("hyp-failure-vis", "turnover signal survives costs", "test", NOW)
    memory.register_experiment(
        "hyp-failure-vis",
        _spec("exp-failure-vis"),
        NOW + timedelta(minutes=1),
    )
    validation_failure = memory.record_failure(
        failure_id="validation-failure",
        category=FailureCategory.COST,
        stage=FailureStage.VALIDATION,
        summary="validation return disappears after costs",
        observed_at=NOW + timedelta(minutes=2),
        hypothesis_id="hyp-failure-vis",
        experiment_id="exp-failure-vis",
        related_node_keys=("experiment:exp-failure-vis",),
    )
    holdout_failure = memory.record_failure(
        failure_id="holdout-failure",
        category=FailureCategory.STATISTICAL,
        stage=FailureStage.VALIDATION,
        summary="sealed holdout rejects the candidate",
        observed_at=NOW + timedelta(minutes=3),
        hypothesis_id="hyp-failure-vis",
        experiment_id="exp-failure-vis",
        related_node_keys=("experiment:exp-failure-vis",),
    )
    visibility.bind(
        "failure:validation-failure",
        EvidenceVisibility.VALIDATION,
        program_id="program-a",
        recorded_at=validation_failure.observed_at,
    )
    visibility.bind(
        "failure:holdout-failure",
        EvidenceVisibility.SEALED_HOLDOUT,
        program_id="program-a",
        recorded_at=holdout_failure.observed_at,
    )

    view_a = AgentResearchMemoryView(memory, visibility, program_id="program-a")
    assert view_a.failures(hypothesis_id="hyp-failure-vis") == (validation_failure,)
    view_b = AgentResearchMemoryView(memory, visibility, program_id="program-b")
    assert view_b.failures(hypothesis_id="hyp-failure-vis") == ()


def test_agent_memory_tools_derive_program_scope_from_run_context(tmp_path):
    store, memory, visibility = _system(tmp_path)
    development, holdout = _evidence(memory)
    visibility.bind(
        development.key,
        EvidenceVisibility.DEVELOPMENT,
        program_id="program-a",
        recorded_at=NOW + timedelta(minutes=2),
    )
    visibility.bind(
        holdout.key,
        EvidenceVisibility.SEALED_HOLDOUT,
        program_id="program-a",
        recorded_at=NOW + timedelta(minutes=3),
    )

    # No explicit visibility dependency is required: the tool dependency creates the
    # colocated registry from the memory-store path and therefore observes the bindings.
    tools = build_research_memory_tools(ResearchMemoryToolDependencies(memory))
    inspect = next(
        tool for tool in tools if tool.spec.action is AgentAction.INSPECT_RESEARCH_HYPOTHESIS
    )
    budget = next(
        tool for tool in tools if tool.spec.action is AgentAction.RECOMMEND_RESEARCH_BUDGET
    )
    context_a = AgentRunContext(
        "run-a",
        "task-a",
        "agent",
        NOW,
        metadata={"program_id": "program-a"},
    )
    inspected = inspect.invoke({"hypothesis_id": "hyp-vis"}, context_a)
    assert inspected["node_counts"]["result"] == 1
    recommendation = budget.invoke(
        {
            "statement": "a distinct volatility regime hypothesis",
            "requested_max_experiments": 4,
            "hypothesis_id": "hyp-vis",
        },
        context_a,
    )
    assert recommendation["supporting_result_count"] == 1

    context_b = AgentRunContext(
        "run-b",
        "task-b",
        "agent",
        NOW,
        metadata={"program_id": "program-b"},
    )
    inspected_b = inspect.invoke({"hypothesis_id": "hyp-vis"}, context_b)
    assert "result" not in inspected_b["node_counts"]

    # Direct store access remains intentionally unrestricted for audit code.
    assert store.get_node(holdout.key) == holdout


def test_visibility_binding_is_immutable_and_rejects_unknown_nodes(tmp_path):
    _, memory, visibility = _system(tmp_path)
    memory.create_hypothesis("hyp-bind", "binding semantics are immutable", "test", NOW)
    key = "hypothesis:hyp-bind"
    first = visibility.bind(
        key,
        EvidenceVisibility.DEVELOPMENT,
        program_id="program-a",
        recorded_at=NOW,
    )
    assert visibility.bind(
        key,
        EvidenceVisibility.DEVELOPMENT,
        program_id="program-a",
        recorded_at=NOW,
    ) == first
    with pytest.raises(ValueError, match="immutable"):
        visibility.bind(
            key,
            EvidenceVisibility.SEALED_HOLDOUT,
            program_id="program-a",
            recorded_at=NOW,
        )
    with pytest.raises(KeyError, match="memory node"):
        visibility.bind(
            "result:not-registered",
            EvidenceVisibility.SEALED_HOLDOUT,
            program_id="program-a",
            recorded_at=NOW,
        )


def test_shared_and_unbound_legacy_nodes_remain_visible(tmp_path):
    _, memory, visibility = _system(tmp_path)
    memory.create_hypothesis("legacy", "legacy memory remains readable", "compatibility", NOW)
    memory.create_hypothesis("shared", "explicit shared memory remains readable", "compatibility", NOW)
    visibility.bind(
        "hypothesis:shared",
        EvidenceVisibility.SHARED,
        recorded_at=NOW,
    )
    view = AgentResearchMemoryView(memory, visibility, program_id="new-program")
    assert {item.hypothesis_id for item in view.list_hypotheses()} == {"legacy", "shared"}

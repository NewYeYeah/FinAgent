from __future__ import annotations

import tomllib
from dataclasses import replace
from pathlib import Path

from finagent.research.us_a1_factor_graph import FactorComplexityBudget
from finagent.research.us_a1_factor_materialization import compile_factor_graph_batch
from finagent.research.us_a1_legacy_graphs import legacy_a0_candidate_factor_graph
from finagent.research.us_agent_value_protocol import canonical_us_a0_primitive_vocabulary
from finagent.research.us_r3_agent_boundary import (
    AgentFactorProposalEnvelope,
    AgentGeneratorType,
    AgentResearchCapability,
    build_us_r3_research_iteration_plan,
    canonical_us_r3_agent_boundary_policy,
    validate_agent_factor_proposal,
)
from finagent.research.us_r3_alpha_catalog import (
    AlphaImplementationReadiness,
    build_us_r3_executable_frontier_candidates,
    build_us_r3_frontier_alpha_catalog,
)
from scripts.freeze_us_r3_research_iteration import build_bundle


def _agent_envelope(index: int = 0) -> AgentFactorProposalEnvelope:
    candidate = build_us_r3_executable_frontier_candidates()[index]
    return AgentFactorProposalEnvelope(
        generation_run_id="fixture-agent-run",
        slot=index,
        round_number=1,
        generator_type=AgentGeneratorType.AGENT,
        graph=candidate.graph,
        hypothesis=candidate.hypothesis,
        requested_capabilities=(
            AgentResearchCapability.PROPOSE_FACTOR_GRAPH,
            AgentResearchCapability.PROPOSE_HYPOTHESIS,
            AgentResearchCapability.PROPOSE_FALSIFICATION,
            AgentResearchCapability.REQUEST_DETERMINISTIC_VALIDATION,
        ),
        provider_id="fixture-provider",
        model_id="fixture-model",
        prompt_template_id="us-r3-structured-factor-graph-v1",
    )


def test_data_blind_agent_proposals_are_validated_without_financial_or_mt5_access() -> None:
    policy = canonical_us_r3_agent_boundary_policy()
    envelope = _agent_envelope()
    evidence = validate_agent_factor_proposal(envelope, policy=policy)

    assert evidence.valid
    assert evidence.candidate_id == envelope.hypothesis.candidate_id
    assert evidence.blockers == ()
    assert evidence.to_dict()["financial_data_read"] is False
    assert evidence.to_dict()["mt5_accessed"] is False
    assert policy.to_dict()["candidate_selection_authority"] is False
    assert policy.to_dict()["threshold_mutation_authority"] is False


def test_agent_boundary_rejects_data_tools_budget_and_identity_drift() -> None:
    valid = _agent_envelope()
    candidate = build_us_r3_executable_frontier_candidates()[1]
    widened_budget = FactorComplexityBudget(max_nodes=33, max_edges=48)
    unsafe_graph = replace(candidate.graph, budget=widened_budget)
    mismatched = replace(candidate.hypothesis, candidate_id="wrong-candidate")
    envelope = replace(
        valid,
        slot=24,
        round_number=4,
        graph=unsafe_graph,
        hypothesis=mismatched,
        requested_data_classes=("candidate_performance",),
        requested_tool_names=("mt5.order_send",),
    )
    evidence = validate_agent_factor_proposal(envelope)

    assert not evidence.valid
    assert evidence.candidate_id is None
    assert "candidate_slot_exceeds_policy" in evidence.blockers
    assert "generation_round_exceeds_policy" in evidence.blockers
    assert "graph_budget_exceeds_policy:max_nodes" in evidence.blockers
    assert "agent_data_access_requested" in evidence.blockers
    assert "agent_tool_access_requested" in evidence.blockers
    assert "hypothesis_candidate_id_mismatch" in evidence.blockers


def test_frontier_catalog_separates_executable_and_unavailable_data_families() -> None:
    catalog = build_us_r3_frontier_alpha_catalog()
    candidates = build_us_r3_executable_frontier_candidates()

    assert len(catalog) == 6
    assert len({item.strategy_id for item in catalog}) == 6
    assert len(candidates) == 3
    assert all(
        item.strategy.readiness is AlphaImplementationReadiness.EXECUTABLE_OHLCV_PANEL
        for item in candidates
    )
    assert {
        item.readiness
        for item in catalog
        if item.readiness is not AlphaImplementationReadiness.EXECUTABLE_OHLCV_PANEL
    } == {
        AlphaImplementationReadiness.REQUIRES_SESSION_ANCHOR_AGGREGATE,
        AlphaImplementationReadiness.REQUIRES_CROSS_SESSION_DATA,
        AlphaImplementationReadiness.REQUIRES_ORDER_FLOW_DATA,
    }


def test_research_plan_freezes_equal_budgets_and_denies_same_corpus_alpha_authority() -> None:
    policy = canonical_us_r3_agent_boundary_policy()
    candidates = build_us_r3_executable_frontier_candidates()
    plan = build_us_r3_research_iteration_plan(candidates)
    payload = plan.to_dict()

    assert plan.agent_boundary_policy_id == policy.policy_id
    assert plan.manual_slots == plan.programmatic_slots_per_seed == plan.agent_slots_per_run == 24
    assert len(plan.programmatic_seeds) == 3
    assert plan.agent_independent_run_count == 3
    assert payload["r2_corpus_reuse_authority"] == "development_and_exploratory_only"
    assert payload["alpha_authority"] is False
    assert payload["mt5_required"] is False


def test_frozen_bundle_is_deterministic_and_contains_no_performance_result() -> None:
    first = build_bundle()
    second = build_bundle()

    assert first == second
    assert first["bundle_id"] == second["bundle_id"]
    assert first["financial_data_read"] is False
    assert first["external_model_called"] is False
    assert first["financial_performance_evaluated"] is False
    assert first["alpha_gate_evaluated"] is False
    assert first["bundle_id"] == "us-r3-research-bundle-dbfa49573ce477e71ca8d85b"
    assert (
        first["agent_boundary_policy"]["policy_id"]
        == "us-r3-agent-boundary-21cd5b601dc578df6ecd2a2a"
    )
    assert (
        first["research_iteration_plan"]["plan_id"]
        == "us-r3-research-plan-b3793331cb19cb0544fa6857"
    )


def test_panel_extension_preserves_the_accepted_legacy_compiled_batch_identity() -> None:
    graphs = tuple(
        legacy_a0_candidate_factor_graph(candidate).graph
        for candidate in canonical_us_a0_primitive_vocabulary().all_candidates()
    )
    compiled = compile_factor_graph_batch(graphs)

    assert compiled.numeric_scope == "single_asset_time_series_v1"
    assert compiled.batch_id == "us-a1-compiled-factor-batch-0167c906375507a1ea810b2d"


def test_status_authority_is_bound_to_the_frozen_data_blind_bundle() -> None:
    root = Path(__file__).resolve().parents[1]
    with (root / "docs/status.toml").open("rb") as handle:
        status = tomllib.load(handle)
    bundle = build_bundle()
    stage = status["stage"]["us_r3"]

    assert status["current_stage"] == "US-R3"
    assert stage["research_iteration_bundle_id"] == bundle["bundle_id"]
    assert stage["agent_boundary_policy_id"] == bundle["agent_boundary_policy"]["policy_id"]
    assert stage["research_iteration_plan_id"] == bundle["research_iteration_plan"]["plan_id"]
    assert stage["financial_performance_evaluated"] is False
    assert stage["mt5_accessed"] is False
    assert stage["alpha_authority"] is False


def test_new_us_r3_runtime_has_no_mt5_import() -> None:
    root = Path(__file__).resolve().parents[1]
    sources = (
        root / "src/finagent/research/us_a1_factor_panel_materialization.py",
        root / "src/finagent/research/us_r3_agent_boundary.py",
        root / "src/finagent/research/us_r3_alpha_catalog.py",
        root / "scripts/freeze_us_r3_research_iteration.py",
    )
    for source in sources:
        text = source.read_text(encoding="utf-8")
        assert "import MetaTrader5" not in text
        assert "from MetaTrader5" not in text

from __future__ import annotations

from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_manual_candidates,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_baselines import canonical_us_baseline_denominator


def test_shared_vocabulary_is_bounded_structural_and_deterministic() -> None:
    left = canonical_us_a0_primitive_vocabulary()
    right = canonical_us_a0_primitive_vocabulary()

    assert left.vocabulary_id == right.vocabulary_id
    assert left.candidate_space_size == 62
    assert len(left.all_candidates()) == 62
    assert len({item.candidate_id for item in left.all_candidates()}) == 62
    assert left.to_dict()["scope"] == "bounded_shared_candidate_grammar_not_executable_code"


def test_candidate_identity_ignores_hypothesis_wording_and_compiles_to_b0_semantics() -> None:
    vocabulary = canonical_us_a0_primitive_vocabulary()
    candidate = vocabulary.all_candidates()[0]
    feature = candidate.compile_feature_spec()

    assert feature.kind is candidate.kind
    assert feature.window_bars == candidate.window_bars
    assert feature.input_fields == candidate.input_fields
    assert feature.protocol_id == canonical_us_baseline_denominator().protocol.protocol_id


def test_manual_grid_freezes_b0_core_plus_pre_result_extensions() -> None:
    manual = canonical_us_a0_manual_candidates()
    baseline = canonical_us_baseline_denominator()
    vocabulary = canonical_us_a0_primitive_vocabulary()

    assert len(manual) == 32
    assert len({item.candidate_id for item in manual}) == 32
    structural_core = tuple(
        vocabulary.candidate(feature.kind, feature.window_bars).candidate_id
        for feature in baseline.candidates
    )
    assert tuple(item.candidate_id for item in manual[:8]) == structural_core


def test_pilot_and_formal_budgets_and_repeats_are_preregistered() -> None:
    pilot = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    formal = canonical_us_a0_experiment_protocol(USAgentValuePhase.FORMAL)

    assert pilot.candidate_budget_per_run == 16
    assert formal.candidate_budget_per_run == 32
    assert len(pilot.manual_candidate_ids) == 16
    assert len(formal.manual_candidate_ids) == 32
    assert pilot.arms == (
        USAgentValueArm.MANUAL,
        USAgentValueArm.PROGRAMMATIC,
        USAgentValueArm.AGENT,
    )
    assert pilot.minimum_runs(USAgentValueArm.PROGRAMMATIC) == 1
    assert pilot.minimum_runs(USAgentValueArm.AGENT) == 1
    assert formal.minimum_runs(USAgentValueArm.PROGRAMMATIC) == 3
    assert formal.minimum_runs(USAgentValueArm.AGENT) == 3
    assert formal.replacements_allowed is False
    assert formal.invalid_and_duplicate_consume_slot is True
    assert formal.maximum_repairs_per_slot == 1
    assert formal.to_dict()["agent_value_gate_authority"] is False

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from finagent.research.us_agent_value_evaluation import (
    USAgentValueRunEvaluationStatus,
    aggregate_us_a0_run_evaluation,
    bind_us_a0_evaluation,
    bind_us_a0_fold_execution_specs,
    build_run_evaluation_link,
    compile_us_a0_evaluation_denominator,
    evaluate_us_a0_fold,
    materialize_us_a0_observations,
    validate_us_a0_preregistration_bundle,
)
from finagent.research.us_agent_value_experiment import USAgentValuePredecessorBinding
from finagent.research.us_agent_value_generation import (
    CandidateGenerationUsage,
    ProposalSlot,
    StructuredCandidateProposal,
    agent_run_spec,
    build_candidate_generation_run,
    canonical_manual_run_spec,
    manual_proposal_slots,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_manual_candidates,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_baseline_evaluation import USBaselineRunSpec
from finagent.research.us_baseline_walkforward import canonical_us_b0_pilot_walk_forward
from finagent.research.us_baselines import (
    USBaselineBar,
    canonical_us_baseline_denominator,
    evaluate_us_baseline_feature,
)


def _hash(payload: object, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _source_run_spec() -> USBaselineRunSpec:
    denominator = canonical_us_baseline_denominator()
    return USBaselineRunSpec(
        certification_report_id="us-minute-research-cert-test",
        certification_outcome="CERTIFIED_FOR_ENGINEERING_RESEARCH",
        engineering_universe_id="engineering-universe-test",
        denominator_id=denominator.denominator_id,
        minimum_cross_section=2,
        minimum_evaluated_periods=1,
        minimum_ic_periods=1,
    )


def _predecessor(source: USBaselineRunSpec) -> USAgentValuePredecessorBinding:
    return USAgentValuePredecessorBinding(
        us_b0_evidence_graph_id="us-baseline-walk-forward-evidence-test",
        us_b0_aggregate_report_id="us-baseline-walk-forward-aggregate-test",
        us_b0_run_spec_id=source.spec_id,
        us_b0_denominator_id=source.denominator_id,
        us_b0_walk_forward_protocol_id=canonical_us_b0_pilot_walk_forward().protocol_id,
        candidate_count=8,
    )


def _manual_run(phase: USAgentValuePhase):
    protocol = canonical_us_a0_experiment_protocol(phase)
    generated_at = datetime(2026, 9, 2, 5, 30, tzinfo=UTC)
    return protocol, build_candidate_generation_run(
        protocol,
        canonical_manual_run_spec(protocol),
        manual_proposal_slots(protocol, generated_at=generated_at),
    )


def _joined_rows(*, periods: int = 12) -> tuple[dict[str, object], ...]:
    assets = ("AAA", "BBB")
    start = datetime(2026, 3, 9, 13, 30, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for index in range(periods):
        event_time = start + timedelta(minutes=15 * index)
        available_at = event_time + timedelta(minutes=15)
        for asset_index, asset in enumerate(assets):
            close = 100.0 + asset_index * 5.0 + index * (1.0 + 0.1 * asset_index)
            rows.append(
                {
                    "research_asset_id": asset,
                    "session_date": "2026-03-09",
                    "session_id": "XNYS:2026-03-09",
                    "event_time": event_time,
                    "available_at": available_at,
                    "open": close - 0.2,
                    "high": close + 0.6,
                    "low": close - 0.5,
                    "close": close,
                    "volume": 1000.0 + asset_index * 100.0 + index * 20.0,
                    "bar_index": index,
                    "observed_minute_count": 15,
                    "expected_minute_count": 15,
                    "coverage_ratio": 1.0,
                    "is_complete": True,
                    "source_event_time": available_at - timedelta(minutes=1),
                    "source_available_at": available_at,
                    "source_price": close,
                    "target_event_time": available_at + timedelta(minutes=59),
                    "target_available_at": available_at + timedelta(minutes=60),
                    "label_value": 0.001 * (1 if asset == "AAA" else 2),
                    "label_available": True,
                    "unavailable_reason": None,
                    "label_row_present": True,
                    "close_anchor_difference": 0.0,
                }
            )
    return tuple(rows)


def _invalid_agent_slots(count: int, *, valid_first: bool = False) -> tuple[ProposalSlot, ...]:
    generated_at = datetime(2026, 9, 2, 5, 31, tzinfo=UTC)
    slots: list[ProposalSlot] = []
    for index in range(count):
        if valid_first and index == 0:
            kind = "momentum"
            window = 2
        else:
            kind = "not_a_frozen_kind"
            window = 2
        slots.append(
            ProposalSlot(
                initial=StructuredCandidateProposal(
                    kind=kind,
                    window_bars=window,
                    hypothesis_summary="Synthetic structured Agent proposal for bridge regression.",
                    generated_at=generated_at,
                    usage=CandidateGenerationUsage(
                        llm_calls=1,
                        input_tokens=10,
                        output_tokens=5,
                        latency_ms=10.0,
                        cost_usd=0.001,
                    ),
                )
            )
        )
    return tuple(slots)


def test_frozen_preregistration_ids_match_operator_artifacts() -> None:
    vocabulary = canonical_us_a0_primitive_vocabulary()
    pilot = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    formal = canonical_us_a0_experiment_protocol(USAgentValuePhase.FORMAL)

    assert vocabulary.vocabulary_id == "us-agent-value-vocabulary-a25485cf3c63c1c4ffd3bbc4"
    assert pilot.protocol_id == "us-agent-value-experiment-protocol-d8b568d76dfa994b2711aa03"
    assert formal.protocol_id == "us-agent-value-experiment-protocol-d214ae1745ebf76284ec1887"

    for phase, expected_bundle_id in (
        (USAgentValuePhase.PILOT, "us-agent-value-preregistration-9d592189de4ed0edf16e23c6"),
        (USAgentValuePhase.FORMAL, "us-agent-value-preregistration-06af38db5c1a22c2e8a3cd64"),
    ):
        protocol = canonical_us_a0_experiment_protocol(phase)
        manual = canonical_us_a0_manual_candidates()[: protocol.candidate_budget_per_run]
        payload: dict[str, object] = {
            "schema_version": "finagent.us-agent-value-preregistration-bundle.v1",
            "phase": phase.value,
            "vocabulary": vocabulary.to_dict(),
            "protocol": protocol.to_dict(),
            "manual_candidates": [candidate.to_dict() for candidate in manual],
            "manual_candidate_count": len(manual),
            "scope": "pre_result_controlled_experiment_preregistration_only",
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        payload["bundle_id"] = _hash(payload, "us-agent-value-preregistration")
        assert payload["bundle_id"] == expected_bundle_id
        assert validate_us_a0_preregistration_bundle(payload, phase).protocol_id == protocol.protocol_id


def test_manual_core_compiles_to_same_feature_semantics_as_us_b0() -> None:
    a0 = canonical_us_a0_manual_candidates()[:8]
    b0 = canonical_us_baseline_denominator()
    compiled = tuple(item.compile_feature_spec() for item in a0)

    bars = tuple(
        USBaselineBar(
            event_time=datetime(2026, 3, 9, 14, 0, tzinfo=UTC) + timedelta(minutes=15 * index),
            available_at=datetime(2026, 3, 9, 14, 15, tzinfo=UTC)
            + timedelta(minutes=15 * index),
            session_id="XNYS:2026-03-09",
            open=100.0 + index,
            high=101.0 + index,
            low=99.5 + index,
            close=100.5 + index,
            volume=1000.0 + 50.0 * index,
        )
        for index in range(10)
    )

    for a0_spec, b0_spec in zip(compiled, b0.candidates, strict=True):
        assert a0_spec.kind is b0_spec.kind
        assert a0_spec.window_bars == b0_spec.window_bars
        assert a0_spec.input_fields == b0_spec.input_fields
        left = evaluate_us_baseline_feature(a0_spec, bars, protocol=b0.protocol)
        right = evaluate_us_baseline_feature(b0_spec, bars, protocol=b0.protocol)
        assert left.value == pytest.approx(right.value) if right.value is not None else left.value is None
        assert left.unavailable_reason == right.unavailable_reason


def test_a0_materialization_reuses_exact_us_b0_formation_and_label_path() -> None:
    protocol, run = _manual_run(USAgentValuePhase.PILOT)
    denominator = compile_us_a0_evaluation_denominator(protocol, run)

    observations, diagnostics = materialize_us_a0_observations(
        _joined_rows(),
        denominator,
        expected_assets=("AAA", "BBB"),
    )

    assert diagnostics.passed
    assert len(observations) == 16
    assert set(observations) == {item.feature_id for item in denominator.candidates}
    assert all(len(rows) == 24 for rows in observations.values())


def test_manual_run_binds_same_certification_universe_and_frozen_folds() -> None:
    protocol, run = _manual_run(USAgentValuePhase.PILOT)
    source = _source_run_spec()
    binding = bind_us_a0_evaluation(protocol, _predecessor(source), run, source)
    folds = bind_us_a0_fold_execution_specs(protocol, binding)

    assert binding.run_spec.certification_report_id == source.certification_report_id
    assert binding.run_spec.engineering_universe_id == source.engineering_universe_id
    assert binding.run_spec.label_name == source.label_name
    assert binding.run_spec.denominator_id == binding.denominator.denominator_id
    assert binding.run_spec.denominator_id != source.denominator_id
    assert len(folds) == 3
    assert [item.fold_ordinal for item in folds] == [1, 2, 3]
    assert all(item.generation_run_id == run.run_id for item in folds)


def test_fold_evaluation_and_run_aggregate_use_shared_candidate_core() -> None:
    protocol, run = _manual_run(USAgentValuePhase.PILOT)
    source = _source_run_spec()
    binding = bind_us_a0_evaluation(protocol, _predecessor(source), run, source)
    observations, diagnostics = materialize_us_a0_observations(
        _joined_rows(),
        binding.denominator,
        expected_assets=("AAA", "BBB"),
    )
    assert diagnostics.passed
    folds = bind_us_a0_fold_execution_specs(protocol, binding)
    reports = tuple(evaluate_us_a0_fold(binding, fold, observations) for fold in folds)

    aggregate = aggregate_us_a0_run_evaluation(binding, reports)
    link = build_run_evaluation_link(run, aggregate)

    assert aggregate.status is USAgentValueRunEvaluationStatus.EVALUATED
    assert aggregate.evaluated_candidate_count == len(run.accepted_candidates)
    assert link.generation_run_id == run.run_id
    assert link.authoritative_evidence_id == aggregate.report_id
    assert link.evaluated_candidate_count == len(run.accepted_candidates)


def test_zero_accepted_agent_run_is_valid_experiment_outcome_without_fake_financial_rows() -> None:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    spec = agent_run_spec(
        protocol,
        run_ordinal=1,
        provider_id="provider-test",
        model_id="model-test",
        prompt_template_id="prompt-test",
    )
    run = build_candidate_generation_run(protocol, spec, _invalid_agent_slots(16))
    assert not run.accepted_candidates

    source = _source_run_spec()
    binding = bind_us_a0_evaluation(protocol, _predecessor(source), run, source)
    report = aggregate_us_a0_run_evaluation(binding, ())
    link = build_run_evaluation_link(run, report)

    assert report.status is USAgentValueRunEvaluationStatus.NO_ACCEPTED_CANDIDATES
    assert report.evaluated_candidate_count == 0
    assert report.valid_candidate_count == 0
    assert link.passed
    assert link.best_mean_rank_ic is None
    assert link.best_worst_fold_rank_ic is None


def test_formal_partial_agent_run_keeps_formal_protocol_even_with_one_candidate() -> None:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.FORMAL)
    spec = agent_run_spec(
        protocol,
        run_ordinal=1,
        provider_id="provider-test",
        model_id="model-test",
        prompt_template_id="prompt-test",
    )
    run = build_candidate_generation_run(protocol, spec, _invalid_agent_slots(32, valid_first=True))
    assert len(run.accepted_candidates) == 1

    source = _source_run_spec()
    binding = bind_us_a0_evaluation(protocol, _predecessor(source), run, source)
    observations, diagnostics = materialize_us_a0_observations(
        _joined_rows(),
        binding.denominator,
        expected_assets=("AAA", "BBB"),
    )
    assert diagnostics.passed
    folds = bind_us_a0_fold_execution_specs(protocol, binding)
    reports = tuple(evaluate_us_a0_fold(binding, fold, observations) for fold in folds)

    aggregate = aggregate_us_a0_run_evaluation(binding, reports)

    assert aggregate.status is USAgentValueRunEvaluationStatus.EVALUATED
    assert aggregate.evaluated_candidate_count == 1

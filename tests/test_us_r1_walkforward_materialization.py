from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from finagent.data.minute_store import MinuteMaterialization, MinuteQueryPlan
from finagent.data.minute_transform import LabelQueryPlan, LabelSeriesEvidence, ResamplingEvidence
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.research.us_agent_value_assembly import AgentValueExperimentEvidenceGraph
from finagent.research.us_agent_value_comparison import build_agent_value_comparison_snapshot
from finagent.research.us_agent_value_execution import build_us_a0_execution_plan
from finagent.research.us_agent_value_experiment import (
    AgentValueExperiment,
    RunEvaluationLink,
    USAgentValuePredecessorBinding,
    build_search_arm_result,
)
from finagent.research.us_agent_value_gate import (
    assess_us_a0_agent_value_gate,
    canonical_us_a0_agent_value_gate_policy,
    finalize_us_a0_agent_value_gate_review,
)
from finagent.research.us_agent_value_generation import (
    CandidateGenerationUsage,
    ProposalSlot,
    StructuredCandidateProposal,
    build_candidate_generation_run,
    deterministic_programmatic_proposal_slots,
    manual_proposal_slots,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_manual_candidates,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_r1_handoff import (
    build_authorized_us_r1_candidate_denominator_from_documents,
    parse_us_r1_candidate_denominator,
)
from finagent.research.us_r1_materialization import (
    USR1FoldMaterializationManifest,
    USR1MaterializationSlice,
    USR1ObservationArtifact,
    USR1ObservationDiagnostics,
    USR1ObservationRole,
    canonical_us_r1_feature_formation_policy,
    materialize_us_r1_candidate_observations,
)
from finagent.research.us_r1_materialization_evidence import (
    build_authoritative_us_r1_input_plan,
    canonical_us_r1_label_spec,
    merge_us_r1_observation_blockers,
    parse_us_r1_fold_materialization_manifest,
    validate_us_r1_input_rows,
)
from finagent.research.us_r1_protocol import (
    USR1AgentScope,
    USR1CandidateDenominator,
    USR1CandidateProvenance,
    canonical_us_r1_research_protocol,
)
from finagent.research.us_r1_walkforward import (
    bind_us_r1_fold_execution_specs,
    canonical_us_r1_walk_forward,
)

_NOW = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)


def _hash(payload: object, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _preregistration() -> dict[str, object]:
    phase = USAgentValuePhase.PILOT
    vocabulary = canonical_us_a0_primitive_vocabulary()
    protocol = canonical_us_a0_experiment_protocol(phase)
    manual = canonical_us_a0_manual_candidates()[: protocol.candidate_budget_per_run]
    payload: dict[str, object] = {
        "schema_version": "finagent.us-agent-value-preregistration-bundle.v1",
        "phase": phase.value,
        "vocabulary": vocabulary.to_dict(),
        "protocol": protocol.to_dict(),
        "manual_candidates": [item.to_dict() for item in manual],
        "manual_candidate_count": len(manual),
        "scope": "pre_result_controlled_experiment_preregistration_only",
        "status_authority": False,
        "stage_exit_authority": False,
        "agent_value_gate_authority": False,
        "alpha_authority": False,
    }
    payload["bundle_id"] = _hash(payload, "us-agent-value-preregistration")
    return payload


def _agent_slots(protocol) -> tuple[ProposalSlot, ...]:
    base = deterministic_programmatic_proposal_slots(
        protocol,
        random_seed=9182,
        generated_at=_NOW,
    )
    return tuple(
        ProposalSlot(
            initial=StructuredCandidateProposal(
                kind=slot.initial.kind,
                window_bars=slot.initial.window_bars,
                hypothesis_summary="Synthetic R1 handoff Agent proposal.",
                generated_at=_NOW,
                usage=CandidateGenerationUsage(
                    llm_calls=1,
                    input_tokens=50,
                    output_tokens=10,
                    latency_ms=100.0,
                    cost_usd=0.001,
                ),
            )
        )
        for slot in base
    )


def _link(run_id: str, count: int, robust: float, mean: float) -> RunEvaluationLink:
    return RunEvaluationLink(
        generation_run_id=run_id,
        authoritative_evidence_id=f"eval-{run_id[-10:]}",
        evaluated_candidate_count=count,
        valid_candidate_count=count,
        best_mean_rank_ic=mean,
        best_worst_fold_rank_ic=robust,
    )


def _terminal_pilot_documents():
    preregistration = _preregistration()
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    plan = build_us_a0_execution_plan(
        protocol,
        preregistration_bundle_id=str(preregistration["bundle_id"]),
        programmatic_seeds=(1729,),
        agent_provider_id="deepseek",
        agent_model_id="deepseek-v4-flash",
        agent_prompt_template_id="us-a0-structured-candidate-v1",
    )
    manual_spec = next(item for item in plan.run_specs if item.arm is USAgentValueArm.MANUAL)
    programmatic_spec = next(
        item for item in plan.run_specs if item.arm is USAgentValueArm.PROGRAMMATIC
    )
    agent_spec = next(item for item in plan.run_specs if item.arm is USAgentValueArm.AGENT)
    manual_run = build_candidate_generation_run(
        protocol,
        manual_spec,
        manual_proposal_slots(protocol, generated_at=_NOW),
    )
    programmatic_run = build_candidate_generation_run(
        protocol,
        programmatic_spec,
        deterministic_programmatic_proposal_slots(
            protocol,
            random_seed=1729,
            generated_at=_NOW,
        ),
    )
    agent_run = build_candidate_generation_run(protocol, agent_spec, _agent_slots(protocol))
    manual_result = build_search_arm_result(
        protocol,
        USAgentValueArm.MANUAL,
        (manual_run,),
        (_link(manual_run.run_id, len(manual_run.accepted_candidates), 0.010, 0.020),),
    )
    programmatic_result = build_search_arm_result(
        protocol,
        USAgentValueArm.PROGRAMMATIC,
        (programmatic_run,),
        (
            _link(
                programmatic_run.run_id,
                len(programmatic_run.accepted_candidates),
                0.012,
                0.022,
            ),
        ),
    )
    agent_result = build_search_arm_result(
        protocol,
        USAgentValueArm.AGENT,
        (agent_run,),
        (_link(agent_run.run_id, len(agent_run.accepted_candidates), 0.009, 0.019),),
    )
    predecessor = USAgentValuePredecessorBinding(
        us_b0_evidence_graph_id="b0-r1-handoff-graph",
        us_b0_aggregate_report_id="b0-r1-handoff-aggregate",
        us_b0_run_spec_id="b0-r1-handoff-run",
        us_b0_denominator_id="b0-r1-handoff-denominator",
        us_b0_walk_forward_protocol_id=protocol.us_b0_walk_forward_protocol_id,
        candidate_count=8,
    )
    experiment = AgentValueExperiment(
        protocol=protocol,
        predecessor=predecessor,
        arm_results=(manual_result, programmatic_result, agent_result),
    )
    comparison = build_agent_value_comparison_snapshot(
        manual_result,
        programmatic_result,
        agent_result,
    )
    runs = (manual_run, programmatic_run, agent_run)
    links = tuple(link for result in experiment.arm_results for link in result.evaluation_links)
    graph = AgentValueExperimentEvidenceGraph(
        execution_plan_id=plan.plan_id,
        preregistration_bundle_id=plan.preregistration_bundle_id,
        predecessor_binding_id=predecessor.binding_id,
        experiment_id=experiment.experiment_id,
        comparison_snapshot_id=comparison.snapshot_id,
        arm_result_ids=tuple(result.result_id for result in experiment.arm_results),
        generation_run_ids=tuple(run.run_id for run in runs),
        run_evidence_manifest_ids=tuple(f"manifest-{index}" for index in range(3)),
        run_evaluation_report_ids=tuple(link.authoritative_evidence_id for link in links),
        run_evaluation_link_ids=tuple(link.link_id for link in links),
        evidence_complete=True,
        ready_for_agent_value_gate_review=True,
    )
    assessment = assess_us_a0_agent_value_gate(
        policy=canonical_us_a0_agent_value_gate_policy(USAgentValuePhase.PILOT),
        execution_plan=plan,
        experiment=experiment,
        comparison=comparison,
        evidence_graph=graph,
    )
    review = finalize_us_a0_agent_value_gate_review(
        assessment,
        reviewer_id="r1-handoff-reviewer",
        reviewed_at=_NOW,
        review_notes="Terminal PILOT review accepted for strict R1 handoff regression evidence.",
        thresholds_unchanged_attested=True,
        evidence_lineage_attested=True,
        alpha_gate_separation_attested=True,
        stage_authority_separation_attested=True,
    )
    assert review.decision.value == "PILOT_DO_NOT_PROCEED_TO_FORMAL"
    status: dict[str, object] = {
        "current_stage": "US-R1",
        "stage": {
            "us_a0": {
                "status": "accepted",
                "stage_exit_gate_passed": True,
                "terminal_gate_review_id": review.review_id,
                "experiment_id": experiment.experiment_id,
                "evidence_graph_id": graph.graph_id,
            }
        },
    }
    return preregistration, plan, experiment, review, runs, status


def _single_denominator() -> USR1CandidateDenominator:
    candidate = canonical_us_a0_primitive_vocabulary().all_candidates()[0]
    return USR1CandidateDenominator(
        protocol_id=canonical_us_r1_research_protocol().protocol_id,
        a0_phase=USAgentValuePhase.PILOT,
        a0_experiment_id="experiment-r1-materialization",
        a0_gate_review_id="review-r1-materialization",
        a0_gate_decision=__import__(
            "finagent.research.us_agent_value_gate",
            fromlist=["USAgentValueGateDecision"],
        ).USAgentValueGateDecision.PILOT_DO_NOT_PROCEED_TO_FORMAL,
        agent_scope=USR1AgentScope.CONTRACTED,
        candidates=(
            USR1CandidateProvenance(
                candidate=candidate,
                source_arms=(USAgentValueArm.MANUAL,),
                source_run_ids=("manual-r1-materialization",),
            ),
        ),
    )


def _plans(
    denominator: USR1CandidateDenominator,
    *,
    interval: BarInterval,
    horizon: int,
    role: USR1ObservationRole,
):
    execution = bind_us_r1_fold_execution_specs(
        canonical_us_r1_walk_forward(),
        denominator,
    )[0]
    start = execution.train_start if role is USR1ObservationRole.TRAIN else execution.evaluation_start
    end = execution.train_end if role is USR1ObservationRole.TRAIN else execution.evaluation_end
    assets = ("AAA", "BBB")
    bars_query = MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=start,
        end=end,
        interval=interval,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )
    labels_query = MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=start,
        end=end,
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.CLOSE,),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )
    bar_plan = MinuteQueryPlan(
        query=bars_query,
        manifest_id="manifest-r1",
        data_version="resampled-r1",
        sql="SELECT * FROM bars",
        partition_months=("2026-01", "2026-02"),
        selected_size_bytes=100,
        output_columns=("research_asset_id", "event_time", "available_at"),
    )
    label_spec = canonical_us_r1_label_spec(horizon)
    label_plan = LabelQueryPlan(
        source_query=labels_query,
        materialization_spec_id="label-materialization-r1",
        label_spec_id=label_spec.label_id,
        source_plan_id="label-source-r1",
        source_data_version="raw-r1",
        data_version="label-r1",
        sql="SELECT * FROM labels",
        partition_months=("2026-01", "2026-02"),
        selected_size_bytes=90,
        output_columns=("research_asset_id", "source_available_at", "label_value"),
    )
    resampling = ResamplingEvidence(
        spec_id="resample-spec-r1",
        calendar_id=canonical_us_r1_walk_forward().calendar_id,
        sessionization_evidence_id="sessionization-r1",
        source_plan_id="raw-plan-r1",
        resampled_plan_id=bar_plan.plan_id,
        source_data_version="raw-r1",
        resampled_data_version=bar_plan.data_version,
    )
    labels = LabelSeriesEvidence(
        materialization_spec_id="label-materialization-r1",
        label_spec_id=label_spec.label_id,
        calendar_id=canonical_us_r1_walk_forward().calendar_id,
        sessionization_evidence_id="sessionization-r1",
        source_plan_id="label-source-r1",
        label_plan_id=label_plan.plan_id,
        source_data_version="raw-r1",
        label_data_version=label_plan.data_version,
    )
    return execution, bar_plan, label_plan, resampling, labels


def _joined_rows(*, interval_minutes: int = 5, periods: int = 5, assets=("AAA", "BBB")):
    start = datetime(2026, 2, 17, 14, 30, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for index in range(periods):
        event_time = start + timedelta(minutes=interval_minutes * index)
        available_at = event_time + timedelta(minutes=interval_minutes)
        for asset_index, asset in enumerate(assets):
            close = 100.0 + asset_index * 5.0 + index
            rows.append(
                {
                    "research_asset_id": asset,
                    "session_date": "2026-02-17",
                    "session_id": "XNYS:2026-02-17",
                    "event_time": event_time,
                    "available_at": available_at,
                    "open": close - 0.2,
                    "high": close + 0.5,
                    "low": close - 0.5,
                    "close": close,
                    "volume": 1000.0 + index,
                    "is_complete": True,
                    "source_available_at": available_at,
                    "source_price": close,
                    "target_available_at": available_at + timedelta(minutes=60),
                    "label_value": 0.001 * (asset_index + 1),
                    "label_available": True,
                    "unavailable_reason": None,
                    "label_row_present": True,
                    "close_anchor_difference": 0.0,
                }
            )
    return tuple(rows)


def test_authorized_a0_handoff_builds_full_structural_union_without_performance_filter() -> None:
    prereg, plan, experiment, review, runs, status = _terminal_pilot_documents()
    denominator = build_authorized_us_r1_candidate_denominator_from_documents(
        status_document=status,
        preregistration_document=prereg,
        execution_plan_document=plan.to_dict(),
        experiment_document=experiment.to_dict(),
        gate_review_document=review.to_dict(),
        generation_run_documents=tuple(run.to_dict() for run in runs),
    )
    expected = tuple(
        dict.fromkeys(
            candidate.candidate_id
            for result in experiment.arm_results
            for run in result.generation_runs
            for candidate in run.accepted_candidates
        )
    )
    assert tuple(item.candidate.candidate_id for item in denominator.candidates) == expected
    assert denominator.to_dict()["performance_filter_applied"] is False
    assert parse_us_r1_candidate_denominator(denominator.to_dict()) == denominator

    tampered = json.loads(json.dumps(denominator.to_dict()))
    tampered["candidates"][0]["candidate"]["window_bars"] = 13
    with pytest.raises(ValueError):
        parse_us_r1_candidate_denominator(tampered)


def test_walk_forward_reuses_b0_oos_windows_and_excludes_entire_validation_gap() -> None:
    r1 = canonical_us_r1_walk_forward()
    assert len(r1.folds) == 3
    assert all(fold.required_gap_trading_minutes == 120 for fold in r1.folds)
    assert r1.folds[0].train_end == r1.folds[0].gap_start
    assert r1.folds[0].gap_end == r1.folds[0].evaluation_start
    assert r1.folds[1].evaluation_start == r1.folds[0].evaluation_end
    assert r1.to_dict()["alpha_authority"] is False


def test_authoritative_input_plan_requires_raw_regular_available_at_and_exact_label_identity() -> None:
    denominator = _single_denominator()
    execution, bars, labels, resampling, label_evidence = _plans(
        denominator,
        interval=BarInterval.MINUTE_5,
        horizon=60,
        role=USR1ObservationRole.EVALUATION,
    )
    plan = build_authoritative_us_r1_input_plan(
        bars,
        labels,
        resampling,
        label_evidence,
        execution_spec=execution,
        denominator=denominator,
        role=USR1ObservationRole.EVALUATION,
        label_horizon_trading_minutes=60,
    )
    assert plan.signal_interval is BarInterval.MINUTE_5
    assert "l.source_available_at = b.available_at" in plan.sql

    bad_query = MarketDataQuery(
        market_id=bars.query.market_id,
        assets=bars.query.assets,
        start=bars.query.start,
        end=bars.query.end,
        interval=bars.query.interval,
        fields=bars.query.fields,
        session_policy=bars.query.session_policy,
        adjustment_policy=ResearchPriceBasis.SPLIT_ADJUSTED,
        availability_policy=bars.query.availability_policy,
    )
    bad_bars = MinuteQueryPlan(
        query=bad_query,
        manifest_id=bars.manifest_id,
        data_version=bars.data_version,
        sql=bars.sql,
        partition_months=bars.partition_months,
        selected_size_bytes=bars.selected_size_bytes,
        output_columns=bars.output_columns,
    )
    with pytest.raises(ValueError, match="RAW"):
        build_authoritative_us_r1_input_plan(
            bad_bars,
            labels,
            resampling,
            label_evidence,
            execution_spec=execution,
            denominator=denominator,
            role=USR1ObservationRole.EVALUATION,
            label_horizon_trading_minutes=60,
        )


def test_multifrequency_materialization_reuses_structural_feature_evaluator() -> None:
    denominator = _single_denominator()
    rows = _joined_rows()
    row_blockers = validate_us_r1_input_rows(rows, expected_assets=("AAA", "BBB"))
    observations, diagnostics = materialize_us_r1_candidate_observations(
        rows,
        denominator,
        role=USR1ObservationRole.EVALUATION,
        signal_interval=BarInterval.MINUTE_5,
        label_horizon_trading_minutes=60,
        expected_assets=("AAA", "BBB"),
    )
    diagnostics = merge_us_r1_observation_blockers(diagnostics, row_blockers)
    assert diagnostics.passed
    assert observations
    assert all(item.signal_interval is BarInterval.MINUTE_5 for item in observations)
    assert any(item.feature_value is not None for item in observations)
    expected_spec = denominator.candidates[0].candidate.compile_feature_spec().spec_id
    assert {item.feature_spec_id for item in observations} == {expected_spec}

    missing_rows = _joined_rows(assets=("AAA",))
    missing = validate_us_r1_input_rows(missing_rows, expected_assets=("AAA", "BBB"))
    assert any("engineering_assets_missing:BBB" in item for item in missing)

    bad_time = list(_joined_rows())
    bad_time[0] = dict(bad_time[0])
    bad_time[0]["target_available_at"] = bad_time[0]["available_at"]
    with pytest.raises(ValueError, match="after feature formation"):
        validate_us_r1_input_rows(tuple(bad_time), expected_assets=("AAA", "BBB"))


def _slice(role: USR1ObservationRole, interval: BarInterval, horizon: int) -> USR1MaterializationSlice:
    return USR1MaterializationSlice(
        role=role,
        signal_interval=interval,
        label_horizon_trading_minutes=horizon,
        input_plan_id=f"plan-{role.value}-{interval.value}-{horizon}",
        input_materialization_id=f"materialization-{role.value}-{interval.value}-{horizon}",
        observation_artifact_id=f"artifact-{role.value}-{interval.value}-{horizon}",
        diagnostics_id=f"diagnostics-{role.value}-{interval.value}-{horizon}",
        input_row_count=10,
        observation_row_count=10,
        passed=True,
        blockers=(),
    )


def test_fold_manifest_requires_exact_six_slice_denominator_and_round_trips() -> None:
    denominator = _single_denominator()
    walk_forward = canonical_us_r1_walk_forward()
    execution = bind_us_r1_fold_execution_specs(walk_forward, denominator)[0]
    slices = (
        _slice(USR1ObservationRole.TRAIN, BarInterval.MINUTE_15, 60),
        _slice(USR1ObservationRole.EVALUATION, BarInterval.MINUTE_5, 60),
        _slice(USR1ObservationRole.EVALUATION, BarInterval.MINUTE_15, 30),
        _slice(USR1ObservationRole.EVALUATION, BarInterval.MINUTE_15, 60),
        _slice(USR1ObservationRole.EVALUATION, BarInterval.MINUTE_15, 120),
        _slice(USR1ObservationRole.EVALUATION, BarInterval.MINUTE_30, 60),
    )
    manifest = USR1FoldMaterializationManifest(
        research_protocol_id=canonical_us_r1_research_protocol().protocol_id,
        walk_forward_protocol_id=walk_forward.protocol_id,
        execution_spec_id=execution.execution_spec_id,
        denominator_id=denominator.denominator_id,
        formation_policy_id=canonical_us_r1_feature_formation_policy().policy_id,
        fold_id=execution.fold_id,
        fold_ordinal=1,
        verified_gap_trading_minutes=390,
        required_gap_trading_minutes=120,
        slices=slices,
    )
    assert manifest.passed
    assert parse_us_r1_fold_materialization_manifest(manifest.to_dict()) == manifest
    with pytest.raises(ValueError, match="exact six"):
        USR1FoldMaterializationManifest(
            research_protocol_id=manifest.research_protocol_id,
            walk_forward_protocol_id=manifest.walk_forward_protocol_id,
            execution_spec_id=manifest.execution_spec_id,
            denominator_id=manifest.denominator_id,
            formation_policy_id=manifest.formation_policy_id,
            fold_id=manifest.fold_id,
            fold_ordinal=1,
            verified_gap_trading_minutes=390,
            required_gap_trading_minutes=120,
            slices=tuple(reversed(slices)),
        )


def test_content_addressed_artifact_and_minute_materialization_bind_slice_ids() -> None:
    artifact = USR1ObservationArtifact(
        execution_spec_id="execution",
        denominator_id="denominator",
        input_plan_id="plan",
        role=USR1ObservationRole.TRAIN,
        signal_interval=BarInterval.MINUTE_15,
        label_horizon_trading_minutes=60,
        row_count=2,
        content_sha256="a" * 64,
        output_filename="observations.jsonl",
    )
    materialization = MinuteMaterialization(
        plan_id="plan",
        data_version="data-version",
        row_count=2,
        size_bytes=128,
        content_sha256="b" * 64,
        output_filename="inputs.parquet",
    )
    diagnostics = USR1ObservationDiagnostics(
        input_row_count=2,
        complete_bar_count=2,
        incomplete_bar_count=0,
        label_anchor_missing_count=0,
        close_anchor_mismatch_count=0,
        observation_count=2,
        available_feature_count=1,
        available_label_count=2,
        blockers=(),
    )
    assert artifact.artifact_id.startswith("us-r1-observations-")
    assert materialization.materialization_id.startswith("minute-materialization-")
    assert diagnostics.diagnostics_id.startswith("us-r1-observation-diagnostics-")

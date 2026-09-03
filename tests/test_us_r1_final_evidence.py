from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest

from finagent.domain.market_bars import BarInterval
from finagent.research.us_agent_value_gate import USAgentValueGateDecision
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_manual_candidates,
)
from finagent.research.us_r1_direction import USR1DirectionPreparationReport
from finagent.research.us_r1_evaluation_policy import (
    canonical_us_r1_statistical_evaluation_policy,
)
from finagent.research.us_r1_final import build_us_r1_final_inference_artifacts
from finagent.research.us_r1_gate import (
    USR1AlphaGateAssessment,
    USR1CandidateGateAssessment,
    canonical_us_r1_alpha_gate_policy,
)
from finagent.research.us_r1_inference import USR1PeriodMetricPoint
from finagent.research.us_r1_materialization import (
    USR1CandidateObservation,
    USR1ObservationArtifact,
    USR1ObservationRole,
    compile_us_r1_feature_spec,
)
from finagent.research.us_r1_observation_io import read_us_r1_observation_file
from finagent.research.us_r1_protocol import (
    USR1AgentScope,
    USR1CandidateDenominator,
    USR1CandidateProvenance,
    USR1Terminal,
    canonical_us_r1_research_protocol,
)
from finagent.research.us_r1_review import finalize_us_r1_alpha_gate_review
from finagent.research.us_r1_statistics import (
    USR1CandidateDirectionEvidence,
    USR1CandidateSliceStatistics,
    USR1DirectionEvidenceSet,
    USR1FoldStatisticsReport,
    USR1PeriodMetricArtifact,
    USR1PeriodMetricRecord,
    build_us_r1_direction_evidence,
    evaluate_us_r1_candidate_slice,
)
from finagent.research.us_r1_walkforward import canonical_us_r1_walk_forward


def _denominator() -> USR1CandidateDenominator:
    candidate = canonical_us_a0_manual_candidates()[0]
    return USR1CandidateDenominator(
        protocol_id=canonical_us_r1_research_protocol().protocol_id,
        a0_phase=USAgentValuePhase.PILOT,
        a0_experiment_id="a0-experiment-final-test",
        a0_gate_review_id="a0-review-final-test",
        a0_gate_decision=USAgentValueGateDecision.PILOT_DO_NOT_PROCEED_TO_FORMAL,
        agent_scope=USR1AgentScope.CONTRACTED,
        candidates=(
            USR1CandidateProvenance(
                candidate=candidate,
                source_arms=(USAgentValueArm.MANUAL,),
                source_run_ids=("manual-run-final-test",),
            ),
        ),
    )


def _observations(
    *,
    role: USR1ObservationRole,
    interval: BarInterval,
    horizon: int,
    periods: int = 24,
    reverse_label: bool = False,
) -> tuple[USR1CandidateObservation, ...]:
    candidate = _denominator().candidates[0].candidate
    spec_id = compile_us_r1_feature_spec(candidate, interval).spec_id
    start = datetime(2026, 1, 5, 14, 45, tzinfo=UTC)
    rows: list[USR1CandidateObservation] = []
    for period in range(periods):
        formation = start + timedelta(minutes=15 * period)
        session_id = f"XNYS:2026-01-{5 + period // 8:02d}"
        for asset_index in range(10):
            feature = float(asset_index + 1)
            label = 0.0005 * (asset_index + 1)
            if reverse_label:
                label = -label
            rows.append(
                USR1CandidateObservation(
                    candidate_id=candidate.candidate_id,
                    feature_spec_id=spec_id,
                    role=role,
                    signal_interval=interval,
                    label_horizon_trading_minutes=horizon,
                    asset=f"T{asset_index:02d}",
                    session_id=session_id,
                    event_time=formation - timedelta(minutes=interval.minutes or 15),
                    feature_available_at=formation,
                    feature_value=feature,
                    feature_unavailable_reason=None,
                    realized_label=label,
                    label_available_at=formation + timedelta(minutes=horizon),
                    label_unavailable_reason=None,
                )
            )
    return tuple(rows)


def _train_statistics(
    *,
    candidate_id: str,
    blockers: tuple[str, ...] = (),
) -> USR1CandidateSliceStatistics:
    return USR1CandidateSliceStatistics(
        candidate_id=candidate_id,
        role=USR1ObservationRole.TRAIN,
        signal_interval=BarInterval.MINUTE_15,
        label_horizon_trading_minutes=60,
        period_count=0 if blockers else 24,
        boundary_unrealized_period_count=0,
        insufficient_cross_section_period_count=0,
        mean_raw_rank_ic=None if blockers else 0.03,
        blockers=blockers,
    )


def _direction_preparation(
    denominator: USR1CandidateDenominator,
    *,
    blockers: tuple[str, ...] = (),
) -> USR1DirectionPreparationReport:
    candidate_id = denominator.candidates[0].candidate.candidate_id
    return USR1DirectionPreparationReport(
        denominator_id=denominator.denominator_id,
        evaluation_policy_id=canonical_us_r1_statistical_evaluation_policy().policy_id,
        source_fold_id="fold-01",
        source_fold_manifest_id="materialization-01",
        candidate_train_statistics=(
            _train_statistics(candidate_id=candidate_id, blockers=blockers),
        ),
        blockers=(
            ()
            if not blockers
            else tuple(f"candidate:{candidate_id}:{item}" for item in blockers)
        ),
    )


def test_statistical_policy_freezes_train_only_direction_and_quintiles() -> None:
    policy = canonical_us_r1_statistical_evaluation_policy()
    assert policy.direction_source_fold_ordinal == 1
    assert policy.direction_signal_interval is BarInterval.MINUTE_15
    assert policy.direction_label_horizon_trading_minutes == 60
    assert policy.direction_frozen_across_oos_folds
    assert policy.minimum_cross_section == 10
    assert policy.quantile_count == 5


def test_direction_is_frozen_from_train_even_when_oos_reverses() -> None:
    denominator = _denominator()
    policy = canonical_us_r1_statistical_evaluation_policy()
    direction = build_us_r1_direction_evidence(
        _observations(
            role=USR1ObservationRole.TRAIN,
            interval=BarInterval.MINUTE_15,
            horizon=60,
        ),
        denominator,
        fold_id="fold-01",
        fold_materialization_manifest_id="manifest-fold-01",
        policy=policy,
    )
    candidate_id = denominator.candidates[0].candidate.candidate_id
    assert direction.direction(candidate_id) == 1

    statistics, points = evaluate_us_r1_candidate_slice(
        _observations(
            role=USR1ObservationRole.EVALUATION,
            interval=BarInterval.MINUTE_15,
            horizon=60,
            reverse_label=True,
        ),
        candidate_id=candidate_id,
        role=USR1ObservationRole.EVALUATION,
        signal_interval=BarInterval.MINUTE_15,
        label_horizon_trading_minutes=60,
        policy=policy,
        minimum_periods=20,
    )
    assert statistics.passed
    assert statistics.mean_raw_rank_ic is not None
    assert statistics.mean_raw_rank_ic < 0
    assert all(point.long_short_return_bps < 0 for point in points)
    assert direction.direction(candidate_id) == 1


def test_partial_label_missing_omits_same_entire_period_for_every_candidate() -> None:
    policy = canonical_us_r1_statistical_evaluation_policy()
    denominator = _denominator()
    candidate_id = denominator.candidates[0].candidate.candidate_id
    rows = list(
        _observations(
            role=USR1ObservationRole.EVALUATION,
            interval=BarInterval.MINUTE_15,
            horizon=60,
        )
    )
    first = rows[0]
    rows[0] = USR1CandidateObservation(
        candidate_id=first.candidate_id,
        feature_spec_id=first.feature_spec_id,
        role=first.role,
        signal_interval=first.signal_interval,
        label_horizon_trading_minutes=first.label_horizon_trading_minutes,
        asset=first.asset,
        session_id=first.session_id,
        event_time=first.event_time,
        feature_available_at=first.feature_available_at,
        feature_value=first.feature_value,
        feature_unavailable_reason=None,
        realized_label=None,
        label_available_at=None,
        label_unavailable_reason="target_minute_missing",
    )
    statistics, points = evaluate_us_r1_candidate_slice(
        rows,
        candidate_id=candidate_id,
        role=USR1ObservationRole.EVALUATION,
        signal_interval=BarInterval.MINUTE_15,
        label_horizon_trading_minutes=60,
        policy=policy,
        minimum_periods=20,
    )
    assert statistics.passed
    assert len(points) == 23
    assert statistics.partial_label_omitted_period_count == 1
    assert statistics.blockers == ()


def _metric_records(
    fold_ordinal: int,
    fold_id: str,
) -> tuple[USR1PeriodMetricRecord, ...]:
    candidate_id = _denominator().candidates[0].candidate.candidate_id
    records: list[USR1PeriodMetricRecord] = []
    start = datetime(2026, 2, 17, tzinfo=UTC) + timedelta(days=20 * (fold_ordinal - 1))
    slices = (
        (BarInterval.MINUTE_5, 60),
        (BarInterval.MINUTE_15, 30),
        (BarInterval.MINUTE_15, 60),
        (BarInterval.MINUTE_15, 120),
        (BarInterval.MINUTE_30, 60),
    )
    for interval, horizon in slices:
        for index in range(24):
            wiggle = ((index % 5) - 2) * 0.001
            records.append(
                USR1PeriodMetricRecord(
                    candidate_id=candidate_id,
                    fold_id=fold_id,
                    fold_ordinal=fold_ordinal,
                    signal_interval=interval,
                    label_horizon_trading_minutes=horizon,
                    point=USR1PeriodMetricPoint(
                        event_time=start + timedelta(minutes=15 * index),
                        session_id=f"{fold_id}-session-{index // 4:02d}",
                        rank_ic=0.035 + wiggle,
                        long_short_return_bps=3.0 + 20.0 * wiggle,
                        one_way_turnover=0.45,
                        coverage=0.95,
                        quantile_monotonicity=0.60,
                    ),
                )
            )
    return tuple(records)


def _fold_reports_and_artifacts(
    denominator: USR1CandidateDenominator,
    fold_records: tuple[
        tuple[USR1PeriodMetricRecord, ...],
        tuple[USR1PeriodMetricRecord, ...],
        tuple[USR1PeriodMetricRecord, ...],
    ],
    *,
    blocker: str | None = None,
) -> tuple[tuple[USR1FoldStatisticsReport, ...], tuple[USR1PeriodMetricArtifact, ...]]:
    candidate_id = denominator.candidates[0].candidate.candidate_id
    policy = canonical_us_r1_statistical_evaluation_policy()
    reports: list[USR1FoldStatisticsReport] = []
    artifacts: list[USR1PeriodMetricArtifact] = []
    for index, records in enumerate(fold_records, start=1):
        slice_stats = tuple(
            USR1CandidateSliceStatistics(
                candidate_id=candidate_id,
                role=USR1ObservationRole.EVALUATION,
                signal_interval=interval,
                label_horizon_trading_minutes=horizon,
                period_count=24,
                boundary_unrealized_period_count=0,
                insufficient_cross_section_period_count=0,
                mean_raw_rank_ic=0.035,
                blockers=((blocker,) if blocker is not None and index == 1 else ()),
            )
            for interval, horizon in (
                (BarInterval.MINUTE_5, 60),
                (BarInterval.MINUTE_15, 30),
                (BarInterval.MINUTE_15, 60),
                (BarInterval.MINUTE_15, 120),
                (BarInterval.MINUTE_30, 60),
            )
        )
        artifact = USR1PeriodMetricArtifact(
            fold_id=f"fold-0{index}",
            fold_ordinal=index,
            denominator_id=denominator.denominator_id,
            evaluation_policy_id=policy.policy_id,
            row_count=len(records),
            content_sha256=(str(index) * 64),
            output_filename="us_r1_period_metrics.jsonl",
        )
        reports.append(
            USR1FoldStatisticsReport(
                fold_id=f"fold-0{index}",
                fold_ordinal=index,
                fold_materialization_manifest_id=f"materialization-0{index}",
                denominator_id=denominator.denominator_id,
                evaluation_policy_id=policy.policy_id,
                period_metric_artifact_id=artifact.artifact_id,
                candidate_slices=slice_stats,
            )
        )
        artifacts.append(artifact)
    return tuple(reports), tuple(artifacts)


def test_final_family_uses_existing_hac_bootstrap_multiplicity_and_gate() -> None:
    denominator = _denominator()
    candidate_id = denominator.candidates[0].candidate.candidate_id
    policy = canonical_us_r1_statistical_evaluation_policy()
    train_statistics = _train_statistics(candidate_id=candidate_id)
    preparation = _direction_preparation(denominator)
    direction_item = USR1CandidateDirectionEvidence(
        candidate_id=candidate_id,
        evaluation_policy_id=policy.policy_id,
        source_fold_id="fold-01",
        source_fold_manifest_id="materialization-01",
        train_statistics_id=train_statistics.statistics_id,
        train_period_count=24,
        train_mean_rank_ic=0.03,
        direction=1,
    )
    direction = USR1DirectionEvidenceSet(
        denominator_id=denominator.denominator_id,
        evaluation_policy_id=policy.policy_id,
        source_fold_id="fold-01",
        source_fold_manifest_id="materialization-01",
        candidates=(direction_item,),
    )
    fold_records = (
        _metric_records(1, "fold-01"),
        _metric_records(2, "fold-02"),
        _metric_records(3, "fold-03"),
    )
    reports, artifacts = _fold_reports_and_artifacts(denominator, fold_records)

    result = build_us_r1_final_inference_artifacts(
        denominator,
        preparation,
        direction,
        fold_records,
        reports,
        artifacts,
        research_protocol_id=canonical_us_r1_research_protocol().protocol_id,
        walk_forward_protocol_id=canonical_us_r1_walk_forward().protocol_id,
        formation_policy_id="formation-policy-test",
        evaluation_policy=policy,
        alpha_gate_policy=canonical_us_r1_alpha_gate_policy(),
        fold_materialization_manifest_ids=(
            "materialization-01",
            "materialization-02",
            "materialization-03",
        ),
    )
    assert result.family.candidates[0].holm_adjusted_pvalue <= 0.10
    assert result.family.candidates[0].bh_qvalue <= 0.10
    assert result.assessment.terminal is USR1Terminal.ROBUST_FACTOR_FAMILY
    assert result.assessment.robust_candidate_ids == (candidate_id,)
    assert result.graph.alpha_gate_assessment_id == result.assessment.assessment_id
    assert result.graph.to_dict()["alpha_authority"] is False


def test_pre_gate_technical_failure_skips_candidate_statistics_and_multiplicity() -> None:
    denominator = _denominator()
    policy = canonical_us_r1_statistical_evaluation_policy()
    blocker = "insufficient_metric_periods:0<20"
    preparation = _direction_preparation(denominator, blockers=(blocker,))
    fold_records = (
        _metric_records(1, "fold-01"),
        _metric_records(2, "fold-02"),
        _metric_records(3, "fold-03"),
    )
    reports, artifacts = _fold_reports_and_artifacts(denominator, fold_records)
    result = build_us_r1_final_inference_artifacts(
        denominator,
        preparation,
        None,
        fold_records,
        reports,
        artifacts,
        research_protocol_id=canonical_us_r1_research_protocol().protocol_id,
        walk_forward_protocol_id=canonical_us_r1_walk_forward().protocol_id,
        formation_policy_id="formation-policy-test",
        evaluation_policy=policy,
        alpha_gate_policy=canonical_us_r1_alpha_gate_policy(),
        fold_materialization_manifest_ids=(
            "materialization-01",
            "materialization-02",
            "materialization-03",
        ),
    )
    assert result.assessment.terminal is USR1Terminal.SYSTEM_FAILURE
    assert not result.family.candidates
    assert not result.assessment.candidates
    assert result.graph.direction_evidence_id is None
    assert result.graph.technical_blockers


def test_negative_review_is_gate_authoritative_but_has_no_alpha_authority() -> None:
    assessment = USR1AlphaGateAssessment(
        policy_id="policy-negative-test",
        family_evidence_id="family-negative-test",
        denominator_id="denominator-negative-test",
        terminal=USR1Terminal.NO_ROBUST_FACTOR_FAMILY,
        candidates=(
            USR1CandidateGateAssessment(
                candidate_id="candidate-negative-test",
                passed=False,
                reasons=("PRIMARY_MEAN_RANK_IC_BELOW_THRESHOLD",),
            ),
        ),
        robust_candidate_ids=(),
        technical_blockers=(),
    )
    review = finalize_us_r1_alpha_gate_review(
        assessment,
        reviewer_id="reviewer-negative-test",
        reviewed_at=datetime(2026, 9, 2, 13, 0, tzinfo=UTC),
        review_notes="Authoritative negative Alpha Gate review with no robust factor family.",
        thresholds_unchanged_attested=True,
        evidence_lineage_attested=True,
        agent_value_gate_separation_attested=True,
        execution_gate_separation_attested=True,
        live_capital_separation_attested=True,
    )
    assert review.alpha_gate_authority
    assert not review.alpha_authority
    assert not review.supports_us_x0_progression


def test_observation_file_parser_rehashes_bytes_and_candidate_identity(tmp_path) -> None:
    denominator = _denominator()
    candidate = denominator.candidates[0].candidate
    row = _observations(
        role=USR1ObservationRole.TRAIN,
        interval=BarInterval.MINUTE_15,
        horizon=60,
        periods=1,
    )[0]
    payload = (
        json.dumps(
            row.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
    path = tmp_path / "observations.jsonl"
    path.write_bytes(payload)
    artifact = USR1ObservationArtifact(
        execution_spec_id="execution-test",
        denominator_id=denominator.denominator_id,
        input_plan_id="input-plan-test",
        role=USR1ObservationRole.TRAIN,
        signal_interval=BarInterval.MINUTE_15,
        label_horizon_trading_minutes=60,
        row_count=1,
        content_sha256=hashlib.sha256(payload).hexdigest(),
        output_filename=path.name,
    )
    parsed = read_us_r1_observation_file(path, artifact, denominator)
    assert parsed == (row,)
    assert parsed[0].feature_spec_id == compile_us_r1_feature_spec(
        candidate,
        BarInterval.MINUTE_15,
    ).spec_id

    path.write_bytes(payload.replace(b"0.0005", b"0.0006"))
    with pytest.raises(ValueError, match="SHA-256"):
        read_us_r1_observation_file(path, artifact, denominator)


def test_observation_serialization_canonicalizes_equal_instants_to_utc() -> None:
    row = _observations(
        role=USR1ObservationRole.EVALUATION,
        interval=BarInterval.MINUTE_15,
        horizon=60,
        periods=1,
    )[0]
    plus_eight = timezone(timedelta(hours=8))
    shifted = replace(
        row,
        event_time=row.event_time.astimezone(plus_eight),
        feature_available_at=row.feature_available_at.astimezone(plus_eight),
        label_available_at=row.label_available_at.astimezone(
            plus_eight
        )
        if row.label_available_at
        else None,
    )
    document = shifted.to_dict()
    assert document["event_time"] == row.event_time.isoformat()
    assert document["feature_available_at"] == row.feature_available_at.isoformat()
    assert document["label_available_at"] == row.label_available_at.isoformat()


def test_turnover_is_byte_deterministic_across_python_hash_seeds() -> None:
    script = (
        "from finagent.research.us_r1_statistics import _one_way_turnover;"
        "assets={f'A{i:03d}' for i in range(200)};"
        "previous={asset:0.0 for asset in assets};"
        "current={asset:(1e16 if asset=='A000' else 1.0) for asset in assets};"
        "print(_one_way_turnover(previous,current).hex())"
    )
    results: list[str] = []
    for seed in ("1", "2", "3"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        results.append(completed.stdout.strip())
    assert len(set(results)) == 1

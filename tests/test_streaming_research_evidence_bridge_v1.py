from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.realtime.algorithm import AlgorithmRunReport
from finagent.realtime.events import BarEvent
from finagent.realtime.projections import RealtimeProjector
from finagent.realtime.streaming_research import USBaselineStreamingAlgorithm
from finagent.research.streaming_experiment_bridge import (
    StreamingExperimentLabel,
    StreamingResearchEvidenceArtifact,
    build_streaming_research_evidence_bundle,
    evaluate_streaming_b0_with_existing_runner,
    materialize_streaming_a0_observations,
    materialize_streaming_b0_observations,
    materialize_streaming_r1_candidate_observations,
    read_streaming_research_evidence_artifact,
    streaming_experiment_rows,
    write_streaming_research_evidence_artifact,
)
from finagent.research.us_agent_value_evaluation import (
    USAgentValueEvaluationDenominator,
    materialize_us_a0_observations,
)
from finagent.research.us_agent_value_gate import USAgentValueGateDecision
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_manual_candidates,
)
from finagent.research.us_baseline_evaluation import USBaselineRunSpec
from finagent.research.us_baseline_materialization import materialize_us_baseline_observations
from finagent.research.us_baselines import USBaselineProtocol, canonical_us_baseline_denominator
from finagent.research.us_r1_materialization import USR1ObservationRole
from finagent.research.us_r1_protocol import (
    USR1AgentScope,
    USR1CandidateDenominator,
    USR1CandidateProvenance,
    canonical_us_r1_research_protocol,
)

BASE = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
SYMBOLS = ("AAA", "BBB")


def _calendar() -> TradingCalendarEvidence:
    return TradingCalendarEvidence(
        market_id="XNYS",
        timezone="America/New_York",
        source="fixture-calendar",
        source_revision="streaming-bridge-v1",
        sessions=(
            TradingSession(
                session_date=date(2026, 1, 5),
                open_at=BASE,
                close_at=BASE + timedelta(minutes=300),
                is_half_day=False,
            ),
        ),
        regular_session_minutes=300,
    )


def _streaming_report(*, minutes: int = 150) -> AlgorithmRunReport:
    projector = RealtimeProjector()
    algorithm = USBaselineStreamingAlgorithm(_calendar(), required_symbols=SYMBOLS)
    outputs: list[object] = []
    sequence = 0
    for minute in range(minutes):
        event_time = BASE + timedelta(minutes=minute)
        for symbol_index, symbol in enumerate(SYMBOLS):
            base_price = (
                100.0
                + symbol_index * 40.0
                + minute * (0.08 + symbol_index * 0.02)
                + (minute % 7) * 0.01
            )
            event = BarEvent(
                source="fixture.streaming.bridge",
                source_event_id=f"{symbol}-{minute}",
                event_time=event_time,
                received_at=event_time + timedelta(minutes=1),
                sequence=sequence,
                symbol=symbol,
                interval_seconds=60,
                open=base_price,
                high=base_price + 0.7,
                low=base_price - 0.4,
                close=base_price + 0.2,
                volume=1000.0 + 25.0 * symbol_index + 3.0 * minute,
                complete=True,
            )
            sequence += 1
            projector.apply(event)
            update = algorithm.on_event(event, projector.snapshot())
            if update is not None:
                outputs.append(update)
    return AlgorithmRunReport(
        source_profile_id="fixture-streaming-profile",
        subscription_id="fixture-streaming-subscription",
        processed_event_count=sequence,
        algorithm_event_count=sequence,
        blocked_event_count=0,
        output_count=len(outputs),
        blocked_decisions=(),
        final_projection=projector.snapshot(),
        outputs=tuple(outputs),
    )


def _labels(report: AlgorithmRunReport) -> tuple[StreamingExperimentLabel, ...]:
    interval_by_seconds = {
        5 * 60: BarInterval.MINUTE_5,
        15 * 60: BarInterval.MINUTE_15,
        30 * 60: BarInterval.MINUTE_30,
    }
    horizons = {
        BarInterval.MINUTE_5: (60,),
        BarInterval.MINUTE_15: (30, 60, 120),
        BarInterval.MINUTE_30: (60,),
    }
    resampled = tuple(
        bar
        for output in report.outputs
        if hasattr(output, "resampled_bars")
        for bar in output.resampled_bars
    )
    labels: list[StreamingExperimentLabel] = []
    for item in resampled:
        interval = interval_by_seconds[item.bar.interval_seconds]
        for horizon in horizons[interval]:
            direction = 1.0 if item.bar.symbol == "BBB" else -1.0
            labels.append(
                StreamingExperimentLabel(
                    asset=item.bar.symbol,
                    session_id=item.session_id,
                    signal_interval=interval,
                    label_horizon_trading_minutes=horizon,
                    source_event_time=item.bar.event_time,
                    source_available_at=item.available_at,
                    source_price=item.bar.close,
                    label_available=True,
                    target_event_time=item.bar.event_time + timedelta(minutes=horizon),
                    target_available_at=item.available_at + timedelta(minutes=horizon),
                    label_value=direction * (0.001 + item.bar_index * 0.00001),
                )
            )
    return tuple(labels)


def _bundle(*, minutes: int = 150):
    report = _streaming_report(minutes=minutes)
    return build_streaming_research_evidence_bundle(
        report,
        required_symbols=SYMBOLS,
        labels=_labels(report),
    )


def _b0_run_spec() -> USBaselineRunSpec:
    return USBaselineRunSpec(
        certification_report_id="fixture-us-d3-certification",
        certification_outcome="CERTIFIED_FOR_RESEARCH_UNDER_LIMITATIONS",
        engineering_universe_id="fixture-engineering-universe",
        denominator_id=canonical_us_baseline_denominator().denominator_id,
        minimum_cross_section=2,
        minimum_evaluated_periods=1,
        minimum_ic_periods=1,
    )


def _a0_denominator() -> USAgentValueEvaluationDenominator:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    candidate = canonical_us_a0_manual_candidates()[8]
    return USAgentValueEvaluationDenominator(
        protocol_id=protocol.protocol_id,
        generation_run_id="fixture-a0-generation-run",
        generation_run_spec_id="fixture-a0-generation-run-spec",
        arm=USAgentValueArm.MANUAL,
        candidate_ids=(candidate.candidate_id,),
        protocol=USBaselineProtocol(),
        candidates=(candidate.compile_feature_spec(),),
    )


def _r1_denominator() -> USR1CandidateDenominator:
    candidate = canonical_us_a0_manual_candidates()[0]
    provenance = USR1CandidateProvenance(
        candidate=candidate,
        source_arms=(USAgentValueArm.MANUAL,),
        source_run_ids=("fixture-a0-run",),
    )
    return USR1CandidateDenominator(
        protocol_id=canonical_us_r1_research_protocol().protocol_id,
        a0_phase=USAgentValuePhase.PILOT,
        a0_experiment_id="fixture-a0-experiment",
        a0_gate_review_id="fixture-a0-review",
        a0_gate_decision=USAgentValueGateDecision.PILOT_DO_NOT_PROCEED_TO_FORMAL,
        agent_scope=USR1AgentScope.CONTRACTED,
        candidates=(provenance,),
    )


def test_bundle_roundtrip_is_content_addressed_and_tamper_evident(tmp_path: Path) -> None:
    bundle = _bundle(minutes=60)
    path = tmp_path / "streaming-research-evidence.json"
    artifact = write_streaming_research_evidence_artifact(bundle, path)
    restored = read_streaming_research_evidence_artifact(path, artifact)

    assert restored == bundle
    assert restored.bundle_id == bundle.bundle_id
    assert artifact.row_count == 1
    assert artifact.byte_count == path.stat().st_size

    payload = path.read_bytes()
    path.write_bytes(
        payload.replace(
            b'"research_authority":false',
            b'"research_authority":true',
            1,
        )
    )
    with pytest.raises(ValueError, match="SHA-256"):
        read_streaming_research_evidence_artifact(path, artifact)


def test_nested_content_identity_is_revalidated_even_with_rehashed_file(tmp_path: Path) -> None:
    bundle = _bundle(minutes=60)
    path = tmp_path / "streaming-research-evidence.json"
    artifact = write_streaming_research_evidence_artifact(bundle, path)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["resampled_bars"][0]["coverage_ratio"] = 0.5
    payload = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    path.write_bytes(payload)
    rehashed = StreamingResearchEvidenceArtifact(
        bundle_id=artifact.bundle_id,
        row_count=1,
        byte_count=len(payload),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        output_filename=path.name,
    )
    with pytest.raises(ValueError, match="coverage_ratio|content mismatch"):
        read_streaming_research_evidence_artifact(path, rehashed)


def test_conflicting_label_semantic_identity_fails_closed() -> None:
    report = _streaming_report(minutes=60)
    labels = list(_labels(report))
    labels.append(
        replace(
            labels[0],
            label_value=float(labels[0].label_value or 0.0) + 0.1,
        )
    )
    with pytest.raises(ValueError, match="conflicting streaming labels"):
        build_streaming_research_evidence_bundle(
            report,
            required_symbols=SYMBOLS,
            labels=labels,
        )


def test_b0_direct_bridge_matches_existing_batch_materializer_without_feature_recompute() -> None:
    bundle = _bundle()
    run_spec = _b0_run_spec()
    direct, direct_diagnostics = materialize_streaming_b0_observations(bundle, run_spec)

    rows = streaming_experiment_rows(
        bundle,
        signal_interval=BarInterval.MINUTE_15,
        label_horizon_trading_minutes=60,
    )
    recomputed, recomputed_diagnostics = materialize_us_baseline_observations(
        rows,
        canonical_us_baseline_denominator(),
        expected_assets=SYMBOLS,
    )

    assert direct == recomputed
    assert direct_diagnostics == recomputed_diagnostics
    assert direct_diagnostics.passed
    report, diagnostics = evaluate_streaming_b0_with_existing_runner(bundle, run_spec)
    assert diagnostics == direct_diagnostics
    assert report.run_spec.spec_id == run_spec.spec_id
    assert report.denominator_id == bundle.denominator_id
    assert len(report.candidates) == len(canonical_us_baseline_denominator().candidates)


def test_missing_b0_label_anchor_is_explicit_blocker() -> None:
    report = _streaming_report(minutes=60)
    labels = list(_labels(report))
    removed = next(
        item
        for item in labels
        if item.signal_interval is BarInterval.MINUTE_15
        and item.label_horizon_trading_minutes == 60
    )
    labels.remove(removed)
    bundle = build_streaming_research_evidence_bundle(
        report,
        required_symbols=SYMBOLS,
        labels=labels,
    )
    _, diagnostics = materialize_streaming_b0_observations(bundle, _b0_run_spec())
    assert not diagnostics.passed
    assert diagnostics.label_anchor_missing_count == 1
    assert any("label_anchor_missing" in item for item in diagnostics.blockers)


def test_a0_bridge_delegates_to_existing_shared_materializer() -> None:
    bundle = _bundle()
    denominator = _a0_denominator()
    bridged, bridged_diagnostics = materialize_streaming_a0_observations(
        bundle,
        denominator,
    )
    rows = streaming_experiment_rows(
        bundle,
        signal_interval=BarInterval.MINUTE_15,
        label_horizon_trading_minutes=60,
    )
    direct, direct_diagnostics = materialize_us_a0_observations(
        rows,
        denominator,
        expected_assets=SYMBOLS,
    )
    assert bridged == direct
    assert bridged_diagnostics == direct_diagnostics
    assert bridged_diagnostics.passed
    compiled = denominator.candidates[0]
    assert tuple(bridged) == (compiled.feature_id,)
    assert any(item.feature_value is not None for item in bridged[compiled.feature_id])


def test_r1_bridge_delegates_frequency_and_horizon_slices_to_existing_materializer() -> None:
    bundle = _bundle()
    denominator = _r1_denominator()

    evaluation, evaluation_diagnostics = materialize_streaming_r1_candidate_observations(
        bundle,
        denominator,
        role=USR1ObservationRole.EVALUATION,
        signal_interval=BarInterval.MINUTE_5,
        label_horizon_trading_minutes=60,
    )
    assert evaluation_diagnostics.passed
    assert evaluation
    assert {item.signal_interval for item in evaluation} == {BarInterval.MINUTE_5}
    assert {item.label_horizon_trading_minutes for item in evaluation} == {60}
    assert {item.candidate_id for item in evaluation} == {
        denominator.candidates[0].candidate.candidate_id
    }

    training, training_diagnostics = materialize_streaming_r1_candidate_observations(
        bundle,
        denominator,
        role=USR1ObservationRole.TRAIN,
        signal_interval=BarInterval.MINUTE_15,
        label_horizon_trading_minutes=60,
    )
    assert training_diagnostics.passed
    assert training

    with pytest.raises(ValueError, match="unsupported R1"):
        materialize_streaming_r1_candidate_observations(
            bundle,
            denominator,
            role=USR1ObservationRole.EVALUATION,
            signal_interval=BarInterval.MINUTE_5,
            label_horizon_trading_minutes=30,
        )


def test_experiment_bundle_rejects_partial_feature_denominator() -> None:
    report = _streaming_report(minutes=60)
    outputs = list(report.outputs)
    removal_index = next(
        index
        for index, output in enumerate(outputs)
        if hasattr(output, "feature_snapshots")
        and output.feature_snapshots
        and output.feature_snapshots[0].symbol == "AAA"
    )
    del outputs[removal_index]
    partial_report = AlgorithmRunReport(
        source_profile_id=report.source_profile_id,
        subscription_id=report.subscription_id,
        processed_event_count=report.processed_event_count,
        algorithm_event_count=report.algorithm_event_count,
        blocked_event_count=0,
        output_count=len(outputs),
        blocked_decisions=(),
        final_projection=report.final_projection,
        outputs=tuple(outputs),
    )
    with pytest.raises(ValueError, match="partial|missing persisted feature"):
        build_streaming_research_evidence_bundle(
            partial_report,
            required_symbols=SYMBOLS,
            labels=_labels(report),
        )


def test_run_without_streaming_research_outputs_cannot_be_promoted_to_experiment_evidence() -> None:
    report = AlgorithmRunReport(
        source_profile_id="fixture-delayed-profile",
        subscription_id="fixture-delayed-subscription",
        processed_event_count=0,
        algorithm_event_count=0,
        blocked_event_count=0,
        output_count=0,
        blocked_decisions=(),
        final_projection=RealtimeProjector().snapshot(),
        outputs=(),
    )
    with pytest.raises(ValueError, match="no streaming research outputs"):
        build_streaming_research_evidence_bundle(
            report,
            required_symbols=SYMBOLS,
            labels=(),
        )

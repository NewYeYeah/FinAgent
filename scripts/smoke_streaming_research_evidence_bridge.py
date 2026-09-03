from __future__ import annotations

import json
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.realtime.algorithm import AlgorithmRunReport
from finagent.realtime.events import BarEvent
from finagent.realtime.projections import RealtimeProjector
from finagent.realtime.streaming_research import (
    StreamingResearchUpdate,
    USBaselineStreamingAlgorithm,
)
from finagent.research.streaming_experiment_bridge import (
    StreamingExperimentLabel,
    build_streaming_research_evidence_bundle,
    materialize_streaming_a0_observations,
    materialize_streaming_b0_observations,
    materialize_streaming_r1_candidate_observations,
    read_streaming_research_evidence_artifact,
    write_streaming_research_evidence_artifact,
)
from finagent.research.us_agent_value_evaluation import USAgentValueEvaluationDenominator
from finagent.research.us_agent_value_gate import USAgentValueGateDecision
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_manual_candidates,
)
from finagent.research.us_baseline_evaluation import USBaselineRunSpec
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
        source_revision="streaming-experiment-bridge-smoke-v1",
        sessions=(
            TradingSession(
                session_date=date(2026, 1, 5),
                open_at=BASE,
                close_at=BASE + timedelta(minutes=180),
                is_half_day=False,
            ),
        ),
        regular_session_minutes=180,
    )


def _report() -> AlgorithmRunReport:
    projector = RealtimeProjector()
    algorithm = USBaselineStreamingAlgorithm(_calendar(), required_symbols=SYMBOLS)
    outputs: list[object] = []
    sequence = 0
    for minute in range(60):
        event_time = BASE + timedelta(minutes=minute)
        for symbol_index, symbol in enumerate(SYMBOLS):
            price = 100.0 + symbol_index * 50.0 + minute * (0.1 + 0.03 * symbol_index)
            event = BarEvent(
                source="fixture.streaming.experiment",
                source_event_id=f"{symbol}-{minute}",
                event_time=event_time,
                received_at=event_time + timedelta(minutes=1),
                sequence=sequence,
                symbol=symbol,
                interval_seconds=60,
                open=price,
                high=price + 0.8,
                low=price - 0.5,
                close=price + 0.25,
                volume=1000.0 + 20.0 * symbol_index + minute,
                complete=True,
            )
            sequence += 1
            projector.apply(event)
            update = algorithm.on_event(event, projector.snapshot())
            if update is not None:
                outputs.append(update)
    return AlgorithmRunReport(
        source_profile_id="fixture-streaming-experiment-profile",
        subscription_id="fixture-streaming-experiment-subscription",
        processed_event_count=sequence,
        algorithm_event_count=sequence,
        blocked_event_count=0,
        output_count=len(outputs),
        blocked_decisions=(),
        final_projection=projector.snapshot(),
        outputs=tuple(outputs),
    )


def _labels(report: AlgorithmRunReport) -> tuple[StreamingExperimentLabel, ...]:
    intervals = {
        300: BarInterval.MINUTE_5,
        900: BarInterval.MINUTE_15,
        1800: BarInterval.MINUTE_30,
    }
    horizons = {
        BarInterval.MINUTE_5: (60,),
        BarInterval.MINUTE_15: (30, 60, 120),
        BarInterval.MINUTE_30: (60,),
    }
    labels: list[StreamingExperimentLabel] = []
    for output in report.outputs:
        if not isinstance(output, StreamingResearchUpdate):
            continue
        for item in output.resampled_bars:
            interval = intervals[item.bar.interval_seconds]
            for horizon in horizons[interval]:
                sign = -1.0 if item.bar.symbol == "AAA" else 1.0
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
                        label_value=sign * (0.001 + item.bar_index * 0.00001),
                    )
                )
    return tuple(labels)


def _a0_denominator() -> USAgentValueEvaluationDenominator:
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    candidate = canonical_us_a0_manual_candidates()[7]
    return USAgentValueEvaluationDenominator(
        protocol_id=protocol.protocol_id,
        generation_run_id="fixture-a0-generation-run",
        generation_run_spec_id="fixture-a0-generation-spec",
        arm=USAgentValueArm.MANUAL,
        candidate_ids=(candidate.candidate_id,),
        protocol=USBaselineProtocol(),
        candidates=(candidate.compile_feature_spec(),),
    )


def _r1_denominator() -> USR1CandidateDenominator:
    candidate = canonical_us_a0_manual_candidates()[7]
    return USR1CandidateDenominator(
        protocol_id=canonical_us_r1_research_protocol().protocol_id,
        a0_phase=USAgentValuePhase.PILOT,
        a0_experiment_id="fixture-a0-experiment",
        a0_gate_review_id="fixture-a0-review",
        a0_gate_decision=USAgentValueGateDecision.PILOT_DO_NOT_PROCEED_TO_FORMAL,
        agent_scope=USR1AgentScope.CONTRACTED,
        candidates=(
            USR1CandidateProvenance(
                candidate=candidate,
                source_arms=(USAgentValueArm.MANUAL,),
                source_run_ids=("fixture-a0-run",),
            ),
        ),
    )


def _run() -> dict[str, object]:
    source_report = _report()
    bundle = build_streaming_research_evidence_bundle(
        source_report,
        required_symbols=SYMBOLS,
        labels=_labels(source_report),
    )
    run_spec = USBaselineRunSpec(
        certification_report_id="fixture-us-d3-certification",
        certification_outcome="CERTIFIED_FOR_RESEARCH_UNDER_LIMITATIONS",
        engineering_universe_id="fixture-engineering-universe",
        denominator_id=canonical_us_baseline_denominator().denominator_id,
        minimum_cross_section=2,
        minimum_evaluated_periods=1,
        minimum_ic_periods=1,
    )
    b0, b0_diagnostics = materialize_streaming_b0_observations(bundle, run_spec)
    a0_denominator = _a0_denominator()
    a0, a0_diagnostics = materialize_streaming_a0_observations(bundle, a0_denominator)
    r1_denominator = _r1_denominator()
    r1, r1_diagnostics = materialize_streaming_r1_candidate_observations(
        bundle,
        r1_denominator,
        role=USR1ObservationRole.EVALUATION,
        signal_interval=BarInterval.MINUTE_5,
        label_horizon_trading_minutes=60,
    )
    with tempfile.TemporaryDirectory(prefix="finagent-stream-evidence-") as raw:
        path = Path(raw) / "streaming-research-evidence.json"
        artifact = write_streaming_research_evidence_artifact(bundle, path)
        restored = read_streaming_research_evidence_artifact(path, artifact)
    return {
        "schema_version": "finagent.streaming-research-evidence-bridge-smoke.v1",
        "source_run_report_id": source_report.report_id,
        "bundle_id": bundle.bundle_id,
        "artifact_id": artifact.artifact_id,
        "artifact_sha256": artifact.content_sha256,
        "roundtrip_identity_equal": restored.bundle_id == bundle.bundle_id,
        "resampled_bar_count": len(bundle.resampled_bars),
        "feature_snapshot_count": len(bundle.feature_snapshots),
        "cross_section_snapshot_count": len(bundle.cross_section_snapshots),
        "label_count": len(bundle.labels),
        "b0_denominator_id": bundle.denominator_id,
        "b0_observation_count": sum(len(rows) for rows in b0.values()),
        "b0_diagnostics_passed": b0_diagnostics.passed,
        "a0_denominator_id": a0_denominator.denominator_id,
        "a0_observation_count": sum(len(rows) for rows in a0.values()),
        "a0_diagnostics_passed": a0_diagnostics.passed,
        "r1_denominator_id": r1_denominator.denominator_id,
        "r1_observation_count": len(r1),
        "r1_diagnostics_passed": r1_diagnostics.passed,
        "feature_authority_recomputed": False,
        "statistical_authority_recomputed": False,
        "research_authority": False,
        "agent_value_gate_authority": False,
        "alpha_authority": False,
        "execution_authority": False,
        "stage_exit_authority": False,
    }


def main() -> int:
    result = _run()
    print(json.dumps(result, sort_keys=True, indent=2))
    expected = {
        "roundtrip_identity_equal": True,
        "resampled_bar_count": 36,
        "feature_snapshot_count": 8,
        "cross_section_snapshot_count": 4,
        "label_count": 52,
        "b0_observation_count": 64,
        "b0_diagnostics_passed": True,
        "a0_observation_count": 8,
        "a0_diagnostics_passed": True,
        "r1_observation_count": 24,
        "r1_diagnostics_passed": True,
    }
    if any(result[key] != value for key, value in expected.items()):
        return 2
    if any(
        result[key] is not False
        for key in (
            "feature_authority_recomputed",
            "statistical_authority_recomputed",
            "research_authority",
            "agent_value_gate_authority",
            "alpha_authority",
            "execution_authority",
            "stage_exit_authority",
        )
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

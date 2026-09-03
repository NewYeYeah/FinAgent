from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb

from finagent.data.minute_store import DuckDBParquetMinuteStore, manifest_from_directory
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.research.replay_experiment_campaign import (
    ReplayCampaignSourceScope,
    ReplayExperimentCampaignSpec,
    run_replay_experiment_campaign,
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
from finagent.research.us_r1_protocol import (
    USR1AgentScope,
    USR1CandidateDenominator,
    USR1CandidateProvenance,
    canonical_us_r1_research_protocol,
)

BASE = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
SYMBOLS = ("AAA", "BBB")
MINUTES = 300


def _calendar() -> TradingCalendarEvidence:
    return TradingCalendarEvidence(
        market_id="XNYS",
        timezone="America/New_York",
        source="fixture-calendar",
        source_revision="replay-experiment-campaign-smoke-v1",
        sessions=(
            TradingSession(
                session_date=date(2026, 1, 5),
                open_at=BASE,
                close_at=BASE + timedelta(minutes=MINUTES),
                is_half_day=False,
            ),
        ),
        regular_session_minutes=MINUTES,
    )


def _store(root: Path) -> DuckDBParquetMinuteStore:
    data_dir = root / "minute"
    data_dir.mkdir(parents=True)
    output = data_dir / "ohlcv_2026-01.parquet"
    rows: list[tuple[object, ...]] = []
    for minute in range(MINUTES):
        for symbol_index, symbol in enumerate(SYMBOLS):
            price = (
                100.0
                + symbol_index * 40.0
                + minute * (0.07 + symbol_index * 0.02)
                + (minute % 11) * 0.01
            )
            rows.append(
                (
                    BASE + timedelta(minutes=minute),
                    price,
                    price + 0.8,
                    price - 0.5,
                    price + 0.2,
                    1000.0 + minute * 3.0 + symbol_index * 50.0,
                    symbol,
                )
            )
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE bars (
                timestamp TIMESTAMPTZ,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                ticker VARCHAR
            )
            """
        )
        connection.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        connection.execute(f"COPY bars TO '{output.as_posix()}' (FORMAT PARQUET)")
    finally:
        connection.close()
    return DuckDBParquetMinuteStore(
        manifest_from_directory(
            data_dir,
            source_id="fixture-us-minute",
            source_revision="fixture-replay-campaign-smoke-v1",
            cleaning_identity="fixture-cleaning",
            inventory_id="fixture-inventory",
        )
    )


def _b0_run_spec() -> USBaselineRunSpec:
    return USBaselineRunSpec(
        certification_report_id="engineering-replay-parity-not-us-d3",
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
        generation_run_id="fixture-replay-campaign-a0",
        generation_run_spec_id="fixture-replay-campaign-a0-spec",
        arm=USAgentValueArm.MANUAL,
        candidate_ids=(candidate.candidate_id,),
        protocol=USBaselineProtocol(),
        candidates=(candidate.compile_feature_spec(),),
    )


def _r1_denominator() -> USR1CandidateDenominator:
    candidate = canonical_us_a0_manual_candidates()[0]
    return USR1CandidateDenominator(
        protocol_id=canonical_us_r1_research_protocol().protocol_id,
        a0_phase=USAgentValuePhase.PILOT,
        a0_experiment_id="fixture-replay-campaign-a0",
        a0_gate_review_id="fixture-replay-campaign-review",
        a0_gate_decision=USAgentValueGateDecision.PILOT_DO_NOT_PROCEED_TO_FORMAL,
        agent_scope=USR1AgentScope.CONTRACTED,
        candidates=(
            USR1CandidateProvenance(
                candidate=candidate,
                source_arms=(USAgentValueArm.MANUAL,),
                source_run_ids=("fixture-replay-campaign-a0-run",),
            ),
        ),
    )


def _run() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="finagent-replay-campaign-") as raw:
        store = _store(Path(raw))
        spec = ReplayExperimentCampaignSpec(
            source_scope=ReplayCampaignSourceScope.FIXTURE,
            required_symbols=SYMBOLS,
            event_start=BASE,
            event_end=BASE + timedelta(minutes=MINUTES),
        )
        report = asyncio.run(
            run_replay_experiment_campaign(
                store,
                _calendar(),
                spec=spec,
                b0_run_spec=_b0_run_spec(),
                a0_denominator=_a0_denominator(),
                r1_denominator=_r1_denominator(),
            )
        )
    return {
        "schema_version": "finagent.replay-experiment-campaign-smoke.v1",
        "report_id": report.report_id,
        "spec_id": report.spec.spec_id,
        "source_manifest_id": report.source_manifest_id,
        "source_run_report_id": report.source_run_report_id,
        "streaming_bundle_id": report.streaming_bundle_id,
        "b0_run_spec_id": report.b0_run_spec_id,
        "b0_denominator_id": report.b0_denominator_id,
        "a0_denominator_id": report.a0_denominator_id,
        "r1_denominator_id": report.r1_denominator_id,
        "batch_slice_ids": [item.slice_id for item in report.batch_slices],
        "batch_slice_row_counts": [item.row_count for item in report.batch_slices],
        "parity_check_count": len(report.parity_checks),
        "parity_check_ids": [item.check_id for item in report.parity_checks],
        "all_parity_equal": all(item.equal for item in report.parity_checks),
        "passed": report.passed,
        "blockers": list(report.blockers),
        "certification_authority": False,
        "research_authority": False,
        "agent_value_gate_authority": False,
        "alpha_authority": False,
        "execution_authority": False,
        "stage_exit_authority": False,
    }


def main() -> int:
    result = _run()
    print(json.dumps(result, sort_keys=True, indent=2))
    if result["passed"] is not True or result["all_parity_equal"] is not True:
        return 2
    if result["parity_check_count"] != 16:
        return 2
    if result["batch_slice_row_counts"] != [120, 40, 40, 40, 20]:
        return 2
    for field_name in (
        "certification_authority",
        "research_authority",
        "agent_value_gate_authority",
        "alpha_authority",
        "execution_authority",
        "stage_exit_authority",
    ):
        if result[field_name] is not False:
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from finagent.data.minute_store import DuckDBParquetMinuteStore, manifest_from_directory
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.research.replay_experiment_campaign import (
    ReplayCampaignSourceScope,
    ReplayExperimentCampaignSpec,
    run_replay_experiment_campaign,
    write_replay_experiment_campaign_report,
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
        source_revision="replay-experiment-campaign-v1",
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
            source_revision="fixture-replay-campaign",
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


def _spec(*, maximum_batch_rows: int = 100_000) -> ReplayExperimentCampaignSpec:
    return ReplayExperimentCampaignSpec(
        source_scope=ReplayCampaignSourceScope.FIXTURE,
        required_symbols=SYMBOLS,
        event_start=BASE,
        event_end=BASE + timedelta(minutes=MINUTES),
        maximum_batch_rows=maximum_batch_rows,
    )


def test_replay_campaign_proves_exact_streaming_batch_parity(tmp_path: Path) -> None:
    report = asyncio.run(
        run_replay_experiment_campaign(
            _store(tmp_path),
            _calendar(),
            spec=_spec(),
            b0_run_spec=_b0_run_spec(),
            a0_denominator=_a0_denominator(),
            r1_denominator=_r1_denominator(),
        )
    )

    assert report.passed
    assert report.blockers == ()
    assert len(report.batch_slices) == 5
    assert len(report.parity_checks) == 16
    assert all(item.equal for item in report.parity_checks)
    assert {item.surface for item in report.parity_checks} == {
        "rows:5m:60m",
        "rows:15m:30m",
        "rows:15m:60m",
        "rows:15m:120m",
        "rows:30m:60m",
        "b0:observations",
        "b0:materialization-diagnostics",
        "b0:evaluation",
        "a0:observations",
        "a0:materialization-diagnostics",
        "r1:TRAIN:15m:60m",
        "r1:EVALUATION:5m:60m",
        "r1:EVALUATION:15m:30m",
        "r1:EVALUATION:15m:60m",
        "r1:EVALUATION:15m:120m",
        "r1:EVALUATION:30m:60m",
    }
    document = report.to_dict()
    assert document["engineering_only"] is True
    assert document["formal_us_b0_operator_invoked"] is False
    assert document["us_d3_certification_consumed"] is False
    assert document["certification_authority"] is False
    assert document["research_authority"] is False
    assert document["agent_value_gate_authority"] is False
    assert document["alpha_authority"] is False
    assert document["execution_authority"] is False
    assert document["stage_exit_authority"] is False


def test_campaign_report_is_content_addressed_and_write_once_by_default(tmp_path: Path) -> None:
    report = asyncio.run(
        run_replay_experiment_campaign(
            _store(tmp_path),
            _calendar(),
            spec=_spec(),
            b0_run_spec=_b0_run_spec(),
            a0_denominator=_a0_denominator(),
            r1_denominator=_r1_denominator(),
        )
    )
    output = tmp_path / "campaign.json"
    written = write_replay_experiment_campaign_report(report, output)
    loaded = json.loads(written.read_text(encoding="utf-8"))

    assert loaded["report_id"] == report.report_id
    assert loaded["passed"] is True
    with pytest.raises(FileExistsError):
        write_replay_experiment_campaign_report(report, output)


def test_campaign_fails_closed_before_truncating_batch_materialization(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="maximum_batch_rows"):
        asyncio.run(
            run_replay_experiment_campaign(
                _store(tmp_path),
                _calendar(),
                spec=_spec(maximum_batch_rows=10),
                b0_run_spec=_b0_run_spec(),
                a0_denominator=_a0_denominator(),
                r1_denominator=_r1_denominator(),
            )
        )


def test_campaign_rejects_noncanonical_b0_denominator(tmp_path: Path) -> None:
    invalid = USBaselineRunSpec(
        certification_report_id="engineering-replay-parity-not-us-d3",
        certification_outcome="CERTIFIED_FOR_RESEARCH_UNDER_LIMITATIONS",
        engineering_universe_id="fixture-engineering-universe",
        denominator_id="not-the-canonical-denominator",
        minimum_cross_section=2,
        minimum_evaluated_periods=1,
        minimum_ic_periods=1,
    )
    with pytest.raises(ValueError, match="canonical B0 denominator"):
        asyncio.run(
            run_replay_experiment_campaign(
                _store(tmp_path),
                _calendar(),
                spec=_spec(),
                b0_run_spec=invalid,
                a0_denominator=_a0_denominator(),
                r1_denominator=_r1_denominator(),
            )
        )

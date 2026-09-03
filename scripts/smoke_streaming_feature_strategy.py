from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb

from finagent.data.minute_store import DuckDBParquetMinuteStore, manifest_from_directory
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.realtime import (
    AlgorithmRunner,
    DatabaseReplaySource,
    FeedTimingClass,
    FeedTimingProfile,
    MarketDataSubscription,
    RealtimeEventKind,
    ReplayPacingMode,
    StrategyFreshnessBudget,
    StreamingResearchUpdate,
    USBaselineStreamingAlgorithm,
)
from finagent.research.us_baselines import canonical_us_baseline_denominator

BASE = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
SYMBOLS = ("AAA", "BBB")


def _fixture_store(root: Path) -> DuckDBParquetMinuteStore:
    data_dir = root / "minute"
    data_dir.mkdir()
    output = data_dir / "ohlcv_2026-01.parquet"
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
        rows: list[tuple[object, ...]] = []
        for minute in range(30):
            for symbol_index, symbol in enumerate(SYMBOLS):
                base_price = 100.0 + symbol_index * 100.0 + minute * 0.25
                rows.append(
                    (
                        BASE + timedelta(minutes=minute),
                        base_price,
                        base_price + 1.0,
                        base_price - 0.5,
                        base_price + 0.4,
                        1000.0 + minute * 10.0 + symbol_index * 100.0,
                        symbol,
                    )
                )
        connection.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        connection.execute(f"COPY bars TO '{output.as_posix()}' (FORMAT PARQUET)")
    finally:
        connection.close()
    return DuckDBParquetMinuteStore(
        manifest_from_directory(
            data_dir,
            source_id="fixture-us-minute",
            source_revision="fixture-revision",
            cleaning_identity="fixture-cleaning",
            inventory_id="fixture-inventory",
        )
    )


def _calendar() -> TradingCalendarEvidence:
    return TradingCalendarEvidence(
        market_id="XNYS",
        timezone="America/New_York",
        source="fixture-calendar",
        source_revision="fixture-calendar-v1",
        sessions=(
            TradingSession(
                session_date=date(2026, 1, 5),
                open_at=BASE,
                close_at=BASE + timedelta(minutes=30),
                is_half_day=False,
            ),
        ),
        regular_session_minutes=30,
    )


def _subscription() -> MarketDataSubscription:
    return MarketDataSubscription(
        symbols=SYMBOLS,
        event_kinds=(RealtimeEventKind.BAR,),
        start=BASE + timedelta(minutes=1),
        end=BASE + timedelta(minutes=31),
        interval_seconds=60,
        pacing_mode=ReplayPacingMode.FAST,
    )


def _updates(outputs: tuple[object, ...]) -> tuple[StreamingResearchUpdate, ...]:
    return tuple(item for item in outputs if isinstance(item, StreamingResearchUpdate))


async def _run(store: DuckDBParquetMinuteStore) -> dict[str, object]:
    calendar = _calendar()
    replay_algorithm = USBaselineStreamingAlgorithm(calendar, required_symbols=SYMBOLS)
    replay_report = await AlgorithmRunner().run(
        DatabaseReplaySource(store),
        _subscription(),
        replay_algorithm,
        freshness_budget=StrategyFreshnessBudget(
            maximum_source_delay_seconds=60.0,
            maximum_event_age_seconds=120.0,
            allow_replay=True,
        ),
    )
    replay_updates = _updates(replay_report.outputs)
    resampled = tuple(item for update in replay_updates for item in update.resampled_bars)
    features = tuple(item for update in replay_updates for item in update.feature_snapshots)
    cross_sections = tuple(
        item for update in replay_updates for item in update.cross_section_snapshots
    )

    delayed_source = DatabaseReplaySource(
        store,
        timing_profile=FeedTimingProfile(
            source_id="fixture.delayed.us",
            timing_class=FeedTimingClass.DELAYED,
            progressing=True,
            observed_delay_seconds=900.0,
            freshness_policy_id="fixture-delay-policy",
        ),
    )
    delayed_report = await AlgorithmRunner().run(
        delayed_source,
        _subscription(),
        USBaselineStreamingAlgorithm(calendar, required_symbols=SYMBOLS),
        freshness_budget=StrategyFreshnessBudget(
            maximum_source_delay_seconds=60.0,
            maximum_event_age_seconds=120.0,
            allow_delayed=True,
        ),
    )
    denominator = canonical_us_baseline_denominator()
    return {
        "schema_version": "finagent.streaming-feature-strategy-smoke.v1",
        "replay_run_id": replay_report.report_id,
        "replay_semantic_state_id": replay_report.final_projection.semantic_state_id,
        "processed_event_count": replay_report.processed_event_count,
        "resampled_bar_count": len(resampled),
        "resampled_5m_count": sum(item.bar.interval_seconds == 300 for item in resampled),
        "resampled_15m_count": sum(item.bar.interval_seconds == 900 for item in resampled),
        "resampled_30m_count": sum(item.bar.interval_seconds == 1800 for item in resampled),
        "feature_snapshot_count": len(features),
        "cross_section_snapshot_count": len(cross_sections),
        "b0_denominator_id": denominator.denominator_id,
        "streaming_denominator_id": replay_algorithm.feature_engine.denominator.denominator_id,
        "delayed_run_id": delayed_report.report_id,
        "delayed_blocked_event_count": delayed_report.blocked_event_count,
        "delayed_algorithm_event_count": delayed_report.algorithm_event_count,
        "delayed_source_still_projected": bool(delayed_report.final_projection.bars),
        "provider_neutral": True,
        "research_authority": False,
        "alpha_authority": False,
        "execution_authority": False,
        "stage_exit_authority": False,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="finagent-stream-feature-") as raw:
        result = asyncio.run(_run(_fixture_store(Path(raw))))
    print(json.dumps(result, sort_keys=True, indent=2))
    required = {
        "processed_event_count": 60,
        "resampled_bar_count": 18,
        "resampled_5m_count": 12,
        "resampled_15m_count": 4,
        "resampled_30m_count": 2,
        "feature_snapshot_count": 4,
        "cross_section_snapshot_count": 2,
        "delayed_blocked_event_count": 60,
        "delayed_algorithm_event_count": 0,
    }
    if any(result[key] != value for key, value in required.items()):
        return 2
    if result["b0_denominator_id"] != result["streaming_denominator_id"]:
        return 2
    if result["delayed_source_still_projected"] is not True:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

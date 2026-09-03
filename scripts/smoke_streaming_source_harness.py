from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from finagent.data.minute_store import DuckDBParquetMinuteStore, manifest_from_directory
from finagent.realtime import (
    AlgorithmRunner,
    CanonicalRealtimeEvent,
    DatabaseReplaySource,
    FeedTimingClass,
    FeedTimingProfile,
    MarketDataSubscription,
    RealtimeEventKind,
    ReplayPacingMode,
    StrategyFreshnessBudget,
)

BASE = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)


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
        connection.executemany(
            "INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (BASE, 100.0, 101.0, 99.0, 100.5, 1000.0, "AAA"),
                (BASE, 200.0, 201.0, 199.0, 200.5, 2000.0, "BBB"),
                (BASE + timedelta(minutes=1), 100.5, 102.0, 100.0, 101.5, 1100.0, "AAA"),
                (BASE + timedelta(minutes=1), 200.5, 202.0, 200.0, 201.5, 2100.0, "BBB"),
            ],
        )
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


class _Recorder:
    def on_event(self, event: CanonicalRealtimeEvent, state: object) -> object:
        del state
        return event.event_id


async def _run(store: DuckDBParquetMinuteStore) -> dict[str, object]:
    subscription = MarketDataSubscription(
        symbols=("AAA", "BBB"),
        event_kinds=(RealtimeEventKind.BAR,),
        start=BASE + timedelta(minutes=1),
        end=BASE + timedelta(minutes=3),
        interval_seconds=60,
        pacing_mode=ReplayPacingMode.FAST,
    )
    replay = DatabaseReplaySource(store)
    replay_report = await AlgorithmRunner().run(
        replay,
        subscription,
        _Recorder(),
        freshness_budget=StrategyFreshnessBudget(
            maximum_source_delay_seconds=60.0,
            maximum_event_age_seconds=120.0,
            allow_replay=True,
        ),
    )

    delayed = DatabaseReplaySource(
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
        delayed,
        subscription,
        _Recorder(),
        freshness_budget=StrategyFreshnessBudget(
            maximum_source_delay_seconds=60.0,
            maximum_event_age_seconds=120.0,
            allow_delayed=True,
        ),
    )
    first_blocked = delayed_report.blocked_decisions[0]
    return {
        "schema_version": "finagent.streaming-source-harness-smoke.v1",
        "replay_profile_id": replay.timing_profile.profile_id,
        "replay_run_id": replay_report.report_id,
        "replay_processed_event_count": replay_report.processed_event_count,
        "replay_algorithm_event_count": replay_report.algorithm_event_count,
        "replay_semantic_state_id": replay_report.final_projection.semantic_state_id,
        "delayed_profile_id": delayed.timing_profile.profile_id,
        "delayed_run_id": delayed_report.report_id,
        "delayed_processed_event_count": delayed_report.processed_event_count,
        "delayed_blocked_event_count": delayed_report.blocked_event_count,
        "delayed_first_event_age_seconds": first_blocked.event_age_seconds,
        "delayed_reasons": list(first_blocked.reasons),
        "database_replay_bar_only": True,
        "provider_neutral_algorithm_boundary": True,
        "market_data_authority": False,
        "execution_authority": False,
        "stage_exit_authority": False,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="finagent-streaming-source-") as raw:
        store = _fixture_store(Path(raw))
        result = asyncio.run(_run(store))
    print(json.dumps(result, sort_keys=True, indent=2))
    if result["replay_processed_event_count"] != 4:
        return 2
    if result["replay_algorithm_event_count"] != 4:
        return 2
    if result["delayed_blocked_event_count"] != 4:
        return 2
    if "freshness:source_delay_exceeded" not in result["delayed_reasons"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from finagent.data.minute_store import DuckDBExecutionPolicy
from finagent.data.us_minute import (
    HuggingFaceSnapshotLayout,
    inventory_monthly_parquet,
)
from finagent.data.us_universe_candidates import (
    USUniverseCandidateSelectionPolicy,
    select_us_universe_candidates,
)
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession

REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"
CLEANING_ID = "us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244"


def _dt(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, minute, tzinfo=UTC)


def _calendar() -> TradingCalendarEvidence:
    sessions = tuple(
        TradingSession(
            session_date=date(2026, 1, day),
            open_at=_dt(day, 14, 30),
            close_at=_dt(day, 14, 40),
        )
        for day in (2, 5, 6)
    )
    return TradingCalendarEvidence(
        market_id="XNYS",
        timezone="America/New_York",
        source="synthetic-calendar:XNYS",
        source_revision="synthetic-v1",
        sessions=sessions,
        regular_session_minutes=10,
    )


def _snapshot(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "datasets--mito0o852--OHLCV-1m"
    snapshot = root / "snapshots" / REVISION
    data_dir = snapshot / "data"
    data_dir.mkdir(parents=True)
    (root / "refs").mkdir(parents=True)
    (root / "refs" / "main").write_text(REVISION + "\n", encoding="utf-8")
    (snapshot / "README.md").write_text("synthetic fixture\n", encoding="utf-8")

    rows: list[tuple[object, ...]] = []
    for day in (2, 5, 6):
        start = _dt(day, 14, 30)
        for minute in range(10):
            timestamp = start + timedelta(minutes=minute)
            rows.append(
                (
                    timestamp,
                    10.0 + minute * 0.01,
                    10.1 + minute * 0.01,
                    9.9 + minute * 0.01,
                    10.05 + minute * 0.01,
                    1000.0 + minute,
                    "AAA",
                )
            )
            if minute != 4:
                rows.append(
                    (
                        timestamp,
                        20.0 + minute * 0.01,
                        20.1 + minute * 0.01,
                        19.9 + minute * 0.01,
                        20.05 + minute * 0.01,
                        500.0 + minute,
                        "BBB",
                    )
                )
            rows.append(
                (
                    timestamp,
                    30.0,
                    30.1,
                    29.9,
                    30.05,
                    100.0,
                    "RAWONLY",
                )
            )
        if day == 2:
            for minute in range(10):
                timestamp = start + timedelta(minutes=minute)
                rows.append(
                    (
                        timestamp,
                        5.0,
                        5.1,
                        4.9,
                        5.05,
                        200.0,
                        "DDD",
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
        target = (data_dir / "ohlcv_2026-01.parquet").as_posix().replace("'", "''")
        connection.execute(
            f"COPY (SELECT * FROM bars ORDER BY timestamp, ticker) "
            f"TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    finally:
        connection.close()

    layout = HuggingFaceSnapshotLayout.resolve(root, expected_revision=REVISION)
    inventory = inventory_monthly_parquet(layout)
    return root, inventory.inventory_id


def _probe() -> dict[str, object]:
    return {
        "probe_id": "mt5-probe-synthetic",
        "probed_at": "2026-01-07T12:00:00+00:00",
        "read_only": True,
        "mutation_authority": False,
        "terminal": {
            "connected": True,
            "broker_server": "Synthetic-Demo",
        },
        "symbols": [
            {
                "symbol": "AAA",
                "path": "Nasdaq\\Stock\\AAA",
                "visible": True,
                "tradable": True,
            },
            {
                "symbol": "BBB",
                "path": "Nasdaq\\Stock\\BBB",
                "visible": False,
                "tradable": True,
            },
            {
                "symbol": "DDD",
                "path": "NYSE\\Stock\\DDD",
                "visible": True,
                "tradable": True,
            },
            {
                "symbol": "AAA.US",
                "path": "Broker\\Stock\\AAA.US",
                "visible": True,
                "tradable": True,
            },
            {
                "symbol": "DISABLED",
                "path": "Broker\\Stock\\DISABLED",
                "visible": True,
                "tradable": False,
            },
        ],
        "spread_samples": [
            {
                "symbol": "AAA",
                "sampled_at": "2026-01-07T12:00:00+00:00",
                "bid": 10.0,
                "ask": 10.01,
            }
        ],
    }


def _policy(calendar: TradingCalendarEvidence, **overrides: object) -> USUniverseCandidateSelectionPolicy:
    values: dict[str, object] = {
        "start": _dt(2, 14, 30),
        "end": _dt(6, 14, 40),
        "calendar_id": calendar.calendar_id,
        "top_n": 2,
        "minimum_selected_count": 2,
        "minimum_active_sessions": 2,
        "minimum_active_session_ratio": 0.66,
        "minimum_median_regular_coverage_ratio": 0.80,
        "minimum_median_session_close": 1.0,
        "seed_symbols": ("AAA", "BBB"),
    }
    values.update(overrides)
    return USUniverseCandidateSelectionPolicy(**values)  # type: ignore[arg-type]


def test_selects_exact_tradable_activity_candidates_and_preserves_seed(tmp_path: Path) -> None:
    root, inventory_id = _snapshot(tmp_path)
    calendar = _calendar()
    policy = _policy(calendar)
    execution = DuckDBExecutionPolicy(
        memory_limit="256MB",
        threads=1,
        max_temp_directory_size="1GB",
    )

    report = select_us_universe_candidates(
        root,
        mt5_probe=_probe(),
        calendar=calendar,
        policy=policy,
        expected_revision=REVISION,
        expected_inventory_id=inventory_id,
        cleaning_identity=CLEANING_ID,
        execution_policy=execution,
        temp_directory=tmp_path / "duckdb-temp",
        generated_at=datetime(2026, 1, 7, tzinfo=UTC),
    )

    assert report.ready_for_spread_probe
    assert report.blockers == ()
    assert report.research_symbol_count == 4
    assert report.broker_tradable_symbol_count == 4
    assert report.exact_intersection_count == 3
    assert report.eligible_candidate_count == 2
    assert [item.research_symbol for item in report.candidates] == ["AAA", "BBB"]
    assert report.candidates[0].current_spread_bps is not None
    assert report.candidates[1].visibility_action_required
    assert report.manual_visibility_required_symbols == ("BBB",)
    assert "AAA.US" not in {item.research_symbol for item in report.candidates}
    assert report.partition_months == ("2026-01",)


def test_selection_identity_excludes_generation_timestamp(tmp_path: Path) -> None:
    root, inventory_id = _snapshot(tmp_path)
    calendar = _calendar()
    policy = _policy(calendar)
    common = {
        "root": root,
        "mt5_probe": _probe(),
        "calendar": calendar,
        "policy": policy,
        "expected_revision": REVISION,
        "expected_inventory_id": inventory_id,
        "cleaning_identity": CLEANING_ID,
        "temp_directory": tmp_path / "duckdb-temp",
    }
    first = select_us_universe_candidates(
        **common,
        generated_at=datetime(2026, 1, 7, tzinfo=UTC),
    )
    second = select_us_universe_candidates(
        **common,
        generated_at=datetime(2026, 1, 8, tzinfo=UTC),
    )

    assert first.selection_id == second.selection_id


def test_visible_only_policy_fails_closed_when_seed_is_not_visible(tmp_path: Path) -> None:
    root, inventory_id = _snapshot(tmp_path)
    calendar = _calendar()
    policy = _policy(calendar, require_visible=True)

    report = select_us_universe_candidates(
        root,
        mt5_probe=_probe(),
        calendar=calendar,
        policy=policy,
        expected_revision=REVISION,
        expected_inventory_id=inventory_id,
        cleaning_identity=CLEANING_ID,
        temp_directory=tmp_path / "duckdb-temp",
    )

    assert not report.ready_for_spread_probe
    assert "seed:BBB:not_eligible" in report.blockers
    assert any(item.startswith("selection:insufficient_candidates") for item in report.blockers)


def test_non_exact_symbol_policy_is_rejected() -> None:
    calendar = _calendar()
    with pytest.raises(ValueError, match="exact symbol text"):
        _policy(calendar, exact_symbol_match_only=False)

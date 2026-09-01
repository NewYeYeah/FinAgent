from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest

from finagent.data.minute_store import (
    DuckDBParquetMinuteStore,
    copy_plan_to_parquet,
    count_plan_rows,
    manifest_from_directory,
)
from finagent.data.minute_transform import (
    CalendarSessionizedMinuteStore,
    load_trading_calendar_evidence_json,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession

_FIXTURE = Path("tests/fixtures/us_minute/sessionization_edge_cases.csv")
_CLEANING_ID = "us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244"


def _dt(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def _calendar() -> TradingCalendarEvidence:
    return TradingCalendarEvidence(
        market_id="XNYS",
        timezone="America/New_York",
        source="synthetic-calendar:XNYS",
        source_revision="synthetic-v1",
        sessions=(
            TradingSession(
                session_date=date(2025, 11, 28),
                open_at=_dt(2025, 11, 28, 14, 30),
                close_at=_dt(2025, 11, 28, 18, 0),
                is_half_day=True,
            ),
            TradingSession(
                session_date=date(2026, 3, 6),
                open_at=_dt(2026, 3, 6, 14, 30),
                close_at=_dt(2026, 3, 6, 21, 0),
            ),
            TradingSession(
                session_date=date(2026, 3, 9),
                open_at=_dt(2026, 3, 9, 13, 30),
                close_at=_dt(2026, 3, 9, 20, 0),
            ),
        ),
    )


def _write_monthly_parquet(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    connection = duckdb.connect(database=":memory:")
    try:
        fixture = _FIXTURE.resolve().as_posix().replace("'", "''")
        connection.execute(
            f"""
            CREATE TABLE raw AS
            SELECT
                CAST(timestamp AS TIMESTAMPTZ) AS timestamp,
                CAST(open AS DOUBLE) AS open,
                CAST(high AS DOUBLE) AS high,
                CAST(low AS DOUBLE) AS low,
                CAST(close AS DOUBLE) AS close,
                CAST(volume AS DOUBLE) AS volume,
                CAST(ticker AS VARCHAR) AS ticker
            FROM read_csv_auto('{fixture}', header = true)
            """
        )
        for month, start, end in (
            ("2025-11", "2025-11-01T00:00:00+00:00", "2025-12-01T00:00:00+00:00"),
            ("2026-03", "2026-03-01T00:00:00+00:00", "2026-04-01T00:00:00+00:00"),
        ):
            target = (data_dir / f"ohlcv_{month}.parquet").as_posix().replace("'", "''")
            connection.execute(
                f"""
                COPY (
                    SELECT timestamp, open, high, low, close, volume, ticker
                    FROM raw
                    WHERE timestamp >= TIMESTAMPTZ '{start}'
                      AND timestamp < TIMESTAMPTZ '{end}'
                    ORDER BY timestamp, ticker
                ) TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)
                """
            )
    finally:
        connection.close()
    return data_dir


def _store(tmp_path: Path) -> CalendarSessionizedMinuteStore:
    data_dir = _write_monthly_parquet(tmp_path)
    manifest = manifest_from_directory(
        data_dir,
        source_id="synthetic-us-minute-sessionization",
        source_revision="synthetic-v1",
        cleaning_identity=_CLEANING_ID,
        inventory_id="synthetic-sessionization-inventory-v1",
    )
    return CalendarSessionizedMinuteStore(
        DuckDBParquetMinuteStore(manifest),
        _calendar(),
    )


def _query(
    *,
    start: datetime,
    end: datetime,
    session_policy: SessionPolicy,
) -> MarketDataQuery:
    return MarketDataQuery(
        market_id="XNYS",
        assets=("MSFT",),
        start=start,
        end=end,
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.CLOSE, MarketDataField.VOLUME),
        session_policy=session_policy,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.EVENT_TIME,
    )


def _read_session_rows(path: Path) -> list[tuple[object, ...]]:
    connection = duckdb.connect(database=":memory:")
    try:
        return connection.execute(
            f"""
            SELECT
                CAST(event_time AS VARCHAR),
                session_type,
                CAST(session_open AS VARCHAR),
                CAST(session_close AS VARCHAR),
                minute_offset,
                is_regular_session,
                is_half_day,
                session_id
            FROM read_parquet('{path.as_posix()}')
            ORDER BY event_time
            """
        ).fetchall()
    finally:
        connection.close()


def test_all_observed_classifies_regular_outside_regular_and_closed_date(tmp_path: Path) -> None:
    store = _store(tmp_path)
    query = _query(
        start=_dt(2026, 3, 6, 14, 29),
        end=_dt(2026, 3, 9, 20, 1),
        session_policy=SessionPolicy.ALL_OBSERVED,
    )
    plan, evidence = store.plan(query)
    output = tmp_path / "sessionized.parquet"
    materialization = copy_plan_to_parquet(plan, output)
    rows = _read_session_rows(output)

    assert materialization.row_count == 9
    assert count_plan_rows(plan) == 9
    assert [row[1] for row in rows].count("regular") == 4
    assert [row[1] for row in rows].count("outside_regular") == 4
    assert [row[1] for row in rows].count("outside_calendar") == 1
    assert evidence.calendar_id == _calendar().calendar_id
    assert evidence.sessionized_plan_id == plan.plan_id
    assert evidence.sessionized_data_version == plan.data_version
    assert plan.data_version.startswith("sessionized-minute-data-version-")


def test_regular_filter_uses_open_inclusive_close_exclusive_across_dst(tmp_path: Path) -> None:
    store = _store(tmp_path)
    plan, _evidence = store.plan(
        _query(
            start=_dt(2026, 3, 6, 14, 29),
            end=_dt(2026, 3, 9, 20, 1),
            session_policy=SessionPolicy.REGULAR,
        )
    )
    output = tmp_path / "regular.parquet"
    copy_plan_to_parquet(plan, output)
    rows = _read_session_rows(output)

    assert len(rows) == 4
    assert [row[4] for row in rows] == [0, 389, 0, 389]
    assert all(row[1] == "regular" for row in rows)
    assert all(row[5] is True for row in rows)
    assert str(rows[0][2]).startswith("2026-03-06 14:30")
    assert str(rows[2][2]).startswith("2026-03-09 13:30")
    assert str(rows[0][3]).startswith("2026-03-06 21:00")
    assert str(rows[2][3]).startswith("2026-03-09 20:00")


def test_half_day_close_boundary_and_flag_are_calendar_authoritative(tmp_path: Path) -> None:
    store = _store(tmp_path)
    all_plan, _evidence = store.plan(
        _query(
            start=_dt(2025, 11, 28, 14, 29),
            end=_dt(2025, 11, 29, 15, 1),
            session_policy=SessionPolicy.ALL_OBSERVED,
        )
    )
    all_output = tmp_path / "half-day-all.parquet"
    copy_plan_to_parquet(all_plan, all_output)
    rows = _read_session_rows(all_output)

    assert [row[1] for row in rows] == [
        "outside_regular",
        "regular",
        "regular",
        "outside_regular",
        "outside_calendar",
    ]
    assert rows[1][6] is True
    assert rows[2][6] is True
    assert rows[3][6] is True

    regular_plan, _ = store.plan(
        _query(
            start=_dt(2025, 11, 28, 14, 29),
            end=_dt(2025, 11, 29, 15, 1),
            session_policy=SessionPolicy.REGULAR,
        )
    )
    assert count_plan_rows(regular_plan) == 2


def test_extended_policy_stays_fail_closed_without_extended_calendar_bounds(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="session_policy:extended"):
        store.plan(
            _query(
                start=_dt(2026, 3, 6, 14, 0),
                end=_dt(2026, 3, 6, 22, 0),
                session_policy=SessionPolicy.EXTENDED,
            )
        )


def test_calendar_json_loader_recomputes_and_checks_calendar_identity(tmp_path: Path) -> None:
    calendar = _calendar()
    path = tmp_path / "calendar.json"
    path.write_text(
        json.dumps({"evidence": calendar.to_dict()}, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    loaded = load_trading_calendar_evidence_json(
        path,
        expected_calendar_id=calendar.calendar_id,
    )
    assert loaded.calendar_id == calendar.calendar_id
    assert loaded.sessions == calendar.sessions

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["evidence"]["calendar_id"] = "trading-calendar-tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="stored calendar_id"):
        load_trading_calendar_evidence_json(path)

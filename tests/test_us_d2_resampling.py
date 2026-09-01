from __future__ import annotations

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
    SessionResampledMinuteStore,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession

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
        connection.execute(
            """
            CREATE TABLE raw AS
            WITH normal AS (
                SELECT
                    TIMESTAMPTZ '2026-03-09T13:30:00+00:00'
                        + i * INTERVAL '1 minute' AS timestamp,
                    ticker,
                    CASE WHEN ticker = 'NVDA' THEN 200.0 ELSE 100.0 END + i * 0.01 AS open,
                    CASE WHEN ticker = 'NVDA' THEN 200.05 ELSE 100.05 END + i * 0.01 AS high,
                    CASE WHEN ticker = 'NVDA' THEN 199.97 ELSE 99.97 END + i * 0.01 AS low,
                    CASE WHEN ticker = 'NVDA' THEN 200.02 ELSE 100.02 END + i * 0.01 AS close,
                    1000.0 + i AS volume
                FROM range(390) AS r(i)
                CROSS JOIN (VALUES ('NVDA'), ('MSFT')) AS symbols(ticker)
                WHERE NOT (ticker = 'MSFT' AND i = 7)
            ),
            half_day AS (
                SELECT
                    TIMESTAMPTZ '2025-11-28T14:30:00+00:00'
                        + i * INTERVAL '1 minute' AS timestamp,
                    ticker,
                    CASE WHEN ticker = 'NVDA' THEN 180.0 ELSE 90.0 END + i * 0.01 AS open,
                    CASE WHEN ticker = 'NVDA' THEN 180.05 ELSE 90.05 END + i * 0.01 AS high,
                    CASE WHEN ticker = 'NVDA' THEN 179.97 ELSE 89.97 END + i * 0.01 AS low,
                    CASE WHEN ticker = 'NVDA' THEN 180.02 ELSE 90.02 END + i * 0.01 AS close,
                    800.0 + i AS volume
                FROM range(210) AS r(i)
                CROSS JOIN (VALUES ('NVDA'), ('MSFT')) AS symbols(ticker)
            )
            SELECT timestamp, open, high, low, close, volume, ticker FROM normal
            UNION ALL
            SELECT timestamp, open, high, low, close, volume, ticker FROM half_day
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


def _store(
    tmp_path: Path,
    *,
    calendar: TradingCalendarEvidence | None = None,
) -> SessionResampledMinuteStore:
    data_dir = _write_monthly_parquet(tmp_path)
    manifest = manifest_from_directory(
        data_dir,
        source_id="synthetic-us-minute-resampling",
        source_revision="synthetic-v1",
        cleaning_identity=_CLEANING_ID,
        inventory_id="synthetic-resampling-inventory-v1",
    )
    sessionized = CalendarSessionizedMinuteStore(
        DuckDBParquetMinuteStore(manifest),
        calendar or _calendar(),
    )
    return SessionResampledMinuteStore(sessionized)


def _query(
    *,
    asset: str,
    start: datetime,
    end: datetime,
    interval: BarInterval,
    availability_policy: AvailabilityPolicy = AvailabilityPolicy.EVENT_TIME,
) -> MarketDataQuery:
    return MarketDataQuery(
        market_id="XNYS",
        assets=(asset,),
        start=start,
        end=end,
        interval=interval,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=availability_policy,
    )


def _read_rows(path: Path) -> list[tuple[object, ...]]:
    connection = duckdb.connect(database=":memory:")
    try:
        return connection.execute(
            f"""
            SELECT
                CAST(event_time AS VARCHAR),
                CAST(available_at AS VARCHAR),
                open,
                high,
                low,
                close,
                volume,
                bar_index,
                observed_minute_count,
                expected_minute_count,
                coverage_ratio,
                is_complete,
                is_half_day
            FROM read_parquet('{path.as_posix()}')
            ORDER BY event_time
            """
        ).fetchall()
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("interval", "normal_count", "half_day_count"),
    (
        (BarInterval.MINUTE_5, 78, 42),
        (BarInterval.MINUTE_15, 26, 14),
        (BarInterval.MINUTE_30, 13, 7),
    ),
)
def test_complete_normal_and_half_day_bar_counts(
    tmp_path: Path,
    interval: BarInterval,
    normal_count: int,
    half_day_count: int,
) -> None:
    store = _store(tmp_path)
    normal_plan, _ = store.plan(
        _query(
            asset="NVDA",
            start=_dt(2026, 3, 9, 13, 30),
            end=_dt(2026, 3, 9, 20, 0),
            interval=interval,
        )
    )
    half_day_plan, _ = store.plan(
        _query(
            asset="NVDA",
            start=_dt(2025, 11, 28, 14, 30),
            end=_dt(2025, 11, 28, 18, 0),
            interval=interval,
        )
    )

    assert count_plan_rows(normal_plan) == normal_count
    assert count_plan_rows(half_day_plan) == half_day_count


def test_ohlcv_aggregation_and_bucket_end_availability_are_deterministic(tmp_path: Path) -> None:
    store = _store(tmp_path)
    plan, evidence = store.plan(
        _query(
            asset="NVDA",
            start=_dt(2026, 3, 9, 13, 30),
            end=_dt(2026, 3, 9, 13, 35),
            interval=BarInterval.MINUTE_5,
        )
    )
    output = tmp_path / "five-minute.parquet"
    materialization = copy_plan_to_parquet(plan, output)
    rows = _read_rows(output)

    assert len(rows) == 1
    row = rows[0]
    assert str(row[0]).startswith("2026-03-09 13:30")
    assert str(row[1]).startswith("2026-03-09 13:35")
    assert row[2] == pytest.approx(200.0)
    assert row[3] == pytest.approx(200.09)
    assert row[4] == pytest.approx(199.97)
    assert row[5] == pytest.approx(200.06)
    assert row[6] == pytest.approx(5010.0)
    assert row[7] == 0
    assert row[8] == 5
    assert row[9] == 5
    assert row[10] == pytest.approx(1.0)
    assert row[11] is True
    assert materialization.data_version == plan.data_version
    assert evidence.resampled_plan_id == plan.plan_id
    assert evidence.resampled_data_version == plan.data_version
    assert plan.data_version.startswith("resampled-minute-data-version-")


def test_missing_minute_is_preserved_as_incomplete_coverage(tmp_path: Path) -> None:
    store = _store(tmp_path)
    plan, _ = store.plan(
        _query(
            asset="MSFT",
            start=_dt(2026, 3, 9, 13, 30),
            end=_dt(2026, 3, 9, 13, 45),
            interval=BarInterval.MINUTE_15,
        )
    )
    output = tmp_path / "incomplete.parquet"
    copy_plan_to_parquet(plan, output)
    rows = _read_rows(output)

    assert len(rows) == 1
    assert rows[0][8] == 14
    assert rows[0][9] == 15
    assert rows[0][10] == pytest.approx(14 / 15)
    assert rows[0][11] is False


def test_available_at_query_filters_on_bucket_end_not_bucket_start(tmp_path: Path) -> None:
    store = _store(tmp_path)
    plan, _ = store.plan(
        _query(
            asset="NVDA",
            start=_dt(2026, 3, 9, 13, 45),
            end=_dt(2026, 3, 9, 14, 0),
            interval=BarInterval.MINUTE_15,
            availability_policy=AvailabilityPolicy.AVAILABLE_AT,
        )
    )
    output = tmp_path / "available.parquet"
    copy_plan_to_parquet(plan, output)
    rows = _read_rows(output)

    assert len(rows) == 1
    assert str(rows[0][0]).startswith("2026-03-09 13:30")
    assert str(rows[0][1]).startswith("2026-03-09 13:45")


def test_60m_and_non_regular_session_policies_stay_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="interval:60m"):
        store.plan(
            _query(
                asset="NVDA",
                start=_dt(2026, 3, 9, 13, 30),
                end=_dt(2026, 3, 9, 20, 0),
                interval=BarInterval.MINUTE_60,
            )
        )

    query = MarketDataQuery(
        market_id="XNYS",
        assets=("NVDA",),
        start=_dt(2026, 3, 9, 13, 30),
        end=_dt(2026, 3, 9, 20, 0),
        interval=BarInterval.MINUTE_15,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.ALL_OBSERVED,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.EVENT_TIME,
    )
    with pytest.raises(ValueError, match="session_policy:all_observed"):
        store.plan(query)


def test_non_divisible_session_duration_fails_before_partial_bar_is_created(
    tmp_path: Path,
) -> None:
    calendar = TradingCalendarEvidence(
        market_id="XNYS",
        timezone="America/New_York",
        source="synthetic-calendar:XNYS",
        source_revision="non-divisible-v1",
        sessions=(
            TradingSession(
                session_date=date(2025, 11, 28),
                open_at=_dt(2025, 11, 28, 14, 30),
                close_at=_dt(2025, 11, 28, 17, 55),
                is_half_day=True,
            ),
        ),
    )
    store = _store(tmp_path, calendar=calendar)
    with pytest.raises(ValueError, match="205.*not divisible by 30"):
        store.plan(
            _query(
                asset="NVDA",
                start=_dt(2025, 11, 28, 14, 30),
                end=_dt(2025, 11, 28, 17, 55),
                interval=BarInterval.MINUTE_30,
            )
        )

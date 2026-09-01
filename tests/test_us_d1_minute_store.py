from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from finagent.data.minute_store import (
    DuckDBParquetMinuteStore,
    copy_plan_to_parquet,
    count_plan_rows,
    fetch_plan_rows,
    manifest_from_directory,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval

_FIXTURE = Path("tests/fixtures/us_minute/synthetic_ohlcv.csv")
_CLEANING_ID = "us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244"


def _utc(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


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
            ("2026-03", "2026-03-01T00:00:00+00:00", "2026-04-01T00:00:00+00:00"),
            ("2026-04", "2026-04-01T00:00:00+00:00", "2026-05-01T00:00:00+00:00"),
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


def _store(tmp_path: Path) -> DuckDBParquetMinuteStore:
    data_dir = _write_monthly_parquet(tmp_path)
    manifest = manifest_from_directory(
        data_dir,
        source_id="synthetic-us-minute-fixture",
        source_revision="synthetic-v1",
        cleaning_identity=_CLEANING_ID,
        inventory_id="synthetic-us-minute-inventory-v1",
    )
    return DuckDBParquetMinuteStore(manifest)


def _query(
    *,
    start: datetime,
    end: datetime,
    session_policy: SessionPolicy = SessionPolicy.ALL_OBSERVED,
    adjustment_policy: ResearchPriceBasis = ResearchPriceBasis.RAW,
    availability_policy: AvailabilityPolicy = AvailabilityPolicy.AVAILABLE_AT,
) -> MarketDataQuery:
    return MarketDataQuery(
        market_id="XNYS",
        assets=("MSFT", "NVDA", "AMD", "INTC"),
        start=start,
        end=end,
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.CLOSE, MarketDataField.VOLUME),
        session_policy=session_policy,
        adjustment_policy=adjustment_policy,
        availability_policy=availability_policy,
    )


def test_bounded_query_prunes_partitions_and_preserves_available_at(tmp_path: Path) -> None:
    store = _store(tmp_path)
    query = _query(start=_utc(3, 9, 13, 31), end=_utc(3, 9, 14, 1))
    plan = store.plan(query)

    assert plan.partition_months == ("2026-03",)
    assert plan.output_columns == (
        "research_asset_id",
        "session_date",
        "event_time",
        "available_at",
        "interval",
        "close",
        "volume",
        "session_type",
        "source_id",
        "source_revision",
        "data_version",
    )
    rows = fetch_plan_rows(plan, limit=500)
    assert len(rows) == 117
    assert count_plan_rows(plan) == 117
    assert all(row["available_at"] == row["event_time"] + timedelta(minutes=1) for row in rows)
    assert all(row["interval"] == "1m" for row in rows)
    assert all(row["session_type"] == "observed_unclassified" for row in rows)
    assert set(rows[0]) == set(plan.output_columns)


def test_admitted_query_collapses_exact_and_quarantines_ambiguous_or_invalid_rows(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    plan = store.plan(_query(start=_utc(3, 9, 13, 31), end=_utc(3, 9, 14, 1)))
    rows = fetch_plan_rows(plan, limit=500)
    keys = [(row["research_asset_id"], row["event_time"]) for row in rows]

    assert len(keys) == len(set(keys))
    assert ("MSFT", _utc(3, 9, 13, 40)) in keys
    assert ("NVDA", _utc(3, 9, 13, 45)) not in keys
    assert ("AMD", _utc(3, 9, 13, 50)) not in keys
    assert ("INTC", _utc(3, 9, 13, 55)) not in keys


def test_event_time_query_uses_event_clock_without_lookahead_shift(tmp_path: Path) -> None:
    store = _store(tmp_path)
    plan = store.plan(
        _query(
            start=_utc(3, 9, 13, 30),
            end=_utc(3, 9, 13, 31),
            availability_policy=AvailabilityPolicy.EVENT_TIME,
        )
    )
    rows = fetch_plan_rows(plan, limit=10)
    assert len(rows) == 4
    assert all(row["event_time"] == _utc(3, 9, 13, 30) for row in rows)


def test_april_query_selects_only_april_partition(tmp_path: Path) -> None:
    store = _store(tmp_path)
    plan = store.plan(_query(start=_utc(4, 1, 13, 31), end=_utc(4, 1, 13, 36)))
    assert plan.partition_months == ("2026-04",)
    assert count_plan_rows(plan) == 20


def test_us_d1_capabilities_fail_closed_before_session_and_adjustment_semantics(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="session_policy:regular"):
        store.plan(
            _query(
                start=_utc(3, 9, 13, 31),
                end=_utc(3, 9, 13, 40),
                session_policy=SessionPolicy.REGULAR,
            )
        )
    with pytest.raises(ValueError, match="adjustment_policy:split_adjusted"):
        store.plan(
            _query(
                start=_utc(3, 9, 13, 31),
                end=_utc(3, 9, 13, 40),
                adjustment_policy=ResearchPriceBasis.SPLIT_ADJUSTED,
            )
        )


def test_bounded_plan_materializes_to_parquet_without_dense_panel(tmp_path: Path) -> None:
    store = _store(tmp_path)
    plan = store.plan(_query(start=_utc(3, 9, 13, 31), end=_utc(3, 9, 13, 46)))
    output = tmp_path / "bounded.parquet"

    materialization = copy_plan_to_parquet(plan, output)

    assert output.is_file()
    assert materialization.row_count == count_plan_rows(plan)
    assert materialization.size_bytes == output.stat().st_size
    assert materialization.materialization_id.startswith("minute-materialization-")
    connection = duckdb.connect(database=":memory:")
    try:
        columns = [
            row[0]
            for row in connection.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{output.as_posix()}')"
            ).fetchall()
        ]
    finally:
        connection.close()
    assert columns == list(plan.output_columns)

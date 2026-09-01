from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest

from finagent.data.minute_store import (
    DuckDBParquetMinuteStore,
    copy_plan_to_parquet,
    fetch_plan_rows,
    manifest_from_directory,
)
from finagent.data.minute_transform import (
    CalendarSessionizedMinuteStore,
    LabelMaterializationSpec,
    SameSessionLabelStore,
    canonical_same_session_60m_label_spec,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import (
    AvailabilityPolicy,
    LabelHorizonUnit,
    LabelMetric,
    LabelSpec,
    ResearchPriceBasis,
)
from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession

_CLEANING_ID = "us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244"


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, 9, hour, minute, tzinfo=UTC)


def _calendar() -> TradingCalendarEvidence:
    return TradingCalendarEvidence(
        market_id="XNYS",
        timezone="America/New_York",
        source="synthetic-calendar:XNYS",
        source_revision="synthetic-v1",
        sessions=(
            TradingSession(
                session_date=date(2026, 3, 9),
                open_at=_dt(13, 30),
                close_at=_dt(20, 0),
            ),
        ),
    )


def _write_parquet(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    target = data_dir / "ohlcv_2026-03.parquet"
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            f"""
            COPY (
                WITH generated AS (
                    SELECT
                        TIMESTAMPTZ '2026-03-09T13:30:00+00:00'
                            + i * INTERVAL '1 minute' AS timestamp,
                        ticker,
                        CASE WHEN ticker = 'NVDA' THEN 200.0 ELSE 100.0 END
                            + i * 0.01 AS open,
                        CASE WHEN ticker = 'NVDA' THEN 200.05 ELSE 100.05 END
                            + i * 0.01 AS high,
                        CASE WHEN ticker = 'NVDA' THEN 199.97 ELSE 99.97 END
                            + i * 0.01 AS low,
                        CASE WHEN ticker = 'NVDA' THEN 200.02 ELSE 100.02 END
                            + i * 0.01 AS close,
                        1000.0 + i AS volume,
                        i
                    FROM range(390) AS r(i)
                    CROSS JOIN (VALUES ('NVDA'), ('MSFT')) AS symbols(ticker)
                )
                SELECT
                    timestamp,
                    CAST(open AS DOUBLE) AS open,
                    CAST(high AS DOUBLE) AS high,
                    CAST(low AS DOUBLE) AS low,
                    CAST(close AS DOUBLE) AS close,
                    CAST(volume AS DOUBLE) AS volume,
                    ticker
                FROM generated
                WHERE NOT (ticker = 'MSFT' AND i = 100)
                ORDER BY timestamp, ticker
            ) TO '{target.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    finally:
        connection.close()
    return data_dir


def _store(tmp_path: Path) -> SameSessionLabelStore:
    data_dir = _write_parquet(tmp_path)
    manifest = manifest_from_directory(
        data_dir,
        source_id="synthetic-us-minute-labels",
        source_revision="synthetic-v1",
        cleaning_identity=_CLEANING_ID,
        inventory_id="synthetic-label-inventory-v1",
    )
    sessionized = CalendarSessionizedMinuteStore(
        DuckDBParquetMinuteStore(manifest),
        _calendar(),
    )
    return SameSessionLabelStore(sessionized)


def _query(
    *,
    availability_policy: AvailabilityPolicy = AvailabilityPolicy.AVAILABLE_AT,
    fields: tuple[MarketDataField, ...] = (MarketDataField.CLOSE,),
) -> MarketDataQuery:
    return MarketDataQuery(
        market_id="XNYS",
        assets=("MSFT", "NVDA"),
        start=_dt(13, 31),
        end=_dt(20, 1),
        interval=BarInterval.MINUTE_1,
        fields=fields,
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=availability_policy,
    )


def _label_summary(path: Path) -> tuple[int, int, int, int]:
    connection = duckdb.connect(database=":memory:")
    try:
        row = connection.execute(
            f"""
            SELECT
                count(*) AS total_rows,
                count(*) FILTER (WHERE label_available) AS available_rows,
                count(*) FILTER (WHERE unavailable_reason = 'target_crosses_session') AS crosses,
                count(*) FILTER (WHERE unavailable_reason = 'target_minute_missing') AS missing
            FROM read_parquet('{path.as_posix()}')
            """
        ).fetchone()
        assert row is not None
        return tuple(int(value) for value in row)
    finally:
        connection.close()


def _label_row(path: Path, asset: str, source_offset: int) -> tuple[object, ...]:
    connection = duckdb.connect(database=":memory:")
    try:
        row = connection.execute(
            f"""
            SELECT
                CAST(source_event_time AS VARCHAR),
                CAST(source_available_at AS VARCHAR),
                source_minute_offset,
                source_price,
                CAST(target_event_time AS VARCHAR),
                CAST(target_available_at AS VARCHAR),
                target_minute_offset,
                target_price,
                label_value,
                label_available,
                unavailable_reason
            FROM read_parquet('{path.as_posix()}')
            WHERE research_asset_id = ? AND source_minute_offset = ?
            """,
            [asset, source_offset],
        ).fetchone()
        assert row is not None
        return row
    finally:
        connection.close()


def test_canonical_60m_label_preserves_available_and_unavailable_denominator(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    label_spec = canonical_same_session_60m_label_spec()
    plan, evidence = store.plan(_query(), label_spec)
    output = tmp_path / "labels.parquet"
    materialization = copy_plan_to_parquet(plan, output)

    assert _label_summary(output) == (779, 658, 120, 1)
    assert materialization.row_count == 779
    assert evidence.label_plan_id == plan.plan_id
    assert evidence.label_data_version == plan.data_version
    assert plan.data_version.startswith("label-data-version-")
    assert plan.label_spec_id == label_spec.label_id


def test_exact_target_join_computes_value_and_pit_target_clock(tmp_path: Path) -> None:
    store = _store(tmp_path)
    plan, _ = store.plan(_query(), canonical_same_session_60m_label_spec())
    output = tmp_path / "labels.parquet"
    copy_plan_to_parquet(plan, output)
    row = _label_row(output, "NVDA", 0)

    assert str(row[0]).startswith("2026-03-09 13:30")
    assert str(row[1]).startswith("2026-03-09 13:31")
    assert row[2] == 0
    assert row[3] == pytest.approx(200.02)
    assert str(row[4]).startswith("2026-03-09 14:30")
    assert str(row[5]).startswith("2026-03-09 14:31")
    assert row[6] == 60
    assert row[7] == pytest.approx(200.62)
    assert row[8] == pytest.approx(200.62 / 200.02 - 1.0)
    assert row[9] is True
    assert row[10] is None


def test_missing_exact_target_is_not_replaced_by_neighboring_minutes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    plan, _ = store.plan(_query(), canonical_same_session_60m_label_spec())
    output = tmp_path / "labels.parquet"
    copy_plan_to_parquet(plan, output)
    row = _label_row(output, "MSFT", 40)

    assert row[6] == 100
    assert row[4] is None
    assert row[5] is None
    assert row[7] is None
    assert row[8] is None
    assert row[9] is False
    assert row[10] == "target_minute_missing"


def test_close_boundary_is_explicitly_unavailable_instead_of_cross_session(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    plan, _ = store.plan(_query(), canonical_same_session_60m_label_spec())
    output = tmp_path / "labels.parquet"
    copy_plan_to_parquet(plan, output)
    row = _label_row(output, "NVDA", 330)

    assert row[6] == 390
    assert row[4] is None
    assert row[8] is None
    assert row[9] is False
    assert row[10] == "target_crosses_session"


def test_label_plan_supports_bounded_python_preview_without_pytz(tmp_path: Path) -> None:
    store = _store(tmp_path)
    plan, _ = store.plan(_query(), canonical_same_session_60m_label_spec())
    rows = fetch_plan_rows(plan, limit=2)

    assert len(rows) == 2
    assert isinstance(rows[0]["source_event_time"], datetime)
    assert isinstance(rows[0]["source_available_at"], datetime)
    assert isinstance(rows[0]["target_event_time"], datetime)
    assert isinstance(rows[0]["target_available_at"], datetime)


def test_materialization_spec_rejects_cross_session_nonminute_and_adjusted_labels() -> None:
    base = canonical_same_session_60m_label_spec()
    calendar_id = _calendar().calendar_id

    with pytest.raises(ValueError, match="same-session"):
        LabelMaterializationSpec(
            label_spec=LabelSpec(
                metric=LabelMetric.SIMPLE_RETURN,
                horizon=60,
                horizon_unit=LabelHorizonUnit.TRADING_MINUTES,
                allow_cross_session=True,
                price_basis=ResearchPriceBasis.RAW,
                availability_policy=AvailabilityPolicy.AVAILABLE_AT,
            ),
            calendar_id=calendar_id,
        )
    with pytest.raises(ValueError, match="trading-minute"):
        LabelMaterializationSpec(
            label_spec=LabelSpec(
                metric=LabelMetric.SIMPLE_RETURN,
                horizon=4,
                horizon_unit=LabelHorizonUnit.BARS,
                allow_cross_session=False,
                price_basis=ResearchPriceBasis.RAW,
                availability_policy=AvailabilityPolicy.AVAILABLE_AT,
            ),
            calendar_id=calendar_id,
        )
    with pytest.raises(ValueError, match="raw price basis"):
        LabelMaterializationSpec(
            label_spec=LabelSpec(
                metric=LabelMetric.SIMPLE_RETURN,
                horizon=base.horizon,
                horizon_unit=base.horizon_unit,
                allow_cross_session=False,
                price_basis=ResearchPriceBasis.SPLIT_ADJUSTED,
                availability_policy=AvailabilityPolicy.AVAILABLE_AT,
            ),
            calendar_id=calendar_id,
        )


def test_label_source_query_requires_close_only_and_available_at(tmp_path: Path) -> None:
    store = _store(tmp_path)
    label_spec = canonical_same_session_60m_label_spec()

    with pytest.raises(ValueError, match="available_at"):
        store.plan(
            _query(availability_policy=AvailabilityPolicy.EVENT_TIME),
            label_spec,
        )
    with pytest.raises(ValueError, match="fields must be exactly"):
        store.plan(
            _query(fields=(MarketDataField.CLOSE, MarketDataField.VOLUME)),
            label_spec,
        )

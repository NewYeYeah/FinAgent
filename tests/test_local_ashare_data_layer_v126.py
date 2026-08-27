from __future__ import annotations

import csv
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from finagent.data import (
    AshareBarFrequency,
    LocalAshareDatasetInspector,
    LocalAshareDatasetLayout,
    LocalAshareParquetDataAdapter,
    LocalAshareSecurityMaster,
)
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.research import DatasetRequest, TimeRange

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _write_parquet_from_csv(
    tmp_path: Path,
    name: str,
    header: list[str],
    rows: list[list[object]],
) -> Path:
    import duckdb

    csv_path = tmp_path / f"{name}.csv"
    parquet_path = tmp_path / f"{name}.parquet"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    con = duckdb.connect()
    con.execute(
        f"COPY (SELECT * FROM read_csv_auto('{csv_path.as_posix()}', HEADER=TRUE)) "
        f"TO '{parquet_path.as_posix()}' (FORMAT PARQUET)"
    )
    return parquet_path


def _minute_times() -> list[datetime]:
    day = date(2024, 1, 2)
    values = [datetime.combine(day, time(9, 30))]
    cursor = datetime.combine(day, time(9, 31))
    while cursor <= datetime.combine(day, time(11, 30)):
        values.append(cursor)
        cursor += timedelta(minutes=1)
    cursor = datetime.combine(day, time(13, 1))
    while cursor <= datetime.combine(day, time(15, 0)):
        values.append(cursor)
        cursor += timedelta(minutes=1)
    assert len(values) == 241
    return values


def _layout(tmp_path: Path) -> LocalAshareDatasetLayout:
    _write_parquet_from_csv(
        tmp_path,
        "stock_basic_data",
        [
            "ts_code",
            "symbol",
            "name",
            "area",
            "industry",
            "market",
            "list_date",
            "delist_date",
            "list_status",
            "act_name",
            "act_ent_type",
        ],
        [
            [
                "000001.SZ",
                "000001",
                "平安银行",
                "深圳",
                "银行",
                "主板",
                "1991-04-03",
                "",
                "",
                "",
                "",
            ],
            [
                "601015.SH",
                "601015",
                "陕西黑猫",
                "陕西",
                "煤炭",
                "主板",
                "2024-01-03",
                "",
                "",
                "",
                "",
            ],
            [
                "920978.BJ",
                "920978",
                "北交样本",
                "北京",
                "制造",
                "北交所",
                "1970-01-01",
                "",
                "",
                "",
                "",
            ],
        ],
    )
    daily_header = [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "change",
        "pct_chg",
        "vol",
        "amount",
        "up_limit",
        "down_limit",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "total_share",
        "float_share",
        "free_share",
        "total_mv",
        "circ_mv",
        "adj_factor",
        "suspend_timing",
        "suspend_type",
        "is_st",
        "listed_days",
    ]
    daily_rows: list[list[object]] = []
    for code, base, factor in (
        ("000001.SZ", 10.0, 2.0),
        ("601015.SH", 20.0, 1.0),
    ):
        previous = base
        for offset, day in enumerate(("2024-01-02", "2024-01-03", "2024-01-04")):
            close = base + offset
            daily_rows.append(
                [
                    code,
                    day,
                    close - 0.2,
                    close + 0.3,
                    close - 0.4,
                    close,
                    previous,
                    close - previous,
                    0.0,
                    100.0 + offset,
                    1000.0 + offset,
                    close * 1.1,
                    close * 0.9,
                    1.0,
                    1.1,
                    1.0,
                    10.0,
                    10.0,
                    1.0,
                    1.0,
                    1.0,
                    0.0,
                    0.0,
                    10000.0,
                    9000.0,
                    8000.0,
                    100000.0,
                    90000.0,
                    factor
                    + (1.0 if code == "000001.SZ" and offset >= 1 else 0.0),
                    "",
                    "N",
                    0,
                    1000 + offset,
                ]
            )
            previous = close

    times = _minute_times()
    minute_rows: list[list[object]] = []
    for index, timestamp in enumerate(times):
        open_ = 9.8 if index == 0 else 10.0
        close = 10.2 if index == len(times) - 1 else 10.0
        high = max(open_, close, 10.5 if index == 100 else 10.0)
        low = min(open_, close, 9.5 if index == 80 else 10.0)
        volume = 0.0 if timestamp.time() == time(14, 59) else 100.0
        amount = volume * close
        minute_rows.append(
            [
                "000001.SZ",
                open_,
                high,
                low,
                close,
                volume,
                amount,
                2.0,
                "2024-01-02",
                timestamp.isoformat(sep=" "),
            ]
        )
    minute_volume = sum(float(row[5]) for row in minute_rows)
    minute_amount = sum(float(row[6]) for row in minute_rows)
    first = next(
        row
        for row in daily_rows
        if row[0] == "000001.SZ" and row[1] == "2024-01-02"
    )
    first[2:6] = [9.8, 10.5, 9.5, 10.2]
    first[9] = minute_volume / 100.0
    first[10] = minute_amount / 1000.0
    first[28] = 2.0
    _write_parquet_from_csv(tmp_path, "stock_daily", daily_header, daily_rows)

    minute_dir = tmp_path / "stock_1min"
    minute_dir.mkdir()
    minute_csv = minute_dir / "000001.SZ.csv"
    with minute_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "ts_code",
                "open",
                "high",
                "low",
                "close",
                "vol",
                "amount",
                "adj_factor",
                "trade_date",
                "trade_time",
            ]
        )
        writer.writerows(minute_rows)
    import duckdb

    duckdb.connect().execute(
        f"COPY (SELECT * FROM read_csv_auto('{minute_csv.as_posix()}', HEADER=TRUE)) "
        f"TO '{(minute_dir / '000001.SZ.parquet').as_posix()}' (FORMAT PARQUET)"
    )
    return LocalAshareDatasetLayout(tmp_path)


def _asset(symbol: str, venue: str) -> AssetId:
    return AssetId(symbol, AssetType.EQUITY, venue=venue, currency="CNY")


def test_local_security_master_is_candidate_only_and_preserves_leading_zero_identity(
    tmp_path,
) -> None:
    layout = _layout(tmp_path)
    master = LocalAshareSecurityMaster.from_parquet(layout.basic_path)

    assert not master.survivorship_certified
    assert _asset("000001", "SZSE") in master.assets
    assert any("delist_date" in item for item in master.limitations)
    assert any("1970-01-01" in item for item in master.limitations)

    asof = datetime(2024, 1, 2, 16, 0, tzinfo=SHANGHAI).astimezone(UTC)
    snapshot = master.snapshot(
        asof,
        (
            _asset("000001", "SZSE"),
            _asset("601015", "SSE"),
            _asset("920978", "BSE"),
        ),
    )
    assert snapshot.eligible[_asset("000001", "SZSE")]
    assert not snapshot.eligible[_asset("601015", "SSE")]
    assert not snapshot.eligible[_asset("920978", "BSE")]


def test_daily_adapter_normalizes_units_and_uses_adjusted_close_for_returns(
    tmp_path,
) -> None:
    layout = _layout(tmp_path)
    master = LocalAshareSecurityMaster.from_parquet(layout.basic_path)
    adapter = LocalAshareParquetDataAdapter(layout, security_master=master)
    universe = (_asset("000001", "SZSE"), _asset("601015", "SSE"))
    split = TimeRange(
        datetime(2024, 1, 2, 16, 0, tzinfo=SHANGHAI).astimezone(UTC),
        datetime(2024, 1, 5, 0, 0, tzinfo=SHANGHAI).astimezone(UTC),
    )
    dataset = adapter.build_dataset(
        DatasetRequest(
            universe=universe,
            features=(
                "close",
                "research_close",
                "volume",
                "amount",
                "simple_return_1",
                "is_st",
            ),
            labels=("forward_simple_return_1",),
            splits={"train": split},
            dataset_id="local-a-share-test",
        )
    )
    panel = dataset.get_split("train")

    first_asset = panel.asset_index(universe[0])
    assert panel.feature_values[0, first_asset, panel.feature_index("volume")] == 24_000.0
    assert panel.feature_values[0, first_asset, panel.feature_index("amount")] > 200_000.0
    assert panel.feature_values[
        0, first_asset, panel.feature_index("research_close")
    ] == 20.4
    expected = (11.0 * 3.0) / (10.2 * 2.0) - 1.0
    assert np.isclose(
        panel.feature_values[1, first_asset, panel.feature_index("simple_return_1")],
        expected,
    )
    assert not panel.eligibility_mask[0, panel.asset_index(universe[1])]
    assert panel.eligibility_mask[1, panel.asset_index(universe[1])]
    assert dataset.metadata["volume_unit"] == "shares"
    assert dataset.metadata["amount_unit"] == "CNY"


def test_1min_adapter_excludes_opening_auction_and_maps_end_timestamps(tmp_path) -> None:
    layout = _layout(tmp_path)
    adapter = LocalAshareParquetDataAdapter(
        layout,
        frequency=AshareBarFrequency.MINUTE_1,
        include_opening_auction=False,
    )
    asset = _asset("000001", "SZSE")
    start = datetime(2024, 1, 2, 9, 30, tzinfo=SHANGHAI).astimezone(UTC)
    end = datetime(2024, 1, 2, 15, 1, tzinfo=SHANGHAI).astimezone(UTC)
    calendar = adapter.calendar(start, end, (asset,))

    assert len(calendar) == 240
    assert calendar[0].astimezone(SHANGHAI).strftime("%H:%M") == "09:31"
    window = adapter.feature_window(
        datetime(2024, 1, 2, 9, 31, tzinfo=SHANGHAI).astimezone(UTC),
        (asset,),
        ("close", "volume"),
        1,
    )
    assert window.timestamps[0].astimezone(SHANGHAI).strftime("%H:%M") == "09:31"
    execution = adapter.execution_snapshot(
        datetime(2024, 1, 2, 9, 30, tzinfo=SHANGHAI).astimezone(UTC),
        (asset,),
        price_field="open",
    )
    assert execution.quotes[asset].event_time.astimezone(SHANGHAI).strftime(
        "%H:%M"
    ) == "09:30"
    assert execution.quotes[asset].available_at == execution.quotes[asset].event_time


def test_local_dataset_inspector_certifies_241_rows_and_daily_reconciliation(
    tmp_path,
) -> None:
    layout = _layout(tmp_path)
    report = LocalAshareDatasetInspector(layout).inspect(
        intraday_symbol="000001.SZ",
        intraday_date=date(2024, 1, 2),
    )

    assert report.passed
    assert report.intraday["rows"] == 241
    assert report.intraday["canonical_continuous_rows"] == 240
    assert report.intraday["opening_auction_row"] is True
    assert report.reconciliation["passed"] is True
    assert any(issue.code == "LA-INTRA-04" for issue in report.issues)


def test_uncertified_intraday_frequency_fails_closed(tmp_path) -> None:
    layout = _layout(tmp_path)
    (tmp_path / "stock_5min").mkdir()
    with pytest.raises(ValueError, match="not been timestamp-certified"):
        LocalAshareParquetDataAdapter(layout, frequency=AshareBarFrequency.MINUTE_5)

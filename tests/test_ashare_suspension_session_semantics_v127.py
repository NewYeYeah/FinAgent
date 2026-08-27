from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from finagent.data import (
    LocalAshareDatasetInspector,
    LocalAshareDatasetLayout,
    LocalAshareParquetDataAdapter,
    LocalAshareSecurityMaster,
)
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.research import DatasetRequest, TimeRange

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _write_parquet(
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
    duckdb.connect().execute(
        f"COPY (SELECT * FROM read_csv_auto('{csv_path.as_posix()}', HEADER=TRUE)) "
        f"TO '{parquet_path.as_posix()}' (FORMAT PARQUET)"
    )
    return parquet_path


def _layout(tmp_path: Path) -> LocalAshareDatasetLayout:
    _write_parquet(
        tmp_path,
        "stock_basic_data",
        [
            "ts_code",
            "name",
            "market",
            "list_date",
            "delist_date",
            "list_status",
        ],
        [
            ["000001.SZ", "A", "主板", "1991-04-03", "", ""],
            ["600000.SH", "B", "主板", "1999-11-10", "", ""],
        ],
    )
    _write_parquet(
        tmp_path,
        "stock_daily",
        [
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "vol",
            "amount",
            "adj_factor",
            "suspend_type",
        ],
        [
            ["000001.SZ", "2024-01-02", 10.0, 10.2, 9.8, 10.0, 9.9, 100.0, 1000.0, 1.0, "N"],
            ["000001.SZ", "2024-01-03", 0.0, 0.0, 0.0, 10.0, 10.0, 0.0, 0.0, 1.0, "S"],
            ["000001.SZ", "2024-01-04", 11.0, 11.2, 10.8, 11.0, 10.0, 120.0, 1300.0, 1.0, "N"],
            ["600000.SH", "2024-01-02", 20.0, 20.2, 19.8, 20.0, 19.9, 100.0, 2000.0, 1.0, "N"],
            ["600000.SH", "2024-01-03", 21.0, 21.2, 20.8, 21.0, 20.0, 100.0, 2100.0, 1.0, "N"],
            ["600000.SH", "2024-01-04", 22.0, 22.2, 21.8, 22.0, 21.0, 100.0, 2200.0, 1.0, "N"],
        ],
    )
    return LocalAshareDatasetLayout(tmp_path)


def _asset(symbol: str, venue: str) -> AssetId:
    return AssetId(symbol, AssetType.EQUITY, venue=venue, currency="CNY")


def test_certification_classifies_strict_no_trade_placeholder_as_warning(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    report = LocalAshareDatasetInspector(layout).inspect()

    assert report.passed
    assert report.daily["suspension_placeholders"] == 1
    assert report.daily["nonpositive_prices"] == 0
    assert report.daily["invalid_ohlc"] == 0
    assert report.daily["anomaly_samples"] == []
    assert report.daily["suspension_placeholder_samples"][0]["ts_code"] == "000001.SZ"
    assert any(issue.code == "LA-DAILY-07" for issue in report.issues)
    assert not any(issue.code in {"LA-DAILY-03", "LA-DAILY-04"} for issue in report.issues)


def test_daily_research_excludes_suspension_and_keeps_forward_horizon_on_panel_clock(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    master = LocalAshareSecurityMaster.from_parquet(layout.basic_path)
    adapter = LocalAshareParquetDataAdapter(layout, security_master=master)
    suspended = _asset("000001", "SZSE")
    continuous = _asset("600000", "SSE")
    split = TimeRange(
        datetime(2024, 1, 2, 0, 0, tzinfo=SHANGHAI).astimezone(UTC),
        datetime(2024, 1, 5, 0, 0, tzinfo=SHANGHAI).astimezone(UTC),
    )
    dataset = adapter.build_dataset(
        DatasetRequest(
            universe=(suspended, continuous),
            features=("close",),
            labels=("forward_simple_return_1",),
            splits={"development": split},
            dataset_id="suspension-session-clock",
        )
    )
    panel = dataset.get_split("development")

    assert len(panel.timestamps) == 3
    suspended_index = panel.asset_index(suspended)
    continuous_index = panel.asset_index(continuous)
    label_index = panel.label_index("forward_simple_return_1")

    # The suspended asset has no tradable observation on the common Jan-03 session.
    assert not panel.eligibility_mask[1, suspended_index]
    assert np.isnan(panel.feature_values[1, suspended_index, 0])

    # One-session forward return from Jan-02 must not jump across the suspension to Jan-04.
    assert np.isnan(panel.label_values[0, suspended_index, label_index])
    assert np.isclose(panel.label_values[0, continuous_index, label_index], 21.0 / 20.0 - 1.0)
    assert panel.metadata["forward_label_clock"] == "common_panel_sessions"
    assert dataset.metadata["daily_nontrading_placeholder"] == "excluded_from_price_bars"

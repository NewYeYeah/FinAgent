from __future__ import annotations

import csv
from pathlib import Path

from finagent.data import (
    LocalAshareDatasetInspector,
    LocalAshareDatasetLayout,
    LocalAshareSecurityMaster,
)


def _write_parquet(
    tmp_path: Path, name: str, header: list[str], rows: list[list[object]]
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
            "area",
            "industry",
            "act_name",
            "act_ent_type",
        ],
        [
            [
                "000001.SZ",
                "平安银行",
                "主板",
                "1991-04-03",
                "",
                "",
                "深圳",
                "银行",
                "",
                "",
            ],
            [
                "T00018.SH",
                "上港集箱",
                "历史",
                "2000-07-19",
                "",
                "",
                "上海",
                "港口",
                "",
                "",
            ],
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
        ],
        [
            [
                "000001.SZ",
                "2024-01-02",
                10.0,
                10.5,
                9.8,
                10.2,
                10.0,
                100.0,
                1000.0,
                1.0,
            ],
            ["000001.SZ", "2024-01-03", 0.0, 0.0, 1.0, 0.0, 10.2, 0.0, 0.0, 1.0],
        ],
    )
    return LocalAshareDatasetLayout(tmp_path)


def test_security_master_quarantines_noncanonical_legacy_code(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    master = LocalAshareSecurityMaster.from_parquet(layout.basic_path)

    assert master.excluded_vendor_codes == ("T00018.SH",)
    assert len(master.records) == 1
    assert master.records[0].ts_code == "000001.SZ"
    assert any("T00018.SH" in item for item in master.limitations)


def test_certification_reports_legacy_codes_and_daily_anomaly_rows(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    report = LocalAshareDatasetInspector(layout).inspect()

    assert not report.passed
    assert report.basic["noncanonical_ts_codes"] == 1
    assert report.basic["noncanonical_samples"][0]["ts_code"] == "T00018.SH"
    assert any(issue.code == "LA-BASIC-05" for issue in report.issues)
    assert report.daily["nonpositive_prices"] == 1
    assert report.daily["invalid_ohlc"] == 1
    assert report.daily["anomaly_samples"] == [
        {
            "ts_code": "000001.SZ",
            "trade_date": "2024-01-03",
            "open": 0.0,
            "high": 0.0,
            "low": 1.0,
            "close": 0.0,
            "pre_close": 10.2,
            "vol": 0.0,
            "amount": 0.0,
            "adj_factor": 1.0,
        }
    ]

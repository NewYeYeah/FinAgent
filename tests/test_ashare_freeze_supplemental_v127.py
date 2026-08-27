from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from finagent.data import (
    AshareBarFrequency,
    AshareSupplementalDataStore,
    LocalAshareDatasetLayout,
    LocalAshareFrozenManifest,
    LocalAshareSecurityMaster,
    SupplementedAshareSecurityMaster,
    create_local_ashare_frozen_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def _write_reference(root: Path, *, delisting: str = "") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "sources.toml").write_text(
        """
[dataset]
coverage = "partial"
notes = "test"

[sources.exchange]
name = "Test exchange"
authority = "TEST"
url = "https://example.test/exchange"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "delistings.csv").write_text(
        "ts_code,effective_date,decision_date,source_id,source_url,observed_at,notes\n"
        + delisting,
        encoding="utf-8",
    )
    (root / "st_periods.csv").write_text(
        "ts_code,start_date,end_date,status,source_id,source_url,observed_at,notes\n",
        encoding="utf-8",
    )
    (root / "suspensions.csv").write_text(
        "ts_code,start_time,end_time,reason,source_id,source_url,observed_at,notes\n",
        encoding="utf-8",
    )


def _write_parquet_from_csv(csv_path: Path, parquet_path: Path) -> None:
    source = csv_path.resolve().as_posix().replace("'", "''")
    target = parquet_path.resolve().as_posix().replace("'", "''")
    duckdb.connect().execute(
        f"COPY (SELECT * FROM read_csv_auto('{source}', header=true)) "
        f"TO '{target}' (FORMAT PARQUET)"
    )


def _vendor_dataset(root: Path, *, assets: int = 6) -> tuple[str, ...]:
    root.mkdir(parents=True, exist_ok=True)
    codes = tuple(f"00000{index + 1}.SZ" for index in range(assets))
    basic_csv = root / "basic.csv"
    with basic_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ts_code", "name", "market", "list_date", "delist_date", "list_status"])
        for index, code in enumerate(codes):
            writer.writerow([code, f"TEST{index}", "主板", "2020-01-01", "", ""])
    _write_parquet_from_csv(basic_csv, root / "stock_basic_data.parquet")

    daily_csv = root / "daily.csv"
    fields = [
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
        "turnover_rate",
        "circ_mv",
    ]
    with daily_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        trading_days: list[date] = []
        cursor = date(2024, 1, 2)
        while len(trading_days) < 110:
            if cursor.weekday() < 5:
                trading_days.append(cursor)
            cursor += timedelta(days=1)
        for asset_index, code in enumerate(codes):
            previous = 10.0 + asset_index
            growth = 1.0005 + asset_index * 0.0003
            for row_index, day in enumerate(trading_days):
                close = previous * growth
                open_ = previous * (1.0 + 0.0001 * ((row_index + asset_index) % 3 - 1))
                high = max(open_, close) * 1.01
                low = min(open_, close) * 0.99
                writer.writerow(
                    {
                        "ts_code": code,
                        "trade_date": day.isoformat(),
                        "open": f"{open_:.6f}",
                        "high": f"{high:.6f}",
                        "low": f"{low:.6f}",
                        "close": f"{close:.6f}",
                        "pre_close": f"{previous:.6f}",
                        "vol": 1000 + row_index + asset_index * 50,
                        "amount": 20_000 + row_index * 100 + asset_index * 1000,
                        "adj_factor": 1.0,
                        "turnover_rate": 1.0 + asset_index * 0.1,
                        "circ_mv": 100_000 + asset_index * 10_000,
                    }
                )
                previous = close
    _write_parquet_from_csv(daily_csv, root / "stock_daily.parquet")
    return codes


def test_supplemental_store_is_partial_versioned_and_source_bound(tmp_path) -> None:
    root = tmp_path / "reference"
    _write_reference(
        root,
        delisting=(
            "000001.SZ,2024-03-01,2024-02-20,exchange,https://example.test/notice," 
            "2024-02-20T12:00:00+00:00,test record\n"
        ),
    )
    first = AshareSupplementalDataStore.from_directory(root)
    assert first.coverage == "partial"
    assert not first.is_complete
    assert first.delisting("000001.SZ").effective_date == date(2024, 3, 1)
    version = first.data_version

    with (root / "delistings.csv").open("a", encoding="utf-8") as handle:
        handle.write(
            "000002.SZ,2024-04-01,,exchange,https://example.test/notice2,"
            "2024-03-20T12:00:00+00:00,second\n"
        )
    second = AshareSupplementalDataStore.from_directory(root)
    assert second.data_version != version


def test_supplemental_master_applies_delisting_without_certifying_history(tmp_path) -> None:
    vendor = tmp_path / "vendor"
    _vendor_dataset(vendor)
    reference = tmp_path / "reference"
    _write_reference(
        reference,
        delisting=(
            "000001.SZ,2024-03-01,2024-02-20,exchange,https://example.test/notice,"
            "2024-02-20T12:00:00+00:00,test\n"
        ),
    )
    base = LocalAshareSecurityMaster.from_parquet(vendor / "stock_basic_data.parquet")
    supplement = AshareSupplementalDataStore.from_directory(reference)
    master = SupplementedAshareSecurityMaster(base, supplement)
    record = next(item for item in master.records if item.ts_code == "000001.SZ")
    assert record.delist_date == date(2024, 3, 1)
    assert master.applied_delistings == 1
    assert not master.survivorship_certified
    assert supplement.data_version in master.data_version


def test_frozen_manifest_content_hash_detects_vendor_mutation(tmp_path) -> None:
    vendor = tmp_path / "vendor"
    _vendor_dataset(vendor)
    layout = LocalAshareDatasetLayout(vendor)
    manifest = create_local_ashare_frozen_manifest(
        layout,
        frequencies=(AshareBarFrequency.DAILY,),
        content_hash=True,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    path = tmp_path / "frozen.json"
    manifest.write_json(path)
    loaded = LocalAshareFrozenManifest.read_json(path)
    loaded.verify(layout, verify_content=True)
    assert loaded.dataset_version == manifest.dataset_version

    daily = vendor / "stock_daily.parquet"
    daily.write_bytes(daily.read_bytes() + b"mutation")
    with pytest.raises(ValueError, match="size changed"):
        loaded.verify(layout, verify_content=False)


def test_local_ashare_system_smoke_uses_frozen_dataset_and_common_research_contract(tmp_path) -> None:
    vendor = tmp_path / "vendor"
    codes = _vendor_dataset(vendor)
    reference = tmp_path / "reference"
    _write_reference(reference)
    layout = LocalAshareDatasetLayout(vendor)
    manifest = create_local_ashare_frozen_manifest(
        layout,
        frequencies=(AshareBarFrequency.DAILY,),
        content_hash=False,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    manifest_path = tmp_path / "frozen.json"
    manifest.write_json(manifest_path)
    report_path = tmp_path / "report.json"
    config = tmp_path / "smoke.toml"
    symbols = ", ".join(f'"{code}"' for code in codes)
    config.write_text(
        f"""
[local_ashare_research_smoke]
root = "{vendor.as_posix()}"
frozen_manifest = "{manifest_path.as_posix()}"
supplement_root = "{reference.as_posix()}"
report_path = "{report_path.as_posix()}"
symbols = [{symbols}]
development_start = 2024-01-01
development_end_exclusive = 2024-03-15
validation_start = 2024-03-15
validation_end_exclusive = 2024-06-30
features = ["simple_return_1", "simple_return_5", "log_volume_change_1", "turnover_rate", "circ_mv"]
labels = ["forward_simple_return_1", "forward_simple_return_5"]
primary_feature = "simple_return_5"
primary_label = "forward_simple_return_1"
min_cross_section = 5
min_periods = 10
""".strip()
        + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_local_ashare_research_smoke.py"), str(config)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["scope"] == "historical_daily_research_only_no_execution_no_realtime"
    assert payload["frozen_dataset_version"] == manifest.dataset_version
    assert payload["security_master"]["survivorship_certified"] is False
    assert payload["research_dataset"]["data_version"] == manifest.dataset_version
    assert payload["splits"]["development"]["rank_ic_periods"] >= 10
    assert payload["splits"]["validation"]["rank_ic_periods"] >= 10

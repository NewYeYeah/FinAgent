from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from finagent.data.provenance import load_dataset_authority_config
from finagent.data.us_minute import (
    HuggingFaceSnapshotLayout,
    admit_local_non_redistributed_research,
    certify_local_minute_snapshot,
    inventory_monthly_parquet,
)

REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"


def _duckdb():
    return pytest.importorskip("duckdb")


def _write_month(path: Path, *, duplicate: bool = False) -> None:
    duckdb = _duckdb()
    con = duckdb.connect(database=":memory:")
    con.execute(
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
    rows = [
        (datetime(2026, 1, 5, 13, 0, tzinfo=UTC), 100.0, 101.0, 99.0, 100.5, 10.0, "AAPL"),
        (datetime(2026, 1, 5, 15, 0, tzinfo=UTC), 100.5, 102.0, 100.0, 101.0, 20.0, "AAPL"),
        (datetime(2026, 1, 5, 15, 1, tzinfo=UTC), 200.0, 201.0, 199.0, 200.5, 30.0, "MSFT"),
    ]
    if duplicate:
        rows.append(rows[1])
    con.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    escaped = path.as_posix().replace("'", "''")
    con.execute(f"COPY bars TO '{escaped}' (FORMAT PARQUET)")
    con.close()


def _make_cache(tmp_path: Path, *, months: tuple[str, ...], duplicate_month: str = "") -> Path:
    root = tmp_path / "datasets--mito0o852--OHLCV-1m"
    snapshot = root / "snapshots" / REVISION
    data = snapshot / "data"
    data.mkdir(parents=True)
    (root / "refs").mkdir(parents=True)
    (root / "refs" / "main").write_text(REVISION + "\n", encoding="utf-8")
    (snapshot / "README.md").write_text("# synthetic fixture\n", encoding="utf-8")
    for month in months:
        _write_month(data / f"ohlcv_{month}.parquet", duplicate=month == duplicate_month)
    return root


def test_resolves_huggingface_cache_layout_and_inventory(tmp_path: Path) -> None:
    root = _make_cache(tmp_path, months=("2026-01", "2026-02", "2026-03"))
    layout = HuggingFaceSnapshotLayout.resolve(root, expected_revision=REVISION)
    inventory = inventory_monthly_parquet(layout)

    assert layout.revision == REVISION
    assert inventory.start_month == "2026-01"
    assert inventory.end_month == "2026-03"
    assert inventory.missing_months == ()
    assert len(inventory.files) == 3
    assert inventory.inventory_id.startswith("us-minute-inventory-")


def test_rejects_cache_ref_drift(tmp_path: Path) -> None:
    root = _make_cache(tmp_path, months=("2026-01",))
    (root / "refs" / "main").write_text("a" * 40 + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="refs/main"):
        HuggingFaceSnapshotLayout.resolve(root, expected_revision=REVISION)


def test_certification_passes_schema_quality_and_extended_hours(tmp_path: Path) -> None:
    root = _make_cache(tmp_path, months=("2026-01", "2026-02", "2026-03"))
    certification = certify_local_minute_snapshot(
        root,
        expected_revision=REVISION,
        expected_coverage_start="2026-01",
        expected_coverage_end="2026-03",
        sample_months=("2026-01", "2026-03"),
        certified_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert certification.passed
    assert certification.extended_hours_observed
    assert all(item.passed for item in certification.sample_checks)


def test_certification_fails_missing_partition(tmp_path: Path) -> None:
    root = _make_cache(tmp_path, months=("2026-01", "2026-03"))
    certification = certify_local_minute_snapshot(
        root,
        expected_revision=REVISION,
        expected_coverage_start="2026-01",
        expected_coverage_end="2026-03",
        certified_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert not certification.passed
    assert certification.missing_months == ("2026-02",)


def test_certification_fails_incomplete_expected_coverage(tmp_path: Path) -> None:
    root = _make_cache(tmp_path, months=("2026-02", "2026-03"))
    certification = certify_local_minute_snapshot(
        root,
        expected_revision=REVISION,
        expected_coverage_start="2026-01",
        expected_coverage_end="2026-03",
        certified_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert not certification.passed
    assert certification.coverage_start == "2026-02"


def test_certification_fails_duplicate_ticker_timestamp(tmp_path: Path) -> None:
    root = _make_cache(tmp_path, months=("2026-01", "2026-02"), duplicate_month="2026-01")
    certification = certify_local_minute_snapshot(
        root,
        expected_revision=REVISION,
        expected_coverage_start="2026-01",
        expected_coverage_end="2026-02",
        sample_months=("2026-01",),
        certified_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert not certification.passed
    assert certification.sample_checks[0].duplicate_key_count > 0


def test_reference_source_can_receive_local_non_redistributed_admission(tmp_path: Path) -> None:
    root = _make_cache(tmp_path, months=("2026-01", "2026-02", "2026-03"))
    authority = load_dataset_authority_config(
        Path("configs/us_source_authority/mito0o852_ohlcv_1m.toml")
    )
    certification = certify_local_minute_snapshot(
        root,
        expected_revision=REVISION,
        expected_coverage_start="2026-01",
        expected_coverage_end="2026-03",
        certified_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    admission = admit_local_non_redistributed_research(
        authority.bundle,
        certification,
        admitted_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert admission.scope == "local_non_redistributed_research"
    assert admission.source_authority_status.value == "reference_only"
    assert "usage_rights:unresolved" in admission.limitations
    assert "prices:intraday_raw_split_unadjusted" in admission.limitations
    assert admission.admission_id.startswith("us-minute-local-admission-")

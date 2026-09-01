from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from finagent.data.provenance import load_dataset_authority_config
from finagent.data.us_minute import (
    CONFLICT_TOLERANT_BASE_POLICY,
    DEFAULT_CONFLICT_QUARANTINE_POLICY,
    ConflictGroupQuarantinePolicy,
    MinuteSampleQuality,
    admit_local_research_with_conflict_quarantine,
    certify_local_minute_snapshot_with_conflict_quarantine,
    conflicting_raw_row_count,
    conflicting_raw_row_rate,
    quarantined_clean_month_select_sql,
)

REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"
NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _duckdb():
    return pytest.importorskip("duckdb")


def _make_cache(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "datasets--mito0o852--OHLCV-1m"
    snapshot = root / "snapshots" / REVISION
    data = snapshot / "data"
    data.mkdir(parents=True)
    (root / "refs").mkdir(parents=True)
    (root / "refs" / "main").write_text(REVISION + "\n", encoding="utf-8")
    (snapshot / "README.md").write_text("# synthetic fixture\n", encoding="utf-8")
    return root, data


def _write_rows(path: Path, rows: list[tuple[object, ...]]) -> None:
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
    con.executemany("INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    escaped = path.as_posix().replace("'", "''")
    con.execute(f"COPY bars TO '{escaped}' (FORMAT PARQUET)")
    con.close()


def _observed_march_sample() -> MinuteSampleQuality:
    return MinuteSampleQuality(
        month="2026-03",
        row_count=34_379_927,
        ticker_count=22_057,
        min_timestamp="2026-03-02T09:00:00+00:00",
        max_timestamp="2026-03-31T23:59:00+00:00",
        duplicate_key_count=409,
        exact_duplicate_key_count=17,
        conflicting_duplicate_key_count=392,
        exact_duplicate_extra_row_count=17,
        conflicting_duplicate_extra_row_count=407,
        invalid_identity_count=0,
        invalid_ohlc_count=0,
        negative_volume_count=0,
        outside_regular_hours_count=3_093_885,
        outside_0400_2000_count=1,
    )


def test_real_march_conflict_rate_fits_frozen_quarantine_ceiling() -> None:
    sample = _observed_march_sample()

    assert sample.passed(CONFLICT_TOLERANT_BASE_POLICY)
    assert conflicting_raw_row_count(sample) == 799
    assert conflicting_raw_row_rate(sample) == pytest.approx(799 / 34_379_927)
    assert conflicting_raw_row_rate(sample) < (
        DEFAULT_CONFLICT_QUARANTINE_POLICY.max_conflicting_raw_row_rate
    )


def test_quarantine_ceiling_still_rejects_structural_conflict_density() -> None:
    sample = _observed_march_sample()
    strict = ConflictGroupQuarantinePolicy(max_conflicting_raw_row_rate=1e-5)

    assert conflicting_raw_row_rate(sample) > strict.max_conflicting_raw_row_rate


def test_quarantined_read_drops_whole_conflicting_key_and_collapses_exact_rows(
    tmp_path: Path,
) -> None:
    _, data = _make_cache(tmp_path)
    t0 = datetime(2026, 3, 31, 18, 7, tzinfo=UTC)
    t1 = datetime(2026, 3, 31, 18, 8, tzinfo=UTC)
    conflict_a = (t0, 100.0, 101.0, 99.0, 100.5, 1000.0, "AAPL")
    conflict_b = (t0, 100.1, 101.2, 99.0, 100.7, 2500.0, "AAPL")
    exact = (t1, 101.0, 101.5, 100.5, 101.25, 500.0, "AAPL")
    path = data / "ohlcv_2026-03.parquet"
    _write_rows(path, [conflict_a, conflict_b, exact, exact])

    duckdb = _duckdb()
    con = duckdb.connect(database=":memory:")
    sql = quarantined_clean_month_select_sql(path)
    try:
        result = con.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT ticker) FROM ({sql})"
        ).fetchone()
    finally:
        con.close()

    assert result is not None
    assert tuple(map(int, result)) == (1, 1)


def test_v3_certification_and_admission_bind_quarantine_policy(tmp_path: Path) -> None:
    root, data = _make_cache(tmp_path)
    t0 = datetime(2026, 3, 31, 18, 7, tzinfo=UTC)
    t1 = datetime(2026, 3, 31, 18, 8, tzinfo=UTC)
    _write_rows(
        data / "ohlcv_2026-03.parquet",
        [
            (t0, 100.0, 101.0, 99.0, 100.5, 1000.0, "AAPL"),
            (t0, 100.1, 101.2, 99.0, 100.7, 2500.0, "AAPL"),
            (t1, 101.0, 101.5, 100.5, 101.25, 500.0, "AAPL"),
        ],
    )
    permissive = ConflictGroupQuarantinePolicy(max_conflicting_raw_row_rate=0.75)
    certification = certify_local_minute_snapshot_with_conflict_quarantine(
        root,
        expected_revision=REVISION,
        expected_coverage_start="2026-03",
        expected_coverage_end="2026-03",
        sample_months=("2026-03",),
        quarantine_policy=permissive,
        certified_at=NOW,
    )

    assert certification.passed
    assert certification.quarantined_conflicting_key_count == 1
    assert certification.quarantined_conflicting_raw_row_count == 2
    assert certification.to_dict()["post_clean_conflicting_duplicate_key_count"] == 0

    authority = load_dataset_authority_config(
        Path("configs/us_source_authority/mito0o852_ohlcv_1m.toml")
    )
    admission = admit_local_research_with_conflict_quarantine(
        authority.bundle,
        certification,
        admitted_at=NOW,
    )

    assert admission.certification_id == certification.certification_id
    assert admission.cleaning_policy_id == certification.cleaning_identity
    assert "cleaning:quarantine_entire_conflicting_duplicate_key_group" in (
        admission.limitations
    )

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from finagent.data.provenance import load_dataset_authority_config
from finagent.data.us_minute import (
    DEFAULT_MINUTE_CLEANING_POLICY,
    MinuteDataCleaningPolicy,
    MinuteSampleQuality,
    admit_local_research_with_cleaning,
    certify_local_minute_research_snapshot,
    clean_month_select_sql,
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


def _quality(**overrides: int) -> MinuteSampleQuality:
    values: dict[str, object] = {
        "month": "2026-03",
        "row_count": 34_379_927,
        "ticker_count": 22_057,
        "min_timestamp": "2026-03-02T09:00:00+00:00",
        "max_timestamp": "2026-03-31T23:59:00+00:00",
        "duplicate_key_count": 409,
        "exact_duplicate_key_count": 409,
        "conflicting_duplicate_key_count": 0,
        "exact_duplicate_extra_row_count": 409,
        "conflicting_duplicate_extra_row_count": 0,
        "invalid_identity_count": 0,
        "invalid_ohlc_count": 0,
        "negative_volume_count": 0,
        "outside_regular_hours_count": 3_093_885,
        "outside_0400_2000_count": 1,
    }
    values.update(overrides)
    return MinuteSampleQuality(**values)  # type: ignore[arg-type]


def test_default_policy_accepts_sparse_quarantinable_anomaly_rates() -> None:
    early = _quality(
        row_count=4_609_974,
        duplicate_key_count=0,
        exact_duplicate_key_count=0,
        exact_duplicate_extra_row_count=0,
        invalid_ohlc_count=1,
    )
    recent = _quality()

    assert early.invalid_ohlc_rate < DEFAULT_MINUTE_CLEANING_POLICY.max_invalid_ohlc_rate
    assert recent.exact_duplicate_extra_row_rate < (
        DEFAULT_MINUTE_CLEANING_POLICY.max_exact_duplicate_extra_row_rate
    )
    assert early.passed(DEFAULT_MINUTE_CLEANING_POLICY)
    assert recent.passed(DEFAULT_MINUTE_CLEANING_POLICY)


def test_conflicting_duplicate_key_remains_fail_closed() -> None:
    sample = _quality(
        conflicting_duplicate_key_count=1,
        conflicting_duplicate_extra_row_count=1,
        exact_duplicate_key_count=408,
        exact_duplicate_extra_row_count=408,
    )

    assert not sample.passed(DEFAULT_MINUTE_CLEANING_POLICY)


def test_certification_classifies_exact_and_conflicting_duplicates(tmp_path: Path) -> None:
    root, data = _make_cache(tmp_path)
    base = (
        datetime(2026, 3, 2, 14, 30, tzinfo=UTC),
        100.0,
        101.0,
        99.0,
        100.5,
        10.0,
        "AAPL",
    )
    exact_rows = [base, base]
    _write_rows(data / "ohlcv_2026-03.parquet", exact_rows)
    permissive = MinuteDataCleaningPolicy(max_exact_duplicate_extra_row_rate=0.75)

    exact = certify_local_minute_research_snapshot(
        root,
        expected_revision=REVISION,
        expected_coverage_start="2026-03",
        expected_coverage_end="2026-03",
        sample_months=("2026-03",),
        cleaning_policy=permissive,
        certified_at=NOW,
    )
    check = exact.sample_checks[0]
    assert check.duplicate_key_count == 1
    assert check.exact_duplicate_key_count == 1
    assert check.conflicting_duplicate_key_count == 0
    assert exact.passed

    conflicting_rows = [base, (*base[:4], 100.75, *base[5:])]
    _write_rows(data / "ohlcv_2026-03.parquet", conflicting_rows)
    conflict = certify_local_minute_research_snapshot(
        root,
        expected_revision=REVISION,
        expected_coverage_start="2026-03",
        expected_coverage_end="2026-03",
        sample_months=("2026-03",),
        cleaning_policy=permissive,
        certified_at=NOW,
    )
    conflict_check = conflict.sample_checks[0]
    assert conflict_check.conflicting_duplicate_key_count == 1
    assert not conflict.passed


def test_clean_query_drops_invalid_ohlc_and_collapses_exact_rows(tmp_path: Path) -> None:
    _, data = _make_cache(tmp_path)
    valid = (
        datetime(2026, 3, 2, 14, 30, tzinfo=UTC),
        100.0,
        101.0,
        99.0,
        100.5,
        10.0,
        "AAPL",
    )
    invalid = (
        datetime(2026, 3, 2, 14, 31, tzinfo=UTC),
        100.0,
        99.0,
        100.0,
        100.0,
        12.0,
        "AAPL",
    )
    path = data / "ohlcv_2026-03.parquet"
    _write_rows(path, [valid, valid, invalid])

    duckdb = _duckdb()
    con = duckdb.connect(database=":memory:")
    clean_sql = clean_month_select_sql(path)
    try:
        clean_count = con.execute(f"SELECT COUNT(*) FROM ({clean_sql})").fetchone()
        ticker_count = con.execute(
            f"SELECT COUNT(DISTINCT ticker) FROM ({clean_sql})"
        ).fetchone()
    finally:
        con.close()

    assert clean_count is not None and int(clean_count[0]) == 1
    assert ticker_count is not None and int(ticker_count[0]) == 1


def test_cleaning_policy_is_part_of_certification_identity(tmp_path: Path) -> None:
    root, data = _make_cache(tmp_path)
    _write_rows(
        data / "ohlcv_2026-03.parquet",
        [
            (
                datetime(2026, 3, 2, 14, 30, tzinfo=UTC),
                100.0,
                101.0,
                99.0,
                100.5,
                10.0,
                "AAPL",
            )
        ],
    )
    first = certify_local_minute_research_snapshot(
        root,
        expected_revision=REVISION,
        expected_coverage_start="2026-03",
        expected_coverage_end="2026-03",
        certified_at=NOW,
    )
    second = certify_local_minute_research_snapshot(
        root,
        expected_revision=REVISION,
        expected_coverage_start="2026-03",
        expected_coverage_end="2026-03",
        cleaning_policy=replace(
            DEFAULT_MINUTE_CLEANING_POLICY,
            max_invalid_ohlc_rate=2e-6,
        ),
        certified_at=NOW,
    )

    assert first.cleaning_policy.policy_id != second.cleaning_policy.policy_id
    assert first.certification_id != second.certification_id


def test_admission_binds_cleaning_policy_and_quarantine_limitations(tmp_path: Path) -> None:
    root, data = _make_cache(tmp_path)
    valid = (
        datetime(2026, 3, 2, 14, 30, tzinfo=UTC),
        100.0,
        101.0,
        99.0,
        100.5,
        10.0,
        "AAPL",
    )
    _write_rows(data / "ohlcv_2026-03.parquet", [valid, valid])
    authority = load_dataset_authority_config(
        Path("configs/us_source_authority/mito0o852_ohlcv_1m.toml")
    )
    permissive = MinuteDataCleaningPolicy(max_exact_duplicate_extra_row_rate=0.75)
    certification = certify_local_minute_research_snapshot(
        root,
        expected_revision=REVISION,
        expected_coverage_start="2026-03",
        expected_coverage_end="2026-03",
        cleaning_policy=permissive,
        certified_at=NOW,
    )

    admission = admit_local_research_with_cleaning(
        authority.bundle,
        certification,
        admitted_at=NOW,
    )

    assert admission.cleaning_policy_id == permissive.policy_id
    assert "cleaning:collapse_exact_duplicate_full_rows" in admission.limitations
    assert admission.scope == "local_non_redistributed_research"

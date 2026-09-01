from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from finagent.data.us_minute import diagnose_local_minute_conflicts

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


def test_conflict_diagnostic_classifies_fields_patterns_and_raw_rows(tmp_path: Path) -> None:
    root, data = _make_cache(tmp_path)
    base_time = datetime(2026, 3, 2, 14, 30, tzinfo=UTC)

    exact = (base_time, 100.0, 101.0, 99.0, 100.5, 10.0, "AAPL")
    volume_only_a = (base_time + timedelta(minutes=1), 100.0, 101.0, 99.0, 100.5, 10.0, "MSFT")
    volume_only_b = (base_time + timedelta(minutes=1), 100.0, 101.0, 99.0, 100.5, 12.0, "MSFT")
    price_only_a = (base_time + timedelta(minutes=2), 200.0, 202.0, 198.0, 201.0, 20.0, "NVDA")
    price_only_b = (base_time + timedelta(minutes=2), 200.0, 203.0, 198.0, 202.0, 20.0, "NVDA")
    both_a = (base_time + timedelta(minutes=3), 300.0, 302.0, 299.0, 301.0, 30.0, "TSLA")
    both_b = (base_time + timedelta(minutes=3), 300.0, 303.0, 299.0, 302.0, 31.0, "TSLA")

    _write_rows(
        data / "ohlcv_2026-03.parquet",
        [
            exact,
            exact,
            volume_only_a,
            volume_only_b,
            price_only_a,
            price_only_b,
            both_a,
            both_b,
            both_b,
        ],
    )
    rows_output = tmp_path / "conflicting_rows.csv"

    diagnostic = diagnose_local_minute_conflicts(
        root,
        expected_revision=REVISION,
        month="2026-03",
        examples=10,
        rows_output=rows_output,
        diagnosed_at=NOW,
    )

    assert diagnostic.unresolved
    assert diagnostic.duplicate_key_count == 4
    assert diagnostic.exact_duplicate_key_count == 1
    assert diagnostic.exact_duplicate_extra_row_count == 1
    assert diagnostic.conflicting_duplicate_key_count == 3
    assert diagnostic.conflicting_duplicate_extra_row_count == 4
    assert diagnostic.conflicting_raw_row_count == 7
    assert diagnostic.conflicting_ticker_count == 3
    assert diagnostic.max_rows_per_conflicting_key == 3
    assert diagnostic.conflicting_keys_over_two_rows == 1
    assert dict(diagnostic.field_conflict_counts) == {
        "open": 0,
        "high": 2,
        "low": 0,
        "close": 2,
        "volume": 2,
    }
    assert dict(diagnostic.pattern_counts) == {
        "volume_only": 1,
        "price_only": 1,
        "price_and_volume": 1,
    }
    assert diagnostic.examples[0].ticker == "TSLA"
    assert diagnostic.examples[0].group_rows == 3
    assert diagnostic.examples[0].distinct_variant_count == 2
    assert diagnostic.examples[0].differing_fields == ("high", "close", "volume")

    with rows_output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 7
    assert {row["ticker"] for row in rows} == {"MSFT", "NVDA", "TSLA"}
    assert {row["diagnostic_variant_rank"] for row in rows if row["ticker"] == "TSLA"} == {
        "1",
        "2",
        "3",
    }


def test_diagnostic_identity_excludes_wall_clock_time(tmp_path: Path) -> None:
    root, data = _make_cache(tmp_path)
    row = (datetime(2026, 3, 2, 14, 30, tzinfo=UTC), 100.0, 101.0, 99.0, 100.5, 10.0, "AAPL")
    conflicting = (
        datetime(2026, 3, 2, 14, 30, tzinfo=UTC),
        100.0,
        101.0,
        99.0,
        100.5,
        11.0,
        "AAPL",
    )
    _write_rows(data / "ohlcv_2026-03.parquet", [row, conflicting])

    first = diagnose_local_minute_conflicts(
        root,
        expected_revision=REVISION,
        month="2026-03",
        diagnosed_at=NOW,
    )
    second = diagnose_local_minute_conflicts(
        root,
        expected_revision=REVISION,
        month="2026-03",
        diagnosed_at=NOW + timedelta(hours=1),
    )

    assert first.diagnostic_id == second.diagnostic_id


def test_diagnostic_handles_month_without_duplicate_conflicts(tmp_path: Path) -> None:
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

    diagnostic = diagnose_local_minute_conflicts(
        root,
        expected_revision=REVISION,
        month="2026-03",
        diagnosed_at=NOW,
    )

    assert not diagnostic.unresolved
    assert diagnostic.duplicate_key_count == 0
    assert diagnostic.conflicting_duplicate_key_count == 0
    assert diagnostic.conflicting_raw_row_count == 0
    assert diagnostic.examples == ()
    assert diagnostic.min_conflict_timestamp == ""
    assert diagnostic.max_conflict_timestamp == ""


def test_diagnostic_rejects_unknown_month(tmp_path: Path) -> None:
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

    with pytest.raises(ValueError, match="not present"):
        diagnose_local_minute_conflicts(
            root,
            expected_revision=REVISION,
            month="2026-02",
            diagnosed_at=NOW,
        )

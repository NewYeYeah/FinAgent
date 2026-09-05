from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from finagent.research import us_r3_usability as usability
from finagent.research.us_a1_factor_materialization import compile_factor_graph_batch
from finagent.research.us_a1_factor_panel_materialization import materialize_compiled_factor_panel
from finagent.research.us_r3_alpha_catalog import build_us_r3_executable_frontier_candidates


def _source(path: Path, *, bad_interval: bool = False, label: float = 0.0) -> Path:
    connection = duckdb.connect()
    connection.execute("""
        CREATE TABLE bars (
            slice_id VARCHAR, session_date DATE, session_id VARCHAR,
            research_asset_id VARCHAR, event_time TIMESTAMPTZ, available_at TIMESTAMPTZ,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE,
            is_complete BOOLEAN, signal_interval VARCHAR, label_value DOUBLE
        )
    """)
    rows = []
    for day in range(2):
        for index in range(14):
            stamp = datetime(2006, 1, 3 + day, 14, 30, tzinfo=UTC) + timedelta(minutes=15 * index)
            for asset in range(4):
                close = 100 + asset * 3 + (asset - 1.5) * index * 0.1 + (index % 3) * 0.07
                rows.append(
                    (
                        usability.SLICE_ID,
                        stamp.date(),
                        stamp.date().isoformat(),
                        f"A{asset}",
                        stamp,
                        stamp + timedelta(minutes=15),
                        close - 0.03,
                        close + 0.2,
                        close - 0.2,
                        close,
                        1000 + asset * 37 + index * 11,
                        not (asset == 3 and index == 1),
                        "5m" if bad_interval else "15m",
                        label,
                    )
                )
    connection.executemany(
        "INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )
    connection.execute("COPY bars TO ? (FORMAT PARQUET)", [str(path)])
    connection.close()
    return path


def test_real_parquet_operator_checks_all_candidates_and_resumes_without_scans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _source(tmp_path / "base.parquet")
    events = []
    result = usability.run_usability(
        (source,), tmp_path / "out", progress=lambda event, _: events.append(event)
    )
    assert result["passed"] is True
    assert result["candidate_count"] == 3
    assert result["session_count"] == 2
    assert result["row_count"] == 112
    assert result["peak_session_rows"] == 56
    assert result["labels_read"] is False
    assert result["alpha_gate_evaluated"] is False
    assert events.count("session_start") == 2
    original = {path.name: path.read_bytes() for path in (tmp_path / "out").iterdir()}

    def no_scan(*args: object) -> None:
        pytest.fail("resumability must not query Parquet or evaluate features")

    monkeypatch.setattr(usability, "iter_feature_sessions", no_scan)
    resumed = usability.run_usability((source,), tmp_path / "out")
    assert resumed["evidence_id"] == result["evidence_id"]
    assert resumed["evaluated_source_count"] == 0
    assert resumed["resumed_source_count"] == 1
    assert original == {path.name: path.read_bytes() for path in (tmp_path / "out").iterdir()}


def test_label_mutation_cannot_change_any_feature_digest(tmp_path: Path) -> None:
    for index, label in enumerate((1.0, -999.0)):
        source = _source(tmp_path / f"base{index}.parquet", label=label)
        usability.run_usability((source,), tmp_path / f"out{index}")
    first = json.loads(next((tmp_path / "out0").glob("source_*.json")).read_text())
    second = json.loads(next((tmp_path / "out1").glob("source_*.json")).read_text())
    assert first["feature_digest"] == second["feature_digest"]
    assert first["candidate_available_counts"] == second["candidate_available_counts"]
    assert "label_value" not in usability.FEATURE_QUERY


def test_interruption_preserves_first_source_and_resumes_remaining_source(tmp_path: Path) -> None:
    first = _source(tmp_path / "first.parquet", label=1)
    second = _source(tmp_path / "second.parquet", label=2)

    def interrupt(event: str, _: object) -> None:
        if event == "source_complete":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        usability.run_usability((first, second), tmp_path / "out", progress=interrupt)
    assert len(list((tmp_path / "out").glob("source_*.json"))) == 1
    resumed = usability.run_usability((first, second), tmp_path / "out")
    assert resumed["resumed_source_count"] == resumed["evaluated_source_count"] == 1


def test_tampered_evidence_and_changed_bindings_fail_closed(tmp_path: Path) -> None:
    source = _source(tmp_path / "base.parquet")
    output = tmp_path / "out"
    usability.run_usability((source,), output)
    with pytest.raises(ValueError, match="immutable evidence mismatch"):
        usability.run_usability((source,), output, minimum_cross_section=2)
    report = next(output.glob("source_*.json"))
    original = json.loads(report.read_text())
    original["session_count"] = 500
    report.write_text(json.dumps(original))
    with pytest.raises(ValueError, match="content identity mismatch"):
        usability.run_usability((source,), output)


def test_reference_catches_numerical_regression(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path / "base.parquet")
    original = usability.materialize_compiled_factor_panel

    def wrong(*args, **kwargs):
        result = original(*args, **kwargs)
        first = result.candidates[0]
        values = list(first.values)
        values[-1] += 0.01
        return replace(
            result, candidates=(replace(first, values=tuple(values)), *result.candidates[1:])
        )

    monkeypatch.setattr(usability, "materialize_compiled_factor_panel", wrong)
    with pytest.raises(ValueError, match="reference numeric mismatch"):
        usability.run_usability((source,), tmp_path / "out")
    assert not list((tmp_path / "out").glob("source_*.json"))


@pytest.mark.parametrize("invalid_index", [0, 5, 12])
def test_all_formulas_match_independent_reference_with_partial_inputs(
    tmp_path: Path,
    invalid_index: int,
) -> None:
    source = _source(tmp_path / "base.parquet")
    _, assets, _ = next(usability.iter_feature_sessions(source))
    bars = list(assets[0].bars)
    bars[invalid_index] = replace(bars[invalid_index], is_complete=False)
    assets = (replace(assets[0], bars=tuple(bars)), *assets[1:])
    candidates = build_us_r3_executable_frontier_candidates()
    compiled = compile_factor_graph_batch(
        tuple(item.graph for item in candidates), admit_panel_operators=True
    )
    actual = materialize_compiled_factor_panel(compiled, assets, minimum_cross_section=3)
    expected = usability.reference_signals(assets, 3)
    for series in actual.candidates:
        candidate_index = [item.candidate_id for item in candidates].index(series.candidate_id)
        assert series.values == pytest.approx(
            tuple(row[candidate_index] for row in expected[series.asset_id])
        )


def test_cli_emits_flushed_progress_final_json_and_clear_failure(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "PYTHONPATH": str(root / "src")}
    command = [sys.executable, str(root / "scripts/check_us_r3_alpha_usability.py")]
    source = _source(tmp_path / "base.parquet")
    success = subprocess.run(
        command + ["--source", str(source), "--output-root", str(tmp_path / "ok")],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert success.returncode == 0
    assert json.loads(success.stdout)["passed"] is True
    assert '"event": "session_start"' in success.stderr
    bad = _source(tmp_path / "bad.parquet", bad_interval=True)
    failure = subprocess.run(
        command + ["--source", str(bad), "--output-root", str(tmp_path / "bad")],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert failure.returncode == 1
    assert '"event": "failed"' in failure.stderr
    assert "Traceback" in failure.stderr
    assert "15m interval" in failure.stderr


def test_session_bound_is_checked_before_panel_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path / "base.parquet")
    monkeypatch.setattr(usability, "MAXIMUM_SESSION_ROWS", 10)
    with pytest.raises(ValueError, match="row bound"):
        list(usability.iter_feature_sessions(source))


def test_empty_source_is_not_reported_usable(tmp_path: Path) -> None:
    source = _source(tmp_path / "base.parquet")
    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE empty AS SELECT * FROM read_parquet(?) WHERE false", [str(source)]
    )
    connection.execute("COPY empty TO ? (FORMAT PARQUET)", [str(tmp_path / "empty.parquet")])
    connection.close()
    result = usability.run_usability((tmp_path / "empty.parquet",), tmp_path / "out")
    assert result["passed"] is False
    assert result["row_count"] == 0


@pytest.mark.parametrize("entire_formation", [False, True])
def test_missing_source_rows_are_masked_not_forward_filled(
    tmp_path: Path, entire_formation: bool
) -> None:
    source = _source(tmp_path / "base.parquet")
    connection = duckdb.connect()
    connection.execute("CREATE TABLE sparse AS SELECT * FROM read_parquet(?)", [str(source)])
    # Delete an internal bar from one asset or the entire formation. Preserve
    # source session endpoints; the adapter restores the clock, never a price.
    connection.execute(
        "DELETE FROM sparse WHERE minute(event_time AT TIME ZONE 'UTC') = 45 "
        "AND hour(event_time AT TIME ZONE 'UTC') = 14 "
        "AND (? OR research_asset_id = 'A0')",
        [entire_formation],
    )
    sparse = tmp_path / "sparse.parquet"
    connection.execute("COPY sparse TO ? (FORMAT PARQUET)", [str(sparse)])
    connection.close()
    _, assets, observed = next(usability.iter_feature_sessions(sparse))
    assert len(assets[0].bars) == 14
    assert observed == 56 - (4 if entire_formation else 1)
    assert assets[0].bars[1].is_complete is False
    result = usability.run_usability((sparse,), tmp_path / "out")
    assert result["missing_bar_padding_count"] == (8 if entire_formation else 2)
    assert result["passed"] is True
    assert result["reference_parity_passed"] is True


def test_immutable_publish_does_not_overwrite_and_cleans_staging_files(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    usability.write_immutable_json(path, {"value": 1})
    original = path.read_bytes()
    with pytest.raises(ValueError, match="immutable"):
        usability.write_immutable_json(path, {"value": 2})
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".r3-*"))

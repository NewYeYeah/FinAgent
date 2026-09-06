from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime

import duckdb
import pytest

from finagent.application.adaptive_research import run_adaptive_research_slice
from finagent.domain.research import TimeRange
from finagent.research.adaptive_inputs import bind_development_source
from finagent.research.factor_library import (
    FactorLibrary,
    FactorOrigin,
    FactorRegistration,
    FactorStatus,
)
from finagent.research.factor_library_evaluation import FactorEvaluationConfig
from finagent.research.market_state import MarketFeatureConfig
from finagent.research.market_state_gmm import GMMConfig, MarketStateModel
from finagent.research.us_r3_alpha_catalog import build_us_r3_executable_frontier_candidates
from finagent.research.us_r3_economics import EconomicPolicy
from tests.test_us_r3_economic_campaign import fixture_inputs


def slice_inputs(root, *, label=0.0):
    paths = fixture_inputs(root, label=label)
    source = bind_development_source(
        *paths,
        source_id="synthetic-fixture",
        source_revision="v1",
        universe=("A0", "A1", "A2", "A3"),
    )
    fit = TimeRange(datetime(2025, 1, 2, tzinfo=UTC), datetime(2025, 1, 3, tzinfo=UTC))
    evaluation = TimeRange(fit.end, datetime(2025, 1, 4, tzinfo=UTC))
    factors = tuple(
        FactorRegistration(
            item.graph,
            item.strategy.slug,
            item.strategy.mechanism,
            item.hypothesis.summary,
            FactorOrigin.MANUAL,
            (
                ("prototype", item.strategy.strategy_id),
                ("prior_terminal", "WORKFLOW_VERIFIED_NO_CONFIRMED_ALPHA"),
            ),
            fit.start,
        )
        for item in build_us_r3_executable_frontier_candidates()
    )
    config = FactorEvaluationConfig(EconomicPolicy(minimum_breadth=3, selection_count=1))
    return paths, source, factors, fit, evaluation, config


def execute(values, output, **kwargs):
    _, source, factors, fit, evaluation, config = values
    return run_adaptive_research_slice(
        source,
        factors,
        fit,
        evaluation,
        output,
        feature_config=MarketFeatureConfig("A0"),
        evaluation_config=config,
        **kwargs,
    )


def test_parquet_ohlcv_to_state_graph_registry_metrics_and_deterministic_replay(tmp_path):
    values = slice_inputs(tmp_path / "inputs")
    first = execute(values, tmp_path / "run")
    persisted = (tmp_path / "run/result.json").read_bytes()
    assert first == execute(values, tmp_path / "run") == execute(values, tmp_path / "other")
    assert (
        (tmp_path / "run/result.json").read_bytes()
        == persisted
        == (tmp_path / "other/result.json").read_bytes()
    )
    assert len(first["states"]) == 26
    assert len(first["factor_evaluations"]) == 3
    assert first["evaluation_data_status"] == "EVALUABLE"
    model = MarketStateModel.from_dict(
        json.loads((tmp_path / "run/market_state_model.json").read_text())
    )
    assert model.model_id == first["model_id"]
    assert model.source == values[1].identity
    library = FactorLibrary(tmp_path / "run/factor_library.sqlite", read_only=True)
    try:
        assert len(library.list_factors(status=FactorStatus.TESTING)) == 3
        for item, expected in zip(values[2], first["factor_evaluations"], strict=True):
            record = library.get(item.factor_id)
            assert record["graph"] == item.graph.to_dict()
            assert record["provenance"]["prior_terminal"] == "WORKFLOW_VERIFIED_NO_CONFIRMED_ALPHA"
            reports = library.evaluations(item.factor_id)
            assert len(reports) == 1
            assert reports[0]["evaluation_id"] == expected["evaluation_id"]
            assert reports[0]["global"]["coverage"] > 0
            assert len(reports[0]["by_market_state"]) == 4
    finally:
        library.close()
    assert all(first[k] is False for k in ("alpha_authority", "paper_authority", "live_authority"))


def test_future_label_columns_cannot_change_model_states_or_economics(tmp_path):
    first = execute(slice_inputs(tmp_path / "a", label=999.0), tmp_path / "out-a")
    second = execute(slice_inputs(tmp_path / "b", label=-999.0), tmp_path / "out-b")
    assert first["model_id"] == second["model_id"]
    assert first["states"] == second["states"]
    assert first["factor_evaluations"] == second["factor_evaluations"]


def test_input_lineage_change_and_calendar_window_fail_closed(tmp_path):
    values = slice_inputs(tmp_path)
    paths, source, _, fit, _, _ = values
    with pytest.raises(ValueError, match="complete calendar sessions"):
        source.read(TimeRange(datetime(2025, 1, 2, 15, tzinfo=UTC), fit.end))
    with pytest.raises(ValueError, match="calendar coverage"):
        source.read(TimeRange(datetime(2024, 1, 1, tzinfo=UTC), fit.end))
    plan = json.loads(paths[2].read_text())
    plan["calendar_id"] = "wrong"
    paths[2].write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="input changed"):
        source.read(fit)
    with pytest.raises(ValueError, match="input changed"):
        execute(values, tmp_path / "failed-run")
    failure = json.loads((tmp_path / "failed-run/failure.json").read_text())
    assert failure["reason"] == "bound development input changed"
    assert not (tmp_path / "failed-run/result.json").exists()
    with pytest.raises(ValueError, match="evidence mismatch"):
        bind_development_source(
            *paths, source_id="fixture", source_revision="v1", universe=source.universe
        )


def test_wholly_missing_day_is_retained_with_unavailable_state_and_factor_coverage(tmp_path):
    paths, _, factors, fit, evaluation, config = slice_inputs(tmp_path / "inputs")
    trimmed = tmp_path / "trimmed.parquet"
    with duckdb.connect() as c:
        c.execute(
            "CREATE TEMP TABLE trimmed AS SELECT * FROM read_parquet(?) WHERE session_date='2025-01-02'",
            [str(paths[0])],
        )
        c.execute("COPY trimmed TO ? (FORMAT PARQUET)", [str(trimmed)])
    evidence = json.loads(paths[3].read_text())
    evidence["row_count"] //= 2
    paths[3].write_text(json.dumps(evidence))
    source = bind_development_source(
        trimmed,
        *paths[1:],
        source_id="fixture",
        source_revision="v1",
        universe=("A0", "A1", "A2", "A3"),
    )
    result = run_adaptive_research_slice(
        source,
        factors,
        fit,
        evaluation,
        tmp_path / "run",
        feature_config=MarketFeatureConfig("A0"),
        evaluation_config=config,
    )
    assert result["evaluation_data_status"] == "NO_EVALUABLE_FACTOR_OBSERVATIONS"
    assert all(row["probabilities"] is None for row in result["states"])
    for report in result["factor_evaluations"]:
        assert report["global"]["coverage"] == 0
        assert report["global"]["economic_scenarios"]["5.0"]["scheduled_sessions"] == 1
        assert report["global"]["economic_scenarios"]["5.0"]["compounded_return"] is None
        assert report["global"]["economic_scenarios"]["5.0"]["unresolved_sessions"] == 1
        assert report["state_unavailable_frames"] == 26


def test_unsuccessful_model_fit_is_persisted_without_authority_or_threshold_changes(tmp_path):
    values = slice_inputs(tmp_path / "inputs")
    with pytest.raises(ValueError, match="INSUFFICIENT"):
        execute(values, tmp_path / "run", gmm_config=GMMConfig(min_train_rows=100))
    failure = json.loads((tmp_path / "run/failure.json").read_text())
    request = json.loads((tmp_path / "run/request.json").read_text())
    assert failure["reason"] == "INSUFFICIENT_TRAIN_FEATURES"
    assert failure["run_id"] == request["run_id"]
    assert request["gmm"]["min_train_rows"] == 100
    assert failure["alpha_authority"] is False
    assert not (tmp_path / "run/result.json").exists()


def test_future_factor_definition_and_overlap_rejected(tmp_path):
    values = slice_inputs(tmp_path / "inputs")
    _, source, factors, fit, evaluation, config = values
    with pytest.raises(ValueError, match="before evaluation"):
        run_adaptive_research_slice(
            source,
            tuple(replace(f, created_at=evaluation.end) for f in factors),
            fit,
            evaluation,
            tmp_path / "bad",
            evaluation_config=config,
            feature_config=MarketFeatureConfig("A0"),
        )
    with pytest.raises(ValueError, match="overlap"):
        run_adaptive_research_slice(
            source,
            factors,
            evaluation,
            fit,
            tmp_path / "bad",
            evaluation_config=config,
            feature_config=MarketFeatureConfig("A0"),
        )


def test_cli_executes_real_slice_and_inspect_is_read_only(tmp_path):
    paths, _, _, fit, evaluation, _ = slice_inputs(tmp_path / "inputs")
    output = tmp_path / "run"
    command = [sys.executable, "scripts/run_r4_research_slice.py", "run"]
    for name, path in zip(("source", "calendar", "base-plan", "base-evidence"), paths, strict=True):
        command.extend(["--" + name, str(path)])
    command.extend(
        [
            "--output",
            str(output),
            "--source-id",
            "synthetic-fixture",
            "--source-revision",
            "v1",
            "--universe",
            "A0,A1,A2,A3",
            "--proxy",
            "A0",
            "--minimum-breadth",
            "3",
            "--selection-count",
            "1",
            "--fit-start",
            fit.start.isoformat(),
            "--fit-end",
            fit.end.isoformat(),
            "--evaluation-start",
            evaluation.start.isoformat(),
            "--evaluation-end",
            evaluation.end.isoformat(),
        ]
    )
    run = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["factor_count"] == 3
    db = output / "factor_library.sqlite"
    original = db.read_bytes()
    inspected = subprocess.run(
        [sys.executable, "scripts/run_r4_research_slice.py", "inspect", "--library", str(db)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert inspected.returncode == 0, inspected.stderr
    assert len(json.loads(inspected.stdout)) == 3
    assert original == db.read_bytes()

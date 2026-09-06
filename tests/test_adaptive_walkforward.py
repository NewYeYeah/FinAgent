from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta

import pytest

from finagent.application.adaptive_portfolio import load_factor_pool
from finagent.research.adaptive_walkforward import validate_walkforward
from finagent.research.factor_library import FactorLibrary, FactorRegistration, FactorStatus
from finagent.research.market_state_gmm import GMMConfig
from tests.adaptive_allocator_fixture import execute, mutated_source, portfolio_inputs


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    root = tmp_path_factory.mktemp("walkforward")
    inputs = portfolio_inputs(root / "inputs")
    report = execute(inputs, root / "baseline")
    return root, inputs, report


def test_parquet_real_graphs_five_allocators_three_folds_and_persisted_weight_series(completed):
    root, inputs, report = completed
    assert len(report["folds"]) == 3
    assert report["terminal"] == "DETERMINISTIC_WALKFORWARD_COMPLETE"
    assert all(report[k] is False for k in ("alpha_authority", "paper_authority", "live_authority"))
    assert len({f["state_model"]["model_id"] for f in report["folds"]}) == 3
    assert len({f["ridge_model"]["model_id"] for f in report["folds"]}) == 3
    for fold in report["folds"]:
        assert fold["ridge_model"]["sample_count"] >= 8
        assert fold["ridge_model"]["fallback_reason"] is None
        assert len(fold["performance_history"]) == 11 * 3
        assert set(fold["arms"]) == {
            "equal_weight",
            "rolling_ic",
            "rolling_net_return",
            "regime_conditional",
            "ridge_meta",
        }
        reference_support = None
        for arm in fold["arms"].values():
            weights = arm["factor_weight_series"]
            assert len(weights) == 3 * 26
            support = [(r["normalized_signal_id"], r["data_fallback_reason"]) for r in weights]
            if reference_support is not None:
                assert support == reference_support
            reference_support = support
            for row in weights:
                assert tuple(row["weights"]) == tuple(fold["factor_ids"])
                assert sum(row["weights"].values()) == pytest.approx(1)
                assert min(row["weights"].values()) >= 0
                if row["history_cutoff"]:
                    assert row["history_cutoff"] <= row["session_open"] < row["as_of"]
                if row["target"]:
                    assert len(row["target"]) == 1 and sum(row["target"].values()) == 1
                else:
                    assert row["data_fallback_reason"] == "INSUFFICIENT_COMMON_FACTOR_SUPPORT"
            assert set(arm["cost_scenarios"]) == {"0.0", "1.0", "5.0", "10.0"}
            for cost, metrics in arm["cost_scenarios"].items():
                assert metrics["scheduled_sessions"] == metrics["resolved_sessions"] == 3
                assert metrics["active_sessions"] > 0
                assert metrics["cost"] == pytest.approx(
                    float(cost) / 10000 * metrics["gross_traded_notional"]
                )
                assert metrics["turnover"] == pytest.approx(0.5 * metrics["gross_traded_notional"])
                assert 1 / 3 - 1e-12 <= metrics["mean_factor_weight_concentration"] <= 1 + 1e-12
                assert len(metrics["by_market_state"]["states"]) == 4
        for observation in fold["performance_history"]:
            assert observation["decision_time"] < observation["outcome_available_at"]
            for decision in observation["decisions"]:
                if decision["outcome_available_at"]:
                    assert (
                        decision["decision_time"]
                        < decision["outcome_available_at"]
                        <= observation["outcome_available_at"]
                    )
                if decision["state_probabilities"]:
                    assert decision["decision_time"] >= fold["state_model"]["available_at"]
    library = FactorLibrary(root / "baseline/factor_library.sqlite", read_only=True)
    try:
        assert len(library.list_factors()) == 3
        for factor in inputs["factors"]:
            assert len(library.evaluations(factor.factor_id)) == 3
            assert library.get(factor.factor_id)["provenance"] == dict(factor.provenance)
    finally:
        library.close()
    assert json.loads((root / "baseline/result.json").read_text())["overall"] == report["overall"]


def test_replay_has_identical_results_and_no_duplicate_registry_evaluations(completed):
    root, inputs, report = completed
    before = (root / "baseline/result.json").read_bytes()
    assert execute(inputs, root / "baseline") == report
    assert (root / "baseline/result.json").read_bytes() == before
    assert execute(inputs, root / "replay")["folds"] == report["folds"]
    assert (root / "replay/result.json").read_bytes() == before


def test_later_fold_mutation_cannot_change_previous_fold_bytes(completed):
    root, inputs, baseline = completed
    boundary = inputs["folds"][2].train.start.isoformat()
    changed = mutated_source(
        inputs,
        root / "later.parquet",
        f"UPDATE bars SET open=open*1.7, high=high*1.7, low=low*1.7, close=close*1.7 WHERE event_time >= TIMESTAMPTZ '{boundary}'",
    )
    result = execute(changed, root / "later-run")
    for i in (0, 1):
        assert json.dumps(result["folds"][i], sort_keys=True) == json.dumps(
            baseline["folds"][i], sort_keys=True
        )


def test_future_intraday_outcomes_and_later_sessions_cannot_change_previous_weights(completed):
    root, inputs, baseline = completed
    start = inputs["folds"][0].evaluation.start
    boundary = start + timedelta(minutes=15 * 14)
    changed = mutated_source(
        inputs,
        root / "future.parquet",
        f"UPDATE bars SET open=open*1.3, high=high*1.3, low=low*1.3, close=close*1.3 WHERE event_time >= TIMESTAMPTZ '{boundary.isoformat()}' AND event_time < TIMESTAMPTZ '{inputs['folds'][0].evaluation.end.isoformat()}'",
    )
    result = execute(changed, root / "future-run")
    assert result["folds"][0]["state_model"] == baseline["folds"][0]["state_model"]
    assert result["folds"][0]["ridge_model"] == baseline["folds"][0]["ridge_model"]
    for arm in baseline["folds"][0]["arms"]:
        before = baseline["folds"][0]["arms"][arm]["factor_weight_series"]
        after = result["folds"][0]["arms"][arm]["factor_weight_series"]
        assert before[:14] == after[:14]
        if arm != "regime_conditional":
            assert [r["weights"] for r in before[:26]] == [r["weights"] for r in after[:26]]
    assert result["folds"][0]["performance_history"] != baseline["folds"][0]["performance_history"]


def test_unused_parquet_label_columns_cannot_change_any_fold(completed):
    root, inputs, baseline = completed
    changed = mutated_source(inputs, root / "labels.parquet", "UPDATE bars SET label_value=-999999")
    result = execute(changed, root / "labels-run")
    assert result["folds"] == baseline["folds"]
    assert result["overall"] == baseline["overall"]


def test_missing_session_retained_and_failure_recorded_without_changing_thresholds(completed):
    root, inputs, _ = completed
    session_date = inputs["folds"][0].evaluation.start.date().isoformat()
    changed = mutated_source(
        inputs,
        root / "missing.parquet",
        f"UPDATE bars SET is_complete=false WHERE session_date=DATE '{session_date}'",
    )
    result = execute(changed, root / "missing-run")
    for arm, evidence in result["folds"][0]["arms"].items():
        metrics = evidence["cost_scenarios"]["5.0"]
        assert metrics["scheduled_sessions"] == 3 and metrics["unresolved_sessions"] == 1
        assert metrics["compounded_return"] is None
        assert metrics["unavailable_signal_frames"] >= 26
        assert result["overall"][arm]["5.0"]["mean_fold_compounded_return"] is None
    with pytest.raises(ValueError, match="INSUFFICIENT"):
        execute(inputs, root / "failure-run", gmm_config=GMMConfig(min_train_rows=1000))
    failure = json.loads((root / "failure-run/failure.json").read_text())
    assert failure["completed_folds"] == [] and failure["alpha_authority"] is False
    assert not (root / "failure-run/result.json").exists()


def test_fold_boundaries_and_execution_policy_fail_closed(completed):
    _, inputs, _ = completed
    folds, factors, policy = inputs["folds"], inputs["factors"], inputs["economics"]
    with pytest.raises(ValueError, match="state_fit_end"):
        replace(folds[0], state_fit_end=folds[0].evaluation.start)
    with pytest.raises(ValueError, match="nonoverlapping"):
        validate_walkforward(factors, (folds[0], replace(folds[0], name="duplicate-time")), policy)
    with pytest.raises(ValueError, match="before first TRAIN"):
        validate_walkforward(
            tuple(replace(f, created_at=folds[0].train.end) for f in factors), folds, policy
        )
    with pytest.raises(ValueError, match="freezes strict_15m"):
        validate_walkforward(factors, folds, replace(policy, delay_bars=2))
    with pytest.raises(ValueError, match="0/1/5/10bp"):
        validate_walkforward(factors, folds, replace(policy, cost_bps=(0.0, 5.0)))


def test_cli_loads_actual_library_without_reading_aggregate_metrics_or_mutating_input(completed):
    root, inputs, baseline = completed
    original = inputs["library"].read_bytes()
    command = [
        sys.executable,
        "scripts/run_r4_walkforward.py",
        "--source",
        str(inputs["paths"][0]),
        "--calendar",
        str(inputs["paths"][1]),
        "--base-plan",
        str(inputs["paths"][2]),
        "--base-evidence",
        str(inputs["paths"][3]),
        "--library",
        str(inputs["library"]),
        "--folds",
        str(root / "inputs/folds.json"),
        "--source-id",
        "synthetic-walkforward",
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
        "--output",
        str(root / "cli"),
    ]
    response = subprocess.run(command, check=True, capture_output=True, text=True)
    assert json.loads(response.stdout)["allocator_count"] == 5
    assert inputs["library"].read_bytes() == original
    result = json.loads((root / "cli/result.json").read_text())
    assert json.dumps(result["folds"], sort_keys=True) == json.dumps(
        baseline["folds"], sort_keys=True
    )
    loaded, _ = load_factor_pool(inputs["library"])
    assert [f.to_dict() for f in loaded] == [f.to_dict() for f in inputs["factors"]]
    request = json.loads((root / "cli/request.json").read_text())
    assert request["input_library_binding"]
    assert request["ridge"]["alpha"] == 1 and request["quality"]["lookback_sessions"] == 20


def test_registry_restore_rejects_tampered_graph_authority_and_retired_pool(completed):
    root, inputs, _ = completed
    factor = inputs["factors"][0]
    payload = factor.to_dict()
    payload["graph"]["label_access"] = True
    with pytest.raises(ValueError, match="content identity"):
        FactorRegistration.from_dict(payload)
    path = root / "rejected.sqlite"
    library = FactorLibrary(path)
    library.register(factor)
    library.transition(
        factor.factor_id,
        FactorStatus.REJECTED,
        at=factor.created_at,
        actor="test",
        reason="test rejected pool",
    )
    library.close()
    with pytest.raises(ValueError, match="nonterminal"):
        load_factor_pool(path)


def test_failure_retains_completed_fold_and_does_not_relax_partial_session_boundary(completed):
    root, inputs, baseline = completed
    folds = list(inputs["folds"])
    folds[1] = replace(folds[1], state_fit_end=folds[1].state_fit_end - timedelta(minutes=7))
    with pytest.raises(ValueError, match="complete separate TRAIN"):
        execute({**inputs, "folds": tuple(folds)}, root / "partial-run")
    failure = json.loads((root / "partial-run/failure.json").read_text())
    assert len(failure["completed_folds"]) == 1
    assert json.dumps(failure["completed_folds"][0], sort_keys=True) == json.dumps(
        baseline["folds"][0], sort_keys=True
    )
    assert not (root / "partial-run/result.json").exists()

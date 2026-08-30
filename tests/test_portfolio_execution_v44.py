from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finagent.backtest import (
    canonical_execution_ledger_digest,
    materialize_strategy_decision_rows,
    write_strategy_decision_series,
)
from finagent.visualization.workbench_api import create_workspace_app
from tests.test_strategy_decision_series_v40 import (
    ASSET,
    _alpha,
    _synthetic_ledger,
    _write_jsonl,
)
from tests.test_visualization_semantic_contract_v2 import _a2p6_report, _a4_report


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _write_v44(tmp_path: Path) -> tuple[str, str]:
    ledger = _synthetic_ledger()
    ledger_digest = canonical_execution_ledger_digest(ledger)

    a26 = _a2p6_report()
    a26_path = tmp_path / "a26.json"
    a26_path.write_text(json.dumps(a26, sort_keys=True), encoding="utf-8")

    report = _a4_report()
    report["ledger_digest"] = ledger_digest
    spec = report["validation_spec"]
    assert isinstance(spec, dict)
    spec["source_report_digest"] = hashlib.sha256(
        _canonical_json(a26).encode("utf-8")
    ).hexdigest()
    spec["validation_config"] = {
        "initial_cash": 1000.0,
        "annualization": 252.0,
    }

    folds = report["folds"]
    assert isinstance(folds, list)
    fold = folds[0]
    assert isinstance(fold, dict)
    fold["fold_id"] = "wf-1"
    fold["points"] = [
        {
            "session_date": "2024-01-02",
            "signal_asof": "2024-01-02T01:29:59.999999+00:00",
            "rebalanced": True,
            "cash_fallback": False,
            "target_id": "a4-target-1",
            "net_nav": 1044.0,
            "gross_nav": 1050.0,
            "net_return": 0.044,
            "gross_return": 0.05,
            "fees": 1.0,
            "slippage": 5.0,
            "gross_traded_weight": 0.5,
            "one_way_turnover": 0.25,
            "target_turnover": 0.5,
            "implementation_shortfall": 0.01,
            "desired_order_count": 1,
            "order_count": 1,
            "fill_count": 1,
            "rejected_order_count": 0,
            "maximum_ex_post_participation": 0.05,
            "reason_counts": {"ACCEPTED": 1},
        },
        {
            "session_date": "2024-01-03",
            "signal_asof": "2024-01-03T01:29:59.999999+00:00",
            "rebalanced": False,
            "cash_fallback": False,
            "target_id": "",
            "net_nav": 1094.0,
            "gross_nav": 1100.0,
            "net_return": 50.0 / 1044.0,
            "gross_return": 50.0 / 1050.0,
            "fees": 0.0,
            "slippage": 0.0,
            "gross_traded_weight": 0.0,
            "one_way_turnover": 0.0,
            "target_turnover": 0.0,
            "implementation_shortfall": 0.0,
            "desired_order_count": 0,
            "order_count": 0,
            "fill_count": 0,
            "rejected_order_count": 0,
            "maximum_ex_post_participation": 0.0,
            "reason_counts": {},
        },
    ]
    fold["net_metrics"] = {
        "periods": 2,
        "total_return": 0.094,
        "annualized_return": 0.2,
        "annualized_volatility": 0.1,
        "sharpe": 1.5,
        "max_drawdown": 0.0,
    }
    fold["gross_metrics"] = {
        "periods": 2,
        "total_return": 0.1,
        "annualized_return": 0.22,
        "annualized_volatility": 0.1,
        "sharpe": 1.7,
        "max_drawdown": 0.0,
    }
    fold["total_fees"] = 1.0
    fold["total_slippage"] = 5.0
    fold["total_one_way_turnover"] = 0.25
    fold["average_implementation_shortfall"] = 0.005
    fold["maximum_ex_post_participation"] = 0.05
    fold["reason_counts"] = {"ACCEPTED": 1}
    fold["ledger_digest"] = ledger_digest

    aggregate = report["aggregate"]
    assert isinstance(aggregate, dict)
    aggregate["net_metrics"] = dict(fold["net_metrics"])
    aggregate["gross_metrics"] = dict(fold["gross_metrics"])
    aggregate["total_fees"] = 1.0
    aggregate["total_slippage"] = 5.0
    aggregate["total_one_way_turnover"] = 0.25
    aggregate["average_implementation_shortfall"] = 0.005
    aggregate["maximum_ex_post_participation"] = 0.05
    aggregate["desired_order_count"] = 1
    aggregate["order_count"] = 1
    aggregate["fill_count"] = 1
    aggregate["rejected_order_count"] = 0
    aggregate["reason_counts"] = {"ACCEPTED": 1}

    report_path = tmp_path / "a4.json"
    ledger_path = tmp_path / "a4.jsonl"
    manifest_path = tmp_path / "a4.strategy-decisions.json"
    data_path = tmp_path / "a4.strategy-decisions.parquet"
    report_path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    _write_jsonl(ledger_path, ledger)

    rows = materialize_strategy_decision_rows(
        ledger_rows=ledger,
        expected_ledger_digest=ledger_digest,
        initial_cash=1000.0,
        alpha_provider=_alpha,
    )
    manifest = write_strategy_decision_series(
        a4_report=report,
        rows=rows,
        source_report_path=report_path,
        source_ledger_path=ledger_path,
        manifest_path=manifest_path,
        data_path=data_path,
    )
    return manifest.portfolio_validation_id, manifest.series_id


def test_v44_links_a4_portfolio_and_v40_decisions_without_browser_authority(
    tmp_path: Path,
) -> None:
    validation_id, series_id = _write_v44(tmp_path)
    app = create_workspace_app(
        report_paths=(tmp_path,),
        config_paths=(),
        frontend_dir=None,
    )
    client = TestClient(app)

    status = client.get("/api/v4/portfolio-execution/status")
    assert status.status_code == 200
    assert status.json()["item_count"] == 1
    assert status.json()["browser_recomputation"] is False
    assert status.json()["benchmark_available"] is False
    assert status.json()["order_id_available"] is True

    catalog = client.get("/api/v4/portfolio-execution")
    assert catalog.status_code == 200
    assert catalog.json()["items"][0]["portfolio_validation_id"] == validation_id
    assert catalog.json()["items"][0]["strategy_series_id"] == series_id

    detail = client.get(f"/api/v4/portfolio-execution/{validation_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["portfolio_metrics"]["net_sharpe"] == pytest.approx(1.5)
    assert payload["authority"]["portfolio_metrics"] == "authoritative_a4_report"
    assert payload["presentation"]["browser_recomputation"] is False
    assert payload["presentation"]["benchmark_available"] is False
    assert payload["presentation"]["order_id_available"] is True

    series = client.get(
        f"/api/v4/portfolio-execution/{validation_id}/series",
        params={"fold_id": "wf-1", "start": "2024-01-02", "end": "2024-01-03"},
    )
    assert series.status_code == 200
    assert series.json()["authority"] == "authoritative_a4_points"
    assert series.json()["total"] == 2
    assert series.json()["items"][0]["net_nav"] == pytest.approx(1044.0)

    analytics = client.get(
        f"/api/v4/portfolio-execution/{validation_id}/analytics",
        params={"fold_id": "wf-1", "start": "2024-01-02", "end": "2024-01-03"},
    )
    assert analytics.status_code == 200
    derived = analytics.json()
    assert derived["drawdown"]["authority"] == "derived_presentation"
    assert derived["rolling"]["authority"] == "derived_presentation"
    assert derived["monthly_returns"]["authority"] == "derived_presentation"
    assert derived["filtered_costs"]["authority"] == "derived_presentation"
    assert derived["filtered_costs"]["fees"] == pytest.approx(1.0)
    assert derived["filtered_costs"]["slippage"] == pytest.approx(5.0)
    assert derived["order_funnel"]["desired"] == 1
    assert derived["order_funnel"]["executable"] == 1
    assert derived["order_funnel"]["filled"] == 1
    assert derived["constraint_attribution"]["reason_counts"]["ACCEPTED"] == 1
    assert derived["benchmark"]["available"] is False

    order = client.get(
        f"/api/v4/portfolio-execution/{validation_id}/decisions",
        params={"order_id": "net-1", "asset": ASSET},
    )
    assert order.status_code == 200
    assert order.json()["authority"] == "authoritative"
    assert order.json()["total"] == 1
    decision = order.json()["items"][0]
    assert decision["client_order_id"] == "net-1"
    assert decision["target_weight"] == pytest.approx(0.5)
    assert decision["realized_weight"] == pytest.approx(550.0 / 1044.0)
    assert decision["constraint_codes"] == ["ACCEPTED"]

    session = client.get(
        f"/api/v4/portfolio-execution/{validation_id}/decisions",
        params={"session_date": "2024-01-03"},
    )
    assert session.status_code == 200
    assert session.json()["total"] == 1
    assert session.json()["items"][0]["client_order_id"] is None


def test_v44_routes_remain_get_only_bounded_and_fail_closed(tmp_path: Path) -> None:
    validation_id, _ = _write_v44(tmp_path)
    app = create_workspace_app(
        report_paths=(tmp_path,),
        config_paths=(),
        frontend_dir=None,
    )
    client = TestClient(app)

    assert client.get(
        f"/api/v4/portfolio-execution/{validation_id}/series",
        params={"limit": 5001},
    ).status_code == 422
    assert client.get(
        f"/api/v4/portfolio-execution/{validation_id}/decisions",
        params={"limit": 5001},
    ).status_code == 422
    assert client.get(
        f"/api/v4/portfolio-execution/{validation_id}/decisions",
        params={"session_date": "2024-01-02", "start": "2024-01-02"},
    ).status_code == 422
    assert client.get(
        f"/api/v4/portfolio-execution/{validation_id}/analytics",
        params={"window": 1},
    ).status_code == 422

    for path in (
        "/api/v4/portfolio-execution",
        "/api/v4/portfolio-execution/status",
        f"/api/v4/portfolio-execution/{validation_id}",
        f"/api/v4/portfolio-execution/{validation_id}/series",
        f"/api/v4/portfolio-execution/{validation_id}/analytics",
        f"/api/v4/portfolio-execution/{validation_id}/decisions",
    ):
        assert client.post(path).status_code == 405

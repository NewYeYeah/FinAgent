from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from finagent.visualization.workspace_api import create_workspace_app

from tests.test_visualization_semantic_contract_v2 import _a2p6_report, _a4_report


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(prefix: str, value: object) -> str:
    return f"{prefix}-{hashlib.sha256(_canonical_json(value).encode()).hexdigest()}"


def _fixture(root: Path) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    a26 = _a2p6_report()
    gate_config = {
        "min_positive_fold_ratio": 0.75,
        "min_direction_consistency": 0.75,
        "min_pooled_rank_icir": 0.0,
        "min_mean_fold_rank_icir": 0.0,
        "min_worst_fold_rank_icir": -0.05,
        "min_mean_fold_long_short_sharpe": 0.0,
        "min_coverage": 0.90,
        "min_quantile_monotonicity": 0.25,
        "min_horizon_sign_consistency": 0.50,
        "max_hac_pvalue": 0.10,
        "max_bh_qvalue": 0.20,
        "max_mean_one_way_turnover": 1.0,
        "turnover_penalty": 0.5,
    }
    a26["program_spec"]["gate_config"] = gate_config  # type: ignore[index]
    a26["gate_report"]["config"] = gate_config  # type: ignore[index]

    decisions: list[dict[str, object]] = []
    for index in range(10):
        rejected = index >= 8
        decisions.append(
            {
                "desired": {
                    "asset": f"CN:{600000 + index}",
                    "side": "buy",
                    "requested_quantity": 100.0,
                    "current_quantity": 0,
                    "target_quantity": 100.0,
                    "reference_price": 10.0,
                },
                "status": "rejected" if rejected else ("adjusted" if index == 0 else "accepted"),
                "executable_quantity": 0 if rejected else 100,
                "rejected_quantity": 100.0 if rejected else 0.0,
                "reason_codes": [
                    "T1_SELLABLE_QUANTITY_CLIPPED" if rejected else ("BUY_LOT_ROUNDED" if index == 0 else "ACCEPTED")
                ],
                "estimated_fees": {
                    "broker_commission": 5.0,
                    "stamp_duty": 0.0,
                    "transfer_fee": 0.01,
                    "exchange_handling_fee": 0.0,
                    "regulatory_fee": 0.0,
                    "total": 5.01,
                },
                "client_order_id": None if rejected else f"order-{index}",
            }
        )
    fills = [
        {
            "client_order_id": f"order-{index}",
            "asset": f"CN:{600000 + index}",
            "side": "buy",
            "quantity": 100,
            "reference_price": 10.0,
            "execution_price": 10.01,
            "executed_at": "2024-01-02T01:30:00+00:00",
            "notional": 1001.0,
            "fees": {
                "broker_commission": 5.0,
                "stamp_duty": 0.0,
                "transfer_fee": 0.01,
                "exchange_handling_fee": 0.0,
                "regulatory_fee": 0.0,
                "total": 5.01,
            },
            "slippage": 0.5,
            "metadata": {},
        }
        for index in range(7)
    ]
    ledger_rows = [
        {
            "fold_id": "wf-2024",
            "point": {
                "session_date": "2024-01-02",
                "cash_fallback": False,
                "implementation_shortfall": 0.02,
                "maximum_ex_post_participation": 0.03,
            },
            "target": {
                "asof": "2024-01-02T01:29:59+00:00",
                "weights": {"CN:600000": 0.5, "CN:600001": 0.4},
                "cash_weight": 0.1,
                "metadata": {"reason": "MODEL_TARGET"},
            },
            "net_cycle": {
                "compilation": {
                    "decisions": decisions,
                    "orders": [f"order-{index}" for index in range(8)],
                },
                "execution": {
                    "orders": [f"order-{index}" for index in range(8)],
                    "fills": fills,
                    "rejections": {"order-7": "EXCHANGE_REVALIDATION_FAILED"},
                },
            },
            "gross_cycle": None,
            "net_close_state": {
                "session_date": "2024-01-02",
                "cash": 100000.0,
                "nav": 1000000.0,
                "positions": {
                    "CN:600000": {"total_quantity": 45000},
                    "CN:600001": {"total_quantity": 35000},
                },
                "marks": {"CN:600000": 10.0, "CN:600001": 10.0},
            },
            "gross_close_state": {},
            "ex_post_close_snapshot": {},
        }
    ]
    # Use exactly the immutable digest algorithm used by A4 core.
    ledger_digest = _digest("a4-execution-ledger", ledger_rows)
    a4 = _a4_report()
    a4["ledger_digest"] = ledger_digest
    a4["validation_spec"]["source_report_digest"] = hashlib.sha256(  # type: ignore[index]
        _canonical_json(a26).encode()
    ).hexdigest()
    a4["validation_spec"]["net_execution_config"] = {"require_price_limits": True, "slippage_bps": 5.0}  # type: ignore[index]
    a4["validation_spec"]["gross_execution_config"] = {"require_price_limits": True, "slippage_bps": 0.0}  # type: ignore[index]
    a4["validation_spec"]["validation_config"] = {  # type: ignore[index]
        "annualization": 252.0,
        "risk_lookback": 120,
        "risk_min_observations": 60,
        "risk_aversion": 5.0,
        "target_cash_weight": 0.05,
        "max_asset_weight": 0.10,
        "minimum_expected_return": 0.0,
        "optimizer_turnover_penalty": 0.01,
        "active_asset_count": 20,
        "min_active_assets": 5,
        "rebalance_every": 5,
        "alpha_ridge": 1e-8,
        "alpha_min_observations": 250,
        "winsor_lower_quantile": 0.01,
        "winsor_upper_quantile": 0.99,
        "policy": {"min_net_sharpe": 0.0, "max_abs_drawdown": 0.35},
    }
    # Keep the aggregate authoritative counts aligned with the detailed ledger.
    a4["aggregate"]["desired_order_count"] = 10  # type: ignore[index]
    a4["aggregate"]["order_count"] = 8  # type: ignore[index]
    a4["aggregate"]["fill_count"] = 7  # type: ignore[index]
    a4["aggregate"]["rejected_order_count"] = 2  # type: ignore[index]
    a4["aggregate"]["reason_counts"] = {  # type: ignore[index]
        "T1_SELLABLE_QUANTITY_CLIPPED": 2,
        "BUY_LOT_ROUNDED": 1,
        "EXCHANGE_REVALIDATION_FAILED": 1,
    }

    (root / "a26.json").write_text(json.dumps(a26), encoding="utf-8")
    (root / "a4.json").write_text(json.dumps(a4), encoding="utf-8")
    with (root / "a4_ledger.jsonl").open("w", encoding="utf-8") as handle:
        for row in ledger_rows:
            handle.write(_canonical_json(row) + "\n")
    return a26, a4, ledger_rows


def test_v2_projects_gates_portfolio_execution_governance_and_export(tmp_path: Path) -> None:
    _fixture(tmp_path)
    db = tmp_path / "derived" / "evidence_catalog.sqlite"
    before = {path.name: path.stat().st_mtime_ns for path in tmp_path.glob("*.json*")}
    app = create_workspace_app(
        report_paths=(tmp_path,),
        frontend_dir=None,
        catalog_db_path=db,
        git_sha="test-git-sha",
    )
    client = TestClient(app)

    health = client.get("/api/v1/health").json()
    assert health["workspace_v2"] is True
    assert health["read_only"] is True

    projects = client.get("/api/v2/projects")
    assert projects.status_code == 200
    project = projects.json()["items"][0]
    assert project["program_id"] == "program-a26"
    assert project["a3_status"] == "BOUND_IN_A4_PROTOCOL"
    assert project["a3_authority"] == "derived"
    assert project["a4_validation_id"] == "a4-validation-v1"
    assert project["reserve"]["status"] == "untouched"
    assert project["a5_status"] == "LOCKED_NOT_CONSUMED"

    cockpit = client.get("/api/v2/programs/program-a26/cockpit")
    assert cockpit.status_code == 200
    gate = cockpit.json()["gate_matrix"]["items"][0]
    assert gate["passed"] is True
    assert gate["checks"][0]["threshold"] == 0.75
    assert gate["checks"][0]["authority"] == "derived"
    statistical = cockpit.json()["statistics"]["items"][0]
    assert statistical["bootstrap_ci_lower"] == 0.001
    assert cockpit.json()["fold_evidence"]["items"][0]["train_direction"] == 1

    portfolio = client.get("/api/v2/a4/a4-validation-v1/cockpit")
    assert portfolio.status_code == 200
    assert portfolio.json()["metrics"]["net_sharpe"] == 0.5
    assert portfolio.json()["derived_rolling"]["authority"] == "derived"
    assert portfolio.json()["economic_evidence"]["hac_pvalue"] == 0.04

    execution = client.get("/api/v2/a4/a4-validation-v1/execution")
    assert execution.status_code == 200
    payload = execution.json()
    assert payload["ledger"]["row_count"] == 1
    assert payload["funnel"] == {
        "desired": 10,
        "compiled_adjusted": 8,
        "executable": 8,
        "filled": 7,
        "authority": "authoritative",
        "note": "counts use canonical A3 compilation and execution records",
    }
    assert payload["reason_categories"]["T+1"] == 2
    assert payload["costs"]["components"]["broker_commission"] == 35.0
    assert any(item["asset"] == "CASH" for item in payload["target_vs_realized"]["items"])

    governance = client.get("/api/v2/governance/a4-validation-v1")
    assert governance.status_code == 200
    gov = governance.json()
    node_ids = {node["evidence_id"] for node in gov["lineage"]["nodes"]}
    assert "robust-selection-v1" in node_ids
    assert "a4-validation-v1" in node_ids
    assert all(not node_id.startswith("a3-protocol-binding") for node_id in node_ids)
    assert gov["a3_protocol_binding"]["authority"] == "derived"

    diff = client.get(
        "/api/v2/protocol-diff",
        params={"left": "ashare-robust-program-result-test", "right": "a4-validation-v1"},
    )
    assert diff.status_code == 200
    assert diff.json()["authority"] == "derived"
    assert all("research_outcome" not in item["field"] for item in diff.json()["changes"])

    raw = client.get("/api/v2/evidence/a4-validation-v1/raw")
    assert raw.status_code == 200
    assert raw.json()["read_only"] is True
    assert raw.json()["payload"]["reserve"]["status"] == "untouched"

    bundle = client.get("/api/v2/a4/a4-validation-v1/review-bundle")
    assert bundle.status_code == 200
    assert bundle.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        names = set(archive.namelist())
        assert {
            "manifest.json",
            "lineage.json",
            "protocol_diff.json",
            "factor_summary.csv",
            "fold_summary.csv",
            "portfolio_summary.csv",
            "execution_summary.csv",
            "report_a26.json",
            "report_a4.json",
            "execution_ledger.jsonl",
            "figures/README.txt",
        } <= names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["reserve_status"] == "untouched"
        assert manifest["signed"] is False

    assert db.is_file()
    with sqlite3.connect(db) as connection:
        count = connection.execute("SELECT COUNT(*) FROM evidence_catalog").fetchone()[0]
        assert count >= 7
        schema = connection.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()[0]
        assert schema == "finagent.workspace.evidence-catalog.v2"

    after = {path.name: path.stat().st_mtime_ns for path in tmp_path.glob("*.json*")}
    assert after == before
    for path in (
        "/api/v2/projects",
        "/api/v2/programs/program-a26/cockpit",
        "/api/v2/a4/a4-validation-v1/execution",
    ):
        assert client.post(path).status_code == 405


def test_v2_catalog_rebuild_is_deterministic(tmp_path: Path) -> None:
    _fixture(tmp_path)
    db = tmp_path / "catalog.sqlite"
    app1 = create_workspace_app(report_paths=(tmp_path,), frontend_dir=None, catalog_db_path=db)
    first = TestClient(app1).get("/api/v2/catalog").json()["items"]
    first_bytes = db.read_bytes()
    app2 = create_workspace_app(report_paths=(tmp_path,), frontend_dir=None, catalog_db_path=db)
    second = TestClient(app2).get("/api/v2/catalog").json()["items"]
    assert first == second
    # SQLite file bytes are not required to be bitwise identical, but logical rows are.
    assert db.read_bytes()
    assert first_bytes

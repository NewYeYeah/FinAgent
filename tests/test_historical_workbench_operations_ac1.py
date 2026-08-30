from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from finagent.application import HistoricalWorkflowResult
from finagent.visualization.historical_command_catalog import (
    default_historical_command_catalog,
)
from finagent.visualization.historical_workbench_control_api import (
    create_historical_control_app,
)
from finagent.visualization.workbench_control_catalog import ConfigRegistry


_FORBIDDEN_AUTHORITY = {
    "production_reserve",
    "strategy_promotion",
    "paper_mutation",
    "broker_order",
    "live_capital",
    "arbitrary_shell",
    "arbitrary_python",
}
_HISTORICAL_L1 = {
    "research.run_development",
    "research.run_a2p6",
    "portfolio.run_a4",
}


def _await_terminal(client: TestClient, run_id: str) -> dict[str, object]:
    for _ in range(200):
        response = client.get(f"/api/v3/control/runs/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["run"]["state"] in {"succeeded", "failed", "rejected"}:
            return payload
        time.sleep(0.01)
    raise AssertionError("A-C1 CommandRun did not reach a terminal state")


def _write_config(root: Path) -> Path:
    config = root / "configs" / "historical.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        """
[local_ashare_factor_research]
root = "C:/Data/A-Share"
report_path = "reports/development.json"
mode = "deterministic"

[local_ashare_robust_research]
root = "C:/Data/A-Share"
report_path = "reports/a2p6.json"
mode = "deterministic"

[ashare_portfolio_validation]
root = "C:/Data/A-Share"
a2p6_report = "reports/a2p6.json"
report_path = "reports/a4.json"
ledger_path = "reports/a4-ledger.jsonl"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return config


def _fake_result(tmp_path: Path, name: str) -> HistoricalWorkflowResult:
    report = tmp_path / "reports" / f"{name}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("{}\n", encoding="utf-8")
    return HistoricalWorkflowResult(
        payload={"name": name},
        report_path=report,
        artifact_paths=(report,),
        evidence_ids=(f"{name}-evidence",),
    )


def test_ac1_historical_catalog_activates_only_reviewed_l1_services() -> None:
    catalog = default_historical_command_catalog()
    by_id = {item.command_id: item for item in catalog.specs}
    assert set(by_id) >= _HISTORICAL_L1
    for command_id in _HISTORICAL_L1:
        spec = by_id[command_id]
        assert spec.level == "L1"
        assert spec.binding_kind == "application_service"
        assert spec.gateway_readiness == "application_service_ready"
        assert spec.requires_confirmation is True
    assert set(catalog.to_dict()["forbidden_authority"]) == _FORBIDDEN_AUTHORITY
    assert not any(
        token in command_id
        for command_id in by_id
        for token in ("reserve.execute", "promote", "paper", "broker", "live")
    )


def test_ac1_control_executes_three_historical_l1_commands_with_durable_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _write_config(tmp_path)
    registry = ConfigRegistry((config,))
    snapshots = {
        descriptor: registry.snapshots(descriptor)[0].snapshot_id
        for descriptor in (
            "local_ashare_factor_research",
            "local_ashare_robust_research",
            "ashare_portfolio_validation",
        )
    }

    import finagent.application.control_services as services

    monkeypatch.setattr(
        services,
        "run_development_factor_research",
        lambda values: _fake_result(tmp_path, "development"),
    )
    monkeypatch.setattr(
        services,
        "run_robust_research",
        lambda values: _fake_result(tmp_path, "a2p6"),
    )
    monkeypatch.setattr(
        services,
        "run_portfolio_validation",
        lambda values: _fake_result(tmp_path, "a4"),
    )

    app = create_historical_control_app(
        config_paths=(config,),
        report_paths=(tmp_path / "reports",),
        store_path=tmp_path / "commands.sqlite",
        export_dir=tmp_path / "exports",
        requested_by="ac1-pytest",
        max_workers=1,
    )
    with TestClient(app) as client:
        status = client.get("/api/v3/control/status")
        assert status.status_code == 200
        status_payload = status.json()
        assert status_payload["historical_operations"] is True
        assert status_payload["local_only"] is True
        assert status_payload["remote_binding_supported"] is False
        assert set(status_payload["application_service_ready"]) == {
            "config.validate",
            "data.certify_local_ashare",
            "research.run_development",
            "research.run_a2p6",
            "portfolio.run_a4",
            "review.export_bundle",
        }
        assert set(status_payload["forbidden_authority"]) == _FORBIDDEN_AUTHORITY

        catalog = client.get("/api/v3/control/commands").json()
        by_id = {item["command_id"]: item for item in catalog["items"]}
        for command_id in _HISTORICAL_L1:
            assert by_id[command_id]["control_execution_enabled"] is True
            assert by_id[command_id]["gateway_readiness"] == "application_service_ready"

        cases = (
            (
                "research.run_development",
                snapshots["local_ashare_factor_research"],
                "development-evidence",
            ),
            (
                "research.run_a2p6",
                snapshots["local_ashare_robust_research"],
                "a2p6-evidence",
            ),
            (
                "portfolio.run_a4",
                snapshots["ashare_portfolio_validation"],
                "a4-evidence",
            ),
        )
        for index, (command_id, snapshot_id, evidence_id) in enumerate(cases):
            missing_confirmation = client.post(
                "/api/v3/control/runs",
                json={
                    "request_id": f"ac1-confirm-{index:02d}",
                    "command_id": command_id,
                    "config_snapshot_id": snapshot_id,
                    "context": {"environment": "historical"},
                },
            )
            assert missing_confirmation.status_code == 422
            assert "explicit confirmation" in missing_confirmation.json()["result"]["message"]

            submitted = client.post(
                "/api/v3/control/runs",
                json={
                    "request_id": f"ac1-run-{index:02d}",
                    "command_id": command_id,
                    "config_snapshot_id": snapshot_id,
                    "context": {"environment": "historical"},
                    "confirmed": True,
                },
            )
            assert submitted.status_code in {200, 202}
            run_id = submitted.json()["run"]["command_run_id"]
            terminal = _await_terminal(client, run_id)
            assert terminal["run"]["state"] == "succeeded"
            assert terminal["result"]["evidence_ids"] == [evidence_id]
            assert terminal["outputs"]["reserve_access"] == "forbidden"
            assert terminal["parameters"] == {}


def test_ac1_powershell_launcher_is_shell_independent() -> None:
    source = Path("scripts/run_workbench_control.ps1").read_text(encoding="utf-8")
    assert "$PSScriptRoot" in source
    assert "FINAGENT_PYTHON" in source
    assert "-3.11" in source
    assert "bash" not in source.lower()
    assert "finagent.sh" not in source.lower()

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from finagent.visualization.workbench_control_api import create_control_app


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _await_terminal(client: TestClient, run_id: str) -> dict[str, object]:
    for _ in range(100):
        response = client.get(f"/api/v3/control/runs/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["run"]["state"] in {"succeeded", "failed", "rejected"}:
            return payload
        time.sleep(0.01)
    raise AssertionError("command run did not reach a terminal state")


def test_control_plane_executes_only_application_service_ready_commands(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "configs" / "local.toml",
        """
[local_ashare]
root = "D:/Data/A-Share"
basic_filename = "stock_basic_data.parquet"
daily_filename = "stock_daily.parquet"
sample_frequency = "1min"
report_path = "reports/local_ashare_certification.json"
""".strip(),
    )
    app = create_control_app(
        config_paths=(tmp_path / "configs",),
        report_paths=(tmp_path / "reports",),
        store_path=tmp_path / "commands.sqlite",
        export_dir=tmp_path / "exports",
        requested_by="pytest-user",
        max_workers=1,
    )
    with TestClient(app) as client:
        status = client.get("/api/v3/control/status")
        assert status.status_code == 200
        assert status.json()["control_plane_enabled"] is True
        assert status.json()["local_only"] is True
        assert status.json()["remote_binding_supported"] is False
        assert status.json()["application_service_ready"] == [
            "config.validate",
            "data.certify_local_ashare",
            "review.export_bundle",
        ]

        commands = client.get("/api/v3/control/commands").json()["items"]
        by_id = {item["command_id"]: item for item in commands}
        assert by_id["config.validate"]["control_execution_enabled"] is True
        assert by_id["research.run_a2p6"]["control_execution_enabled"] is False
        assert by_id["portfolio.run_a4"]["control_execution_enabled"] is False

        registry_response = client.post(
            "/api/v3/control/runs",
            json={
                "request_id": "request-config-validate-001",
                "command_id": "config.validate",
                "config_snapshot_id": "missing-snapshot",
                "context": {},
            },
        )
        assert registry_response.status_code == 422
        assert registry_response.json()["run"]["state"] == "rejected"
        assert registry_response.json()["intent"]["requested_by"] == "pytest-user"

        rejected = client.post(
            "/api/v3/control/runs",
            json={
                "request_id": "request-a2p6-001",
                "command_id": "research.run_a2p6",
                "context": {"project_id": "project-1"},
                "confirmed": True,
            },
        )
        assert rejected.status_code == 422
        rejected_payload = rejected.json()
        assert rejected_payload["run"]["state"] == "rejected"
        assert "application-service binding" in rejected_payload["result"]["message"]

        unknown = client.post(
            "/api/v3/control/runs",
            json={
                "request_id": "request-unknown-001",
                "command_id": "python.exec",
                "context": {},
            },
        )
        assert unknown.status_code == 422
        assert unknown.json()["run"]["state"] == "rejected"
        assert "allowlisted catalog" in unknown.json()["result"]["message"]


def test_control_plane_runs_config_validation_and_is_idempotent(tmp_path: Path) -> None:
    config = _write(
        tmp_path / "configs" / "local.toml",
        """
[local_ashare]
root = "D:/Data/A-Share"
basic_filename = "stock_basic_data.parquet"
daily_filename = "stock_daily.parquet"
sample_frequency = "1min"
sample_symbol = "000001.SZ"
sample_date = 2009-01-05
report_path = "reports/local_ashare_certification.json"
""".strip(),
    )
    assert config.is_file()
    app = create_control_app(
        config_paths=(tmp_path / "configs",),
        report_paths=(tmp_path / "reports",),
        store_path=tmp_path / "commands.sqlite",
        export_dir=tmp_path / "exports",
        requested_by="pytest-user",
        max_workers=1,
    )
    with TestClient(app) as client:
        # Control Plane deliberately does not mutate/project config. Resolve the
        # deterministic snapshot from its own registry through the application state.
        registry = app.state.command_store
        assert registry is not None
        from finagent.visualization.workbench_control_catalog import ConfigRegistry

        snapshot = ConfigRegistry((tmp_path / "configs",)).snapshots("local_ashare")[0]
        payload = {
            "request_id": "request-config-valid-001",
            "command_id": "config.validate",
            "config_snapshot_id": snapshot.snapshot_id,
            "context": {"project_id": "project-1"},
        }
        response = client.post("/api/v3/control/runs", json=payload)
        assert response.status_code in {200, 202}
        run_id = response.json()["run"]["command_run_id"]
        terminal = _await_terminal(client, run_id)
        assert terminal["run"]["state"] == "succeeded"
        assert terminal["outputs"]["valid"] is True
        assert [item["event_type"] for item in terminal["events"]] == [
            "RUN_PLANNED",
            "RUN_STARTED",
            "RUN_SUCCEEDED",
        ]

        replay = client.post("/api/v3/control/runs", json=payload)
        assert replay.status_code == 200
        assert replay.json()["run"]["command_run_id"] == run_id
        assert replay.json()["run"]["state"] == "succeeded"

        conflict = client.post(
            "/api/v3/control/runs",
            json={**payload, "command_id": "review.export_bundle"},
        )
        assert conflict.status_code == 409


def test_control_plane_rejects_unknown_context_and_extra_payload(tmp_path: Path) -> None:
    app = create_control_app(
        config_paths=(tmp_path,),
        report_paths=(tmp_path,),
        store_path=tmp_path / "commands.sqlite",
        export_dir=tmp_path / "exports",
        requested_by="pytest-user",
        max_workers=1,
    )
    with TestClient(app) as client:
        unknown_context = client.post(
            "/api/v3/control/runs",
            json={
                "request_id": "request-context-001",
                "command_id": "review.export_bundle",
                "context": {"shell": "rm -rf /"},
            },
        )
        assert unknown_context.status_code == 422
        assert unknown_context.json()["run"]["state"] == "rejected"

        extra = client.post(
            "/api/v3/control/runs",
            json={
                "request_id": "request-extra-001",
                "command_id": "config.validate",
                "context": {},
                "shell": "echo unsafe",
            },
        )
        assert extra.status_code == 422
        assert "extra_forbidden" in str(extra.json())

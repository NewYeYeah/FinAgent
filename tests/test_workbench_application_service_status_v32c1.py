from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from finagent.visualization.workbench_api import create_workspace_app


def test_evidence_plane_reports_service_readiness_without_execution(tmp_path: Path) -> None:
    config = tmp_path / "local.toml"
    config.write_text(
        """
[local_ashare]
root = "D:/Data/A-Share"
basic_filename = "stock_basic_data.parquet"
daily_filename = "stock_daily.parquet"
sample_frequency = "1min"
report_path = "reports/local_ashare_certification.json"
""".strip(),
        encoding="utf-8",
    )
    client = TestClient(
        create_workspace_app(
            report_paths=(),
            config_paths=(config,),
            frontend_dir=None,
        )
    )

    status = client.get("/api/v3/workbench/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["control_plane_enabled"] is False
    assert payload["command_execution_enabled"] is False
    assert payload["application_service_ready_command_count"] == 3
    assert payload["application_service_ready_commands"] == [
        "config.validate",
        "data.certify_local_ashare",
        "review.export_bundle",
    ]

    assert client.post(
        "/api/v3/commands",
        json={"command_id": "data.certify_local_ashare"},
    ).status_code == 405
    assert client.post(
        "/api/v3/commands",
        json={"command_id": "review.export_bundle"},
    ).status_code == 405

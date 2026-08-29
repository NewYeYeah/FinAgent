from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from finagent.agents.audit import SQLiteAgentAuditStore
from finagent.application.command_store import SQLiteCommandStore
from finagent.application.control_services import ApplicationCommandExecution
from finagent.visualization.workbench_api import create_workspace_app
from finagent.visualization.workbench_control_catalog import ConfigRegistry

from tests.test_agent_index_v3 import _run_with_artifacts
from tests.test_workspace_api_v2 import _fixture


def _public_config(root: Path) -> tuple[Path, str]:
    config = root / "configs"
    config.mkdir()
    path = config / "local.toml"
    path.write_text(
        """
[local_ashare]
root = "D:/Data/A-Share"
basic_filename = "stock_basic_data.parquet"
daily_filename = "stock_daily.parquet"
sample_frequency = "1min"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    registry = ConfigRegistry((config,))
    snapshot = next(
        value
        for value in registry.projection.snapshots
        if value.descriptor_id == "local_ashare"
    )
    return config, snapshot.snapshot_id


def _command_store(path: Path, *, snapshot_id: str, evidence_id: str) -> str:
    store = SQLiteCommandStore(path)
    record, created = store.create(
        request_key="v33-command-request",
        command_id="config.validate",
        config_snapshot_id=snapshot_id,
        context={
            "program_id": "program-a26",
            "portfolio_validation_id": "a4-validation-v1",
        },
        parameters={},
        requested_by="v33-test",
        accepted=True,
    )
    assert created is True
    run_id = record.run.command_run_id
    store.mark_running(run_id)
    store.mark_succeeded(
        run_id,
        ApplicationCommandExecution(
            command_id="config.validate",
            status="succeeded",
            evidence_ids=(evidence_id,),
            message="synthetic deep-link result",
        ),
    )
    return run_id


def test_v33_resolves_agent_factor_program_a4_config_and_command_links(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    a26, a4, _ = _fixture(reports)
    report_id = str(a26["program_result_id"])
    feature_digest = "a" * 64

    audit = tmp_path / "agent.sqlite"
    agent_store = SQLiteAgentAuditStore(audit)
    _run_with_artifacts(
        agent_store,
        now=datetime(2026, 8, 29, 14, 0, tzinfo=UTC),
        report_id=report_id,
        feature_digest=feature_digest,
    )

    configs, snapshot_id = _public_config(tmp_path)
    command_db = tmp_path / "commands.sqlite"
    command_run_id = _command_store(
        command_db,
        snapshot_id=snapshot_id,
        evidence_id=str(a4["portfolio_validation_id"]),
    )

    before_command = command_db.stat().st_mtime_ns
    before_agent = audit.stat().st_mtime_ns
    client = TestClient(
        create_workspace_app(
            report_paths=(reports,),
            config_paths=(configs,),
            agent_audit_path=audit,
            command_store_path=command_db,
            frontend_dir=None,
        )
    )

    status = client.get("/api/v3/deep-links/status")
    assert status.status_code == 200
    assert status.json()["read_only"] is True
    assert status.json()["command_store_available"] is True
    assert status.json()["phoenix_role"] == "diagnostic_only_not_product_identity"

    run = client.get("/api/v3/refs/agent_run/run-artifacts")
    assert run.status_code == 200
    assert run.json()["metadata"]["hidden_reasoning"] == "not_persisted_not_projected"
    run_related = {(item["kind"], item["identity"]) for item in run.json()["related"]}
    assert ("evidence", report_id) in run_related
    assert ("factor", feature_digest) in run_related

    root = client.get(f"/api/v3/refs/evidence/{report_id}")
    assert root.status_code == 200
    assert root.json()["metadata"]["is_root"] is True
    assert root.json()["metadata"]["canonical_root_evidence_id"] == report_id

    child = client.get("/api/v3/refs/evidence/robust-selection-v1")
    assert child.status_code == 200
    assert child.json()["metadata"]["is_root"] is False
    assert child.json()["metadata"]["canonical_root_evidence_id"] == report_id
    assert child.json()["target_url"].endswith(report_id)

    program = client.get("/api/v3/refs/research_program/program-a26")
    assert program.status_code == 200
    related = {(item["kind"], item["identity"]) for item in program.json()["related"]}
    assert ("factor", feature_digest) in related
    assert ("portfolio_validation", "a4-validation-v1") in related

    factor = client.get(f"/api/v3/refs/factor/{feature_digest}")
    assert factor.status_code == 200
    assert factor.json()["context"]["factor_id"] == feature_digest
    assert factor.json()["context"]["program_id"] == "program-a26"

    generated = client.get(f"/api/v3/artifacts/{feature_digest}")
    assert generated.status_code == 200
    assert generated.json()["artifact_type"] == "generated_feature"
    assert generated.json()["source"]["host_path_accepted_from_browser"] is False
    assert generated.json()["preview"]["kind"] == "metadata"

    source_artifact = next(
        item["identity"] for item in root.json()["related"] if item["kind"] == "artifact"
    )
    source = client.get(f"/api/v3/artifacts/{source_artifact}")
    assert source.status_code == 200
    assert source.json()["artifact_type"] == "source_report"
    assert source.json()["preview"]["kind"] == "text"
    assert "program_result_id" in source.json()["preview"]["content"]

    snapshot = client.get(f"/api/v3/refs/config_snapshot/{snapshot_id}")
    assert snapshot.status_code == 200
    snapshot_related = {(item["kind"], item["identity"]) for item in snapshot.json()["related"]}
    assert ("command_run", command_run_id) in snapshot_related

    command = client.get(f"/api/v3/refs/command_run/{command_run_id}")
    assert command.status_code == 200
    command_related = {(item["kind"], item["identity"]) for item in command.json()["related"]}
    assert ("config_snapshot", snapshot_id) in command_related
    assert ("evidence", "a4-validation-v1") in command_related
    assert command.json()["metadata"]["result"]["message"] == "synthetic deep-link result"

    command_projection = client.get(f"/api/v3/command-runs/{command_run_id}")
    assert command_projection.status_code == 200
    assert command_projection.json()["result"]["evidence_ids"] == ["a4-validation-v1"]

    assert command_db.stat().st_mtime_ns == before_command
    assert audit.stat().st_mtime_ns == before_agent


def test_v33_fails_closed_and_never_accepts_browser_host_paths(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    _fixture(reports)
    configs, _ = _public_config(tmp_path)
    client = TestClient(
        create_workspace_app(
            report_paths=(reports,),
            config_paths=(configs,),
            frontend_dir=None,
        )
    )

    assert client.get("/api/v3/refs/not-a-kind/value").status_code == 422
    assert client.get("/api/v3/refs/evidence/missing").status_code == 404
    assert client.get("/api/v3/artifacts/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert client.get("/api/v3/command-runs").json()["configured"] is False
    assert client.get("/api/v3/command-runs/missing").status_code == 404

    for path in (
        "/api/v3/deep-links/status",
        "/api/v3/refs/evidence/a4-validation-v1",
        "/api/v3/artifacts/missing",
        "/api/v3/command-runs",
    ):
        assert client.post(path).status_code == 405


def test_v33_source_artifact_preview_is_bounded_to_configured_report_roots(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    a26, _, _ = _fixture(reports)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"secret": "must-not-be-addressable"}), encoding="utf-8")
    client = TestClient(create_workspace_app(report_paths=(reports,), frontend_dir=None))

    root = client.get(f"/api/v3/refs/evidence/{a26['program_result_id']}").json()
    artifact_id = next(
        item["identity"] for item in root["related"] if item["kind"] == "artifact"
    )
    inspection = client.get(f"/api/v3/artifacts/{artifact_id}").json()
    assert inspection["source"]["display_uri"].endswith("a26.json")
    assert str(outside) not in json.dumps(inspection)

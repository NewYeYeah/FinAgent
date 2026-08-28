from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from finagent.agents.audit import SQLiteAgentAuditStore
from finagent.agents.domain import (
    AgentDecision,
    AgentDecisionStatus,
    AgentRunContext,
    AgentTask,
)
from finagent.visualization.workspace_api import create_workspace_app

from tests.test_visualization_semantic_contract_v2 import _a2p6_report, _a4_report


def _write_reports(root: Path) -> None:
    import json

    (root / "a26.json").write_text(
        json.dumps(_a2p6_report(), ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "a4.json").write_text(
        json.dumps(_a4_report(), ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "unsupported.json").write_text(
        '{"schema_version":"other.v1"}',
        encoding="utf-8",
    )


def _agent_database(path: Path) -> None:
    now = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)
    store = SQLiteAgentAuditStore(path, event_id_factory=iter(("event-1", "event-2")).__next__)
    task = AgentTask(
        task_id="task-1",
        objective="Inspect robust factor evidence",
        created_at=now,
    )
    context = AgentRunContext(
        run_id="run-1",
        task_id="task-1",
        actor="research-agent",
        started_at=now,
        metadata={
            "project_id": "program-a26",
            "thread_id": "thread-1",
            "trigger_type": "research_program",
        },
    )
    store.start_run(task, context)
    store.finish_run(
        AgentDecision(
            run_id="run-1",
            status=AgentDecisionStatus.COMPLETED,
            summary="Evidence inspected",
            finished_at=now + timedelta(seconds=3),
        )
    )


def test_workspace_catalog_evidence_factor_lineage_and_widgets(tmp_path: Path) -> None:
    _write_reports(tmp_path)
    app = create_workspace_app(report_paths=(tmp_path,), frontend_dir=None)
    client = TestClient(app)

    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["read_only"] is True
    assert health.json()["evidence_count"] == 2

    catalog = client.get("/api/v1/catalog").json()
    assert catalog["read_only"] is True
    assert len(catalog["items"]) == 2
    assert any("unsupported evidence schema" in value for value in catalog["warnings"])

    program_id = _a2p6_report()["program_result_id"]
    program = client.get(f"/api/v1/evidence/{program_id}")
    assert program.status_code == 200
    assert program.json()["reserve_status"] == "untouched"
    assert program.json()["promotion_eligible"] is False

    program_by_domain_id = client.get("/api/v1/programs/program-a26")
    assert program_by_domain_id.status_code == 200
    assert program_by_domain_id.json()["root"]["program_id"] == "program-a26"

    factor_digest = "a" * 64
    factor = client.get(f"/api/v1/factors/{factor_digest}")
    assert factor.status_code == 200
    assert factor.json()["occurrences"][0]["factor"]["selected"] is True

    lineage = client.get(f"/api/v1/lineage/{program_id}")
    assert lineage.status_code == 200
    assert len(lineage.json()["nodes"]) == 5

    widgets = client.get("/api/v1/widgets").json()["items"]
    assert any(value["widget_id"] == "a4.portfolio.gross_net_nav" for value in widgets)
    assert any(value["widget_id"] == "agent.run.activity" for value in widgets)

    a4_id = _a4_report()["portfolio_validation_id"]
    a4 = client.get(f"/api/v1/portfolio-validations/{a4_id}")
    assert a4.status_code == 200
    assert a4.json()["portfolio"]["points"][0]["net_nav"] > 0
    assert a4.json()["execution"]["rejected_order_count"] == 2

    for path in (
        "/api/v1/catalog",
        f"/api/v1/evidence/{program_id}",
        "/api/v1/agent/runs",
    ):
        assert client.post(path).status_code == 405


def test_workspace_agent_projection_is_read_only(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    _write_reports(reports)
    audit = tmp_path / "agent.sqlite"
    _agent_database(audit)
    before = audit.stat().st_mtime_ns
    app = create_workspace_app(
        report_paths=(reports,),
        agent_audit_path=audit,
        frontend_dir=None,
    )
    client = TestClient(app)

    runs = client.get("/api/v1/agent/runs")
    assert runs.status_code == 200
    assert runs.json()["configured"] is True
    assert runs.json()["items"][0]["run_id"] == "run-1"

    run = client.get("/api/v1/agent/runs/run-1")
    assert run.status_code == 200
    assert run.json()["status"] == "completed"
    assert run.json()["hidden_reasoning"] == "not_persisted_not_projected"
    assert audit.stat().st_mtime_ns == before


def test_workspace_serves_built_spa_without_exposing_report_files(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    _write_reports(reports)
    frontend = tmp_path / "dist"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html>workspace-v1</html>", encoding="utf-8")
    (frontend / "asset.txt").write_text("asset", encoding="utf-8")
    app = create_workspace_app(report_paths=(reports,), frontend_dir=frontend)
    client = TestClient(app)

    assert "workspace-v1" in client.get("/").text
    assert "workspace-v1" in client.get("/evidence/anything").text
    assert client.get("/asset.txt").text == "asset"
    assert client.get("/api/v1/not-present").status_code == 404
    assert client.get("/reports/a26.json").text != (reports / "a26.json").read_text(
        encoding="utf-8"
    )

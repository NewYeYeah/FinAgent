from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finagent.agents.audit import SQLiteAgentAuditStore
from finagent.agents.domain import (
    AgentDecision,
    AgentDecisionStatus,
    AgentRunContext,
    AgentTask,
    PolicyDecision,
    PolicyOutcome,
    ToolCallRequest,
    ToolCallResult,
    ToolCallStatus,
)
from finagent.visualization.agent_index import (
    build_agent_artifact_catalog,
    load_agent_index,
)
from finagent.visualization.semantic import EvidenceContractError, parse_evidence_report
from finagent.visualization.workspace_api import create_workspace_app

from tests.test_visualization_semantic_contract_v2 import _a2p6_report


def _finish_run(
    store: SQLiteAgentAuditStore,
    *,
    run_id: str,
    task_id: str,
    started_at: datetime,
    objective: str,
    metadata: dict[str, str] | None = None,
    actor: str = "research-agent",
    duration_seconds: int = 5,
) -> None:
    task = AgentTask(
        task_id=task_id,
        objective=objective,
        created_at=started_at,
    )
    context = AgentRunContext(
        run_id=run_id,
        task_id=task_id,
        actor=actor,
        started_at=started_at,
        metadata=metadata or {},
    )
    store.start_run(task, context)
    store.finish_run(
        AgentDecision(
            run_id=run_id,
            status=AgentDecisionStatus.COMPLETED,
            summary=f"{objective} completed",
            finished_at=started_at + timedelta(seconds=duration_seconds),
        )
    )


def _run_with_artifacts(
    store: SQLiteAgentAuditStore,
    *,
    now: datetime,
    report_id: str,
    feature_digest: str,
) -> None:
    task = AgentTask(
        task_id="task-artifacts",
        objective="Inspect factor artifacts",
        created_at=now,
    )
    context = AgentRunContext(
        run_id="run-artifacts",
        task_id=task.task_id,
        actor="research-agent",
        started_at=now,
        metadata={
            "project_id": "program-a26",
            "thread_id": "thread-artifacts",
            "trigger_type": "research_program",
        },
    )
    store.start_run(task, context)
    request = ToolCallRequest(
        call_id="call-artifacts",
        tool_name="inspect_factor",
        arguments={"feature_digest": feature_digest},
        requested_at=now + timedelta(seconds=1),
    )
    store.record_tool_request(context.run_id, request)
    decision = PolicyDecision(
        decision_id="policy-artifacts",
        run_id=context.run_id,
        call_id=request.call_id,
        tool_name=request.tool_name,
        outcome=PolicyOutcome.ALLOW,
        reason="read-only evidence inspection",
        decided_at=now + timedelta(seconds=2),
        policy_name="research-readonly",
        policy_version="v1",
    )
    store.record_policy_decision(decision)
    store.record_tool_result(
        ToolCallResult(
            call_id=request.call_id,
            run_id=context.run_id,
            tool_name=request.tool_name,
            status=ToolCallStatus.SUCCEEDED,
            finished_at=now + timedelta(seconds=3),
            policy_decision_id=decision.decision_id,
            output={
                "report_id": report_id,
                "feature_digest": feature_digest,
                "artifact_id": "unknown-artifact-id",
            },
        )
    )
    store.finish_run(
        AgentDecision(
            run_id=context.run_id,
            status=AgentDecisionStatus.COMPLETED,
            summary="Artifacts inspected",
            finished_at=now + timedelta(seconds=4),
            tool_call_ids=(request.call_id,),
        )
    )


def test_agent_index_groups_projects_threads_runs_and_sorts_deterministically(
    tmp_path: Path,
) -> None:
    database = tmp_path / "agent.sqlite"
    store = SQLiteAgentAuditStore(database)
    now = datetime(2026, 8, 29, 8, 0, tzinfo=UTC)
    _finish_run(
        store,
        run_id="run-old",
        task_id="task-a",
        started_at=now,
        objective="Older research run",
        metadata={"project_id": "project-a", "thread_id": "thread-a"},
    )
    _finish_run(
        store,
        run_id="run-new",
        task_id="task-b",
        started_at=now + timedelta(minutes=3),
        objective="Newest research run",
        metadata={"project_id": "project-a", "thread_id": "thread-b"},
    )
    _finish_run(
        store,
        run_id="run-other",
        task_id="task-c",
        started_at=now + timedelta(minutes=1),
        objective="Other project",
        metadata={"project_id": "project-b", "thread_id": "thread-c"},
    )

    before = database.stat().st_mtime_ns
    first = load_agent_index(database)
    second = load_agent_index(database)
    assert database.stat().st_mtime_ns == before

    assert [value.project_id for value in first.projects] == ["project-a", "project-b"]
    project = first.project("project-a")
    assert [value.thread_id for value in project.threads] == ["thread-b", "thread-a"]
    assert project.run_count == 2
    assert first.thread("thread-b").runs[0].run_id == "run-new"
    assert first.projects_response() == second.projects_response()


def test_agent_index_uses_deterministic_fallback_identity_without_mutating_audit(
    tmp_path: Path,
) -> None:
    database = tmp_path / "agent.sqlite"
    store = SQLiteAgentAuditStore(database)
    now = datetime(2026, 8, 29, 9, 0, tzinfo=UTC)
    _finish_run(
        store,
        run_id="run-1",
        task_id="task-fallback",
        started_at=now,
        objective="Fallback one",
        metadata={},
    )
    _finish_run(
        store,
        run_id="run-2",
        task_id="task-fallback",
        started_at=now + timedelta(minutes=1),
        objective="Fallback two",
        metadata={"trigger_type": "system"},
    )

    before = database.read_bytes()
    index = load_agent_index(database)
    after = database.read_bytes()
    assert before == after

    summaries = [index.run_summaries["run-1"], index.run_summaries["run-2"]]
    assert summaries[0].project_id == summaries[1].project_id
    assert summaries[0].thread_id == summaries[1].thread_id
    assert summaries[0].project_id.startswith("finagent-derived-project-task-")
    assert summaries[0].thread_id.startswith("finagent-derived-thread-task-")
    assert summaries[0].project_identity_source == "task_fallback"
    assert summaries[0].thread_identity_source == "task_fallback"
    assert summaries[1].trigger_type == "system"


def test_agent_index_infers_missing_project_from_explicit_thread_binding(tmp_path: Path) -> None:
    database = tmp_path / "agent.sqlite"
    store = SQLiteAgentAuditStore(database)
    now = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)
    _finish_run(
        store,
        run_id="run-bound",
        task_id="task-a",
        started_at=now,
        objective="Bound",
        metadata={"project_id": "project-a", "thread_id": "thread-shared"},
    )
    _finish_run(
        store,
        run_id="run-inferred",
        task_id="task-b",
        started_at=now + timedelta(minutes=1),
        objective="Inferred",
        metadata={"thread_id": "thread-shared"},
    )

    index = load_agent_index(database)
    inferred = index.run_summaries["run-inferred"]
    assert inferred.project_id == "project-a"
    assert inferred.project_identity_source == "thread_inferred"
    assert inferred.thread_identity_source == "explicit"
    assert index.thread("thread-shared").project_id == "project-a"


def test_agent_index_rejects_conflicting_thread_project_identity(tmp_path: Path) -> None:
    database = tmp_path / "agent.sqlite"
    store = SQLiteAgentAuditStore(database)
    now = datetime(2026, 8, 29, 11, 0, tzinfo=UTC)
    _finish_run(
        store,
        run_id="run-a",
        task_id="task-a",
        started_at=now,
        objective="A",
        metadata={"project_id": "project-a", "thread_id": "thread-conflict"},
    )
    _finish_run(
        store,
        run_id="run-b",
        task_id="task-b",
        started_at=now + timedelta(minutes=1),
        objective="B",
        metadata={"project_id": "project-b", "thread_id": "thread-conflict"},
    )

    with pytest.raises(EvidenceContractError, match="conflicting projects"):
        load_agent_index(database)


def test_agent_index_rejects_corrupted_canonical_audit_payload(tmp_path: Path) -> None:
    database = tmp_path / "agent.sqlite"
    store = SQLiteAgentAuditStore(database)
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    _finish_run(
        store,
        run_id="run-corrupt",
        task_id="task-corrupt",
        started_at=now,
        objective="Corrupt me",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE agent_runs SET payload_json=? WHERE run_id=?",
            ("{not-json", "run-corrupt"),
        )

    with pytest.raises(EvidenceContractError, match="invalid JSON"):
        load_agent_index(database)


def test_agent_artifact_refs_only_include_verified_workspace_identities(tmp_path: Path) -> None:
    database = tmp_path / "agent.sqlite"
    store = SQLiteAgentAuditStore(database)
    now = datetime(2026, 8, 29, 13, 0, tzinfo=UTC)
    report = _a2p6_report()
    report_id = str(report["program_result_id"])
    feature_digest = "a" * 64
    _run_with_artifacts(
        store,
        now=now,
        report_id=report_id,
        feature_digest=feature_digest,
    )
    bundle = parse_evidence_report(report, source_uri="reports/a26.json")
    catalog = build_agent_artifact_catalog((bundle,))

    index = load_agent_index(database, artifact_catalog=catalog)
    summary = index.run_summaries["run-artifacts"]
    artifacts = {value.artifact_id: value for value in summary.artifact_refs}
    assert report_id in artifacts
    assert feature_digest in artifacts
    assert "unknown-artifact-id" not in artifacts
    assert summary.unresolved_artifact_count == 1
    assert artifacts[report_id].verification == "workspace_catalog"
    assert artifacts[feature_digest].artifact_type == "factor"


def test_workspace_v3_agent_index_api_is_get_only_and_fail_closed(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    report = _a2p6_report()
    import json

    (reports / "a26.json").write_text(json.dumps(report), encoding="utf-8")
    database = tmp_path / "agent.sqlite"
    store = SQLiteAgentAuditStore(database)
    now = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
    _finish_run(
        store,
        run_id="run-api",
        task_id="task-api",
        started_at=now,
        objective="Index API",
        metadata={"project_id": "project-api", "thread_id": "thread-api"},
    )
    before = database.stat().st_mtime_ns
    client = TestClient(
        create_workspace_app(
            report_paths=(reports,),
            agent_audit_path=database,
            frontend_dir=None,
        )
    )

    projects = client.get("/api/v3/agent/projects")
    assert projects.status_code == 200
    assert projects.json()["configured"] is True
    assert projects.json()["items"][0]["project_id"] == "project-api"

    project = client.get("/api/v3/agent/projects/project-api")
    assert project.status_code == 200
    assert project.json()["threads"][0]["thread_id"] == "thread-api"

    thread = client.get("/api/v3/agent/threads/thread-api")
    assert thread.status_code == 200
    assert thread.json()["runs"][0]["run_id"] == "run-api"

    run = client.get("/api/v3/agent/runs/run-api")
    assert run.status_code == 200
    assert run.json()["run"]["hidden_reasoning"] == "not_persisted_not_projected"
    assert run.json()["summary"]["project_id"] == "project-api"
    assert database.stat().st_mtime_ns == before

    assert client.get("/api/v3/agent/projects/missing").status_code == 404
    assert client.post("/api/v3/agent/projects").status_code == 405
    assert client.post("/api/v3/agent/runs/run-api").status_code == 405


def test_workspace_v3_agent_index_reports_not_configured_without_audit(tmp_path: Path) -> None:
    client = TestClient(create_workspace_app(report_paths=(tmp_path,), frontend_dir=None))
    response = client.get("/api/v3/agent/projects")
    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert response.json()["items"] == []
    assert client.get("/api/v3/agent/projects/anything").status_code == 404


def test_workspace_v3_agent_index_conflict_returns_409(tmp_path: Path) -> None:
    database = tmp_path / "agent.sqlite"
    store = SQLiteAgentAuditStore(database)
    now = datetime(2026, 8, 29, 15, 0, tzinfo=UTC)
    _finish_run(
        store,
        run_id="run-conflict-a",
        task_id="task-conflict-a",
        started_at=now,
        objective="Conflict A",
        metadata={"project_id": "project-a", "thread_id": "thread-conflict"},
    )
    _finish_run(
        store,
        run_id="run-conflict-b",
        task_id="task-conflict-b",
        started_at=now + timedelta(minutes=1),
        objective="Conflict B",
        metadata={"project_id": "project-b", "thread_id": "thread-conflict"},
    )
    client = TestClient(
        create_workspace_app(
            report_paths=(tmp_path,),
            agent_audit_path=database,
            frontend_dir=None,
        )
    )
    response = client.get("/api/v3/agent/projects")
    assert response.status_code == 409
    assert "conflicting projects" in response.json()["detail"]


def test_agent_index_bulk_projection_opens_one_read_only_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from finagent.visualization import agent_projection

    database = tmp_path / "agent.sqlite"
    store = SQLiteAgentAuditStore(database)
    now = datetime(2026, 8, 29, 16, 0, tzinfo=UTC)
    for index in range(3):
        _finish_run(
            store,
            run_id=f"run-bulk-{index}",
            task_id=f"task-bulk-{index}",
            started_at=now + timedelta(minutes=index),
            objective=f"Bulk {index}",
        )

    calls = 0
    original = agent_projection._connect_read_only

    def counted(path: Path):
        nonlocal calls
        calls += 1
        return original(path)

    monkeypatch.setattr(agent_projection, "_connect_read_only", counted)
    projection = load_agent_index(database)
    assert len(projection.run_summaries) == 3
    assert calls == 1

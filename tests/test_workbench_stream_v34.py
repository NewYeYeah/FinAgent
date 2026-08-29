from __future__ import annotations

import json
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
from finagent.application.command_store import SQLiteCommandStore
from finagent.application.control_services import ApplicationCommandExecution
from finagent.visualization.workbench_api import create_workspace_app
from finagent.visualization.workbench_streams import WorkbenchStreamProjection


def _started_agent(path: Path) -> tuple[SQLiteAgentAuditStore, datetime]:
    store = SQLiteAgentAuditStore(path)
    now = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)
    task = AgentTask(
        task_id="task-stream",
        objective="Review stable product evidence",
        created_at=now,
    )
    context = AgentRunContext(
        run_id="run-stream",
        task_id=task.task_id,
        actor="research-agent",
        started_at=now,
        metadata={
            "project_id": "project-stream",
            "thread_id": "thread-stream",
            "trigger_type": "research_program",
        },
    )
    store.start_run(task, context)
    return store, now


def _command(path: Path) -> tuple[SQLiteCommandStore, str]:
    store = SQLiteCommandStore(path)
    record, created = store.create(
        request_key="stream-command-request",
        command_id="review.export_bundle",
        config_snapshot_id=None,
        context={"portfolio_validation_id": "a4-validation-v1"},
        parameters={"validation_id": "a4-validation-v1"},
        requested_by="stream-test",
        accepted=True,
    )
    assert created is True
    return store, record.run.command_run_id


def _sse_payload(text: str) -> dict[str, object]:
    line = next(value for value in text.splitlines() if value.startswith("data: "))
    payload = json.loads(line.removeprefix("data: "))
    assert isinstance(payload, dict)
    return payload


def test_v34_agent_projection_is_stable_sanitized_and_changes_with_audit_state(
    tmp_path: Path,
) -> None:
    audit = tmp_path / "agent.sqlite"
    store, now = _started_agent(audit)
    streams = WorkbenchStreamProjection(
        bundles=(),
        agent_audit_path=audit,
    )

    first = streams.agent_snapshot("run-stream")
    first_event = streams.event_for_agent(first)
    repeated_event = streams.event_for_agent(streams.agent_snapshot("run-stream"))
    assert first_event.event_id == repeated_event.event_id
    assert first.terminal is False
    assert first.latest_activity is not None
    assert first.latest_activity.title == "Run started"

    serialized = json.dumps(first_event.to_dict(), sort_keys=True).lower()
    for forbidden in (
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "tool_allowlist",
        "governance",
        "provider_callback",
        "artifact_paths",
        "phoenix_span",
        "otlp_span",
    ):
        assert forbidden not in serialized
    assert first.hidden_reasoning == "not_persisted_not_projected"

    store.finish_run(
        AgentDecision(
            run_id="run-stream",
            status=AgentDecisionStatus.COMPLETED,
            summary="completed without exposing hidden reasoning",
            finished_at=now + timedelta(seconds=5),
        )
    )
    finished = streams.agent_snapshot("run-stream")
    finished_event = streams.event_for_agent(finished)
    assert finished.terminal is True
    assert finished.latest_activity is not None
    assert finished.latest_activity.title == "Run finished"
    assert finished_event.event_id != first_event.event_id


def test_v34_command_projection_streams_state_without_outputs_paths_or_messages(
    tmp_path: Path,
) -> None:
    command_db = tmp_path / "commands.sqlite"
    store, run_id = _command(command_db)
    streams = WorkbenchStreamProjection(
        bundles=(),
        command_store_path=command_db,
    )

    planned = streams.command_snapshot(run_id)
    planned_event = streams.event_for_command(planned)
    assert planned.state == "planned"
    assert planned.terminal is False
    assert planned.latest_event is not None
    assert planned.latest_event["event_type"] == "RUN_PLANNED"
    assert "message" not in planned.latest_event

    store.mark_running(run_id)
    running = streams.command_snapshot(run_id)
    running_event = streams.event_for_command(running)
    assert running.state == "running"
    assert running_event.event_id != planned_event.event_id

    store.mark_succeeded(
        run_id,
        ApplicationCommandExecution(
            command_id="review.export_bundle",
            status="succeeded",
            outputs={"host_detail": "D:/private/should-not-stream"},
            artifact_paths=("D:/private/review.zip",),
            evidence_ids=("a4-validation-v1",),
            message="D:/private/free-form-message-must-not-stream",
        ),
    )
    succeeded = streams.command_snapshot(run_id)
    succeeded_event = streams.event_for_command(succeeded)
    assert succeeded.state == "succeeded"
    assert succeeded.terminal is True
    assert succeeded.result_status == "succeeded"
    assert succeeded.evidence_ids == ("a4-validation-v1",)
    assert succeeded_event.event_id != running_event.event_id

    serialized = json.dumps(succeeded_event.to_dict(), sort_keys=True).lower()
    for forbidden in (
        "parameters",
        "outputs",
        "artifact_paths",
        "host_detail",
        "review.zip",
        "free-form-message",
        "d:/private",
    ):
        assert forbidden not in serialized


def test_v34_once_sse_api_is_get_only_and_read_only(tmp_path: Path) -> None:
    audit = tmp_path / "agent.sqlite"
    _started_agent(audit)
    command_db = tmp_path / "commands.sqlite"
    _, run_id = _command(command_db)
    before_agent = audit.read_bytes()
    before_command = command_db.read_bytes()

    client = TestClient(
        create_workspace_app(
            report_paths=(tmp_path,),
            agent_audit_path=audit,
            command_store_path=command_db,
            frontend_dir=None,
        )
    )

    status = client.get("/api/v3/streams/status")
    assert status.status_code == 200
    assert status.json()["transport"] == "sse"
    assert status.json()["hidden_reasoning"] == "not_persisted_not_projected"
    assert status.json()["raw_provider_callbacks"] is False
    assert status.json()["raw_otlp_phoenix"] is False
    assert status.json()["arbitrary_command_outputs"] is False
    assert status.json()["free_form_command_messages"] is False
    assert status.json()["host_artifact_paths"] is False

    agent = client.get("/api/v3/streams/agent/runs/run-stream?once=true")
    assert agent.status_code == 200
    assert agent.headers["content-type"].startswith("text/event-stream")
    assert "event: agent_run_snapshot" in agent.text
    assert agent.headers["cache-control"] == "no-cache, no-transform"
    agent_payload = _sse_payload(agent.text)
    assert agent_payload["identity"] == "run-stream"
    assert agent_payload["projection"]["hidden_reasoning"] == "not_persisted_not_projected"  # type: ignore[index]

    command = client.get(f"/api/v3/streams/command-runs/{run_id}?once=true")
    assert command.status_code == 200
    assert "event: command_run_snapshot" in command.text
    command_payload = _sse_payload(command.text)
    assert command_payload["identity"] == run_id
    projection = command_payload["projection"]
    assert isinstance(projection, dict)
    assert "parameters" not in projection
    assert "outputs" not in projection
    assert "artifact_paths" not in projection

    assert client.get("/api/v3/streams/agent/runs/missing?once=true").status_code == 404
    assert client.get("/api/v3/streams/command-runs/missing?once=true").status_code == 404
    assert client.post("/api/v3/streams/agent/runs/run-stream").status_code == 405
    assert client.post(f"/api/v3/streams/command-runs/{run_id}").status_code == 405

    assert audit.read_bytes() == before_agent
    assert command_db.read_bytes() == before_command


def test_v34_command_stream_path_can_be_configured_before_store_exists(tmp_path: Path) -> None:
    future_store = tmp_path / "later" / "commands.sqlite"
    client = TestClient(
        create_workspace_app(
            report_paths=(tmp_path,),
            command_store_path=future_store,
            frontend_dir=None,
        )
    )
    status = client.get("/api/v3/streams/status").json()
    assert status["command_store_configured"] is True
    assert status["command_store_available"] is False
    assert client.get("/api/v3/streams/command-runs/anything?once=true").status_code == 503

    store, run_id = _command(future_store)
    assert store.get(run_id).run.state == "planned"
    event = client.get(f"/api/v3/streams/command-runs/{run_id}?once=true")
    assert event.status_code == 200
    assert "event: command_run_snapshot" in event.text

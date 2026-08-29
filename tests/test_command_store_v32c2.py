from __future__ import annotations

from pathlib import Path

import pytest

from finagent.application import ApplicationCommandExecution, SQLiteCommandStore


def test_command_store_persists_idempotent_lifecycle(tmp_path: Path) -> None:
    store = SQLiteCommandStore(tmp_path / "commands.sqlite")
    record, created = store.create(
        request_key="request-001",
        command_id="config.validate",
        config_snapshot_id="config-snapshot-abc",
        context={"project_id": "project-1"},
        parameters={},
        requested_by="tester",
        accepted=True,
    )
    assert created is True
    assert record.intent.state == "validated"
    assert record.run.state == "planned"
    assert [item.event_type for item in record.events] == ["RUN_PLANNED"]

    duplicate, duplicate_created = store.create(
        request_key="request-001",
        command_id="config.validate",
        config_snapshot_id="config-snapshot-abc",
        context={"project_id": "project-1"},
        parameters={},
        requested_by="tester",
        accepted=True,
    )
    assert duplicate_created is False
    assert duplicate.run.command_run_id == record.run.command_run_id

    running = store.mark_running(record.run.command_run_id)
    assert running.run.state == "running"
    finished = store.mark_succeeded(
        record.run.command_run_id,
        ApplicationCommandExecution(
            command_id="config.validate",
            status="succeeded",
            outputs={"valid": True},
            evidence_ids=("evidence-1",),
            artifact_paths=("artifact.json",),
            message="ok",
        ),
    )
    assert finished.run.state == "succeeded"
    assert finished.result is not None
    assert finished.result.status == "succeeded"
    assert finished.result.evidence_ids == ("evidence-1",)
    assert finished.artifact_paths == ("artifact.json",)
    assert finished.outputs == {"valid": True}
    assert [item.event_type for item in finished.events] == [
        "RUN_PLANNED",
        "RUN_STARTED",
        "RUN_SUCCEEDED",
    ]

    reopened = SQLiteCommandStore(tmp_path / "commands.sqlite")
    persisted = reopened.get(record.run.command_run_id)
    assert persisted.to_dict() == finished.to_dict()


def test_command_store_rejects_conflicting_idempotency_key(tmp_path: Path) -> None:
    store = SQLiteCommandStore(tmp_path / "commands.sqlite")
    store.create(
        request_key="same-request",
        command_id="config.validate",
        config_snapshot_id="config-snapshot-1",
        context={},
        parameters={},
        requested_by="tester",
        accepted=True,
    )
    with pytest.raises(ValueError, match="conflicting immutable command request"):
        store.create(
            request_key="same-request",
            command_id="review.export_bundle",
            config_snapshot_id=None,
            context={"portfolio_validation_id": "a4-1"},
            parameters={"validation_id": "a4-1"},
            requested_by="tester",
            accepted=True,
        )


def test_command_store_persists_rejection_without_running(tmp_path: Path) -> None:
    store = SQLiteCommandStore(tmp_path / "commands.sqlite")
    record, _ = store.create(
        request_key="rejected-request",
        command_id="research.run_a2p6",
        config_snapshot_id=None,
        context={},
        parameters={},
        requested_by="tester",
        accepted=False,
        rejection_message="adapter required",
    )
    assert record.intent.state == "rejected"
    assert record.run.state == "rejected"
    assert record.run.started_at is None
    assert record.run.finished_at is not None
    assert record.result is not None
    assert record.result.status == "rejected"
    assert record.result.message == "adapter required"
    with pytest.raises(ValueError, match="illegal command run transition"):
        store.mark_running(record.run.command_run_id)


def test_command_store_recovery_never_retries_incomplete_work(tmp_path: Path) -> None:
    store = SQLiteCommandStore(tmp_path / "commands.sqlite")
    planned, _ = store.create(
        request_key="planned-request",
        command_id="config.validate",
        config_snapshot_id="config-snapshot-a",
        context={},
        parameters={},
        requested_by="tester",
        accepted=True,
    )
    running, _ = store.create(
        request_key="running-request",
        command_id="config.validate",
        config_snapshot_id="config-snapshot-b",
        context={},
        parameters={},
        requested_by="tester",
        accepted=True,
    )
    store.mark_running(running.run.command_run_id)

    reopened = SQLiteCommandStore(tmp_path / "commands.sqlite")
    recovered = set(reopened.recover_incomplete())
    assert recovered == {planned.run.command_run_id, running.run.command_run_id}
    for run_id in recovered:
        record = reopened.get(run_id)
        assert record.run.state == "failed"
        assert record.result is not None
        assert "automatic retry is forbidden" in record.result.message

    assert reopened.recover_incomplete() == ()

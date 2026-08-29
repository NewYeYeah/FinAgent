from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator, cast

from .command_contracts import (
    CommandEvent,
    CommandIntent,
    CommandIntentState,
    CommandRecord,
    CommandResult,
    CommandResultStatus,
    CommandRun,
    CommandRunState,
)
from .control_services import ApplicationCommandExecution

COMMAND_STORE_SCHEMA = "finagent.workbench.command-store.v1"
_TERMINAL_STATES: frozenset[CommandRunState] = frozenset(
    {"succeeded", "failed", "rejected"}
)
_INTENT_STATES = frozenset({"draft", "validated", "rejected"})
_RUN_STATES = frozenset({"planned", "running", "succeeded", "failed", "rejected"})
_RESULT_STATES = frozenset({"succeeded", "failed", "rejected"})


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _digest(prefix: str, value: object, length: int = 32) -> str:
    digest = hashlib.sha256(_json(value).encode("utf-8")).hexdigest()[:length]
    return f"{prefix}-{digest}"


def _object(raw: str) -> dict[str, object]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("stored JSON value must be an object")
    return {str(key): item for key, item in value.items()}


def _strings(raw: str) -> tuple[str, ...]:
    value = json.loads(raw)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("stored JSON value must be a string array")
    return tuple(value)


def _intent_state(value: object) -> CommandIntentState:
    text = str(value)
    if text not in _INTENT_STATES:
        raise ValueError(f"invalid stored CommandIntent state: {text}")
    return cast(CommandIntentState, text)


def _run_state(value: object) -> CommandRunState:
    text = str(value)
    if text not in _RUN_STATES:
        raise ValueError(f"invalid stored CommandRun state: {text}")
    return cast(CommandRunState, text)


def _result_state(value: object) -> CommandResultStatus:
    text = str(value)
    if text not in _RESULT_STATES:
        raise ValueError(f"invalid stored CommandResult status: {text}")
    return cast(CommandResultStatus, text)


class SQLiteCommandStore:
    """Crash-visible, append-audited command lifecycle persistence.

    The store persists typed command data only. It has no shell command, Python
    source, subprocess argument or executable-text field. Each operation owns its
    SQLite connection so background command workers never share connection objects.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._read_connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS command_intents (
                    intent_id TEXT PRIMARY KEY,
                    request_key TEXT NOT NULL UNIQUE,
                    command_id TEXT NOT NULL,
                    config_snapshot_id TEXT,
                    context_json TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN ('draft', 'validated', 'rejected')
                    ),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS command_runs (
                    command_run_id TEXT PRIMARY KEY,
                    intent_id TEXT NOT NULL UNIQUE
                        REFERENCES command_intents(intent_id),
                    command_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN (
                            'planned', 'running', 'succeeded', 'failed', 'rejected'
                        )
                    ),
                    started_at TEXT,
                    finished_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS command_results (
                    command_run_id TEXT PRIMARY KEY
                        REFERENCES command_runs(command_run_id),
                    status TEXT NOT NULL CHECK (
                        status IN ('succeeded', 'failed', 'rejected')
                    ),
                    evidence_ids_json TEXT NOT NULL,
                    artifact_paths_json TEXT NOT NULL,
                    outputs_json TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS command_events (
                    event_id TEXT PRIMARY KEY,
                    command_run_id TEXT NOT NULL
                        REFERENCES command_runs(command_run_id),
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN (
                            'planned', 'running', 'succeeded', 'failed', 'rejected'
                        )
                    ),
                    occurred_at TEXT NOT NULL,
                    message TEXT NOT NULL,
                    UNIQUE(command_run_id, sequence)
                );

                CREATE INDEX IF NOT EXISTS idx_command_runs_updated
                    ON command_runs(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_command_events_run
                    ON command_events(command_run_id, sequence);
                """
            )
            connection.commit()

    def create(
        self,
        *,
        request_key: str,
        command_id: str,
        config_snapshot_id: str | None,
        context: Mapping[str, str],
        parameters: Mapping[str, object],
        requested_by: str,
        accepted: bool,
        rejection_message: str = "",
    ) -> tuple[CommandRecord, bool]:
        """Create one idempotent intent/run pair.

        Reusing ``request_key`` returns the exact prior record if the immutable
        request is identical; conflicting key reuse fails closed.
        """

        normalized_request_key = request_key.strip()
        normalized_command_id = command_id.strip()
        normalized_actor = requested_by.strip()
        if not normalized_request_key:
            raise ValueError("request_key is required")
        if not normalized_command_id:
            raise ValueError("command_id is required")
        if not normalized_actor:
            raise ValueError("requested_by is required")

        context_payload = {
            str(key): str(value) for key, value in sorted(context.items())
        }
        parameters_payload = {
            str(key): value for key, value in sorted(parameters.items())
        }
        intent_id = _digest(
            "command-intent",
            {
                "request_key": normalized_request_key,
                "requested_by": normalized_actor,
            },
        )
        run_id = _digest("command-run", {"intent_id": intent_id})
        intent_state: CommandIntentState = "validated" if accepted else "rejected"
        run_state: CommandRunState = "planned" if accepted else "rejected"
        created_at = _now()

        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT intent_id FROM command_intents WHERE request_key = ?",
                (normalized_request_key,),
            ).fetchone()
            if existing is not None:
                existing_record = self._load_record(
                    connection,
                    str(existing["intent_id"]),
                )
                self._assert_same_request(
                    existing_record,
                    command_id=normalized_command_id,
                    config_snapshot_id=config_snapshot_id,
                    context=context_payload,
                    parameters=parameters_payload,
                    requested_by=normalized_actor,
                )
                return existing_record, False

            connection.execute(
                """
                INSERT INTO command_intents (
                    intent_id, request_key, command_id, config_snapshot_id,
                    context_json, parameters_json, requested_by, state, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent_id,
                    normalized_request_key,
                    normalized_command_id,
                    config_snapshot_id,
                    _json(context_payload),
                    _json(parameters_payload),
                    normalized_actor,
                    intent_state,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO command_runs (
                    command_run_id, intent_id, command_id, state,
                    started_at, finished_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    run_id,
                    intent_id,
                    normalized_command_id,
                    run_state,
                    created_at if not accepted else None,
                    created_at,
                    created_at,
                ),
            )
            self._append_event(
                connection,
                run_id=run_id,
                event_type="RUN_PLANNED" if accepted else "RUN_REJECTED",
                state=run_state,
                message=(
                    "command accepted for execution"
                    if accepted
                    else rejection_message or "command rejected"
                ),
                occurred_at=created_at,
            )
            if not accepted:
                self._insert_result(
                    connection,
                    run_id=run_id,
                    status="rejected",
                    evidence_ids=(),
                    artifact_paths=(),
                    outputs={},
                    message=rejection_message or "command rejected",
                    created_at=created_at,
                )
            return self._load_record(connection, intent_id), True

    def get(self, command_run_id: str) -> CommandRecord:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT intent_id FROM command_runs WHERE command_run_id = ?",
                (command_run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"command run not found: {command_run_id}")
            return self._load_record(connection, str(row["intent_id"]))

    def list(self, *, limit: int = 100) -> tuple[CommandRecord, ...]:
        bounded = max(1, min(int(limit), 500))
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT intent_id FROM command_runs
                ORDER BY updated_at DESC, command_run_id DESC
                LIMIT ?
                """,
                (bounded,),
            ).fetchall()
            return tuple(
                self._load_record(connection, str(row["intent_id"]))
                for row in rows
            )

    def mark_running(self, command_run_id: str) -> CommandRecord:
        return self._transition(
            command_run_id,
            expected=("planned",),
            target="running",
            event_type="RUN_STARTED",
            message="application service execution started",
        )

    def mark_succeeded(
        self,
        command_run_id: str,
        execution: ApplicationCommandExecution,
    ) -> CommandRecord:
        if execution.status != "succeeded":
            raise ValueError(
                "succeeded transition requires succeeded application execution"
            )
        return self._finish(
            command_run_id,
            expected=("running",),
            target="succeeded",
            execution=execution,
            event_type="RUN_SUCCEEDED",
        )

    def mark_rejected(
        self,
        command_run_id: str,
        execution: ApplicationCommandExecution,
    ) -> CommandRecord:
        if execution.status != "rejected":
            raise ValueError(
                "rejected transition requires rejected application execution"
            )
        return self._finish(
            command_run_id,
            expected=("running",),
            target="rejected",
            execution=execution,
            event_type="RUN_REJECTED",
        )

    def mark_failed(self, command_run_id: str, message: str) -> CommandRecord:
        command_id = self.get(command_run_id).run.command_id
        execution = ApplicationCommandExecution(
            command_id=command_id,
            status="rejected",
            message=message,
        )
        return self._finish(
            command_run_id,
            expected=("planned", "running"),
            target="failed",
            execution=execution,
            event_type="RUN_FAILED",
            result_status="failed",
        )

    def recover_incomplete(self) -> tuple[str, ...]:
        """Fail incomplete work after restart; never automatically retry it."""

        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT command_run_id FROM command_runs
                WHERE state IN ('planned', 'running')
                ORDER BY created_at, command_run_id
                """
            ).fetchall()
        recovered: list[str] = []
        for row in rows:
            run_id = str(row["command_run_id"])
            try:
                self.mark_failed(
                    run_id,
                    (
                        "control process restarted before a terminal result; "
                        "automatic retry is forbidden"
                    ),
                )
            except ValueError:
                continue
            recovered.append(run_id)
        return tuple(recovered)

    def status(self) -> dict[str, object]:
        with self._read_connection() as connection:
            counts = {
                str(row["state"]): int(row["count"])
                for row in connection.execute(
                    "SELECT state, COUNT(*) AS count FROM command_runs GROUP BY state"
                ).fetchall()
            }
        return {
            "schema_version": COMMAND_STORE_SCHEMA,
            "run_counts": counts,
            "terminal_states": sorted(_TERMINAL_STATES),
        }

    def _transition(
        self,
        command_run_id: str,
        *,
        expected: Sequence[CommandRunState],
        target: CommandRunState,
        event_type: str,
        message: str,
    ) -> CommandRecord:
        occurred_at = _now()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT intent_id, state FROM command_runs WHERE command_run_id = ?",
                (command_run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"command run not found: {command_run_id}")
            current = _run_state(row["state"])
            if current not in expected:
                raise ValueError(
                    f"illegal command run transition: {current} -> {target}"
                )
            connection.execute(
                """
                UPDATE command_runs
                SET state = ?, started_at = ?, updated_at = ?
                WHERE command_run_id = ?
                """,
                (target, occurred_at, occurred_at, command_run_id),
            )
            self._append_event(
                connection,
                run_id=command_run_id,
                event_type=event_type,
                state=target,
                message=message,
                occurred_at=occurred_at,
            )
            return self._load_record(connection, str(row["intent_id"]))

    def _finish(
        self,
        command_run_id: str,
        *,
        expected: Sequence[CommandRunState],
        target: CommandRunState,
        execution: ApplicationCommandExecution,
        event_type: str,
        result_status: CommandResultStatus | None = None,
    ) -> CommandRecord:
        occurred_at = _now()
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT intent_id, command_id, state, started_at
                FROM command_runs
                WHERE command_run_id = ?
                """,
                (command_run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"command run not found: {command_run_id}")
            current = _run_state(row["state"])
            if current not in expected:
                raise ValueError(
                    f"illegal command run transition: {current} -> {target}"
                )
            if str(row["command_id"]) != execution.command_id:
                raise ValueError(
                    "application execution command_id differs from persisted run"
                )
            # A planned run failed during restart recovery before service execution;
            # preserve started_at=NULL rather than fabricating an execution start.
            started_at = row["started_at"]
            if current == "running" and started_at is None:
                started_at = occurred_at
            connection.execute(
                """
                UPDATE command_runs
                SET state = ?, started_at = ?, finished_at = ?, updated_at = ?
                WHERE command_run_id = ?
                """,
                (
                    target,
                    started_at,
                    occurred_at,
                    occurred_at,
                    command_run_id,
                ),
            )
            status: CommandResultStatus = result_status or cast(
                CommandResultStatus,
                target,
            )
            if status not in _RESULT_STATES:
                raise ValueError(f"invalid terminal result status: {status}")
            self._insert_result(
                connection,
                run_id=command_run_id,
                status=status,
                evidence_ids=execution.evidence_ids,
                artifact_paths=execution.artifact_paths,
                outputs=execution.outputs,
                message=execution.message,
                created_at=occurred_at,
            )
            self._append_event(
                connection,
                run_id=command_run_id,
                event_type=event_type,
                state=target,
                message=execution.message,
                occurred_at=occurred_at,
            )
            return self._load_record(connection, str(row["intent_id"]))

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        event_type: str,
        state: CommandRunState,
        message: str,
        occurred_at: str,
    ) -> None:
        row = connection.execute(
            """
            SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence
            FROM command_events
            WHERE command_run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("command event sequence query returned no row")
        sequence = int(row["sequence"])
        event_id = _digest(
            "command-event",
            {
                "run_id": run_id,
                "sequence": sequence,
                "event_type": event_type,
            },
        )
        connection.execute(
            """
            INSERT INTO command_events (
                event_id, command_run_id, sequence, event_type,
                state, occurred_at, message
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                run_id,
                sequence,
                event_type,
                state,
                occurred_at,
                message,
            ),
        )

    def _insert_result(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        status: CommandResultStatus,
        evidence_ids: Sequence[str],
        artifact_paths: Sequence[str],
        outputs: Mapping[str, object],
        message: str,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO command_results (
                command_run_id, status, evidence_ids_json, artifact_paths_json,
                outputs_json, message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                status,
                _json(list(evidence_ids)),
                _json(list(artifact_paths)),
                _json(dict(outputs)),
                message,
                created_at,
            ),
        )

    def _load_record(
        self,
        connection: sqlite3.Connection,
        intent_id: str,
    ) -> CommandRecord:
        row = connection.execute(
            """
            SELECT
                i.intent_id,
                i.command_id AS intent_command_id,
                i.config_snapshot_id,
                i.context_json,
                i.parameters_json,
                i.requested_by,
                i.state AS intent_state,
                r.command_run_id,
                r.command_id AS run_command_id,
                r.state AS run_state,
                r.started_at,
                r.finished_at,
                r.created_at AS run_created_at,
                r.updated_at
            FROM command_intents i
            JOIN command_runs r ON r.intent_id = i.intent_id
            WHERE i.intent_id = ?
            """,
            (intent_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"command intent not found: {intent_id}")

        context_raw = _object(str(row["context_json"]))
        context = {key: str(value) for key, value in context_raw.items()}
        parameters = _object(str(row["parameters_json"]))
        intent = CommandIntent(
            intent_id=str(row["intent_id"]),
            command_id=str(row["intent_command_id"]),
            config_snapshot_id=(
                str(row["config_snapshot_id"])
                if row["config_snapshot_id"] is not None
                else None
            ),
            context=context,
            requested_by=str(row["requested_by"]),
            state=_intent_state(row["intent_state"]),
        )
        run = CommandRun(
            command_run_id=str(row["command_run_id"]),
            intent_id=intent.intent_id,
            command_id=str(row["run_command_id"]),
            state=_run_state(row["run_state"]),
            started_at=(
                str(row["started_at"]) if row["started_at"] is not None else None
            ),
            finished_at=(
                str(row["finished_at"])
                if row["finished_at"] is not None
                else None
            ),
        )

        result_row = connection.execute(
            "SELECT * FROM command_results WHERE command_run_id = ?",
            (run.command_run_id,),
        ).fetchone()
        result: CommandResult | None = None
        artifacts: tuple[str, ...] = ()
        outputs: Mapping[str, object] = {}
        if result_row is not None:
            result = CommandResult(
                command_run_id=run.command_run_id,
                status=_result_state(result_row["status"]),
                evidence_ids=_strings(str(result_row["evidence_ids_json"])),
                message=str(result_row["message"]),
            )
            artifacts = _strings(str(result_row["artifact_paths_json"]))
            outputs = _object(str(result_row["outputs_json"]))

        events = tuple(
            CommandEvent(
                event_id=str(event["event_id"]),
                command_run_id=run.command_run_id,
                sequence=int(event["sequence"]),
                event_type=str(event["event_type"]),
                state=_run_state(event["state"]),
                occurred_at=str(event["occurred_at"]),
                message=str(event["message"]),
            )
            for event in connection.execute(
                """
                SELECT * FROM command_events
                WHERE command_run_id = ?
                ORDER BY sequence
                """,
                (run.command_run_id,),
            ).fetchall()
        )
        return CommandRecord(
            intent=intent,
            run=run,
            parameters=parameters,
            created_at=str(row["run_created_at"]),
            updated_at=str(row["updated_at"]),
            result=result,
            artifact_paths=artifacts,
            outputs=outputs,
            events=events,
        )

    @staticmethod
    def _assert_same_request(
        record: CommandRecord,
        *,
        command_id: str,
        config_snapshot_id: str | None,
        context: Mapping[str, str],
        parameters: Mapping[str, object],
        requested_by: str,
    ) -> None:
        expected = {
            "command_id": command_id,
            "config_snapshot_id": config_snapshot_id,
            "context": dict(context),
            "parameters": dict(parameters),
            "requested_by": requested_by,
        }
        actual = {
            "command_id": record.intent.command_id,
            "config_snapshot_id": record.intent.config_snapshot_id,
            "context": dict(record.intent.context),
            "parameters": dict(record.parameters),
            "requested_by": record.intent.requested_by,
        }
        if _json(actual) != _json(expected):
            raise ValueError(
                "request_key was reused with a conflicting immutable command request"
            )

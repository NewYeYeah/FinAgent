from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Mapping, Protocol

from .domain import (
    AgentAuditEvent,
    AgentAuditEventType,
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


def _jsonable(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"value is not JSON-auditable: {type(value).__name__}")


def _dump(payload: Mapping[str, object]) -> str:
    return json.dumps(_jsonable(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class AgentAuditStore(Protocol):
    def start_run(self, task: AgentTask, context: AgentRunContext) -> None: ...

    def finish_run(self, decision: AgentDecision) -> None: ...

    def has_run(self, run_id: str) -> bool: ...

    def get_run_context(self, run_id: str) -> AgentRunContext: ...

    def record_tool_request(self, run_id: str, request: ToolCallRequest) -> None: ...

    def record_policy_decision(self, decision: PolicyDecision) -> None: ...

    def record_tool_result(self, result: ToolCallResult) -> None: ...

    def tool_call_count(self, run_id: str) -> int: ...


class SQLiteAgentAuditStore:
    """Append-oriented Agent audit store.

    The store may share a SQLite file with `SQLiteResearchRegistry`, but it owns only
    `agent_*` tables.  Numerical experiment state remains canonical in the research
    registry; this store records who requested which governed action and what happened.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        event_id_factory=None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.event_id_factory = event_id_factory or (lambda: f"audit-{uuid.uuid4().hex}")
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    decision_json TEXT
                );
                CREATE TABLE IF NOT EXISTS agent_tool_calls (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    call_id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS agent_policy_decisions (
                    decision_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    call_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE RESTRICT,
                    FOREIGN KEY (call_id) REFERENCES agent_tool_calls(call_id) ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS agent_audit_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL,
                    call_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES agent_runs(run_id) ON DELETE RESTRICT
                );
                """
            )

    def start_run(self, task: AgentTask, context: AgentRunContext) -> None:
        if task.task_id != context.task_id:
            raise ValueError("task.task_id must match context.task_id")
        payload = {
            "task": {
                "task_id": task.task_id,
                "objective": task.objective,
                "created_at": task.created_at,
                "metadata": task.metadata,
            },
            "context": {
                "run_id": context.run_id,
                "task_id": context.task_id,
                "actor": context.actor,
                "started_at": context.started_at,
                "max_tool_calls": context.max_tool_calls,
                "tool_allowlist": context.tool_allowlist,
                "metadata": context.metadata,
            },
        }
        with self._connect() as con:
            try:
                con.execute(
                    "INSERT INTO agent_runs (run_id, task_id, payload_json) VALUES (?, ?, ?)",
                    (context.run_id, context.task_id, _dump(payload)),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"agent run {context.run_id!r} is already registered") from exc
        self._append_event(
            AgentAuditEvent(
                event_id=self.event_id_factory(),
                run_id=context.run_id,
                event_type=AgentAuditEventType.RUN_STARTED,
                occurred_at=context.started_at,
                payload={"task_id": context.task_id, "actor": context.actor},
            )
        )

    def finish_run(self, decision: AgentDecision) -> None:
        with self._connect() as con:
            row = con.execute(
                "SELECT decision_json FROM agent_runs WHERE run_id=?", (decision.run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(decision.run_id)
            if row[0] is not None:
                raise ValueError(f"agent run {decision.run_id!r} is already finished")
            con.execute(
                "UPDATE agent_runs SET decision_json=? WHERE run_id=?",
                (
                    _dump(
                        {
                            "run_id": decision.run_id,
                            "status": decision.status,
                            "summary": decision.summary,
                            "finished_at": decision.finished_at,
                            "tool_call_ids": decision.tool_call_ids,
                            "metadata": decision.metadata,
                        }
                    ),
                    decision.run_id,
                ),
            )
        self._append_event(
            AgentAuditEvent(
                event_id=self.event_id_factory(),
                run_id=decision.run_id,
                event_type=AgentAuditEventType.RUN_FINISHED,
                occurred_at=decision.finished_at,
                payload={"status": decision.status.value, "summary": decision.summary},
            )
        )

    def has_run(self, run_id: str) -> bool:
        with self._connect() as con:
            return (
                con.execute("SELECT 1 FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
                is not None
            )

    def get_run_context(self, run_id: str) -> AgentRunContext:
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM agent_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        context = json.loads(row[0])["context"]
        return AgentRunContext(
            run_id=context["run_id"],
            task_id=context["task_id"],
            actor=context["actor"],
            started_at=datetime.fromisoformat(context["started_at"]),
            max_tool_calls=int(context["max_tool_calls"]),
            tool_allowlist=tuple(context["tool_allowlist"]),
            metadata=context["metadata"],
        )

    def record_tool_request(self, run_id: str, request: ToolCallRequest) -> None:
        if not self.has_run(run_id):
            raise KeyError(f"agent run {run_id!r} is not registered")
        payload = {
            "call_id": request.call_id,
            "tool_name": request.tool_name,
            "arguments": request.arguments,
            "requested_at": request.requested_at,
        }
        with self._connect() as con:
            try:
                con.execute(
                    """INSERT INTO agent_tool_calls
                       (call_id, run_id, request_json) VALUES (?, ?, ?)""",
                    (request.call_id, run_id, _dump(payload)),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"tool call {request.call_id!r} is already registered") from exc
        self._append_event(
            AgentAuditEvent(
                event_id=self.event_id_factory(),
                run_id=run_id,
                event_type=AgentAuditEventType.TOOL_REQUESTED,
                occurred_at=request.requested_at,
                call_id=request.call_id,
                payload={"tool_name": request.tool_name, "arguments": request.arguments},
            )
        )

    def record_policy_decision(self, decision: PolicyDecision) -> None:
        payload = {
            "decision_id": decision.decision_id,
            "run_id": decision.run_id,
            "call_id": decision.call_id,
            "tool_name": decision.tool_name,
            "outcome": decision.outcome,
            "reason": decision.reason,
            "decided_at": decision.decided_at,
            "policy_name": decision.policy_name,
            "policy_version": decision.policy_version,
        }
        with self._connect() as con:
            if con.execute(
                "SELECT 1 FROM agent_tool_calls WHERE call_id=? AND run_id=?",
                (decision.call_id, decision.run_id),
            ).fetchone() is None:
                raise KeyError(decision.call_id)
            con.execute(
                """INSERT INTO agent_policy_decisions
                   (decision_id, run_id, call_id, payload_json) VALUES (?, ?, ?, ?)""",
                (decision.decision_id, decision.run_id, decision.call_id, _dump(payload)),
            )
        self._append_event(
            AgentAuditEvent(
                event_id=self.event_id_factory(),
                run_id=decision.run_id,
                event_type=AgentAuditEventType.POLICY_DECIDED,
                occurred_at=decision.decided_at,
                call_id=decision.call_id,
                payload={
                    "tool_name": decision.tool_name,
                    "outcome": decision.outcome.value,
                    "reason": decision.reason,
                    "policy_name": decision.policy_name,
                    "policy_version": decision.policy_version,
                },
            )
        )

    def record_tool_result(self, result: ToolCallResult) -> None:
        payload = {
            "call_id": result.call_id,
            "run_id": result.run_id,
            "tool_name": result.tool_name,
            "status": result.status,
            "finished_at": result.finished_at,
            "policy_decision_id": result.policy_decision_id,
            "output": result.output,
            "error": result.error,
        }
        with self._connect() as con:
            cursor = con.execute(
                """UPDATE agent_tool_calls SET result_json=?
                   WHERE call_id=? AND run_id=? AND result_json IS NULL""",
                (_dump(payload), result.call_id, result.run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"pending tool call {result.call_id!r} was not found")
        self._append_event(
            AgentAuditEvent(
                event_id=self.event_id_factory(),
                run_id=result.run_id,
                event_type=AgentAuditEventType.TOOL_FINISHED,
                occurred_at=result.finished_at,
                call_id=result.call_id,
                payload={
                    "tool_name": result.tool_name,
                    "status": result.status.value,
                    "policy_decision_id": result.policy_decision_id,
                    "error": result.error,
                },
            )
        )

    def tool_call_count(self, run_id: str) -> int:
        with self._connect() as con:
            row = con.execute(
                "SELECT COUNT(*) FROM agent_tool_calls WHERE run_id=?", (run_id,)
            ).fetchone()
        return int(row[0])

    def replay_requests(self, run_id: str) -> tuple[ToolCallRequest, ...]:
        with self._connect() as con:
            rows = con.execute(
                """SELECT request_json FROM agent_tool_calls
                   WHERE run_id=? ORDER BY sequence""",
                (run_id,),
            ).fetchall()
        requests: list[ToolCallRequest] = []
        for (payload_json,) in rows:
            payload = json.loads(payload_json)
            requests.append(
                ToolCallRequest(
                    call_id=payload["call_id"],
                    tool_name=payload["tool_name"],
                    arguments=payload["arguments"],
                    requested_at=datetime.fromisoformat(payload["requested_at"]),
                )
            )
        return tuple(requests)

    def get_tool_result(self, call_id: str) -> ToolCallResult:
        with self._connect() as con:
            row = con.execute(
                "SELECT result_json FROM agent_tool_calls WHERE call_id=?", (call_id,)
            ).fetchone()
        if row is None or row[0] is None:
            raise KeyError(call_id)
        payload = json.loads(row[0])
        return ToolCallResult(
            call_id=payload["call_id"],
            run_id=payload["run_id"],
            tool_name=payload["tool_name"],
            status=ToolCallStatus(payload["status"]),
            finished_at=datetime.fromisoformat(payload["finished_at"]),
            policy_decision_id=payload["policy_decision_id"],
            output=payload["output"],
            error=payload["error"],
        )

    def get_policy_decision(self, decision_id: str) -> PolicyDecision:
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM agent_policy_decisions WHERE decision_id=?",
                (decision_id,),
            ).fetchone()
        if row is None:
            raise KeyError(decision_id)
        payload = json.loads(row[0])
        return PolicyDecision(
            decision_id=payload["decision_id"],
            run_id=payload["run_id"],
            call_id=payload["call_id"],
            tool_name=payload["tool_name"],
            outcome=PolicyOutcome(payload["outcome"]),
            reason=payload["reason"],
            decided_at=datetime.fromisoformat(payload["decided_at"]),
            policy_name=payload["policy_name"],
            policy_version=payload["policy_version"],
        )

    def list_events(self, run_id: str) -> tuple[AgentAuditEvent, ...]:
        with self._connect() as con:
            rows = con.execute(
                """SELECT event_id, event_type, occurred_at, call_id, payload_json
                   FROM agent_audit_events WHERE run_id=? ORDER BY sequence""",
                (run_id,),
            ).fetchall()
        return tuple(
            AgentAuditEvent(
                event_id=row[0],
                run_id=run_id,
                event_type=AgentAuditEventType(row[1]),
                occurred_at=datetime.fromisoformat(row[2]),
                call_id=row[3],
                payload=json.loads(row[4]),
            )
            for row in rows
        )

    def _append_event(self, event: AgentAuditEvent) -> None:
        with self._connect() as con:
            con.execute(
                """INSERT INTO agent_audit_events
                   (event_id, run_id, call_id, event_type, occurred_at, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    event.event_id,
                    event.run_id,
                    event.call_id,
                    event.event_type.value,
                    event.occurred_at.isoformat(),
                    _dump(event.payload),
                ),
            )

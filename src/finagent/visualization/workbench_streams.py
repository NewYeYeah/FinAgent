from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal, TypeVar

from fastapi import Request
from fastapi.responses import Response, StreamingResponse

from .agent_index import build_agent_artifact_catalog, load_agent_index
from .semantic import EvidenceBundle, EvidenceContractError
from .workbench_links import ReadOnlyCommandRunProjection

AGENT_ACTIVE_RUN_SCHEMA = "finagent.workbench.agent-active-run.v1"
COMMAND_RUN_STREAM_SCHEMA = "finagent.workbench.command-run-stream.v1"
WORKBENCH_SSE_EVENT_SCHEMA = "finagent.workbench.sse-event.v1"

StreamEventType = Literal["agent_run_snapshot", "command_run_snapshot"]
TProjection = TypeVar("TProjection")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )


def _digest(prefix: str, value: object, length: int = 32) -> str:
    raw = hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]
    return f"{prefix}-{raw}"


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): child for key, child in value.items()}


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _read_only_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@dataclass(frozen=True, slots=True)
class StreamActivity:
    item_id: str
    item_type: str
    occurred_at: str
    title: str
    status: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentActiveRunProjection:
    run_id: str
    project_id: str
    thread_id: str
    objective: str
    actor: str
    trigger_type: str
    status: str
    started_at: str
    finished_at: str | None
    updated_at: str
    item_count: int
    artifact_count: int
    unresolved_artifact_count: int
    latest_activity: StreamActivity | None
    terminal: bool
    hidden_reasoning: str = "not_persisted_not_projected"
    read_only: bool = True
    schema_version: str = AGENT_ACTIVE_RUN_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "read_only": self.read_only,
            "run_id": self.run_id,
            "project_id": self.project_id,
            "thread_id": self.thread_id,
            "objective": self.objective,
            "actor": self.actor,
            "trigger_type": self.trigger_type,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "updated_at": self.updated_at,
            "item_count": self.item_count,
            "artifact_count": self.artifact_count,
            "unresolved_artifact_count": self.unresolved_artifact_count,
            "latest_activity": (
                self.latest_activity.to_dict() if self.latest_activity else None
            ),
            "terminal": self.terminal,
            "hidden_reasoning": self.hidden_reasoning,
        }


@dataclass(frozen=True, slots=True)
class CommandRunStreamProjection:
    command_run_id: str
    command_id: str
    state: str
    config_snapshot_id: str | None
    context: Mapping[str, str]
    requested_by: str
    started_at: str | None
    finished_at: str | None
    updated_at: str
    result_status: str | None
    evidence_ids: tuple[str, ...]
    result_message: str
    latest_event: Mapping[str, object] | None
    terminal: bool
    read_only: bool = True
    schema_version: str = COMMAND_RUN_STREAM_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))
        if self.latest_event is not None:
            object.__setattr__(
                self,
                "latest_event",
                MappingProxyType(dict(self.latest_event)),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "read_only": self.read_only,
            "command_run_id": self.command_run_id,
            "command_id": self.command_id,
            "state": self.state,
            "config_snapshot_id": self.config_snapshot_id,
            "context": dict(self.context),
            "requested_by": self.requested_by,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "updated_at": self.updated_at,
            "result_status": self.result_status,
            "evidence_ids": list(self.evidence_ids),
            "result_message": self.result_message,
            "latest_event": dict(self.latest_event) if self.latest_event else None,
            "terminal": self.terminal,
        }


@dataclass(frozen=True, slots=True)
class WorkbenchSseEvent:
    event_id: str
    event_type: StreamEventType
    identity: str
    occurred_at: str
    projection: Mapping[str, object] = field(default_factory=dict)
    schema_version: str = WORKBENCH_SSE_EVENT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "projection",
            MappingProxyType(dict(self.projection)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "identity": self.identity,
            "occurred_at": self.occurred_at,
            "projection": dict(self.projection),
        }

    def to_sse(self) -> str:
        return (
            f"id: {self.event_id}\n"
            f"event: {self.event_type}\n"
            f"data: {_canonical_json(self.to_dict())}\n\n"
        )


class WorkbenchStreamProjection:
    """Stable product projections for V3-4 streaming.

    The stream layer reads canonical Agent audit and durable CommandRun state. It
    deliberately excludes prompts, provider callbacks, token/reasoning payloads,
    arbitrary command outputs, host artifact paths and raw OTLP/Phoenix spans.
    """

    def __init__(
        self,
        *,
        bundles: Sequence[EvidenceBundle],
        agent_audit_path: str | Path | None = None,
        command_store_path: str | Path | None = None,
    ) -> None:
        self.agent_audit_path = (
            Path(agent_audit_path).expanduser() if agent_audit_path else None
        )
        self.command_store_path = (
            Path(command_store_path).expanduser() if command_store_path else None
        )
        self.command_runs = ReadOnlyCommandRunProjection(command_store_path)
        self._agent_artifacts = build_agent_artifact_catalog(tuple(bundles))

    @property
    def agent_configured(self) -> bool:
        return self.agent_audit_path is not None

    @property
    def command_configured(self) -> bool:
        return self.command_store_path is not None

    def agent_snapshot(self, run_id: str) -> AgentActiveRunProjection:
        if self.agent_audit_path is None:
            raise KeyError(run_id)
        index = load_agent_index(
            self.agent_audit_path,
            artifact_catalog=self._agent_artifacts,
        )
        try:
            summary = index.run_summaries[run_id]
            run = index.runs[run_id]
        except KeyError as exc:
            raise KeyError(run_id) from exc
        latest = run.items[-1] if run.items else None
        updated = summary.updated_at
        if latest is not None and latest.occurred_at > updated:
            updated = latest.occurred_at
        activity = (
            StreamActivity(
                item_id=latest.item_id,
                item_type=latest.item_type.value,
                occurred_at=latest.occurred_at.isoformat(),
                title=latest.title,
                status=latest.status,
            )
            if latest is not None
            else None
        )
        return AgentActiveRunProjection(
            run_id=run_id,
            project_id=summary.project_id,
            thread_id=summary.thread_id,
            objective=summary.objective,
            actor=summary.actor,
            trigger_type=summary.trigger_type,
            status=summary.status,
            started_at=summary.started_at.isoformat(),
            finished_at=(
                summary.finished_at.isoformat() if summary.finished_at else None
            ),
            updated_at=updated.isoformat(),
            item_count=summary.item_count,
            artifact_count=len(summary.artifact_refs),
            unresolved_artifact_count=summary.unresolved_artifact_count,
            latest_activity=activity,
            terminal=summary.finished_at is not None,
        )

    def _latest_command_event(
        self,
        command_run_id: str,
    ) -> Mapping[str, object] | None:
        if self.command_store_path is None:
            return None
        with _read_only_connection(self.command_store_path) as connection:
            row = connection.execute(
                """
                SELECT event_id, sequence, event_type, state, occurred_at, message
                FROM command_events
                WHERE command_run_id = ?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (command_run_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "event_id": str(row["event_id"]),
            "sequence": int(row["sequence"]),
            "event_type": str(row["event_type"]),
            "state": str(row["state"]),
            "occurred_at": str(row["occurred_at"]),
            "message": str(row["message"] or ""),
        }

    def command_snapshot(self, command_run_id: str) -> CommandRunStreamProjection:
        payload = self.command_runs.get(command_run_id)
        result = _mapping(payload.get("result"))
        evidence_ids = tuple(
            text
            for value in _sequence(result.get("evidence_ids"))
            if (text := _text(value))
        )
        context = {
            str(key): str(value)
            for key, value in _mapping(payload.get("context")).items()
            if _text(value)
        }
        state = _text(payload.get("state"))
        return CommandRunStreamProjection(
            command_run_id=command_run_id,
            command_id=_text(payload.get("command_id")),
            state=state,
            config_snapshot_id=_text(payload.get("config_snapshot_id")) or None,
            context=context,
            requested_by=_text(payload.get("requested_by")),
            started_at=_text(payload.get("started_at")) or None,
            finished_at=_text(payload.get("finished_at")) or None,
            updated_at=_text(payload.get("updated_at")),
            result_status=_text(result.get("status")) or None,
            evidence_ids=evidence_ids,
            result_message=_text(result.get("message")),
            latest_event=self._latest_command_event(command_run_id),
            terminal=state in {"succeeded", "failed", "rejected"},
        )

    @staticmethod
    def event_for_agent(projection: AgentActiveRunProjection) -> WorkbenchSseEvent:
        payload = projection.to_dict()
        return WorkbenchSseEvent(
            event_id=_digest(
                "agent-stream",
                {
                    "event_type": "agent_run_snapshot",
                    "identity": projection.run_id,
                    "projection": payload,
                },
            ),
            event_type="agent_run_snapshot",
            identity=projection.run_id,
            occurred_at=projection.updated_at,
            projection=payload,
        )

    @staticmethod
    def event_for_command(
        projection: CommandRunStreamProjection,
    ) -> WorkbenchSseEvent:
        payload = projection.to_dict()
        return WorkbenchSseEvent(
            event_id=_digest(
                "command-stream",
                {
                    "event_type": "command_run_snapshot",
                    "identity": projection.command_run_id,
                    "projection": payload,
                },
            ),
            event_type="command_run_snapshot",
            identity=projection.command_run_id,
            occurred_at=projection.updated_at,
            projection=payload,
        )

    def status(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.workbench.stream-status.v1",
            "read_only": True,
            "transport": "sse",
            "agent_configured": self.agent_configured,
            "command_store_configured": self.command_configured,
            "command_store_available": self.command_runs.available,
            "event_types": ["agent_run_snapshot", "command_run_snapshot"],
            "hidden_reasoning": "not_persisted_not_projected",
            "raw_provider_callbacks": False,
            "raw_otlp_phoenix": False,
            "arbitrary_command_outputs": False,
            "host_artifact_paths": False,
        }


def sse_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }


async def _stream_events(
    request: Request,
    *,
    initial: TProjection,
    loader: Callable[[], TProjection],
    event_builder: Callable[[TProjection], WorkbenchSseEvent],
    poll_seconds: float = 0.75,
    heartbeat_seconds: float = 15.0,
) -> AsyncIterator[str]:
    last_sent = request.headers.get("last-event-id", "").strip()
    current = initial
    heartbeat_at = time.monotonic()
    while True:
        if await request.is_disconnected():
            return
        event = event_builder(current)
        if event.event_id != last_sent:
            yield event.to_sse()
            last_sent = event.event_id
        now = time.monotonic()
        if now - heartbeat_at >= heartbeat_seconds:
            yield ": keepalive\n\n"
            heartbeat_at = now
        await asyncio.sleep(poll_seconds)
        try:
            current = await asyncio.to_thread(loader)
        except (KeyError, FileNotFoundError, sqlite3.Error, EvidenceContractError):
            return


def sse_response(
    request: Request,
    *,
    initial: TProjection,
    loader: Callable[[], TProjection],
    event_builder: Callable[[TProjection], WorkbenchSseEvent],
    once: bool,
) -> Response:
    if once:
        return Response(
            content=event_builder(initial).to_sse(),
            media_type="text/event-stream",
            headers=sse_headers(),
        )
    return StreamingResponse(
        _stream_events(
            request,
            initial=initial,
            loader=loader,
            event_builder=event_builder,
        ),
        media_type="text/event-stream",
        headers=sse_headers(),
    )

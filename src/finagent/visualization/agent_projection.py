from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .semantic import EvidenceContractError


class AgentProjectionItemType(str, Enum):
    PLAN = "plan"
    LLM = "llm"
    TOOL = "tool"
    GUARDRAIL = "guardrail"
    EVIDENCE = "evidence"
    DECISION = "decision"
    APPROVAL = "approval"
    RESULT = "result"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AgentProjectionItem:
    item_id: str
    item_type: AgentProjectionItemType
    occurred_at: datetime
    title: str
    status: str
    summary: str = ""
    call_id: str = ""
    evidence_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.item_id or not self.title or not self.status:
            raise EvidenceContractError("Agent projection item identity/title/status is required")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise EvidenceContractError("Agent projection item time must be timezone-aware")
        evidence = tuple(str(value).strip() for value in self.evidence_ids if str(value).strip())
        if len(set(evidence)) != len(evidence):
            raise EvidenceContractError("Agent projection evidence ids must be unique")
        object.__setattr__(self, "evidence_ids", evidence)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "item_type": self.item_type.value,
            "occurred_at": self.occurred_at.isoformat(),
            "title": self.title,
            "status": self.status,
            "summary": self.summary,
            "call_id": self.call_id,
            "evidence_ids": list(self.evidence_ids),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class AgentTokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        values = (
            self.prompt_tokens,
            self.completion_tokens,
            self.reasoning_tokens,
            self.total_tokens,
        )
        if any(value < 0 for value in values):
            raise EvidenceContractError("Agent token usage must be non-negative")
        if self.total_tokens and self.total_tokens < self.prompt_tokens + self.completion_tokens:
            raise EvidenceContractError("Agent total_tokens is smaller than prompt+completion")

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True, slots=True)
class AgentRunProjection:
    run_id: str
    task_id: str
    actor: str
    trigger_type: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    objective: str
    items: tuple[AgentProjectionItem, ...]
    project_id: str = ""
    thread_id: str = ""
    artifact_ids: tuple[str, ...] = ()
    token_usage: AgentTokenUsage = field(default_factory=AgentTokenUsage)
    latency_ms: float = 0.0
    governance: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""

    def __post_init__(self) -> None:
        for name in ("run_id", "task_id", "actor", "trigger_type", "status", "objective"):
            if not str(getattr(self, name)).strip():
                raise EvidenceContractError(f"AgentRunProjection.{name} must be non-empty")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise EvidenceContractError("Agent run start time must be timezone-aware")
        if self.finished_at is not None:
            if self.finished_at.tzinfo is None or self.finished_at.utcoffset() is None:
                raise EvidenceContractError("Agent run finish time must be timezone-aware")
            if self.finished_at < self.started_at:
                raise EvidenceContractError("Agent run cannot finish before it starts")
        if self.latency_ms < 0:
            raise EvidenceContractError("Agent run latency must be non-negative")
        item_ids = {item.item_id for item in self.items}
        if len(item_ids) != len(self.items):
            raise EvidenceContractError("Agent projection item ids must be unique")
        artifacts = tuple(str(value).strip() for value in self.artifact_ids if str(value).strip())
        if len(set(artifacts)) != len(artifacts):
            raise EvidenceContractError("Agent projection artifact ids must be unique")
        object.__setattr__(self, "artifact_ids", artifacts)
        object.__setattr__(self, "governance", MappingProxyType(dict(self.governance)))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.visualization.agent-run-projection.v1",
            "run_id": self.run_id,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "thread_id": self.thread_id,
            "actor": self.actor,
            "trigger_type": self.trigger_type,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "objective": self.objective,
            "items": [item.to_dict() for item in self.items],
            "artifact_ids": list(self.artifact_ids),
            "token_usage": self.token_usage.to_dict(),
            "latency_ms": self.latency_ms,
            "governance": dict(self.governance),
            "error": self.error,
            "hidden_reasoning": "not_persisted_not_projected",
        }


def _connect_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _json_object(raw: object, name: str) -> Mapping[str, Any]:
    if raw is None:
        return {}
    try:
        value = json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise EvidenceContractError(f"{name} contains invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise EvidenceContractError(f"{name} must decode to an object")
    return value


def _parse_time(value: object, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise EvidenceContractError(f"invalid {name} timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceContractError(f"{name} timestamp must be timezone-aware")
    return parsed


def _extract_evidence_ids(value: object) -> tuple[str, ...]:
    interesting_keys = {
        "evidence_id",
        "artifact_id",
        "report_id",
        "acceptance_id",
        "program_result_id",
        "portfolio_validation_id",
        "selection_id",
        "feedback_id",
        "feature_digest",
        "ensemble_id",
        "ledger_digest",
    }
    output: list[str] = []

    def walk(item: object, key: str = "") -> None:
        if isinstance(item, Mapping):
            for child_key, child_value in item.items():
                walk(child_value, str(child_key))
            return
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            for child in item:
                walk(child, key)
            return
        if key in interesting_keys and item is not None:
            text = str(item).strip()
            if text and text not in output:
                output.append(text)

    walk(value)
    return tuple(output)


def _event_item(
    *,
    sequence: int,
    event_id: str,
    event_type: str,
    occurred_at: datetime,
    call_id: str,
    payload: Mapping[str, Any],
) -> AgentProjectionItem:
    if event_type == "run_started":
        return AgentProjectionItem(
            item_id=event_id,
            item_type=AgentProjectionItemType.PLAN,
            occurred_at=occurred_at,
            title="Run started",
            status="started",
            summary=f"Actor {payload.get('actor', '')} started task {payload.get('task_id', '')}".strip(),
            metadata={"sequence": sequence, **dict(payload)},
        )
    if event_type == "tool_requested":
        tool_name = str(payload.get("tool_name", "tool"))
        return AgentProjectionItem(
            item_id=event_id,
            item_type=AgentProjectionItemType.TOOL,
            occurred_at=occurred_at,
            title=f"Requested {tool_name}",
            status="requested",
            call_id=call_id,
            evidence_ids=_extract_evidence_ids(payload),
            metadata={"sequence": sequence, **dict(payload)},
        )
    if event_type == "policy_decided":
        outcome = str(payload.get("outcome", "unknown"))
        item_type = (
            AgentProjectionItemType.APPROVAL
            if outcome == "require_human"
            else AgentProjectionItemType.GUARDRAIL
        )
        return AgentProjectionItem(
            item_id=event_id,
            item_type=item_type,
            occurred_at=occurred_at,
            title=f"Policy {outcome}",
            status=outcome,
            summary=str(payload.get("reason", "")),
            call_id=call_id,
            metadata={"sequence": sequence, **dict(payload)},
        )
    if event_type == "tool_finished":
        status = str(payload.get("status", "unknown"))
        error = str(payload.get("error", "") or "")
        return AgentProjectionItem(
            item_id=event_id,
            item_type=(
                AgentProjectionItemType.ERROR
                if status in {"failed", "denied"}
                else AgentProjectionItemType.TOOL
            ),
            occurred_at=occurred_at,
            title=f"Tool {status}",
            status=status,
            summary=error,
            call_id=call_id,
            evidence_ids=_extract_evidence_ids(payload),
            metadata={"sequence": sequence, **dict(payload)},
        )
    if event_type == "run_finished":
        status = str(payload.get("status", "unknown"))
        return AgentProjectionItem(
            item_id=event_id,
            item_type=(
                AgentProjectionItemType.ERROR
                if status == "failed"
                else AgentProjectionItemType.RESULT
            ),
            occurred_at=occurred_at,
            title="Run finished",
            status=status,
            summary=str(payload.get("summary", "")),
            evidence_ids=_extract_evidence_ids(payload),
            metadata={"sequence": sequence, **dict(payload)},
        )
    return AgentProjectionItem(
        item_id=event_id,
        item_type=AgentProjectionItemType.DECISION,
        occurred_at=occurred_at,
        title=event_type,
        status="recorded",
        call_id=call_id,
        evidence_ids=_extract_evidence_ids(payload),
        metadata={"sequence": sequence, **dict(payload)},
    )


def load_agent_run_projection(
    path: str | Path,
    run_id: str,
) -> AgentRunProjection:
    """Project the canonical Agent audit DB into a UI-ready, read-only run model.

    OTLP/Phoenix spans are deliberately not consumed here.  They remain diagnostic
    evidence and can be linked separately in V1 without changing this stable contract.
    """

    source = Path(path).expanduser()
    with _connect_read_only(source) as connection:
        row = connection.execute(
            "SELECT task_id, payload_json, decision_json FROM agent_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        task_id = str(row[0])
        run_payload = _json_object(row[1], "agent run payload")
        decision = _json_object(row[2], "agent decision") if row[2] is not None else {}
        event_rows = connection.execute(
            "SELECT sequence, event_id, event_type, occurred_at, call_id, payload_json "
            "FROM agent_audit_events WHERE run_id=? ORDER BY sequence",
            (run_id,),
        ).fetchall()
        policy_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM agent_policy_decisions WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
        )
        tool_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM agent_tool_calls WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
        )

    task = run_payload.get("task", {})
    context = run_payload.get("context", {})
    if not isinstance(task, Mapping) or not isinstance(context, Mapping):
        raise EvidenceContractError("agent run payload lacks task/context objects")
    started_at = _parse_time(context.get("started_at"), "started_at")
    finished_at = (
        _parse_time(decision.get("finished_at"), "finished_at")
        if decision.get("finished_at")
        else None
    )
    items = tuple(
        _event_item(
            sequence=int(sequence),
            event_id=str(event_id),
            event_type=str(event_type),
            occurred_at=_parse_time(occurred_at, "audit event"),
            call_id=str(call_id or ""),
            payload=_json_object(payload_json, "agent audit event payload"),
        )
        for sequence, event_id, event_type, occurred_at, call_id, payload_json in event_rows
    )
    artifact_ids = tuple(
        dict.fromkeys(
            evidence_id
            for item in items
            for evidence_id in item.evidence_ids
        )
    )
    context_metadata = context.get("metadata", {})
    if not isinstance(context_metadata, Mapping):
        context_metadata = {}
    status = str(decision.get("status", "running"))
    error = ""
    if status == "failed":
        error = str(decision.get("summary", "Agent run failed"))
    latency_ms = (
        max(0.0, (finished_at - started_at).total_seconds() * 1000.0)
        if finished_at is not None
        else 0.0
    )
    allowlist = context.get("tool_allowlist", ())
    if isinstance(allowlist, (str, bytes)) or not isinstance(allowlist, Sequence):
        allowlist = ()
    return AgentRunProjection(
        run_id=run_id,
        task_id=task_id,
        actor=str(context.get("actor", "unknown")),
        trigger_type=str(context_metadata.get("trigger_type", "manual")),
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        objective=str(task.get("objective", "unknown objective")),
        items=items,
        project_id=str(context_metadata.get("project_id", "")),
        thread_id=str(context_metadata.get("thread_id", "")),
        artifact_ids=artifact_ids,
        latency_ms=latency_ms,
        governance={
            "max_tool_calls": int(context.get("max_tool_calls", 0)),
            "tool_allowlist": list(allowlist),
            "tool_call_count": tool_count,
            "policy_decision_count": policy_count,
            "audit_source": str(source),
            "audit_access": "sqlite_read_only",
        },
        error=error,
    )

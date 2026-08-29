from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Literal

COMMAND_INTENT_SCHEMA = "finagent.workbench.command-intent.v1"
COMMAND_RUN_SCHEMA = "finagent.workbench.command-run.v1"
COMMAND_RESULT_SCHEMA = "finagent.workbench.command-result.v1"
COMMAND_EVENT_SCHEMA = "finagent.workbench.command-event.v1"
COMMAND_RECORD_SCHEMA = "finagent.workbench.command-record.v1"

CommandIntentState = Literal["draft", "validated", "rejected"]
CommandRunState = Literal["planned", "running", "succeeded", "failed", "rejected"]
CommandResultStatus = Literal["succeeded", "failed", "rejected"]


@dataclass(frozen=True, slots=True)
class CommandIntent:
    intent_id: str
    command_id: str
    config_snapshot_id: str | None
    context: Mapping[str, str]
    requested_by: str
    state: CommandIntentState
    schema_version: str = COMMAND_INTENT_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "context": dict(self.context)}


@dataclass(frozen=True, slots=True)
class CommandRun:
    command_run_id: str
    intent_id: str
    command_id: str
    state: CommandRunState
    started_at: str | None
    finished_at: str | None
    schema_version: str = COMMAND_RUN_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CommandResult:
    command_run_id: str
    status: CommandResultStatus
    evidence_ids: tuple[str, ...]
    message: str
    schema_version: str = COMMAND_RESULT_SCHEMA

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["evidence_ids"] = list(self.evidence_ids)
        return payload


@dataclass(frozen=True, slots=True)
class CommandEvent:
    event_id: str
    command_run_id: str
    sequence: int
    event_type: str
    state: CommandRunState
    occurred_at: str
    message: str = ""
    schema_version: str = COMMAND_EVENT_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CommandRecord:
    intent: CommandIntent
    run: CommandRun
    parameters: Mapping[str, object]
    created_at: str
    updated_at: str
    result: CommandResult | None = None
    artifact_paths: tuple[str, ...] = ()
    outputs: Mapping[str, object] | None = None
    events: tuple[CommandEvent, ...] = ()
    schema_version: str = COMMAND_RECORD_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "intent": self.intent.to_dict(),
            "run": self.run.to_dict(),
            "parameters": dict(self.parameters),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result.to_dict() if self.result is not None else None,
            "artifact_paths": list(self.artifact_paths),
            "outputs": dict(self.outputs or {}),
            "events": [item.to_dict() for item in self.events],
        }

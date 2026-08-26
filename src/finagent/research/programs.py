from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Protocol

from finagent.domain._validation import require_non_empty


class PlanLike(Protocol):
    program_id: str
    family_id: str
    alpha: float
    variants: tuple[object, ...]

    def fingerprint(self, task_id: str) -> str: ...


class ResearchProgramStatus(str, Enum):
    OPEN = "open"
    FROZEN = "frozen"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class ResearchProgram:
    """Cross-family statistical/search budget for an autonomous research program."""

    program_id: str
    alpha_budget: float = 0.05
    max_families: int = 20
    max_experiments: int = 100
    sealed_holdout_id: str = ""
    status: ResearchProgramStatus = ResearchProgramStatus.OPEN

    def __post_init__(self) -> None:
        object.__setattr__(self, "program_id", require_non_empty(self.program_id, "program_id"))
        if not 0.0 < float(self.alpha_budget) < 1.0:
            raise ValueError("alpha_budget must be in (0, 1)")
        if self.max_families < 1 or self.max_experiments < 1:
            raise ValueError("program family/experiment budgets must be >= 1")
        if self.max_experiments < self.max_families:
            raise ValueError("max_experiments cannot be below max_families")
        object.__setattr__(self, "sealed_holdout_id", self.sealed_holdout_id.strip())


@dataclass(frozen=True, slots=True)
class ProgramReservation:
    program_id: str
    family_id: str
    plan_fingerprint: str
    alpha_spent: float
    experiment_count: int
    reserved_at: datetime


@dataclass(frozen=True, slots=True)
class ProgramBudgetSnapshot:
    program_id: str
    family_count: int
    experiment_count: int
    alpha_spent: float
    alpha_remaining: float
    max_families: int
    max_experiments: int


@dataclass(frozen=True, slots=True)
class ProgramLifecycleEvent:
    program_id: str
    from_status: ResearchProgramStatus
    to_status: ResearchProgramStatus
    actor: str
    reason: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ProgramLifecycleSnapshot:
    program_id: str
    status: ResearchProgramStatus
    holdout_consumed: bool
    frozen_at: datetime | None = None
    closed_at: datetime | None = None


class SQLiteResearchProgramStore:
    """Durable search-budget and lifecycle ledger across ExperimentFamily objects.

    Program registration remains immutable. Lifecycle transitions are append-only so
    older 1.0/1.2 databases can be upgraded without rewriting their program payloads.
    Exact replay of an already-reserved plan remains idempotent after freezing; only
    new research reservations are blocked.
    """

    _ALLOWED_TRANSITIONS = {
        ResearchProgramStatus.OPEN: frozenset({ResearchProgramStatus.FROZEN}),
        ResearchProgramStatus.FROZEN: frozenset({ResearchProgramStatus.CLOSED}),
        ResearchProgramStatus.CLOSED: frozenset(),
    }

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_programs (
                    program_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_program_reservations (
                    program_id TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    plan_fingerprint TEXT NOT NULL,
                    alpha_spent REAL NOT NULL,
                    experiment_count INTEGER NOT NULL,
                    reserved_at TEXT NOT NULL,
                    PRIMARY KEY (program_id, family_id)
                );
                CREATE TABLE IF NOT EXISTS research_program_holdout_access (
                    program_id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    accessed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_program_lifecycle_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    program_id TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_research_program_lifecycle_target
                    ON research_program_lifecycle_events(program_id, to_status);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    @staticmethod
    def _decode_program(payload_json: str, status: ResearchProgramStatus) -> ResearchProgram:
        payload = json.loads(payload_json)
        return ResearchProgram(
            program_id=payload["program_id"],
            alpha_budget=float(payload["alpha_budget"]),
            max_families=int(payload["max_families"]),
            max_experiments=int(payload["max_experiments"]),
            sealed_holdout_id=payload.get("sealed_holdout_id", ""),
            status=status,
        )

    @staticmethod
    def _base_status(payload_json: str) -> ResearchProgramStatus:
        payload = json.loads(payload_json)
        return ResearchProgramStatus(payload.get("status", ResearchProgramStatus.OPEN.value))

    @staticmethod
    def _payload_row(con: sqlite3.Connection, program_id: str) -> str:
        row = con.execute(
            "SELECT payload_json FROM research_programs WHERE program_id=?",
            (program_id,),
        ).fetchone()
        if row is None:
            raise KeyError(program_id)
        return str(row[0])

    @classmethod
    def _status_in_connection(
        cls,
        con: sqlite3.Connection,
        program_id: str,
        payload_json: str,
    ) -> ResearchProgramStatus:
        row = con.execute(
            "SELECT to_status FROM research_program_lifecycle_events "
            "WHERE program_id=? ORDER BY event_id DESC LIMIT 1",
            (program_id,),
        ).fetchone()
        if row is None:
            return cls._base_status(payload_json)
        return ResearchProgramStatus(str(row[0]))

    @staticmethod
    def _holdout_consumed_in_connection(con: sqlite3.Connection, program_id: str) -> bool:
        row = con.execute(
            "SELECT 1 FROM research_program_holdout_access WHERE program_id=?",
            (program_id,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _event_from_row(row) -> ProgramLifecycleEvent:
        return ProgramLifecycleEvent(
            program_id=str(row[0]),
            from_status=ResearchProgramStatus(str(row[1])),
            to_status=ResearchProgramStatus(str(row[2])),
            actor=str(row[3]),
            reason=str(row[4]),
            occurred_at=datetime.fromisoformat(str(row[5])),
        )

    def register(self, program: ResearchProgram) -> None:
        payload = json.dumps(
            {
                "program_id": program.program_id,
                "alpha_budget": program.alpha_budget,
                "max_families": program.max_families,
                "max_experiments": program.max_experiments,
                "sealed_holdout_id": program.sealed_holdout_id,
                "status": program.status.value,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connect() as con:
            existing = con.execute(
                "SELECT payload_json FROM research_programs WHERE program_id=?",
                (program.program_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != payload:
                    raise ValueError(f"research program {program.program_id!r} is immutable")
                return
            con.execute(
                "INSERT INTO research_programs VALUES (?, ?)",
                (program.program_id, payload),
            )

    def get(self, program_id: str) -> ResearchProgram:
        with self._connect() as con:
            payload_json = self._payload_row(con, program_id)
            status = self._status_in_connection(con, program_id, payload_json)
        return self._decode_program(payload_json, status)

    def lifecycle_events(self, program_id: str) -> tuple[ProgramLifecycleEvent, ...]:
        with self._connect() as con:
            self._payload_row(con, program_id)
            rows = con.execute(
                "SELECT program_id, from_status, to_status, actor, reason, occurred_at "
                "FROM research_program_lifecycle_events WHERE program_id=? "
                "ORDER BY event_id",
                (program_id,),
            ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def lifecycle_snapshot(self, program_id: str) -> ProgramLifecycleSnapshot:
        program = self.get(program_id)
        events = self.lifecycle_events(program_id)
        frozen_at = next(
            (event.occurred_at for event in events if event.to_status is ResearchProgramStatus.FROZEN),
            None,
        )
        closed_at = next(
            (event.occurred_at for event in events if event.to_status is ResearchProgramStatus.CLOSED),
            None,
        )
        with self._connect() as con:
            holdout_consumed = self._holdout_consumed_in_connection(con, program_id)
        return ProgramLifecycleSnapshot(
            program_id=program_id,
            status=program.status,
            holdout_consumed=holdout_consumed,
            frozen_at=frozen_at,
            closed_at=closed_at,
        )

    def _transition(
        self,
        program_id: str,
        target: ResearchProgramStatus,
        *,
        actor: str,
        reason: str,
        occurred_at: datetime | None,
    ) -> ProgramLifecycleEvent:
        actor = require_non_empty(actor, "actor")
        reason = require_non_empty(reason, "reason")
        occurred_at = occurred_at or datetime.now(timezone.utc)
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            payload_json = self._payload_row(con, program_id)
            current = self._status_in_connection(con, program_id, payload_json)
            if current is target:
                row = con.execute(
                    "SELECT program_id, from_status, to_status, actor, reason, occurred_at "
                    "FROM research_program_lifecycle_events "
                    "WHERE program_id=? AND to_status=?",
                    (program_id, target.value),
                ).fetchone()
                if row is None:
                    raise PermissionError(
                        "program was registered in the target state and has no lifecycle event"
                    )
                return self._event_from_row(row)
            if target not in self._ALLOWED_TRANSITIONS[current]:
                raise PermissionError(
                    f"invalid research program transition {current.value!r} -> {target.value!r}"
                )
            if target is ResearchProgramStatus.CLOSED:
                payload = json.loads(payload_json)
                if payload.get("sealed_holdout_id") and not self._holdout_consumed_in_connection(
                    con, program_id
                ):
                    raise PermissionError(
                        "research program cannot close before its sealed holdout is consumed"
                    )
            con.execute(
                "INSERT INTO research_program_lifecycle_events "
                "(program_id, from_status, to_status, actor, reason, occurred_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    program_id,
                    current.value,
                    target.value,
                    actor,
                    reason,
                    occurred_at.isoformat(),
                ),
            )
        return ProgramLifecycleEvent(
            program_id=program_id,
            from_status=current,
            to_status=target,
            actor=actor,
            reason=reason,
            occurred_at=occurred_at,
        )

    def freeze_program(
        self,
        program_id: str,
        *,
        actor: str,
        reason: str = "research search space frozen before holdout access",
        occurred_at: datetime | None = None,
    ) -> ProgramLifecycleEvent:
        return self._transition(
            program_id,
            ResearchProgramStatus.FROZEN,
            actor=actor,
            reason=reason,
            occurred_at=occurred_at,
        )

    def close_program(
        self,
        program_id: str,
        *,
        actor: str,
        reason: str = "research program closed after final evaluation",
        occurred_at: datetime | None = None,
    ) -> ProgramLifecycleEvent:
        return self._transition(
            program_id,
            ResearchProgramStatus.CLOSED,
            actor=actor,
            reason=reason,
            occurred_at=occurred_at,
        )

    def reserve_plan(
        self,
        plan: PlanLike,
        *,
        task_id: str,
        reserved_at: datetime | None = None,
    ) -> ProgramReservation:
        if not plan.program_id:
            raise ValueError("ResearchPlan.program_id is required for program-governed execution")
        fingerprint = plan.fingerprint(task_id)
        reserved_at = reserved_at or datetime.now(timezone.utc)
        family_alpha = float(plan.alpha)
        experiment_count = len(plan.variants)

        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            payload_json = self._payload_row(con, plan.program_id)
            program_status = self._status_in_connection(con, plan.program_id, payload_json)
            program = self._decode_program(payload_json, program_status)
            existing = con.execute(
                "SELECT plan_fingerprint, alpha_spent, experiment_count, reserved_at "
                "FROM research_program_reservations WHERE program_id=? AND family_id=?",
                (program.program_id, plan.family_id),
            ).fetchone()
            if existing is not None:
                if existing[0] != fingerprint:
                    raise ValueError("family_id is already reserved by a different plan")
                return ProgramReservation(
                    program.program_id,
                    plan.family_id,
                    str(existing[0]),
                    float(existing[1]),
                    int(existing[2]),
                    datetime.fromisoformat(str(existing[3])),
                )
            if program.status is not ResearchProgramStatus.OPEN:
                raise PermissionError(
                    "new research reservations require an open program; "
                    f"current status={program.status.value}"
                )

            aggregate = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(experiment_count),0), "
                "COALESCE(SUM(alpha_spent),0.0) FROM research_program_reservations "
                "WHERE program_id=?",
                (program.program_id,),
            ).fetchone()
            family_count = int(aggregate[0])
            used_experiments = int(aggregate[1])
            used_alpha = float(aggregate[2])
            if family_count + 1 > program.max_families:
                raise PermissionError("research program family budget exhausted")
            if used_experiments + experiment_count > program.max_experiments:
                raise PermissionError("research program experiment budget exhausted")
            if used_alpha + family_alpha > program.alpha_budget + 1e-12:
                raise PermissionError("research program alpha-spending budget exhausted")
            con.execute(
                "INSERT INTO research_program_reservations VALUES (?, ?, ?, ?, ?, ?)",
                (
                    program.program_id,
                    plan.family_id,
                    fingerprint,
                    family_alpha,
                    experiment_count,
                    reserved_at.isoformat(),
                ),
            )
        return ProgramReservation(
            program.program_id,
            plan.family_id,
            fingerprint,
            family_alpha,
            experiment_count,
            reserved_at,
        )

    def budget_snapshot(self, program_id: str) -> ProgramBudgetSnapshot:
        program = self.get(program_id)
        with self._connect() as con:
            aggregate = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(experiment_count),0), "
                "COALESCE(SUM(alpha_spent),0.0) FROM research_program_reservations "
                "WHERE program_id=?",
                (program_id,),
            ).fetchone()
        families = int(aggregate[0])
        experiments = int(aggregate[1])
        alpha_spent = float(aggregate[2])
        return ProgramBudgetSnapshot(
            program_id=program_id,
            family_count=families,
            experiment_count=experiments,
            alpha_spent=alpha_spent,
            alpha_remaining=max(0.0, program.alpha_budget - alpha_spent),
            max_families=program.max_families,
            max_experiments=program.max_experiments,
        )

    def consume_sealed_holdout(
        self,
        program_id: str,
        *,
        actor: str,
        accessed_at: datetime | None = None,
    ) -> Mapping[str, str]:
        actor = require_non_empty(actor, "actor")
        accessed_at = accessed_at or datetime.now(timezone.utc)
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            payload_json = self._payload_row(con, program_id)
            status = self._status_in_connection(con, program_id, payload_json)
            program = self._decode_program(payload_json, status)
            if not program.sealed_holdout_id:
                raise ValueError("research program has no sealed_holdout_id")
            if program.status is not ResearchProgramStatus.FROZEN:
                raise PermissionError(
                    "sealed holdout access requires a frozen research program; "
                    f"current status={program.status.value}"
                )
            existing = con.execute(
                "SELECT actor, accessed_at FROM research_program_holdout_access WHERE program_id=?",
                (program_id,),
            ).fetchone()
            if existing is not None:
                raise PermissionError("sealed holdout has already been consumed for this program")
            con.execute(
                "INSERT INTO research_program_holdout_access VALUES (?, ?, ?)",
                (program_id, actor, accessed_at.isoformat()),
            )
        return MappingProxyType(
            {
                "program_id": program_id,
                "holdout_id": program.sealed_holdout_id,
                "actor": actor,
                "accessed_at": accessed_at.isoformat(),
            }
        )


class ResearchProgramGuard:
    """Coordinator hook that spends program budget before any research tool executes."""

    def __init__(self, store: SQLiteResearchProgramStore) -> None:
        self.store = store

    def authorize_plan(self, plan: PlanLike, *, task_id: str) -> ProgramReservation:
        return self.store.reserve_plan(plan, task_id=task_id)

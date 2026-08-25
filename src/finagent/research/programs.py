from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from finagent.agents.planning import ResearchPlan
from finagent.domain._validation import require_non_empty


class ResearchProgramStatus(str, Enum):
    OPEN = "open"
    FROZEN = "frozen"


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


class SQLiteResearchProgramStore:
    """Durable alpha-spending/search-budget ledger across ExperimentFamily objects."""

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
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

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
            row = con.execute(
                "SELECT payload_json FROM research_programs WHERE program_id=?",
                (program_id,),
            ).fetchone()
        if row is None:
            raise KeyError(program_id)
        payload = json.loads(row[0])
        return ResearchProgram(
            program_id=payload["program_id"],
            alpha_budget=float(payload["alpha_budget"]),
            max_families=int(payload["max_families"]),
            max_experiments=int(payload["max_experiments"]),
            sealed_holdout_id=payload["sealed_holdout_id"],
            status=ResearchProgramStatus(payload["status"]),
        )

    def reserve_plan(
        self,
        plan: ResearchPlan,
        *,
        task_id: str,
        reserved_at: datetime | None = None,
    ) -> ProgramReservation:
        if not plan.program_id:
            raise ValueError("ResearchPlan.program_id is required for program-governed execution")
        program = self.get(plan.program_id)
        if program.status is not ResearchProgramStatus.OPEN:
            raise PermissionError("research program is frozen")
        fingerprint = plan.fingerprint(task_id)
        reserved_at = reserved_at or datetime.now(timezone.utc)
        family_alpha = float(plan.alpha)
        experiment_count = len(plan.variants)

        with self._connect() as con:
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
                    existing[0],
                    float(existing[1]),
                    int(existing[2]),
                    datetime.fromisoformat(existing[3]),
                )

            aggregate = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(experiment_count),0), COALESCE(SUM(alpha_spent),0.0) "
                "FROM research_program_reservations WHERE program_id=?",
                (program.program_id,),
            ).fetchone()
            family_count, used_experiments, used_alpha = int(aggregate[0]), int(aggregate[1]), float(aggregate[2])
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
                "SELECT COUNT(*), COALESCE(SUM(experiment_count),0), COALESCE(SUM(alpha_spent),0.0) "
                "FROM research_program_reservations WHERE program_id=?",
                (program_id,),
            ).fetchone()
        families, experiments, alpha_spent = int(aggregate[0]), int(aggregate[1]), float(aggregate[2])
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
        program = self.get(program_id)
        if not program.sealed_holdout_id:
            raise ValueError("research program has no sealed_holdout_id")
        accessed_at = accessed_at or datetime.now(timezone.utc)
        actor = require_non_empty(actor, "actor")
        with self._connect() as con:
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

    def authorize_plan(self, plan: ResearchPlan, *, task_id: str) -> ProgramReservation:
        return self.store.reserve_plan(plan, task_id=task_id)

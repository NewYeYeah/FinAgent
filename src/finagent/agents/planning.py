from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from finagent.domain._validation import require_non_empty

Scalar = str | int | float | bool


@dataclass(frozen=True, slots=True)
class ResearchBudget:
    max_tool_calls: int
    max_experiments: int
    max_family_size: int
    max_failed_experiments: int = 0
    allow_new_family: bool = True
    allow_promotion_request: bool = False

    def __post_init__(self) -> None:
        for name in ("max_tool_calls", "max_experiments", "max_family_size"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be an integer >= 1")
        if isinstance(self.max_failed_experiments, bool) or self.max_failed_experiments < 0:
            raise ValueError("max_failed_experiments must be an integer >= 0")
        if self.max_failed_experiments > self.max_experiments:
            raise ValueError("max_failed_experiments cannot exceed max_experiments")


@dataclass(frozen=True, slots=True)
class ExperimentVariant:
    variant_id: str
    experiment_id: str
    parameters: Mapping[str, Scalar]
    hypothesis: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "variant_id", require_non_empty(self.variant_id, "variant_id"))
        object.__setattr__(self, "experiment_id", require_non_empty(self.experiment_id, "experiment_id"))
        object.__setattr__(self, "hypothesis", require_non_empty(self.hypothesis, "hypothesis"))
        normalized: dict[str, Scalar] = {}
        for key, value in self.parameters.items():
            key = require_non_empty(str(key), "parameter name")
            if not isinstance(value, (str, int, float, bool)):
                raise TypeError("variant parameters must be scalar")
            normalized[key] = value
        object.__setattr__(self, "parameters", MappingProxyType(normalized))


@dataclass(frozen=True, slots=True)
class PromotionIntent:
    model_id: str
    to_stage: str
    reason: str

    def __post_init__(self) -> None:
        for name in ("model_id", "to_stage", "reason"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class ResearchPlan:
    plan_id: str
    planner_version: str
    family_id: str
    research_question: str
    primary_metric: str
    template_id: str
    variants: tuple[ExperimentVariant, ...]
    budget: ResearchBudget
    tie_break_metric: str = "turnover"
    alpha: float = 0.05
    correction_method: str = "holm"
    promotion_intent: PromotionIntent | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("plan_id", "planner_version", "family_id", "research_question", "primary_metric", "template_id"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        variants = tuple(self.variants)
        if not variants:
            raise ValueError("ResearchPlan requires at least one variant")
        if len({v.variant_id for v in variants}) != len(variants) or len({v.experiment_id for v in variants}) != len(variants):
            raise ValueError("variant_id and experiment_id values must be unique")
        if len(variants) > self.budget.max_experiments or len(variants) > self.budget.max_family_size:
            raise ValueError("plan variants exceed research budget")
        if self.promotion_intent is not None and not self.budget.allow_promotion_request:
            raise ValueError("promotion_intent requires allow_promotion_request=True")
        if not 0.0 < float(self.alpha) < 1.0:
            raise ValueError("alpha must be in (0, 1)")
        object.__setattr__(self, "tie_break_metric", self.tie_break_metric.strip())
        object.__setattr__(self, "metadata", MappingProxyType({str(k): str(v) for k, v in self.metadata.items()}))
        if self.maximum_tool_calls > self.budget.max_tool_calls:
            raise ValueError("plan maximum tool calls exceed ResearchBudget.max_tool_calls")

    @property
    def maximum_tool_calls(self) -> int:
        # list + create + N register + N run + primary compare + freeze + validate
        count = 5 + 2 * len(self.variants)
        if self.tie_break_metric:
            count += 1
        if self.promotion_intent is not None:
            count += 1
        return count

    def to_payload(self, task_id: str) -> dict[str, object]:
        return {
            "task_id": require_non_empty(task_id, "task_id"),
            "plan_id": self.plan_id,
            "planner_version": self.planner_version,
            "family_id": self.family_id,
            "research_question": self.research_question,
            "primary_metric": self.primary_metric,
            "template_id": self.template_id,
            "variants": [{"variant_id": v.variant_id, "experiment_id": v.experiment_id, "parameters": dict(v.parameters), "hypothesis": v.hypothesis} for v in self.variants],
            "budget": {"max_tool_calls": self.budget.max_tool_calls, "max_experiments": self.budget.max_experiments, "max_family_size": self.budget.max_family_size, "max_failed_experiments": self.budget.max_failed_experiments, "allow_new_family": self.budget.allow_new_family, "allow_promotion_request": self.budget.allow_promotion_request},
            "tie_break_metric": self.tie_break_metric,
            "alpha": float(self.alpha),
            "correction_method": self.correction_method,
            "promotion_intent": None if self.promotion_intent is None else {"model_id": self.promotion_intent.model_id, "to_stage": self.promotion_intent.to_stage, "reason": self.promotion_intent.reason},
            "metadata": dict(self.metadata),
        }

    def fingerprint(self, task_id: str) -> str:
        encoded = json.dumps(self.to_payload(task_id), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class StoredResearchPlan:
    run_id: str
    task_id: str
    fingerprint: str
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ResearchRunSummary:
    run_id: str
    plan_fingerprint: str
    family_id: str
    selected_experiment_id: str = ""
    validation_passed: bool | None = None
    tool_calls: int = 0
    failed_experiments: int = 0


class SQLiteAgentPlanStore:
    """Append-only plan/selection store; research state remains in ResearchRegistry."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS agent_plans (
                    run_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, fingerprint TEXT NOT NULL, payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_plan_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def record_plan(self, run_id: str, task_id: str, plan: ResearchPlan) -> StoredResearchPlan:
        payload = plan.to_payload(task_id)
        fingerprint = plan.fingerprint(task_id)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self._connect() as con:
            try:
                con.execute("INSERT INTO agent_plans VALUES (?, ?, ?, ?)", (run_id, task_id, fingerprint, encoded))
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"agent plan for run {run_id!r} is already registered") from exc
        return StoredResearchPlan(run_id, task_id, fingerprint, MappingProxyType(payload))

    def get_plan(self, run_id: str) -> StoredResearchPlan:
        with self._connect() as con:
            row = con.execute("SELECT task_id, fingerprint, payload_json FROM agent_plans WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return StoredResearchPlan(run_id, row[0], row[1], MappingProxyType(json.loads(row[2])))

    def append_event(self, run_id: str, event_type: str, payload: Mapping[str, object]) -> None:
        with self._connect() as con:
            if con.execute("SELECT 1 FROM agent_plans WHERE run_id=?", (run_id,)).fetchone() is None:
                raise KeyError(run_id)
            con.execute("INSERT INTO agent_plan_events (run_id, event_type, payload_json) VALUES (?, ?, ?)", (run_id, require_non_empty(event_type, "event_type"), json.dumps(payload, sort_keys=True, separators=(",", ":"))))

    def events(self, run_id: str) -> tuple[tuple[str, Mapping[str, object]], ...]:
        with self._connect() as con:
            rows = con.execute("SELECT event_type, payload_json FROM agent_plan_events WHERE run_id=? ORDER BY sequence", (run_id,)).fetchall()
        return tuple((row[0], MappingProxyType(json.loads(row[1]))) for row in rows)

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .audit import AgentAuditStore
from .domain import PolicyOutcome, ToolCallStatus
from .planning import SQLiteAgentPlanStore


@dataclass(frozen=True, slots=True)
class ReplayEntry:
    tool_name: str
    arguments: Mapping[str, object]
    status: ToolCallStatus
    policy_outcome: PolicyOutcome


@dataclass(frozen=True, slots=True)
class ReplayTrace:
    run_id: str
    plan_fingerprint: str
    entries: tuple[ReplayEntry, ...]
    selection: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class ReplayComparison:
    equivalent: bool
    differences: tuple[str, ...]


class AgentReplayEngine:
    """Dry replay reconstructs the audited action trace without re-running mutations."""

    def __init__(self, *, audit_store: AgentAuditStore, plan_store: SQLiteAgentPlanStore) -> None:
        self.audit_store = audit_store
        self.plan_store = plan_store

    def dry_replay(self, run_id: str) -> ReplayTrace:
        stored = self.plan_store.get_plan(run_id)
        entries: list[ReplayEntry] = []
        for request in self.audit_store.replay_requests(run_id):
            result = self.audit_store.get_tool_result(request.call_id)
            decision = self.audit_store.get_policy_decision(result.policy_decision_id)
            entries.append(ReplayEntry(request.tool_name, MappingProxyType(dict(request.arguments)), result.status, decision.outcome))
        selection = None
        for event_type, payload in self.plan_store.events(run_id):
            if event_type == "selection_sealed":
                selection = payload
        return ReplayTrace(run_id, stored.fingerprint, tuple(entries), selection)

    @staticmethod
    def compare(left: ReplayTrace, right: ReplayTrace) -> ReplayComparison:
        differences: list[str] = []
        if left.plan_fingerprint != right.plan_fingerprint:
            differences.append("plan_fingerprint")
        if len(left.entries) != len(right.entries):
            differences.append("entry_count")
        for index, (a, b) in enumerate(zip(left.entries, right.entries)):
            if (a.tool_name, dict(a.arguments), a.status, a.policy_outcome) != (b.tool_name, dict(b.arguments), b.status, b.policy_outcome):
                differences.append(f"entry[{index}]")
        left_selection = dict(left.selection) if left.selection is not None else None
        right_selection = dict(right.selection) if right.selection is not None else None
        if left_selection != right_selection:
            differences.append("selection")
        return ReplayComparison(not differences, tuple(differences))

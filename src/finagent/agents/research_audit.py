"""Required bridge from research execution facts to the existing Agent audit store."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from finagent.agents.audit import SQLiteAgentAuditStore
from finagent.agents.domain import (
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
from finagent.agents.r3_contracts import canonical_json, identity
from finagent.agents.r3_ledger import ResearchLedger, Reservation
from finagent.agents.r3_runtime import RequiredAuditFailure


def resource_snapshot(ledger: ResearchLedger) -> dict[str, Any]:
    snapshot, policy = cast(dict[str, Any], ledger.snapshot()), ledger.policy
    return {
        "status": snapshot["status"],
        "attempts": snapshot["attempt_count"],
        "evaluations": snapshot["evaluation_calls"],
        "tokens": snapshot["charged_tokens"],
        "cost_microusd": snapshot["charged_cost_microusd"],
        "remaining_tool_calls": max(0, policy.maximum_attempts - int(snapshot["attempt_count"])),
        "remaining_evaluations": max(
            0, policy.maximum_evaluations - int(snapshot["evaluation_calls"])
        ),
        "remaining_tokens": max(0, policy.maximum_tokens - int(snapshot["charged_tokens"])),
        "remaining_cost_microusd": max(
            0, policy.maximum_cost_microusd - int(snapshot["charged_cost_microusd"])
        ),
    }


class ResearchAuditBridge:
    def __init__(
        self,
        store: SQLiteAgentAuditStore,
        task: AgentTask,
        context: AgentRunContext,
        state: Callable[[ResearchLedger], dict[str, Any]],
    ) -> None:
        self.store, self.task, self.context, self.state = store, task, context, state

    def call_id(self, reservation: Reservation) -> str:
        return identity([self.context.run_id, reservation.request_id], "research-tool-call")

    def before_step(self, ledger: ResearchLedger) -> None:
        rows = ledger.journal()
        if ledger.snapshot()["status"] == "AUDIT_FAILED":
            raise RequiredAuditFailure("audit_reconciliation_required")
        if not self.store.has_run(ledger.run_id):
            if rows:
                raise RequiredAuditFailure("ledger_without_audit")
            self.store.start_run(self.task, self.context)
        stored = self.store.get_run_context(ledger.run_id)
        if stored != self.context:
            raise RequiredAuditFailure("audit_run_binding_mismatch")
        events = self.store.list_events(ledger.run_id)
        if sum(e.event_type.value == "run_started" for e in events) != 1:
            raise RequiredAuditFailure("audit_start_event_missing")
        requests = self.store.replay_requests(ledger.run_id)
        expected = {
            self.call_id(Reservation(r["request_id"], r["slot"], r["ordinal"], None)): r
            for r in rows
        }
        if {r.call_id for r in requests} != set(expected):
            raise RequiredAuditFailure("audit_trial_denominator_mismatch")
        for request in requests:
            row = expected[request.call_id]
            if row["result"] is None:
                raise RequiredAuditFailure("pending_execution_requires_reconciliation")
            result = self.store.get_tool_result(request.call_id)
            policy = self.store.get_policy_decision(request.call_id + "-policy")
            if canonical_json(result.output.get("research_result")) != canonical_json(
                row["result"]
            ):
                raise RequiredAuditFailure("audit_result_mismatch")
            if row["action"] is not None and (
                request.tool_name != row["action"]["tool"]
                or canonical_json(dict(request.arguments))
                != canonical_json(row["action"]["arguments"])
            ):
                raise RequiredAuditFailure("audit_action_mismatch")
            lifecycle = [e.event_type.value for e in events if e.call_id == request.call_id]
            if (
                lifecycle != ["tool_requested", "policy_decided", "tool_finished"]
                or policy.run_id != ledger.run_id
            ):
                raise RequiredAuditFailure("audit_tool_lifecycle_mismatch")
        terminal = ledger.snapshot()["status"] != "ACTIVE"
        if sum(e.event_type.value == "run_finished" for e in events) != int(terminal):
            raise RequiredAuditFailure("audit_terminal_mismatch")
        if rows:
            last = rows[-1]
            call_id = self.call_id(
                Reservation(last["request_id"], last["slot"], last["ordinal"], None)
            )
            projected = self.store.get_tool_result(call_id).output.get("research_state")
            if canonical_json(projected) != canonical_json(self.state(ledger)):
                raise RequiredAuditFailure("audit_explicit_state_mismatch")

    def requested(self, reservation: Reservation, action: dict[str, Any], now: float) -> None:
        try:
            self.store.record_tool_request(
                self.context.run_id,
                ToolCallRequest(
                    self.call_id(reservation),
                    action["tool"],
                    action["arguments"],
                    datetime.fromtimestamp(now, UTC),
                ),
            )
        except Exception:  # noqa: BLE001 -- required audit must stop on any storage failure.
            raise RequiredAuditFailure("audit_request_write_failed") from None

    def decided(self, reservation: Reservation, allowed: bool, reason: str, now: float) -> None:
        try:
            call = self.call_id(reservation)
            request = next(
                r for r in self.store.replay_requests(self.context.run_id) if r.call_id == call
            )
            self.store.record_policy_decision(
                PolicyDecision(
                    call + "-policy",
                    self.context.run_id,
                    call,
                    request.tool_name,
                    PolicyOutcome.ALLOW if allowed else PolicyOutcome.DENY,
                    reason,
                    datetime.fromtimestamp(now, UTC),
                    "r4-development-capabilities",
                    "1",
                )
            )
        except Exception:  # noqa: BLE001 -- required audit must stop on any storage failure.
            raise RequiredAuditFailure("audit_policy_write_failed") from None

    def finished(
        self, reservation: Reservation, result: dict[str, Any], ledger: ResearchLedger, now: float
    ) -> None:
        call = self.call_id(reservation)
        requests = self.store.replay_requests(ledger.run_id)
        request = next((r for r in requests if r.call_id == call), None)
        if request is None:
            self.requested(reservation, {"tool": "runtime_admission", "arguments": {}}, now)
            request = next(
                r for r in self.store.replay_requests(ledger.run_id) if r.call_id == call
            )
        try:
            policy = self.store.get_policy_decision(call + "-policy")
        except KeyError:
            self.decided(reservation, False, str(result.get("code", result["outcome"])), now)
            policy = self.store.get_policy_decision(call + "-policy")
        failed = result["outcome"] in {"TOOL_FAILED", "EVALUATOR_TIMEOUT", "AUDIT_FAILED"}
        status = (
            ToolCallStatus.DENIED
            if policy.outcome is PolicyOutcome.DENY
            else ToolCallStatus.FAILED
            if failed
            else ToolCallStatus.SUCCEEDED
        )
        state = self.state(ledger)
        state["resources"] = resource_snapshot(ledger)
        self.store.record_tool_result(
            ToolCallResult(
                call,
                ledger.run_id,
                request.tool_name,
                status,
                datetime.fromtimestamp(now, UTC),
                policy.decision_id,
                {"research_result": result, "research_state": state},
                ""
                if status is ToolCallStatus.SUCCEEDED
                else str(result.get("code", result["outcome"])),
            )
        )
        if ledger.snapshot()["status"] != "ACTIVE":
            terminal = str(ledger.snapshot()["status"])
            success = terminal in {"DEVELOPMENT_CANDIDATE_PROPOSED", "NO_CANDIDATE_RECOMMENDED"}
            self.store.finish_run(
                AgentDecision(
                    ledger.run_id,
                    AgentDecisionStatus.COMPLETED if success else AgentDecisionStatus.BLOCKED,
                    str(result.get("decision", terminal)),
                    datetime.fromtimestamp(now, UTC),
                    tuple(r.call_id for r in self.store.replay_requests(ledger.run_id)),
                    {
                        "terminal": terminal,
                        "development_only": "true",
                        "alpha_authority": "false",
                        "paper_authority": "false",
                        "live_authority": "false",
                    },
                )
            )

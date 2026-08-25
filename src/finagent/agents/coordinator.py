from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable, Protocol, Sequence

from .audit import AgentAuditStore
from .domain import AgentDecision, AgentDecisionStatus, AgentRunContext, AgentTask
from .planning import ResearchPlan, SQLiteAgentPlanStore
from .runtime import AgentRuntime


class ProgramGuard(Protocol):
    def authorize_plan(self, plan: ResearchPlan, *, task_id: str): ...


class AgentRunCoordinator:
    """Own start/finish/failure semantics for any AgentRuntime implementation.

    When ``program_guard`` is configured, cross-family search/alpha budget is reserved
    before any research tool call.  A failed run still consumes its reservation,
    because attempted hypotheses must remain part of the autonomous research record.
    """

    def __init__(
        self,
        *,
        audit_store: AgentAuditStore,
        plan_store: SQLiteAgentPlanStore,
        clock: Callable[[], datetime] | None = None,
        run_id_factory: Callable[[], str] | None = None,
        program_guard: ProgramGuard | None = None,
    ) -> None:
        self.audit_store = audit_store
        self.plan_store = plan_store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.run_id_factory = run_id_factory or (lambda: f"agent-run-{uuid.uuid4().hex}")
        self.program_guard = program_guard

    def run(
        self,
        *,
        runtime: AgentRuntime,
        task: AgentTask,
        tools,
        actor: str,
        plan: ResearchPlan,
        tool_allowlist: Sequence[str] = (),
    ) -> AgentDecision:
        run_id = self.run_id_factory()
        fingerprint = plan.fingerprint(task.task_id)
        metadata = {
            "plan_id": plan.plan_id,
            "planner_version": plan.planner_version,
            "plan_fingerprint": fingerprint,
        }
        if plan.program_id:
            metadata["program_id"] = plan.program_id

        context = AgentRunContext(
            run_id=run_id,
            task_id=task.task_id,
            actor=actor,
            started_at=self.clock(),
            max_tool_calls=plan.budget.max_tool_calls,
            tool_allowlist=tuple(tool_allowlist),
            metadata=metadata,
        )

        try:
            if self.program_guard is not None:
                self.program_guard.authorize_plan(plan, task_id=task.task_id)
            self.audit_store.start_run(task, context)
            self.plan_store.record_plan(run_id, task.task_id, plan)
            runtime_plan = getattr(runtime, "plan", None)
            if runtime_plan is not None and runtime_plan.fingerprint(task.task_id) != fingerprint:
                raise ValueError("runtime plan does not match coordinator plan")
            decision = runtime.run(task, tools, context)
            if decision.run_id != run_id:
                raise ValueError("AgentRuntime returned a decision for the wrong run_id")
        except Exception as exc:
            # The program guard can fail before audit registration.  In that case there
            # are no tool requests to replay and no audit run to finish.
            try:
                call_ids = tuple(
                    request.call_id for request in self.audit_store.replay_requests(run_id)
                )
            except Exception:
                call_ids = ()
            decision = AgentDecision(
                run_id,
                AgentDecisionStatus.FAILED,
                f"agent runtime failed: {type(exc).__name__}: {exc}",
                self.clock(),
                call_ids,
                {
                    "plan_id": plan.plan_id,
                    "plan_fingerprint": fingerprint,
                    "exception_type": type(exc).__name__,
                },
            )
            try:
                self.audit_store.finish_run(decision)
            except Exception:
                pass
            return decision

        self.audit_store.finish_run(decision)
        return decision

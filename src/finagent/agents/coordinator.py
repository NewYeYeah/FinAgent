from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable, Sequence

from .audit import AgentAuditStore
from .domain import AgentDecision, AgentDecisionStatus, AgentRunContext, AgentTask
from .planning import ResearchPlan, SQLiteAgentPlanStore
from .runtime import AgentRuntime


class AgentRunCoordinator:
    """Own start/finish/failure semantics for any AgentRuntime implementation."""

    def __init__(self, *, audit_store: AgentAuditStore, plan_store: SQLiteAgentPlanStore, clock: Callable[[], datetime] | None = None, run_id_factory: Callable[[], str] | None = None) -> None:
        self.audit_store = audit_store
        self.plan_store = plan_store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.run_id_factory = run_id_factory or (lambda: f"agent-run-{uuid.uuid4().hex}")

    def run(self, *, runtime: AgentRuntime, task: AgentTask, tools, actor: str, plan: ResearchPlan, tool_allowlist: Sequence[str] = ()) -> AgentDecision:
        run_id = self.run_id_factory()
        fingerprint = plan.fingerprint(task.task_id)
        context = AgentRunContext(
            run_id=run_id,
            task_id=task.task_id,
            actor=actor,
            started_at=self.clock(),
            max_tool_calls=plan.budget.max_tool_calls,
            tool_allowlist=tuple(tool_allowlist),
            metadata={"plan_id": plan.plan_id, "planner_version": plan.planner_version, "plan_fingerprint": fingerprint},
        )
        self.audit_store.start_run(task, context)
        self.plan_store.record_plan(run_id, task.task_id, plan)
        try:
            runtime_plan = getattr(runtime, "plan", None)
            if runtime_plan is not None and runtime_plan.fingerprint(task.task_id) != fingerprint:
                raise ValueError("runtime plan does not match coordinator plan")
            decision = runtime.run(task, tools, context)
            if decision.run_id != run_id:
                raise ValueError("AgentRuntime returned a decision for the wrong run_id")
        except Exception as exc:
            call_ids = tuple(request.call_id for request in self.audit_store.replay_requests(run_id))
            decision = AgentDecision(
                run_id,
                AgentDecisionStatus.FAILED,
                f"agent runtime failed: {type(exc).__name__}: {exc}",
                self.clock(),
                call_ids,
                {"plan_id": plan.plan_id, "plan_fingerprint": fingerprint, "exception_type": type(exc).__name__},
            )
        self.audit_store.finish_run(decision)
        return decision

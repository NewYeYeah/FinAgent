from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping

from finagent.domain.metrics import MetricObjective

from .domain import (
    AgentDecision,
    AgentDecisionStatus,
    AgentRunContext,
    AgentTask,
    ToolCallRequest,
    ToolCallResult,
    ToolCallStatus,
)
from .planning import ResearchPlan, SQLiteAgentPlanStore
from .templates import ExperimentTemplateRegistry
from .tools.base import ToolRegistry


@dataclass(frozen=True, slots=True)
class WinnerSelection:
    experiment_id: str
    primary_value: float
    tie_break_value: float | None


class ScriptedResearchAgent:
    """Deterministic research runtime using only the governed ToolRegistry surface."""

    def __init__(
        self,
        *,
        plan: ResearchPlan,
        templates: ExperimentTemplateRegistry,
        plan_store: SQLiteAgentPlanStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.plan = plan
        self.templates = templates
        self.plan_store = plan_store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self, task: AgentTask, tools: ToolRegistry, context: AgentRunContext) -> AgentDecision:
        if task.task_id != context.task_id:
            raise ValueError("task.task_id must match context.task_id")
        fingerprint = self.plan.fingerprint(task.task_id)
        if context.metadata.get("plan_fingerprint") != fingerprint:
            raise ValueError("AgentRunContext plan_fingerprint does not match scripted plan")
        if context.max_tool_calls != self.plan.budget.max_tool_calls:
            raise ValueError("AgentRunContext max_tool_calls must equal plan research budget")
        if self.plan_store.get_plan(context.run_id).fingerprint != fingerprint:
            raise ValueError("stored ResearchPlan fingerprint does not match runtime plan")

        call_ids: list[str] = []
        call_no = 0
        failed_experiments = 0

        def invoke(tool_name: str, arguments: Mapping[str, object]) -> ToolCallResult:
            nonlocal call_no
            call_no += 1
            call_id = f"{context.run_id}-call-{call_no:03d}"
            result = tools.invoke(
                ToolCallRequest(call_id, tool_name, arguments, self.clock()),
                context,
            )
            call_ids.append(call_id)
            return result

        def terminal(result: ToolCallResult, action: str) -> AgentDecision | None:
            if result.status is ToolCallStatus.SUCCEEDED:
                return None
            status = (
                AgentDecisionStatus.BLOCKED
                if result.status in {ToolCallStatus.DENIED, ToolCallStatus.REQUIRES_APPROVAL}
                else AgentDecisionStatus.FAILED
            )
            return AgentDecision(
                context.run_id,
                status,
                f"{action} did not complete: {result.error}",
                self.clock(),
                tuple(call_ids),
                {
                    "plan_fingerprint": fingerprint,
                    "family_id": self.plan.family_id,
                    "waiting_for_approval": str(
                        result.status is ToolCallStatus.REQUIRES_APPROVAL
                    ).lower(),
                },
            )

        state = invoke("list_experiment_families", {})
        if (decision := terminal(state, "inspect research state")) is not None:
            return decision
        if any(
            isinstance(item, Mapping) and item.get("family_id") == self.plan.family_id
            for item in state.output.get("families", ())
        ):
            return AgentDecision(
                context.run_id,
                AgentDecisionStatus.BLOCKED,
                f"experiment family {self.plan.family_id!r} already exists",
                self.clock(),
                tuple(call_ids),
                {"plan_fingerprint": fingerprint},
            )
        if not self.plan.budget.allow_new_family:
            return AgentDecision(
                context.run_id,
                AgentDecisionStatus.BLOCKED,
                "research budget forbids creating a new family",
                self.clock(),
                tuple(call_ids),
                {"plan_fingerprint": fingerprint},
            )

        created = invoke(
            "create_experiment_family",
            {
                "family_id": self.plan.family_id,
                "research_question": self.plan.research_question,
                "primary_metric": self.plan.primary_metric,
                "alpha": self.plan.alpha,
                "correction_method": self.plan.correction_method,
                "metadata": {
                    "plan_id": self.plan.plan_id,
                    "planner_version": self.plan.planner_version,
                    "program_id": self.plan.program_id,
                    "primary_metric_objective": self.plan.primary_metric_objective.value,
                },
            },
        )
        if (decision := terminal(created, "create experiment family")) is not None:
            return decision

        template = self.templates.get(self.plan.template_id)
        for variant in self.plan.variants:
            result = invoke(
                "register_experiment",
                template.materialize(family_id=self.plan.family_id, variant=variant),
            )
            if (decision := terminal(result, f"register {variant.experiment_id}")) is not None:
                return decision

        for variant in self.plan.variants:
            result = invoke("run_experiment", {"experiment_id": variant.experiment_id})
            if result.status is ToolCallStatus.FAILED:
                failed_experiments += 1
                if failed_experiments > self.plan.budget.max_failed_experiments:
                    return AgentDecision(
                        context.run_id,
                        AgentDecisionStatus.FAILED,
                        f"failed experiment budget exceeded after {variant.experiment_id}: "
                        f"{result.error}",
                        self.clock(),
                        tuple(call_ids),
                        {
                            "plan_fingerprint": fingerprint,
                            "family_id": self.plan.family_id,
                            "failed_experiments": str(failed_experiments),
                        },
                    )
                continue
            if (decision := terminal(result, f"run {variant.experiment_id}")) is not None:
                return decision

        experiment_ids = [variant.experiment_id for variant in self.plan.variants]
        primary = invoke(
            "compare_experiment_results",
            {"experiment_ids": experiment_ids, "metric": self.plan.primary_metric},
        )
        if (decision := terminal(primary, "compare primary metric")) is not None:
            return decision
        tie = None
        if self.plan.tie_break_metric:
            tie = invoke(
                "compare_experiment_results",
                {"experiment_ids": experiment_ids, "metric": self.plan.tie_break_metric},
            )
            if (decision := terminal(tie, "compare tie-break metric")) is not None:
                return decision

        selection = self._select_winner(
            primary.output,
            tie.output if tie is not None else None,
            primary_objective=self.plan.primary_metric_objective,
            tie_break_objective=self.plan.tie_break_metric_objective,
        )
        self.plan_store.append_event(
            context.run_id,
            "selection_sealed",
            {
                "experiment_id": selection.experiment_id,
                "primary_metric": self.plan.primary_metric,
                "primary_metric_objective": self.plan.primary_metric_objective.value,
                "primary_value": selection.primary_value,
                "tie_break_metric": self.plan.tie_break_metric,
                "tie_break_metric_objective": self.plan.tie_break_metric_objective.value,
                "tie_break_value": selection.tie_break_value,
            },
        )

        frozen = invoke("freeze_experiment_family", {"family_id": self.plan.family_id})
        if (decision := terminal(frozen, "freeze experiment family")) is not None:
            return decision
        validation = invoke(
            "validate_experiment_family",
            {
                "family_id": self.plan.family_id,
                "selected_experiment_id": selection.experiment_id,
            },
        )
        if (decision := terminal(validation, "validate experiment family")) is not None:
            return decision
        validation_passed = bool(validation.output.get("passed", False))
        metadata = {
            "plan_fingerprint": fingerprint,
            "family_id": self.plan.family_id,
            "selected_experiment_id": selection.experiment_id,
            "validation_passed": str(validation_passed).lower(),
            "failed_experiments": str(failed_experiments),
        }

        if (
            validation_passed
            and self.plan.promotion_intent is not None
            and self.plan.budget.allow_promotion_request
        ):
            intent = self.plan.promotion_intent
            promotion = invoke(
                "request_model_promotion",
                {"model_id": intent.model_id, "to_stage": intent.to_stage, "reason": intent.reason},
            )
            if promotion.status is ToolCallStatus.REQUIRES_APPROVAL:
                metadata["waiting_for_approval"] = "true"
                return AgentDecision(
                    context.run_id,
                    AgentDecisionStatus.BLOCKED,
                    "research completed; promotion request awaits human approval",
                    self.clock(),
                    tuple(call_ids),
                    metadata,
                )
            if (decision := terminal(promotion, "request model promotion")) is not None:
                return decision

        summary = (
            "scripted research completed and family validation passed"
            if validation_passed
            else "scripted research completed but family validation did not pass"
        )
        return AgentDecision(
            context.run_id,
            AgentDecisionStatus.COMPLETED,
            summary,
            self.clock(),
            tuple(call_ids),
            metadata,
        )

    @staticmethod
    def _select_winner(
        primary_output: Mapping[str, object],
        tie_break_output: Mapping[str, object] | None,
        *,
        primary_objective: MetricObjective = MetricObjective.MAXIMIZE,
        tie_break_objective: MetricObjective = MetricObjective.MINIMIZE,
    ) -> WinnerSelection:
        raw = primary_output.get("comparisons")
        if not isinstance(raw, (list, tuple)):
            raise ValueError("invalid primary comparison payload")
        primary: dict[str, float] = {}
        for item in raw:
            if (
                isinstance(item, Mapping)
                and item.get("value") is not None
                and item.get("passed") is not False
            ):
                primary[str(item["experiment_id"])] = float(item["value"])
        if not primary:
            raise ValueError("no successful experiment has a comparable primary metric")

        tie: dict[str, float] = {}
        if tie_break_output is not None:
            raw_tie = tie_break_output.get("comparisons")
            if not isinstance(raw_tie, (list, tuple)):
                raise ValueError("invalid tie-break comparison payload")
            for item in raw_tie:
                if isinstance(item, Mapping) and item.get("value") is not None:
                    tie[str(item["experiment_id"])] = float(item["value"])

        def objective_key(value: float, objective: MetricObjective) -> float:
            return -value if objective is MetricObjective.MAXIMIZE else value

        def key(experiment_id: str) -> tuple[float, float, str]:
            primary_key = objective_key(primary[experiment_id], primary_objective)
            if experiment_id in tie:
                tie_key = objective_key(tie[experiment_id], tie_break_objective)
            else:
                tie_key = float("inf")
            return primary_key, tie_key, experiment_id

        winner = min(primary, key=key)
        return WinnerSelection(winner, primary[winner], tie.get(winner))

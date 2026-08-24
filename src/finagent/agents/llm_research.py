from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence

from .coordinator import AgentRunCoordinator
from .domain import AgentDecision, AgentTask
from .llm_planner import LLMPlanningResult, LLMResearchPlanner
from .planning import SQLiteAgentPlanStore
from .scripted import ScriptedResearchAgent
from .templates import ExperimentTemplateRegistry


@dataclass(frozen=True, slots=True)
class LLMResearchOutcome:
    planning: LLMPlanningResult
    decision: AgentDecision


class LLMResearchAgent:
    """Phase 3C facade: LLM plans, deterministic runtime executes governed tools."""

    def __init__(
        self,
        *,
        planner: LLMResearchPlanner,
        templates: ExperimentTemplateRegistry,
        coordinator: AgentRunCoordinator,
        plan_store: SQLiteAgentPlanStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.planner = planner
        self.templates = templates
        self.coordinator = coordinator
        self.plan_store = plan_store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        *,
        task: AgentTask,
        tools,
        actor: str = "llm-research-agent",
        tool_allowlist: Sequence[str] = (),
    ) -> LLMResearchOutcome:
        planning = self.planner.plan(task)
        runtime = ScriptedResearchAgent(
            plan=planning.plan,
            templates=self.templates,
            plan_store=self.plan_store,
            clock=self.clock,
        )
        decision = self.coordinator.run(
            runtime=runtime,
            task=task,
            tools=tools,
            actor=actor,
            plan=planning.plan,
            tool_allowlist=tool_allowlist,
        )
        return LLMResearchOutcome(planning, decision)

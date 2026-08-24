from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, TYPE_CHECKING

from finagent.domain.model_registry import ModelStage

from .domain import (
    AgentAction,
    AgentRunContext,
    PolicyDecision,
    PolicyOutcome,
    ToolCallRequest,
)

if TYPE_CHECKING:
    from .tools.base import ToolSpec


class AgentPolicyEngine(Protocol):
    def evaluate(
        self,
        request: ToolCallRequest,
        spec: "ToolSpec",
        context: AgentRunContext,
        *,
        decision_id: str,
        decided_at: datetime,
    ) -> PolicyDecision:
        ...


@dataclass(frozen=True, slots=True)
class DefaultResearchAgentPolicy:
    """Deterministic Phase 3A policy-as-code.

    The policy controls the finite Agent action surface.  It does not replace domain
    invariants: OPEN/FROZEN family rules, experiment lifecycle and model-stage legality
    remain enforced by their existing deterministic services.
    """

    name: str = "default-research-agent-policy"
    version: str = "1"
    human_approval_stages: frozenset[ModelStage] = field(
        default_factory=lambda: frozenset({ModelStage.SHADOW, ModelStage.LIVE})
    )
    requestable_model_stages: frozenset[ModelStage] = field(
        default_factory=lambda: frozenset(
            {ModelStage.VALIDATED, ModelStage.PAPER, ModelStage.SHADOW, ModelStage.LIVE}
        )
    )

    def evaluate(
        self,
        request: ToolCallRequest,
        spec: "ToolSpec",
        context: AgentRunContext,
        *,
        decision_id: str,
        decided_at: datetime,
    ) -> PolicyDecision:
        if context.tool_allowlist and spec.name not in context.tool_allowlist:
            return self._decision(
                request,
                context,
                decision_id,
                decided_at,
                PolicyOutcome.DENY,
                "tool is not present in this run's allowlist",
            )

        if spec.action is AgentAction.REQUEST_MODEL_PROMOTION:
            raw_stage = request.arguments.get("to_stage")
            try:
                to_stage = ModelStage(str(raw_stage))
            except (TypeError, ValueError):
                return self._decision(
                    request,
                    context,
                    decision_id,
                    decided_at,
                    PolicyOutcome.DENY,
                    "to_stage must be a recognized model stage",
                )
            if to_stage not in self.requestable_model_stages:
                return self._decision(
                    request,
                    context,
                    decision_id,
                    decided_at,
                    PolicyOutcome.DENY,
                    f"Agent cannot request promotion to {to_stage.value}",
                )
            if to_stage in self.human_approval_stages:
                return self._decision(
                    request,
                    context,
                    decision_id,
                    decided_at,
                    PolicyOutcome.REQUIRE_HUMAN,
                    f"promotion request to {to_stage.value} requires human approval",
                )

        return self._decision(
            request,
            context,
            decision_id,
            decided_at,
            PolicyOutcome.ALLOW,
            "action is within the Phase 3A research policy surface",
        )

    def _decision(
        self,
        request: ToolCallRequest,
        context: AgentRunContext,
        decision_id: str,
        decided_at: datetime,
        outcome: PolicyOutcome,
        reason: str,
    ) -> PolicyDecision:
        return PolicyDecision(
            decision_id=decision_id,
            run_id=context.run_id,
            call_id=request.call_id,
            tool_name=request.tool_name,
            outcome=outcome,
            reason=reason,
            decided_at=decided_at,
            policy_name=self.name,
            policy_version=self.version,
        )

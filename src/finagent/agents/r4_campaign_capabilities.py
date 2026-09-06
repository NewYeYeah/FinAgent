"""Frozen arm restrictions over R4 tools; all counters come from ResearchLedger."""

from __future__ import annotations

from typing import Any, cast

from finagent.agents.r3_contracts import ContractError
from finagent.agents.r3_ledger import ResearchLedger, Reservation
from finagent.agents.r3_runtime import PreparedResearchAction
from finagent.agents.r4_controller import R4ResearchCapabilities
from finagent.application.research_controller_host import R4ResearchHost


class CampaignCapabilities(R4ResearchCapabilities):
    halt_on_tool_failure = True

    def __init__(self, host: R4ResearchHost, objective: str, arm: dict[str, Any]) -> None:
        super().__init__(host, objective)
        self.arm = arm

    @property
    def binding(self) -> dict[str, object]:
        return {**super().binding, "frozen_campaign_arm": self.arm}

    def manifest(self) -> dict[str, Any]:
        manifest = super().manifest()
        manifest["tools"] = {
            k: v
            for k, v in cast(dict[str, Any], manifest["tools"]).items()
            if k in self.arm["tools"]
        }
        manifest["campaign_limits"] = self.arm["budgets"]
        manifest["repair_policy"] = "no repairs or replacement slots"
        return manifest

    def prepare(
        self, action: dict[str, Any], ledger: ResearchLedger, reservation: Reservation, now: float
    ) -> PreparedResearchAction:
        tool = action["tool"]
        if tool not in self.arm["tools"]:
            raise ContractError("campaign_arm_tool_forbidden")
        if "repairs_request_id" in action["arguments"]:
            raise ContractError("campaign_repairs_forbidden")
        previous = [r for r in ledger.journal() if r["request_id"] != reservation.request_id]
        untyped = sum(r["state"] == "REJECTED" and r["action"] is None for r in previous)
        limits = {
            "propose_factor": "factor_proposals",
            "validate_factor": "factor_proposals",
            "propose_factor_set": "factor_set_proposals",
        }
        if tool in limits:
            group = (
                {"propose_factor", "validate_factor"} if tool != "propose_factor_set" else {tool}
            )
            count = untyped + sum((r["action"] or {}).get("tool") in group for r in previous)
            if count >= self.arm["budgets"][limits[tool]]:
                raise ContractError("campaign_proposal_budget_denied")
        if (
            tool == "propose_factor_set"
            and self.arm["kind"] == "primary"
            and not set(action["arguments"]["factor_ids"]).issubset(self.arm["initial_factor_ids"])
        ):
            raise ContractError("campaign_fixed_pool_required")
        prepared = super().prepare(action, ledger, reservation, now)
        if prepared.evaluation_key is not None:
            field = (
                "portfolio_evaluations" if tool == "evaluate_portfolio" else "factor_evaluations"
            )
            count = sum(
                bool(r["evaluation_reserved"]) and (r["action"] or {}).get("tool") == tool
                for r in previous
            )
            if count >= self.arm["budgets"][field]:
                raise ContractError("campaign_evaluation_budget_denied")
        return prepared

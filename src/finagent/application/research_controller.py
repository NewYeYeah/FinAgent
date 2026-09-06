"""Start/resume a bounded research session through ResearchCapabilityRuntime."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finagent.agents.audit import SQLiteAgentAuditStore
from finagent.agents.domain import AgentRunContext, AgentTask
from finagent.agents.r3_contracts import ContractError, ResearchRuntimePolicy, identity
from finagent.agents.r3_runtime import ResearchCapabilityRuntime, ResearchProvider
from finagent.agents.r4_contracts import R4Tool
from finagent.agents.r4_controller import R4ResearchCapabilities
from finagent.agents.research_audit import ResearchAuditBridge
from finagent.application.control_services import ApplicationCommandExecution
from finagent.application.research_controller_host import R4ResearchAdmission, R4ResearchHost
from finagent.research.us_r3_economic_campaign import file_digest
from finagent.research.us_r3_usability import write_immutable_json


def controller_implementation() -> dict[str, str]:
    root = Path(__file__).parents[1]
    return {
        name: file_digest(root / name)
        for name in (
            "agents/r4_contracts.py",
            "agents/r4_controller.py",
            "agents/research_audit.py",
            "application/research_controller.py",
            "application/research_controller_host.py",
            "research/adaptive_factor_admission.py",
            "research/r4_feedback.py",
        )
    }


def open_research_session(
    admission: R4ResearchAdmission,
    output: Path,
    *,
    run_id: str,
    objective: str,
    provider: ResearchProvider,
    provider_id: str,
    model_id: str,
    audit: SQLiteAgentAuditStore,
    policy: ResearchRuntimePolicy | None = None,
    clock: Callable[[], float] = time.time,
    campaign_arm: dict[str, Any] | None = None,
) -> ResearchCapabilityRuntime:
    if not objective.strip() or len(objective) > 1000:
        raise ContractError("invalid_research_objective")
    policy = policy or ResearchRuntimePolicy(
        maximum_attempts=48,
        maximum_attempts_per_slot=48,
        maximum_tokens=262144,
        tokens_per_call=32768,
        maximum_cost_microusd=1000000,
        maximum_evaluations=4,
        call_timeout_seconds=120,
    )
    request_path = output / "request.json"
    started_at = (
        json.loads(request_path.read_text())["started_at"]
        if request_path.exists()
        else datetime.fromtimestamp(clock(), UTC).isoformat()
    )
    request = {
        "run_id": run_id,
        "objective": objective,
        "provider_id": provider_id,
        "model_id": model_id,
        "policy": policy.to_dict(),
        "host": admission.manifest(),
        "started_at": started_at,
        "implementation": controller_implementation(),
        "audit_required": True,
        "audit_path": str(audit.path.resolve()),
        "evidence_scope": "exposed_development_only",
        **({"campaign_arm": campaign_arm} if campaign_arm is not None else {}),
    }
    write_immutable_json(request_path, request)
    host = R4ResearchHost(admission, output, run_id)
    capabilities = R4ResearchCapabilities(host, objective)
    if campaign_arm is not None:
        from finagent.agents.r4_campaign_capabilities import CampaignCapabilities

        capabilities = CampaignCapabilities(host, objective, campaign_arm)
    stamp = datetime.fromisoformat(started_at)
    task = AgentTask("task-" + run_id, objective, stamp)
    context = AgentRunContext(
        run_id,
        task.task_id,
        "agent_controller",
        stamp,
        max_tool_calls=policy.maximum_attempts,
        tool_allowlist=tuple(tool.value for tool in R4Tool),
        metadata={
            "project_id": "r4-research",
            "thread_id": "thread-" + run_id,
            "trigger_type": "research_objective",
            "controller": "r4",
            "binding_id": identity(request, "r4-research-request"),
            "authority": "development_only; no_alpha_paper_live",
        },
    )
    observer = ResearchAuditBridge(audit, task, context, capabilities.context)
    return ResearchCapabilityRuntime(
        output / "research.sqlite",
        run_id=run_id,
        scope=admission.scope,
        provider=provider,
        provider_id=provider_id,
        model_id=model_id,
        policy=policy,
        capabilities=capabilities,
        observer=observer,
        clock=clock,
    )


def run_research_session(runtime: ResearchCapabilityRuntime) -> dict[str, Any]:
    """Application scheduling only; provider/timeout/budget/retry remain in runtime.step."""
    # A deterministic request sequence resumes committed work without reissuing
    # any call. PENDING/uncertain execution is reconciled by the existing runtime.
    for index in range(runtime.policy.maximum_attempts + 1):
        result = runtime.step(f"research-step-{index:04d}", 0)
        if runtime.ledger.snapshot()["status"] != "ACTIVE":
            committed = [r["result"] for r in runtime.ledger.journal() if r["result"] is not None]
            return {
                "terminal": runtime.ledger.snapshot()["status"],
                "result": committed[-1] if committed else result,
                "resources": runtime.ledger.snapshot(),
            }
    raise ContractError("research_session_did_not_terminate")


class ResearchSessionService:
    """Explicit host injection; no environment-key discovery or provider fallback."""

    def __init__(
        self,
        admission: R4ResearchAdmission,
        output: Path,
        audit: SQLiteAgentAuditStore,
        provider_factory: Callable[[], ResearchProvider],
        *,
        provider_id: str,
        model_id: str,
        policy: ResearchRuntimePolicy | None = None,
    ) -> None:
        self.admission, self.output, self.audit = admission, output, audit
        self.provider_factory, self.provider_id, self.model_id = (
            provider_factory,
            provider_id,
            model_id,
        )
        self.policy = policy

    def status(self) -> dict[str, Any]:
        return {
            "provider_available": True,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "scope_id": self.admission.scope.scope_id,
            "cancel_supported": False,
            "development_only": True,
            "alpha_authority": False,
            "paper_authority": False,
            "live_authority": False,
        }

    @property
    def binding_id(self) -> str:
        return identity(
            {
                "host": self.admission.manifest(),
                "provider": self.provider_id,
                "model": self.model_id,
                "policy": self.policy.to_dict() if self.policy else None,
                "implementation": controller_implementation(),
            },
            "r4-service",
        )

    def execute(self, run_id: str, objective: str) -> ApplicationCommandExecution:
        runtime = open_research_session(
            self.admission,
            self.output / run_id,
            run_id=run_id,
            objective=objective,
            provider=self.provider_factory(),
            provider_id=self.provider_id,
            model_id=self.model_id,
            audit=self.audit,
            policy=self.policy,
        )
        result = run_research_session(runtime)
        state = (
            "succeeded"
            if result["terminal"] in {"DEVELOPMENT_CANDIDATE_PROPOSED", "NO_CANDIDATE_RECOMMENDED"}
            else "failed"
        )
        return ApplicationCommandExecution(
            "agent.research.start",
            state,
            outputs={"run_id": run_id, "terminal": result["terminal"], **self.status()},
            message=str(result["terminal"]),
        )

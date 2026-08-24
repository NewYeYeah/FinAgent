from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol

from finagent.domain._validation import require_non_empty

from ..audit import AgentAuditStore
from ..domain import (
    AgentAction,
    AgentRunContext,
    PolicyDecision,
    PolicyOutcome,
    ToolCallRequest,
    ToolCallResult,
    ToolCallStatus,
    ToolMode,
)
from ..policy import AgentPolicyEngine


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    action: AgentAction
    mode: ToolMode
    required_arguments: frozenset[str] = field(default_factory=frozenset)
    optional_arguments: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        normalized_name = require_non_empty(self.name, "tool name")
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "description", require_non_empty(self.description, "description"))
        required = frozenset(require_non_empty(value, "argument name") for value in self.required_arguments)
        optional = frozenset(require_non_empty(value, "argument name") for value in self.optional_arguments)
        if required & optional:
            raise ValueError("required_arguments and optional_arguments must be disjoint")
        object.__setattr__(self, "required_arguments", required)
        object.__setattr__(self, "optional_arguments", optional)
        if normalized_name != self.action.value:
            raise ValueError("Phase 3A tool names must equal their finite AgentAction value")

    def validate_arguments(self, arguments: Mapping[str, object]) -> None:
        keys = set(arguments)
        missing = self.required_arguments - keys
        if missing:
            raise ValueError(f"missing required tool arguments: {sorted(missing)}")
        allowed = self.required_arguments | self.optional_arguments
        unexpected = keys - allowed
        if unexpected:
            raise ValueError(f"unexpected tool arguments: {sorted(unexpected)}")


class AgentTool(Protocol):
    @property
    def spec(self) -> ToolSpec: ...

    def invoke(
        self,
        arguments: Mapping[str, object],
        context: AgentRunContext,
    ) -> Mapping[str, object]: ...


@dataclass(slots=True)
class FunctionTool:
    spec: ToolSpec
    handler: Callable[[Mapping[str, object], AgentRunContext], Mapping[str, object]]

    def invoke(
        self,
        arguments: Mapping[str, object],
        context: AgentRunContext,
    ) -> Mapping[str, object]:
        output = self.handler(arguments, context)
        if not isinstance(output, Mapping):
            raise TypeError("tool handlers must return a mapping")
        return dict(output)


class ToolRegistry:
    """Finite, governed Agent tool registry.

    Runtime implementations only receive this registry.  Handlers are not exposed as a
    public mapping, so every invocation passes through schema validation, policy-as-code
    and durable audit logging.
    """

    def __init__(
        self,
        *,
        policy_engine: AgentPolicyEngine,
        audit_store: AgentAuditStore,
        clock: Callable[[], datetime] | None = None,
        decision_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.policy_engine = policy_engine
        self.audit_store = audit_store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.decision_id_factory = decision_id_factory or (
            lambda: f"policy-{uuid.uuid4().hex}"
        )
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        name = tool.spec.name
        if name in self._tools:
            raise ValueError(f"tool {name!r} is already registered")
        self._tools[name] = tool

    def register_many(self, tools) -> None:
        for tool in tools:
            self.register(tool)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._tools[name].spec for name in sorted(self._tools))

    def invoke(
        self,
        request: ToolCallRequest,
        context: AgentRunContext,
    ) -> ToolCallResult:
        if not self.audit_store.has_run(context.run_id):
            raise ValueError("agent run must be registered in the audit store before tool use")
        if context.task_id.strip() == "":  # defensive; domain already validates this
            raise ValueError("context.task_id cannot be empty")

        existing_calls = self.audit_store.tool_call_count(context.run_id)
        self.audit_store.record_tool_request(context.run_id, request)

        if existing_calls >= context.max_tool_calls:
            decision = self._synthetic_decision(
                request,
                context,
                outcome=PolicyOutcome.DENY,
                reason="agent tool-call budget has been exhausted",
                policy_name="tool-budget",
            )
            return self._finish_without_handler(
                request,
                context,
                decision,
                ToolCallStatus.DENIED,
            )

        tool = self._tools.get(request.tool_name)
        if tool is None:
            decision = self._synthetic_decision(
                request,
                context,
                outcome=PolicyOutcome.DENY,
                reason="tool is not registered",
                policy_name="tool-registry",
            )
            return self._finish_without_handler(
                request,
                context,
                decision,
                ToolCallStatus.DENIED,
            )

        try:
            tool.spec.validate_arguments(request.arguments)
        except Exception as exc:
            decision = self._synthetic_decision(
                request,
                context,
                outcome=PolicyOutcome.DENY,
                reason=f"tool argument schema rejected the call: {exc}",
                policy_name="tool-schema",
            )
            return self._finish_without_handler(
                request,
                context,
                decision,
                ToolCallStatus.DENIED,
            )

        decision = self.policy_engine.evaluate(
            request,
            tool.spec,
            context,
            decision_id=self.decision_id_factory(),
            decided_at=self.clock(),
        )
        self.audit_store.record_policy_decision(decision)

        if decision.outcome is PolicyOutcome.DENY:
            return self._record_result(
                ToolCallResult(
                    call_id=request.call_id,
                    run_id=context.run_id,
                    tool_name=request.tool_name,
                    status=ToolCallStatus.DENIED,
                    finished_at=self.clock(),
                    policy_decision_id=decision.decision_id,
                    error=decision.reason,
                )
            )
        if decision.outcome is PolicyOutcome.REQUIRE_HUMAN:
            return self._record_result(
                ToolCallResult(
                    call_id=request.call_id,
                    run_id=context.run_id,
                    tool_name=request.tool_name,
                    status=ToolCallStatus.REQUIRES_APPROVAL,
                    finished_at=self.clock(),
                    policy_decision_id=decision.decision_id,
                    error=decision.reason,
                )
            )

        try:
            output = tool.invoke(request.arguments, context)
            result = ToolCallResult(
                call_id=request.call_id,
                run_id=context.run_id,
                tool_name=request.tool_name,
                status=ToolCallStatus.SUCCEEDED,
                finished_at=self.clock(),
                policy_decision_id=decision.decision_id,
                output=output,
            )
        except Exception as exc:
            result = ToolCallResult(
                call_id=request.call_id,
                run_id=context.run_id,
                tool_name=request.tool_name,
                status=ToolCallStatus.FAILED,
                finished_at=self.clock(),
                policy_decision_id=decision.decision_id,
                error=f"{type(exc).__name__}: {exc}",
            )
        return self._record_result(result)

    def _synthetic_decision(
        self,
        request: ToolCallRequest,
        context: AgentRunContext,
        *,
        outcome: PolicyOutcome,
        reason: str,
        policy_name: str,
    ) -> PolicyDecision:
        decision = PolicyDecision(
            decision_id=self.decision_id_factory(),
            run_id=context.run_id,
            call_id=request.call_id,
            tool_name=request.tool_name,
            outcome=outcome,
            reason=reason,
            decided_at=self.clock(),
            policy_name=policy_name,
            policy_version="1",
        )
        self.audit_store.record_policy_decision(decision)
        return decision

    def _finish_without_handler(
        self,
        request: ToolCallRequest,
        context: AgentRunContext,
        decision: PolicyDecision,
        status: ToolCallStatus,
    ) -> ToolCallResult:
        return self._record_result(
            ToolCallResult(
                call_id=request.call_id,
                run_id=context.run_id,
                tool_name=request.tool_name,
                status=status,
                finished_at=self.clock(),
                policy_decision_id=decision.decision_id,
                error=decision.reason,
            )
        )

    def _record_result(self, result: ToolCallResult) -> ToolCallResult:
        self.audit_store.record_tool_result(result)
        return result

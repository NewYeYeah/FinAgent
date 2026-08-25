from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping

from finagent.domain._validation import freeze_mapping, require_aware_datetime, require_non_empty


class AgentAction(str, Enum):
    INSPECT_DATA_CONTRACT = "inspect_data_contract"
    LIST_EXPERIMENT_FAMILIES = "list_experiment_families"
    INSPECT_EXPERIMENT_FAMILY = "inspect_experiment_family"
    LIST_EXPERIMENTS = "list_experiments"
    INSPECT_EXPERIMENT = "inspect_experiment"
    COMPARE_EXPERIMENT_RESULTS = "compare_experiment_results"
    INSPECT_MODEL_REGISTRY = "inspect_model_registry"
    INSPECT_MODEL_HISTORY = "inspect_model_history"
    LIST_RESEARCH_HYPOTHESES = "list_research_hypotheses"
    INSPECT_RESEARCH_HYPOTHESIS = "inspect_research_hypothesis"
    FIND_SIMILAR_HYPOTHESES = "find_similar_hypotheses"
    INSPECT_RESEARCH_LINEAGE = "inspect_research_lineage"
    INSPECT_RESEARCH_FAILURES = "inspect_research_failures"
    RECOMMEND_RESEARCH_BUDGET = "recommend_research_budget"
    CREATE_EXPERIMENT_FAMILY = "create_experiment_family"
    REGISTER_EXPERIMENT = "register_experiment"
    RUN_EXPERIMENT = "run_experiment"
    FREEZE_EXPERIMENT_FAMILY = "freeze_experiment_family"
    VALIDATE_EXPERIMENT_FAMILY = "validate_experiment_family"
    REQUEST_MODEL_PROMOTION = "request_model_promotion"
    INSPECT_PORTFOLIO_HEALTH = "inspect_portfolio_health"
    INSPECT_PORTFOLIO_BENCHMARKS = "inspect_portfolio_benchmarks"
    INSPECT_STRESS_REPORT = "inspect_stress_report"
    INSPECT_REBALANCE_DECISION = "inspect_rebalance_decision"
    LIST_OPERATING_POLICIES = "list_operating_policies"
    REQUEST_OPERATING_POLICY = "request_operating_policy"
    REQUEST_REBALANCE = "request_rebalance"
    REQUEST_HUMAN_REVIEW = "request_human_review"


class ToolMode(str, Enum):
    READ = "read"
    WRITE = "write"
    REQUEST = "request"


class PolicyOutcome(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_HUMAN = "require_human"


class ToolCallStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    REQUIRES_APPROVAL = "requires_approval"


class AgentDecisionStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class AgentAuditEventType(str, Enum):
    RUN_STARTED = "run_started"
    TOOL_REQUESTED = "tool_requested"
    POLICY_DECIDED = "policy_decided"
    TOOL_FINISHED = "tool_finished"
    RUN_FINISHED = "run_finished"


@dataclass(frozen=True, slots=True)
class AgentTask:
    task_id: str
    objective: str
    created_at: datetime
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", require_non_empty(self.task_id, "task_id"))
        object.__setattr__(self, "objective", require_non_empty(self.objective, "objective"))
        object.__setattr__(self, "created_at", require_aware_datetime(self.created_at, "created_at"))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class AgentRunContext:
    run_id: str
    task_id: str
    actor: str
    started_at: datetime
    max_tool_calls: int = 50
    tool_allowlist: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", require_non_empty(self.run_id, "run_id"))
        object.__setattr__(self, "task_id", require_non_empty(self.task_id, "task_id"))
        object.__setattr__(self, "actor", require_non_empty(self.actor, "actor"))
        object.__setattr__(self, "started_at", require_aware_datetime(self.started_at, "started_at"))
        if isinstance(self.max_tool_calls, bool) or self.max_tool_calls < 1:
            raise ValueError("max_tool_calls must be an integer >= 1")
        normalized_allowlist = tuple(require_non_empty(name, "tool name") for name in self.tool_allowlist)
        if len(set(normalized_allowlist)) != len(normalized_allowlist):
            raise ValueError("tool_allowlist cannot contain duplicates")
        object.__setattr__(self, "tool_allowlist", normalized_allowlist)
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    call_id: str
    tool_name: str
    arguments: Mapping[str, object]
    requested_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "call_id", require_non_empty(self.call_id, "call_id"))
        object.__setattr__(self, "tool_name", require_non_empty(self.tool_name, "tool_name"))
        object.__setattr__(self, "arguments", freeze_mapping(self.arguments))
        object.__setattr__(
            self, "requested_at", require_aware_datetime(self.requested_at, "requested_at")
        )


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    decision_id: str
    run_id: str
    call_id: str
    tool_name: str
    outcome: PolicyOutcome
    reason: str
    decided_at: datetime
    policy_name: str
    policy_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "decision_id", require_non_empty(self.decision_id, "decision_id"))
        object.__setattr__(self, "run_id", require_non_empty(self.run_id, "run_id"))
        object.__setattr__(self, "call_id", require_non_empty(self.call_id, "call_id"))
        object.__setattr__(self, "tool_name", require_non_empty(self.tool_name, "tool_name"))
        object.__setattr__(self, "reason", require_non_empty(self.reason, "reason"))
        object.__setattr__(
            self, "decided_at", require_aware_datetime(self.decided_at, "decided_at")
        )
        object.__setattr__(self, "policy_name", require_non_empty(self.policy_name, "policy_name"))
        object.__setattr__(
            self, "policy_version", require_non_empty(self.policy_version, "policy_version")
        )


@dataclass(frozen=True, slots=True)
class ToolCallResult:
    call_id: str
    run_id: str
    tool_name: str
    status: ToolCallStatus
    finished_at: datetime
    policy_decision_id: str
    output: Mapping[str, object] = field(default_factory=dict)
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "call_id", require_non_empty(self.call_id, "call_id"))
        object.__setattr__(self, "run_id", require_non_empty(self.run_id, "run_id"))
        object.__setattr__(self, "tool_name", require_non_empty(self.tool_name, "tool_name"))
        object.__setattr__(
            self, "finished_at", require_aware_datetime(self.finished_at, "finished_at")
        )
        object.__setattr__(
            self,
            "policy_decision_id",
            require_non_empty(self.policy_decision_id, "policy_decision_id"),
        )
        object.__setattr__(self, "output", freeze_mapping(self.output))
        object.__setattr__(self, "error", self.error.strip())
        if self.status is ToolCallStatus.SUCCEEDED and self.error:
            raise ValueError("successful tool calls cannot carry an error")
        if self.status in {
            ToolCallStatus.FAILED,
            ToolCallStatus.DENIED,
            ToolCallStatus.REQUIRES_APPROVAL,
        } and not self.error:
            raise ValueError("non-successful tool calls require an error/reason")


@dataclass(frozen=True, slots=True)
class AgentDecision:
    run_id: str
    status: AgentDecisionStatus
    summary: str
    finished_at: datetime
    tool_call_ids: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", require_non_empty(self.run_id, "run_id"))
        object.__setattr__(self, "summary", require_non_empty(self.summary, "summary"))
        object.__setattr__(
            self, "finished_at", require_aware_datetime(self.finished_at, "finished_at")
        )
        normalized_ids = tuple(require_non_empty(value, "tool_call_id") for value in self.tool_call_ids)
        if len(set(normalized_ids)) != len(normalized_ids):
            raise ValueError("tool_call_ids cannot contain duplicates")
        object.__setattr__(self, "tool_call_ids", normalized_ids)
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class AgentAuditEvent:
    event_id: str
    run_id: str
    event_type: AgentAuditEventType
    occurred_at: datetime
    call_id: str = ""
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", require_non_empty(self.event_id, "event_id"))
        object.__setattr__(self, "run_id", require_non_empty(self.run_id, "run_id"))
        object.__setattr__(
            self, "occurred_at", require_aware_datetime(self.occurred_at, "occurred_at")
        )
        object.__setattr__(self, "call_id", self.call_id.strip())
        object.__setattr__(self, "payload", freeze_mapping(self.payload))

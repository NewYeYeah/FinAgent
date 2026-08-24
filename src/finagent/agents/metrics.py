from __future__ import annotations

from dataclasses import dataclass

from .domain import AgentDecisionStatus, ToolCallStatus
from .providers import LLMResponse
from .replay import ReplayTrace


@dataclass(frozen=True, slots=True)
class AgentEvaluationMetrics:
    completed: bool
    tool_calls: int
    tool_success_rate: float
    denied_calls: int
    failed_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int
    llm_latency_ms: float


def evaluate_agent_run(*, decision, trace: ReplayTrace, provider_response: LLMResponse) -> AgentEvaluationMetrics:
    total = len(trace.entries)
    succeeded = sum(entry.status is ToolCallStatus.SUCCEEDED for entry in trace.entries)
    denied = sum(entry.status is ToolCallStatus.DENIED for entry in trace.entries)
    failed = sum(entry.status is ToolCallStatus.FAILED for entry in trace.entries)
    usage = provider_response.usage
    return AgentEvaluationMetrics(
        completed=decision.status is AgentDecisionStatus.COMPLETED,
        tool_calls=total,
        tool_success_rate=(succeeded / total if total else 0.0),
        denied_calls=denied,
        failed_calls=failed,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        cached_input_tokens=usage.cached_input_tokens,
        llm_latency_ms=provider_response.latency_ms,
    )

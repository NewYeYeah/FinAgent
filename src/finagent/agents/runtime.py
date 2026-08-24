from __future__ import annotations

from typing import Protocol

from .domain import AgentDecision, AgentRunContext, AgentTask


class AgentRuntime(Protocol):
    """Provider/framework-independent Agent runtime contract.

    Phase 3A intentionally provides only the protocol.  Phase 3B will implement a
    deterministic scripted runtime against the same governed ToolRegistry surface,
    and Phase 3C may attach an LLM-backed implementation without changing Quant Core.
    """

    def run(
        self,
        task: AgentTask,
        tools,
        context: AgentRunContext,
    ) -> AgentDecision:
        ...

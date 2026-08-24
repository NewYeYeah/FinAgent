from datetime import datetime, timezone

import pytest

from finagent.agents.domain import (
    AgentAction,
    AgentRunContext,
    AgentTask,
    ToolCallRequest,
    ToolCallResult,
    ToolCallStatus,
)


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def test_agent_task_and_context_require_aware_time_and_positive_budget():
    with pytest.raises(ValueError):
        AgentTask("task", "objective", datetime(2026, 8, 24, 12, 0))
    with pytest.raises(ValueError):
        AgentRunContext("run", "task", "research-agent", NOW, max_tool_calls=0)


def test_agent_context_rejects_duplicate_allowlist_entries():
    with pytest.raises(ValueError):
        AgentRunContext(
            "run",
            "task",
            "research-agent",
            NOW,
            tool_allowlist=("inspect_data_contract", "inspect_data_contract"),
        )


def test_tool_call_request_defensively_freezes_arguments():
    arguments = {"family_id": "family-a"}
    request = ToolCallRequest("call-1", AgentAction.INSPECT_EXPERIMENT_FAMILY.value, arguments, NOW)
    arguments["family_id"] = "mutated"
    assert request.arguments["family_id"] == "family-a"
    with pytest.raises(TypeError):
        request.arguments["x"] = 1


def test_tool_call_result_requires_reason_for_non_success():
    with pytest.raises(ValueError):
        ToolCallResult(
            call_id="call-1",
            run_id="run-1",
            tool_name="unknown",
            status=ToolCallStatus.DENIED,
            finished_at=NOW,
            policy_decision_id="policy-1",
        )

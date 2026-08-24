from datetime import datetime, timezone

from finagent.agents import (
    AgentAction,
    AgentRunContext,
    AgentTask,
    DefaultResearchAgentPolicy,
    FunctionTool,
    PolicyOutcome,
    SQLiteAgentAuditStore,
    ToolCallRequest,
    ToolCallStatus,
    ToolMode,
    ToolRegistry,
    ToolSpec,
)


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def _counter(prefix):
    state = {"n": 0}

    def make():
        state["n"] += 1
        return f"{prefix}-{state['n']}"

    return make


def _runtime(tmp_path, *, max_tool_calls=10, allowlist=()):
    audit = SQLiteAgentAuditStore(tmp_path / "audit.db", event_id_factory=_counter("event"))
    task = AgentTask("task-1", "research safely", NOW)
    context = AgentRunContext(
        "agent-run-1",
        task.task_id,
        "research-agent",
        NOW,
        max_tool_calls=max_tool_calls,
        tool_allowlist=allowlist,
    )
    audit.start_run(task, context)
    registry = ToolRegistry(
        policy_engine=DefaultResearchAgentPolicy(),
        audit_store=audit,
        clock=lambda: NOW,
        decision_id_factory=_counter("policy"),
    )
    return registry, audit, context


def test_unregistered_tool_is_denied_and_audited(tmp_path):
    registry, audit, context = _runtime(tmp_path)
    request = ToolCallRequest("call-1", "set_portfolio_weights", {}, NOW)
    result = registry.invoke(request, context)
    assert result.status is ToolCallStatus.DENIED
    decision = audit.get_policy_decision(result.policy_decision_id)
    assert decision.outcome is PolicyOutcome.DENY
    assert decision.policy_name == "tool-registry"
    assert audit.replay_requests(context.run_id) == (request,)
    assert [event.event_type.value for event in audit.list_events(context.run_id)] == [
        "run_started",
        "tool_requested",
        "policy_decided",
        "tool_finished",
    ]


def test_allowlist_blocks_registered_tool(tmp_path):
    registry, audit, context = _runtime(tmp_path, allowlist=("list_experiments",))
    called = {"value": False}

    def handler(arguments, ctx):
        called["value"] = True
        return {"ok": True}

    registry.register(
        FunctionTool(
            ToolSpec(
                name=AgentAction.INSPECT_DATA_CONTRACT.value,
                description="read contract",
                action=AgentAction.INSPECT_DATA_CONTRACT,
                mode=ToolMode.READ,
            ),
            handler,
        )
    )
    result = registry.invoke(
        ToolCallRequest("call-1", AgentAction.INSPECT_DATA_CONTRACT.value, {}, NOW),
        context,
    )
    assert result.status is ToolCallStatus.DENIED
    assert called["value"] is False


def test_argument_schema_rejects_agent_threshold_mutation(tmp_path):
    registry, audit, context = _runtime(tmp_path)
    registry.register(
        FunctionTool(
            ToolSpec(
                name=AgentAction.VALIDATE_EXPERIMENT_FAMILY.value,
                description="fixed validation",
                action=AgentAction.VALIDATE_EXPERIMENT_FAMILY,
                mode=ToolMode.WRITE,
                required_arguments=frozenset({"family_id", "selected_experiment_id"}),
            ),
            lambda arguments, ctx: {"unexpected": True},
        )
    )
    result = registry.invoke(
        ToolCallRequest(
            "call-1",
            AgentAction.VALIDATE_EXPERIMENT_FAMILY.value,
            {
                "family_id": "family",
                "selected_experiment_id": "exp",
                "pbo_threshold": 0.99,
            },
            NOW,
        ),
        context,
    )
    assert result.status is ToolCallStatus.DENIED
    assert "unexpected tool arguments" in result.error


def test_tool_budget_denies_calls_after_limit(tmp_path):
    registry, audit, context = _runtime(tmp_path, max_tool_calls=1)
    registry.register(
        FunctionTool(
            ToolSpec(
                name=AgentAction.INSPECT_DATA_CONTRACT.value,
                description="read contract",
                action=AgentAction.INSPECT_DATA_CONTRACT,
                mode=ToolMode.READ,
            ),
            lambda arguments, ctx: {"ok": True},
        )
    )
    first = registry.invoke(
        ToolCallRequest("call-1", AgentAction.INSPECT_DATA_CONTRACT.value, {}, NOW), context
    )
    second = registry.invoke(
        ToolCallRequest("call-2", AgentAction.INSPECT_DATA_CONTRACT.value, {}, NOW), context
    )
    assert first.status is ToolCallStatus.SUCCEEDED
    assert second.status is ToolCallStatus.DENIED
    assert "budget" in second.error
    assert audit.tool_call_count(context.run_id) == 2


def test_registered_run_context_is_immutable_and_cannot_be_forged(tmp_path):
    registry, audit, context = _runtime(
        tmp_path,
        max_tool_calls=1,
        allowlist=(AgentAction.INSPECT_DATA_CONTRACT.value,),
    )
    registry.register(
        FunctionTool(
            ToolSpec(
                name=AgentAction.INSPECT_DATA_CONTRACT.value,
                description="read contract",
                action=AgentAction.INSPECT_DATA_CONTRACT,
                mode=ToolMode.READ,
            ),
            lambda arguments, ctx: {"ok": True},
        )
    )
    assert audit.get_run_context(context.run_id) == context

    forged = AgentRunContext(
        context.run_id,
        context.task_id,
        context.actor,
        context.started_at,
        max_tool_calls=999,
        tool_allowlist=(),
    )
    try:
        registry.invoke(
            ToolCallRequest("call-forged", AgentAction.INSPECT_DATA_CONTRACT.value, {}, NOW),
            forged,
        )
    except ValueError as exc:
        assert "immutable registered run context" in str(exc)
    else:  # pragma: no cover - safety regression guard
        raise AssertionError("forged AgentRunContext was unexpectedly accepted")

    assert audit.tool_call_count(context.run_id) == 0

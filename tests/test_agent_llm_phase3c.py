import json
from datetime import datetime, timezone

import pytest

from finagent.agents import (
    AgentDecisionStatus,
    AgentReplayEngine,
    AgentRunCoordinator,
    AgentTask,
    LLMPlanValidationError,
    LLMPlanningPolicy,
    LLMResearchAgent,
    LLMResearchPlanner,
    OpenAIResponsesProvider,
    SQLiteLLMCallStore,
    StaticLLMProvider,
    evaluate_agent_run,
)
from finagent.agents.providers import LLMRequest
from tests.test_agent_scripted_phase3b import _counter, _system

NOW = datetime(2026, 8, 25, 0, 0, tzinfo=timezone.utc)


def _output(**overrides):
    payload = {
        "family_id": "family-llm-ar",
        "research_question": "Which approved AR order is strongest?",
        "primary_metric": "validation_sharpe",
        "template_id": "ar-order",
        "tie_break_metric": "turnover",
        "variants": [
            {"variant_id": "ar1", "experiment_id": "exp-ar1", "hypothesis": "AR1", "parameters": [{"name": "order", "value": 1}, {"name": "score", "value": 0.8}, {"name": "turnover", "value": 0.30}]},
            {"variant_id": "ar2", "experiment_id": "exp-ar2", "hypothesis": "AR2", "parameters": [{"name": "order", "value": 2}, {"name": "score", "value": 1.1}, {"name": "turnover", "value": 0.25}]},
            {"variant_id": "ar3", "experiment_id": "exp-ar3", "hypothesis": "AR3", "parameters": [{"name": "order", "value": 3}, {"name": "score", "value": 1.1}, {"name": "turnover", "value": 0.15}]},
        ],
    }
    payload.update(overrides)
    return json.dumps(payload)


def _planner(tmp_path, output=None):
    _, _, _, _, templates = _system(tmp_path / "infra")
    store = SQLiteLLMCallStore(tmp_path / "llm.db")
    provider = StaticLLMProvider(output or _output())
    policy = LLMPlanningPolicy(model="test-model", max_variants=3, max_tool_calls=20)
    planner = LLMResearchPlanner(
        provider=provider,
        templates=templates,
        policy=policy,
        call_store=store,
        request_id_factory=_counter("llm-request"),
    )
    return planner, provider, store, templates


def test_llm_planner_emits_policy_bounded_research_plan(tmp_path):
    planner, provider, store, templates = _planner(tmp_path)
    task = AgentTask("task-llm", "compare approved AR orders", NOW)
    result = planner.plan(task)
    assert result.plan.family_id == "family-llm-ar"
    assert result.plan.primary_metric == "validation_sharpe"
    assert result.plan.tie_break_metric == "turnover"
    assert [v.experiment_id for v in result.plan.variants] == ["exp-ar1", "exp-ar2", "exp-ar3"]
    assert result.plan.budget.max_tool_calls == 20
    assert result.plan.budget.allow_promotion_request is False
    assert provider.requests[0].prompt_hash == result.prompt_hash
    record = store.get(result.provider_response.request_id)
    assert record.planning_valid is True
    assert record.prompt_hash == result.prompt_hash


def test_llm_cannot_inject_validation_policy_or_unapproved_tie_metric(tmp_path):
    payload = json.loads(_output())
    payload["pbo_threshold"] = 0.99
    planner, _, store, _ = _planner(tmp_path, json.dumps(payload))
    task = AgentTask("task-llm", "research", NOW)
    with pytest.raises(LLMPlanValidationError, match="unexpected planner fields"):
        planner.plan(task)
    record = store.get("llm-request-1")
    assert record.planning_valid is False

    payload = json.loads(_output())
    payload["tie_break_metric"] = "outer_test_sharpe"
    planner, _, _, _ = _planner(tmp_path / "tie", json.dumps(payload))
    with pytest.raises(LLMPlanValidationError, match="tie_break_metric"):
        planner.plan(task)


def test_llm_variant_parameters_must_exactly_match_template(tmp_path):
    payload = json.loads(_output())
    payload["variants"][0]["parameters"].append({"name": "unapproved", "value": 1})
    planner, _, _, _ = _planner(tmp_path, json.dumps(payload))
    with pytest.raises(LLMPlanValidationError, match="exactly match template"):
        planner.plan(AgentTask("task-llm", "research", NOW))


def test_phase3c_llm_planning_then_deterministic_execution(tmp_path):
    research, audit, plans, tools, templates = _system(tmp_path / "system")
    provider = StaticLLMProvider(_output())
    call_store = SQLiteLLMCallStore(tmp_path / "system" / "state.db")
    planner = LLMResearchPlanner(
        provider=provider,
        templates=templates,
        policy=LLMPlanningPolicy(model="test-model", max_variants=3, max_tool_calls=20),
        call_store=call_store,
        request_id_factory=_counter("llm-request"),
    )
    coordinator = AgentRunCoordinator(
        audit_store=audit,
        plan_store=plans,
        clock=lambda: NOW,
        run_id_factory=_counter("agent-run"),
    )
    agent = LLMResearchAgent(
        planner=planner,
        templates=templates,
        coordinator=coordinator,
        plan_store=plans,
        clock=lambda: NOW,
    )
    task = AgentTask("task-llm", "compare approved AR orders", NOW)
    outcome = agent.run(task=task, tools=tools)
    assert outcome.decision.status is AgentDecisionStatus.COMPLETED
    assert outcome.decision.metadata["selected_experiment_id"] == "exp-ar3"
    assert research.get_family("family-llm-ar").status.value == "frozen"

    trace = AgentReplayEngine(audit_store=audit, plan_store=plans).dry_replay(outcome.decision.run_id)
    metrics = evaluate_agent_run(
        decision=outcome.decision,
        trace=trace,
        provider_response=outcome.planning.provider_response,
    )
    assert metrics.completed
    assert metrics.tool_calls == 12
    assert metrics.denied_calls == 0
    assert metrics.failed_calls == 0


class _FakeUsageDetails:
    cached_tokens = 3


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5
    total_tokens = 15
    input_tokens_details = _FakeUsageDetails()


class _FakeResponse:
    id = "resp-test"
    model = "gpt-test"
    status = "completed"
    output_text = '{"ok":true}'
    usage = _FakeUsage()


class _FakeResponses:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return _FakeResponse()


class _FakeClient:
    def __init__(self):
        self.responses = _FakeResponses()


def test_openai_responses_adapter_uses_strict_json_schema_without_core_dependency():
    client = _FakeClient()
    provider = OpenAIResponsesProvider(client=client)
    request = LLMRequest(
        request_id="req-1",
        model="gpt-test",
        instructions="return structured data",
        input_text="x",
        schema_name="test_schema",
        response_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        max_output_tokens=100,
    )
    response = provider.complete(request)
    assert response.output_text == '{"ok":true}'
    assert response.usage.cached_input_tokens == 3
    fmt = client.responses.kwargs["text"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["strict"] is True
    assert client.responses.kwargs["store"] is False

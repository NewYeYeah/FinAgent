from __future__ import annotations

import json

import pytest

from finagent.agents.r3_contracts import ContractError
from finagent.agents.r3_runtime import ResearchCapabilityRuntime, ResearchReply
from finagent.research.us_r3_completion import baseline_action, run_completion
from finagent.research.us_r3_followup_review import audit_daily, evidence_plan, review_completion
from finagent.research.us_r3_workflow_pilot import freeze_workflow, run_workflow
from tests.test_us_r3_agent_runtime import FakeEvaluator, FakeProvider, _action, _proposal, _runtime
from tests.test_us_r3_completion import ScriptedProvider, completion_fixture


def test_workflow_refuses_premature_submit_and_changed_proposal(tmp_path):
    candidate = json.loads(_proposal(validate=True))
    provider = FakeProvider(_proposal(), json.dumps(candidate))
    runtime = _runtime(
        tmp_path / "run.sqlite",
        provider,
        evaluator=FakeEvaluator(),
        require_evaluated_submission=True,
    )
    assert runtime.step("early", 0)["code"] == "workflow_tool_out_of_order"
    validated = runtime.step("validate", 0)
    provider.responses.extend(
        [
            _action("evaluate_development", candidate_id=validated["candidate_id"]),
            _proposal(1),
            _proposal(),
        ]
    )
    assert runtime.step("evaluate", 0)["outcome"] == "DEVELOPMENT_EVALUATED"
    assert runtime.step("changed", 0)["code"] == "workflow_proposal_changed_after_evaluation"
    assert runtime.step("submit", 0)["outcome"] == "SUBMITTED"
    context = json.loads(provider.requests[-1].context_json)
    assert context["workflow"]["required_tool"] == "submit_factor"
    assert (
        context["workflow"]["development_evaluation"]["candidate_id"] == validated["candidate_id"]
    )
    assert runtime.ledger.snapshot()["evaluation_calls"] == 1


def test_workflow_recovers_from_ledger_and_keeps_slots_separate(tmp_path):
    path = tmp_path / "run.sqlite"
    first = _runtime(
        path,
        FakeProvider(_proposal(validate=True)),
        evaluator=FakeEvaluator(),
        require_evaluated_submission=True,
    )
    validated = first.step("validate", 0)
    provider = FakeProvider(
        _action("evaluate_development", candidate_id=validated["candidate_id"]),
        _proposal(validate=True),
    )
    second = _runtime(path, provider, evaluator=FakeEvaluator(), require_evaluated_submission=True)
    assert second.step("evaluate", 0)["outcome"] == "DEVELOPMENT_EVALUATED"
    assert second.step("other-slot", 1)["outcome"] == "VALIDATED"
    assert (
        json.loads(provider.requests[1].context_json)["workflow"]["required_tool"]
        == "validate_factor"
    )
    with pytest.raises(ContractError, match="run_binding_mismatch"):
        _runtime(path, provider, evaluator=FakeEvaluator())


def test_workflow_cannot_be_enabled_without_feedback_evaluator(tmp_path):
    with pytest.raises(ContractError, match="workflow_requires"):
        _runtime(tmp_path / "run.sqlite", FakeProvider(), require_evaluated_submission=True)


def test_workflow_rejects_wrong_candidate_and_resists_memory_eviction(tmp_path):
    provider = FakeProvider(_proposal(validate=True))
    runtime = _runtime(
        tmp_path / "run.sqlite",
        provider,
        evaluator=FakeEvaluator(),
        require_evaluated_submission=True,
    )
    validated = runtime.step("validate", 0)
    provider.responses.append(_action("evaluate_development", candidate_id="different"))
    assert runtime.step("wrong", 0)["code"] == "workflow_candidate_mismatch"
    for index in range(7):
        provider.responses.append(_proposal(1, validate=True))
        # Other slots evict the first slot from the six-item prompt memory.
        runtime.step(f"other-{index}", index + 1)
    assert not any(
        r.get("candidate_id") == validated["candidate_id"] for r in runtime.ledger.recall()
    )
    assert runtime._workflow(0)["candidate_id"] == validated["candidate_id"]
    provider.responses.append(
        _action("evaluate_development", candidate_id=validated["candidate_id"])
    )
    assert runtime.step("correct", 0)["outcome"] == "DEVELOPMENT_EVALUATED"


def test_workflow_uses_current_slot_hypothesis_even_for_same_graph(tmp_path):
    altered = json.loads(_proposal(validate=True))
    altered["arguments"]["hypothesis"]["summary"] = "Different slot hypothesis on the same graph"
    provider = FakeProvider(_proposal(validate=True), json.dumps(altered))
    runtime = _runtime(
        tmp_path / "run.sqlite",
        provider,
        evaluator=FakeEvaluator(),
        require_evaluated_submission=True,
    )
    first = runtime.step("first", 0)
    second = runtime.step("second", 1)
    assert first["candidate_id"] == second["candidate_id"]
    provider.responses.append(_action("evaluate_development", candidate_id=second["candidate_id"]))
    assert runtime.step("eval-second", 1)["outcome"] == "DEVELOPMENT_EVALUATED"
    assert (
        runtime._workflow(1)["required_action"]["arguments"]["hypothesis"]["summary"]
        == altered["arguments"]["hypothesis"]["summary"]
    )


class GuidedProvider:
    def __init__(self, index):
        self.index = index
        self.calls = 0

    def respond(self, request):
        workflow = json.loads(request.context_json)["workflow"]
        action = workflow.get("required_action")
        if action is None:
            action = json.loads(baseline_action("manual", 0, self.index))
            action["tool"] = "validate_factor"
        self.calls += 1
        return ResearchReply(json.dumps(action), 100, 100)


def test_full_audit_plan_and_guided_real_evaluator_integration(tmp_path, monkeypatch):
    protocol = completion_fixture(tmp_path)
    previous = tmp_path / "previous"
    run_completion(
        protocol,
        previous,
        provider_factory=lambda method, run: ScriptedProvider(feedback=method == "feedback_agent"),
    )
    audit = review_completion(previous, tmp_path / "review.json")
    assert audit["arithmetic_and_chain_passed"] is True
    assert audit["reviewer_independent_of_author"] is False
    assert audit["feedback_evaluations"] == 9
    plan = evidence_plan(previous, tmp_path / "plan.json")
    assert plan["next_mechanism_search_admitted"] is False
    assert len(plan["future_design_scenarios"]) == 4
    frozen = tmp_path / "workflow.json"
    freeze_workflow(previous, tmp_path / "llm.toml", frozen)
    providers = []

    def factory(index, instruction):
        provider = GuidedProvider(index)
        providers.append(provider)
        return provider

    result = run_workflow(frozen, tmp_path / "workflow", provider_factory=factory)
    assert result["passed"] is True
    assert result["real_model_workflow_accepted"] is False
    assert result["attempts"] == 9
    assert result["development_evaluation_calls"] == 3
    assert sum(p.calls for p in providers) == 9
    assert result["autonomous_agent_value_demonstrated"] is False
    resumed = run_workflow(
        frozen, tmp_path / "workflow", provider_factory=lambda *a: pytest.fail("recall")
    )
    assert (
        resumed["provider_calls_this_invocation"] == resumed["evaluator_calls_this_invocation"] == 0
    )
    assert resumed["evidence_id"] == result["evidence_id"]
    # Even a correctly re-sealed summary cannot alter audited arithmetic.
    run_path = previous / "runs/manual-0.json"
    run = json.loads(run_path.read_text())
    evaluation = run["slots"][0]["evaluation"]
    evaluation["daily"][0]["cost"] += 0.1
    with pytest.raises(ValueError, match="cost/notional"):
        audit_daily(evaluation, [d["session_date"] for d in evaluation["daily"]])
    monkeypatch.setattr(ResearchCapabilityRuntime, "step", lambda *a: {"outcome": "RUN_BUSY"})
    with pytest.raises(RuntimeError, match="pending workflow"):
        run_workflow(frozen, tmp_path / "busy", provider_factory=factory)
    assert not (tmp_path / "busy/run-0.json").exists()
    assert not (tmp_path / "busy/summary.json").exists()

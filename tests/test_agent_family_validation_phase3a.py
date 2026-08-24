from datetime import datetime, timezone

import numpy as np

from finagent.agents import (
    AgentRunContext,
    AgentTask,
    DefaultResearchAgentPolicy,
    ExperimentEvaluatorRegistry,
    FamilyValidationInputs,
    FamilyValidationPolicy,
    ResearchToolDependencies,
    SQLiteAgentAuditStore,
    ToolCallRequest,
    ToolCallStatus,
    ToolRegistry,
    build_research_tools,
)
from finagent.research import (
    ExperimentEvaluation,
    ExperimentFamilyValidator,
    ExperimentRunner,
    SQLiteResearchQueryService,
    SQLiteResearchRegistry,
)


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)


def _counter(prefix):
    state = {"n": 0}

    def make():
        state["n"] += 1
        return f"{prefix}-{state['n']}"

    return make


def _artifact(artifact_id, artifact_type):
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "version": "v1",
        "digest": f"digest-{artifact_id}",
    }


def _exp(family, experiment_id):
    return {
        "family_id": family,
        "experiment_id": experiment_id,
        "hypothesis": experiment_id,
        "dataset": _artifact("dataset", "dataset"),
        "code": _artifact(f"code-{experiment_id}", "code"),
        "universe": [{"symbol": "AAA", "asset_type": "equity", "currency": "USD"}],
        "evaluator_id": "fixed",
    }


def test_family_validation_tool_uses_trusted_provider_and_fixed_policy(tmp_path):
    path = tmp_path / "state.db"
    research = SQLiteResearchRegistry(path)
    query = SQLiteResearchQueryService(research)
    evaluators = ExperimentEvaluatorRegistry()
    evaluators.register("fixed", lambda spec: ExperimentEvaluation(metrics={"x": 1.0}, passed=True))
    runner = ExperimentRunner(
        research,
        clock=lambda: NOW,
        run_id_factory=_counter("run"),
        environment={"test": "phase3a"},
    )
    rng = np.random.default_rng(11)
    base = rng.normal(0.002, 0.01, 48)
    inputs = FamilyValidationInputs(
        trial_returns={
            "exp-a": base + rng.normal(0.0, 0.001, 48),
            "exp-b": rng.normal(0.0, 0.01, 48),
        },
        pvalues={"exp-a": 0.001, "exp-b": 0.7},
    )
    provider_calls = []

    def provider(family_id):
        provider_calls.append(family_id)
        return inputs

    deps = ResearchToolDependencies(
        registry=research,
        query=query,
        runner=runner,
        family_validator=ExperimentFamilyValidator(research),
        evaluators=evaluators,
        validation_input_provider=provider,
        validation_policy=FamilyValidationPolicy(
            dsr_probability_threshold=0.5,
            pbo_threshold=1.0,
            pbo_blocks=4,
            bootstrap_samples=25,
            seed=3,
        ),
        clock=lambda: NOW,
    )
    audit = SQLiteAgentAuditStore(path, event_id_factory=_counter("event"))
    task = AgentTask("task", "validate", NOW)
    context = AgentRunContext("agent-run", task.task_id, "research-agent", NOW)
    audit.start_run(task, context)
    tools = ToolRegistry(
        policy_engine=DefaultResearchAgentPolicy(),
        audit_store=audit,
        clock=lambda: NOW,
        decision_id_factory=_counter("policy"),
    )
    tools.register_many(build_research_tools(deps))

    def call(call_id, name, args):
        return tools.invoke(ToolCallRequest(call_id, name, args, NOW), context)

    call(
        "c1",
        "create_experiment_family",
        {"family_id": "family", "research_question": "q", "primary_metric": "return"},
    )
    call("c2", "register_experiment", _exp("family", "exp-a"))
    call("c3", "register_experiment", _exp("family", "exp-b"))
    call("c4", "freeze_experiment_family", {"family_id": "family"})
    validated = call(
        "c5",
        "validate_experiment_family",
        {"family_id": "family", "selected_experiment_id": "exp-a"},
    )
    assert validated.status is ToolCallStatus.SUCCEEDED
    assert provider_calls == ["family"]
    assert validated.output["experiment_order"] == ["exp-a", "exp-b"]
    assert validated.output["validation_policy"]["pbo_threshold"] == 1.0
    assert validated.output["validation_policy"]["seed"] == 3

    attempted_override = call(
        "c6",
        "validate_experiment_family",
        {
            "family_id": "family",
            "selected_experiment_id": "exp-a",
            "pbo_threshold": 0.999,
        },
    )
    assert attempted_override.status is ToolCallStatus.DENIED
    assert provider_calls == ["family"]

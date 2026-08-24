from datetime import datetime, timezone

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
from finagent.domain.experiments import ArtifactRef, ArtifactType
from finagent.domain.model_registry import ModelStage, RegisteredModel
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


def _system(tmp_path, validation_provider=None):
    path = tmp_path / "state.db"
    research = SQLiteResearchRegistry(path)
    query = SQLiteResearchQueryService(research)
    evaluators = ExperimentEvaluatorRegistry()
    evaluators.register(
        "fixed",
        lambda spec: ExperimentEvaluation(
            metrics={"score": float(spec.parameters.get("score", 1.0))},
            passed=True,
            notes="deterministic",
        ),
    )
    runner = ExperimentRunner(
        research,
        clock=lambda: NOW,
        run_id_factory=_counter("run"),
        environment={"test": "phase3a"},
    )
    validator = ExperimentFamilyValidator(research)
    if validation_provider is None:
        validation_provider = lambda family_id: FamilyValidationInputs(
            trial_returns={}, pvalues={}
        )
    deps = ResearchToolDependencies(
        registry=research,
        query=query,
        runner=runner,
        family_validator=validator,
        evaluators=evaluators,
        validation_input_provider=validation_provider,
        validation_policy=FamilyValidationPolicy(
            pbo_blocks=4,
            bootstrap_samples=20,
            seed=7,
        ),
        clock=lambda: NOW,
    )
    audit = SQLiteAgentAuditStore(path, event_id_factory=_counter("event"))
    task = AgentTask("task-1", "evaluate a registered research family", NOW)
    context = AgentRunContext("agent-run-1", task.task_id, "research-agent", NOW)
    audit.start_run(task, context)
    tools = ToolRegistry(
        policy_engine=DefaultResearchAgentPolicy(),
        audit_store=audit,
        clock=lambda: NOW,
        decision_id_factory=_counter("policy"),
    )
    tools.register_many(build_research_tools(deps))
    return research, query, audit, tools, context


def _invoke(tools, context, call_id, tool_name, arguments):
    return tools.invoke(ToolCallRequest(call_id, tool_name, arguments, NOW), context)


def _artifact(artifact_id, artifact_type):
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "version": "v1",
        "digest": f"digest-{artifact_id}",
    }


def _experiment_args(family_id="family-a", experiment_id="exp-a", score=1.0):
    return {
        "family_id": family_id,
        "experiment_id": experiment_id,
        "hypothesis": f"{experiment_id} has predictive value",
        "dataset": _artifact("dataset-a", "dataset"),
        "code": _artifact(f"code-{experiment_id}", "code"),
        "universe": [
            {
                "symbol": "AAA",
                "asset_type": "equity",
                "venue": "TEST",
                "currency": "USD",
            }
        ],
        "evaluator_id": "fixed",
        "parameters": {"score": score},
        "seed": 3,
    }


def test_research_tool_surface_contains_only_phase3a_actions(tmp_path):
    research, query, audit, tools, context = _system(tmp_path)
    assert set(tools.names()) == {
        "inspect_data_contract",
        "list_experiment_families",
        "inspect_experiment_family",
        "list_experiments",
        "inspect_experiment",
        "compare_experiment_results",
        "inspect_model_registry",
        "inspect_model_history",
        "create_experiment_family",
        "register_experiment",
        "run_experiment",
        "freeze_experiment_family",
        "validate_experiment_family",
        "request_model_promotion",
    }
    assert "set_portfolio_weights" not in tools.names()
    assert "promote_model" not in tools.names()
    assert "execute_broker_order" not in tools.names()


def test_create_register_run_and_inspect_experiment_through_tools(tmp_path):
    research, query, audit, tools, context = _system(tmp_path)
    created = _invoke(
        tools,
        context,
        "call-1",
        "create_experiment_family",
        {
            "family_id": "family-a",
            "research_question": "Does the approved baseline work?",
            "primary_metric": "score",
        },
    )
    assert created.status is ToolCallStatus.SUCCEEDED
    registered = _invoke(
        tools,
        context,
        "call-2",
        "register_experiment",
        _experiment_args(),
    )
    assert registered.status is ToolCallStatus.SUCCEEDED
    assert research.family_members("family-a")[0].experiment_id == "exp-a"

    executed = _invoke(
        tools,
        context,
        "call-3",
        "run_experiment",
        {"experiment_id": "exp-a"},
    )
    assert executed.status is ToolCallStatus.SUCCEEDED
    assert executed.output["result"]["metrics"]["score"] == 1.0

    inspected = _invoke(
        tools,
        context,
        "call-4",
        "inspect_experiment",
        {"experiment_id": "exp-a"},
    )
    assert inspected.status is ToolCallStatus.SUCCEEDED
    assert inspected.output["experiment"]["metadata"]["evaluator_id"] == "fixed"
    assert inspected.output["latest_result"]["passed"] is True
    assert inspected.output["runs"][-1]["status"] == "succeeded"


def test_frozen_family_rejects_agent_attempt_to_add_trial(tmp_path):
    research, query, audit, tools, context = _system(tmp_path)
    _invoke(
        tools,
        context,
        "call-1",
        "create_experiment_family",
        {
            "family_id": "family-a",
            "research_question": "question",
            "primary_metric": "score",
        },
    )
    _invoke(tools, context, "call-2", "register_experiment", _experiment_args())
    frozen = _invoke(
        tools,
        context,
        "call-3",
        "freeze_experiment_family",
        {"family_id": "family-a"},
    )
    assert frozen.status is ToolCallStatus.SUCCEEDED

    rejected = _invoke(
        tools,
        context,
        "call-4",
        "register_experiment",
        _experiment_args(experiment_id="exp-b"),
    )
    assert rejected.status is ToolCallStatus.FAILED
    assert "OPEN family" in rejected.error
    assert tuple(member.experiment_id for member in research.family_members("family-a")) == (
        "exp-a",
    )


def test_candidate_to_validated_is_only_a_promotion_request(tmp_path):
    research, query, audit, tools, context = _system(tmp_path)
    model = RegisteredModel(
        model_id="model-a",
        family="alpha",
        artifact=ArtifactRef("model-artifact", ArtifactType.MODEL, "v1", "model-digest"),
        stage=ModelStage.CANDIDATE,
        created_at=NOW,
        metrics={"sharpe": 1.0},
    )
    research.register_model(model)
    result = _invoke(
        tools,
        context,
        "call-1",
        "request_model_promotion",
        {"model_id": "model-a", "to_stage": "validated", "reason": "passed family gate"},
    )
    assert result.status is ToolCallStatus.SUCCEEDED
    assert result.output["request"]["mutation_performed"] is False
    assert research.get_model("model-a").stage is ModelStage.CANDIDATE


def test_shadow_and_live_promotion_requests_require_human_before_handler(tmp_path):
    research, query, audit, tools, context = _system(tmp_path)
    model = RegisteredModel(
        model_id="model-a",
        family="alpha",
        artifact=ArtifactRef("model-artifact", ArtifactType.MODEL, "v1", "model-digest"),
        stage=ModelStage.CANDIDATE,
        created_at=NOW,
    )
    research.register_model(model)
    research.promote_model(
        "model-a", ModelStage.VALIDATED, changed_at=NOW, reason="validated", actor="system"
    )
    research.promote_model(
        "model-a", ModelStage.PAPER, changed_at=NOW, reason="paper", actor="system"
    )
    result = _invoke(
        tools,
        context,
        "call-1",
        "request_model_promotion",
        {"model_id": "model-a", "to_stage": "shadow", "reason": "paper stable"},
    )
    assert result.status is ToolCallStatus.REQUIRES_APPROVAL
    assert "human approval" in result.error
    assert research.get_model("model-a").stage is ModelStage.PAPER

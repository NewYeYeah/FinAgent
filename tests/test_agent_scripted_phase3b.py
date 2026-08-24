from datetime import datetime, timezone

from finagent.agents import (
    AgentDecisionStatus, AgentReplayEngine, AgentRunCoordinator, AgentTask,
    DefaultResearchAgentPolicy, ExperimentEvaluatorRegistry, ExperimentTemplate,
    ExperimentTemplateRegistry, ExperimentVariant, FamilyValidationInputs,
    FamilyValidationPolicy, ResearchBudget, ResearchPlan, ResearchToolDependencies,
    SQLiteAgentAuditStore, SQLiteAgentPlanStore, ScriptedResearchAgent,
    ToolRegistry, build_research_tools,
)
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiments import ArtifactRef, ArtifactType
from finagent.research import (
    ExperimentEvaluation, ExperimentFamilyValidator, ExperimentRunner,
    SQLiteResearchQueryService, SQLiteResearchRegistry,
)

NOW = datetime(2026, 8, 24, 15, 30, tzinfo=timezone.utc)


def _counter(prefix):
    state = {"n": 0}
    def make():
        state["n"] += 1
        return f"{prefix}-{state['n']}"
    return make


def _plan(max_tool_calls=20, max_failed=0):
    variants = (
        ExperimentVariant("ar1", "exp-ar1", {"order": 1, "score": 0.8, "turnover": 0.30}, "AR1"),
        ExperimentVariant("ar2", "exp-ar2", {"order": 2, "score": 1.1, "turnover": 0.25}, "AR2"),
        ExperimentVariant("ar3", "exp-ar3", {"order": 3, "score": 1.1, "turnover": 0.15}, "AR3"),
    )
    return ResearchPlan(
        plan_id="plan-ar-order", planner_version="scripted-1", family_id="family-ar",
        research_question="Which AR order is strongest?", primary_metric="validation_sharpe",
        template_id="ar-order", variants=variants,
        budget=ResearchBudget(max_tool_calls, 3, 3, max_failed),
        tie_break_metric="turnover",
    )


def _system(tmp_path, fail_order=None):
    path = tmp_path / "state.db"
    research = SQLiteResearchRegistry(path)
    query = SQLiteResearchQueryService(research)
    evaluators = ExperimentEvaluatorRegistry()
    def evaluator(spec):
        order = int(spec.parameters["order"])
        if order == fail_order:
            raise RuntimeError("forced evaluator failure")
        return ExperimentEvaluation(
            metrics={"validation_sharpe": float(spec.parameters["score"]), "turnover": float(spec.parameters["turnover"])},
            passed=True,
            notes="phase3b fixture",
        )
    evaluators.register("ar-order-evaluator", evaluator)
    runner = ExperimentRunner(research, clock=lambda: NOW, run_id_factory=_counter("exp-run"), environment={"phase": "3b"})
    validator = ExperimentFamilyValidator(research)
    returns = {
        "exp-ar1": [0.001, 0.002, -0.001, 0.0015] * 8,
        "exp-ar2": [0.002, 0.0025, -0.0005, 0.002] * 8,
        "exp-ar3": [0.0022, 0.0024, -0.0004, 0.0021] * 8,
    }
    deps = ResearchToolDependencies(
        registry=research, query=query, runner=runner, family_validator=validator,
        evaluators=evaluators,
        validation_input_provider=lambda family_id: FamilyValidationInputs(
            trial_returns=returns, pvalues={"exp-ar1": 0.04, "exp-ar2": 0.03, "exp-ar3": 0.02}
        ),
        validation_policy=FamilyValidationPolicy(pbo_blocks=4, bootstrap_samples=20, seed=3),
        clock=lambda: NOW,
    )
    audit = SQLiteAgentAuditStore(path, event_id_factory=_counter("audit-event"))
    plans = SQLiteAgentPlanStore(path)
    tools = ToolRegistry(policy_engine=DefaultResearchAgentPolicy(), audit_store=audit, clock=lambda: NOW, decision_id_factory=_counter("policy"))
    tools.register_many(build_research_tools(deps))
    templates = ExperimentTemplateRegistry()
    templates.register(ExperimentTemplate(
        "ar-order", "ar-order-evaluator",
        ArtifactRef("dataset-p3b", ArtifactType.DATASET, "v1", "dataset-digest"),
        ArtifactRef("code-p3b", ArtifactType.CODE, "v1", "code-digest"),
        (AssetId("AAA", AssetType.EQUITY, "TEST", "USD"),),
        frozenset({"order", "score", "turnover"}), seed=11,
    ))
    return research, audit, plans, tools, templates


def _execute(tmp_path, plan=None, fail_order=None):
    research, audit, plans, tools, templates = _system(tmp_path, fail_order)
    plan = plan or _plan()
    runtime = ScriptedResearchAgent(plan=plan, templates=templates, plan_store=plans, clock=lambda: NOW)
    coordinator = AgentRunCoordinator(audit_store=audit, plan_store=plans, clock=lambda: NOW, run_id_factory=_counter("agent-run"))
    task = AgentTask("task-ar", "compare approved AR orders", NOW)
    decision = coordinator.run(runtime=runtime, task=task, tools=tools, actor="scripted-agent", plan=plan)
    return decision, research, audit, plans


def test_plan_budget_and_fingerprint_are_frozen():
    plan = _plan()
    assert plan.maximum_tool_calls == 12
    assert plan.fingerprint("task-a") == plan.fingerprint("task-a")
    assert plan.fingerprint("task-a") != plan.fingerprint("task-b")
    try:
        _plan(max_tool_calls=5)
    except ValueError as exc:
        assert "maximum tool calls" in str(exc)
    else:
        raise AssertionError("expected budget rejection")


def test_scripted_agent_executes_complete_governed_loop(tmp_path):
    decision, research, audit, plans = _execute(tmp_path)
    assert decision.status is AgentDecisionStatus.COMPLETED
    assert decision.metadata["selected_experiment_id"] == "exp-ar3"
    assert research.get_family("family-ar").status.value == "frozen"
    assert [m.experiment_id for m in research.family_members("family-ar")] == ["exp-ar1", "exp-ar2", "exp-ar3"]
    assert len(audit.replay_requests(decision.run_id)) == 12
    assert plans.events(decision.run_id)[0][1]["experiment_id"] == "exp-ar3"


def test_failed_trial_is_not_removed_from_family(tmp_path):
    decision, research, audit, plans = _execute(tmp_path, fail_order=2)
    assert decision.status is AgentDecisionStatus.FAILED
    assert "failed experiment budget exceeded" in decision.summary
    assert [m.experiment_id for m in research.family_members("family-ar")] == ["exp-ar1", "exp-ar2", "exp-ar3"]
    runs = SQLiteResearchQueryService(research).runs_for_experiment("exp-ar2")
    assert runs[-1].status.value == "failed"


def test_winner_selection_is_metric_then_turnover_then_id():
    primary = {"comparisons": [
        {"experiment_id": "b", "value": 1.0, "passed": True},
        {"experiment_id": "a", "value": 1.0, "passed": True},
    ]}
    tie = {"comparisons": [
        {"experiment_id": "b", "value": 0.2, "passed": True},
        {"experiment_id": "a", "value": 0.1, "passed": True},
    ]}
    assert ScriptedResearchAgent._select_winner(primary, tie).experiment_id == "a"


def test_plan_store_is_append_only(tmp_path):
    _, audit, plans, _, _ = _system(tmp_path)
    plan = _plan()
    plans.record_plan("run-1", "task-a", plan)
    try:
        plans.record_plan("run-1", "task-a", plan)
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("expected duplicate plan rejection")


def test_dry_replay_is_equivalent_across_isolated_runs(tmp_path):
    left, _, left_audit, left_plans = _execute(tmp_path / "left")
    right, _, right_audit, right_plans = _execute(tmp_path / "right")
    left_trace = AgentReplayEngine(audit_store=left_audit, plan_store=left_plans).dry_replay(left.run_id)
    right_trace = AgentReplayEngine(audit_store=right_audit, plan_store=right_plans).dry_replay(right.run_id)
    comparison = AgentReplayEngine.compare(left_trace, right_trace)
    assert comparison.equivalent
    assert left_trace.selection["experiment_id"] == "exp-ar3"

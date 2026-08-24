from __future__ import annotations

from datetime import datetime, timedelta, timezone

from finagent.agents import (
    AgentAction,
    AgentDecisionStatus,
    AgentRunContext,
    AgentTask,
    HealthCheck,
    HealthLevel,
    OperatingPolicyRegistry,
    PortfolioBenchmarkSummary,
    PortfolioHealthMonitor,
    PortfolioHealthSnapshot,
    PortfolioHealthThresholds,
    PortfolioStressSummary,
    PortfolioSupervisorPolicy,
    PortfolioSupervisorToolDependencies,
    SQLiteAgentAuditStore,
    SQLitePortfolioSupervisionStore,
    ScriptedPortfolioSupervisorAgent,
    ToolCallRequest,
    ToolCallStatus,
    ToolMode,
    ToolRegistry,
    WeightDriftSummary,
    build_portfolio_supervisor_tools,
)
from finagent.agents.tools import FunctionTool, ToolSpec
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.forecasts import AlphaForecast, ModelRef, RiskForecast
from finagent.domain.portfolio import PortfolioState, PortfolioTarget
from finagent.portfolio.benchmarks import PortfolioBenchmarkMetrics, PortfolioBenchmarkResult
from finagent.portfolio.stress import RebalanceDecision, ScenarioResult, StressTestReport


UTC = timezone.utc
NOW = datetime(2026, 8, 25, 2, 0, tzinfo=UTC)
ASOF = NOW - timedelta(hours=1)


def _counter(prefix):
    state = {"n": 0}

    def make():
        state["n"] += 1
        return f"{prefix}-{state['n']}"

    return make


def _phase4_inputs():
    a = AssetId("AAA", AssetType.EQUITY, venue="XNAS", currency="USD")
    b = AssetId("BBB", AssetType.EQUITY, venue="XNAS", currency="USD")
    alpha = AlphaForecast(
        ASOF,
        timedelta(days=1),
        {a: 0.01, b: 0.02},
        ModelRef("ensemble", "phase4"),
    )
    risk = RiskForecast(
        ASOF,
        timedelta(days=1),
        {a: 0.10, b: 0.20},
        {
            (a, a): 0.01,
            (a, b): 0.005,
            (b, a): 0.005,
            (b, b): 0.04,
        },
        ModelRef("oas", "phase4"),
    )
    state = PortfolioState(
        ASOF,
        "USD",
        1000.0,
        positions={a: 5.0, b: 5.0},
        marks={a: 100.0, b: 100.0},
    )
    target = PortfolioTarget(
        ASOF,
        {a: 0.50, b: 0.50},
        0.0,
        ModelRef("mean_variance", "phase4"),
    )
    metrics = PortfolioBenchmarkMetrics(
        expected_return=0.015,
        volatility=0.12,
        turnover=0.25,
        expected_transaction_cost=0.000125,
        expected_net_return=0.014875,
        gross_exposure=1.0,
        net_exposure=1.0,
    )
    benchmark = PortfolioBenchmarkResult("mean_variance", target, metrics)
    stress = StressTestReport((ScenarioResult("mild", -0.03), ScenarioResult("crash", -0.20)))
    rebalance = RebalanceDecision(True, 0.25, 0.25, ("force_turnover",))
    return alpha, risk, state, benchmark, stress, rebalance


def _snapshot(level: HealthLevel, *, rebalance_required: bool = False) -> PortfolioHealthSnapshot:
    return PortfolioHealthSnapshot(
        snapshot_id=f"snapshot-{level.value}-{int(rebalance_required)}",
        asof=ASOF,
        observed_at=NOW,
        data_asof=ASOF,
        selected_constructor="mean_variance",
        checks=(HealthCheck("primary", level, f"{level.value} condition"),),
        benchmarks=(
            PortfolioBenchmarkSummary("mean_variance", 0.01, 0.009, 0.10, 0.05, 1.0, 1.0),
            PortfolioBenchmarkSummary("minimum_variance", 0.006, 0.0055, 0.07, 0.02, 1.0, 1.0),
        ),
        stresses=(PortfolioStressSummary("crash", -0.15),),
        weight_drifts=(WeightDriftSummary("equity:XNAS:AAA:USD", 0.45, 0.50, 0.05),),
        rebalance_required=rebalance_required,
        rebalance_turnover=0.10 if rebalance_required else 0.0,
        rebalance_max_weight_drift=0.06 if rebalance_required else 0.0,
        rebalance_reasons=("weight_drift",) if rebalance_required else (),
        metadata={"source": "test"},
    )


def _registry(tmp_path, snapshot):
    supervision = SQLitePortfolioSupervisionStore(tmp_path / "supervision.db")
    supervision.register(snapshot)
    audit = SQLiteAgentAuditStore(tmp_path / "audit.db", event_id_factory=_counter("event"))
    task = AgentTask("task-supervisor", "inspect portfolio health", NOW)
    context = AgentRunContext(
        "run-supervisor",
        task.task_id,
        "portfolio-supervisor",
        NOW,
        max_tool_calls=20,
    )
    audit.start_run(task, context)
    registry = ToolRegistry(
        policy_engine=PortfolioSupervisorPolicy(),
        audit_store=audit,
        clock=lambda: NOW,
        decision_id_factory=_counter("policy"),
    )
    registry.register_many(
        build_portfolio_supervisor_tools(
            PortfolioSupervisorToolDependencies(supervision, OperatingPolicyRegistry.reference())
        )
    )
    return task, context, registry, audit, supervision


def test_health_monitor_detects_stale_data_stress_and_rebalance():
    alpha, risk, state, benchmark, stress, rebalance = _phase4_inputs()
    monitor = PortfolioHealthMonitor(
        PortfolioHealthThresholds(
            max_data_age=timedelta(minutes=30),
            max_forecast_age=timedelta(hours=2),
            max_turnover=0.20,
            max_stress_loss=0.10,
        )
    )
    snapshot = monitor.build(
        snapshot_id="health-1",
        observed_at=NOW,
        data_asof=ASOF,
        alpha=alpha,
        risk=risk,
        state=state,
        benchmarks=(benchmark,),
        stress_report=stress,
        rebalance=rebalance,
        selected_constructor="mean_variance",
    )
    assert snapshot.overall_level is HealthLevel.CRITICAL
    assert snapshot.worst_stress.name == "crash"
    assert snapshot.rebalance_required is True
    assert snapshot.weight_drifts[0].delta == 0.25
    assert {check.name for check in snapshot.checks} >= {"data_freshness", "stress_loss", "rebalance"}


def test_supervision_store_is_immutable_and_round_trips(tmp_path):
    snapshot = _snapshot(HealthLevel.WARNING, rebalance_required=True)
    store = SQLitePortfolioSupervisionStore(tmp_path / "supervision.db")
    store.register(snapshot)
    store.register(snapshot)
    loaded = store.get(snapshot.snapshot_id)
    assert loaded == snapshot
    changed = PortfolioHealthSnapshot(
        snapshot.snapshot_id,
        snapshot.asof,
        snapshot.observed_at,
        snapshot.data_asof,
        snapshot.selected_constructor,
        (HealthCheck("changed", HealthLevel.CRITICAL, "changed"),),
        snapshot.benchmarks,
        snapshot.stresses,
        snapshot.weight_drifts,
        snapshot.rebalance_required,
        snapshot.rebalance_turnover,
        snapshot.rebalance_max_weight_drift,
        snapshot.rebalance_reasons,
        snapshot.metadata,
    )
    try:
        store.register(changed)
    except ValueError as exc:
        assert "immutable" in str(exc)
    else:
        raise AssertionError("mutable supervision evidence was unexpectedly accepted")


def test_supervisor_request_tools_are_non_mutating_and_require_approval(tmp_path):
    snapshot = _snapshot(HealthLevel.CRITICAL, rebalance_required=True)
    task, context, registry, audit, supervision = _registry(tmp_path, snapshot)
    result = registry.invoke(
        ToolCallRequest(
            "call-policy",
            AgentAction.REQUEST_OPERATING_POLICY.value,
            {"snapshot_id": snapshot.snapshot_id, "policy_id": "defensive", "reason": "stress"},
            NOW,
        ),
        context,
    )
    assert result.status is ToolCallStatus.REQUIRES_APPROVAL
    assert result.output["mutation_performed"] is False
    assert result.output["mode"] == "defensive"

    rebalance_result = registry.invoke(
        ToolCallRequest(
            "call-rebalance",
            AgentAction.REQUEST_REBALANCE.value,
            {"snapshot_id": snapshot.snapshot_id, "reason": "drift"},
            NOW,
        ),
        context,
    )
    assert rebalance_result.status is ToolCallStatus.REQUIRES_APPROVAL
    assert rebalance_result.output["mutation_performed"] is False


def test_supervisor_policy_denies_research_write_even_if_registered(tmp_path):
    snapshot = _snapshot(HealthLevel.OK)
    task, context, registry, audit, supervision = _registry(tmp_path, snapshot)
    called = {"value": False}

    registry.register(
        FunctionTool(
            ToolSpec(
                AgentAction.RUN_EXPERIMENT.value,
                "should be forbidden to portfolio supervisor",
                AgentAction.RUN_EXPERIMENT,
                ToolMode.WRITE,
            ),
            lambda arguments, ctx: called.__setitem__("value", True) or {"ok": True},
        )
    )
    result = registry.invoke(
        ToolCallRequest("call-research", AgentAction.RUN_EXPERIMENT.value, {}, NOW),
        context,
    )
    assert result.status is ToolCallStatus.DENIED
    assert called["value"] is False
    assert "outside" in result.error


def test_supervisor_tool_surface_has_no_direct_weight_or_execution_capability(tmp_path):
    snapshot = _snapshot(HealthLevel.OK)
    task, context, registry, audit, supervision = _registry(tmp_path, snapshot)
    names = set(registry.names())
    assert "set_portfolio_weights" not in names
    assert "bypass_risk_gate" not in names
    assert "choose_fill_price" not in names
    assert "execute_broker_order" not in names
    assert AgentAction.REQUEST_REBALANCE.value in names
    assert AgentAction.REQUEST_OPERATING_POLICY.value in names


def test_scripted_supervisor_healthy_snapshot_only_inspects(tmp_path):
    snapshot = _snapshot(HealthLevel.OK)
    task, context, registry, audit, supervision = _registry(tmp_path, snapshot)
    decision = ScriptedPortfolioSupervisorAgent(snapshot.snapshot_id).run(task, registry, context)
    assert decision.status is AgentDecisionStatus.COMPLETED
    requests = audit.replay_requests(context.run_id)
    assert len(requests) == 5
    assert all(request.tool_name.startswith("inspect_") or request.tool_name == "list_operating_policies" for request in requests)


def test_scripted_supervisor_warning_requests_rebalance_without_mutation(tmp_path):
    snapshot = _snapshot(HealthLevel.WARNING, rebalance_required=True)
    task, context, registry, audit, supervision = _registry(tmp_path, snapshot)
    decision = ScriptedPortfolioSupervisorAgent(snapshot.snapshot_id).run(task, registry, context)
    assert decision.status is AgentDecisionStatus.BLOCKED
    requests = audit.replay_requests(context.run_id)
    assert requests[-1].tool_name == AgentAction.REQUEST_REBALANCE.value
    results = [audit.get_tool_result(request.call_id) for request in requests]
    assert results[-1].status is ToolCallStatus.REQUIRES_APPROVAL
    assert results[-1].output["mutation_performed"] is False


def test_scripted_supervisor_critical_requests_defensive_policy_and_review(tmp_path):
    snapshot = _snapshot(HealthLevel.CRITICAL, rebalance_required=True)
    task, context, registry, audit, supervision = _registry(tmp_path, snapshot)
    decision = ScriptedPortfolioSupervisorAgent(snapshot.snapshot_id).run(task, registry, context)
    assert decision.status is AgentDecisionStatus.BLOCKED
    assert decision.metadata["recommended_policy"] == "defensive"
    requests = audit.replay_requests(context.run_id)
    assert requests[-2].tool_name == AgentAction.REQUEST_OPERATING_POLICY.value
    assert requests[-1].tool_name == AgentAction.REQUEST_HUMAN_REVIEW.value
    policy_result = audit.get_tool_result(requests[-2].call_id)
    review_result = audit.get_tool_result(requests[-1].call_id)
    assert policy_result.status is ToolCallStatus.REQUIRES_APPROVAL
    assert policy_result.output["mutation_performed"] is False
    assert review_result.status is ToolCallStatus.SUCCEEDED
    assert review_result.output["mutation_performed"] is False

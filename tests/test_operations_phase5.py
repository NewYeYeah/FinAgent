from datetime import date, datetime, time, timezone

import pytest

from finagent.agents.supervisor import (
    OperatingPolicyRegistry,
    PortfolioBenchmarkSummary,
    PortfolioHealthSnapshot,
    SQLitePortfolioSupervisionStore,
)
from finagent.domain.assets import AssetId
from finagent.domain.execution import ExecutionQuote, ExecutionSnapshot, Fill
from finagent.domain.forecasts import ModelRef
from finagent.domain.orders import OrderIntent, OrderSide
from finagent.domain.portfolio import PortfolioState, PortfolioTarget
from finagent.operations import (
    ApprovedPaperTradingController,
    BrokerOrderStatus,
    CorporateAction,
    CorporateActionType,
    ExecutionCostCalibrator,
    HumanApproval,
    OperationalApprovalService,
    PaperBroker,
    PaperBrokerConfig,
    PortfolioReconciler,
    ShadowPortfolioMonitor,
    SQLitePaperBrokerStore,
    TradingSafetyController,
    TradingSafetyLimits,
    TradingSessionCalendar,
)


UTC = timezone.utc
ASSET = AssetId("AAA")
OTHER = AssetId("BBB")


def _snapshot(at: datetime, *, price=100.0, volume=100.0, asset=ASSET):
    quote = ExecutionQuote(
        event_time=at,
        available_at=at,
        price=price,
        volume=volume,
        price_field="open",
    )
    return ExecutionSnapshot(at, {asset: quote}, "phase5-test")


def _health_snapshot(snapshot_id="health-1", *, rebalance=True):
    return PortfolioHealthSnapshot(
        snapshot_id=snapshot_id,
        asof=datetime(2026, 8, 25, 13, 0, tzinfo=UTC),
        observed_at=datetime(2026, 8, 25, 13, 0, tzinfo=UTC),
        data_asof=datetime(2026, 8, 25, 13, 0, tzinfo=UTC),
        selected_constructor="mean_variance",
        checks=(),
        benchmarks=(
            PortfolioBenchmarkSummary(
                "mean_variance", 0.01, 0.009, 0.1, 0.05, 1.0, 1.0
            ),
        ),
        stresses=(),
        weight_drifts=(),
        rebalance_required=rebalance,
        rebalance_turnover=0.05 if rebalance else 0.0,
        rebalance_max_weight_drift=0.05 if rebalance else 0.0,
        rebalance_reasons=("weight_drift",) if rebalance else (),
    )


def test_trading_session_calendar_respects_holiday_and_next_open():
    calendar = TradingSessionCalendar(
        timezone_name="UTC",
        open_time=time(9, 30),
        close_time=time(16, 0),
        holidays=frozenset({date(2026, 8, 25)}),
    )
    monday = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
    after_close = datetime(2026, 8, 24, 17, 0, tzinfo=UTC)
    assert calendar.is_open(monday)
    assert not calendar.is_open(after_close)
    assert calendar.next_open(after_close) == datetime(2026, 8, 26, 9, 30, tzinfo=UTC)


def test_paper_broker_partial_fill_idempotency_and_restart(tmp_path):
    store = SQLitePaperBrokerStore(tmp_path / "paper.db")
    broker = PaperBroker(
        store=store,
        config=PaperBrokerConfig(
            commission_bps=1.0,
            base_slippage_bps=0.0,
            impact_bps=0.0,
            max_participation_rate=0.10,
        ),
    )
    initial = PortfolioState(
        asof=datetime(2026, 8, 25, 13, 0, tzinfo=UTC),
        base_currency="USD",
        cash=10_000.0,
    )
    broker.initialize_account(initial)
    intent = OrderIntent(
        asset=ASSET,
        side=OrderSide.BUY,
        quantity=10.0,
        created_at=datetime(2026, 8, 25, 13, 1, tzinfo=UTC),
        client_order_id="paper-order-1",
    )
    registered = broker.submit((intent,))
    assert registered[0].status is BrokerOrderStatus.NEW

    first = broker.process(_snapshot(datetime(2026, 8, 25, 13, 2, tzinfo=UTC), volume=50.0))
    assert len(first.fills) == 1
    assert first.fills[0].quantity == pytest.approx(5.0)
    assert store.get_order(intent.client_order_id).status is BrokerOrderStatus.PARTIALLY_FILLED

    second = broker.process(_snapshot(datetime(2026, 8, 25, 13, 3, tzinfo=UTC), volume=100.0))
    assert len(second.fills) == 1
    assert second.fills[0].quantity == pytest.approx(5.0)
    assert store.get_order(intent.client_order_id).status is BrokerOrderStatus.FILLED

    repeated = broker.process(_snapshot(datetime(2026, 8, 25, 13, 3, tzinfo=UTC), volume=100.0))
    assert repeated.fills == ()
    assert len(store.list_fills(intent.client_order_id)) == 2

    restarted = PaperBroker(store=SQLitePaperBrokerStore(tmp_path / "paper.db"), config=broker.config)
    account = restarted.account()
    assert account.positions[ASSET] == pytest.approx(10.0)
    assert restarted.submit((intent,))[0].status is BrokerOrderStatus.FILLED


def test_paper_broker_rejects_out_of_session_and_client_id_reuse(tmp_path):
    store = SQLitePaperBrokerStore(tmp_path / "paper.db")
    calendar = TradingSessionCalendar(timezone_name="UTC")
    broker = PaperBroker(store=store, calendar=calendar)
    broker.initialize_account(
        PortfolioState(datetime(2026, 8, 25, 8, 0, tzinfo=UTC), "USD", 10_000.0)
    )
    rejected = OrderIntent(
        ASSET,
        OrderSide.BUY,
        1.0,
        datetime(2026, 8, 25, 8, 30, tzinfo=UTC),
        client_order_id="same-id",
    )
    assert broker.submit((rejected,))[0].status is BrokerOrderStatus.REJECTED

    different = OrderIntent(
        ASSET,
        OrderSide.BUY,
        2.0,
        datetime(2026, 8, 25, 8, 30, tzinfo=UTC),
        client_order_id="same-id",
    )
    with pytest.raises(ValueError, match="reused"):
        broker.submit((different,))


def test_corporate_actions_are_idempotent_and_preserve_split_nav(tmp_path):
    store = SQLitePaperBrokerStore(tmp_path / "paper.db")
    broker = PaperBroker(store=store)
    initial = PortfolioState(
        datetime(2026, 8, 25, 13, 0, tzinfo=UTC),
        "USD",
        1_000.0,
        {ASSET: 10.0},
        {ASSET: 100.0},
    )
    broker.initialize_account(initial)
    split = CorporateAction(
        "split-1",
        ASSET,
        CorporateActionType.SPLIT,
        datetime(2026, 8, 25, 14, 0, tzinfo=UTC),
        ratio=2.0,
    )
    after_split = broker.apply_corporate_action(split)
    assert after_split.nav == pytest.approx(initial.nav)
    assert after_split.positions[ASSET] == pytest.approx(20.0)
    assert after_split.marks[ASSET] == pytest.approx(50.0)

    duplicate = broker.apply_corporate_action(split)
    assert duplicate == after_split

    dividend = CorporateAction(
        "div-1",
        ASSET,
        CorporateActionType.CASH_DIVIDEND,
        datetime(2026, 8, 25, 15, 0, tzinfo=UTC),
        cash_amount=1.0,
    )
    after_dividend = broker.apply_corporate_action(dividend)
    assert after_dividend.cash == pytest.approx(after_split.cash + 20.0)


def test_reconciliation_critical_issue_trips_persistent_kill_switch(tmp_path):
    store = SQLitePaperBrokerStore(tmp_path / "paper.db")
    broker = PaperBroker(store=store)
    actual = PortfolioState(datetime(2026, 8, 25, 13, 0, tzinfo=UTC), "USD", 10_000.0)
    broker.initialize_account(actual)
    safety = TradingSafetyController(store=store)
    controller = ApprovedPaperTradingController(
        broker=broker,
        store=store,
        safety=safety,
        reconciler=PortfolioReconciler(),
    )
    expected = PortfolioState(datetime(2026, 8, 25, 13, 0, tzinfo=UTC), "USD", 9_900.0)
    report = controller.reconcile(expected=expected, at_snapshot_id="health-1")
    assert report.critical_count == 1
    assert store.get_kill_switch().status.value == "halted"

    restarted_store = SQLitePaperBrokerStore(tmp_path / "paper.db")
    assert restarted_store.get_kill_switch().status.value == "halted"


def test_safety_controller_blocks_notional_and_halted_state(tmp_path):
    store = SQLitePaperBrokerStore(tmp_path / "paper.db")
    account = PortfolioState(datetime(2026, 8, 25, 13, 0, tzinfo=UTC), "USD", 10_000.0)
    PaperBroker(store=store).initialize_account(account)
    safety = TradingSafetyController(
        store=store,
        limits=TradingSafetyLimits(max_order_notional=1_000.0, max_batch_notional=2_000.0),
    )
    at = datetime(2026, 8, 25, 13, 1, tzinfo=UTC)
    large = OrderIntent(ASSET, OrderSide.BUY, 20.0, at, client_order_id="large")
    decision = safety.evaluate(
        orders=(large,),
        snapshot=_snapshot(at, price=100.0, volume=1_000.0),
        account=account,
        session_start_nav=10_000.0,
    )
    assert not decision.approved
    assert any("order_notional_limit" in reason for reason in decision.reasons)

    safety.trip(at=at, reason="manual test", actor="operator")
    small = OrderIntent(ASSET, OrderSide.BUY, 1.0, at, client_order_id="small")
    halted = safety.evaluate(
        orders=(small,),
        snapshot=_snapshot(at, price=100.0, volume=1_000.0),
        account=account,
        session_start_nav=10_000.0,
    )
    assert not halted.approved
    assert "kill_switch_halted" in halted.reasons


def test_human_approval_applies_policy_and_gates_paper_rebalance(tmp_path):
    broker_store = SQLitePaperBrokerStore(tmp_path / "paper.db")
    supervision_store = SQLitePortfolioSupervisionStore(tmp_path / "supervision.db")
    supervision_store.register(_health_snapshot())
    policies = OperatingPolicyRegistry.reference()
    service = OperationalApprovalService(
        broker_store=broker_store,
        supervision_store=supervision_store,
        operating_policies=policies,
    )
    policy_request = {
        "request_type": "operating_policy",
        "snapshot_id": "health-1",
        "policy_id": "defensive",
        "mutation_performed": False,
        "requires_human_approval": True,
    }
    policy_approval = HumanApproval(
        "approval-policy",
        "operating_policy",
        "health-1",
        "human-operator",
        datetime(2026, 8, 25, 13, 1, tzinfo=UTC),
        policy_id="defensive",
    )
    service.apply(
        request_payload=policy_request,
        approval=policy_approval,
        applied_at=datetime(2026, 8, 25, 13, 2, tzinfo=UTC),
        applied_by="operations-controller",
    )
    assert broker_store.current_operating_policy() == "defensive"

    rebalance_request = {
        "request_type": "rebalance",
        "snapshot_id": "health-1",
        "mutation_performed": False,
        "requires_human_approval": True,
    }
    rebalance_approval = HumanApproval(
        "approval-rebalance",
        "rebalance",
        "health-1",
        "human-operator",
        datetime(2026, 8, 25, 13, 3, tzinfo=UTC),
    )
    service.apply(
        request_payload=rebalance_request,
        approval=rebalance_approval,
        applied_at=datetime(2026, 8, 25, 13, 4, tzinfo=UTC),
        applied_by="operations-controller",
    )
    assert broker_store.rebalance_approval_id("health-1") == "approval-rebalance"

    broker = PaperBroker(
        store=broker_store,
        config=PaperBrokerConfig(impact_bps=0.0, max_participation_rate=1.0),
    )
    broker.initialize_account(
        PortfolioState(datetime(2026, 8, 25, 13, 4, tzinfo=UTC), "USD", 10_000.0)
    )
    controller = ApprovedPaperTradingController(
        broker=broker,
        store=broker_store,
        safety=TradingSafetyController(store=broker_store),
    )
    order = OrderIntent(
        ASSET,
        OrderSide.BUY,
        1.0,
        datetime(2026, 8, 25, 13, 5, tzinfo=UTC),
        client_order_id="approved-order",
    )
    execution = _snapshot(datetime(2026, 8, 25, 13, 6, tzinfo=UTC), price=100.0, volume=100.0)

    with pytest.raises(PermissionError):
        controller.execute_rebalance(
            snapshot_id="health-1",
            approval_id="wrong-approval",
            orders=(order,),
            execution_snapshot=execution,
            session_start_nav=10_000.0,
        )

    result = controller.execute_rebalance(
        snapshot_id="health-1",
        approval_id="approval-rebalance",
        orders=(order,),
        execution_snapshot=execution,
        session_start_nav=10_000.0,
    )
    assert result.safety.approved
    assert result.cycle is not None
    assert len(result.cycle.fills) == 1


def test_shadow_comparison_and_execution_cost_calibration():
    at = datetime(2026, 8, 25, 13, 0, tzinfo=UTC)
    primary = PortfolioTarget(at, {ASSET: 0.6, OTHER: 0.4}, 0.0, ModelRef("primary", "1"))
    shadow = PortfolioTarget(at, {ASSET: 0.5, OTHER: 0.5}, 0.0, ModelRef("shadow", "2"))
    comparison = ShadowPortfolioMonitor().compare(primary, shadow)
    assert comparison.max_abs_weight_difference == pytest.approx(0.1)
    assert comparison.active_turnover == pytest.approx(0.1)
    assert comparison.cosine_similarity < 1.0

    fill = Fill(
        "fill-order",
        ASSET,
        OrderSide.BUY,
        10.0,
        101.0,
        at,
        commission=1.0,
        slippage=10.0,
        metadata={"reference_price": "100.0", "participation_rate": "0.1"},
    )
    calibrated = ExecutionCostCalibrator().fit((fill,))
    assert calibrated.fill_count == 1
    assert calibrated.weighted_slippage_bps == pytest.approx(100.0)
    assert calibrated.weighted_participation_rate == pytest.approx(0.1)

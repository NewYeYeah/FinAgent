import pytest

from finagent.domain.forecasts import ModelRef
from finagent.domain.orders import OrderSide
from finagent.domain.portfolio import PortfolioState, PortfolioTarget, RiskDecision, RiskStatus, RiskViolation
from finagent.services.execution import AccountLedger, SimulatedExchange
from finagent.services.portfolio import OrderPlanner


def approved(now):
    return RiskDecision(status=RiskStatus.APPROVE, checked_at=now)


def test_order_planner_generates_buy_and_sell(now, assets, snapshot):
    a, b = assets
    state = PortfolioState(
        asof=now,
        base_currency="USD",
        cash=500.0,
        positions={a: 5.0},
        marks={a: 100.0},
    )
    target = PortfolioTarget(
        asof=now,
        weights={a: 0.2, b: 0.8},
        cash_weight=0.0,
        source=ModelRef("optimizer", "1"),
    )
    orders = OrderPlanner().plan(target, state, snapshot, approved(now))
    by_asset = {order.asset: order for order in orders}

    assert by_asset[a].side is OrderSide.SELL
    assert by_asset[a].quantity == pytest.approx(3.0)
    assert by_asset[b].side is OrderSide.BUY
    assert by_asset[b].quantity == pytest.approx(16.0)


def test_order_planner_refuses_unapproved_target(now, assets, snapshot):
    a, b = assets
    state = PortfolioState(now, "USD", 1000.0)
    target = PortfolioTarget(
        asof=now,
        weights={a: 0.5, b: 0.5},
        cash_weight=0.0,
        source=ModelRef("optimizer", "1"),
    )
    rejected = RiskDecision(
        status=RiskStatus.REQUIRE_RESOLVE,
        violations=(RiskViolation("LIMIT", "test violation"),),
        checked_at=now,
    )
    with pytest.raises(PermissionError, match="not approved"):
        OrderPlanner().plan(target, state, snapshot, rejected)


def test_order_planner_respects_min_notional(now, assets, snapshot):
    a, b = assets
    state = PortfolioState(now, "USD", 1000.0)
    target = PortfolioTarget(
        asof=now,
        weights={a: 0.005, b: 0.0},
        cash_weight=0.995,
        source=ModelRef("optimizer", "1"),
    )
    orders = OrderPlanner(min_notional=10.0).plan(target, state, snapshot, approved(now))
    assert orders == ()


def test_simulated_exchange_applies_adverse_slippage_and_commission(now, assets, snapshot):
    a = assets[0]
    target = PortfolioTarget(
        asof=now,
        weights={a: 1.0},
        cash_weight=0.0,
        source=ModelRef("optimizer", "1"),
    )
    state = PortfolioState(now, "USD", 1000.0)
    orders = OrderPlanner().plan(target, state, snapshot, approved(now))

    report = SimulatedExchange(slippage_bps=10.0, commission_bps=5.0).execute(orders, snapshot)
    fill = report.fills[0]
    assert fill.price == pytest.approx(100.1)
    assert fill.slippage == pytest.approx(1.0)
    assert fill.commission == pytest.approx(0.5005)


def test_ledger_applies_fills_without_mutating_prior_state(now, assets, snapshot):
    a = assets[0]
    state = PortfolioState(now, "USD", 1000.0)
    target = PortfolioTarget(
        asof=now,
        weights={a: 0.5},
        cash_weight=0.5,
        source=ModelRef("optimizer", "1"),
    )
    orders = OrderPlanner().plan(target, state, snapshot, approved(now))
    report = SimulatedExchange().execute(orders, snapshot)
    updated = AccountLedger().apply_execution(state, report, snapshot)

    assert state.cash == pytest.approx(1000.0)
    assert state.positions == {}
    assert updated.cash == pytest.approx(500.0)
    assert updated.positions[a] == pytest.approx(5.0)
    assert updated.nav == pytest.approx(1000.0)

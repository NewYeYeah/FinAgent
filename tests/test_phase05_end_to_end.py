import pytest

from finagent.domain.portfolio import PortfolioState, RiskStatus
from finagent.services.execution import AccountLedger, SimulatedExchange
from finagent.services.portfolio import EqualWeightTargetBuilder, OrderPlanner, StaticRiskGate


def test_phase05_equal_weight_closed_loop(now, assets, snapshot):
    """Canonical Phase 0.5 smoke path.

    EqualWeight -> PortfolioTarget -> RiskDecision -> OrderIntent -> Fill -> PortfolioState
    """

    state0 = PortfolioState(asof=now, base_currency="USD", cash=1000.0)
    target = EqualWeightTargetBuilder().build(snapshot, assets)

    decision = StaticRiskGate(max_gross_exposure=1.0, max_abs_weight=0.5).assess(
        target, state0, snapshot
    )
    assert decision.status is RiskStatus.APPROVE

    orders = OrderPlanner().plan(target, state0, snapshot, decision)
    assert len(orders) == 2

    report = SimulatedExchange().execute(orders, snapshot)
    assert len(report.fills) == 2
    assert report.rejections == ()

    state1 = AccountLedger().apply_execution(state0, report, snapshot)
    a, b = assets
    assert state1.cash == pytest.approx(0.0)
    assert state1.nav == pytest.approx(1000.0)
    assert state1.positions[a] == pytest.approx(5.0)
    assert state1.positions[b] == pytest.approx(10.0)
    assert state1.weight(a) == pytest.approx(0.5)
    assert state1.weight(b) == pytest.approx(0.5)

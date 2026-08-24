import pytest

from finagent.domain.forecasts import ModelRef
from finagent.domain.portfolio import PortfolioState, PortfolioTarget, RiskStatus
from finagent.services.portfolio import StaticRiskGate


def test_portfolio_state_nav_and_weights(now, assets):
    a, b = assets
    state = PortfolioState(
        asof=now,
        base_currency="usd",
        cash=100.0,
        positions={a: 2.0, b: -1.0},
        marks={a: 100.0, b: 50.0},
    )
    assert state.nav == pytest.approx(250.0)
    assert state.weight(a) == pytest.approx(0.8)
    assert state.weight(b) == pytest.approx(-0.2)


def test_portfolio_state_requires_mark_for_open_position(now, assets):
    with pytest.raises(ValueError, match="require marks"):
        PortfolioState(now, "USD", 1000, positions={assets[0]: 1}, marks={})


def test_portfolio_target_supports_long_short_but_requires_accounting_identity(now, assets):
    a, b = assets
    source = ModelRef("optimizer", "1")
    target = PortfolioTarget(
        asof=now,
        weights={a: 1.2, b: -0.4},
        cash_weight=0.2,
        source=source,
    )
    assert target.net_exposure == pytest.approx(0.8)
    assert target.gross_exposure == pytest.approx(1.6)

    with pytest.raises(ValueError, match=r"sum\(weights\)"):
        PortfolioTarget(asof=now, weights={a: 0.5}, cash_weight=0.4, source=source)


def test_risk_gate_never_silently_rewrites_target(now, assets, snapshot):
    a, b = assets
    target = PortfolioTarget(
        asof=now,
        weights={a: 0.8, b: 0.2},
        cash_weight=0.0,
        source=ModelRef("optimizer", "1"),
    )
    state = PortfolioState(now, "USD", 1000.0)
    gate = StaticRiskGate(max_gross_exposure=1.0, max_abs_weight=0.6)
    decision = gate.assess(target, state, snapshot)

    assert decision.status is RiskStatus.REQUIRE_RESOLVE
    assert any(v.code == "MAX_ABS_WEIGHT" for v in decision.violations)
    assert target.weights[a] == pytest.approx(0.8)  # unchanged


def test_risk_gate_approves_valid_target(now, assets, snapshot):
    a, b = assets
    target = PortfolioTarget(
        asof=now,
        weights={a: 0.5, b: 0.5},
        cash_weight=0.0,
        source=ModelRef("optimizer", "1"),
    )
    decision = StaticRiskGate(max_gross_exposure=1.0, max_abs_weight=0.5).assess(
        target, PortfolioState(now, "USD", 1000), snapshot
    )
    assert decision.status is RiskStatus.APPROVE
    assert decision.violations == ()

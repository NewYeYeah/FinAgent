from __future__ import annotations

from datetime import UTC, datetime

from finagent.brokers.mt5 import (
    MT5CapabilityProbeReport,
    MT5HistoryCapability,
    MT5P0AcceptancePolicy,
    MT5SpreadSample,
    MT5SymbolSpec,
    MT5TerminalCapability,
    assess_mt5_p0,
)


def _utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 31, hour, minute, tzinfo=UTC)


def _symbol(
    name: str,
    *,
    visible: bool = True,
    trade_mode: int = 4,
) -> MT5SymbolSpec:
    return MT5SymbolSpec(
        symbol=name,
        path=f"Nasdaq\\Stock\\{name}",
        visible=visible,
        trade_mode=trade_mode,
        trade_calc_mode=32,
        digits=2,
        point=0.01,
        tick_size=0.01,
        tick_value=0.01,
        contract_size=1.0,
        volume_min=1.0,
        volume_max=1_000_000.0,
        volume_step=1.0,
        margin_initial=0.0,
        margin_maintenance=0.0,
        swap_mode=0,
        swap_long=0.0,
        swap_short=0.0,
        filling_mode=1,
        order_mode=127,
        currency_base="USD",
        currency_profit="USD",
        currency_margin="USD",
    )


def _history(name: str, *, m1: int = 120, ticks: int = 50) -> MT5HistoryCapability:
    return MT5HistoryCapability(
        symbol=name,
        requested_bar_start=_utc(13, 30),
        requested_bar_end=_utc(20, 0),
        m1_bar_count=m1,
        m1_first_at=_utc(13, 30) if m1 else None,
        m1_last_at=_utc(15, 29) if m1 else None,
        requested_tick_start=_utc(13, 30),
        requested_tick_end=_utc(14, 30),
        tick_count=ticks,
        tick_first_at=_utc(13, 30) if ticks else None,
        tick_last_at=_utc(14, 29) if ticks else None,
    )


def _spread(name: str) -> MT5SpreadSample:
    return MT5SpreadSample(
        symbol=name,
        sampled_at=_utc(20, 1),
        bid=100.0,
        ask=100.05,
        last=100.02,
        point=0.01,
    )


def _report(
    *,
    symbols: tuple[MT5SymbolSpec, ...] | None = None,
    history: tuple[MT5HistoryCapability, ...] | None = None,
    spreads: tuple[MT5SpreadSample, ...] | None = None,
    trade_allowed: bool = False,
    package_version: str = "5.0.6147",
) -> MT5CapabilityProbeReport:
    names = ("MSFT", "NVDA")
    return MT5CapabilityProbeReport(
        terminal=MT5TerminalCapability(
            package_version=package_version,
            terminal_version="500/6140/21 Aug 2026",
            terminal_build=6140,
            terminal_name="MetaTrader 5",
            terminal_company="MetaQuotes Ltd.",
            connected=True,
            trade_allowed=trade_allowed,
            tradeapi_disabled=False,
            broker_server="MetaQuotes-Demo",
            broker_company="MetaQuotes Ltd.",
            account_currency="USD",
        ),
        symbols=symbols if symbols is not None else tuple(_symbol(name) for name in names),
        history=history if history is not None else tuple(_history(name) for name in names),
        spread_samples=spreads if spreads is not None else tuple(_spread(name) for name in names),
        probed_at=_utc(20, 2),
    )


def test_acceptance_can_pass_read_only_probe_when_trading_toggle_is_off() -> None:
    policy = MT5P0AcceptancePolicy(representative_symbols=("MSFT", "NVDA"))
    assessment = assess_mt5_p0(_report(trade_allowed=False), policy)

    assert assessment.accepted is True
    assert assessment.blockers == ()
    assert assessment.limitations == ("terminal:automated_trading_not_allowed",)
    assert assessment.probe_id.startswith("mt5-capability-probe-")
    assert assessment.assessment_id.startswith("mt5-p0-assessment-")


def test_inventory_only_report_fails_history_and_spread_gate() -> None:
    policy = MT5P0AcceptancePolicy(representative_symbols=("MSFT", "NVDA"))
    assessment = assess_mt5_p0(_report(history=(), spreads=()), policy)

    assert assessment.accepted is False
    assert "history:MSFT:m1_missing" in assessment.blockers
    assert "history:MSFT:ticks_missing" in assessment.blockers
    assert "spread:MSFT:missing" in assessment.blockers
    assert "history:NVDA:m1_missing" in assessment.blockers
    assert "spread:NVDA:missing" in assessment.blockers


def test_acceptance_fails_closed_on_visibility_and_trade_mode() -> None:
    policy = MT5P0AcceptancePolicy(representative_symbols=("MSFT", "NVDA"))
    report = _report(
        symbols=(
            _symbol("MSFT", visible=False),
            _symbol("NVDA", trade_mode=0),
        )
    )
    assessment = assess_mt5_p0(report, policy)

    assert assessment.accepted is False
    assert "symbol:MSFT:not_visible" in assessment.blockers
    assert "symbol:NVDA:not_tradable" in assessment.blockers


def test_acceptance_fails_closed_on_package_version_drift() -> None:
    policy = MT5P0AcceptancePolicy(representative_symbols=("MSFT", "NVDA"))
    assessment = assess_mt5_p0(_report(package_version="5.0.9999"), policy)

    assert assessment.accepted is False
    assert any(
        blocker.startswith("terminal:package_version_mismatch:")
        for blocker in assessment.blockers
    )


def test_policy_normalizes_duplicate_representative_symbols() -> None:
    policy = MT5P0AcceptancePolicy(
        representative_symbols=(" MSFT ", "NVDA", "MSFT", ""),
    )
    same = MT5P0AcceptancePolicy(representative_symbols=("MSFT", "NVDA"))

    assert policy.representative_symbols == ("MSFT", "NVDA")
    assert policy.policy_id == same.policy_id

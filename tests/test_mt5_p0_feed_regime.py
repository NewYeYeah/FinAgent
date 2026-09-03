from __future__ import annotations

from datetime import UTC, datetime

import pytest

from finagent.brokers.mt5 import (
    FX_ENGINEERING_FIXTURE,
    METAQUOTES_DELAYED_US_EQUITY,
    MT5CapabilityProbeReport,
    MT5SymbolSpec,
    MT5TerminalCapability,
    build_mt5_feed_regime_evidence,
    build_mt5_feed_regime_report,
)


def _utc(hour: int = 12) -> datetime:
    return datetime(2026, 9, 3, hour, tzinfo=UTC)


def _symbol(name: str, *, visible: bool = True) -> MT5SymbolSpec:
    return MT5SymbolSpec(
        symbol=name,
        path=f"Test\\{name}",
        visible=visible,
        trade_mode=4,
        trade_calc_mode=32,
        digits=5 if "USD" in name else 2,
        point=0.00001 if "USD" in name else 0.01,
        tick_size=0.00001 if "USD" in name else 0.01,
        tick_value=1.0,
        contract_size=100_000.0 if "USD" in name else 1.0,
        volume_min=0.01 if "USD" in name else 1.0,
        volume_max=1000.0,
        volume_step=0.01 if "USD" in name else 1.0,
        margin_initial=0.0,
        margin_maintenance=0.0,
        swap_mode=0,
        swap_long=0.0,
        swap_short=0.0,
        filling_mode=1,
        order_mode=127,
        currency_base="EUR" if name == "EURUSD" else "USD",
        currency_profit="USD",
        currency_margin="USD",
    )


def _report(
    *symbols: MT5SymbolSpec,
    broker_server: str = "MetaQuotes-Demo",
) -> MT5CapabilityProbeReport:
    return MT5CapabilityProbeReport(
        terminal=MT5TerminalCapability(
            package_version="5.0.6147",
            terminal_version="500/6147/27 Aug 2026",
            terminal_build=6147,
            terminal_name="MetaTrader 5",
            terminal_company="MetaQuotes Ltd.",
            connected=True,
            trade_allowed=False,
            tradeapi_disabled=False,
            broker_server=broker_server,
            broker_company="MetaQuotes Ltd.",
            account_currency="USD",
        ),
        symbols=tuple(symbols),
        history=(),
        spread_samples=(),
        probed_at=_utc(),
    )


def _raw(
    name: str,
    *,
    visible: bool = True,
    subscription_delay: bool | None = False,
    include_optional_fields: bool = True,
) -> dict[str, object]:
    row: dict[str, object] = {
        "name": name,
        "visible": visible,
    }
    if subscription_delay is not None:
        row["subscription_delay"] = subscription_delay
    if include_optional_fields:
        row.update(
            {
                "chart_mode": 0,
                "trade_exemode": 2,
                "ticks_bookdepth": 10,
            }
        )
    return row


def test_feed_fingerprint_preserves_explicit_fields_without_promoting_authority() -> None:
    spec = _symbol("MSFT")
    evidence = build_mt5_feed_regime_evidence(
        broker_server="MetaQuotes-Demo",
        capability_probe_id="mt5-capability-probe-example",
        symbol_spec=spec,
        raw_symbol_info=_raw("MSFT", subscription_delay=True),
        feed_lane=METAQUOTES_DELAYED_US_EQUITY,
        observed_at=_utc(),
    )

    assert evidence.symbol_spec_id == spec.spec_id
    assert evidence.subscription_delay is True
    assert evidence.chart_mode == 0
    assert evidence.trade_exemode == 2
    assert evidence.ticks_bookdepth == 10
    assert evidence.unknown_fields == ()
    payload = evidence.to_dict()
    assert payload["scope"] == "mt5_feed_regime_diagnostic_only"
    for field_name in (
        "stage_exit_authority",
        "research_universe_authority",
        "us_i0_authority",
        "mt5_d0_authority",
        "us_d3_authority",
        "paper_authority",
        "execution_authority",
        "live_market_data_authority",
        "live_executable_spread_authority",
    ):
        assert payload[field_name] is False

    # Feed hardening is deliberately additive; the accepted v1 symbol spec identity
    # does not gain feed/subscription fields.
    assert "subscription_delay" not in spec.to_dict()
    assert "feed_lane" not in spec.to_dict()


def test_missing_feed_fields_remain_unknown_and_are_never_inferred() -> None:
    spec = _symbol("EURUSD")
    evidence = build_mt5_feed_regime_evidence(
        broker_server="MetaQuotes-Demo",
        capability_probe_id="mt5-capability-probe-example",
        symbol_spec=spec,
        raw_symbol_info=_raw(
            "EURUSD",
            subscription_delay=None,
            include_optional_fields=False,
        ),
        feed_lane=FX_ENGINEERING_FIXTURE,
        observed_at=_utc(),
    )

    assert evidence.subscription_delay is None
    assert evidence.chart_mode is None
    assert evidence.trade_exemode is None
    assert evidence.ticks_bookdepth is None
    assert evidence.unknown_fields == (
        "subscription_delay",
        "chart_mode",
        "trade_exemode",
        "ticks_bookdepth",
    )
    assert "subscription_delay:unavailable_not_inferred" in evidence.limitations


def test_hidden_symbol_never_turns_subscription_delay_value_into_evidence() -> None:
    spec = _symbol("MSFT", visible=False)
    evidence = build_mt5_feed_regime_evidence(
        broker_server="MetaQuotes-Demo",
        capability_probe_id="mt5-capability-probe-example",
        symbol_spec=spec,
        raw_symbol_info=_raw("MSFT", visible=False, subscription_delay=True),
        feed_lane=METAQUOTES_DELAYED_US_EQUITY,
        observed_at=_utc(),
    )

    assert evidence.subscription_delay is None
    assert "subscription_delay:unavailable_symbol_not_visible" in evidence.limitations


def test_feed_lane_is_explicit_and_changes_identity_for_same_raw_symbol() -> None:
    spec = _symbol("EURUSD")
    kwargs = {
        "broker_server": "MetaQuotes-Demo",
        "capability_probe_id": "mt5-capability-probe-example",
        "symbol_spec": spec,
        "raw_symbol_info": _raw("EURUSD"),
        "observed_at": _utc(),
    }
    fx = build_mt5_feed_regime_evidence(feed_lane=FX_ENGINEERING_FIXTURE, **kwargs)
    delayed = build_mt5_feed_regime_evidence(
        feed_lane=METAQUOTES_DELAYED_US_EQUITY,
        **kwargs,
    )

    assert fx.feed_lane == FX_ENGINEERING_FIXTURE
    assert delayed.feed_lane == METAQUOTES_DELAYED_US_EQUITY
    assert fx.evidence_id != delayed.evidence_id


def test_broker_server_identity_changes_feed_evidence_identity() -> None:
    spec = _symbol("MSFT")
    common = {
        "capability_probe_id": "mt5-capability-probe-example",
        "symbol_spec": spec,
        "raw_symbol_info": _raw("MSFT", subscription_delay=True),
        "feed_lane": METAQUOTES_DELAYED_US_EQUITY,
        "observed_at": _utc(),
    }
    metaquotes = build_mt5_feed_regime_evidence(
        broker_server="MetaQuotes-Demo",
        **common,
    )
    target = build_mt5_feed_regime_evidence(
        broker_server="TargetBroker-Demo",
        **common,
    )

    assert metaquotes.evidence_id != target.evidence_id


def test_report_is_diagnostic_only_and_records_missing_requested_symbol() -> None:
    report = _report(_symbol("EURUSD"))
    feed_report = build_mt5_feed_regime_report(
        report,
        (_raw("EURUSD"),),
        ("EURUSD", "GBPUSD"),
        feed_lane=FX_ENGINEERING_FIXTURE,
    )

    assert feed_report.complete_for_diagnostic is False
    assert tuple(item.symbol for item in feed_report.evidence) == ("EURUSD",)
    assert feed_report.issues[0].symbol == "GBPUSD"
    assert feed_report.issues[0].reasons == (
        "missing_symbol_spec",
        "missing_raw_inventory",
    )
    payload = feed_report.to_dict()
    assert payload["us_d3_authority"] is False
    assert payload["research_universe_authority"] is False


def test_report_fails_closed_on_duplicate_raw_inventory_symbol() -> None:
    report = _report(_symbol("MSFT"))
    feed_report = build_mt5_feed_regime_report(
        report,
        (
            _raw("MSFT", subscription_delay=True),
            _raw("MSFT", subscription_delay=True),
        ),
        ("MSFT",),
        feed_lane=METAQUOTES_DELAYED_US_EQUITY,
    )

    assert feed_report.complete_for_diagnostic is False
    assert feed_report.evidence == ()
    assert feed_report.issues[0].reasons == ("duplicate_raw_inventory_symbol",)


def test_report_records_visibility_drift_instead_of_rebinding_spec_identity() -> None:
    report = _report(_symbol("MSFT", visible=True))
    feed_report = build_mt5_feed_regime_report(
        report,
        (_raw("MSFT", visible=False, subscription_delay=True),),
        ("MSFT",),
        feed_lane=METAQUOTES_DELAYED_US_EQUITY,
    )

    assert feed_report.evidence == ()
    assert feed_report.issues[0].reasons[0].startswith("invalid_feed_fingerprint:")
    assert "visibility" in feed_report.issues[0].reasons[0]


def test_unsupported_lane_is_rejected_instead_of_guessed() -> None:
    spec = _symbol("EURUSD")
    with pytest.raises(ValueError, match="unsupported MT5 feed regime lane"):
        build_mt5_feed_regime_evidence(
            broker_server="MetaQuotes-Demo",
            capability_probe_id="mt5-capability-probe-example",
            symbol_spec=spec,
            raw_symbol_info=_raw("EURUSD"),
            feed_lane="auto_detect",
            observed_at=_utc(),
        )

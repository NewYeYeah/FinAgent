from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from finagent.brokers.mt5.capabilities import (
    MT5CapabilityProbeReport,
    MT5TerminalCapability,
)
from finagent.brokers.mt5.clock import (
    MT5BrokerClockEvidence,
    MT5BrokerClockObservation,
    build_mt5_broker_clock_evidence,
)
from finagent.brokers.mt5.feed_regime import (
    FX_ENGINEERING_FIXTURE,
    METAQUOTES_DELAYED_US_EQUITY,
)
from finagent.brokers.mt5.realtime_adapter import (
    MT5RealtimeAdapterPolicy,
    MT5RealtimeMarketAdapter,
)
from finagent.realtime.projections import RealtimeProjector

NOW = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
OFFSET = 3 * 60 * 60
SERVER = "MetaQuotes-Demo"


def _raw_msc(normalized: datetime) -> int:
    return int((normalized + timedelta(seconds=OFFSET)).timestamp() * 1000)


def _clock(server: str = SERVER) -> MT5BrokerClockEvidence:
    observations = tuple(
        MT5BrokerClockObservation(
            symbol=symbol,
            raw_broker_time_msc=_raw_msc(NOW),
            retrieved_at_utc=NOW,
            bid=1.0 + index * 0.1,
            ask=1.0001 + index * 0.1,
        )
        for index, symbol in enumerate(("EURUSD", "GBPUSD", "USDJPY"))
    )
    evidence = build_mt5_broker_clock_evidence(server, observations, generated_at=NOW)
    assert evidence.passed
    return evidence


def _capability(*, server: str = SERVER, connected: bool = True) -> MT5CapabilityProbeReport:
    terminal = MT5TerminalCapability(
        package_version="5.0.6147",
        terminal_version="5.0",
        terminal_build=6147,
        terminal_name="MetaTrader 5",
        terminal_company="MetaQuotes Ltd.",
        connected=connected,
        trade_allowed=False,
        tradeapi_disabled=True,
        broker_server=server,
        broker_company="MetaQuotes Ltd.",
        account_currency="USD",
    )
    return MT5CapabilityProbeReport(
        terminal=terminal,
        symbols=(),
        history=(),
        spread_samples=(),
        probed_at=NOW,
        symbol_group="fixture",
    )


def _adapter(*, lane: str = FX_ENGINEERING_FIXTURE) -> MT5RealtimeMarketAdapter:
    return MT5RealtimeMarketAdapter(
        MT5RealtimeAdapterPolicy(
            broker_server=SERVER,
            feed_lane=lane,
        ),
        _clock(),
    )


def test_quote_observation_uses_broker_clock_normalization_and_explicit_feed_lane() -> None:
    adapter = _adapter()
    tick_time = NOW - timedelta(seconds=2)
    event = adapter.quote_event(
        "EURUSD",
        {
            "time_msc": _raw_msc(tick_time),
            "bid": 1.1000,
            "ask": 1.1001,
            "last": 0.0,
            "volume": 0,
        },
        received_at=NOW,
    )
    assert event.event_time == tick_time
    assert event.received_at == NOW
    assert event.latency_seconds == pytest.approx(2.0)
    assert event.bid == pytest.approx(1.1000)
    assert event.ask == pytest.approx(1.1001)
    assert event.last == 0.0
    assert adapter.policy.feed_lane == FX_ENGINEERING_FIXTURE
    assert adapter.policy.to_dict()["feed_lane_inferred"] is False


def test_repolling_same_mt5_tick_at_later_receive_time_is_a_new_poll_observation() -> None:
    adapter = _adapter()
    raw = {
        "time_msc": _raw_msc(NOW - timedelta(seconds=1)),
        "bid": 1.1,
        "ask": 1.1001,
        "last": 0.0,
    }
    first = adapter.quote_event("EURUSD", raw, received_at=NOW)
    second = adapter.quote_event(
        "EURUSD",
        raw,
        received_at=NOW + timedelta(seconds=1),
    )
    assert first.event_time == second.event_time
    assert first.source_event_id != second.source_event_id
    assert first.event_id != second.event_id

    projector = RealtimeProjector()
    assert projector.apply(first)
    assert projector.apply(second)
    assert projector.snapshot().out_of_order_event_count == 0


def test_identical_observation_input_is_content_stable_across_fresh_adapter_instances() -> None:
    raw = {
        "time_msc": _raw_msc(NOW - timedelta(seconds=1)),
        "bid": 1.1,
        "ask": 1.1001,
        "last": 0.0,
    }
    first = _adapter().quote_event("EURUSD", raw, received_at=NOW)
    second = _adapter().quote_event("EURUSD", raw, received_at=NOW)
    assert first.to_dict() == second.to_dict()
    assert first.event_id == second.event_id
    assert first.source_event_id == second.source_event_id


class _IndexOnlyRate:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def __getitem__(self, key: str) -> object:
        return self._values[key]


def test_m1_bar_adapter_accepts_numpy_like_index_records_and_tick_volume_zero() -> None:
    adapter = _adapter()
    bar_time = NOW - timedelta(minutes=1)
    rate = _IndexOnlyRate(
        {
            "time": int((bar_time + timedelta(seconds=OFFSET)).timestamp()),
            "open": 1.1000,
            "high": 1.1004,
            "low": 1.0998,
            "close": 1.1002,
            "tick_volume": 0,
        }
    )
    event = adapter.bar_event(
        "EURUSD",
        rate,
        received_at=NOW,
        complete=True,
    )
    assert event.event_time == bar_time
    assert event.interval_seconds == 60
    assert event.volume == 0.0
    assert event.complete is True


def test_feed_lane_is_explicit_and_never_inferred_from_us_ticker() -> None:
    policy = MT5RealtimeAdapterPolicy(
        broker_server=SERVER,
        feed_lane=METAQUOTES_DELAYED_US_EQUITY,
    )
    assert policy.feed_lane == METAQUOTES_DELAYED_US_EQUITY
    with pytest.raises(ValueError, match="unsupported MT5 feed regime"):
        MT5RealtimeAdapterPolicy(
            broker_server=SERVER,
            feed_lane="infer-from-symbol-name",
        )


def test_adapter_rejects_failed_clock_or_broker_server_drift() -> None:
    failed_clock = MT5BrokerClockEvidence(
        broker_server=SERVER,
        policy=_clock().policy,
        observations=(),
        inferred_offset_seconds=None,
        generated_at=NOW,
    )
    assert not failed_clock.passed
    with pytest.raises(ValueError, match="passing broker-clock"):
        MT5RealtimeMarketAdapter(
            MT5RealtimeAdapterPolicy(
                broker_server=SERVER,
                feed_lane=FX_ENGINEERING_FIXTURE,
            ),
            failed_clock,
        )

    with pytest.raises(ValueError, match="broker-server/clock mismatch"):
        MT5RealtimeMarketAdapter(
            MT5RealtimeAdapterPolicy(
                broker_server="Other-Demo",
                feed_lane=FX_ENGINEERING_FIXTURE,
            ),
            _clock(),
        )


def test_connection_event_and_report_preserve_read_only_no_authority_boundary() -> None:
    adapter = _adapter()
    capability = _capability()
    connection = adapter.connection_event(capability, observed_at=NOW)
    quote = adapter.quote_event(
        "EURUSD",
        {
            "time_msc": _raw_msc(NOW - timedelta(seconds=1)),
            "bid": 1.1,
            "ask": 1.1001,
            "last": 0.0,
        },
        received_at=NOW,
    )
    report = adapter.build_report(
        capability,
        (connection, quote),
        generated_at=NOW,
    )
    assert report.passed
    payload = report.to_dict()
    assert payload["implementation_ready_for_mt5_m1_acceptance"] is True
    assert payload["read_only"] is True
    assert payload["symbol_select_used"] is False
    assert payload["order_send_used"] is False
    assert payload["us_market_source_authority"] is False
    assert payload["live_market_data_authority"] is False
    assert payload["broker_account_authority"] is False
    assert payload["execution_authority"] is False
    assert payload["paper_authority"] is False
    assert payload["status_authority"] is False
    assert payload["stage_exit_authority"] is False
    assert payload["live_capital_authority"] is False


def test_disconnected_terminal_creates_connection_event_but_blocks_adapter_report() -> None:
    adapter = _adapter()
    capability = _capability(connected=False)
    connection = adapter.connection_event(capability, observed_at=NOW)
    report = adapter.build_report(
        capability,
        (connection,),
        generated_at=NOW,
    )
    assert not report.passed
    assert "terminal:not_connected" in report.blockers


def test_capability_server_drift_fails_before_report_materialization() -> None:
    adapter = _adapter()
    with pytest.raises(ValueError, match="capability broker-server mismatch"):
        adapter.connection_event(_capability(server="Other-Demo"), observed_at=NOW)

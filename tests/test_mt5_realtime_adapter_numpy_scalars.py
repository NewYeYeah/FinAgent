from __future__ import annotations

from datetime import UTC, datetime, timedelta

from finagent.brokers.mt5.clock import (
    MT5BrokerClockObservation,
    build_mt5_broker_clock_evidence,
)
from finagent.brokers.mt5.feed_regime import FX_ENGINEERING_FIXTURE
from finagent.brokers.mt5.realtime_adapter import (
    MT5RealtimeAdapterPolicy,
    MT5RealtimeMarketAdapter,
)

NOW = datetime(2026, 9, 3, 6, 0, tzinfo=UTC)
OFFSET = 3 * 60 * 60


class _NumpyLikeScalar:
    def __init__(self, value: int | float) -> None:
        self._value = value

    def item(self) -> int | float:
        return self._value


class _IndexRow:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = values

    def __getitem__(self, key: str) -> object:
        return self._values[key]


def _raw_msc(normalized: datetime) -> int:
    return int((normalized + timedelta(seconds=OFFSET)).timestamp() * 1000)


def _adapter() -> MT5RealtimeMarketAdapter:
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
    clock = build_mt5_broker_clock_evidence(
        "MetaQuotes-Demo",
        observations,
        generated_at=NOW,
    )
    assert clock.passed
    return MT5RealtimeMarketAdapter(
        MT5RealtimeAdapterPolicy(
            broker_server="MetaQuotes-Demo",
            feed_lane=FX_ENGINEERING_FIXTURE,
        ),
        clock,
    )


def test_quote_and_bar_accept_numpy_like_item_scalars() -> None:
    adapter = _adapter()
    quote_time = NOW - timedelta(seconds=1)
    tick = _IndexRow(
        {
            "time_msc": _NumpyLikeScalar(_raw_msc(quote_time)),
            "bid": _NumpyLikeScalar(1.1),
            "ask": _NumpyLikeScalar(1.1001),
            "last": _NumpyLikeScalar(0.0),
        }
    )
    quote = adapter.quote_event("EURUSD", tick, received_at=NOW)
    assert quote.event_time == quote_time
    assert quote.bid == 1.1
    assert quote.last == 0.0

    bar_time = NOW - timedelta(minutes=2)
    rate = _IndexRow(
        {
            "time": _NumpyLikeScalar(
                int((bar_time + timedelta(seconds=OFFSET)).timestamp())
            ),
            "open": _NumpyLikeScalar(1.1),
            "high": _NumpyLikeScalar(1.2),
            "low": _NumpyLikeScalar(1.0),
            "close": _NumpyLikeScalar(1.15),
            "tick_volume": _NumpyLikeScalar(0),
        }
    )
    bar = adapter.bar_event(
        "EURUSD",
        rate,
        received_at=NOW,
        complete=True,
    )
    assert bar.event_time == bar_time
    assert bar.volume == 0.0

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

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


def test_quote_and_bar_accept_real_numpy_scalar_rows() -> None:
    adapter = _adapter()
    quote_time = NOW - timedelta(seconds=1)
    tick = _IndexRow(
        {
            "time_msc": np.int64(_raw_msc(quote_time)),
            "bid": np.float64(1.1),
            "ask": np.float64(1.1001),
            "last": np.float64(0.0),
        }
    )
    quote = adapter.quote_event("EURUSD", tick, received_at=NOW)
    assert quote.event_time == quote_time
    assert quote.bid == 1.1
    assert quote.last == 0.0

    bar_time = NOW - timedelta(minutes=2)
    rate = _IndexRow(
        {
            "time": np.int64(
                int((bar_time + timedelta(seconds=OFFSET)).timestamp())
            ),
            "open": np.float64(1.1),
            "high": np.float64(1.2),
            "low": np.float64(1.0),
            "close": np.float64(1.15),
            "tick_volume": np.int64(0),
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

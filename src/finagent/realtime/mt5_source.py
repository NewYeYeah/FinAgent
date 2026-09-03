from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

from finagent.brokers.mt5.client import MT5ReadOnlyClientProtocol
from finagent.realtime.events import CanonicalRealtimeEvent, QuoteEvent, RealtimeEventKind
from finagent.realtime.sources import FeedTimingProfile, MarketDataSubscription

SleepCallable = Callable[[float], Awaitable[None]]
ClockCallable = Callable[[], datetime]


class MT5QuoteAdapterProtocol(Protocol):
    def quote_event(
        self,
        symbol: str,
        tick: object,
        *,
        received_at: datetime,
    ) -> QuoteEvent: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MT5RealtimeSource:
    """Expose read-only MT5 polling through the provider-neutral source contract.

    This wrapper deliberately owns no symbol-selection or order surface. Feed timing
    classification is supplied explicitly by evidence/configuration rather than inferred
    from a ticker or from one poll result.
    """

    def __init__(
        self,
        client: MT5ReadOnlyClientProtocol,
        adapter: MT5QuoteAdapterProtocol,
        *,
        timing_profile: FeedTimingProfile,
        poll_interval_seconds: float = 1.0,
        sleeper: SleepCallable = asyncio.sleep,
        clock: ClockCallable = _utc_now,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._client = client
        self._adapter = adapter
        self._timing_profile = timing_profile
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._sleeper = sleeper
        self._clock = clock

    @property
    def timing_profile(self) -> FeedTimingProfile:
        return self._timing_profile

    async def subscribe(
        self,
        subscription: MarketDataSubscription,
    ) -> object:
        if subscription.start is not None or subscription.end is not None:
            raise ValueError("live MT5 source does not accept historical start/end bounds")
        if subscription.event_kinds != (RealtimeEventKind.QUOTE,):
            raise ValueError("MT5 realtime source v1 supports QUOTE subscriptions only")
        emitted = 0
        self._client.initialize()
        try:
            while True:
                for symbol in subscription.symbols:
                    tick = self._client.symbol_info_tick(symbol)
                    event: CanonicalRealtimeEvent = self._adapter.quote_event(
                        symbol,
                        tick,
                        received_at=self._clock(),
                    )
                    yield event
                    emitted += 1
                    if (
                        subscription.maximum_events is not None
                        and emitted >= subscription.maximum_events
                    ):
                        return
                await self._sleeper(self._poll_interval_seconds)
        finally:
            self._client.shutdown()

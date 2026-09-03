from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from finagent.data.minute_store.execution import (
    DEFAULT_DUCKDB_EXECUTION_POLICY,
    DuckDBExecutionPolicy,
)
from finagent.data.minute_store.parquet_store import DuckDBParquetMinuteStore
from finagent.data.minute_store.streaming import iter_plan_rows
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.realtime.events import BarEvent, CanonicalRealtimeEvent, RealtimeEventKind
from finagent.realtime.sources import (
    FeedTimingClass,
    FeedTimingProfile,
    MarketDataSubscription,
    ReplayPacingMode,
)

SleepCallable = Callable[[float], Awaitable[None]]


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    return float(value)


class DatabaseReplaySource:
    """Pace admitted U.S. minute rows through the canonical realtime event contract.

    The historical source remains truthful: OHLCV rows become only ``BarEvent`` values.
    ``event_time`` remains the historical bar start. ``received_at`` is a deterministic
    replay delivery clock based on source ``available_at`` plus the timing-profile delay.
    Actual wall-clock sleeping controls pace but is deliberately excluded from event identity.
    """

    def __init__(
        self,
        store: DuckDBParquetMinuteStore,
        *,
        timing_profile: FeedTimingProfile | None = None,
        execution_policy: DuckDBExecutionPolicy = DEFAULT_DUCKDB_EXECUTION_POLICY,
        temp_directory: str | Path | None = None,
        batch_size: int = 4096,
        sleeper: SleepCallable = asyncio.sleep,
    ) -> None:
        if not 1 <= batch_size <= 100_000:
            raise ValueError("batch_size must be in 1..100000")
        default_profile = FeedTimingProfile(
            source_id=f"database.replay:{store.manifest.manifest_id}",
            timing_class=FeedTimingClass.REPLAY,
            progressing=True,
            observed_delay_seconds=0.0,
            freshness_policy_id="database_replay_available_at_v1",
        )
        self._store = store
        self._timing_profile = timing_profile or default_profile
        self._execution_policy = execution_policy
        self._temp_directory = temp_directory
        self._batch_size = batch_size
        self._sleeper = sleeper
        self._step_permits = asyncio.Semaphore(0)

    @property
    def timing_profile(self) -> FeedTimingProfile:
        return self._timing_profile

    def advance(self, count: int = 1) -> None:
        if count < 1:
            raise ValueError("step advance count must be >= 1")
        for _ in range(count):
            self._step_permits.release()

    async def _pace(
        self,
        mode: ReplayPacingMode,
        speed: float,
        previous_delivery_at: datetime | None,
        delivery_at: datetime,
    ) -> None:
        if mode is ReplayPacingMode.STEP:
            await self._step_permits.acquire()
            return
        if previous_delivery_at is None or mode is ReplayPacingMode.FAST:
            return
        delta_seconds = max((delivery_at - previous_delivery_at).total_seconds(), 0.0)
        if mode is ReplayPacingMode.REALTIME:
            sleep_seconds = delta_seconds
        elif mode is ReplayPacingMode.ACCELERATED:
            sleep_seconds = delta_seconds / speed
        else:  # pragma: no cover - enum exhaustiveness guard
            raise ValueError(f"unsupported replay pacing mode: {mode}")
        if sleep_seconds > 0:
            await self._sleeper(sleep_seconds)

    def _query(self, subscription: MarketDataSubscription) -> MarketDataQuery:
        if subscription.start is None or subscription.end is None:
            raise ValueError("database replay requires bounded subscription start/end")
        if subscription.event_kinds != (RealtimeEventKind.BAR,):
            raise ValueError("database replay v1 supports BAR subscriptions only")
        if subscription.interval_seconds != 60:
            raise ValueError("database replay v1 supports source-native 60-second bars only")
        return MarketDataQuery(
            market_id=self._store.manifest.market_id,
            assets=subscription.symbols,
            start=subscription.start,
            end=subscription.end,
            interval=BarInterval.MINUTE_1,
            fields=tuple(MarketDataField),
            session_policy=SessionPolicy.ALL_OBSERVED,
            adjustment_policy=ResearchPriceBasis.RAW,
            availability_policy=AvailabilityPolicy.AVAILABLE_AT,
        )

    def _event(
        self,
        *,
        plan_id: str,
        sequence: int,
        row: dict[str, object],
    ) -> BarEvent:
        symbol = str(row.get("research_asset_id", "")).strip()
        if not symbol:
            raise ValueError("database replay row is missing research_asset_id")
        event_time = _aware(row.get("event_time"), "event_time")
        available_at = _aware(row.get("available_at"), "available_at")
        if available_at < event_time:
            raise ValueError("database replay available_at cannot precede event_time")
        source_delay = self._timing_profile.observed_delay_seconds or 0.0
        received_at = available_at + timedelta(seconds=source_delay)
        values = {
            "open": _number(row.get("open"), "open"),
            "high": _number(row.get("high"), "high"),
            "low": _number(row.get("low"), "low"),
            "close": _number(row.get("close"), "close"),
            "volume": _number(row.get("volume"), "volume"),
        }
        source_event_id = _canonical_hash(
            {
                "plan_id": plan_id,
                "symbol": symbol,
                "event_time": event_time.isoformat(),
                "available_at": available_at.isoformat(),
                **values,
            },
            prefix="database-replay-observation",
        )
        return BarEvent(
            source=self._timing_profile.source_id,
            source_event_id=source_event_id,
            event_time=event_time,
            received_at=received_at,
            sequence=sequence,
            symbol=symbol,
            interval_seconds=60,
            open=values["open"],
            high=values["high"],
            low=values["low"],
            close=values["close"],
            volume=values["volume"],
            complete=True,
        )

    async def subscribe(
        self,
        subscription: MarketDataSubscription,
    ) -> object:
        query = self._query(subscription)
        plan = self._store.plan(query)
        previous_delivery_at: datetime | None = None
        emitted = 0
        sequence = 0
        for row in iter_plan_rows(
            plan,
            batch_size=self._batch_size,
            policy=self._execution_policy,
            temp_directory=self._temp_directory,
        ):
            event = self._event(plan_id=plan.plan_id, sequence=sequence, row=row)
            await self._pace(
                subscription.pacing_mode,
                subscription.speed,
                previous_delivery_at,
                event.received_at,
            )
            yield event
            emitted += 1
            sequence += 1
            previous_delivery_at = event.received_at
            if subscription.maximum_events is not None and emitted >= subscription.maximum_events:
                return

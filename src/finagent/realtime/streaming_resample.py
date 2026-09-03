from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from finagent.data.minute_transform import ResamplingSpec
from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.realtime.events import BarEvent, CanonicalRealtimeEvent

_SUPPORTED_INTERVALS = (
    BarInterval.MINUTE_5,
    BarInterval.MINUTE_15,
    BarInterval.MINUTE_30,
)


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class StreamingResampledBar:
    bar: BarEvent
    available_at: datetime
    session_id: str
    session_open: datetime
    session_close: datetime
    bar_index: int
    observed_minute_count: int
    expected_minute_count: int
    coverage_ratio: float
    is_half_day: bool
    resampling_spec_id: str
    source_event_ids: tuple[str, ...]
    schema_version: str = "finagent.streaming-resampled-bar.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "available_at", _aware(self.available_at, "available_at"))
        object.__setattr__(self, "session_open", _aware(self.session_open, "session_open"))
        object.__setattr__(self, "session_close", _aware(self.session_close, "session_close"))
        if self.available_at <= self.bar.event_time:
            raise ValueError("resampled available_at must be later than event_time")
        if not self.session_id.strip() or not self.resampling_spec_id.strip():
            raise ValueError("session_id and resampling_spec_id must be non-empty")
        if self.bar_index < 0:
            raise ValueError("bar_index must be >= 0")
        if self.expected_minute_count <= 0:
            raise ValueError("expected_minute_count must be positive")
        if not 0 < self.observed_minute_count <= self.expected_minute_count:
            raise ValueError("observed_minute_count must be in 1..expected_minute_count")
        expected_ratio = self.observed_minute_count / self.expected_minute_count
        if abs(self.coverage_ratio - expected_ratio) > 1e-12:
            raise ValueError("coverage_ratio does not match observed/expected minute counts")
        if (
            self.bar.complete
            and self.observed_minute_count != self.expected_minute_count
        ):
            raise ValueError("complete resampled bar requires full minute coverage")
        if len(self.source_event_ids) != self.observed_minute_count:
            raise ValueError("source_event_ids must bind every observed minute")
        if len(self.source_event_ids) != len(set(self.source_event_ids)):
            raise ValueError("source_event_ids must be unique")

    @property
    def resampled_bar_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="streaming-resampled-bar")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "bar": self.bar.to_dict(),
            "available_at": self.available_at.isoformat(),
            "session_id": self.session_id,
            "session_open": self.session_open.isoformat(),
            "session_close": self.session_close.isoformat(),
            "bar_index": self.bar_index,
            "observed_minute_count": self.observed_minute_count,
            "expected_minute_count": self.expected_minute_count,
            "coverage_ratio": self.coverage_ratio,
            "is_half_day": self.is_half_day,
            "resampling_spec_id": self.resampling_spec_id,
            "source_event_ids": list(self.source_event_ids),
            "engineering_only": True,
            "research_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["resampled_bar_id"] = self.resampled_bar_id
        return payload


@dataclass(slots=True)
class _BucketState:
    symbol: str
    session: TradingSession
    session_id: str
    spec: ResamplingSpec
    bar_index: int
    bucket_start: datetime
    bucket_end: datetime
    minute_events: dict[int, BarEvent] = field(default_factory=dict)
    all_source_complete: bool = True


class StreamingBarAggregator:
    """Incrementally reproduce the accepted US-D2 session-open resampling semantics.

    Only source-native 60-second ``BarEvent`` values participate. Quotes and other event
    kinds pass through the outer runtime but are intentionally ignored here. Regular-session
    classification uses the frozen ``TradingCalendarEvidence`` rather than provider-specific
    session assumptions.
    """

    def __init__(
        self,
        calendar: TradingCalendarEvidence,
        *,
        intervals: tuple[BarInterval, ...] = _SUPPORTED_INTERVALS,
    ) -> None:
        if not intervals:
            raise ValueError("streaming resampler requires at least one interval")
        if any(item not in _SUPPORTED_INTERVALS for item in intervals):
            raise ValueError("streaming resampling v1 supports only 5m, 15m and 30m")
        if len(intervals) != len(set(intervals)):
            raise ValueError("streaming resampling intervals must be unique")
        self._calendar = calendar
        self._zone = ZoneInfo(calendar.timezone)
        self._specs = tuple(
            ResamplingSpec(calendar_id=calendar.calendar_id, target_interval=item)
            for item in sorted(intervals, key=lambda value: value.minutes or 0)
        )
        self._active: dict[tuple[str, str], _BucketState] = {}
        self._seen_input: dict[tuple[str, datetime], str] = {}
        self._last_regular_time: dict[str, datetime] = {}
        self._sequence = 0

    @property
    def calendar(self) -> TradingCalendarEvidence:
        return self._calendar

    @property
    def specs(self) -> tuple[ResamplingSpec, ...]:
        return self._specs

    def _session(self, event: BarEvent) -> TradingSession | None:
        session = self._calendar.session(event.event_time.astimezone(self._zone).date())
        if session is None:
            return None
        if not session.open_at <= event.event_time < session.close_at:
            return None
        return session

    @staticmethod
    def _minute_offset(event: BarEvent, session: TradingSession) -> int:
        seconds = (event.event_time - session.open_at).total_seconds()
        if seconds < 0 or seconds >= session.regular_minutes * 60:
            raise ValueError("regular-session bar lies outside materialized session bounds")
        quotient, remainder = divmod(int(seconds), 60)
        if remainder != 0 or abs(seconds - int(seconds)) > 1e-9:
            raise ValueError("source 1m bar must align exactly to a session minute boundary")
        return quotient

    def _new_state(
        self,
        event: BarEvent,
        session: TradingSession,
        spec: ResamplingSpec,
        minute_offset: int,
    ) -> _BucketState:
        if session.regular_minutes % spec.interval_minutes != 0:
            raise ValueError(
                f"session duration {session.regular_minutes} is not divisible by "
                f"{spec.interval_minutes} minutes"
            )
        bar_index = minute_offset // spec.interval_minutes
        bucket_start = session.open_at + timedelta(minutes=bar_index * spec.interval_minutes)
        bucket_end = bucket_start + timedelta(minutes=spec.interval_minutes)
        return _BucketState(
            symbol=event.symbol,
            session=session,
            session_id=f"{self._calendar.market_id}:{session.session_date.isoformat()}",
            spec=spec,
            bar_index=bar_index,
            bucket_start=bucket_start,
            bucket_end=bucket_end,
        )

    def _finish(
        self,
        state: _BucketState,
        *,
        detected_at: datetime,
    ) -> StreamingResampledBar:
        ordered = tuple(state.minute_events[index] for index in sorted(state.minute_events))
        if not ordered:
            raise RuntimeError("cannot finish an empty streaming resample bucket")
        expected_offsets = tuple(
            range(
                state.bar_index * state.spec.interval_minutes,
                (state.bar_index + 1) * state.spec.interval_minutes,
            )
        )
        observed_offsets = tuple(sorted(state.minute_events))
        exact_coverage = observed_offsets == expected_offsets
        complete = exact_coverage and state.all_source_complete
        received_at = max(
            _aware(detected_at, "detected_at"),
            max(item.received_at for item in ordered),
        )
        source_event_ids = tuple(item.event_id for item in ordered)
        source_event_id = _canonical_hash(
            {
                "resampling_spec_id": state.spec.spec_id,
                "calendar_id": self._calendar.calendar_id,
                "session_id": state.session_id,
                "symbol": state.symbol,
                "bar_index": state.bar_index,
                "bucket_start": state.bucket_start.isoformat(),
                "source_event_ids": list(source_event_ids),
            },
            prefix="streaming-resample-observation",
        )
        bar = BarEvent(
            source=f"stream.resample:{state.spec.spec_id}",
            source_event_id=source_event_id,
            event_time=state.bucket_start,
            received_at=received_at,
            sequence=self._sequence,
            symbol=state.symbol,
            interval_seconds=state.spec.interval_minutes * 60,
            open=ordered[0].open,
            high=max(item.high for item in ordered),
            low=min(item.low for item in ordered),
            close=ordered[-1].close,
            volume=sum(item.volume for item in ordered),
            complete=complete,
        )
        self._sequence += 1
        return StreamingResampledBar(
            bar=bar,
            available_at=state.bucket_end,
            session_id=state.session_id,
            session_open=state.session.open_at,
            session_close=state.session.close_at,
            bar_index=state.bar_index,
            observed_minute_count=len(ordered),
            expected_minute_count=state.spec.interval_minutes,
            coverage_ratio=len(ordered) / state.spec.interval_minutes,
            is_half_day=state.session.is_half_day,
            resampling_spec_id=state.spec.spec_id,
            source_event_ids=source_event_ids,
        )

    def on_event(self, event: CanonicalRealtimeEvent) -> tuple[StreamingResampledBar, ...]:
        if not isinstance(event, BarEvent) or event.interval_seconds != 60:
            return ()
        session = self._session(event)
        if session is None:
            return ()

        input_key = (event.symbol, event.event_time)
        existing_input_id = self._seen_input.get(input_key)
        if existing_input_id is not None:
            if existing_input_id == event.event_id:
                return ()
            raise ValueError("conflicting source 1m bar identity for one symbol/event_time")

        previous_time = self._last_regular_time.get(event.symbol)
        if previous_time is not None and event.event_time < previous_time:
            raise ValueError("streaming feature input is out of order for one symbol")
        self._seen_input[input_key] = event.event_id
        self._last_regular_time[event.symbol] = event.event_time
        minute_offset = self._minute_offset(event, session)
        outputs: list[StreamingResampledBar] = []

        for spec in self._specs:
            key = (event.symbol, spec.target_interval.value)
            expected_state = self._new_state(event, session, spec, minute_offset)
            active = self._active.get(key)
            if active is not None and active.bucket_start != expected_state.bucket_start:
                if expected_state.bucket_start < active.bucket_start:
                    raise ValueError("streaming resample bucket regressed")
                outputs.append(self._finish(active, detected_at=event.received_at))
                del self._active[key]
                active = None
            if active is None:
                active = expected_state
                self._active[key] = active

            if minute_offset in active.minute_events:
                existing = active.minute_events[minute_offset]
                if existing.event_id != event.event_id:
                    raise ValueError("conflicting duplicate minute inside streaming resample bucket")
                continue
            active.minute_events[minute_offset] = event
            active.all_source_complete = active.all_source_complete and event.complete
            if len(active.minute_events) == spec.interval_minutes:
                outputs.append(self._finish(active, detected_at=event.received_at))
                del self._active[key]

        return tuple(outputs)

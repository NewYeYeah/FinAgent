from __future__ import annotations

import hashlib
import json
import math
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from finagent.realtime.events import CanonicalRealtimeEvent, RealtimeEventKind


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _text(value: str, field_name: str) -> str:
    rendered = value.strip()
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _aware_optional(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _non_negative_optional(value: float | None, field_name: str) -> float | None:
    if value is None:
        return None
    rendered = float(value)
    if not math.isfinite(rendered) or rendered < 0:
        raise ValueError(f"{field_name} must be non-negative and finite")
    return rendered


class FeedTimingClass(StrEnum):
    CURRENT = "CURRENT"
    DELAYED = "DELAYED"
    REPLAY = "REPLAY"
    UNKNOWN = "UNKNOWN"


class ReplayPacingMode(StrEnum):
    REALTIME = "REALTIME"
    ACCELERATED = "ACCELERATED"
    FAST = "FAST"
    STEP = "STEP"


@dataclass(frozen=True, slots=True)
class FeedTimingProfile:
    source_id: str
    timing_class: FeedTimingClass
    progressing: bool
    observed_delay_seconds: float | None = None
    latency_p50_seconds: float | None = None
    latency_p95_seconds: float | None = None
    jitter_seconds: float | None = None
    freshness_policy_id: str = "unbound_engineering_profile"
    measured_at: datetime | None = None
    schema_version: str = "finagent.feed-timing-profile.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        object.__setattr__(
            self,
            "freshness_policy_id",
            _text(self.freshness_policy_id, "freshness_policy_id"),
        )
        for field_name in (
            "observed_delay_seconds",
            "latency_p50_seconds",
            "latency_p95_seconds",
            "jitter_seconds",
        ):
            object.__setattr__(
                self,
                field_name,
                _non_negative_optional(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "measured_at", _aware_optional(self.measured_at, "measured_at"))
        if (
            self.timing_class is FeedTimingClass.DELAYED
            and (self.observed_delay_seconds is None or self.observed_delay_seconds <= 0)
        ):
            raise ValueError("DELAYED timing profile requires observed_delay_seconds > 0")
        if self.timing_class is FeedTimingClass.UNKNOWN and self.observed_delay_seconds is not None:
            raise ValueError("UNKNOWN timing profile cannot claim an observed source delay")
        if (
            self.latency_p50_seconds is not None
            and self.latency_p95_seconds is not None
            and self.latency_p95_seconds < self.latency_p50_seconds
        ):
            raise ValueError("latency_p95_seconds cannot be below latency_p50_seconds")

    @property
    def profile_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="feed-timing-profile")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "timing_class": self.timing_class.value,
            "progressing": self.progressing,
            "observed_delay_seconds": self.observed_delay_seconds,
            "latency_p50_seconds": self.latency_p50_seconds,
            "latency_p95_seconds": self.latency_p95_seconds,
            "jitter_seconds": self.jitter_seconds,
            "freshness_policy_id": self.freshness_policy_id,
            "measured_at": self.measured_at.isoformat() if self.measured_at is not None else None,
            "engineering_only": True,
            "market_data_authority": False,
            "execution_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["profile_id"] = self.profile_id
        return payload


@dataclass(frozen=True, slots=True)
class MarketDataSubscription:
    symbols: tuple[str, ...]
    event_kinds: tuple[RealtimeEventKind, ...]
    start: datetime | None = None
    end: datetime | None = None
    interval_seconds: int = 60
    pacing_mode: ReplayPacingMode = ReplayPacingMode.FAST
    speed: float = 1.0
    maximum_events: int | None = None
    schema_version: str = "finagent.market-data-subscription.v1"

    def __post_init__(self) -> None:
        symbols = tuple(sorted(_text(item, "symbol") for item in self.symbols))
        if not symbols:
            raise ValueError("market-data subscription requires at least one symbol")
        if len(symbols) != len(set(symbols)):
            raise ValueError("market-data subscription symbols must be unique")
        kinds = tuple(sorted(self.event_kinds, key=lambda item: item.value))
        if not kinds:
            raise ValueError("market-data subscription requires at least one event kind")
        if any(not isinstance(item, RealtimeEventKind) for item in kinds):
            raise TypeError("event_kinds must contain RealtimeEventKind values")
        if len(kinds) != len(set(kinds)):
            raise ValueError("market-data subscription event kinds must be unique")
        start = _aware_optional(self.start, "start")
        end = _aware_optional(self.end, "end")
        if (start is None) != (end is None):
            raise ValueError("subscription start/end must either both be set or both be omitted")
        if start is not None and end is not None and end <= start:
            raise ValueError("subscription end must be later than start")
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        speed = float(self.speed)
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("speed must be positive and finite")
        if self.maximum_events is not None and self.maximum_events < 1:
            raise ValueError("maximum_events must be >= 1 when supplied")
        object.__setattr__(self, "symbols", symbols)
        object.__setattr__(self, "event_kinds", kinds)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "speed", speed)

    @property
    def subscription_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="market-data-subscription")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "symbols": list(self.symbols),
            "event_kinds": [item.value for item in self.event_kinds],
            "start": self.start.isoformat() if self.start is not None else None,
            "end": self.end.isoformat() if self.end is not None else None,
            "interval_seconds": self.interval_seconds,
            "pacing_mode": self.pacing_mode.value,
            "speed": self.speed,
            "maximum_events": self.maximum_events,
        }
        if include_id:
            payload["subscription_id"] = self.subscription_id
        return payload


@dataclass(frozen=True, slots=True)
class StrategyFreshnessBudget:
    maximum_source_delay_seconds: float
    maximum_event_age_seconds: float
    allow_replay: bool = True
    allow_delayed: bool = False
    allow_unknown: bool = False
    require_progressing: bool = True
    schema_version: str = "finagent.strategy-freshness-budget.v1"

    def __post_init__(self) -> None:
        for field_name in ("maximum_source_delay_seconds", "maximum_event_age_seconds"):
            value = float(getattr(self, field_name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{field_name} must be non-negative and finite")
            object.__setattr__(self, field_name, value)

    @property
    def budget_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="strategy-freshness-budget")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "maximum_source_delay_seconds": self.maximum_source_delay_seconds,
            "maximum_event_age_seconds": self.maximum_event_age_seconds,
            "allow_replay": self.allow_replay,
            "allow_delayed": self.allow_delayed,
            "allow_unknown": self.allow_unknown,
            "require_progressing": self.require_progressing,
        }
        if include_id:
            payload["budget_id"] = self.budget_id
        return payload

    def assess(
        self,
        profile: FeedTimingProfile,
        event: CanonicalRealtimeEvent,
    ) -> DataAdmissibilityDecision:
        reasons: list[str] = []
        if self.require_progressing and not profile.progressing:
            reasons.append("source:not_progressing")
        if profile.timing_class is FeedTimingClass.REPLAY and not self.allow_replay:
            reasons.append("timing:replay_not_allowed")
        elif profile.timing_class is FeedTimingClass.DELAYED and not self.allow_delayed:
            reasons.append("timing:delayed_not_allowed")
        elif profile.timing_class is FeedTimingClass.UNKNOWN and not self.allow_unknown:
            reasons.append("timing:unknown_not_allowed")
        if (
            profile.observed_delay_seconds is not None
            and profile.observed_delay_seconds > self.maximum_source_delay_seconds
        ):
            reasons.append("freshness:source_delay_exceeded")
        event_age_seconds = max(event.latency_seconds, 0.0)
        if event_age_seconds > self.maximum_event_age_seconds:
            reasons.append("freshness:event_age_exceeded")
        return DataAdmissibilityDecision(
            allowed=not reasons,
            reasons=tuple(dict.fromkeys(reasons)),
            profile_id=profile.profile_id,
            event_id=event.event_id,
            source_delay_seconds=profile.observed_delay_seconds,
            event_age_seconds=event_age_seconds,
        )


@dataclass(frozen=True, slots=True)
class DataAdmissibilityDecision:
    allowed: bool
    reasons: tuple[str, ...]
    profile_id: str
    event_id: str
    source_delay_seconds: float | None
    event_age_seconds: float
    schema_version: str = "finagent.data-admissibility-decision.v1"

    def __post_init__(self) -> None:
        normalized = tuple(dict.fromkeys(_text(item, "reason") for item in self.reasons))
        if self.allowed and normalized:
            raise ValueError("allowed data decision cannot carry rejection reasons")
        if not self.allowed and not normalized:
            raise ValueError("rejected data decision requires at least one reason")
        object.__setattr__(self, "reasons", normalized)
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        object.__setattr__(self, "event_id", _text(self.event_id, "event_id"))
        object.__setattr__(
            self,
            "source_delay_seconds",
            _non_negative_optional(self.source_delay_seconds, "source_delay_seconds"),
        )
        age = float(self.event_age_seconds)
        if not math.isfinite(age) or age < 0:
            raise ValueError("event_age_seconds must be non-negative and finite")
        object.__setattr__(self, "event_age_seconds", age)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "profile_id": self.profile_id,
            "event_id": self.event_id,
            "source_delay_seconds": self.source_delay_seconds,
            "event_age_seconds": self.event_age_seconds,
        }


@runtime_checkable
class MarketDataSource(Protocol):
    @property
    def timing_profile(self) -> FeedTimingProfile: ...

    def subscribe(
        self,
        subscription: MarketDataSubscription,
    ) -> AsyncIterator[CanonicalRealtimeEvent]: ...

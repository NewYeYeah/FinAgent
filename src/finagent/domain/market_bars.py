from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from ._validation import require_aware_datetime, require_non_empty, require_non_negative, require_positive


class BarInterval(str, Enum):
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    MINUTE_30 = "30m"
    MINUTE_60 = "60m"
    DAY_1 = "1d"

    @property
    def minutes(self) -> int | None:
        return {
            BarInterval.MINUTE_1: 1,
            BarInterval.MINUTE_5: 5,
            BarInterval.MINUTE_15: 15,
            BarInterval.MINUTE_30: 30,
            BarInterval.MINUTE_60: 60,
            BarInterval.DAY_1: None,
        }[self]


class BarTimestampConvention(str, Enum):
    """Meaning of ``MarketBarRow.event_time``.

    ``available_at`` remains the PIT observation clock independently of this field.
    """

    BAR_START = "bar_start"
    BAR_END = "bar_end"
    SESSION_OPEN = "session_open"


class LabelHorizonMode(str, Enum):
    BAR_COUNT = "bar_count"
    TRADING_MINUTES = "trading_minutes"
    SAME_SESSION = "same_session"
    TRADING_DAYS = "trading_days"


@dataclass(frozen=True, slots=True)
class LabelHorizonPolicy:
    mode: LabelHorizonMode
    value: int = 1
    allow_cross_session: bool = False

    def __post_init__(self) -> None:
        if self.value < 1:
            raise ValueError("label horizon value must be >= 1")
        if self.mode is LabelHorizonMode.SAME_SESSION and self.allow_cross_session:
            raise ValueError("same-session horizon cannot allow cross-session labels")

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "value": self.value,
            "allow_cross_session": self.allow_cross_session,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> LabelHorizonPolicy:
        return cls(
            mode=LabelHorizonMode(str(raw["mode"])),
            value=int(raw.get("value", 1)),
            allow_cross_session=bool(raw.get("allow_cross_session", False)),
        )


@dataclass(frozen=True, slots=True)
class SessionSegment:
    name: str
    start: str
    end: str
    session_type: str = "regular"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_non_empty(self.name, "name"))
        object.__setattr__(
            self,
            "session_type",
            require_non_empty(self.session_type, "session_type").lower(),
        )
        start_minutes = self._clock_minutes(self.start, "start")
        end_minutes = self._clock_minutes(self.end, "end")
        if end_minutes <= start_minutes:
            raise ValueError("session segment end must be later than start")

    @staticmethod
    def _clock_minutes(value: str, field: str) -> int:
        pieces = value.split(":")
        if len(pieces) != 2:
            raise ValueError(f"{field} must use HH:MM")
        try:
            hour, minute = (int(piece) for piece in pieces)
        except ValueError as exc:
            raise ValueError(f"{field} must use HH:MM") from exc
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError(f"{field} must use a valid 24-hour clock")
        return hour * 60 + minute

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "start": self.start,
            "end": self.end,
            "session_type": self.session_type,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> SessionSegment:
        return cls(
            name=str(raw["name"]),
            start=str(raw["start"]),
            end=str(raw["end"]),
            session_type=str(raw.get("session_type", "regular")),
        )


@dataclass(frozen=True, slots=True)
class MarketSessionSpec:
    market_id: str
    timezone: str
    segments: tuple[SessionSegment, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "market_id", require_non_empty(self.market_id, "market_id"))
        object.__setattr__(self, "timezone", require_non_empty(self.timezone, "timezone"))
        if not self.segments:
            raise ValueError("market session spec requires at least one segment")
        names = tuple(segment.name for segment in self.segments)
        if len(names) != len(set(names)):
            raise ValueError("market session segment names must be unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "market_id": self.market_id,
            "timezone": self.timezone,
            "segments": [segment.to_dict() for segment in self.segments],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> MarketSessionSpec:
        raw_segments = raw.get("segments")
        if not isinstance(raw_segments, list):
            raise TypeError("market session segments must be an array")
        return cls(
            market_id=str(raw["market_id"]),
            timezone=str(raw["timezone"]),
            segments=tuple(
                SessionSegment.from_dict(segment)
                for segment in raw_segments
                if isinstance(segment, dict)
            ),
        )


@dataclass(frozen=True, slots=True)
class MarketBarRow:
    asset: str
    session_date: date
    event_time: datetime
    available_at: datetime
    interval: BarInterval
    open: float
    high: float
    low: float
    close: float
    volume: float
    session_id: str
    session_type: str
    source: str
    data_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", require_non_empty(self.asset, "asset"))
        event_time = require_aware_datetime(self.event_time, "event_time")
        available_at = require_aware_datetime(self.available_at, "available_at")
        if available_at < event_time:
            raise ValueError("market bar available_at cannot precede event_time")
        open_ = require_positive(self.open, "open")
        high = require_positive(self.high, "high")
        low = require_positive(self.low, "low")
        close = require_positive(self.close, "close")
        volume = require_non_negative(self.volume, "volume")
        if high < max(open_, low, close):
            raise ValueError("market bar high must be >= open, low and close")
        if low > min(open_, high, close):
            raise ValueError("market bar low must be <= open, high and close")
        if any(not math.isfinite(value) for value in (open_, high, low, close, volume)):
            raise ValueError("market bar numeric values must be finite")
        object.__setattr__(self, "event_time", event_time)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "open", open_)
        object.__setattr__(self, "high", high)
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "close", close)
        object.__setattr__(self, "volume", volume)
        object.__setattr__(self, "session_id", require_non_empty(self.session_id, "session_id"))
        object.__setattr__(
            self,
            "session_type",
            require_non_empty(self.session_type, "session_type").lower(),
        )
        object.__setattr__(self, "source", require_non_empty(self.source, "source"))
        object.__setattr__(
            self,
            "data_version",
            require_non_empty(self.data_version, "data_version"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "asset": self.asset,
            "session_date": self.session_date.isoformat(),
            "event_time": self.event_time.isoformat(),
            "available_at": self.available_at.isoformat(),
            "interval": self.interval.value,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "session_id": self.session_id,
            "session_type": self.session_type,
            "source": self.source,
            "data_version": self.data_version,
        }

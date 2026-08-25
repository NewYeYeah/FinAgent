from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from finagent.domain._validation import require_aware_datetime, require_non_empty


@dataclass(frozen=True, slots=True)
class TradingSessionCalendar:
    timezone_name: str = "UTC"
    open_time: time = time(9, 30)
    close_time: time = time(16, 0)
    weekdays: frozenset[int] = field(default_factory=lambda: frozenset(range(5)))
    holidays: frozenset[date] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        timezone_name = require_non_empty(self.timezone_name, "timezone_name")
        ZoneInfo(timezone_name)
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be after open_time")
        if not self.weekdays or any(day < 0 or day > 6 for day in self.weekdays):
            raise ValueError("weekdays must contain integers in [0, 6]")
        object.__setattr__(self, "timezone_name", timezone_name)

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    def is_session_day(self, day: date) -> bool:
        return day.weekday() in self.weekdays and day not in self.holidays

    def session_bounds(self, day: date) -> tuple[datetime, datetime]:
        if not self.is_session_day(day):
            raise ValueError(f"{day.isoformat()} is not a trading session")
        tz = self.timezone
        return (
            datetime.combine(day, self.open_time, tzinfo=tz),
            datetime.combine(day, self.close_time, tzinfo=tz),
        )

    def is_open(self, timestamp: datetime) -> bool:
        timestamp = require_aware_datetime(timestamp, "timestamp").astimezone(self.timezone)
        if not self.is_session_day(timestamp.date()):
            return False
        opened, closed = self.session_bounds(timestamp.date())
        return opened <= timestamp < closed

    def next_open(self, timestamp: datetime) -> datetime:
        timestamp = require_aware_datetime(timestamp, "timestamp").astimezone(self.timezone)
        day = timestamp.date()
        for offset in range(370):
            candidate = day + timedelta(days=offset)
            if not self.is_session_day(candidate):
                continue
            opened, _ = self.session_bounds(candidate)
            if opened >= timestamp:
                return opened
        raise RuntimeError("could not locate a trading session within one year")

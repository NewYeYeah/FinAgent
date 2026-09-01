from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ._validation import require_aware_datetime, require_non_empty


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class TradingSession:
    session_date: date
    open_at: datetime
    close_at: datetime
    pre_open_at: datetime | None = None
    post_close_at: datetime | None = None
    is_half_day: bool = False

    def __post_init__(self) -> None:
        open_at = require_aware_datetime(self.open_at, "open_at")
        close_at = require_aware_datetime(self.close_at, "close_at")
        if close_at <= open_at:
            raise ValueError("close_at must be later than open_at")
        pre_open_at = self.pre_open_at
        if pre_open_at is not None:
            pre_open_at = require_aware_datetime(pre_open_at, "pre_open_at")
            if pre_open_at > open_at:
                raise ValueError("pre_open_at cannot be later than open_at")
        post_close_at = self.post_close_at
        if post_close_at is not None:
            post_close_at = require_aware_datetime(post_close_at, "post_close_at")
            if post_close_at < close_at:
                raise ValueError("post_close_at cannot precede close_at")
        object.__setattr__(self, "open_at", open_at)
        object.__setattr__(self, "close_at", close_at)
        object.__setattr__(self, "pre_open_at", pre_open_at)
        object.__setattr__(self, "post_close_at", post_close_at)

    @property
    def regular_minutes(self) -> int:
        return int((self.close_at - self.open_at).total_seconds() // 60)

    def to_dict(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "open_at": self.open_at.isoformat(),
            "close_at": self.close_at.isoformat(),
            "pre_open_at": self.pre_open_at.isoformat() if self.pre_open_at else None,
            "post_close_at": self.post_close_at.isoformat() if self.post_close_at else None,
            "is_half_day": self.is_half_day,
        }


@dataclass(frozen=True, slots=True)
class TradingCalendarEvidence:
    market_id: str
    timezone: str
    source: str
    source_revision: str
    sessions: tuple[TradingSession, ...]
    regular_session_minutes: int = 390
    schema_version: str = "finagent.trading-calendar-evidence.v1"

    def __post_init__(self) -> None:
        market_id = require_non_empty(self.market_id, "market_id")
        timezone = require_non_empty(self.timezone, "timezone")
        source = require_non_empty(self.source, "source")
        source_revision = require_non_empty(self.source_revision, "source_revision")
        if self.regular_session_minutes <= 0:
            raise ValueError("regular_session_minutes must be positive")
        if not self.sessions:
            raise ValueError("trading calendar evidence requires at least one session")
        zone = ZoneInfo(timezone)
        ordered = tuple(sorted(self.sessions, key=lambda item: item.session_date))
        dates = tuple(item.session_date for item in ordered)
        if len(dates) != len(set(dates)):
            raise ValueError("trading calendar session dates must be unique")
        for session in ordered:
            local_open = session.open_at.astimezone(zone)
            local_close = session.close_at.astimezone(zone)
            if local_open.date() != session.session_date or local_close.date() != session.session_date:
                raise ValueError("session open/close must map to session_date in calendar timezone")
            if session.regular_minutes > self.regular_session_minutes:
                raise ValueError("session duration cannot exceed regular_session_minutes")
            expected_half_day = session.regular_minutes < self.regular_session_minutes
            if session.is_half_day != expected_half_day:
                raise ValueError("is_half_day must match the observed regular-session duration")
        object.__setattr__(self, "market_id", market_id)
        object.__setattr__(self, "timezone", timezone)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "source_revision", source_revision)
        object.__setattr__(self, "sessions", ordered)

    @property
    def coverage_start(self) -> date:
        return self.sessions[0].session_date

    @property
    def coverage_end(self) -> date:
        return self.sessions[-1].session_date

    @property
    def calendar_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "market_id": self.market_id,
            "timezone": self.timezone,
            "source": self.source,
            "source_revision": self.source_revision,
            "regular_session_minutes": self.regular_session_minutes,
            "sessions": [session.to_dict() for session in self.sessions],
        }
        return _canonical_hash(payload, prefix="trading-calendar")

    def session(self, session_date: date) -> TradingSession | None:
        return next((item for item in self.sessions if item.session_date == session_date), None)

    def require_session(self, session_date: date) -> TradingSession:
        session = self.session(session_date)
        if session is None:
            raise KeyError(f"{session_date.isoformat()} is not a materialized {self.market_id} session")
        return session

    def is_session(self, session_date: date) -> bool:
        return self.session(session_date) is not None

    def covers(self, session_date: date) -> bool:
        return self.coverage_start <= session_date <= self.coverage_end

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "calendar_id": self.calendar_id,
            "market_id": self.market_id,
            "timezone": self.timezone,
            "source": self.source,
            "source_revision": self.source_revision,
            "coverage_start": self.coverage_start.isoformat(),
            "coverage_end": self.coverage_end.isoformat(),
            "regular_session_minutes": self.regular_session_minutes,
            "sessions": [session.to_dict() for session in self.sessions],
        }

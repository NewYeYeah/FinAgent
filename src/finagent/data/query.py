from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from finagent.domain._validation import require_aware_datetime, require_non_empty
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


class MarketDataField(str, Enum):
    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    VOLUME = "volume"


class SessionPolicy(str, Enum):
    REGULAR = "regular"
    EXTENDED = "extended"
    ALL_OBSERVED = "all_observed"


@dataclass(frozen=True, slots=True)
class MarketDataQuery:
    market_id: str
    assets: tuple[str, ...]
    start: datetime
    end: datetime
    interval: BarInterval
    fields: tuple[MarketDataField, ...]
    session_policy: SessionPolicy
    adjustment_policy: ResearchPriceBasis
    availability_policy: AvailabilityPolicy = AvailabilityPolicy.AVAILABLE_AT
    schema_version: str = "finagent.market-data-query.v1"

    def __post_init__(self) -> None:
        market_id = require_non_empty(self.market_id, "market_id")
        assets = tuple(sorted(require_non_empty(item, "asset") for item in self.assets))
        if not assets:
            raise ValueError("market data query requires at least one asset")
        if len(assets) != len(set(assets)):
            raise ValueError("market data query assets must be unique")
        start = require_aware_datetime(self.start, "start")
        end = require_aware_datetime(self.end, "end")
        if end <= start:
            raise ValueError("market data query end must be later than start")
        if not isinstance(self.interval, BarInterval):
            raise TypeError("interval must be a BarInterval")
        if not isinstance(self.session_policy, SessionPolicy):
            raise TypeError("session_policy must be a SessionPolicy")
        if not isinstance(self.adjustment_policy, ResearchPriceBasis):
            raise TypeError("adjustment_policy must be a ResearchPriceBasis")
        if not isinstance(self.availability_policy, AvailabilityPolicy):
            raise TypeError("availability_policy must be an AvailabilityPolicy")
        fields = tuple(sorted(self.fields, key=lambda item: item.value))
        if not fields:
            raise ValueError("market data query requires at least one value field")
        if any(not isinstance(item, MarketDataField) for item in fields):
            raise TypeError("fields must contain only MarketDataField values")
        if len(fields) != len(set(fields)):
            raise ValueError("market data query fields must be unique")
        object.__setattr__(self, "market_id", market_id)
        object.__setattr__(self, "assets", assets)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "fields", fields)

    @property
    def query_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "market_id": self.market_id,
            "assets": list(self.assets),
            "start_inclusive": self.start.isoformat(),
            "end_exclusive": self.end.isoformat(),
            "interval": self.interval.value,
            "fields": [item.value for item in self.fields],
            "session_policy": self.session_policy.value,
            "adjustment_policy": self.adjustment_policy.value,
            "availability_policy": self.availability_policy.value,
        }
        return _canonical_hash(payload, prefix="market-data-query")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "query_id": self.query_id,
            "market_id": self.market_id,
            "assets": list(self.assets),
            "start_inclusive": self.start.isoformat(),
            "end_exclusive": self.end.isoformat(),
            "interval": self.interval.value,
            "fields": [item.value for item in self.fields],
            "session_policy": self.session_policy.value,
            "adjustment_policy": self.adjustment_policy.value,
            "availability_policy": self.availability_policy.value,
        }


@dataclass(frozen=True, slots=True)
class MarketDataView:
    query: MarketDataQuery
    adapter_id: str
    data_version: str
    lazy: bool = True
    estimated_rows: int | None = None
    schema_version: str = "finagent.market-data-view.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter_id", require_non_empty(self.adapter_id, "adapter_id"))
        object.__setattr__(
            self,
            "data_version",
            require_non_empty(self.data_version, "data_version"),
        )
        if not self.lazy:
            raise ValueError("US-C0 MarketDataView must remain lazy")
        if self.estimated_rows is not None and self.estimated_rows < 0:
            raise ValueError("estimated_rows must be >= 0")

    @property
    def view_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "query_id": self.query.query_id,
            "adapter_id": self.adapter_id,
            "data_version": self.data_version,
            "lazy": self.lazy,
            "estimated_rows": self.estimated_rows,
        }
        return _canonical_hash(payload, prefix="market-data-view")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "view_id": self.view_id,
            "query": self.query.to_dict(),
            "adapter_id": self.adapter_id,
            "data_version": self.data_version,
            "lazy": self.lazy,
            "estimated_rows": self.estimated_rows,
        }

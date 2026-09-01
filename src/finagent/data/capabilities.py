from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from finagent.domain._validation import require_non_empty
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval

from .query import MarketDataField, MarketDataQuery, SessionPolicy


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    """Capabilities actually implemented and tested by one FinAgent adapter.

    This contract is intentionally independent from provider/API capability declarations.
    A provider may advertise functionality that a particular FinAgent adapter has not
    implemented or certified yet.
    """

    adapter_id: str
    provider: str
    market_ids: frozenset[str]
    intervals: frozenset[BarInterval]
    fields: frozenset[MarketDataField]
    session_policies: frozenset[SessionPolicy]
    adjustment_policies: frozenset[ResearchPriceBasis]
    availability_policies: frozenset[AvailabilityPolicy]
    supports_corporate_actions: bool = False
    lazy_query: bool = True
    schema_version: str = "finagent.adapter-capabilities.v1"

    def __post_init__(self) -> None:
        adapter_id = require_non_empty(self.adapter_id, "adapter_id")
        provider = require_non_empty(self.provider, "provider").lower()
        market_ids = frozenset(require_non_empty(item, "market_id") for item in self.market_ids)
        if not market_ids:
            raise ValueError("adapter capabilities require at least one market")
        if not self.intervals:
            raise ValueError("adapter capabilities require at least one interval")
        if not self.fields:
            raise ValueError("adapter capabilities require at least one field")
        if not self.session_policies:
            raise ValueError("adapter capabilities require at least one session policy")
        if not self.adjustment_policies:
            raise ValueError("adapter capabilities require at least one adjustment policy")
        if not self.availability_policies:
            raise ValueError("adapter capabilities require at least one availability policy")
        object.__setattr__(self, "adapter_id", adapter_id)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "market_ids", market_ids)
        object.__setattr__(self, "intervals", frozenset(self.intervals))
        object.__setattr__(self, "fields", frozenset(self.fields))
        object.__setattr__(self, "session_policies", frozenset(self.session_policies))
        object.__setattr__(self, "adjustment_policies", frozenset(self.adjustment_policies))
        object.__setattr__(self, "availability_policies", frozenset(self.availability_policies))

    @property
    def capability_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "adapter_id": self.adapter_id,
            "provider": self.provider,
            "market_ids": sorted(self.market_ids),
            "intervals": sorted(item.value for item in self.intervals),
            "fields": sorted(item.value for item in self.fields),
            "session_policies": sorted(item.value for item in self.session_policies),
            "adjustment_policies": sorted(item.value for item in self.adjustment_policies),
            "availability_policies": sorted(item.value for item in self.availability_policies),
            "supports_corporate_actions": self.supports_corporate_actions,
            "lazy_query": self.lazy_query,
        }
        return _canonical_hash(payload, prefix="adapter-capabilities")

    def gaps(self, query: MarketDataQuery) -> tuple[str, ...]:
        gaps: list[str] = []
        if query.market_id not in self.market_ids:
            gaps.append(f"market:{query.market_id}")
        if query.interval not in self.intervals:
            gaps.append(f"interval:{query.interval.value}")
        for field in query.fields:
            if field not in self.fields:
                gaps.append(f"field:{field.value}")
        if query.session_policy not in self.session_policies:
            gaps.append(f"session_policy:{query.session_policy.value}")
        if query.adjustment_policy not in self.adjustment_policies:
            gaps.append(f"adjustment_policy:{query.adjustment_policy.value}")
        if query.availability_policy not in self.availability_policies:
            gaps.append(f"availability_policy:{query.availability_policy.value}")
        if not self.lazy_query:
            gaps.append("lazy_query")
        return tuple(gaps)

    def require(self, query: MarketDataQuery) -> None:
        gaps = self.gaps(query)
        if gaps:
            raise ValueError(
                f"adapter {self.adapter_id!r} cannot satisfy market-data query: "
                + ", ".join(gaps)
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capability_id": self.capability_id,
            "adapter_id": self.adapter_id,
            "provider": self.provider,
            "market_ids": sorted(self.market_ids),
            "intervals": sorted(item.value for item in self.intervals),
            "fields": sorted(item.value for item in self.fields),
            "session_policies": sorted(item.value for item in self.session_policies),
            "adjustment_policies": sorted(item.value for item in self.adjustment_policies),
            "availability_policies": sorted(item.value for item in self.availability_policies),
            "supports_corporate_actions": self.supports_corporate_actions,
            "lazy_query": self.lazy_query,
        }

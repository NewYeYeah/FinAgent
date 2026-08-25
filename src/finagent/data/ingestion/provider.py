from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from .base import MarketRegion


class DataFrequency(str, Enum):
    DAILY = "1d"
    MINUTE = "1m"
    SNAPSHOT = "snapshot"


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Machine-readable market-data capability declaration.

    Capability declarations are intentionally conservative. A provider being able to
    represent a market does not imply that it is suitable for every research study.
    """

    provider: str
    markets: frozenset[MarketRegion]
    historical_daily: bool = False
    historical_minute: bool = False
    realtime_snapshot: bool = False
    realtime_stream: bool = False
    fundamentals: bool = False
    macro: bool = False
    corporate_actions: bool = False
    pit_universe: bool = False
    delisted_history: bool = False
    alternative_data: bool = False
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        provider = self.provider.strip().lower()
        if not provider:
            raise ValueError("provider must be non-empty")
        if not self.markets:
            raise ValueError("markets cannot be empty")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "markets", frozenset(self.markets))
        object.__setattr__(self, "notes", tuple(str(item) for item in self.notes))


@dataclass(frozen=True, slots=True)
class ResearchDataRequirement:
    market: MarketRegion
    frequency: DataFrequency = DataFrequency.DAILY
    require_fundamentals: bool = False
    require_macro: bool = False
    require_corporate_actions: bool = False
    require_pit_universe: bool = False
    require_delisted_history: bool = False
    require_alternative_data: bool = False

    def gaps(self, capabilities: ProviderCapabilities) -> tuple[str, ...]:
        gaps: list[str] = []
        if self.market not in capabilities.markets:
            gaps.append(f"market:{self.market.value}")
        if self.frequency is DataFrequency.DAILY and not capabilities.historical_daily:
            gaps.append("historical_daily")
        elif self.frequency is DataFrequency.MINUTE and not capabilities.historical_minute:
            gaps.append("historical_minute")
        elif self.frequency is DataFrequency.SNAPSHOT and not capabilities.realtime_snapshot:
            gaps.append("realtime_snapshot")
        checks = (
            (self.require_fundamentals, capabilities.fundamentals, "fundamentals"),
            (self.require_macro, capabilities.macro, "macro"),
            (self.require_corporate_actions, capabilities.corporate_actions, "corporate_actions"),
            (self.require_pit_universe, capabilities.pit_universe, "pit_universe"),
            (self.require_delisted_history, capabilities.delisted_history, "delisted_history"),
            (self.require_alternative_data, capabilities.alternative_data, "alternative_data"),
        )
        gaps.extend(name for required, supported, name in checks if required and not supported)
        return tuple(gaps)

    def require(self, capabilities: ProviderCapabilities) -> None:
        gaps = self.gaps(capabilities)
        if gaps:
            raise ValueError(
                f"provider {capabilities.provider!r} does not satisfy research data requirements: "
                + ", ".join(gaps)
            )


@dataclass(frozen=True, slots=True)
class ProviderSymbolMap:
    """Explicit canonical-symbol to provider-symbol mapping.

    This is deliberately separate from AssetId identity. Provider-specific encodings
    such as AKShare's US-market codes must never leak into portfolio identity.
    """

    provider: str
    mappings: Mapping[str, str] = field(default_factory=dict)
    strict: bool = False

    def __post_init__(self) -> None:
        provider = self.provider.strip().lower()
        if not provider:
            raise ValueError("provider must be non-empty")
        normalized = {
            str(key).strip().upper(): str(value).strip()
            for key, value in self.mappings.items()
        }
        if any(not key or not value for key, value in normalized.items()):
            raise ValueError("symbol mappings cannot contain empty keys or values")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "mappings", MappingProxyType(normalized))

    def resolve(self, canonical_symbol: str) -> str:
        symbol = canonical_symbol.strip().upper()
        if symbol in self.mappings:
            return self.mappings[symbol]
        if self.strict:
            raise KeyError(f"no {self.provider} symbol mapping registered for {symbol!r}")
        return symbol


ALPACA_CAPABILITIES = ProviderCapabilities(
    provider="alpaca",
    markets=frozenset({MarketRegion.US_EQUITY}),
    historical_daily=True,
    historical_minute=True,
    realtime_snapshot=True,
    realtime_stream=True,
    notes=("US historical/realtime provider; entitlements depend on Alpaca account/feed",),
)

AKSHARE_CAPABILITIES = ProviderCapabilities(
    provider="akshare",
    markets=frozenset({MarketRegion.A_SHARE, MarketRegion.US_EQUITY}),
    historical_daily=True,
    historical_minute=True,
    realtime_snapshot=True,
    fundamentals=True,
    corporate_actions=True,
    notes=(
        "community/open-source aggregation; endpoint coverage and upstream stability are best-effort",
        "intended as development, smoke-test and cross-provider evidence by default",
    ),
)

HITHINK_CAPABILITIES = ProviderCapabilities(
    provider="hithink",
    markets=frozenset({MarketRegion.A_SHARE}),
    historical_daily=True,
    realtime_snapshot=True,
    fundamentals=True,
    corporate_actions=True,
    alternative_data=True,
    pit_universe=False,
    delisted_history=False,
    notes=(
        "official HiThink A-share API; public surface is daily/snapshot, not minute/tick/Level-2",
        "do not certify survivorship-bias-free individual-equity studies until delisted history exists",
    ),
)

TUSHARE_15000_CAPABILITIES = ProviderCapabilities(
    provider="tushare",
    markets=frozenset({MarketRegion.A_SHARE}),
    historical_daily=True,
    fundamentals=True,
    macro=True,
    alternative_data=True,
    notes=(
        "15,000-point baseline only; excludes separately paid realtime/minute/US entitlements",
        "kept as optional reference/fundamental provider rather than strategic market-data dependency",
    ),
)


def provider_capabilities(name: str) -> ProviderCapabilities:
    providers = {
        item.provider: item
        for item in (
            ALPACA_CAPABILITIES,
            AKSHARE_CAPABILITIES,
            HITHINK_CAPABILITIES,
            TUSHARE_15000_CAPABILITIES,
        )
    }
    key = name.strip().lower()
    try:
        return providers[key]
    except KeyError as exc:
        raise KeyError(f"unknown market-data provider {name!r}") from exc

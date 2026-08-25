from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from finagent.domain.assets import AssetType

from .base import MarketRegion


class DataCapability(str, Enum):
    HISTORICAL_DAILY = "historical_daily"
    HISTORICAL_MINUTE = "historical_minute"
    REALTIME_SNAPSHOT = "realtime_snapshot"
    REALTIME_STREAM = "realtime_stream"
    FUNDAMENTALS = "fundamentals"
    CORPORATE_ACTIONS = "corporate_actions"
    PIT_UNIVERSE = "pit_universe"
    DELISTED_HISTORY = "delisted_history"
    MACRO = "macro"
    ALTERNATIVE_DATA = "alternative_data"


class ProviderTier(str, Enum):
    DEVELOPMENT = "development"
    RESEARCH = "research"
    REFERENCE = "reference"


@dataclass(frozen=True, slots=True)
class ResearchDataRequirement:
    market: MarketRegion
    asset_types: frozenset[AssetType]
    capabilities: frozenset[DataCapability] = frozenset({DataCapability.HISTORICAL_DAILY})
    description: str = ""

    def __post_init__(self) -> None:
        if not self.asset_types:
            raise ValueError("asset_types cannot be empty")
        if not self.capabilities:
            raise ValueError("capabilities cannot be empty")


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    provider: str
    markets: frozenset[MarketRegion]
    asset_types: frozenset[AssetType]
    available: frozenset[DataCapability]
    implemented: frozenset[DataCapability]
    tier: ProviderTier = ProviderTier.RESEARCH
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        provider = self.provider.strip().lower()
        if not provider:
            raise ValueError("provider must be non-empty")
        if not self.implemented.issubset(self.available):
            raise ValueError("implemented capabilities must be a subset of available capabilities")
        object.__setattr__(self, "provider", provider)

    def supports(self, requirement: ResearchDataRequirement, *, implemented_only: bool = True) -> bool:
        return not self.requirement_errors(requirement, implemented_only=implemented_only)

    def requirement_errors(
        self,
        requirement: ResearchDataRequirement,
        *,
        implemented_only: bool = True,
    ) -> tuple[str, ...]:
        errors: list[str] = []
        if requirement.market not in self.markets:
            errors.append(f"market {requirement.market.value} is unsupported")
        unsupported_assets = requirement.asset_types - self.asset_types
        if unsupported_assets:
            errors.append(
                "asset types are unsupported: "
                + ", ".join(sorted(asset.value for asset in unsupported_assets))
            )
        surface = self.implemented if implemented_only else self.available
        missing = requirement.capabilities - surface
        if missing:
            errors.append(
                "capabilities are unavailable on the selected surface: "
                + ", ".join(sorted(item.value for item in missing))
            )
        return tuple(errors)

    def assert_supports(
        self,
        requirement: ResearchDataRequirement,
        *,
        implemented_only: bool = True,
    ) -> None:
        errors = self.requirement_errors(requirement, implemented_only=implemented_only)
        if errors:
            raise ValueError(f"provider {self.provider!r} cannot satisfy requirement: {'; '.join(errors)}")


@dataclass(frozen=True, slots=True)
class ProviderSymbolMap:
    provider: str
    symbols: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        provider = self.provider.strip().lower()
        if not provider:
            raise ValueError("provider must be non-empty")
        normalized = {
            str(canonical).strip().upper(): str(source).strip()
            for canonical, source in self.symbols.items()
        }
        if any(not key or not value for key, value in normalized.items()):
            raise ValueError("symbol mappings must use non-empty canonical and provider symbols")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "symbols", MappingProxyType(normalized))

    def resolve(self, canonical_symbol: str) -> str:
        canonical = canonical_symbol.strip().upper()
        if not canonical:
            raise ValueError("canonical_symbol must be non-empty")
        return self.symbols.get(canonical, canonical)


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    capabilities: ProviderCapabilities
    factory: Callable[[ProviderSymbolMap | None], object]


class ProviderRegistry:
    """Explicit provider catalog; selection never performs silent fallback."""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderDescriptor] = {}

    def register(self, descriptor: ProviderDescriptor) -> None:
        key = descriptor.capabilities.provider
        if key in self._providers:
            raise ValueError(f"provider {key!r} is already registered")
        self._providers[key] = descriptor

    def get(self, provider: str) -> ProviderDescriptor:
        key = provider.strip().lower()
        try:
            return self._providers[key]
        except KeyError as exc:
            raise KeyError(f"unknown market-data provider {provider!r}") from exc

    def create(self, provider: str, *, symbol_map: ProviderSymbolMap | None = None) -> object:
        return self.get(provider).factory(symbol_map)

    def list_capabilities(self) -> tuple[ProviderCapabilities, ...]:
        return tuple(self._providers[key].capabilities for key in sorted(self._providers))

    def candidates(
        self,
        requirement: ResearchDataRequirement,
        *,
        implemented_only: bool = True,
    ) -> tuple[ProviderCapabilities, ...]:
        return tuple(
            item
            for item in self.list_capabilities()
            if item.supports(requirement, implemented_only=implemented_only)
        )

from __future__ import annotations

from finagent.domain.assets import AssetType

from .akshare import AKShareMarketDataIngestor
from .alpaca import AlpacaMarketDataIngestor
from .base import MarketRegion
from .hithink import HiThinkMarketDataIngestor
from .providers import (
    DataCapability,
    ProviderCapabilities,
    ProviderDescriptor,
    ProviderRegistry,
    ProviderSymbolMap,
    ProviderTier,
)
from .tushare import TushareMarketDataIngestor


ALPACA_CAPABILITIES = ProviderCapabilities(
    provider="alpaca",
    markets=frozenset({MarketRegion.US_EQUITY}),
    asset_types=frozenset({AssetType.EQUITY, AssetType.ETF}),
    available=frozenset(
        {
            DataCapability.HISTORICAL_DAILY,
            DataCapability.HISTORICAL_MINUTE,
            DataCapability.REALTIME_SNAPSHOT,
            DataCapability.REALTIME_STREAM,
        }
    ),
    implemented=frozenset({DataCapability.HISTORICAL_DAILY}),
    tier=ProviderTier.RESEARCH,
    notes=("primary US-market provider", "realtime/minute vendor capability is not yet exposed by this adapter"),
)

TUSHARE_15K_CAPABILITIES = ProviderCapabilities(
    provider="tushare",
    markets=frozenset({MarketRegion.A_SHARE}),
    asset_types=frozenset({AssetType.EQUITY, AssetType.ETF}),
    available=frozenset(
        {
            DataCapability.HISTORICAL_DAILY,
            DataCapability.FUNDAMENTALS,
            DataCapability.MACRO,
            DataCapability.ALTERNATIVE_DATA,
        }
    ),
    implemented=frozenset({DataCapability.HISTORICAL_DAILY}),
    tier=ProviderTier.REFERENCE,
    notes=(
        "models the 15k-points/no-extra-paid-services boundary",
        "no minute/realtime/US-market capability is assumed",
    ),
)


def default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(
        ProviderDescriptor(
            ALPACA_CAPABILITIES,
            lambda _mapping=None: AlpacaMarketDataIngestor.from_environment(),
        )
    )
    registry.register(
        ProviderDescriptor(
            AKShareMarketDataIngestor.CAPABILITIES,
            lambda mapping=None: AKShareMarketDataIngestor.from_environment(symbol_map=mapping),
        )
    )
    registry.register(
        ProviderDescriptor(
            HiThinkMarketDataIngestor.CAPABILITIES,
            lambda _mapping=None: HiThinkMarketDataIngestor.from_environment(),
        )
    )
    registry.register(
        ProviderDescriptor(
            TUSHARE_15K_CAPABILITIES,
            lambda _mapping=None: TushareMarketDataIngestor.from_environment(),
        )
    )
    return registry


def create_provider(
    provider: str,
    *,
    symbol_map: ProviderSymbolMap | None = None,
):
    return default_provider_registry().create(provider, symbol_map=symbol_map)

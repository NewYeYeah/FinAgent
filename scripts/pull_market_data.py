#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tomllib
from datetime import date
from pathlib import Path

from finagent.data import (
    AKShareMarketDataIngestor,
    AlpacaMarketDataIngestor,
    HiThinkMarketDataIngestor,
    MarketDataPullRequest,
    MarketRegion,
    ProviderSymbolMap,
    TushareMarketDataIngestor,
    provider_capabilities,
)
from finagent.domain.assets import AssetType


def _date(value: object, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"market.{name} must use YYYY-MM-DD") from exc


def _load(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    market = payload.get("market")
    if not isinstance(market, dict):
        raise TypeError("configuration must contain a [market] table")
    return market


def _symbol_map(provider: str, values: dict[str, object]) -> ProviderSymbolMap:
    mappings = {
        str(key): str(value)
        for key, value in dict(values.get("provider_symbols", {})).items()
    }
    strict = bool(values.get("strict_provider_symbols", False))
    return ProviderSymbolMap(provider, mappings, strict=strict)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pull and normalize provider-neutral daily market bars for FinAgent studies."
    )
    parser.add_argument("config", type=Path, help="TOML market-study configuration")
    parser.add_argument("--output-dir", type=Path, help="override market.output_dir")
    parser.add_argument(
        "--show-capabilities",
        action="store_true",
        help="print the selected provider's declared capabilities before pulling",
    )
    args = parser.parse_args()

    values = _load(args.config)
    provider = str(values.get("provider", "")).strip().lower()
    capabilities = provider_capabilities(provider)
    request = MarketDataPullRequest(
        market=MarketRegion(str(values["region"])),
        symbols=tuple(str(item) for item in values["symbols"]),
        start=_date(values["start"], "start"),
        end=_date(values["end"], "end"),
        asset_type=AssetType(str(values.get("asset_type", "etf")).lower()),
        adjustment=str(values.get("adjustment", "raw")),
        feed=str(values.get("feed", "")),
        venue_overrides={
            str(key): str(value)
            for key, value in dict(values.get("venue_overrides", {})).items()
        },
        metadata={
            str(key): str(value) for key, value in dict(values.get("metadata", {})).items()
        },
    )
    if request.market not in capabilities.markets or not capabilities.historical_daily:
        raise ValueError(
            f"provider {provider!r} does not declare daily-history support for "
            f"{request.market.value!r}"
        )
    if args.show_capabilities:
        print(
            json.dumps(
                {
                    "provider": capabilities.provider,
                    "markets": sorted(item.value for item in capabilities.markets),
                    "historical_daily": capabilities.historical_daily,
                    "historical_minute": capabilities.historical_minute,
                    "realtime_snapshot": capabilities.realtime_snapshot,
                    "realtime_stream": capabilities.realtime_stream,
                    "fundamentals": capabilities.fundamentals,
                    "macro": capabilities.macro,
                    "corporate_actions": capabilities.corporate_actions,
                    "pit_universe": capabilities.pit_universe,
                    "delisted_history": capabilities.delisted_history,
                    "alternative_data": capabilities.alternative_data,
                    "notes": list(capabilities.notes),
                },
                indent=2,
                ensure_ascii=False,
            )
        )

    output_dir = args.output_dir or Path(str(values["output_dir"]))
    if provider == "hithink":
        ingestor = HiThinkMarketDataIngestor.from_environment()
    elif provider == "akshare":
        ingestor = AKShareMarketDataIngestor.from_environment(
            symbol_map=_symbol_map(provider, values)
        )
    elif provider == "tushare":
        ingestor = TushareMarketDataIngestor.from_environment()
    elif provider == "alpaca":
        ingestor = AlpacaMarketDataIngestor.from_environment()
    else:  # provider_capabilities() should already have rejected this branch.
        raise ValueError(f"unsupported market.provider {provider!r}")

    result = ingestor.materialize(request, output_dir)
    print(json.dumps(result.manifest.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

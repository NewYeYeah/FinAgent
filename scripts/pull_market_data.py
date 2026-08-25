#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tomllib
from datetime import date
from pathlib import Path

from finagent.data import (
    DataCapability,
    MarketDataPullRequest,
    MarketRegion,
    ProviderSymbolMap,
    ResearchDataRequirement,
    default_provider_registry,
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pull and normalize provider-governed daily bars for FinAgent studies."
    )
    parser.add_argument("config", type=Path, help="TOML market-study configuration")
    parser.add_argument("--output-dir", type=Path, help="override market.output_dir")
    args = parser.parse_args()

    values = _load(args.config)
    provider = str(values.get("provider", "")).strip().lower()
    asset_type = AssetType(str(values.get("asset_type", "etf")).lower())
    region = MarketRegion(str(values["region"]))
    provider_symbols = {
        str(key).upper(): str(value)
        for key, value in dict(values.get("provider_symbols", {})).items()
    }
    metadata = {
        str(key): str(value) for key, value in dict(values.get("metadata", {})).items()
    }
    metadata.update(
        {f"provider_symbol.{key}": value for key, value in sorted(provider_symbols.items())}
    )
    request = MarketDataPullRequest(
        market=region,
        symbols=tuple(str(item) for item in values["symbols"]),
        start=_date(values["start"], "start"),
        end=_date(values["end"], "end"),
        asset_type=asset_type,
        adjustment=str(values.get("adjustment", "raw")),
        feed=str(values.get("feed", "")),
        venue_overrides={
            str(key): str(value)
            for key, value in dict(values.get("venue_overrides", {})).items()
        },
        metadata=metadata,
    )
    output_dir = args.output_dir or Path(str(values["output_dir"]))
    symbol_map = ProviderSymbolMap(provider, provider_symbols)

    registry = default_provider_registry()
    descriptor = registry.get(provider)
    descriptor.capabilities.assert_supports(
        ResearchDataRequirement(
            market=region,
            asset_types=frozenset({asset_type}),
            capabilities=frozenset({DataCapability.HISTORICAL_DAILY}),
            description="historical daily market study",
        )
    )
    ingestor = registry.create(provider, symbol_map=symbol_map)
    materialize = getattr(ingestor, "materialize", None)
    if not callable(materialize):
        raise TypeError(f"provider {provider!r} does not expose materialize()")
    result = materialize(request, output_dir)
    print(json.dumps(result.manifest.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tomllib
from datetime import date
from pathlib import Path

from finagent.data import (
    AlpacaMarketDataIngestor,
    MarketDataPullRequest,
    MarketRegion,
    TushareMarketDataIngestor,
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
        description="Pull and normalize fixed-universe ETF bars for FinAgent M1 studies."
    )
    parser.add_argument("config", type=Path, help="TOML market-study configuration")
    parser.add_argument("--output-dir", type=Path, help="override market.output_dir")
    args = parser.parse_args()

    values = _load(args.config)
    provider = str(values.get("provider", "")).strip().lower()
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
    output_dir = args.output_dir or Path(str(values["output_dir"]))
    if provider == "tushare":
        ingestor = TushareMarketDataIngestor.from_environment()
    elif provider == "alpaca":
        ingestor = AlpacaMarketDataIngestor.from_environment()
    else:
        raise ValueError("market.provider must be 'tushare' or 'alpaca'")

    result = ingestor.materialize(request, output_dir)
    print(json.dumps(result.manifest.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

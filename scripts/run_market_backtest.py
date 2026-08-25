#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tomllib
from dataclasses import fields, replace
from datetime import timedelta
from pathlib import Path

from finagent.backtest import MarketStudyConfig, run_nested_market_study
from finagent.data import CSVPriceDataAdapter, read_normalized_csv
from finagent.data.ingestion.base import sha256_file


def _load(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    study = payload.get("study")
    if not isinstance(study, dict):
        raise TypeError("configuration must contain a [study] table")
    return study


def _manifest(path: Path, bars_path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("quality_passed"):
        raise ValueError("manifest does not record a passed quality gate")
    if payload.get("normalized_sha256") != sha256_file(bars_path):
        raise ValueError("bars CSV digest does not match manifest.normalized_sha256")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a fixed-universe ETF nested walk-forward market study."
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("--bars", type=Path, help="override study.bars_path")
    parser.add_argument("--manifest", type=Path, help="override study.manifest_path")
    parser.add_argument("--report", type=Path, help="override study.report_path")
    args = parser.parse_args()

    values = _load(args.config)
    bars_path = args.bars or Path(str(values["bars_path"]))
    manifest_path = args.manifest or Path(str(values["manifest_path"]))
    report_path = args.report or Path(str(values["report_path"]))
    manifest = _manifest(manifest_path, bars_path)
    data_version = str(manifest["data_version"])

    records = read_normalized_csv(bars_path)
    universe = tuple(sorted({record.asset for record in records}, key=lambda asset: asset.key))
    available = tuple(record.bar.available_at for record in records)
    start = min(available)
    end = max(available) + timedelta(microseconds=1)
    allowed = {field.name for field in fields(MarketStudyConfig)}
    config_values = {key: value for key, value in values.items() if key in allowed}
    if "candidate_names" in config_values:
        config_values["candidate_names"] = tuple(config_values["candidate_names"])
    config = MarketStudyConfig(**config_values)

    multipliers = tuple(float(value) for value in values.get("cost_multipliers", [1.0]))
    if not multipliers or any(value < 0 for value in multipliers):
        raise ValueError("study.cost_multipliers must be a non-empty list of non-negative values")
    scenarios = []
    for multiplier in multipliers:
        scenario_config = replace(
            config,
            commission_bps=config.commission_bps * multiplier,
            slippage_bps=config.slippage_bps * multiplier,
            impact_bps=config.impact_bps * multiplier,
        )
        result = run_nested_market_study(
            CSVPriceDataAdapter(bars_path, data_version=data_version),
            universe=universe,
            start=start,
            end=end,
            config=scenario_config,
        )
        scenarios.append({"cost_multiplier": multiplier, "result": result.to_dict()})

    payload = {
        "schema_version": "finagent.market-study.m1.v1",
        "manifest": str(manifest_path),
        "bars": str(bars_path),
        "data_version": data_version,
        "scenarios": scenarios,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tomllib
from dataclasses import fields
from datetime import timedelta
from pathlib import Path

import numpy as np

from finagent.agents import AgentTask
from finagent.agents.generated_features import SQLiteGeneratedFeatureStore
from finagent.agents.llm_feature import LLMFeatureGenerationPolicy, LLMFeatureGenerator
from finagent.agents.providers.openai import OpenAIResponsesProvider
from finagent.backtest import MarketStudyConfig
from finagent.data import CSVPriceDataAdapter, read_normalized_csv
from finagent.data.ingestion.base import MarketRegion, sha256_file
from finagent.data.ingestion.provider import (
    DataFrequency,
    ResearchDataRequirement,
    provider_capabilities,
)
from finagent.research import (
    AgentMarketResearchConfig,
    AgentMarketResearchRunner,
    LLMMarketFeatureCandidateGenerator,
    ResearchProgram,
    SQLiteAgentMarketResearchStore,
    SQLiteResearchProgramStore,
)


def _load(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    study = payload.get("agent_market_research")
    if not isinstance(study, dict):
        raise TypeError("configuration must contain [agent_market_research]")
    return study


def _manifest(path: Path, bars_path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("quality_passed"):
        raise ValueError("manifest does not record a passed quality gate")
    if payload.get("normalized_sha256") != sha256_file(bars_path):
        raise ValueError("bars CSV digest does not match manifest.normalized_sha256")
    return payload


def _market_config(values: dict[str, object]) -> MarketStudyConfig:
    allowed = {field.name for field in fields(MarketStudyConfig)}
    config_values = {key: value for key, value in values.items() if key in allowed}
    if "candidate_names" in config_values:
        # Candidate names belong to the legacy fixed-model study and are irrelevant
        # for agent-generated feature families.
        config_values.pop("candidate_names")
    return MarketStudyConfig(**config_values)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a bounded LLM feature family and evaluate it on immutable US-market "
            "historical data using nested selection, multiplicity control and deterministic portfolio execution."
        )
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("--bars", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    values = _load(args.config)
    bars_path = args.bars or Path(str(values["bars_path"]))
    manifest_path = args.manifest or Path(str(values["manifest_path"]))
    report_path = args.report or Path(str(values["report_path"]))
    manifest = _manifest(manifest_path, bars_path)
    data_version = str(manifest["data_version"])
    provider_name = str(values.get("provider", manifest.get("provider", "alpaca"))).strip().lower()
    capabilities = provider_capabilities(provider_name)

    market_value = str(values.get("market", "us_equity"))
    market = MarketRegion(market_value)
    requirement = ResearchDataRequirement(market=market, frequency=DataFrequency.DAILY)
    requirement.require(capabilities)

    records = read_normalized_csv(bars_path)
    universe = tuple(sorted({record.asset for record in records}, key=lambda asset: asset.key))
    available = tuple(record.bar.available_at for record in records)
    start = min(available)
    end = max(available) + timedelta(microseconds=1)
    adapter = CSVPriceDataAdapter(bars_path, data_version=data_version)

    approved_fields = tuple(str(value) for value in values.get("approved_input_fields", ()))
    if not approved_fields:
        raise ValueError("approved_input_fields must be configured")
    smoke_lookback = int(values.get("smoke_lookback", 64))
    if smoke_lookback < 2:
        raise ValueError("smoke_lookback must be >= 2")
    calendar = adapter.calendar(start, end, universe)
    if not calendar:
        raise ValueError("market dataset has no common calendar")
    smoke_window = adapter.feature_window(
        calendar[-1],
        (universe[0],),
        approved_fields,
        smoke_lookback,
    )
    smoke_inputs: dict[str, list[float | None]] = {}
    for feature_index, name in enumerate(smoke_window.feature_names):
        values_array = smoke_window.values[:, 0, feature_index]
        smoke_inputs[name] = [
            float(value) if np.isfinite(value) else None for value in values_array
        ]

    task_id = str(values.get("task_id", "us-etf-agent-research"))
    research_question = str(values["research_question"])
    program_id = str(values.get("program_id", f"program:{task_id}"))
    family_id = str(values.get("family_id", f"family:{task_id}:001"))
    family_alpha = float(values.get("family_alpha", 0.05))
    candidate_count = int(values.get("candidate_count", 4))
    model = str(values["llm_model"])

    state_dir = Path(str(values.get("state_dir", ".finagent/agent-market")))
    state_dir.mkdir(parents=True, exist_ok=True)
    feature_store = SQLiteGeneratedFeatureStore(state_dir / "generated_features.sqlite")
    program_store = SQLiteResearchProgramStore(state_dir / "research_programs.sqlite")
    evidence_store = SQLiteAgentMarketResearchStore(state_dir / "agent_market_research.sqlite")
    program_store.register(
        ResearchProgram(
            program_id=program_id,
            alpha_budget=float(values.get("program_alpha_budget", 0.05)),
            max_families=int(values.get("program_max_families", 4)),
            max_experiments=int(values.get("program_max_experiments", 16)),
            sealed_holdout_id=str(values.get("sealed_holdout_id", "")),
        )
    )

    task = AgentTask(
        task_id=task_id,
        objective=research_question,
        created_at=calendar[-1],
        metadata={
            "market": market.value,
            "provider": provider_name,
            "data_version": data_version,
            "universe": ",".join(asset.key for asset in universe),
        },
    )
    feature_generator = LLMFeatureGenerator(
        provider=OpenAIResponsesProvider(),
        policy=LLMFeatureGenerationPolicy(
            model=model,
            max_lookback=int(values.get("max_feature_lookback", 60)),
            max_output_tokens=int(values.get("max_output_tokens", 3500)),
        ),
        feature_store=feature_store,
    )
    candidate_generator = LLMMarketFeatureCandidateGenerator(
        feature_generator,
        max_candidates=int(values.get("max_candidates", 8)),
    )
    candidates = candidate_generator.generate(
        task=task,
        count=candidate_count,
        approved_input_fields=approved_fields,
        smoke_inputs=smoke_inputs,
    )

    market_config = _market_config(values)
    config = AgentMarketResearchConfig(
        max_candidates=int(values.get("max_candidates", 8)),
        family_alpha=family_alpha,
        selection_metric=str(values.get("selection_metric", "net_sharpe")),
        label_name=str(values.get("label_name", "forward_simple_return_1")),
        transaction_cost_bps=float(values.get("feature_transaction_cost_bps", 5.0)),
        min_cross_section=int(values.get("min_cross_section", 2)),
        min_periods=int(values.get("min_periods", 5)),
        require_statistical_acceptance=bool(values.get("require_statistical_acceptance", False)),
        market=market_config,
    )
    runner = AgentMarketResearchRunner(
        adapter=adapter,
        capabilities=capabilities,
        requirement=requirement,
        program_store=program_store,
        config=config,
    )
    result = runner.run(
        task=task,
        candidates=candidates,
        universe=universe,
        start=start,
        end=end,
        program_id=program_id,
        family_id=family_id,
    )
    evidence_store.register(result)
    result.write_json(report_path)
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

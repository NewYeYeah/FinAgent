from __future__ import annotations

import argparse
import json
import tomllib
from dataclasses import fields
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Mapping

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
    AgentMarketExperimentFamilyBridge,
    AgentMarketResearchConfig,
    AgentMarketValidationPolicy,
    GovernedAgentMarketResearchRunner,
    LLMMarketFeatureCandidateGenerator,
    ResearchProgram,
    SQLiteAgentMarketResearchStore,
    SQLiteResearchProgramStore,
    SQLiteResearchRegistry,
    frozen_feature_family,
    read_agent_market_result,
    validate_agent_market_results,
)


def _date(value: object, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must use YYYY-MM-DD") from exc


def _load(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    study = payload.get("agent_market_research")
    if not isinstance(study, dict):
        raise TypeError("configuration must contain [agent_market_research]")
    return study


def _manifest(path: Path, bars_path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("manifest must contain a JSON object")
    if not payload.get("quality_passed"):
        raise ValueError("manifest does not record a passed quality gate")
    if payload.get("normalized_sha256") != sha256_file(bars_path):
        raise ValueError("bars CSV digest does not match manifest.normalized_sha256")
    return payload


def _manifest_request(manifest: Mapping[str, object]) -> Mapping[str, object]:
    request = manifest.get("request")
    if not isinstance(request, Mapping):
        raise TypeError("manifest.request must be an object")
    return request


def _validate_data_contract(
    *,
    manifest: Mapping[str, object],
    configured_provider: str,
    market: MarketRegion,
    expected_symbols: tuple[str, ...],
    observed_symbols: tuple[str, ...],
) -> None:
    actual_provider = str(manifest.get("provider", "")).strip().lower()
    if not actual_provider:
        raise ValueError("manifest.provider is required")
    if configured_provider != actual_provider:
        raise ValueError(
            f"configured provider {configured_provider!r} does not match manifest provider "
            f"{actual_provider!r}"
        )
    request = _manifest_request(manifest)
    manifest_market = str(request.get("market", "")).strip()
    if manifest_market != market.value:
        raise ValueError(
            f"configured market {market.value!r} does not match manifest market "
            f"{manifest_market!r}"
        )
    manifest_symbols_raw = request.get("symbols")
    if not isinstance(manifest_symbols_raw, list):
        raise TypeError("manifest.request.symbols must be an array")
    manifest_symbols = tuple(sorted(str(value).upper() for value in manifest_symbols_raw))
    if expected_symbols and tuple(sorted(expected_symbols)) != manifest_symbols:
        raise ValueError("expected_symbols do not match the immutable manifest request")
    if expected_symbols and tuple(sorted(observed_symbols)) != tuple(sorted(expected_symbols)):
        raise ValueError("normalized dataset canonical symbols do not match expected_symbols")


def _market_config(values: dict[str, object]) -> MarketStudyConfig:
    allowed = {field.name for field in fields(MarketStudyConfig)}
    config_values = {key: value for key, value in values.items() if key in allowed}
    if "candidate_names" in config_values:
        config_values.pop("candidate_names")
    return MarketStudyConfig(**config_values)


def _smoke_inputs(
    *,
    adapter: CSVPriceDataAdapter,
    universe,
    start: datetime,
    end: datetime,
    approved_fields: tuple[str, ...],
    smoke_lookback: int,
) -> dict[str, list[float | None]]:
    calendar = adapter.calendar(start, end, universe)
    if not calendar:
        raise ValueError("market dataset has no common calendar")
    smoke_window = adapter.feature_window(
        calendar[-1],
        (universe[0],),
        approved_fields,
        smoke_lookback,
    )
    output: dict[str, list[float | None]] = {}
    for feature_index, name in enumerate(smoke_window.feature_names):
        values_array = smoke_window.values[:, 0, feature_index]
        output[name] = [float(value) if np.isfinite(value) else None for value in values_array]
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate or replay a bounded feature family on immutable US-market historical "
            "data using nested selection, multiplicity control and deterministic execution."
        )
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("--bars", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--provider", help="explicit provider override; must match manifest")
    parser.add_argument(
        "--frozen-family-report",
        type=Path,
        help="reuse exact generated feature digests from a prior Agent market result",
    )
    parser.add_argument(
        "--assert-replay",
        action="store_true",
        help="require exact deterministic replay of --frozen-family-report",
    )
    args = parser.parse_args()
    if args.assert_replay and args.frozen_family_report is None:
        parser.error("--assert-replay requires --frozen-family-report")

    values = _load(args.config)
    bars_path = args.bars or Path(str(values["bars_path"]))
    manifest_path = args.manifest or Path(str(values["manifest_path"]))
    report_path = args.report or Path(str(values["report_path"]))
    manifest = _manifest(manifest_path, bars_path)
    data_version = str(manifest["data_version"])
    configured_provider = str(
        args.provider or values.get("provider", manifest.get("provider", "alpaca"))
    ).strip().lower()
    market = MarketRegion(str(values.get("market", "us_equity")))

    records = read_normalized_csv(bars_path)
    universe = tuple(sorted({record.asset for record in records}, key=lambda asset: asset.key))
    observed_symbols = tuple(sorted({record.asset.symbol.upper() for record in records}))
    expected_symbols_raw = values.get("expected_symbols", ())
    if not isinstance(expected_symbols_raw, list):
        raise TypeError("expected_symbols must be an array")
    expected_symbols = tuple(str(value).upper() for value in expected_symbols_raw)
    if expected_symbols and len(set(expected_symbols)) != len(expected_symbols):
        raise ValueError("expected_symbols cannot contain duplicates")
    _validate_data_contract(
        manifest=manifest,
        configured_provider=configured_provider,
        market=market,
        expected_symbols=expected_symbols,
        observed_symbols=observed_symbols,
    )

    capabilities = provider_capabilities(configured_provider)
    requirement = ResearchDataRequirement(market=market, frequency=DataFrequency.DAILY)
    requirement.require(capabilities)
    if not records:
        raise ValueError("normalized market dataset is empty")
    available = tuple(record.bar.available_at for record in records)
    start = min(available)
    end = max(available) + timedelta(microseconds=1)
    adapter = CSVPriceDataAdapter(bars_path, data_version=data_version)
    calendar = adapter.calendar(start, end, universe)
    if not calendar:
        raise ValueError("market dataset has no common calendar")

    approved_fields_raw = values.get("approved_input_fields", ())
    if not isinstance(approved_fields_raw, list):
        raise TypeError("approved_input_fields must be an array")
    approved_fields = tuple(str(value) for value in approved_fields_raw)
    if not approved_fields:
        raise ValueError("approved_input_fields must be configured")

    task_id = str(values.get("task_id", "us-etf-agent-research"))
    research_question = str(values["research_question"])
    program_id = str(values.get("program_id", f"program:{task_id}"))
    family_id = str(values.get("family_id", f"family:{task_id}:001"))
    family_alpha = float(values.get("family_alpha", 0.05))
    candidate_count = int(values.get("candidate_count", 4))

    state_dir = Path(str(values.get("state_dir", ".finagent/agent-market")))
    state_dir.mkdir(parents=True, exist_ok=True)
    feature_store = SQLiteGeneratedFeatureStore(state_dir / "generated_features.sqlite")
    program_store = SQLiteResearchProgramStore(state_dir / "research_programs.sqlite")
    research_registry = SQLiteResearchRegistry(state_dir / "research_registry.sqlite")
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
        created_at=datetime.now(UTC),
        metadata={
            "market": market.value,
            "provider": configured_provider,
            "data_version": data_version,
            "data_end": calendar[-1].isoformat(),
            "universe": ",".join(asset.key for asset in universe),
        },
    )

    reference = None
    if args.frozen_family_report is not None:
        reference = read_agent_market_result(args.frozen_family_report)
        identity = (
            (reference.task_id, task_id, "task_id"),
            (reference.program_id, program_id, "program_id"),
            (reference.family_id, family_id, "family_id"),
        )
        for expected, actual, name in identity:
            if expected != actual:
                raise ValueError(f"frozen family {name} does not match configuration")
        if len(reference.candidates) != candidate_count:
            raise ValueError("candidate_count must match the frozen family exactly")
        candidates = frozen_feature_family(
            feature_store,
            reference,
            approved_input_fields=approved_fields,
        )
    else:
        smoke_lookback = int(values.get("smoke_lookback", 64))
        if smoke_lookback < 2:
            raise ValueError("smoke_lookback must be >= 2")
        smoke_inputs = _smoke_inputs(
            adapter=adapter,
            universe=universe,
            start=start,
            end=end,
            approved_fields=approved_fields,
            smoke_lookback=smoke_lookback,
        )
        model = str(values.get("llm_model", "")).strip()
        if not model or model == "REPLACE_WITH_AVAILABLE_MODEL_ID":
            raise ValueError("llm_model must name a model available to the OpenAI API account")
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
    runner = GovernedAgentMarketResearchRunner(
        adapter=adapter,
        capabilities=capabilities,
        requirement=requirement,
        program_store=program_store,
        research_registry=research_registry,
        config=config,
    )
    dataset_artifact = AgentMarketExperimentFamilyBridge.market_dataset_artifact(
        provider=configured_provider,
        data_version=data_version,
        normalized_digest=str(manifest["normalized_sha256"]),
        uri=bars_path.resolve().as_uri(),
    )
    result = runner.run(
        task=task,
        candidates=candidates,
        universe=universe,
        start=start,
        end=end,
        program_id=program_id,
        family_id=family_id,
        dataset_artifact=dataset_artifact,
        require_existing_family=args.frozen_family_report is not None,
    )
    if args.assert_replay:
        assert reference is not None
        replay = validate_agent_market_results(
            reference,
            result,
            policy=AgentMarketValidationPolicy.replay(),
        )
        if not replay.passed:
            raise RuntimeError("deterministic replay failed: " + "; ".join(replay.policy_violations))

    evidence_store.register(result)
    result.write_json(report_path)
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tomllib
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np

from finagent.agents import AgentTask
from finagent.agents.generated_features import (
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
    SQLiteGeneratedFeatureStore,
)
from finagent.agents.generation_checkpoint import SQLiteFeatureGenerationCheckpointStore
from finagent.agents.llm_feature import LLMFeatureGenerationPolicy, LLMFeatureGenerator
from finagent.agents.observability import default_agent_tracer
from finagent.agents.providers import SQLiteLLMCallStore, load_configured_llm
from finagent.data import (
    AshareBarFrequency,
    AshareSupplementalDataStore,
    LocalAshareDatasetLayout,
    LocalAshareFrozenManifest,
    LocalAshareParquetDataAdapter,
    LocalAshareSecurityMaster,
    SupplementedAshareSecurityMaster,
)
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.research.ashare_factor_acceptance import (
    AshareFactorResearchAcceptanceEngine,
)
from finagent.research.ashare_universe import (
    AshareCandidateUniverseConfig,
    AshareCandidateUniverseSelector,
    AshareResearchUniversePolicy,
    AshareResearchUniversePolicyConfig,
)
from finagent.research.factor_discovery import AgentFactorDiscoveryConfig
from finagent.research.factor_feedback_v2 import (
    FactorQuantFeedbackAwareMarketFeatureCandidateGenerator,
)
from finagent.research.factor_quant import (
    FactorEnsembleSelectionConfig,
    FactorEnsembleSelector,
    FactorQuantAnalyzer,
    FactorQuantConfig,
)
from finagent.research.factor_quant_discovery import AgentFactorQuantDiscoveryLoop
from finagent.research.panel_feature_materializer import PanelGeneratedFeatureMaterializer
from finagent.research.resilient_candidate_generator import (
    ResilientLLMMarketFeatureCandidateGenerator,
)
from finagent.sandbox import FeatureSandboxRequest, LocalFeatureSandbox


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _date(value: object, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must use YYYY-MM-DD") from exc


def _range(start: date, end: date) -> TimeRange:
    if end <= start:
        raise ValueError("research split end must be after start")
    return TimeRange(
        datetime.combine(start, time.min, tzinfo=SHANGHAI).astimezone(UTC),
        datetime.combine(end, time.min, tzinfo=SHANGHAI).astimezone(UTC),
    )


def _load(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    values = payload.get("local_ashare_factor_research")
    if not isinstance(values, dict):
        raise TypeError("configuration must contain [local_ashare_factor_research]")
    return values


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise TypeError(f"{name} must be a non-empty array")
    output = tuple(str(item).strip() for item in value)
    if any(not item for item in output) or len(set(output)) != len(output):
        raise ValueError(f"{name} must contain unique non-empty strings")
    return output


def _smoke_inputs(
    adapter,
    universe,
    approved_fields: tuple[str, ...],
    development: TimeRange,
    lookback: int,
) -> dict[str, list[float | None]]:
    asof = development.end - timedelta(microseconds=1)
    for asset in universe:
        try:
            window = adapter.feature_window(
                asof,
                (asset,),
                approved_fields,
                lookback,
            )
        except (KeyError, ValueError):
            continue
        output: dict[str, list[float | None]] = {}
        usable = True
        for feature_index, name in enumerate(window.feature_names):
            values = window.values[:, 0, feature_index]
            converted = [float(value) if np.isfinite(value) else None for value in values]
            if all(value is None for value in converted):
                usable = False
                break
            output[name] = converted
        if usable:
            return output
    raise ValueError("no candidate-universe asset provides usable smoke inputs")


def _register_idempotent(
    store: SQLiteGeneratedFeatureStore,
    artifact: GeneratedFeatureArtifact,
) -> GeneratedFeatureArtifact:
    try:
        existing = store.get(artifact.digest)
    except KeyError:
        store.register(artifact)
        return artifact
    if existing.spec != artifact.spec or existing.source != artifact.source:
        raise ValueError("generated feature store contains conflicting immutable artifact")
    return existing


def _baseline_artifacts(
    raw_factors: object,
    *,
    smoke_inputs: Mapping[str, Sequence[int | float | None]],
    store: SQLiteGeneratedFeatureStore,
) -> tuple[GeneratedFeatureArtifact, ...]:
    if not isinstance(raw_factors, list) or not raw_factors:
        raise TypeError("baseline_factors must be a non-empty array of tables")
    validator = FeatureCodeValidator()
    sandbox = LocalFeatureSandbox(validator=validator)
    artifacts: list[GeneratedFeatureArtifact] = []
    for raw in raw_factors:
        if not isinstance(raw, dict):
            raise TypeError("each baseline factor must be a table")
        fields = _strings(raw.get("input_fields"), "baseline factor input_fields")
        missing = set(fields) - set(smoke_inputs)
        if missing:
            raise ValueError(
                f"baseline factor references unavailable smoke fields: {sorted(missing)}"
            )
        source = str(raw["source"]).strip() + "\n"
        spec = FeatureSpec(
            feature_id=str(raw["feature_id"]),
            name=str(raw.get("name", raw["feature_id"])),
            description=str(raw["description"]),
            hypothesis=str(raw["hypothesis"]),
            input_fields=fields,
            lookback=int(raw.get("lookback", 1)),
        )
        request = FeatureSandboxRequest(
            spec,
            source,
            {field: smoke_inputs[field] for field in fields},
        )
        smoke = sandbox.run(request)
        artifact = GeneratedFeatureArtifact(
            spec=spec,
            source=source,
            validation=validator.validate(source),
            generated_at=datetime.now(UTC),
            generator_id="ashare-a2-deterministic-baseline-v1",
            smoke_output_digest=smoke.output_digest,
            metadata={"scope": "A2 deterministic baseline"},
        )
        artifacts.append(_register_idempotent(store, artifact))
    if len({artifact.digest for artifact in artifacts}) != len(artifacts):
        raise ValueError("baseline factors contain duplicate immutable digests")
    return tuple(artifacts)


def _replay_artifacts(
    reference: Mapping[str, object],
    store: SQLiteGeneratedFeatureStore,
) -> tuple[GeneratedFeatureArtifact, ...]:
    raw = reference.get("candidate_denominator")
    if not isinstance(raw, list) or not raw:
        raise ValueError("frozen report has no candidate_denominator")
    digests: list[str] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise TypeError("frozen report candidate_denominator is invalid")
        digests.append(str(item["feature_digest"]))
    if len(set(digests)) != len(digests):
        raise ValueError("frozen report candidate denominator contains duplicates")
    return tuple(store.get(digest) for digest in digests)


def _factor_quant_config(
    values: Mapping[str, object],
    *,
    split_name: str,
    primary_label: str,
    decay_labels: tuple[str, ...],
) -> FactorQuantConfig:
    return FactorQuantConfig(
        split_name=split_name,
        primary_label=primary_label,
        decay_labels=decay_labels,
        quantiles=int(values.get("quantiles", 5)),
        min_cross_section=int(values.get("min_cross_section", 50)),
        min_periods=int(values.get("min_periods", 250)),
        annualization=float(values.get("annualization", 252.0)),
        winsor_lower_quantile=float(values.get("winsor_lower_quantile", 0.01)),
        winsor_upper_quantile=float(values.get("winsor_upper_quantile", 0.99)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run bounded A-share daily Agent/Factor Quant acceptance on frozen local "
            "Parquet. This command does not execute, promote, consume holdout or trade."
        )
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--mode", choices=("deterministic", "agent"))
    parser.add_argument("--llm-profile")
    parser.add_argument("--frozen-report", type=Path)
    parser.add_argument("--assert-replay", action="store_true")
    parser.add_argument("--verify-content", action="store_true")
    args = parser.parse_args()
    if args.assert_replay and args.frozen_report is None:
        parser.error("--assert-replay requires --frozen-report")

    values = _load(args.config)
    root = args.root or Path(str(values["root"]))
    manifest_path = args.manifest or Path(str(values["frozen_manifest"]))
    report_path = args.report or Path(str(values["report_path"]))
    state_dir = Path(str(values.get("state_dir", ".finagent/ashare-factor-a2")))
    state_dir.mkdir(parents=True, exist_ok=True)

    layout = LocalAshareDatasetLayout(root)
    frozen = LocalAshareFrozenManifest.read_json(manifest_path)
    if AshareBarFrequency.DAILY.value not in frozen.frequencies:
        raise ValueError("frozen manifest does not include daily A-share data")
    frozen.verify(layout, verify_content=True if args.verify_content else False)
    base_master = LocalAshareSecurityMaster.from_parquet(layout.basic_path)
    supplement_root = Path(str(values.get("supplement_root", "reference_data/a_share")))
    supplement = AshareSupplementalDataStore.from_directory(supplement_root)
    master = SupplementedAshareSecurityMaster(base_master, supplement)

    development_start = _date(values["development_start"], "development_start")
    development_end = _date(
        values["development_end_exclusive"],
        "development_end_exclusive",
    )
    validation_start = _date(values["validation_start"], "validation_start")
    validation_end = _date(
        values["validation_end_exclusive"],
        "validation_end_exclusive",
    )
    reserve_start = _date(values["reserve_start"], "reserve_start")
    reserve_end = _date(values["reserve_end_exclusive"], "reserve_end_exclusive")
    if not development_end <= validation_start or not validation_end <= reserve_start:
        raise ValueError("development, validation and untouched reserve windows must not overlap")
    if reserve_end <= reserve_start:
        raise ValueError("reserve_end_exclusive must be later than reserve_start")

    selection_date = _date(values["universe_selection_date"], "universe_selection_date")
    if selection_date >= development_start:
        raise ValueError("universe_selection_date must be before development_start")
    candidate_selection = AshareCandidateUniverseSelector(
        layout,
        master,
        data_version=frozen.dataset_version,
    ).select(
        AshareCandidateUniverseConfig(
            selection_date=selection_date,
            top_n=int(values.get("universe_top_n", 150)),
            min_universe_size=int(values.get("min_universe_size", 100)),
            include_bse=bool(values.get("include_bse", False)),
            min_listed_days=int(values.get("selection_min_listed_days", 250)),
            min_close=float(values.get("selection_min_close", 1.0)),
            min_amount_cny=float(values.get("selection_min_amount_cny", 10_000_000.0)),
            exclude_st=bool(values.get("selection_exclude_st", True)),
        )
    )
    universe = candidate_selection.assets
    adapter = LocalAshareParquetDataAdapter(
        layout,
        frequency=AshareBarFrequency.DAILY,
        security_master=master,
        data_version=frozen.dataset_version,
    )

    approved_fields = _strings(values.get("approved_input_fields"), "approved_input_fields")
    primary_label = str(values.get("primary_label", "forward_simple_return_1"))
    decay_raw = values.get("decay_labels", [])
    if not isinstance(decay_raw, list):
        raise TypeError("decay_labels must be an array")
    decay_labels = tuple(str(value) for value in decay_raw)
    labels = (primary_label, *decay_labels)
    if len(set(labels)) != len(labels):
        raise ValueError("primary_label and decay_labels must be unique")

    development = _range(development_start, development_end)
    validation = _range(validation_start, validation_end)
    combined_request = DatasetRequest(
        universe=universe,
        features=approved_fields,
        labels=labels,
        splits={"development": development, "validation": validation},
        dataset_id="local-ashare-factor-a2-policy",
        metadata={
            "frozen_manifest": str(manifest_path),
            "supplement_version": supplement.data_version,
            "candidate_selection_id": candidate_selection.selection_id,
        },
    )
    universe_provider, universe_report = AshareResearchUniversePolicy(
        AshareResearchUniversePolicyConfig(
            min_listed_days=int(values.get("policy_min_listed_days", 120)),
            exclude_st=bool(values.get("policy_exclude_st", True)),
            min_close=float(values.get("policy_min_close", 1.0)),
            min_median_amount_cny=float(
                values.get("policy_min_median_amount_cny", 5_000_000.0)
            ),
            liquidity_lookback=int(values.get("policy_liquidity_lookback", 20)),
            min_liquidity_observations=int(
                values.get("policy_min_liquidity_observations", 10)
            ),
        )
    ).build(
        adapter,
        combined_request,
        candidate_selection_id=candidate_selection.selection_id,
    )

    development_request = DatasetRequest(
        universe=universe,
        features=approved_fields,
        labels=labels,
        splits={"development": development},
        dataset_id="local-ashare-factor-a2-development",
        metadata={
            "scope": "adaptive development only",
            "universe_policy_version": universe_provider.data_version,
        },
    )
    validation_request = DatasetRequest(
        universe=universe,
        features=approved_fields,
        labels=labels,
        splits={"validation": validation},
        dataset_id="local-ashare-factor-a2-validation",
        metadata={
            "scope": "independent factor-level validation only",
            "universe_policy_version": universe_provider.data_version,
        },
    )

    materializer = PanelGeneratedFeatureMaterializer(
        adapter,
        universe_provider=universe_provider,
        batch_size=int(values.get("sandbox_batch_size", 512)),
    )
    development_analyzer = FactorQuantAnalyzer(
        adapter,
        config=_factor_quant_config(
            values,
            split_name="development",
            primary_label=primary_label,
            decay_labels=decay_labels,
        ),
        materializer=materializer,
    )
    validation_analyzer = FactorQuantAnalyzer(
        adapter,
        config=_factor_quant_config(
            values,
            split_name="validation",
            primary_label=primary_label,
            decay_labels=decay_labels,
        ),
        materializer=materializer,
    )
    selector = FactorEnsembleSelector(
        FactorEnsembleSelectionConfig(
            max_factors=int(values.get("ensemble_max_factors", 3)),
            max_abs_factor_correlation=float(
                values.get("ensemble_max_abs_factor_correlation", 0.85)
            ),
            quality_metric=str(values.get("ensemble_quality_metric", "rank_icir")),
            min_abs_quality=float(values.get("ensemble_min_abs_quality", 0.0)),
            quality_power=float(values.get("ensemble_quality_power", 1.0)),
        )
    )
    feature_store = SQLiteGeneratedFeatureStore(state_dir / "generated_features.sqlite")
    smoke_lookback = int(values.get("smoke_lookback", 64))
    smoke_inputs = _smoke_inputs(
        adapter,
        universe,
        approved_fields,
        development,
        smoke_lookback,
    )

    reference: Mapping[str, object] | None = None
    discovery: Mapping[str, object] | None = None
    development_report = None
    selection = None
    if args.frozen_report is not None:
        loaded = json.loads(args.frozen_report.read_text(encoding="utf-8"))
        if not isinstance(loaded, Mapping):
            raise TypeError("frozen report must contain a JSON object")
        reference = loaded
        if str(loaded.get("data_version")) != frozen.dataset_version:
            raise ValueError("frozen report data_version differs from current frozen manifest")
        candidates = _replay_artifacts(loaded, feature_store)
        mode = "replay"
    else:
        mode = str(args.mode or values.get("mode", "deterministic")).strip().lower()
        if mode == "deterministic":
            candidates = _baseline_artifacts(
                values.get("baseline_factors"),
                smoke_inputs=smoke_inputs,
                store=feature_store,
            )
        elif mode == "agent":
            tracer = default_agent_tracer()
            llm_path = Path(str(values.get("llm_config_path", "configs/llm.toml")))
            profile = str(args.llm_profile or values.get("llm_profile", "")).strip()
            configured_llm = load_configured_llm(
                llm_path,
                profile_name=profile or None,
            )
            model_override = str(values.get("llm_model", "")).strip()
            model = model_override or configured_llm.model
            if not model or model.startswith("REPLACE_WITH_"):
                raise ValueError("LLM model is not configured")
            llm_call_store = SQLiteLLMCallStore(state_dir / "llm_calls.sqlite")
            checkpoint_store = SQLiteFeatureGenerationCheckpointStore(
                state_dir / "feature_generation_checkpoints.sqlite"
            )
            generator = ResilientLLMMarketFeatureCandidateGenerator(
                LLMFeatureGenerator(
                    provider=configured_llm.provider,
                    policy=LLMFeatureGenerationPolicy(
                        model=model,
                        max_lookback=int(values.get("max_feature_lookback", 60)),
                        max_output_tokens=int(values.get("max_output_tokens", 50_000)),
                        max_validation_attempts=int(
                            values.get("candidate_repair_attempts", 3)
                        ),
                    ),
                    feature_store=feature_store,
                    call_store=llm_call_store,
                    tracer=tracer,
                ),
                max_candidates=int(values.get("candidates_per_round", 3)),
                max_replacements_per_candidate=int(
                    values.get("candidate_replacement_attempts", 2)
                ),
                checkpoint_store=checkpoint_store,
                tracer=tracer,
            )
            loop = AgentFactorQuantDiscoveryLoop(
                generator=FactorQuantFeedbackAwareMarketFeatureCandidateGenerator(generator),
                analyzer=development_analyzer,
                selector=selector,
                config=AgentFactorDiscoveryConfig(
                    rounds=int(values.get("agent_rounds", 2)),
                    candidates_per_round=int(values.get("candidates_per_round", 3)),
                    max_total_candidates=int(values.get("max_total_candidates", 8)),
                ),
                tracer=tracer,
            )
            task = AgentTask(
                task_id=str(values.get("task_id", "local-ashare-factor-a2")),
                objective=str(values["research_question"]),
                created_at=datetime.now(UTC),
                metadata={
                    "market": "a_share",
                    "data_version": frozen.dataset_version,
                    "candidate_selection_id": candidate_selection.selection_id,
                    "universe_policy_version": universe_provider.data_version,
                    "reserve_start": reserve_start.isoformat(),
                    "reserve_status": "untouched",
                },
            )
            discovered = loop.run(
                task=task,
                request=development_request,
                approved_input_fields=approved_fields,
                smoke_inputs=smoke_inputs,
            )
            candidates = discovered.candidates
            development_report = discovered.final_report
            selection = discovered.final_selection
            discovery = discovered.to_dict()
        else:
            raise ValueError("mode must be deterministic or agent")

    engine = AshareFactorResearchAcceptanceEngine(
        development_analyzer=development_analyzer,
        validation_analyzer=validation_analyzer,
        selector=selector,
    )
    result = engine.run(
        mode=mode,
        candidates=candidates,
        development_request=development_request,
        validation_request=validation_request,
        candidate_universe=candidate_selection,
        universe_policy=universe_report,
        reserve_start=reserve_start.isoformat(),
        reserve_end=reserve_end.isoformat(),
        development_report=development_report,
        selection=selection,
        discovery=discovery,
    )
    if args.assert_replay:
        assert reference is not None
        expected = str(reference.get("acceptance_id", ""))
        if result.acceptance_id != expected:
            raise RuntimeError(
                f"A-share factor acceptance replay failed: {result.acceptance_id} != {expected}"
            )

    result.write_json(report_path)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

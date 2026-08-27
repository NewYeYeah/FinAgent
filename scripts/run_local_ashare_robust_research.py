#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo

import numpy as np

from finagent.agents import AgentTask
from finagent.agents.generated_features import (
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
    SQLiteGeneratedFeatureStore,
)
from finagent.agents.generation_checkpoint import (
    SQLiteFeatureGenerationCheckpointStore,
)
from finagent.agents.llm_feature import (
    LLMFeatureGenerationPolicy,
    LLMFeatureGenerator,
)
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
from finagent.research.ashare_robust_program import (
    AshareExpandingWalkForwardPlan,
    AshareProgramReservationPlan,
    AshareResearchProgramSpec,
    AshareRobustCandidateGate,
    AshareRobustCandidateGateConfig,
    AshareRobustFactorSelector,
    AshareRobustResearchProgramResult,
    AshareRobustSelectorConfig,
    AshareWalkForwardFactorAnalyzer,
    AshareWalkForwardFold,
    SQLiteAshareResearchProgramSpecStore,
)
from finagent.research.ashare_universe import (
    AshareCandidateUniverseConfig,
    AshareCandidateUniverseSelector,
    AshareResearchUniversePolicy,
    AshareResearchUniversePolicyConfig,
)
from finagent.research.factor_discovery import AgentFactorDiscoveryConfig
from finagent.research.factor_feedback_v3 import (
    AgentAshareRobustDiscoveryLoop,
    AshareRobustFeedbackAwareMarketFeatureCandidateGenerator,
)
from finagent.research.factor_quant import FactorQuantConfig
from finagent.research.panel_feature_materializer import (
    PanelGeneratedFeatureMaterializer,
)
from finagent.research.programs import (
    ResearchProgram,
    SQLiteResearchProgramStore,
)
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
        raise ValueError("research range end must be after start")
    return TimeRange(
        datetime.combine(start, time.min, tzinfo=SHANGHAI).astimezone(UTC),
        datetime.combine(end, time.min, tzinfo=SHANGHAI).astimezone(UTC),
    )


def _load(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    values = payload.get("local_ashare_robust_research")
    if not isinstance(values, dict):
        raise TypeError(
            "configuration must contain [local_ashare_robust_research]"
        )
    return values


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise TypeError(f"{name} must be a non-empty array")
    output = tuple(str(item).strip() for item in value)
    if any(not item for item in output) or len(set(output)) != len(output):
        raise ValueError(f"{name} must contain unique non-empty strings")
    return output


def _years(value: object) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise TypeError("walk_forward_test_years must be a non-empty array")
    years = tuple(int(item) for item in value)
    if years != tuple(sorted(set(years))):
        raise ValueError("walk_forward_test_years must be unique and increasing")
    return years


def _plan(
    *,
    program_start: date,
    test_years: tuple[int, ...],
    reserve_start: date,
    reserve_end: date,
) -> AshareExpandingWalkForwardPlan:
    folds = []
    for year in test_years:
        train_end = date(year, 1, 1)
        test_end = date(year + 1, 1, 1)
        folds.append(
            AshareWalkForwardFold(
                fold_id=f"wf-{year}",
                train_split=f"wf_{year}_train",
                test_split=f"wf_{year}_test",
                train=_range(program_start, train_end),
                test=_range(train_end, test_end),
            )
        )
    return AshareExpandingWalkForwardPlan(
        folds=tuple(folds),
        reserve=_range(reserve_start, reserve_end),
    )


def _smoke_inputs(
    adapter,
    universe,
    approved_fields: tuple[str, ...],
    internal_end: datetime,
    lookback: int,
) -> dict[str, list[float | None]]:
    asof = internal_end - timedelta(microseconds=1)
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
            converted = [
                float(value) if np.isfinite(value) else None for value in values
            ]
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
        raise ValueError("generated feature store contains conflicting artifact")
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
    artifacts = []
    for raw in raw_factors:
        if not isinstance(raw, dict):
            raise TypeError("each baseline factor must be a table")
        fields = _strings(
            raw.get("input_fields"),
            "baseline factor input_fields",
        )
        missing = set(fields) - set(smoke_inputs)
        if missing:
            raise ValueError(
                f"baseline factor references unavailable fields: {sorted(missing)}"
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
        smoke = sandbox.run(
            FeatureSandboxRequest(
                spec,
                source,
                {field: smoke_inputs[field] for field in fields},
            )
        )
        artifact = GeneratedFeatureArtifact(
            spec=spec,
            source=source,
            validation=validator.validate(source),
            generated_at=datetime.now(UTC),
            generator_id="ashare-a2p6-deterministic-baseline-v1",
            smoke_output_digest=smoke.output_digest,
            metadata={"scope": "A2.6 deterministic baseline"},
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
        raise ValueError("frozen robust report has no candidate_denominator")
    digests = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise TypeError("frozen candidate denominator is invalid")
        digests.append(str(item["feature_digest"]))
    if len(set(digests)) != len(digests):
        raise ValueError("frozen candidate denominator contains duplicates")
    return tuple(store.get(digest) for digest in digests)


def _public_llm_identity(
    values: Mapping[str, object],
    profile_override: str | None,
) -> Mapping[str, object]:
    config_path = Path(str(values.get("llm_config_path", "configs/llm.toml")))
    with config_path.open("rb") as handle:
        payload = tomllib.load(handle)
    llm = payload.get("llm")
    if not isinstance(llm, Mapping):
        raise TypeError("LLM config must contain [llm]")
    profiles = llm.get("profiles")
    if not isinstance(profiles, Mapping):
        raise TypeError("LLM config must contain [llm.profiles]")
    profile_name = str(
        profile_override
        or values.get("llm_profile", "")
        or llm.get("default_profile", "")
    ).strip()
    if not profile_name or profile_name not in profiles:
        raise ValueError("configured LLM profile is missing")
    raw = profiles[profile_name]
    if not isinstance(raw, Mapping):
        raise TypeError("configured LLM profile must be a table")
    model_override = str(values.get("llm_model", "")).strip()
    model = model_override or str(raw.get("model", "")).strip()
    if not model or model.startswith("REPLACE_WITH_"):
        raise ValueError("LLM model is not configured")
    return MappingProxyType(
        {
            "profile": profile_name,
            "provider": str(raw.get("provider", "")).strip(),
            "model": model,
            "base_url": str(raw.get("base_url", "")).strip(),
            "thinking": bool(raw.get("thinking", False)),
            "reasoning_effort": str(raw.get("reasoning_effort", "")).strip(),
        }
    )


def _reserve_id(
    data_version: str,
    candidate_selection_id: str,
    reserve: TimeRange,
) -> str:
    payload = {
        "data_version": data_version,
        "candidate_selection_id": candidate_selection_id,
        "range": [reserve.start.isoformat(), reserve.end.isoformat()],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    return f"ashare-reserve-{digest}"


def _request(
    *,
    universe,
    approved_fields: tuple[str, ...],
    labels: tuple[str, ...],
    split_name: str,
    split: TimeRange,
    frozen_manifest: Path,
    supplement_version: str,
    candidate_selection_id: str,
    universe_policy_version: str,
) -> DatasetRequest:
    return DatasetRequest(
        universe=universe,
        features=approved_fields,
        labels=labels,
        splits={split_name: split},
        dataset_id=f"local-ashare-a2p6-{split_name}",
        metadata={
            "scope": "internal walk-forward development only",
            "frozen_manifest": str(frozen_manifest),
            "supplement_version": supplement_version,
            "candidate_selection_id": candidate_selection_id,
            "universe_policy_version": universe_policy_version,
            "reserve_status": "untouched",
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run A2.6 robust A-share expanding walk-forward research. "
            "The command never reads the 2025+ reserve, executes orders, promotes "
            "a model or starts PAPER/realtime operations."
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
    state_dir = Path(
        str(values.get("state_dir", ".finagent/local-ashare-robust-a2p6"))
    )
    state_dir.mkdir(parents=True, exist_ok=True)

    layout = LocalAshareDatasetLayout(root)
    frozen = LocalAshareFrozenManifest.read_json(manifest_path)
    if AshareBarFrequency.DAILY.value not in frozen.frequencies:
        raise ValueError("frozen manifest does not include daily A-share data")
    frozen.verify(layout, verify_content=bool(args.verify_content))
    base_master = LocalAshareSecurityMaster.from_parquet(layout.basic_path)
    supplement_root = Path(
        str(values.get("supplement_root", "reference_data/a_share"))
    )
    supplement = AshareSupplementalDataStore.from_directory(supplement_root)
    master = SupplementedAshareSecurityMaster(base_master, supplement)

    program_start = _date(values["program_start"], "program_start")
    test_years = _years(values["walk_forward_test_years"])
    reserve_start = _date(values["reserve_start"], "reserve_start")
    reserve_end = _date(values["reserve_end_exclusive"], "reserve_end_exclusive")
    plan = _plan(
        program_start=program_start,
        test_years=test_years,
        reserve_start=reserve_start,
        reserve_end=reserve_end,
    )
    selection_date = _date(
        values["universe_selection_date"],
        "universe_selection_date",
    )
    if selection_date >= program_start:
        raise ValueError("universe_selection_date must be before program_start")

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
            min_listed_days=int(
                values.get("selection_min_listed_days", 250)
            ),
            min_close=float(values.get("selection_min_close", 1.0)),
            min_amount_cny=float(
                values.get("selection_min_amount_cny", 10_000_000.0)
            ),
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

    approved_fields = _strings(
        values.get("approved_input_fields"),
        "approved_input_fields",
    )
    primary_label = str(
        values.get("primary_label", "forward_simple_return_1")
    )
    decay_raw = values.get("decay_labels", [])
    if not isinstance(decay_raw, list):
        raise TypeError("decay_labels must be an array")
    decay_labels = tuple(str(value) for value in decay_raw)
    labels = (primary_label, *decay_labels)
    if len(set(labels)) != len(labels):
        raise ValueError("primary_label and decay_labels must be unique")

    combined_request = DatasetRequest(
        universe=universe,
        features=approved_fields,
        labels=labels,
        splits=plan.split_ranges,
        dataset_id="local-ashare-a2p6-universe-policy",
        metadata={
            "frozen_manifest": str(manifest_path),
            "supplement_version": supplement.data_version,
            "candidate_selection_id": candidate_selection.selection_id,
            "reserve_status": "untouched",
        },
    )
    universe_policy_config = AshareResearchUniversePolicyConfig(
        min_listed_days=int(values.get("policy_min_listed_days", 120)),
        exclude_st=bool(values.get("policy_exclude_st", True)),
        min_close=float(values.get("policy_min_close", 1.0)),
        min_median_amount_cny=float(
            values.get("policy_min_median_amount_cny", 5_000_000.0)
        ),
        liquidity_lookback=int(
            values.get("policy_liquidity_lookback", 20)
        ),
        min_liquidity_observations=int(
            values.get("policy_min_liquidity_observations", 10)
        ),
        liquidity_warmup_calendar_days=int(
            values.get("policy_liquidity_warmup_calendar_days", 120)
        ),
    )
    universe_provider, universe_report = AshareResearchUniversePolicy(
        universe_policy_config
    ).build(
        adapter,
        combined_request,
        candidate_selection_id=candidate_selection.selection_id,
    )
    requests = {
        split_name: _request(
            universe=universe,
            approved_fields=approved_fields,
            labels=labels,
            split_name=split_name,
            split=split,
            frozen_manifest=manifest_path,
            supplement_version=supplement.data_version,
            candidate_selection_id=candidate_selection.selection_id,
            universe_policy_version=universe_provider.data_version,
        )
        for split_name, split in plan.split_ranges.items()
    }

    quant_config = FactorQuantConfig(
        split_name=plan.folds[0].train_split,
        primary_label=primary_label,
        decay_labels=decay_labels,
        quantiles=int(values.get("quantiles", 5)),
        min_cross_section=int(values.get("min_cross_section", 50)),
        min_periods=int(values.get("min_periods", 180)),
        annualization=float(values.get("annualization", 252.0)),
        winsor_lower_quantile=float(
            values.get("winsor_lower_quantile", 0.01)
        ),
        winsor_upper_quantile=float(
            values.get("winsor_upper_quantile", 0.99)
        ),
    )
    gate_config = AshareRobustCandidateGateConfig(
        min_positive_fold_ratio=float(
            values.get("gate_min_positive_fold_ratio", 0.75)
        ),
        min_direction_consistency=float(
            values.get("gate_min_direction_consistency", 0.75)
        ),
        min_pooled_rank_icir=float(
            values.get("gate_min_pooled_rank_icir", 0.0)
        ),
        min_mean_fold_rank_icir=float(
            values.get("gate_min_mean_fold_rank_icir", 0.0)
        ),
        min_worst_fold_rank_icir=float(
            values.get("gate_min_worst_fold_rank_icir", -0.05)
        ),
        min_mean_fold_long_short_sharpe=float(
            values.get(
                "gate_min_mean_fold_long_short_sharpe",
                0.0,
            )
        ),
        min_coverage=float(values.get("gate_min_coverage", 0.90)),
        min_quantile_monotonicity=float(
            values.get("gate_min_quantile_monotonicity", 0.25)
        ),
        min_horizon_sign_consistency=float(
            values.get("gate_min_horizon_sign_consistency", 0.50)
        ),
        max_hac_pvalue=float(values.get("gate_max_hac_pvalue", 0.10)),
        max_bh_qvalue=float(values.get("gate_max_bh_qvalue", 0.20)),
        max_mean_one_way_turnover=float(
            values.get("gate_max_mean_one_way_turnover", 1.0)
        ),
        turnover_penalty=float(values.get("gate_turnover_penalty", 0.5)),
    )
    selector_config = AshareRobustSelectorConfig(
        max_factors=int(values.get("selector_max_factors", 3)),
        max_abs_factor_correlation=float(
            values.get("selector_max_abs_factor_correlation", 0.85)
        ),
        quality_power=float(values.get("selector_quality_power", 1.0)),
    )

    configured_mode = str(
        args.mode or values.get("mode", "deterministic")
    ).strip().lower()
    reference: Mapping[str, object] | None = None
    if args.frozen_report is not None:
        loaded = json.loads(args.frozen_report.read_text(encoding="utf-8"))
        if not isinstance(loaded, Mapping):
            raise TypeError("frozen robust report must contain a JSON object")
        reference = loaded
        mode = "replay"
        source_mode = str(loaded.get("mode", configured_mode))
    else:
        mode = configured_mode
        source_mode = configured_mode

    llm_identity = (
        _public_llm_identity(values, args.llm_profile)
        if source_mode == "agent"
        else None
    )
    generation_config: dict[str, object] = {
        "source_mode": source_mode,
        "agent_rounds": int(values.get("agent_rounds", 2)),
        "candidates_per_round": int(
            values.get("candidates_per_round", 3)
        ),
        "max_total_candidates": int(
            values.get("max_total_candidates", 8)
        ),
        "max_feature_lookback": int(
            values.get("max_feature_lookback", 60)
        ),
        "max_output_tokens": int(values.get("max_output_tokens", 50_000)),
        "candidate_repair_attempts": int(
            values.get("candidate_repair_attempts", 3)
        ),
        "candidate_replacement_attempts": int(
            values.get("candidate_replacement_attempts", 2)
        ),
        "llm_identity": dict(llm_identity) if llm_identity is not None else None,
    }
    if source_mode == "deterministic":
        raw_baselines = values.get("baseline_factors")
        if not isinstance(raw_baselines, list):
            raise TypeError("baseline_factors must be an array")
        generation_config["baseline_feature_ids"] = [
            str(item["feature_id"])
            for item in raw_baselines
            if isinstance(item, Mapping)
        ]

    reserve_id = _reserve_id(
        frozen.dataset_version,
        candidate_selection.selection_id,
        plan.reserve,
    )
    program_id = str(
        values.get("program_id", "local-ashare-robust-a2p6")
    )
    spec = AshareResearchProgramSpec(
        program_id=program_id,
        data_version=frozen.dataset_version,
        candidate_selection_id=candidate_selection.selection_id,
        universe_policy_version=universe_provider.data_version,
        plan=plan,
        approved_input_fields=approved_fields,
        primary_label=primary_label,
        decay_labels=decay_labels,
        factor_quant_config={
            "quantiles": quant_config.quantiles,
            "min_cross_section": quant_config.min_cross_section,
            "min_periods": quant_config.min_periods,
            "annualization": quant_config.annualization,
            "winsor_lower_quantile": quant_config.winsor_lower_quantile,
            "winsor_upper_quantile": quant_config.winsor_upper_quantile,
            "hac_lags": int(values.get("robust_hac_lags", 5)),
            "bootstrap_samples": int(
                values.get("robust_bootstrap_samples", 500)
            ),
            "bootstrap_block_length": int(
                values.get("robust_bootstrap_block_length", 20)
            ),
            "bootstrap_seed": int(
                values.get("robust_bootstrap_seed", 20_260_828)
            ),
        },
        gate_config=gate_config.to_dict(),
        selector_config=selector_config.to_dict(),
        generation_config=generation_config,
        reserve_id=reserve_id,
    )
    if reference is not None:
        reference_spec = reference.get("program_spec")
        if not isinstance(reference_spec, Mapping):
            raise ValueError("frozen report has no program_spec")
        if str(reference_spec.get("spec_id")) != spec.spec_id:
            raise ValueError(
                "current A2.6 configuration differs from frozen program spec"
            )

    spec_store = SQLiteAshareResearchProgramSpecStore(
        state_dir / "ashare_research_program_specs.sqlite"
    )
    spec_store.register(spec)
    program_store = SQLiteResearchProgramStore(
        state_dir / "research_programs.sqlite"
    )
    program_store.register(
        ResearchProgram(
            program_id=program_id,
            alpha_budget=float(values.get("program_alpha_budget", 0.05)),
            max_families=int(values.get("program_max_families", 1)),
            max_experiments=int(
                values.get(
                    "program_max_experiments",
                    generation_config["max_total_candidates"],
                )
            ),
            sealed_holdout_id=reserve_id,
        )
    )

    materializer = PanelGeneratedFeatureMaterializer(
        adapter,
        universe_provider=universe_provider,
        batch_size=int(values.get("sandbox_batch_size", 512)),
    )
    analyzer = AshareWalkForwardFactorAnalyzer(
        adapter=adapter,
        materializer=materializer,
        program_spec=spec,
        requests=requests,
        factor_quant_config=quant_config,
        hac_lags=int(values.get("robust_hac_lags", 5)),
        bootstrap_samples=int(
            values.get("robust_bootstrap_samples", 500)
        ),
        bootstrap_block_length=int(
            values.get("robust_bootstrap_block_length", 20)
        ),
        bootstrap_seed=int(
            values.get("robust_bootstrap_seed", 20_260_828)
        ),
    )
    gate = AshareRobustCandidateGate(gate_config)
    selector = AshareRobustFactorSelector(selector_config)

    feature_store = SQLiteGeneratedFeatureStore(
        state_dir / "generated_features.sqlite"
    )
    smoke_inputs = _smoke_inputs(
        adapter,
        universe,
        approved_fields,
        plan.reserve.start,
        int(values.get("smoke_lookback", 64)),
    )
    discovery: Mapping[str, object] | None = None
    walk_forward_report = None
    gate_report = None
    selection = None

    if reference is not None:
        candidates = _replay_artifacts(reference, feature_store)
        raw_discovery = reference.get("discovery")
        discovery = (
            dict(raw_discovery)
            if isinstance(raw_discovery, Mapping)
            else None
        )
    elif mode == "deterministic":
        candidates = _baseline_artifacts(
            values.get("baseline_factors"),
            smoke_inputs=smoke_inputs,
            store=feature_store,
        )
    elif mode == "agent":
        tracer = default_agent_tracer()
        assert llm_identity is not None
        configured_llm = load_configured_llm(
            Path(str(values.get("llm_config_path", "configs/llm.toml"))),
            profile_name=str(llm_identity["profile"]),
        )
        model = str(llm_identity["model"])
        if configured_llm.model != model:
            raise ValueError("configured LLM runtime identity differs from program spec")
        if configured_llm.provider.provider_name != str(llm_identity["provider"]):
            raise ValueError("configured LLM provider differs from program spec")
        base_generator = ResilientLLMMarketFeatureCandidateGenerator(
            LLMFeatureGenerator(
                provider=configured_llm.provider,
                policy=LLMFeatureGenerationPolicy(
                    model=model,
                    max_lookback=int(
                        values.get("max_feature_lookback", 60)
                    ),
                    max_output_tokens=int(
                        values.get("max_output_tokens", 50_000)
                    ),
                    max_validation_attempts=int(
                        values.get("candidate_repair_attempts", 3)
                    ),
                ),
                feature_store=feature_store,
                call_store=SQLiteLLMCallStore(
                    state_dir / "llm_calls.sqlite"
                ),
                tracer=tracer,
            ),
            max_candidates=int(
                values.get("candidates_per_round", 3)
            ),
            max_replacements_per_candidate=int(
                values.get("candidate_replacement_attempts", 2)
            ),
            checkpoint_store=SQLiteFeatureGenerationCheckpointStore(
                state_dir / "feature_generation_checkpoints.sqlite"
            ),
            tracer=tracer,
        )
        loop = AgentAshareRobustDiscoveryLoop(
            generator=AshareRobustFeedbackAwareMarketFeatureCandidateGenerator(
                base_generator
            ),
            analyzer=analyzer,
            gate=gate,
            selector=selector,
            config=AgentFactorDiscoveryConfig(
                rounds=int(values.get("agent_rounds", 2)),
                candidates_per_round=int(
                    values.get("candidates_per_round", 3)
                ),
                max_total_candidates=int(
                    values.get("max_total_candidates", 8)
                ),
            ),
            tracer=tracer,
        )
        task = AgentTask(
            task_id=str(
                values.get("task_id", "local-ashare-robust-a2p6")
            ),
            objective=str(values["research_question"]),
            created_at=datetime.now(UTC),
            metadata={
                "market": "a_share",
                "program_id": program_id,
                "program_spec_id": spec.spec_id,
                "data_version": frozen.dataset_version,
                "candidate_selection_id": candidate_selection.selection_id,
                "universe_policy_version": universe_provider.data_version,
                "reserve_id": reserve_id,
                "reserve_status": "untouched",
            },
        )
        discovered = loop.run(
            task=task,
            approved_input_fields=approved_fields,
            smoke_inputs=smoke_inputs,
        )
        candidates = discovered.candidates
        walk_forward_report = discovered.final_report
        gate_report = discovered.final_gate_report
        selection = discovered.final_selection
        discovery = discovered.to_dict()
    else:
        raise ValueError("mode must be deterministic or agent")

    family_id = str(
        values.get("family_id", f"{program_id}:factor-family")
    )
    family_alpha = float(values.get("family_alpha", 0.05))
    program_store.reserve_plan(
        AshareProgramReservationPlan(
            program_id=program_id,
            family_id=family_id,
            spec_id=spec.spec_id,
            alpha=family_alpha,
            variants=tuple(candidate.digest for candidate in candidates),
        ),
        task_id=str(values.get("task_id", program_id)),
    )

    if walk_forward_report is None:
        walk_forward_report = analyzer.analyze(candidates)
    if gate_report is None:
        gate_report = gate.evaluate(walk_forward_report)
    if selection is None:
        selection = selector.select(walk_forward_report, gate_report)

    program_store.freeze_program(
        program_id,
        actor=str(values.get("freeze_actor", "finagent-a2p6")),
        reason=(
            "A2.6 candidate denominator, walk-forward plan, robust gate and "
            "factor selection frozen before reserve access"
        ),
    )
    lifecycle = program_store.lifecycle_snapshot(program_id)
    result = AshareRobustResearchProgramResult(
        mode=mode,
        program_spec=spec,
        candidate_universe=candidate_selection,
        universe_policy=universe_report,
        candidates=tuple(candidates),
        walk_forward_report=walk_forward_report,
        gate_report=gate_report,
        frozen_selection=selection,
        program_status=lifecycle.status.value,
        discovery=discovery,
    )

    if args.assert_replay:
        assert reference is not None
        expected = str(reference.get("program_result_id", ""))
        if result.result_id != expected:
            raise RuntimeError(
                f"A2.6 exact replay failed: {result.result_id} != {expected}"
            )

    result.write_json(report_path)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

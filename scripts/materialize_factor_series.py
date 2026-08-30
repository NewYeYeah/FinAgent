#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from finagent.agents.generated_features import SQLiteGeneratedFeatureStore
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
from finagent.research.ashare_universe import (
    AshareResearchUniversePolicy,
    AshareResearchUniversePolicyConfig,
)
from finagent.research.factor_quant import FactorQuantConfig
from finagent.research.factor_series import (
    AshareFactorSeriesMaterializer,
    FactorSeriesRow,
    write_factor_series,
)
from finagent.research.panel_feature_materializer import PanelGeneratedFeatureMaterializer


def _load(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    values = payload.get("local_ashare_robust_research")
    if not isinstance(values, dict):
        raise TypeError("configuration must contain [local_ashare_robust_research]")
    return values


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a JSON object")
    return cast(Mapping[str, Any], value)


def _sequence(value: object, name: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a JSON array")
    return cast(Sequence[Any], value)


def _time_range(raw: object, name: str) -> TimeRange:
    values = _sequence(raw, name)
    if len(values) != 2:
        raise ValueError(f"{name} must contain [start, end]")
    return TimeRange(
        datetime.fromisoformat(str(values[0])),
        datetime.fromisoformat(str(values[1])),
    )


def _source_report(path: Path) -> Mapping[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    report = _mapping(raw, "A2.6 report")
    if report.get("schema_version") != "finagent.ashare-robust-research-program.v1":
        raise ValueError("V4-1 requires an A2.6 robust ResearchProgram report")
    if _mapping(report.get("system_acceptance"), "system_acceptance").get("passed") is not True:
        raise ValueError("V4-1 source A2.6 run did not complete successfully")
    if str(report.get("program_status", "")) != "frozen":
        raise ValueError("V4-1 source ResearchProgram must be frozen")
    if str(_mapping(report.get("reserve"), "reserve").get("status", "")) != "untouched":
        raise ValueError("V4-1 refuses an A2.6 report whose reserve is not untouched")
    return report


def _policy_config(raw: Mapping[str, Any]) -> AshareResearchUniversePolicyConfig:
    return AshareResearchUniversePolicyConfig(
        min_listed_days=int(raw["min_listed_days"]),
        exclude_st=bool(raw["exclude_st"]),
        min_close=float(raw["min_close"]),
        min_median_amount_cny=float(raw["min_median_amount_cny"]),
        liquidity_lookback=int(raw["liquidity_lookback"]),
        min_liquidity_observations=int(raw["min_liquidity_observations"]),
        liquidity_warmup_calendar_days=int(raw["liquidity_warmup_calendar_days"]),
    )


def _quant_config(
    program: Mapping[str, Any],
    split_name: str,
) -> FactorQuantConfig:
    raw = _mapping(program.get("factor_quant_config"), "factor_quant_config")
    return FactorQuantConfig(
        split_name=split_name,
        primary_label=str(program["primary_label"]),
        decay_labels=tuple(
            str(value)
            for value in _sequence(program.get("decay_labels", []), "decay_labels")
        ),
        quantiles=int(raw["quantiles"]),
        min_cross_section=int(raw["min_cross_section"]),
        min_periods=int(raw["min_periods"]),
        annualization=float(raw["annualization"]),
        winsor_lower_quantile=float(raw["winsor_lower_quantile"]),
        winsor_upper_quantile=float(raw["winsor_upper_quantile"]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize V4-1 immutable FactorSeriesEvidence from a frozen A2.6 "
            "ResearchProgram. This command reads internal walk-forward evidence only; "
            "the reserve remains untouched."
        )
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("--a2p6-report", type=Path)
    parser.add_argument("--feature-store", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--rolling-window", type=int, default=20)
    parser.add_argument("--verify-content", action="store_true")
    args = parser.parse_args()
    if args.rolling_window < 2:
        parser.error("--rolling-window must be >= 2")

    values = _load(args.config)
    report_path = args.a2p6_report or Path(str(values["report_path"]))
    source = _source_report(report_path)
    program = _mapping(source["program_spec"], "program_spec")
    plan = _mapping(program["walk_forward_plan"], "walk_forward_plan")
    candidate = _mapping(source["candidate_universe"], "candidate_universe")
    universe_policy_raw = _mapping(source["universe_policy"], "universe_policy")

    root = Path(str(values["root"]))
    frozen_manifest_path = Path(str(values["frozen_manifest"]))
    supplement_root = Path(str(values.get("supplement_root", "reference_data/a_share")))
    state_dir = Path(str(values.get("state_dir", ".finagent/local-ashare-robust-a2p6")))
    feature_store_path = args.feature_store or state_dir / "generated_features.sqlite"
    manifest_path = args.manifest or report_path.with_name(
        f"{report_path.stem}.factor-series.json"
    )
    data_path = args.data or report_path.with_name(
        f"{report_path.stem}.factor-series.parquet"
    )

    layout = LocalAshareDatasetLayout(root)
    frozen = LocalAshareFrozenManifest.read_json(frozen_manifest_path)
    if AshareBarFrequency.DAILY.value not in frozen.frequencies:
        raise ValueError("V4-1 frozen manifest does not include A-share daily data")
    frozen.verify(layout, verify_content=bool(args.verify_content))
    if str(source["data_version"]) != frozen.dataset_version:
        raise ValueError("V4-1 source report data_version differs from frozen manifest")

    base_master = LocalAshareSecurityMaster.from_parquet(layout.basic_path)
    supplement = AshareSupplementalDataStore.from_directory(supplement_root)
    master = SupplementedAshareSecurityMaster(base_master, supplement)
    by_code = {record.ts_code: record.asset for record in master.records}
    codes = tuple(str(value) for value in _sequence(candidate["ts_codes"], "ts_codes"))
    missing = set(codes) - set(by_code)
    if missing:
        raise ValueError(f"V4-1 candidate universe is absent from security master: {sorted(missing)}")
    universe = tuple(by_code[code] for code in codes)
    source_asset_keys = tuple(
        str(value) for value in _sequence(candidate["asset_keys"], "asset_keys")
    )
    if tuple(asset.key for asset in universe) != source_asset_keys:
        raise ValueError("V4-1 canonical asset identities differ from A2.6 candidate universe")

    adapter = LocalAshareParquetDataAdapter(
        layout,
        frequency=AshareBarFrequency.DAILY,
        security_master=master,
        data_version=frozen.dataset_version,
    )
    approved_fields = tuple(
        str(value)
        for value in _sequence(program["approved_input_fields"], "approved_input_fields")
    )
    labels = (
        str(program["primary_label"]),
        *tuple(
            str(value)
            for value in _sequence(program.get("decay_labels", []), "decay_labels")
        ),
    )
    folds = tuple(
        _mapping(value, "walk_forward fold")
        for value in _sequence(plan["folds"], "walk_forward folds")
    )
    split_ranges: dict[str, TimeRange] = {}
    for fold in folds:
        split_ranges[str(fold["train_split"])] = _time_range(fold["train"], "fold train")
        split_ranges[str(fold["test_split"])] = _time_range(fold["test"], "fold test")

    policy_config = _policy_config(
        _mapping(universe_policy_raw["config"], "universe_policy.config")
    )
    policy_request = DatasetRequest(
        universe=universe,
        features=approved_fields,
        labels=labels,
        splits=split_ranges,
        dataset_id="v4-1-factor-series-universe-policy",
        metadata={
            "source_program_result_id": str(source["program_result_id"]),
            "reserve_access": "forbidden",
        },
    )
    universe_provider, rebuilt_universe_report = AshareResearchUniversePolicy(
        policy_config
    ).build(
        adapter,
        policy_request,
        candidate_selection_id=str(candidate["selection_id"]),
    )
    expected_policy_version = str(program["universe_policy_version"])
    if universe_provider.data_version != expected_policy_version:
        raise ValueError("V4-1 rebuilt universe-policy identity differs from A2.6")
    if rebuilt_universe_report.to_dict() != dict(universe_policy_raw):
        raise ValueError("V4-1 rebuilt universe-policy report differs from frozen A2.6")

    feature_store = SQLiteGeneratedFeatureStore(feature_store_path)
    denominator = tuple(
        _mapping(value, "candidate denominator item")
        for value in _sequence(source["candidate_denominator"], "candidate_denominator")
    )
    artifacts = []
    for item in denominator:
        digest = str(item["feature_digest"])
        artifact = feature_store.get(digest)
        if artifact.spec.feature_id != str(item["feature_id"]):
            raise ValueError("V4-1 feature_id differs from frozen candidate denominator")
        if tuple(artifact.spec.input_fields) != tuple(
            str(value) for value in _sequence(item["input_fields"], "candidate input_fields")
        ):
            raise ValueError("V4-1 feature inputs differ from frozen candidate denominator")
        if artifact.spec.lookback != int(item["lookback"]):
            raise ValueError("V4-1 feature lookback differs from frozen candidate denominator")
        artifacts.append(artifact)

    fold_by_candidate: dict[str, dict[str, Mapping[str, Any]]] = {}
    walk = _mapping(source["walk_forward_report"], "walk_forward_report")
    for raw_candidate in _sequence(walk["candidates"], "walk_forward candidates"):
        value = _mapping(raw_candidate, "walk_forward candidate")
        fold_by_candidate[str(value["feature_digest"])] = {
            str(fold["fold_id"]): fold
            for fold in (
                _mapping(raw_fold, "walk_forward candidate fold")
                for raw_fold in _sequence(value["folds"], "candidate folds")
            )
        }
    if set(fold_by_candidate) != {artifact.digest for artifact in artifacts}:
        raise ValueError("V4-1 walk-forward denominator differs from generated-feature store")

    panel_materializer = PanelGeneratedFeatureMaterializer(
        adapter,
        universe_provider=universe_provider,
        batch_size=512,
    )
    series_materializer = AshareFactorSeriesMaterializer(
        panel_materializer,
        rolling_window=args.rolling_window,
    )
    rows: list[FactorSeriesRow] = []
    for artifact in artifacts:
        candidate_folds = fold_by_candidate[artifact.digest]
        if set(candidate_folds) != {str(fold["fold_id"]) for fold in folds}:
            raise ValueError("V4-1 candidate fold identities differ from frozen plan")
        for fold in folds:
            fold_id = str(fold["fold_id"])
            split_name = str(fold["test_split"])
            request = DatasetRequest(
                universe=universe,
                features=approved_fields,
                labels=labels,
                splits={split_name: _time_range(fold["test"], "fold test")},
                dataset_id=f"v4-1-{artifact.digest[:12]}-{split_name}",
                metadata={
                    "source_program_result_id": str(source["program_result_id"]),
                    "source_program_spec_id": str(program["spec_id"]),
                    "candidate_selection_id": str(candidate["selection_id"]),
                    "universe_policy_version": universe_provider.data_version,
                    "reserve_access": "forbidden",
                },
            )
            rows.extend(
                series_materializer.materialize_fold(
                    artifact=artifact,
                    request=request,
                    split_name=split_name,
                    fold_id=fold_id,
                    train_direction=int(candidate_folds[fold_id]["train_direction"]),
                    config=_quant_config(program, split_name),
                )
            )

    manifest = write_factor_series(
        source_report=source,
        rows=rows,
        source_report_path=report_path,
        manifest_path=manifest_path,
        data_path=data_path,
        rolling_window=args.rolling_window,
    )
    print(json.dumps(manifest.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

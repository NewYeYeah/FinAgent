#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from finagent.agents.generated_features import SQLiteGeneratedFeatureStore
from finagent.backtest.strategy_decision_alpha import (
    AshareStrategyDecisionAlphaReplay,
    StrategyDecisionAlphaFoldSpec,
)
from finagent.backtest.strategy_decision_series import (
    materialize_strategy_decision_rows,
    write_strategy_decision_series,
)
from finagent.data import (
    AshareBarFrequency,
    AshareSupplementalDataStore,
    LocalAshareDatasetLayout,
    LocalAshareFrozenManifest,
    LocalAshareParquetDataAdapter,
    LocalAshareSecurityMaster,
    SupplementedAshareSecurityMaster,
)
from finagent.data.local_ashare_inference_adapter import LocalAshareInferenceDataAdapter
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.research.ashare_robust_program import (
    AshareExpandingWalkForwardPlan,
    AshareWalkForwardFold,
)
from finagent.research.ashare_universe import (
    AshareResearchUniversePolicy,
    AshareResearchUniversePolicyConfig,
)


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a JSON object")
    return value


def _sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a JSON array")
    return value


def _load_json(path: Path, name: str) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(value, name)


def _load_config(path: Path) -> Mapping[str, object]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    return _mapping(payload.get("ashare_portfolio_validation"), "ashare_portfolio_validation")


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _time_range(raw: object, name: str) -> TimeRange:
    values = _sequence(raw, name)
    if len(values) != 2:
        raise ValueError(f"{name} must contain [start, end]")
    return TimeRange(
        datetime.fromisoformat(str(values[0])),
        datetime.fromisoformat(str(values[1])),
    )


def _plan(
    source: Mapping[str, object],
) -> tuple[AshareExpandingWalkForwardPlan, dict[str, Mapping[str, object]]]:
    program = _mapping(source.get("program_spec"), "program_spec")
    raw_plan = _mapping(program.get("walk_forward_plan"), "walk_forward_plan")
    folds: list[AshareWalkForwardFold] = []
    raw_by_id: dict[str, Mapping[str, object]] = {}
    for raw in _sequence(raw_plan.get("folds"), "walk_forward folds"):
        value = _mapping(raw, "walk_forward fold")
        fold_id = str(value["fold_id"])
        if fold_id in raw_by_id:
            raise ValueError(f"duplicate A2.6 fold_id {fold_id!r}")
        raw_by_id[fold_id] = value
        folds.append(
            AshareWalkForwardFold(
                fold_id=fold_id,
                train_split=str(value["train_split"]),
                test_split=str(value["test_split"]),
                train=_time_range(value["train"], "fold train"),
                test=_time_range(value["test"], "fold test"),
            )
        )
    plan = AshareExpandingWalkForwardPlan(
        folds=tuple(folds),
        reserve=_time_range(raw_plan["reserve"], "walk_forward reserve"),
    )
    if str(raw_plan.get("plan_id", "")) != plan.plan_id:
        raise ValueError("A2.6 walk-forward content differs from its frozen plan_id")
    return plan, raw_by_id


def _policy_config(source: Mapping[str, object]) -> AshareResearchUniversePolicyConfig:
    policy = _mapping(source.get("universe_policy"), "universe_policy")
    raw = _mapping(policy.get("config"), "universe_policy.config")
    return AshareResearchUniversePolicyConfig(
        min_listed_days=int(raw["min_listed_days"]),
        exclude_st=bool(raw["exclude_st"]),
        min_close=float(raw["min_close"]),
        min_median_amount_cny=float(raw["min_median_amount_cny"]),
        liquidity_lookback=int(raw["liquidity_lookback"]),
        min_liquidity_observations=int(raw["min_liquidity_observations"]),
        liquidity_warmup_calendar_days=int(raw["liquidity_warmup_calendar_days"]),
    )


def _ledger_rows(path: Path) -> tuple[Mapping[str, object], ...]:
    output: list[Mapping[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSONL") from exc
            output.append(_mapping(value, f"ledger row {line_number}"))
    return tuple(output)


def _target_reason(row: Mapping[str, object]) -> str:
    target = row.get("target")
    if not isinstance(target, Mapping):
        return ""
    metadata = target.get("metadata")
    if not isinstance(metadata, Mapping):
        return ""
    return str(metadata.get("reason", "")).strip()


def _validate_lineage(
    a4: Mapping[str, object],
    source: Mapping[str, object],
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    if a4.get("schema_version") != "finagent.ashare-portfolio-validation.v1":
        raise ValueError("V4-0 requires an A4 portfolio-validation report")
    if source.get("schema_version") != "finagent.ashare-robust-research-program.v1":
        raise ValueError("V4-0 requires the A2.6 source ResearchProgram report")
    spec = _mapping(a4.get("validation_spec"), "validation_spec")
    program = _mapping(source.get("program_spec"), "program_spec")
    selection = _mapping(source.get("frozen_selection"), "frozen_selection")
    expected = {
        "source_program_result_id": source.get("program_result_id"),
        "source_program_spec_id": program.get("spec_id"),
        "source_selection_id": selection.get("selection_id"),
        "data_version": source.get("data_version"),
    }
    for field, value in expected.items():
        if str(spec.get(field, "")) != str(value or ""):
            raise ValueError(f"A4/A2.6 lineage mismatch: {field}")
    if str(spec.get("source_report_digest", "")) != _canonical_digest(source):
        raise ValueError("A2.6 source report differs from A4 source_report_digest")
    if _mapping(source.get("reserve"), "source reserve").get("status") != "untouched":
        raise ValueError("V4-0 refuses an A2.6 source whose reserve is not untouched")
    if _mapping(a4.get("reserve"), "A4 reserve").get("status") != "untouched":
        raise ValueError("V4-0 refuses an A4 report whose reserve is not untouched")

    components = [
        _mapping(value, "frozen factor component")
        for value in _sequence(selection.get("components"), "frozen_selection.components")
    ]
    source_digests = tuple(str(value.get("feature_digest", "")) for value in components)
    source_weights = tuple(float(value.get("weight", 0.0)) for value in components)
    source_directions = tuple(int(value.get("direction", 0)) for value in components)
    if source_digests != tuple(
        str(value)
        for value in _sequence(
            spec.get("selected_feature_digests"), "selected_feature_digests"
        )
    ):
        raise ValueError("A4 selected factor digests differ from frozen A2.6 selection")
    if source_weights != tuple(
        float(value)
        for value in _sequence(spec.get("selected_weights"), "selected_weights")
    ):
        raise ValueError("A4 selected factor weights differ from frozen A2.6 selection")
    if source_directions != tuple(
        int(value)
        for value in _sequence(spec.get("selected_directions"), "selected_directions")
    ):
        raise ValueError("A4 selected factor directions differ from frozen A2.6 selection")
    return spec, program


def _default_output(report: Path, suffix: str) -> Path:
    return report.with_name(f"{report.stem}.strategy-decisions{suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize authoritative V4-0 StrategyDecisionSeriesEvidence from an "
            "immutable A4 report/ledger while replaying only the frozen A4 AlphaModel."
        )
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("--a4-report", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--a2p6-report", type=Path)
    parser.add_argument("--feature-store", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--verify-content", action="store_true")
    args = parser.parse_args()

    values = _load_config(args.config)
    report_path = args.a4_report or Path(
        str(values.get("report_path", "reports/ashare_a4.json"))
    )
    ledger_path = args.ledger or Path(
        str(values.get("ledger_path", "reports/ashare_a4_ledger.jsonl"))
    )
    source_path = args.a2p6_report or Path(str(values["a2p6_report"]))
    state_dir = Path(str(values.get("state_dir", ".finagent/ashare-a4")))
    feature_store_path = args.feature_store or Path(
        str(values.get("feature_store", state_dir / "generated_features.sqlite"))
    )
    manifest_path = args.manifest or _default_output(report_path, ".json")
    data_path = args.data or _default_output(report_path, ".parquet")

    a4 = _load_json(report_path, "A4 report")
    source = _load_json(source_path, "A2.6 report")
    spec, program = _validate_lineage(a4, source)
    plan, raw_folds = _plan(source)
    if str(spec.get("plan_id", "")) != plan.plan_id:
        raise ValueError("A4 plan_id differs from frozen A2.6 plan")

    root = Path(str(values["root"]))
    manifest_source = Path(str(values["frozen_manifest"]))
    supplement_root = Path(str(values.get("supplement_root", "reference_data/a_share")))
    layout = LocalAshareDatasetLayout(root)
    frozen = LocalAshareFrozenManifest.read_json(manifest_source)
    if AshareBarFrequency.DAILY.value not in frozen.frequencies:
        raise ValueError("V4-0 frozen manifest does not include A-share daily data")
    frozen.verify(layout, verify_content=args.verify_content)
    if str(spec.get("data_version", "")) != frozen.dataset_version:
        raise ValueError("V4-0 data_version differs from frozen market-data manifest")

    base_master = LocalAshareSecurityMaster.from_parquet(layout.basic_path)
    supplemental = AshareSupplementalDataStore.from_directory(supplement_root)
    master = SupplementedAshareSecurityMaster(base_master, supplemental)
    by_code = {record.ts_code: record.asset for record in master.records}
    candidate = _mapping(source.get("candidate_universe"), "candidate_universe")
    codes = tuple(
        str(value)
        for value in _sequence(candidate.get("ts_codes"), "candidate ts_codes")
    )
    missing_codes = set(codes) - set(by_code)
    if missing_codes:
        raise ValueError(
            "V4-0 candidate universe is absent from security master: "
            f"{sorted(missing_codes)}"
        )
    universe = tuple(by_code[code] for code in codes)

    research_adapter = LocalAshareParquetDataAdapter(
        layout,
        frequency=AshareBarFrequency.DAILY,
        security_master=master,
        data_version=frozen.dataset_version,
    )
    inference_adapter = LocalAshareInferenceDataAdapter(
        layout,
        frequency=AshareBarFrequency.DAILY,
        security_master=master,
        data_version=frozen.dataset_version,
    )
    primary_label = str(program["primary_label"])
    policy_config = _policy_config(source)
    policy_request = DatasetRequest(
        universe=universe,
        features=policy_config.required_features,
        labels=(primary_label,),
        splits=plan.split_ranges,
        dataset_id="a4-reserve-safe-universe-policy",
        metadata={
            "source_program_result_id": str(source["program_result_id"]),
            "reserve_access": "forbidden",
        },
    )
    universe_provider, _ = AshareResearchUniversePolicy(policy_config).build(
        inference_adapter,
        policy_request,
        candidate_selection_id=str(candidate["selection_id"]),
    )
    expected_policy = str(
        _mapping(spec.get("net_execution_config"), "net_execution_config").get(
            "inference_universe_policy_version", ""
        )
    )
    if universe_provider.data_version != expected_policy:
        raise ValueError(
            "V4-0 rebuilt universe-policy identity differs from A4 execution binding"
        )

    selected_digests = tuple(
        str(value)
        for value in _sequence(
            spec.get("selected_feature_digests"), "selected_feature_digests"
        )
    )
    selected_weights = tuple(
        float(value)
        for value in _sequence(spec.get("selected_weights"), "selected_weights")
    )
    selected_directions = tuple(
        int(value)
        for value in _sequence(spec.get("selected_directions"), "selected_directions")
    )
    a4_folds = {
        str(_mapping(value, "A4 fold")["fold_id"]): _mapping(value, "A4 fold")
        for value in _sequence(a4.get("folds"), "A4 folds")
    }
    ledger_rows = _ledger_rows(ledger_path)
    alpha_provider = None

    if selected_digests:
        if set(a4_folds) != set(raw_folds):
            raise ValueError("V4-0 A4 fold identities differ from A2.6 walk-forward plan")
        feature_store = SQLiteGeneratedFeatureStore(feature_store_path)
        artifacts = tuple(feature_store.get(digest) for digest in selected_digests)
        validation = _mapping(spec.get("validation_config"), "validation_config")
        replay = AshareStrategyDecisionAlphaReplay(
            research_adapter=research_adapter,
            universe_provider=universe_provider,
            artifacts=artifacts,
            weights=selected_weights,
            directions=selected_directions,
            universe=universe,
            primary_label=primary_label,
            risk_lookback=int(validation["risk_lookback"]),
            alpha_ridge=float(validation["alpha_ridge"]),
            alpha_min_observations=int(validation["alpha_min_observations"]),
            winsor_lower_quantile=float(validation["winsor_lower_quantile"]),
            winsor_upper_quantile=float(validation["winsor_upper_quantile"]),
            folds=tuple(
                StrategyDecisionAlphaFoldSpec(
                    fold_id=fold_id,
                    train_split=str(raw_folds[fold_id]["train_split"]),
                    train_range=_time_range(raw_folds[fold_id]["train"], "fold train"),
                    expected_alpha_model_id=str(a4_folds[fold_id]["alpha_model_id"]),
                )
                for fold_id in sorted(raw_folds)
            ),
        )
        model_error_keys = {
            (
                str(row.get("fold_id", "")),
                datetime.fromisoformat(
                    str(_mapping(row.get("point"), "ledger point")["signal_asof"])
                ),
            )
            for row in ledger_rows
            if _target_reason(row).startswith("MODEL_ERROR:")
        }

        def provide_alpha(fold_id: str, signal_asof: datetime):
            if (fold_id, signal_asof) in model_error_keys:
                return {}
            return replay.snapshot(fold_id, signal_asof)

        alpha_provider = provide_alpha
    elif a4_folds or ledger_rows:
        raise ValueError("V4-0 found A4 execution evidence without a frozen factor family")

    validation = _mapping(spec.get("validation_config"), "validation_config")
    rows = materialize_strategy_decision_rows(
        ledger_rows=ledger_rows,
        expected_ledger_digest=str(a4["ledger_digest"]),
        initial_cash=float(validation["initial_cash"]),
        alpha_provider=alpha_provider,
    )
    manifest = write_strategy_decision_series(
        a4_report=a4,
        rows=rows,
        source_report_path=report_path,
        source_ledger_path=ledger_path,
        manifest_path=manifest_path,
        data_path=data_path,
    )
    print(json.dumps(manifest.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

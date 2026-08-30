from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from finagent.agents.generated_features import SQLiteGeneratedFeatureStore
from finagent.backtest.ashare_portfolio import (
    AshareExecutionAwarePortfolioValidator,
    AsharePortfolioValidationConfig,
    AsharePortfolioValidationPolicy,
    AsharePortfolioValidationSpec,
    SQLiteAsharePortfolioValidationSpecStore,
    no_robust_factor_result,
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
from finagent.data.ashare_close import LocalAshareDailyCloseAdapter
from finagent.data.ashare_execution import LocalAshareDailyExecutionAdapter
from finagent.data.local_ashare_inference_adapter import LocalAshareInferenceDataAdapter
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.research.ashare_robust_program import (
    AshareExpandingWalkForwardPlan,
    AshareRobustFactorComponent,
    AshareRobustFactorSelection,
    AshareRobustSelectorConfig,
    AshareWalkForwardFold,
)
from finagent.research.ashare_universe import (
    AshareResearchUniversePolicy,
    AshareResearchUniversePolicyConfig,
)
from finagent.services.ashare_execution import AshareFeeSchedule

from .ashare_research_workflows import HistoricalWorkflowResult


@dataclass(frozen=True, slots=True)
class PortfolioValidationOptions:
    a2p6_report: Path | None = None
    feature_store: Path | None = None
    report: Path | None = None
    ledger: Path | None = None
    frozen_report: Path | None = None
    assert_replay: bool = False
    verify_content: bool = False


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a JSON object")
    return value


def _sequence(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a JSON array")
    return value


def _time_range(raw: object, name: str) -> TimeRange:
    values = _sequence(raw, name)
    if len(values) != 2:
        raise ValueError(f"{name} must contain [start, end]")
    return TimeRange(
        datetime.fromisoformat(str(values[0])),
        datetime.fromisoformat(str(values[1])),
    )


def _source_report(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    report = _mapping(value, "A2.6 report")
    if report.get("schema_version") != "finagent.ashare-robust-research-program.v1":
        raise ValueError("A4 requires an A2.6 robust ResearchProgram report")
    acceptance = _mapping(report.get("system_acceptance"), "system_acceptance")
    if acceptance.get("passed") is not True:
        raise ValueError("A4 source ResearchProgram did not complete successfully")
    if str(report.get("program_status")) != "frozen":
        raise ValueError("A4 source ResearchProgram must be frozen")
    reserve = _mapping(report.get("reserve"), "reserve")
    if str(reserve.get("status")) != "untouched":
        raise ValueError("A4 refuses a source report whose reserve is not untouched")
    return report


def _plan(report: Mapping[str, object]) -> AshareExpandingWalkForwardPlan:
    program = _mapping(report.get("program_spec"), "program_spec")
    raw_plan = _mapping(program.get("walk_forward_plan"), "walk_forward_plan")
    folds = []
    for raw in _sequence(raw_plan.get("folds"), "walk_forward folds"):
        fold = _mapping(raw, "walk_forward fold")
        folds.append(
            AshareWalkForwardFold(
                fold_id=str(fold["fold_id"]),
                train_split=str(fold["train_split"]),
                test_split=str(fold["test_split"]),
                train=_time_range(fold["train"], "fold train"),
                test=_time_range(fold["test"], "fold test"),
            )
        )
    plan = AshareExpandingWalkForwardPlan(
        folds=tuple(folds),
        reserve=_time_range(raw_plan["reserve"], "walk_forward reserve"),
    )
    if str(raw_plan.get("plan_id", "")) != plan.plan_id:
        raise ValueError("A2.6 walk-forward content differs from its frozen plan_id")
    return plan


def _selection(report: Mapping[str, object]) -> AshareRobustFactorSelection:
    raw = _mapping(report.get("frozen_selection"), "frozen_selection")
    raw_config = _mapping(raw.get("config"), "frozen_selection.config")
    components = []
    for item in _sequence(raw.get("components"), "frozen_selection.components"):
        value = _mapping(item, "frozen factor component")
        components.append(
            AshareRobustFactorComponent(
                feature_id=str(value["feature_id"]),
                feature_digest=str(value["feature_digest"]),
                direction=int(value["direction"]),
                robust_score=float(value["robust_score"]),
                weight=float(value["weight"]),
            )
        )
    selection = AshareRobustFactorSelection(
        walk_forward_report_id=str(raw["walk_forward_report_id"]),
        gate_report_id=str(raw["gate_report_id"]),
        status=str(raw["status"]),
        config=AshareRobustSelectorConfig(
            max_factors=int(raw_config.get("max_factors", 3)),
            max_abs_factor_correlation=float(
                raw_config.get("max_abs_factor_correlation", 0.85)
            ),
            quality_power=float(raw_config.get("quality_power", 1.0)),
        ),
        components=tuple(components),
    )
    if str(raw.get("selection_id", "")) != selection.selection_id:
        raise ValueError("A2.6 factor-family content differs from its selection_id")
    return selection


def _fee_schedule(values: Mapping[str, object]) -> AshareFeeSchedule:
    return AshareFeeSchedule(
        broker_commission_rate=float(values.get("broker_commission_rate", 0.0003)),
        minimum_broker_commission=float(values.get("minimum_broker_commission", 5.0)),
        stamp_duty_sell_rate=float(values.get("stamp_duty_sell_rate", 0.0005)),
        transfer_fee_rate=float(values.get("transfer_fee_rate", 0.00001)),
        sse_szse_handling_rate=float(values.get("sse_szse_handling_rate", 0.0000341)),
        bse_handling_rate=float(values.get("bse_handling_rate", 0.000125)),
        regulatory_fee_rate=float(values.get("regulatory_fee_rate", 0.00002)),
        pass_through_exchange_handling=bool(
            values.get("pass_through_exchange_handling", False)
        ),
        pass_through_regulatory_fee=bool(values.get("pass_through_regulatory_fee", False)),
    )


def _config(values: Mapping[str, object]) -> AsharePortfolioValidationConfig:
    policy = AsharePortfolioValidationPolicy(
        min_net_annualized_return=float(
            values.get("policy_min_net_annualized_return", 0.0)
        ),
        min_net_sharpe=float(values.get("policy_min_net_sharpe", 0.0)),
        max_abs_drawdown=float(values.get("policy_max_abs_drawdown", 0.35)),
        max_gross_to_net_return_drag=float(
            values.get("policy_max_gross_to_net_return_drag", 0.10)
        ),
        min_positive_fold_ratio=float(
            values.get("policy_min_positive_fold_ratio", 0.50)
        ),
        max_hac_pvalue=float(values.get("policy_max_hac_pvalue", 0.10)),
        max_bootstrap_pvalue=float(values.get("policy_max_bootstrap_pvalue", 0.10)),
        max_rejected_order_ratio=float(
            values.get("policy_max_rejected_order_ratio", 0.50)
        ),
        max_ex_post_participation=float(
            values.get("policy_max_ex_post_participation", 0.10)
        ),
        max_cash_fallback_ratio=float(
            values.get("policy_max_cash_fallback_ratio", 0.25)
        ),
    )
    return AsharePortfolioValidationConfig(
        initial_cash=float(values.get("initial_cash", 10_000_000.0)),
        rebalance_every=int(values.get("rebalance_every", 5)),
        active_asset_count=int(values.get("active_asset_count", 20)),
        min_active_assets=int(values.get("min_active_assets", 5)),
        minimum_expected_return=float(values.get("minimum_expected_return", 0.0)),
        risk_lookback=int(values.get("risk_lookback", 120)),
        risk_min_observations=int(values.get("risk_min_observations", 60)),
        risk_aversion=float(values.get("risk_aversion", 5.0)),
        target_cash_weight=float(values.get("target_cash_weight", 0.05)),
        max_asset_weight=float(values.get("max_asset_weight", 0.10)),
        optimizer_turnover_penalty=float(values.get("optimizer_turnover_penalty", 0.01)),
        alpha_ridge=float(values.get("alpha_ridge", 1e-8)),
        alpha_min_observations=int(values.get("alpha_min_observations", 250)),
        winsor_lower_quantile=float(values.get("winsor_lower_quantile", 0.01)),
        winsor_upper_quantile=float(values.get("winsor_upper_quantile", 0.99)),
        annualization=float(values.get("annualization", 252.0)),
        hac_lags=int(values.get("hac_lags", 5)),
        bootstrap_samples=int(values.get("bootstrap_samples", 500)),
        bootstrap_block_length=int(values.get("bootstrap_block_length", 20)),
        bootstrap_seed=int(values.get("bootstrap_seed", 20_260_828)),
        cash_fallback_on_model_error=bool(
            values.get("cash_fallback_on_model_error", True)
        ),
        policy=policy,
    )


def _write_ledger(path: Path, rows: tuple[dict[str, object], ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    row,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            )


def _first_difference(expected: object, actual: object, path: str = "$") -> str:
    if type(expected) is not type(actual):
        return f"{path}: type {type(expected).__name__} != {type(actual).__name__}"
    if isinstance(expected, Mapping):
        expected_keys = set(expected)
        actual_keys = set(actual)
        if expected_keys != actual_keys:
            return (
                f"{path}: keys missing={sorted(expected_keys - actual_keys)} "
                f"extra={sorted(actual_keys - expected_keys)}"
            )
        for key in sorted(expected_keys):
            difference = _first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference:
                return difference
        return ""
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path}: length {len(expected)} != {len(actual)}"
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            difference = _first_difference(left, right, f"{path}[{index}]")
            if difference:
                return difference
        return ""
    if expected != actual:
        return f"{path}: {expected!r} != {actual!r}"
    return ""


def run_portfolio_validation(
    values: Mapping[str, object],
    *,
    options: PortfolioValidationOptions = PortfolioValidationOptions(),
) -> HistoricalWorkflowResult:
    if options.assert_replay and options.frozen_report is None:
        raise ValueError("assert_replay requires frozen_report")

    source_path = options.a2p6_report or Path(str(values["a2p6_report"]))
    source = _source_report(source_path)
    plan = _plan(source)
    selection = _selection(source)
    program = _mapping(source["program_spec"], "program_spec")
    source_universe = _mapping(source["candidate_universe"], "candidate_universe")
    source_policy = _mapping(source["universe_policy"], "universe_policy")
    source_reserve = _mapping(source["reserve"], "reserve")

    root = Path(str(values["root"]))
    manifest_path = Path(str(values["frozen_manifest"]))
    supplement_root = Path(str(values.get("supplement_root", "reference_data/a_share")))
    state_dir = Path(str(values.get("state_dir", ".finagent/ashare-a4")))
    state_dir.mkdir(parents=True, exist_ok=True)
    report_path = options.report or Path(
        str(values.get("report_path", "reports/ashare_a4.json"))
    )
    ledger_path = options.ledger or Path(
        str(values.get("ledger_path", "reports/ashare_a4_ledger.jsonl"))
    )
    feature_store_path = options.feature_store or Path(
        str(values.get("feature_store", state_dir / "generated_features.sqlite"))
    )

    layout = LocalAshareDatasetLayout(root)
    frozen = LocalAshareFrozenManifest.read_json(manifest_path)
    if AshareBarFrequency.DAILY.value not in frozen.frequencies:
        raise ValueError("A4 frozen manifest does not include A-share daily data")
    frozen.verify(layout, verify_content=options.verify_content)
    if str(source["data_version"]) != frozen.dataset_version:
        raise ValueError("A4 source report data_version differs from frozen manifest")

    base_master = LocalAshareSecurityMaster.from_parquet(layout.basic_path)
    supplement = AshareSupplementalDataStore.from_directory(supplement_root)
    master = SupplementedAshareSecurityMaster(base_master, supplement)
    by_code = {record.ts_code: record.asset for record in master.records}
    codes = tuple(
        str(value) for value in _sequence(source_universe["ts_codes"], "ts_codes")
    )
    missing_codes = set(codes) - set(by_code)
    if missing_codes:
        raise ValueError(
            f"A4 candidate universe is absent from security master: {sorted(missing_codes)}"
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
    execution_adapter = LocalAshareDailyExecutionAdapter(
        layout,
        data_version=frozen.dataset_version,
        require_price_limits=bool(values.get("require_price_limits", True)),
    )
    close_adapter = LocalAshareDailyCloseAdapter(
        layout,
        data_version=frozen.dataset_version,
    )

    raw_policy_config = _mapping(source_policy["config"], "universe_policy.config")
    policy_config = AshareResearchUniversePolicyConfig(
        min_listed_days=int(raw_policy_config["min_listed_days"]),
        exclude_st=bool(raw_policy_config["exclude_st"]),
        min_close=float(raw_policy_config["min_close"]),
        min_median_amount_cny=float(raw_policy_config["min_median_amount_cny"]),
        liquidity_lookback=int(raw_policy_config["liquidity_lookback"]),
        min_liquidity_observations=int(raw_policy_config["min_liquidity_observations"]),
        liquidity_warmup_calendar_days=int(
            raw_policy_config["liquidity_warmup_calendar_days"]
        ),
    )
    primary_label = str(program["primary_label"])
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
    universe_provider, _universe_report = AshareResearchUniversePolicy(policy_config).build(
        inference_adapter,
        policy_request,
        candidate_selection_id=str(source_universe["selection_id"]),
    )

    validation_config = _config(values)
    fee_schedule = _fee_schedule(values)
    selected_digests = tuple(
        component.feature_digest for component in selection.components
    )
    selected_weights = tuple(component.weight for component in selection.components)
    selected_directions = tuple(component.direction for component in selection.components)
    spec = AsharePortfolioValidationSpec(
        source_program_result_id=str(source["program_result_id"]),
        source_report_digest=_canonical_digest(source),
        source_program_spec_id=str(program["spec_id"]),
        source_selection_id=str(
            _mapping(source["frozen_selection"], "selection")["selection_id"]
        ),
        data_version=frozen.dataset_version,
        candidate_selection_id=str(source_universe["selection_id"]),
        universe_policy_version=str(source_policy["data_version"]),
        plan_id=plan.plan_id,
        reserve_id=str(source_reserve["reserve_id"]),
        selected_feature_digests=selected_digests,
        selected_weights=selected_weights,
        selected_directions=selected_directions,
        fee_schedule_id=fee_schedule.schedule_id,
        net_execution_config={
            "slippage_bps": float(values.get("slippage_bps", 5.0)),
            "require_price_limits": bool(values.get("require_price_limits", True)),
            "fee_schedule": fee_schedule.to_dict(),
            "inference_universe_policy_version": universe_provider.data_version,
        },
        gross_execution_config={
            "slippage_bps": 0.0,
            "fees": 0.0,
            "same_tradeability_and_lot_rules": True,
        },
        validation_config=validation_config,
    )
    SQLiteAsharePortfolioValidationSpecStore(
        state_dir / "portfolio_validation_specs.sqlite"
    ).register(spec)

    reference: Mapping[str, object] | None = None
    mode = str(source.get("mode", "deterministic"))
    if options.frozen_report is not None:
        loaded = json.loads(options.frozen_report.read_text(encoding="utf-8"))
        reference = _mapping(loaded, "frozen A4 report")
        frozen_spec = _mapping(reference["validation_spec"], "validation_spec")
        if frozen_spec.get("spec_id") != spec.spec_id:
            raise ValueError("frozen A4 report uses a different validation specification")
        mode = "replay"

    if selection.status == "NO_ROBUST_FACTOR_FOUND":
        result = no_robust_factor_result(
            mode=mode,
            spec=spec,
            source_research_status=selection.status,
            reserve_start=plan.reserve.start.isoformat(),
            reserve_end=plan.reserve.end.isoformat(),
        )
        ledger_rows: tuple[dict[str, object], ...] = ()
    else:
        feature_store = SQLiteGeneratedFeatureStore(feature_store_path)
        artifacts = tuple(feature_store.get(digest) for digest in selected_digests)
        validator = AshareExecutionAwarePortfolioValidator(
            research_adapter=research_adapter,
            inference_adapter=inference_adapter,
            execution_adapter=execution_adapter,
            close_adapter=close_adapter,
            universe_provider=universe_provider,
            artifacts=artifacts,
            selection=selection,
            config=validation_config,
            net_fee_schedule=fee_schedule,
            net_slippage_bps=float(values.get("slippage_bps", 5.0)),
            require_price_limits=bool(values.get("require_price_limits", True)),
        )
        result, ledger_rows = validator.run(
            mode=mode,
            spec=spec,
            plan=plan,
            universe=universe,
            primary_label=primary_label,
        )

    result.write_json(report_path)
    _write_ledger(ledger_path, ledger_rows)

    if options.assert_replay:
        assert reference is not None
        expected_id = str(reference.get("portfolio_validation_id", ""))
        expected_ledger = str(reference.get("ledger_digest", ""))
        if result.result_id != expected_id or result.ledger_digest != expected_ledger:
            expected_body = dict(reference)
            actual_body = result.to_dict()
            for payload in (expected_body, actual_body):
                payload.pop("mode", None)
                payload.pop("portfolio_validation_id", None)
            difference = _first_difference(expected_body, actual_body)
            raise RuntimeError(
                "A4 exact replay failed: "
                f"result {result.result_id} != {expected_id}; "
                f"ledger {result.ledger_digest} != {expected_ledger}; "
                f"first_difference={difference or 'none'}"
            )

    payload = result.to_dict()
    return HistoricalWorkflowResult(
        payload=payload,
        report_path=report_path,
        artifact_paths=(report_path, ledger_path),
        evidence_ids=(result.result_id,),
    )

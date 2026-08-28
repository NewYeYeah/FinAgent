from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pytest

from finagent.agents.generated_features import (
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
    SQLiteGeneratedFeatureStore,
)
from finagent.backtest.ashare_portfolio import (
    AsharePortfolioValidationConfig,
    AsharePortfolioValidationPolicy,
    AsharePortfolioValidationSpec,
    SQLiteAsharePortfolioValidationSpecStore,
    no_robust_factor_result,
)
from finagent.data import (
    AshareBarFrequency,
    LocalAshareDatasetLayout,
    LocalAshareParquetDataAdapter,
    LocalAshareSecurityMaster,
    create_local_ashare_frozen_manifest,
)
from finagent.data.ashare_close import LocalAshareDailyCloseAdapter
from finagent.data.local_ashare_inference_adapter import (
    LocalAshareInferenceDataAdapter,
)
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.research.ashare_robust_program import (
    AshareExpandingWalkForwardPlan,
    AshareRobustFactorComponent,
    AshareRobustFactorSelection,
    AshareRobustSelectorConfig,
    AshareWalkForwardFold,
)
from finagent.research.ashare_universe import (
    AshareCandidateUniverseConfig,
    AshareCandidateUniverseSelector,
    AshareResearchUniversePolicy,
    AshareResearchUniversePolicyConfig,
)

from tests.test_ashare_factor_acceptance_a2 import _reference, _vendor


ROOT = Path(__file__).resolve().parents[1]


def _json_difference(expected: object, actual: object, path: str = "$") -> str:
    if type(expected) is not type(actual):
        return f"{path}: type {type(expected).__name__} != {type(actual).__name__}"
    if isinstance(expected, dict):
        keys = set(expected) | set(actual)
        for key in sorted(keys):
            if key not in expected or key not in actual:
                return f"{path}.{key}: key presence differs"
            difference = _json_difference(expected[key], actual[key], f"{path}.{key}")
            if difference:
                return difference
        return ""
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path}: length {len(expected)} != {len(actual)}"
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            difference = _json_difference(left, right, f"{path}[{index}]")
            if difference:
                return difference
        return ""
    if expected != actual:
        return f"{path}: {expected!r} != {actual!r}"
    return ""


def _ledger_difference(expected_path: Path, actual_path: Path) -> str:
    expected_lines = expected_path.read_text(encoding="utf-8").splitlines()
    actual_lines = actual_path.read_text(encoding="utf-8").splitlines()
    if len(expected_lines) != len(actual_lines):
        return f"ledger length {len(expected_lines)} != {len(actual_lines)}"
    for index, (left, right) in enumerate(zip(expected_lines, actual_lines, strict=True)):
        if left != right:
            return f"line {index}: " + _json_difference(json.loads(left), json.loads(right))
    return "no JSONL field difference found"


def _range(start: str, end: str) -> TimeRange:
    return TimeRange(
        datetime.fromisoformat(start).replace(tzinfo=UTC),
        datetime.fromisoformat(end).replace(tzinfo=UTC),
    )


def _plan() -> AshareExpandingWalkForwardPlan:
    return AshareExpandingWalkForwardPlan(
        folds=(
            AshareWalkForwardFold(
                "wf-2021",
                "wf_2021_train",
                "wf_2021_test",
                _range("2020-03-02", "2021-01-01"),
                _range("2021-01-01", "2022-01-01"),
            ),
            AshareWalkForwardFold(
                "wf-2022",
                "wf_2022_train",
                "wf_2022_test",
                _range("2020-03-02", "2022-01-01"),
                _range("2022-01-01", "2023-01-01"),
            ),
        ),
        reserve=_range("2023-01-01", "2023-02-01"),
    )


def _artifact() -> GeneratedFeatureArtifact:
    source = 'def compute_feature(inputs):\n    return inputs["simple_return_20"]\n'
    validator = FeatureCodeValidator()
    return GeneratedFeatureArtifact(
        spec=FeatureSpec(
            feature_id="a4-test-momentum",
            name="A4 test momentum",
            description="twenty-session momentum",
            hypothesis="continuation",
            input_fields=("simple_return_20",),
            lookback=1,
        ),
        source=source,
        validation=validator.validate(source),
        generated_at=datetime(2026, 8, 28, tzinfo=UTC),
        generator_id="test",
        smoke_output_digest="a4-smoke",
    )


def test_inference_adapter_returns_structural_nan_labels(tmp_path: Path) -> None:
    vendor = tmp_path / "vendor"
    _vendor(vendor, assets=8, days=120)
    layout = LocalAshareDatasetLayout(vendor)
    master = LocalAshareSecurityMaster.from_parquet(layout.basic_path)
    adapter = LocalAshareInferenceDataAdapter(
        layout,
        frequency=AshareBarFrequency.DAILY,
        security_master=master,
        data_version="a4-inference",
    )
    universe = tuple(record.asset for record in master.records[:6])
    request = DatasetRequest(
        universe=universe,
        features=("simple_return_5",),
        labels=("forward_simple_return_1",),
        splits={"inference": _range("2020-03-02", "2020-05-01")},
        dataset_id="a4-inference-test",
    )
    dataset = adapter.build_dataset(request)
    panel = dataset.get_split("inference")
    assert np.isnan(panel.label_values).all()
    assert dataset.metadata["forward_rows_read"] == "0"
    assert panel.metadata["reserve_access"] == "forbidden"


def test_exact_close_adapter_does_not_fall_back_to_another_session(
    tmp_path: Path,
) -> None:
    vendor = tmp_path / "vendor"
    _vendor(vendor, assets=4, days=20)
    layout = LocalAshareDatasetLayout(vendor)
    master = LocalAshareSecurityMaster.from_parquet(layout.basic_path)
    assets = tuple(record.asset for record in master.records[:3])
    adapter = LocalAshareDailyCloseAdapter(layout, data_version="a4-close")
    present = adapter.snapshot(date(2020, 1, 2), assets)
    assert len(present.marks) == 3
    absent = adapter.snapshot(date(2019, 12, 31), assets)
    assert absent.marks == {}


def test_empty_frozen_family_has_explicit_no_execution_outcome(tmp_path: Path) -> None:
    config = AsharePortfolioValidationConfig(
        active_asset_count=3,
        min_active_assets=3,
        max_asset_weight=0.4,
        target_cash_weight=0.1,
    )
    spec = AsharePortfolioValidationSpec(
        source_program_result_id="program-result",
        source_report_digest="a" * 64,
        source_program_spec_id="program-spec",
        source_selection_id="selection",
        data_version="data",
        candidate_selection_id="candidate-universe",
        universe_policy_version="universe-policy",
        plan_id="plan",
        reserve_id="reserve",
        selected_feature_digests=(),
        selected_weights=(),
        selected_directions=(),
        fee_schedule_id="fees",
        net_execution_config={},
        gross_execution_config={},
        validation_config=config,
    )
    store = SQLiteAsharePortfolioValidationSpecStore(tmp_path / "spec.sqlite")
    store.register(spec)
    store.register(spec)
    result = no_robust_factor_result(
        mode="deterministic",
        spec=spec,
        source_research_status="NO_ROBUST_FACTOR_FOUND",
        reserve_start="2023-01-01T00:00:00+00:00",
        reserve_end="2023-02-01T00:00:00+00:00",
    )
    assert result.outcome.status == "NO_ROBUST_FACTOR_FAMILY"
    assert result.aggregate is None
    assert result.outcome.promotion_eligible is False


def test_a4_cli_runs_internal_execution_validation_and_exact_replay(
    tmp_path: Path,
) -> None:
    vendor = tmp_path / "vendor"
    _vendor(vendor, assets=10, days=800)
    reference = tmp_path / "reference"
    _reference(reference)
    layout = LocalAshareDatasetLayout(vendor)
    manifest = create_local_ashare_frozen_manifest(
        layout,
        frequencies=(AshareBarFrequency.DAILY,),
        content_hash=False,
        created_at=datetime(2026, 8, 28, tzinfo=UTC),
    )
    manifest_path = tmp_path / "manifest.json"
    manifest.write_json(manifest_path)
    master = LocalAshareSecurityMaster.from_parquet(layout.basic_path)
    research_adapter = LocalAshareParquetDataAdapter(
        layout,
        frequency=AshareBarFrequency.DAILY,
        security_master=master,
        data_version=manifest.dataset_version,
    )
    inference_adapter = LocalAshareInferenceDataAdapter(
        layout,
        frequency=AshareBarFrequency.DAILY,
        security_master=master,
        data_version=manifest.dataset_version,
    )
    selection = AshareCandidateUniverseSelector(
        layout,
        master,
        data_version=manifest.dataset_version,
    ).select(
        AshareCandidateUniverseConfig(
            selection_date=date(2020, 2, 28),
            top_n=8,
            min_universe_size=6,
            min_listed_days=100,
            min_amount_cny=1_000_000,
        )
    )
    plan = _plan()
    policy_config = AshareResearchUniversePolicyConfig(
        min_listed_days=100,
        exclude_st=True,
        min_close=1.0,
        min_median_amount_cny=1_000_000,
        liquidity_lookback=5,
        min_liquidity_observations=3,
        liquidity_warmup_calendar_days=30,
    )
    policy_request = DatasetRequest(
        universe=selection.assets,
        features=policy_config.required_features,
        labels=("forward_simple_return_1",),
        splits=plan.split_ranges,
        dataset_id="a4-source-policy",
    )
    provider, policy_report = AshareResearchUniversePolicy(policy_config).build(
        inference_adapter,
        policy_request,
        candidate_selection_id=selection.selection_id,
    )
    assert provider.data_version == policy_report.data_version

    artifact = _artifact()
    state = tmp_path / "state"
    feature_store = state / "generated_features.sqlite"
    SQLiteGeneratedFeatureStore(feature_store).register(artifact)
    robust_selection = AshareRobustFactorSelection(
        walk_forward_report_id="walk-forward-report",
        gate_report_id="gate-report",
        status="ROBUST_FACTOR_FAMILY_FROZEN",
        config=AshareRobustSelectorConfig(
            max_factors=1,
            max_abs_factor_correlation=0.85,
            quality_power=1.0,
        ),
        components=(
            AshareRobustFactorComponent(
                feature_id=artifact.spec.feature_id,
                feature_digest=artifact.digest,
                direction=1,
                robust_score=1.0,
                weight=1.0,
            ),
        ),
    )
    source = {
        "schema_version": "finagent.ashare-robust-research-program.v1",
        "program_result_id": "a2p6-source-result",
        "mode": "deterministic",
        "system_acceptance": {"passed": True, "status": "PASS"},
        "program_status": "frozen",
        "data_version": manifest.dataset_version,
        "program_spec": {
            "spec_id": "a2p6-source-spec",
            "primary_label": "forward_simple_return_1",
            "walk_forward_plan": plan.to_dict(),
        },
        "candidate_universe": selection.to_dict(),
        "universe_policy": policy_report.to_dict(),
        "frozen_selection": robust_selection.to_dict(),
        "reserve": {
            "reserve_id": "a2p6-reserve",
            "start": plan.reserve.start.isoformat(),
            "end": plan.reserve.end.isoformat(),
            "status": "untouched",
        },
    }
    source_path = tmp_path / "a2p6.json"
    source_path.write_text(json.dumps(source), encoding="utf-8")
    report = tmp_path / "a4.json"
    replay = tmp_path / "a4-replay.json"
    ledger = tmp_path / "a4.jsonl"
    replay_ledger = tmp_path / "a4-replay.jsonl"
    config = tmp_path / "a4.toml"
    config.write_text(
        f'''
[ashare_portfolio_validation]
a2p6_report = "{source_path.as_posix()}"
feature_store = "{feature_store.as_posix()}"
root = "{vendor.as_posix()}"
frozen_manifest = "{manifest_path.as_posix()}"
supplement_root = "{reference.as_posix()}"
state_dir = "{state.as_posix()}"
report_path = "{report.as_posix()}"
ledger_path = "{ledger.as_posix()}"
initial_cash = 1000000.0
rebalance_every = 10
active_asset_count = 5
min_active_assets = 3
minimum_expected_return = -1.0
risk_lookback = 20
risk_min_observations = 10
risk_aversion = 2.0
target_cash_weight = 0.1
max_asset_weight = 0.4
optimizer_turnover_penalty = 0.0
alpha_min_observations = 30
annualization = 252.0
hac_lags = 3
bootstrap_samples = 100
bootstrap_block_length = 5
bootstrap_seed = 7
cash_fallback_on_model_error = true
require_price_limits = false
slippage_bps = 2.0
broker_commission_rate = 0.0001
minimum_broker_commission = 0.0
stamp_duty_sell_rate = 0.0005
transfer_fee_rate = 0.0
policy_min_net_annualized_return = -100.0
policy_min_net_sharpe = -100.0
policy_max_abs_drawdown = 1.0
policy_max_gross_to_net_return_drag = 1.0
policy_min_positive_fold_ratio = 0.0
policy_max_hac_pvalue = 1.0
policy_max_bootstrap_pvalue = 1.0
policy_max_rejected_order_ratio = 1.0
policy_max_ex_post_participation = 1.0
'''.strip()
        + "\n",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_ashare_portfolio_validation.py"),
        str(config),
    ]
    first = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr + first.stdout
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "finagent.ashare-portfolio-validation.v1"
    assert payload["system_acceptance"]["passed"] is True
    assert payload["reserve"]["status"] == "untouched"
    assert payload["research_outcome"]["promotion_eligible"] is False
    assert len(payload["folds"]) == 2
    assert payload["aggregate"]["net_metrics"]["periods"] > 400
    assert payload["aggregate"]["gross_metrics"]["periods"] == (
        payload["aggregate"]["net_metrics"]["periods"]
    )
    assert payload["aggregate"]["total_fees"] >= 0
    assert payload["aggregate"]["total_slippage"] >= 0
    assert payload["aggregate"]["desired_order_count"] >= (
        payload["aggregate"]["rejected_order_count"]
    )
    assert 0.0 <= payload["aggregate"]["cash_fallback_ratio"] <= 1.0
    assert payload["validation_spec"]["source_report_digest"]
    assert payload["ledger_digest"].startswith("a4-execution-ledger-")
    assert ledger.read_text(encoding="utf-8").strip()

    second = subprocess.run(
        [
            *command,
            "--frozen-report",
            str(report),
            "--assert-replay",
            "--report",
            str(replay),
            "--ledger",
            str(replay_ledger),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, (
        second.stderr
        + second.stdout
        + "\nledger_difference="
        + (
            _ledger_difference(ledger, replay_ledger)
            if replay_ledger.exists()
            else "replay ledger was not written"
        )
    )
    replay_payload = json.loads(replay.read_text(encoding="utf-8"))
    assert replay_payload["mode"] == "replay"
    assert (
        replay_payload["portfolio_validation_id"]
        == payload["portfolio_validation_id"]
    )
    assert replay_payload["ledger_digest"] == payload["ledger_digest"]
    assert replay_ledger.read_text(encoding="utf-8") == ledger.read_text(encoding="utf-8")

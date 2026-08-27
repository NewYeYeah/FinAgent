from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from finagent.data import (
    AshareBarFrequency,
    LocalAshareDatasetLayout,
    create_local_ashare_frozen_manifest,
)
from finagent.domain.research import TimeRange
from finagent.research.ashare_robust_program import (
    AshareExpandingWalkForwardPlan,
    AshareResearchProgramSpec,
    AshareRobustCandidateGate,
    AshareRobustCandidateGateConfig,
    AshareRobustFactorSelector,
    AshareRobustSelectorConfig,
    AshareWalkForwardCandidateReport,
    AshareWalkForwardFamilyReport,
    AshareWalkForwardFold,
    AshareWalkForwardFoldCandidate,
    SQLiteAshareResearchProgramSpecStore,
)
from finagent.research.factor_feedback_v3 import AshareRobustAgentFeedbackV3

from tests.test_ashare_factor_acceptance_a2 import _reference, _vendor


ROOT = Path(__file__).resolve().parents[1]


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
                _range("2018-01-01", "2021-01-01"),
                _range("2021-01-01", "2022-01-01"),
            ),
            AshareWalkForwardFold(
                "wf-2022",
                "wf_2022_train",
                "wf_2022_test",
                _range("2018-01-01", "2022-01-01"),
                _range("2022-01-01", "2023-01-01"),
            ),
        ),
        reserve=_range("2023-01-01", "2024-01-01"),
    )


def _candidate(
    feature_id: str,
    digest: str,
    *,
    pooled: float,
    positive_ratio: float,
    pvalue: float,
    bh: float,
) -> AshareWalkForwardCandidateReport:
    folds = (
        AshareWalkForwardFoldCandidate(
            fold_id="wf-2021",
            train_direction=1,
            train_rank_ic=0.02,
            train_rank_icir=0.1,
            test_raw_rank_ic=0.02,
            test_raw_rank_icir=pooled,
            test_rank_ic=0.02,
            test_rank_icir=pooled,
            test_raw_long_short_sharpe=0.5,
            test_long_short_sharpe=0.5,
            coverage=0.98,
            quantile_monotonicity=0.8,
            mean_one_way_turnover=0.3,
            periods=240,
        ),
        AshareWalkForwardFoldCandidate(
            fold_id="wf-2022",
            train_direction=1,
            train_rank_ic=0.02,
            train_rank_icir=0.1,
            test_raw_rank_ic=0.01,
            test_raw_rank_icir=pooled / 2,
            test_rank_ic=0.01,
            test_rank_icir=pooled / 2,
            test_raw_long_short_sharpe=0.4,
            test_long_short_sharpe=0.4,
            coverage=0.97,
            quantile_monotonicity=0.7,
            mean_one_way_turnover=0.35,
            periods=240,
        ),
    )
    return AshareWalkForwardCandidateReport(
        feature_id=feature_id,
        feature_digest=digest,
        folds=folds,
        dominant_direction=1,
        direction_consistency=1.0,
        pooled_rank_ic=0.015,
        pooled_rank_icir=pooled,
        mean_fold_rank_icir=pooled * 0.75,
        worst_fold_rank_icir=pooled / 2,
        positive_fold_ratio=positive_ratio,
        mean_fold_long_short_sharpe=0.45,
        worst_fold_long_short_sharpe=0.4,
        coverage_mean=0.975,
        coverage_min=0.97,
        quantile_monotonicity=0.75,
        mean_one_way_turnover=0.325,
        horizon_sign_consistency=1.0,
        hac_tstat=2.2,
        raw_hac_pvalue=pvalue,
        bootstrap_pvalue=pvalue,
        bootstrap_ci_lower=0.001,
        bootstrap_ci_upper=0.02,
        holm_adjusted_pvalue=min(1.0, pvalue * 2),
        bh_qvalue=bh,
    )


def _family(*candidates: AshareWalkForwardCandidateReport):
    correlations = {}
    if len(candidates) > 1:
        correlations[
            "|".join(
                sorted(
                    (
                        candidates[0].feature_digest,
                        candidates[1].feature_digest,
                    )
                )
            )
        ] = 0.2
    return AshareWalkForwardFamilyReport(
        program_spec_id="spec-test",
        data_version="data-test",
        primary_label="forward_simple_return_1",
        plan_id="plan-test",
        candidates=tuple(candidates),
        factor_value_correlations=correlations,
    )


def test_program_spec_store_is_immutable(tmp_path: Path) -> None:
    spec = AshareResearchProgramSpec(
        program_id="program-a",
        data_version="data-a",
        candidate_selection_id="selection-a",
        universe_policy_version="universe-a",
        plan=_plan(),
        approved_input_fields=("simple_return_5",),
        primary_label="forward_simple_return_1",
        decay_labels=("forward_simple_return_5",),
        factor_quant_config={"min_periods": 100},
        gate_config={"min_positive_fold_ratio": 0.75},
        selector_config={"max_factors": 3},
        generation_config={"mode": "deterministic"},
        reserve_id="reserve-a",
    )
    store = SQLiteAshareResearchProgramSpecStore(tmp_path / "specs.sqlite")
    store.register(spec)
    store.register(spec)
    assert store.payload("program-a")["spec_id"] == spec.spec_id

    changed = AshareResearchProgramSpec(
        program_id="program-a",
        data_version="data-a",
        candidate_selection_id="selection-a",
        universe_policy_version="universe-a",
        plan=_plan(),
        approved_input_fields=("simple_return_20",),
        primary_label="forward_simple_return_1",
        decay_labels=("forward_simple_return_5",),
        factor_quant_config={"min_periods": 100},
        gate_config={"min_positive_fold_ratio": 0.75},
        selector_config={"max_factors": 3},
        generation_config={"mode": "deterministic"},
        reserve_id="reserve-a",
    )
    with pytest.raises(ValueError, match="immutable"):
        store.register(changed)


def test_preregistered_gate_allows_explicit_no_alpha() -> None:
    weak = _candidate(
        "weak",
        "a" * 64,
        pooled=-0.1,
        positive_ratio=0.0,
        pvalue=0.8,
        bh=0.8,
    )
    family = _family(weak)
    gate = AshareRobustCandidateGate().evaluate(family)
    selection = AshareRobustFactorSelector().select(family, gate)
    assert gate.candidates[0].passed is False
    assert selection.status == "NO_ROBUST_FACTOR_FOUND"
    assert selection.components == ()


def test_robust_gate_selection_and_feedback_v3() -> None:
    strong = _candidate(
        "strong",
        "a" * 64,
        pooled=0.2,
        positive_ratio=1.0,
        pvalue=0.01,
        bh=0.02,
    )
    peer = _candidate(
        "peer",
        "b" * 64,
        pooled=0.12,
        positive_ratio=1.0,
        pvalue=0.03,
        bh=0.04,
    )
    family = _family(strong, peer)
    gate = AshareRobustCandidateGate(
        AshareRobustCandidateGateConfig(
            max_hac_pvalue=0.05,
            max_bh_qvalue=0.05,
        )
    ).evaluate(family)
    selection = AshareRobustFactorSelector(
        AshareRobustSelectorConfig(max_factors=2)
    ).select(family, gate)
    feedback = AshareRobustAgentFeedbackV3.from_reports(
        family,
        gate,
        selection,
    )
    assert selection.status == "ROBUST_FACTOR_FAMILY_FROZEN"
    assert len(selection.components) == 2
    assert feedback.selection_status == selection.status
    assert feedback.candidates[0].folds[0].fold_id == "wf-2021"
    assert "2025+ reserve" in feedback.to_dict()["scope"]


def test_a2p6_cli_runs_deterministic_walk_forward_and_exact_replay(
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
    state = tmp_path / "state"
    report = tmp_path / "robust.json"
    replay = tmp_path / "robust-replay.json"
    config = tmp_path / "a2p6.toml"
    config.write_text(
        f'''
[local_ashare_robust_research]
mode = "deterministic"
root = "{vendor.as_posix()}"
frozen_manifest = "{manifest_path.as_posix()}"
supplement_root = "{reference.as_posix()}"
state_dir = "{state.as_posix()}"
report_path = "{report.as_posix()}"
program_id = "test-a2p6-program"
family_id = "test-a2p6-family"
program_alpha_budget = 0.05
program_max_families = 1
program_max_experiments = 6
family_alpha = 0.05
universe_selection_date = 2020-02-28
universe_top_n = 8
min_universe_size = 6
include_bse = false
selection_min_listed_days = 100
selection_min_close = 1.0
selection_min_amount_cny = 1000000.0
selection_exclude_st = true
program_start = 2020-03-02
walk_forward_test_years = [2021, 2022]
reserve_start = 2023-01-01
reserve_end_exclusive = 2024-01-01
approved_input_fields = ["simple_return_1", "simple_return_5", "simple_return_20", "log_volume_change_5", "squared_log_return_1", "circ_mv"]
primary_label = "forward_simple_return_1"
decay_labels = ["forward_simple_return_5"]
policy_min_listed_days = 100
policy_exclude_st = true
policy_min_close = 1.0
policy_min_median_amount_cny = 1000000.0
policy_liquidity_lookback = 5
policy_min_liquidity_observations = 3
policy_liquidity_warmup_calendar_days = 30
quantiles = 3
min_cross_section = 5
min_periods = 30
robust_hac_lags = 3
robust_bootstrap_samples = 100
robust_bootstrap_block_length = 5
robust_bootstrap_seed = 7
gate_min_positive_fold_ratio = 0.0
gate_min_direction_consistency = 0.0
gate_min_pooled_rank_icir = -100.0
gate_min_mean_fold_rank_icir = -100.0
gate_min_worst_fold_rank_icir = -100.0
gate_min_mean_fold_long_short_sharpe = -100.0
gate_min_coverage = 0.0
gate_min_quantile_monotonicity = 0.0
gate_min_horizon_sign_consistency = 0.0
gate_max_hac_pvalue = 1.0
gate_max_bh_qvalue = 1.0
gate_max_mean_one_way_turnover = 10.0
selector_max_factors = 2
selector_max_abs_factor_correlation = 0.99
selector_quality_power = 1.0
sandbox_batch_size = 64
smoke_lookback = 30
task_id = "test-a2p6"

[[local_ashare_robust_research.baseline_factors]]
feature_id = "a2p6-test-momentum"
description = "momentum"
hypothesis = "continuation"
input_fields = ["simple_return_20"]
lookback = 1
source = """
def compute_feature(inputs):
    return inputs["simple_return_20"]
"""

[[local_ashare_robust_research.baseline_factors]]
feature_id = "a2p6-test-reversal"
description = "reversal"
hypothesis = "reversal"
input_fields = ["simple_return_5"]
lookback = 1
source = """
def compute_feature(inputs):
    return [None if value is None else -value for value in inputs["simple_return_5"]]
"""

[[local_ashare_robust_research.baseline_factors]]
feature_id = "a2p6-test-size"
description = "size"
hypothesis = "size premium"
input_fields = ["circ_mv"]
lookback = 1
source = """
def compute_feature(inputs):
    return [None if value is None else -math.log(value) for value in inputs["circ_mv"]]
"""
'''.strip()
        + "\n",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_local_ashare_robust_research.py"),
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
    assert payload["schema_version"] == (
        "finagent.ashare-robust-research-program.v1"
    )
    assert payload["system_acceptance"]["passed"] is True
    assert payload["program_status"] == "frozen"
    assert payload["reserve"]["status"] == "untouched"
    assert payload["candidate_universe"]["size"] >= 6
    assert len(payload["universe_policy"]["splits"]) == 4
    assert len(payload["walk_forward_report"]["candidates"]) == 3
    assert len(payload["walk_forward_report"]["candidates"][0]["folds"]) == 2
    assert len(payload["gate_report"]["candidates"]) == 3
    assert payload["frozen_selection"]["status"] in {
        "ROBUST_FACTOR_FAMILY_FROZEN",
        "NO_ROBUST_FACTOR_FOUND",
    }
    assert payload["research_outcome"]["promotion_eligible"] is False

    second = subprocess.run(
        [
            *command,
            "--frozen-report",
            str(report),
            "--assert-replay",
            "--report",
            str(replay),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr + second.stdout
    replay_payload = json.loads(replay.read_text(encoding="utf-8"))
    assert replay_payload["mode"] == "replay"
    assert replay_payload["program_result_id"] == payload["program_result_id"]
    assert (
        replay_payload["walk_forward_report"]["report_id"]
        == payload["walk_forward_report"]["report_id"]
    )
    assert (
        replay_payload["frozen_selection"]["selection_id"]
        == payload["frozen_selection"]["selection_id"]
    )

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from finagent.domain.assets import AssetId
from finagent.domain.research import ResearchSplit
from finagent.research.ashare_factor_acceptance import (
    AshareFactorResearchAcceptanceEngine,
)
from finagent.research.factor_quant import (
    FactorEnsembleSelector,
    FactorHorizonDiagnostics,
    FactorQuantAnalyzer,
    FactorQuantCandidateReport,
    FactorQuantConfig,
    FactorQuantFamilyReport,
    QuantilePortfolioDiagnostics,
)
from finagent.research.factor_stability import (
    FactorStabilityAnalyzer,
    FactorStabilityConfig,
    adjust_family_pvalues,
)


class _Adapter:
    data_version = "stability-test-data"


def _candidate(
    feature_id: str,
    digest: str,
    *,
    rank_ic: float,
    rank_icir: float,
    sharpe: float,
) -> FactorQuantCandidateReport:
    return FactorQuantCandidateReport(
        feature_id=feature_id,
        feature_digest=digest,
        primary_label="forward_simple_return_1",
        horizon_diagnostics={
            "forward_simple_return_1": FactorHorizonDiagnostics(
                label_name="forward_simple_return_1",
                pearson_ic=rank_ic,
                pearson_icir=rank_icir,
                rank_ic=rank_ic,
                rank_icir=rank_icir,
                periods=100,
            )
        },
        quantile_diagnostics=QuantilePortfolioDiagnostics(
            quantile_mean_returns=(-0.001, 0.0, 0.001),
            long_short_mean_return=0.002 if sharpe >= 0 else -0.002,
            long_short_sharpe=sharpe,
            mean_one_way_turnover=0.2,
            periods=100,
        ),
        coverage=1.0,
    )


def _family(split_name: str, *candidates: FactorQuantCandidateReport) -> FactorQuantFamilyReport:
    return FactorQuantFamilyReport(
        data_version="stability-test-data",
        split_name=split_name,
        primary_label="forward_simple_return_1",
        candidates=tuple(candidates),
        factor_value_correlations={},
    )


def test_validation_comparison_uses_development_direction_and_signed_delta() -> None:
    development = _family(
        "development",
        _candidate("negative-direction", "a", rank_ic=-0.03, rank_icir=-0.2, sharpe=-0.3),
        _candidate("positive-direction", "b", rank_ic=0.02, rank_icir=0.1, sharpe=0.2),
    )
    validation = _family(
        "validation",
        _candidate("negative-direction", "a", rank_ic=-0.04, rank_icir=-0.3, sharpe=-0.4),
        _candidate("positive-direction", "b", rank_ic=0.02, rank_icir=0.2, sharpe=0.2),
    )
    ensemble = _candidate(
        "ensemble",
        "ensemble",
        rank_ic=-0.01,
        rank_icir=-0.1,
        sharpe=-0.5,
    )

    comparison = AshareFactorResearchAcceptanceEngine._comparison(
        development,
        validation,
        ensemble,
    )

    assert comparison.best_single_feature_digest == "a"
    assert comparison.best_single_direction == -1
    assert comparison.best_single_raw_rank_icir == pytest.approx(-0.3)
    assert comparison.best_single_rank_icir == pytest.approx(0.3)
    assert comparison.ensemble_minus_best_single_rank_icir == pytest.approx(-0.4)
    assert comparison.best_single_long_short_sharpe == pytest.approx(0.4)
    assert comparison.ensemble_minus_best_single_long_short_sharpe == pytest.approx(-0.9)
    assert comparison.absolute_long_short_sharpe_magnitude_delta == pytest.approx(0.1)


def test_factor_stability_reports_rolling_subperiod_and_dependence_aware_inference() -> None:
    rng = np.random.default_rng(42)
    n_times = 160
    n_assets = 30
    timestamps = tuple(
        datetime(2020, 1, 2, tzinfo=UTC) + timedelta(days=index)
        for index in range(n_times)
    )
    assets = tuple(AssetId(f"A{index:03d}", venue="TEST") for index in range(n_assets))
    factor = np.empty((n_times, n_assets), dtype=float)
    labels = np.empty((n_times, n_assets), dtype=float)
    base = np.linspace(-1.0, 1.0, n_assets)
    for row in range(n_times):
        values = base + 0.05 * np.sin(row / 9.0 + np.arange(n_assets))
        factor[row] = values
        labels[row] = 0.002 * values + rng.normal(0.0, 0.00005, n_assets)
    panel = ResearchSplit(
        timestamps=timestamps,
        assets=assets,
        feature_names=("generated:stable",),
        label_names=("forward_simple_return_1",),
        feature_values=factor[:, :, None],
        label_values=labels[:, :, None],
        eligibility_mask=np.ones((n_times, n_assets), dtype=bool),
    )
    quant = FactorQuantAnalyzer(
        _Adapter(),
        config=FactorQuantConfig(
            split_name="validation",
            primary_label="forward_simple_return_1",
            quantiles=5,
            min_cross_section=20,
            min_periods=50,
        ),
    )
    analyzer = FactorStabilityAnalyzer(
        quant,
        config=FactorStabilityConfig(
            rolling_window=40,
            rolling_step=20,
            min_rolling_periods=20,
            hac_lags=5,
            bootstrap_samples=200,
            bootstrap_block_length=10,
            bootstrap_seed=7,
        ),
    )

    report = analyzer.analyze_panel(
        feature_id="stable",
        feature_digest="stable-digest",
        panel=panel,
    )

    assert report.periods == n_times
    assert report.hac_tstat > 0
    assert report.hac_pvalue < 0.05
    assert report.bootstrap_pvalue < 0.05
    assert report.sign_consistency_ratio > 0.95
    assert report.quantile_monotonicity > 0.9
    assert report.coverage_min == 1.0
    assert len(report.rolling_rank_ic) >= 6
    assert report.subperiods


def test_family_pvalue_adjustments_preserve_denominator_and_monotonicity() -> None:
    adjusted = adjust_family_pvalues({"a": 0.01, "b": 0.04, "c": 0.20})

    assert set(adjusted) == {"a", "b", "c"}
    assert adjusted["a"][0] == pytest.approx(0.03)
    assert adjusted["b"][0] == pytest.approx(0.08)
    assert adjusted["c"][0] == pytest.approx(0.20)
    assert adjusted["a"][1] <= adjusted["b"][1] <= adjusted["c"][1]


def test_research_outcome_is_separate_from_system_completion() -> None:
    development = FactorQuantAnalyzer(
        _Adapter(),
        config=FactorQuantConfig(split_name="development"),
    )
    validation = FactorQuantAnalyzer(
        _Adapter(),
        config=FactorQuantConfig(split_name="validation"),
    )
    engine = AshareFactorResearchAcceptanceEngine(
        development_analyzer=development,
        validation_analyzer=validation,
        selector=FactorEnsembleSelector(),
    )
    panel = ResearchSplit(
        timestamps=tuple(
            datetime(2021, 1, 1, tzinfo=UTC) + timedelta(days=index)
            for index in range(30)
        ),
        assets=tuple(AssetId(f"B{index:03d}", venue="TEST") for index in range(10)),
        feature_names=("generated:negative",),
        label_names=("forward_simple_return_1",),
        feature_values=np.tile(np.arange(10, dtype=float), (30, 1))[:, :, None],
        label_values=-np.tile(np.arange(10, dtype=float), (30, 1))[:, :, None],
        eligibility_mask=np.ones((30, 10), dtype=bool),
    )
    stability = FactorStabilityAnalyzer(
        validation,
        config=FactorStabilityConfig(
            rolling_window=20,
            rolling_step=10,
            min_rolling_periods=10,
            bootstrap_samples=100,
            bootstrap_block_length=5,
        ),
    ).analyze_panel(
        feature_id="negative",
        feature_digest="negative-digest",
        panel=panel,
    )
    ensemble = _candidate(
        "ensemble",
        "negative-digest",
        rank_ic=-0.1,
        rank_icir=-0.2,
        sharpe=-0.3,
    )

    outcome = engine._research_outcome(ensemble, stability)

    assert outcome.status == "ENSEMBLE_VALIDATION_FAILED"
    assert outcome.ensemble_validation_passed is False
    assert outcome.promotion_eligible is False
    assert "A_SHARE_EXECUTION_NOT_CERTIFIED" in outcome.reason_codes

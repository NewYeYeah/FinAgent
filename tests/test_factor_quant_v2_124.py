from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from finagent.agents.generated_features import (
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
)
from finagent.data import InMemoryPriceDataAdapter
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiments import ArtifactType
from finagent.domain.market import PriceBar
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.models.alpha import GeneratedFeatureEnsembleAlphaModel
from finagent.research import (
    FactorEnsembleSelectionConfig,
    FactorEnsembleSelector,
    FactorHorizonDiagnostics,
    FactorQuantAnalyzer,
    FactorQuantCandidateReport,
    FactorQuantConfig,
    FactorQuantFamilyReport,
    QuantilePortfolioDiagnostics,
)


NOW = datetime(2026, 8, 26, 7, 0, tzinfo=UTC)


def _artifact(
    feature_id: str,
    source: str,
    *,
    hypothesis: str,
    input_fields: tuple[str, ...],
    lookback: int = 3,
) -> GeneratedFeatureArtifact:
    validator = FeatureCodeValidator()
    return GeneratedFeatureArtifact(
        spec=FeatureSpec(
            feature_id=feature_id,
            name=feature_id,
            description=f"factor quant feature {feature_id}",
            hypothesis=hypothesis,
            input_fields=input_fields,
            lookback=lookback,
        ),
        source=source,
        validation=validator.validate(source),
        generated_at=NOW,
        generator_id="unit-test",
        smoke_output_digest=f"smoke-{feature_id}",
    )


def _adapter(days: int = 72):
    assets = tuple(
        AssetId(symbol, AssetType.ETF, venue="ARCX", currency="USD")
        for symbol in ("SPY", "QQQ", "IWM", "DIA", "XLK")
    )
    start = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    histories = {}
    for asset_index, asset in enumerate(assets):
        price = 90.0 + 12.0 * asset_index
        bars = []
        for day in range(days):
            event_time = start + timedelta(days=day)
            persistent = 0.0025 * np.sin(day / 5.0 + asset_index * 0.65)
            cross_section = 0.00035 * (asset_index - 2)
            return_component = cross_section + persistent
            price *= 1.0 + return_component
            volume = 1_200_000.0 * (
                1.0
                + 0.10 * np.cos(day / 6.0 + asset_index * 0.9)
                + 0.015 * asset_index
            )
            bars.append(
                PriceBar(
                    event_time=event_time,
                    available_at=event_time + timedelta(hours=6, minutes=30),
                    open=price * 0.999,
                    high=price * 1.004,
                    low=price * 0.996,
                    close=price,
                    volume=volume,
                )
            )
        histories[asset] = tuple(bars)
    return InMemoryPriceDataAdapter(histories, data_version="factor-quant-v2-test"), assets, start


def _development_request(universe, start) -> DatasetRequest:
    available_start = start + timedelta(hours=6, minutes=30)
    return DatasetRequest(
        universe=universe,
        features=("simple_return_1", "log_volume_change_1"),
        labels=(
            "forward_simple_return_1",
            "forward_simple_return_3",
            "forward_simple_return_5",
        ),
        splits={
            "development": TimeRange(
                available_start + timedelta(days=10),
                available_start + timedelta(days=58),
            )
        },
        dataset_id="factor-quant-development",
    )


def test_factor_quant_engine_reports_ic_decay_quantiles_and_value_redundancy() -> None:
    adapter, universe, start = _adapter()
    request = _development_request(universe, start)
    momentum = _artifact(
        "momentum",
        'def compute_feature(inputs):\n    return inputs["simple_return_1"]\n',
        hypothesis="short-horizon continuation",
        input_fields=("simple_return_1",),
    )
    volume = _artifact(
        "volume-change",
        'def compute_feature(inputs):\n    return inputs["log_volume_change_1"]\n',
        hypothesis="volume change predicts next return",
        input_fields=("log_volume_change_1",),
    )
    analyzer = FactorQuantAnalyzer(
        adapter,
        config=FactorQuantConfig(
            split_name="development",
            primary_label="forward_simple_return_1",
            decay_labels=("forward_simple_return_3", "forward_simple_return_5"),
            quantiles=3,
            min_cross_section=5,
            min_periods=20,
        ),
    )

    report = analyzer.analyze((momentum, volume), request=request)

    assert report.data_version == adapter.data_version
    assert report.report_id.startswith("factor-quant-")
    assert len(report.candidates) == 2
    for candidate in report.candidates:
        assert set(candidate.horizon_diagnostics) == {
            "forward_simple_return_1",
            "forward_simple_return_3",
            "forward_simple_return_5",
        }
        assert candidate.primary.periods >= 20
        assert np.isfinite(candidate.primary.pearson_ic)
        assert np.isfinite(candidate.primary.rank_ic)
        assert len(candidate.quantile_diagnostics.quantile_mean_returns) == 3
        assert candidate.quantile_diagnostics.periods >= 20
        assert candidate.quantile_diagnostics.mean_one_way_turnover >= 0.0
        assert 0.0 <= candidate.coverage <= 1.0
    assert len(report.factor_value_correlations) == 1
    correlation = next(iter(report.factor_value_correlations.values()))
    assert -1.0 <= correlation <= 1.0


def _candidate_report(feature_id: str, digest: str, rank_icir: float) -> FactorQuantCandidateReport:
    horizon = FactorHorizonDiagnostics(
        label_name="forward_simple_return_1",
        pearson_ic=0.02,
        pearson_icir=rank_icir * 0.8,
        rank_ic=0.03,
        rank_icir=rank_icir,
        periods=80,
    )
    return FactorQuantCandidateReport(
        feature_id=feature_id,
        feature_digest=digest,
        primary_label="forward_simple_return_1",
        horizon_diagnostics={"forward_simple_return_1": horizon},
        quantile_diagnostics=QuantilePortfolioDiagnostics(
            quantile_mean_returns=(-0.001, 0.0, 0.001),
            long_short_mean_return=0.002,
            long_short_sharpe=1.0,
            mean_one_way_turnover=0.25,
            periods=80,
        ),
        coverage=0.98,
    )


def test_factor_ensemble_selector_removes_redundant_high_quality_factor() -> None:
    a = _candidate_report("a", "a" * 64, 1.2)
    b = _candidate_report("b", "b" * 64, 1.0)
    c = _candidate_report("c", "c" * 64, 0.8)
    report = FactorQuantFamilyReport(
        data_version="v1",
        split_name="development",
        primary_label="forward_simple_return_1",
        candidates=(a, b, c),
        factor_value_correlations={
            f"{a.feature_digest}|{b.feature_digest}": 0.96,
            f"{a.feature_digest}|{c.feature_digest}": 0.10,
            f"{b.feature_digest}|{c.feature_digest}": 0.15,
        },
    )
    selector = FactorEnsembleSelector(
        FactorEnsembleSelectionConfig(
            max_factors=2,
            max_abs_factor_correlation=0.85,
            quality_metric="rank_icir",
        )
    )

    selection = selector.select(report)

    assert selection.feature_digests == (a.feature_digest, c.feature_digest)
    assert np.isclose(sum(selection.weights), 1.0)
    assert np.isclose(selection.weights[0], 0.6)
    assert np.isclose(selection.weights[1], 0.4)
    assert selection.to_dict()["quality_metric"] == "rank_icir"


def test_generated_feature_ensemble_is_standard_alpha_model_fit_predict() -> None:
    adapter, universe, start = _adapter()
    available_start = start + timedelta(hours=6, minutes=30)
    momentum = _artifact(
        "ensemble-momentum",
        'def compute_feature(inputs):\n    return inputs["simple_return_1"]\n',
        hypothesis="continuation",
        input_fields=("simple_return_1",),
    )
    volume = _artifact(
        "ensemble-volume",
        'def compute_feature(inputs):\n    return inputs["log_volume_change_1"]\n',
        hypothesis="volume confirmation",
        input_fields=("log_volume_change_1",),
        lookback=4,
    )
    dataset = adapter.build_dataset(
        DatasetRequest(
            universe=universe,
            features=("simple_return_1", "log_volume_change_1"),
            labels=("forward_simple_return_1",),
            splits={
                "train": TimeRange(
                    available_start + timedelta(days=8),
                    available_start + timedelta(days=52),
                )
            },
            dataset_id="ensemble-alpha-train",
        )
    )
    model = GeneratedFeatureEnsembleAlphaModel(
        (momentum, volume),
        (0.65, 0.35),
        label_name="forward_simple_return_1",
        min_observations=30,
    )

    artifact = model.fit(dataset, "train")
    asof = available_start + timedelta(days=60)
    window = adapter.feature_window(
        asof,
        universe,
        model.required_features,
        model.min_lookback,
    )
    forecast = model.predict(window)

    assert artifact.artifact_type is ArtifactType.MODEL
    assert model.required_features == ("simple_return_1", "log_volume_change_1")
    assert model.min_lookback == 4
    assert len(model.component_artifacts) == 2
    assert set(forecast.expected_returns) == set(universe)
    assert all(np.isfinite(value) for value in forecast.expected_returns.values())
    assert forecast.source.name == "generated_feature_ensemble_alpha"
    assert forecast.metadata["feature_ids"] == "ensemble-momentum|ensemble-volume"
    assert forecast.metadata["label_name"] == "forward_simple_return_1"

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from finagent.agents.generated_features import (
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
)
from finagent.research import (
    FactorEnsembleComponentSelection,
    FactorEnsembleModelBuilder,
    FactorEnsembleSelection,
    FactorHorizonDiagnostics,
    FactorQuantCandidateReport,
    FactorQuantFamilyReport,
    QuantilePortfolioDiagnostics,
)


NOW = datetime(2026, 8, 26, 7, 30, tzinfo=UTC)


def _artifact(feature_id: str, field: str) -> GeneratedFeatureArtifact:
    source = f'def compute_feature(inputs):\n    return inputs["{field}"]\n'
    validator = FeatureCodeValidator()
    return GeneratedFeatureArtifact(
        spec=FeatureSpec(
            feature_id=feature_id,
            name=feature_id,
            description=f"wiring feature {feature_id}",
            hypothesis=f"{field} carries predictive information",
            input_fields=(field,),
            lookback=3,
        ),
        source=source,
        validation=validator.validate(source),
        generated_at=NOW,
        generator_id="unit-test",
        smoke_output_digest=f"smoke-{feature_id}",
    )


def _candidate(artifact: GeneratedFeatureArtifact, rank_icir: float) -> FactorQuantCandidateReport:
    return FactorQuantCandidateReport(
        feature_id=artifact.spec.feature_id,
        feature_digest=artifact.digest,
        primary_label="forward_simple_return_1",
        horizon_diagnostics={
            "forward_simple_return_1": FactorHorizonDiagnostics(
                label_name="forward_simple_return_1",
                pearson_ic=0.02,
                pearson_icir=rank_icir * 0.8,
                rank_ic=0.03,
                rank_icir=rank_icir,
                periods=80,
            )
        },
        quantile_diagnostics=QuantilePortfolioDiagnostics(
            quantile_mean_returns=(-0.001, 0.0, 0.001),
            long_short_mean_return=0.002,
            long_short_sharpe=1.0,
            mean_one_way_turnover=0.2,
            periods=80,
        ),
        coverage=0.99,
    )


def test_builder_resolves_frozen_selection_in_selection_order() -> None:
    momentum = _artifact("momentum", "simple_return_1")
    volume = _artifact("volume", "log_volume_change_1")
    report = FactorQuantFamilyReport(
        data_version="factor-v2",
        split_name="development",
        primary_label="forward_simple_return_1",
        candidates=(_candidate(momentum, 1.2), _candidate(volume, 0.8)),
        factor_value_correlations={
            "|".join(sorted((momentum.digest, volume.digest))): 0.15,
        },
    )
    selection = FactorEnsembleSelection(
        report_id=report.report_id,
        primary_label=report.primary_label,
        quality_metric="rank_icir",
        components=(
            FactorEnsembleComponentSelection(
                feature_id=volume.spec.feature_id,
                feature_digest=volume.digest,
                quality_score=0.8,
                weight=0.4,
            ),
            FactorEnsembleComponentSelection(
                feature_id=momentum.spec.feature_id,
                feature_digest=momentum.digest,
                quality_score=1.2,
                weight=0.6,
            ),
        ),
    )

    model = FactorEnsembleModelBuilder().build(
        report=report,
        selection=selection,
        candidates=(momentum, volume),
        min_observations=10,
    )

    assert tuple(artifact.digest for artifact in model.artifacts) == (
        volume.digest,
        momentum.digest,
    )
    assert model.weights == (0.4, 0.6)
    assert model.label_name == "forward_simple_return_1"
    assert model.required_features == ("log_volume_change_1", "simple_return_1")


def test_builder_rejects_candidate_denominator_drift() -> None:
    momentum = _artifact("momentum", "simple_return_1")
    volume = _artifact("volume", "log_volume_change_1")
    report = FactorQuantFamilyReport(
        data_version="factor-v2",
        split_name="development",
        primary_label="forward_simple_return_1",
        candidates=(_candidate(momentum, 1.2), _candidate(volume, 0.8)),
        factor_value_correlations={},
    )
    selection = FactorEnsembleSelection(
        report_id=report.report_id,
        primary_label=report.primary_label,
        quality_metric="rank_icir",
        components=(
            FactorEnsembleComponentSelection(
                feature_id=momentum.spec.feature_id,
                feature_digest=momentum.digest,
                quality_score=1.2,
                weight=1.0,
            ),
        ),
    )

    with pytest.raises(ValueError, match="candidate denominator"):
        FactorEnsembleModelBuilder().build(
            report=report,
            selection=selection,
            candidates=(momentum,),
        )

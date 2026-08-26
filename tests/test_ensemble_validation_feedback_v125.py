from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from finagent.agents.domain import AgentTask
from finagent.agents.generated_features import (
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
)
from finagent.backtest.market_study import MarketStudyConfig
from finagent.data import InMemoryPriceDataAdapter
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiment_family import ExperimentFamily, ExperimentFamilyStatus
from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentSpec
from finagent.domain.market import PriceBar
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.research import (
    AgentFactorDiscoveryConfig,
    AgentFactorQuantDiscoveryLoop,
    AgentMarketResearchConfig,
    FactorEnsembleFormalValidator,
    FactorEnsembleSelectionConfig,
    FactorEnsembleSelector,
    FactorEnsembleValidationEvidenceBuilder,
    FactorQuantAnalyzer,
    FactorQuantConfig,
    FactorQuantFeedbackAwareMarketFeatureCandidateGenerator,
    SQLiteResearchRegistry,
)


NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)


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
            description=f"FinAgent 1.2.5 factor {feature_id}",
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


def _adapter(days: int = 125):
    assets = tuple(
        AssetId(symbol, AssetType.ETF, venue="ARCX", currency="USD")
        for symbol in ("SPY", "QQQ", "IWM", "DIA", "XLK")
    )
    start = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    histories = {}
    for asset_index, asset in enumerate(assets):
        price = 90.0 + 11.0 * asset_index
        bars = []
        for day in range(days):
            event_time = start + timedelta(days=day)
            persistent = 0.0028 * np.sin(day / 5.0 + asset_index * 0.70)
            cross_section = 0.00045 * (asset_index - 2)
            volume_signal = 0.0005 * np.cos(day / 4.0 + asset_index * 0.35)
            price *= 1.0 + cross_section + persistent + volume_signal
            volume = 1_300_000.0 * (
                1.0
                + 0.12 * np.cos(day / 6.0 + asset_index * 0.8)
                + 0.02 * asset_index
            )
            bars.append(
                PriceBar(
                    event_time=event_time,
                    available_at=event_time + timedelta(hours=6, minutes=30),
                    open=price * (0.9985 + 0.0001 * asset_index),
                    high=price * 1.004,
                    low=price * 0.996,
                    close=price,
                    volume=volume,
                )
            )
        histories[asset] = tuple(bars)
    return InMemoryPriceDataAdapter(histories, data_version="ensemble-v125-test"), assets, start


def _candidates() -> tuple[GeneratedFeatureArtifact, GeneratedFeatureArtifact]:
    momentum = _artifact(
        "momentum-v125",
        'def compute_feature(inputs):\n    return inputs["simple_return_1"]\n',
        hypothesis="short-horizon return continuation",
        input_fields=("simple_return_1",),
    )
    volume = _artifact(
        "volume-v125",
        'def compute_feature(inputs):\n    return inputs["log_volume_change_1"]\n',
        hypothesis="volume change confirms next-period cross-sectional returns",
        input_fields=("log_volume_change_1",),
        lookback=4,
    )
    return momentum, volume


def _development_request(universe, start) -> DatasetRequest:
    available_start = start + timedelta(hours=6, minutes=30)
    return DatasetRequest(
        universe=universe,
        features=("simple_return_1", "log_volume_change_1"),
        labels=("forward_simple_return_1", "forward_simple_return_3"),
        splits={
            "development": TimeRange(
                available_start + timedelta(days=10),
                available_start + timedelta(days=55),
            )
        },
        dataset_id="factor-quant-v125-development",
        metadata={"scope": "development-only"},
    )


def _analyzer(adapter) -> FactorQuantAnalyzer:
    return FactorQuantAnalyzer(
        adapter,
        config=FactorQuantConfig(
            split_name="development",
            primary_label="forward_simple_return_1",
            decay_labels=("forward_simple_return_3",),
            quantiles=3,
            min_cross_section=5,
            min_periods=15,
        ),
    )


class _SequentialGenerator:
    def __init__(self, artifacts: tuple[GeneratedFeatureArtifact, ...]) -> None:
        self.artifacts = artifacts
        self.calls = 0
        self.tasks: list[AgentTask] = []

    def generate(self, *, task, count, approved_input_fields, smoke_inputs):
        assert count == 1
        assert set(approved_input_fields) == set(smoke_inputs)
        self.tasks.append(task)
        artifact = self.artifacts[self.calls]
        self.calls += 1
        return (artifact,)


def test_factor_quant_feedback_v2_is_cumulative_and_development_only() -> None:
    adapter, universe, start = _adapter()
    candidates = _candidates()
    request = _development_request(universe, start)
    base = _SequentialGenerator(candidates)
    loop = AgentFactorQuantDiscoveryLoop(
        generator=FactorQuantFeedbackAwareMarketFeatureCandidateGenerator(base),
        analyzer=_analyzer(adapter),
        selector=FactorEnsembleSelector(
            FactorEnsembleSelectionConfig(
                max_factors=2,
                max_abs_factor_correlation=1.0,
                quality_metric="rank_icir",
            )
        ),
        config=AgentFactorDiscoveryConfig(
            rounds=2,
            candidates_per_round=1,
            max_total_candidates=2,
        ),
    )
    result = loop.run(
        task=AgentTask(
            task_id="factor-quant-v125",
            objective="discover complementary PIT factors",
            created_at=NOW,
        ),
        request=request,
        approved_input_fields=("simple_return_1", "log_volume_change_1"),
        smoke_inputs={
            "simple_return_1": [0.01, -0.02, 0.03, 0.01],
            "log_volume_change_1": [0.02, 0.01, -0.01, 0.03],
        },
    )

    assert len(result.rounds) == 2
    assert len(result.rounds[0].cumulative_report.candidates) == 1
    assert len(result.rounds[1].cumulative_report.candidates) == 2
    assert {item.feature_digest for item in result.final_report.candidates} == {
        artifact.digest for artifact in candidates
    }
    assert len(base.tasks) == 2
    assert "DEVELOPMENT-ONLY FACTOR QUANT FEEDBACK V2" in base.tasks[1].objective
    assert "sealed-holdout" in base.tasks[1].objective
    assert result.rounds[0].feedback.development_data_id == result.development_data_id
    assert result.rounds[1].feedback.development_data_id == result.development_data_id
    assert set(result.final_feedback.candidates[0].to_dict()) >= {
        "horizons",
        "quantile_monotonicity",
        "long_short_sharpe",
        "mean_one_way_turnover",
        "coverage",
        "max_abs_factor_correlation",
    }
    for candidate in result.final_feedback.candidates:
        assert {item.label_name for item in candidate.horizons} == {
            "forward_simple_return_1",
            "forward_simple_return_3",
        }
        assert 0.0 <= candidate.quantile_monotonicity <= 1.0
        assert candidate.mean_one_way_turnover >= 0.0
        assert 0.0 <= candidate.coverage <= 1.0
    assert np.isclose(sum(result.final_selection.weights), 1.0)
    payload = result.final_feedback.to_dict()
    assert payload["schema_version"] == "finagent.factor-quant-agent-feedback.v2"
    assert "outer_metrics" not in payload
    assert "holdout_metrics" not in payload
    assert payload["scope"].startswith("development_only")


def _registry(tmp_path, candidates, universe):
    registry = SQLiteResearchRegistry(tmp_path / "ensemble-v125-registry.sqlite")
    dataset = ArtifactRef(
        artifact_id="v125-dataset",
        artifact_type=ArtifactType.DATASET,
        version="v1",
        digest="d" * 64,
    )
    registry.register_family(
        ExperimentFamily(
            family_id="factor-v125-family",
            research_question="do generated factors or their frozen ensemble generalize?",
            primary_metric="portfolio_sharpe",
            created_at=NOW,
            alpha=0.20,
        )
    )
    for index, artifact in enumerate(candidates):
        experiment_id = f"factor-v125-exp-{index + 1:02d}"
        registry.register_experiment(
            ExperimentSpec(
                experiment_id=experiment_id,
                hypothesis=artifact.spec.hypothesis,
                dataset=dataset,
                code=artifact.code_artifact_ref(),
                universe=universe,
                parameters={"feature_id": artifact.spec.feature_id},
                seed=0,
                metadata={"generated_feature_digest": artifact.digest},
            )
        )
        registry.add_experiment_to_family(
            "factor-v125-family",
            experiment_id,
            added_at=NOW + timedelta(seconds=index),
        )
    registry.transition_family("factor-v125-family", ExperimentFamilyStatus.FROZEN)
    return registry, dataset


def _formal_config() -> AgentMarketResearchConfig:
    return AgentMarketResearchConfig(
        max_candidates=4,
        family_alpha=0.20,
        label_name="forward_simple_return_1",
        transaction_cost_bps=2.0,
        min_cross_section=3,
        min_periods=4,
        market=MarketStudyConfig(
            outer_train_size=18,
            outer_test_size=6,
            outer_step_size=6,
            inner_train_size=10,
            inner_test_size=4,
            inner_step_size=4,
            purge_bars=1,
            embargo_bars=1,
            initial_cash=100_000.0,
            lookback=5,
            rebalance_every=1,
            execution_lag_events=1,
            cash_weight=0.10,
            max_weight=0.50,
            commission_bps=0.5,
            slippage_bps=0.5,
            impact_bps=0.5,
            max_participation_rate=0.50,
            garch_min_observations=10,
            correlation_lookback=5,
            ar_min_observations=10,
            risk_aversion=10.0,
            turnover_penalty=0.0,
        ),
    )


def test_formal_ensemble_validation_compares_k_singles_plus_one_model_level_ensemble(tmp_path) -> None:
    adapter, universe, start = _adapter()
    candidates = _candidates()
    development_request = _development_request(universe, start)
    analyzer = _analyzer(adapter)
    report = analyzer.analyze(candidates, request=development_request)
    selection = FactorEnsembleSelector(
        FactorEnsembleSelectionConfig(
            max_factors=2,
            max_abs_factor_correlation=1.0,
            quality_metric="rank_icir",
        )
    ).select(report)
    assert len(selection.components) == 2
    registry, dataset_artifact = _registry(tmp_path, candidates, universe)
    available_start = start + timedelta(hours=6, minutes=30)
    config = _formal_config()

    evidence = FactorEnsembleValidationEvidenceBuilder(
        registry=registry,
        adapter=adapter,
        factor_quant_analyzer=analyzer,
        config=config,
    ).build(
        "factor-v125-family",
        report=report,
        selection=selection,
        candidates=candidates,
        development_request=development_request,
        universe=universe,
        validation_start=available_start + timedelta(days=60),
        validation_end=available_start + timedelta(days=90),
        dataset_artifact=dataset_artifact,
    )

    formal_order = tuple(
        item.experiment_id for item in registry.family_members("factor-v125-family")
    )
    assert evidence.single_experiment_order == formal_order
    assert evidence.trial_order[:2] == formal_order
    assert len(evidence.trials) == 3
    assert [item.trial_kind for item in evidence.trials] == ["single", "single", "ensemble"]
    assert evidence.ensemble_trial.feature_digests == selection.feature_digests
    assert evidence.ensemble_trial.weights == selection.weights
    assert evidence.factor_quant_report_id == report.report_id
    assert len(evidence.timestamps) == len(evidence.trials[0].returns)
    assert len(set(evidence.timestamps)) == len(evidence.timestamps)
    assert all(
        len(trial.returns) == len(evidence.timestamps)
        and np.isfinite(np.asarray(trial.returns, dtype=float)).all()
        for trial in evidence.trials
    )

    validation = FactorEnsembleFormalValidator(registry).validate(
        evidence,
        dsr_probability_threshold=0.50,
        pbo_threshold=1.0,
        pbo_blocks=4,
        bootstrap_samples=40,
        seed=11,
    )

    assert len(validation.trials) == 3
    assert validation.ensemble_validation.trial_kind == "ensemble"
    assert all(item.deflated_sharpe.n_trials == 3 for item in validation.trials)
    assert validation.incremental_comparison.best_single_trial_id in formal_order
    assert 0.0 <= validation.incremental_comparison.paired_one_sided_pvalue <= 1.0
    assert np.isfinite(validation.incremental_comparison.sharpe_improvement)
    assert np.isfinite(validation.incremental_comparison.mean_return_improvement)
    assert validation.factor_quant_report_id == report.report_id
    assert validation.selection_id == evidence.selection_id
    assert validation.evidence_id == evidence.evidence_id
    payload = validation.to_dict()
    assert payload["denominator_size"] == 3
    assert payload["scope"].startswith("governance-only")


def test_ensemble_validation_rejects_development_report_or_candidate_denominator_drift(tmp_path) -> None:
    adapter, universe, start = _adapter()
    candidates = _candidates()
    request = _development_request(universe, start)
    analyzer = _analyzer(adapter)
    report = analyzer.analyze(candidates, request=request)
    selection = FactorEnsembleSelector(
        FactorEnsembleSelectionConfig(
            max_factors=2,
            max_abs_factor_correlation=1.0,
        )
    ).select(report)
    registry, dataset_artifact = _registry(tmp_path, candidates, universe)
    available_start = start + timedelta(hours=6, minutes=30)
    builder = FactorEnsembleValidationEvidenceBuilder(
        registry=registry,
        adapter=adapter,
        factor_quant_analyzer=analyzer,
        config=_formal_config(),
    )

    try:
        builder.build(
            "factor-v125-family",
            report=report,
            selection=selection,
            candidates=(candidates[0],),
            development_request=request,
            universe=universe,
            validation_start=available_start + timedelta(days=60),
            validation_end=available_start + timedelta(days=90),
            dataset_artifact=dataset_artifact,
        )
    except ValueError as exc:
        message = str(exc)
        assert any(token in message for token in ("report", "denominator", "selection", "family"))
    else:  # pragma: no cover - fail closed assertion
        raise AssertionError("candidate denominator drift must be rejected")

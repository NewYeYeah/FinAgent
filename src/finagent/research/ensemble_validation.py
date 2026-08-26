from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

import numpy as np

from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.backtest.timed import TimedBacktestConfig, TimedEventDrivenBacktestEngine
from finagent.backtest.walk_forward import PurgedWalkForwardSplitter, WalkForwardConfig
from finagent.domain._validation import require_aware_datetime, require_non_empty
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiment_family import ExperimentFamilyStatus
from finagent.domain.experiments import ArtifactRef
from finagent.domain.research import DatasetRequest
from finagent.models.alpha import GeneratedFeatureAlphaModel
from finagent.models.risk import GARCH11RiskModel
from finagent.portfolio import MeanVarianceConfig, MeanVarianceOptimizer
from finagent.services import StaticRiskGate, TimedSimulatedExchange

from .agent_market import AgentMarketResearchConfig, one_sided_mean_pvalue
from .factor_ensemble import FactorEnsembleModelBuilder
from .factor_feedback_v2 import factor_ensemble_selection_id
from .factor_quant import FactorEnsembleSelection, FactorQuantAnalyzer, FactorQuantFamilyReport
from .registry import SQLiteResearchRegistry
from .validation import (
    DeflatedSharpeResult,
    MultipleTestingResult,
    PBOResult,
    RealityCheckResult,
    adjust_pvalues,
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_ratio,
    whites_reality_check,
)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _period_returns(result, initial_cash: float) -> tuple[float, ...]:
    nav = np.asarray([initial_cash, *(point.nav for point in result.points)], dtype=float)
    return tuple(float(value) for value in nav[1:] / nav[:-1] - 1.0)


def _validation_data_id(
    *,
    data_version: str,
    universe: tuple[AssetId, ...],
    start: datetime,
    end: datetime,
    label_name: str,
    report_id: str,
    selection_id: str,
    config: AgentMarketResearchConfig,
) -> str:
    market = config.market
    payload = {
        "data_version": data_version,
        "universe": [asset.key for asset in universe],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "label_name": label_name,
        "report_id": report_id,
        "selection_id": selection_id,
        "outer": {
            "train_size": market.outer_train_size,
            "test_size": market.outer_test_size,
            "step_size": market.outer_step_size,
            "purge_bars": market.purge_bars,
            "embargo_bars": market.embargo_bars,
        },
        "portfolio": {
            "lookback": market.lookback,
            "rebalance_every": market.rebalance_every,
            "execution_lag_events": market.execution_lag_events,
            "cash_weight": market.cash_weight,
            "max_weight": market.max_weight,
            "commission_bps": market.commission_bps,
            "slippage_bps": market.slippage_bps,
            "impact_bps": market.impact_bps,
            "max_participation_rate": market.max_participation_rate,
            "risk_aversion": market.risk_aversion,
            "turnover_penalty": market.turnover_penalty,
        },
    }
    digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:24]
    return f"factor-ensemble-validation-data-{digest}"


@dataclass(frozen=True, slots=True)
class FactorPortfolioTrialEvidence:
    trial_id: str
    trial_kind: str
    feature_digests: tuple[str, ...]
    weights: tuple[float, ...]
    returns: tuple[float, ...]
    gross_traded_weight: float
    transaction_cost: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "trial_id", require_non_empty(self.trial_id, "trial_id"))
        if self.trial_kind not in {"single", "ensemble"}:
            raise ValueError("trial_kind must be single or ensemble")
        if not self.feature_digests or len(set(self.feature_digests)) != len(self.feature_digests):
            raise ValueError("feature_digests must be non-empty and unique")
        weights = tuple(float(value) for value in self.weights)
        if len(weights) != len(self.feature_digests):
            raise ValueError("trial weights must match feature_digests")
        if any(not math.isfinite(value) or value < 0 for value in weights):
            raise ValueError("trial weights must be finite and non-negative")
        if abs(sum(weights) - 1.0) > 1e-9:
            raise ValueError("trial weights must sum to one")
        returns = tuple(float(value) for value in self.returns)
        if len(returns) < 2 or not np.isfinite(np.asarray(returns, dtype=float)).all():
            raise ValueError("trial returns must contain at least two finite observations")
        if not math.isfinite(self.gross_traded_weight) or self.gross_traded_weight < 0:
            raise ValueError("gross_traded_weight must be finite and >= 0")
        if not math.isfinite(self.transaction_cost) or self.transaction_cost < 0:
            raise ValueError("transaction_cost must be finite and >= 0")
        if self.trial_kind == "single" and len(self.feature_digests) != 1:
            raise ValueError("single trial must reference exactly one feature")
        if self.trial_kind == "ensemble" and len(self.feature_digests) < 2:
            raise ValueError("ensemble validation requires at least two selected factors")
        object.__setattr__(self, "weights", weights)
        object.__setattr__(self, "returns", returns)

    @property
    def mean_return(self) -> float:
        return float(np.mean(np.asarray(self.returns, dtype=float)))

    @property
    def sharpe(self) -> float:
        return float(sharpe_ratio(np.asarray(self.returns, dtype=float)))

    def to_dict(self, *, include_returns: bool = False) -> dict[str, object]:
        payload: dict[str, object] = {
            "trial_id": self.trial_id,
            "trial_kind": self.trial_kind,
            "feature_digests": list(self.feature_digests),
            "weights": list(self.weights),
            "observations": len(self.returns),
            "mean_return": self.mean_return,
            "sharpe": self.sharpe,
            "gross_traded_weight": self.gross_traded_weight,
            "transaction_cost": self.transaction_cost,
        }
        if include_returns:
            payload["returns"] = list(self.returns)
        return payload


@dataclass(frozen=True, slots=True)
class FactorEnsembleValidationEvidence:
    source_family_id: str
    factor_quant_report_id: str
    selection_id: str
    validation_data_id: str
    data_version: str
    label_name: str
    timestamps: tuple[str, ...]
    single_experiment_order: tuple[str, ...]
    trials: tuple[FactorPortfolioTrialEvidence, ...]

    def __post_init__(self) -> None:
        for name in (
            "source_family_id",
            "factor_quant_report_id",
            "selection_id",
            "validation_data_id",
            "data_version",
            "label_name",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if not self.timestamps or len(set(self.timestamps)) != len(self.timestamps):
            raise ValueError("validation timestamps must be non-empty and non-overlapping")
        if not self.single_experiment_order:
            raise ValueError("single_experiment_order cannot be empty")
        if len(set(self.single_experiment_order)) != len(self.single_experiment_order):
            raise ValueError("single_experiment_order cannot contain duplicates")
        if not self.trials or len({trial.trial_id for trial in self.trials}) != len(self.trials):
            raise ValueError("validation trials must be non-empty and unique")
        expected_observations = len(self.timestamps)
        if any(len(trial.returns) != expected_observations for trial in self.trials):
            raise ValueError("all validation trials must align to the common timestamp denominator")
        singles = tuple(trial.trial_id for trial in self.trials if trial.trial_kind == "single")
        if singles != self.single_experiment_order:
            raise ValueError("single trial order must exactly match the frozen experiment order")
        ensembles = [trial for trial in self.trials if trial.trial_kind == "ensemble"]
        if len(ensembles) != 1:
            raise ValueError("validation evidence must contain exactly one ensemble trial")

    @property
    def trial_order(self) -> tuple[str, ...]:
        return tuple(trial.trial_id for trial in self.trials)

    @property
    def ensemble_trial(self) -> FactorPortfolioTrialEvidence:
        return next(trial for trial in self.trials if trial.trial_kind == "ensemble")

    @property
    def evidence_id(self) -> str:
        payload = self.to_dict(include_returns=True, include_id=False)
        digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:24]
        return f"factor-ensemble-validation-evidence-{digest}"

    def to_dict(
        self,
        *,
        include_returns: bool = False,
        include_id: bool = True,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.factor-ensemble-validation-evidence.v1",
            "source_family_id": self.source_family_id,
            "factor_quant_report_id": self.factor_quant_report_id,
            "selection_id": self.selection_id,
            "validation_data_id": self.validation_data_id,
            "data_version": self.data_version,
            "label_name": self.label_name,
            "timestamps": list(self.timestamps),
            "single_experiment_order": list(self.single_experiment_order),
            "trial_order": list(self.trial_order),
            "trials": [trial.to_dict(include_returns=include_returns) for trial in self.trials],
            "scope": (
                "independent model-level outer validation; all single generated-factor AlphaModels "
                "and one frozen development-selected ensemble share identical folds, risk model, "
                "optimizer, next-open execution and transaction-cost semantics"
            ),
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


class FactorEnsembleValidationEvidenceBuilder:
    """Build aligned independent OOS portfolio evidence for singles and one ensemble."""

    VERSION = "factor-ensemble-validation-evidence-builder-v1"

    def __init__(
        self,
        *,
        registry: SQLiteResearchRegistry,
        adapter,
        factor_quant_analyzer: FactorQuantAnalyzer,
        config: AgentMarketResearchConfig | None = None,
    ) -> None:
        self.registry = registry
        self.adapter = adapter
        self.factor_quant_analyzer = factor_quant_analyzer
        self.config = config or AgentMarketResearchConfig()
        if self.factor_quant_analyzer.adapter.data_version != self.adapter.data_version:
            raise ValueError("Factor Quant and validation adapters must share data_version")

    def _formal_artifacts(
        self,
        family_id: str,
        candidates: tuple[GeneratedFeatureArtifact, ...],
        universe: tuple[AssetId, ...],
        dataset_artifact: ArtifactRef | None,
    ) -> tuple[tuple[str, GeneratedFeatureArtifact], ...]:
        family = self.registry.get_family(family_id)
        if family.status is not ExperimentFamilyStatus.FROZEN:
            raise ValueError("source ExperimentFamily must be FROZEN before ensemble validation")
        members = self.registry.family_members(family_id)
        experiment_order = tuple(member.experiment_id for member in members)
        if not experiment_order:
            raise ValueError("source ExperimentFamily has no registered members")
        by_digest = {artifact.digest: artifact for artifact in candidates}
        if len(by_digest) != len(candidates):
            raise ValueError("candidate artifacts contain duplicate digests")
        resolved: list[tuple[str, GeneratedFeatureArtifact]] = []
        for experiment_id in experiment_order:
            spec = self.registry.get_experiment(experiment_id)
            digest = str(spec.metadata.get("generated_feature_digest", "")).strip()
            if not digest or digest not in by_digest:
                raise ValueError("candidate artifacts do not match frozen family membership")
            artifact = by_digest[digest]
            if spec.code.digest != artifact.code_artifact_ref().digest:
                raise ValueError("candidate code digest does not match formal ExperimentSpec")
            if tuple(spec.universe) != tuple(universe):
                raise ValueError("validation universe does not match formal ExperimentSpec")
            if dataset_artifact is not None and spec.dataset != dataset_artifact:
                raise ValueError("dataset artifact does not match formal ExperimentSpec")
            resolved.append((experiment_id, artifact))
        if {artifact.digest for _, artifact in resolved} != set(by_digest):
            raise ValueError("candidate artifacts contain members outside frozen ExperimentFamily")
        return tuple(resolved)

    def _outer_splitter(self) -> PurgedWalkForwardSplitter:
        market = self.config.market
        return PurgedWalkForwardSplitter(
            WalkForwardConfig(
                train_size=market.outer_train_size,
                test_size=market.outer_test_size,
                step_size=market.outer_step_size,
                purge_bars=market.purge_bars,
                embargo_bars=market.embargo_bars,
            )
        )

    def _run_trial(
        self,
        *,
        dataset,
        alpha_model,
        lookback: int,
    ):
        market = self.config.market
        risk = GARCH11RiskModel(
            min_observations=market.garch_min_observations,
            correlation_lookback=market.correlation_lookback,
        )
        optimizer = MeanVarianceOptimizer(
            MeanVarianceConfig(
                risk_aversion=market.risk_aversion,
                cash_weight=market.cash_weight,
                long_only=True,
                max_abs_weight=market.max_weight,
                turnover_penalty=market.turnover_penalty,
            )
        )
        gate = StaticRiskGate(
            max_gross_exposure=1.0,
            max_abs_weight=market.max_weight,
            min_cash_weight=market.cash_weight - 1e-9,
        )
        engine = TimedEventDrivenBacktestEngine(
            self.adapter,
            self.adapter,
            config=TimedBacktestConfig(
                train_split="train",
                test_split="test",
                initial_cash=market.initial_cash,
                lookback=max(market.lookback, lookback),
                rebalance_every=market.rebalance_every,
                execution_lag_events=market.execution_lag_events,
                execution_price_field="open",
                annualization_factor=252.0,
            ),
            exchange=TimedSimulatedExchange(
                slippage_bps=market.slippage_bps,
                commission_bps=market.commission_bps,
                impact_bps=market.impact_bps,
                max_participation_rate=market.max_participation_rate,
            ),
        )
        return engine.run(dataset, alpha_model, risk, optimizer, gate)

    def build(
        self,
        family_id: str,
        *,
        report: FactorQuantFamilyReport,
        selection: FactorEnsembleSelection,
        candidates: Sequence[GeneratedFeatureArtifact],
        development_request: DatasetRequest,
        universe: tuple[AssetId, ...],
        validation_start: datetime,
        validation_end: datetime,
        dataset_artifact: ArtifactRef | None = None,
    ) -> FactorEnsembleValidationEvidence:
        validation_start = require_aware_datetime(validation_start, "validation_start")
        validation_end = require_aware_datetime(validation_end, "validation_end")
        if validation_end <= validation_start:
            raise ValueError("validation_end must be later than validation_start")
        artifacts = tuple(candidates)
        if len(universe) < 2 or len(set(universe)) != len(universe):
            raise ValueError("ensemble validation requires at least two unique assets")
        if any(asset.asset_type not in {AssetType.EQUITY, AssetType.ETF} for asset in universe):
            raise ValueError("ensemble validation supports EQUITY/ETF research identities")
        if len({asset.currency for asset in universe}) != 1:
            raise ValueError("ensemble validation requires a single base currency")
        if tuple(development_request.universe) != tuple(universe):
            raise ValueError("development and validation universes must match")
        if report.data_version != self.adapter.data_version:
            raise ValueError("Factor Quant report data_version differs from validation adapter")
        if report.primary_label != self.config.label_name:
            raise ValueError("Factor Quant report label differs from validation label contract")
        if selection.report_id != report.report_id:
            raise ValueError("ensemble selection does not belong to Factor Quant report")
        if selection.primary_label != report.primary_label:
            raise ValueError("ensemble selection label differs from Factor Quant report")
        if len(selection.components) < 2:
            raise ValueError("formal ensemble comparison requires at least two selected factors")
        if report.split_name not in development_request.splits:
            raise KeyError(f"development request has no split {report.split_name!r}")
        development_end = development_request.splits[report.split_name].end
        if development_end > validation_start:
            raise ValueError("development evidence overlaps independent ensemble validation")

        recomputed = self.factor_quant_analyzer.analyze(artifacts, request=development_request)
        if recomputed.report_id != report.report_id:
            raise ValueError("supplied Factor Quant report is not reproducible from development data")
        formal_artifacts = self._formal_artifacts(
            family_id,
            artifacts,
            universe,
            dataset_artifact,
        )
        report_digests = {candidate.feature_digest for candidate in report.candidates}
        if report_digests != {artifact.digest for _, artifact in formal_artifacts}:
            raise ValueError("Factor Quant denominator differs from frozen formal family")

        market = self.config.market
        outer_splitter = self._outer_splitter()
        calendar = self.adapter.calendar(validation_start, validation_end, universe)
        outer_folds = outer_splitter.split(calendar, labels=(self.config.label_name,))
        risk_features = ("log_return_1", "squared_log_return_1")
        required_features = tuple(
            dict.fromkeys(
                field
                for artifact in artifacts
                for field in artifact.spec.input_fields
            )
        )
        required_features = tuple(dict.fromkeys((*required_features, *risk_features)))
        selection_id = factor_ensemble_selection_id(selection)
        ensemble_trial_id = f"ensemble:{selection_id}"
        trial_ids = tuple(experiment_id for experiment_id, _ in formal_artifacts) + (
            ensemble_trial_id,
        )
        trial_returns: dict[str, list[float]] = {trial_id: [] for trial_id in trial_ids}
        total_turnover: dict[str, float] = {trial_id: 0.0 for trial_id in trial_ids}
        total_cost: dict[str, float] = {trial_id: 0.0 for trial_id in trial_ids}
        canonical_timestamps: list[str] = []

        by_digest = {artifact.digest: artifact for artifact in artifacts}
        selected_artifacts = tuple(by_digest[digest] for digest in selection.feature_digests)
        for fold in outer_folds:
            dataset = self.adapter.build_dataset(
                DatasetRequest(
                    universe=universe,
                    features=required_features,
                    labels=(self.config.label_name,),
                    splits={"train": fold.train, "test": fold.test},
                    dataset_id=(
                        f"factor-ensemble-validation-{family_id}-outer-{fold.fold_index:03d}"
                    ),
                    metadata={
                        "source_family_id": family_id,
                        "factor_quant_report_id": report.report_id,
                        "factor_ensemble_selection_id": selection_id,
                        "validation_role": "independent_outer_model_comparison",
                    },
                )
            )
            fold_timestamps: tuple[str, ...] | None = None
            for experiment_id, artifact in formal_artifacts:
                alpha = GeneratedFeatureAlphaModel(
                    artifact,
                    label_name=self.config.label_name,
                    min_observations=max(10, market.ar_min_observations),
                )
                result = self._run_trial(
                    dataset=dataset,
                    alpha_model=alpha,
                    lookback=artifact.spec.lookback,
                )
                timestamps = tuple(point.information_at.isoformat() for point in result.points)
                if fold_timestamps is None:
                    fold_timestamps = timestamps
                elif timestamps != fold_timestamps:
                    raise RuntimeError("single-factor portfolio trials disagree on fold timestamps")
                trial_returns[experiment_id].extend(_period_returns(result, market.initial_cash))
                total_turnover[experiment_id] += float(result.total_turnover)
                total_cost[experiment_id] += float(result.total_transaction_cost)

            ensemble = FactorEnsembleModelBuilder().build(
                report=report,
                selection=selection,
                candidates=artifacts,
                min_observations=max(10, market.ar_min_observations),
            )
            ensemble_result = self._run_trial(
                dataset=dataset,
                alpha_model=ensemble,
                lookback=max(artifact.spec.lookback for artifact in selected_artifacts),
            )
            ensemble_timestamps = tuple(
                point.information_at.isoformat() for point in ensemble_result.points
            )
            if fold_timestamps is None or ensemble_timestamps != fold_timestamps:
                raise RuntimeError("ensemble portfolio timestamps differ from single-factor trials")
            trial_returns[ensemble_trial_id].extend(
                _period_returns(ensemble_result, market.initial_cash)
            )
            total_turnover[ensemble_trial_id] += float(ensemble_result.total_turnover)
            total_cost[ensemble_trial_id] += float(ensemble_result.total_transaction_cost)
            canonical_timestamps.extend(fold_timestamps)

        if not canonical_timestamps or len(set(canonical_timestamps)) != len(canonical_timestamps):
            raise ValueError("outer validation folds overlap or produced no aligned timestamps")
        trials: list[FactorPortfolioTrialEvidence] = []
        for experiment_id, artifact in formal_artifacts:
            trials.append(
                FactorPortfolioTrialEvidence(
                    trial_id=experiment_id,
                    trial_kind="single",
                    feature_digests=(artifact.digest,),
                    weights=(1.0,),
                    returns=tuple(trial_returns[experiment_id]),
                    gross_traded_weight=total_turnover[experiment_id],
                    transaction_cost=total_cost[experiment_id],
                )
            )
        trials.append(
            FactorPortfolioTrialEvidence(
                trial_id=ensemble_trial_id,
                trial_kind="ensemble",
                feature_digests=selection.feature_digests,
                weights=selection.weights,
                returns=tuple(trial_returns[ensemble_trial_id]),
                gross_traded_weight=total_turnover[ensemble_trial_id],
                transaction_cost=total_cost[ensemble_trial_id],
            )
        )
        return FactorEnsembleValidationEvidence(
            source_family_id=family_id,
            factor_quant_report_id=report.report_id,
            selection_id=selection_id,
            validation_data_id=_validation_data_id(
                data_version=self.adapter.data_version,
                universe=universe,
                start=validation_start,
                end=validation_end,
                label_name=self.config.label_name,
                report_id=report.report_id,
                selection_id=selection_id,
                config=self.config,
            ),
            data_version=self.adapter.data_version,
            label_name=self.config.label_name,
            timestamps=tuple(canonical_timestamps),
            single_experiment_order=tuple(
                experiment_id for experiment_id, _ in formal_artifacts
            ),
            trials=tuple(trials),
        )


@dataclass(frozen=True, slots=True)
class FactorModelStatisticalValidation:
    trial_id: str
    trial_kind: str
    raw_pvalue: float
    adjusted_pvalue: float
    multiplicity_rejected: bool
    observed_sharpe: float
    deflated_sharpe: DeflatedSharpeResult
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "trial_id": self.trial_id,
            "trial_kind": self.trial_kind,
            "raw_pvalue": self.raw_pvalue,
            "adjusted_pvalue": self.adjusted_pvalue,
            "multiplicity_rejected": self.multiplicity_rejected,
            "observed_sharpe": self.observed_sharpe,
            "deflated_sharpe": {
                "observed_sharpe": self.deflated_sharpe.observed_sharpe,
                "benchmark_sharpe": self.deflated_sharpe.benchmark_sharpe,
                "deflated_probability": self.deflated_sharpe.deflated_probability,
                "sample_size": self.deflated_sharpe.sample_size,
                "n_trials": self.deflated_sharpe.n_trials,
                "skewness": self.deflated_sharpe.skewness,
                "kurtosis": self.deflated_sharpe.kurtosis,
            },
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class FactorEnsembleIncrementalComparison:
    ensemble_trial_id: str
    best_single_trial_id: str
    ensemble_sharpe: float
    best_single_sharpe: float
    sharpe_improvement: float
    mean_return_improvement: float
    differential_information_ratio: float
    paired_one_sided_pvalue: float
    alpha: float

    @property
    def statistically_dominates(self) -> bool:
        return self.sharpe_improvement > 0 and self.paired_one_sided_pvalue <= self.alpha

    def to_dict(self) -> dict[str, object]:
        return {
            "ensemble_trial_id": self.ensemble_trial_id,
            "best_single_trial_id": self.best_single_trial_id,
            "ensemble_sharpe": self.ensemble_sharpe,
            "best_single_sharpe": self.best_single_sharpe,
            "sharpe_improvement": self.sharpe_improvement,
            "mean_return_improvement": self.mean_return_improvement,
            "differential_information_ratio": self.differential_information_ratio,
            "paired_one_sided_pvalue": self.paired_one_sided_pvalue,
            "alpha": self.alpha,
            "statistically_dominates": self.statistically_dominates,
        }


@dataclass(frozen=True, slots=True)
class FactorEnsembleStatisticalReport:
    source_family_id: str
    evidence_id: str
    factor_quant_report_id: str
    selection_id: str
    observation_count: int
    multiple_testing: MultipleTestingResult
    pbo: PBOResult
    reality_check: RealityCheckResult
    trials: tuple[FactorModelStatisticalValidation, ...]
    incremental_comparison: FactorEnsembleIncrementalComparison
    dsr_probability_threshold: float
    pbo_threshold: float
    validator_version: str = "factor-ensemble-formal-validation-v1"

    @property
    def ensemble_validation(self) -> FactorModelStatisticalValidation:
        return next(item for item in self.trials if item.trial_kind == "ensemble")

    @property
    def ensemble_passed(self) -> bool:
        return self.ensemble_validation.passed

    @property
    def ensemble_dominates_best_single(self) -> bool:
        return self.incremental_comparison.statistically_dominates

    @property
    def report_id(self) -> str:
        digest = hashlib.sha256(_canonical_json(self.to_dict(include_id=False)).encode()).hexdigest()
        return f"factor-ensemble-validation-{digest[:24]}"

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.factor-ensemble-statistical-report.v1",
            "validator_version": self.validator_version,
            "source_family_id": self.source_family_id,
            "evidence_id": self.evidence_id,
            "factor_quant_report_id": self.factor_quant_report_id,
            "selection_id": self.selection_id,
            "observation_count": self.observation_count,
            "denominator_size": len(self.trials),
            "multiple_testing": {
                "method": self.multiple_testing.method.value,
                "alpha": self.multiple_testing.alpha,
                "raw_pvalues": list(self.multiple_testing.raw_pvalues),
                "adjusted_pvalues": list(self.multiple_testing.adjusted_pvalues),
                "rejected": list(self.multiple_testing.rejected),
            },
            "pbo": {
                "probability_of_backtest_overfitting": self.pbo.probability_of_backtest_overfitting,
                "combinations_evaluated": self.pbo.combinations_evaluated,
                "blocks": self.pbo.blocks,
            },
            "reality_check": {
                "observed_statistic": self.reality_check.observed_statistic,
                "pvalue": self.reality_check.pvalue,
                "bootstrap_samples": self.reality_check.bootstrap_samples,
                "block_size": self.reality_check.block_size,
            },
            "trials": [item.to_dict() for item in self.trials],
            "incremental_comparison": self.incremental_comparison.to_dict(),
            "dsr_probability_threshold": self.dsr_probability_threshold,
            "pbo_threshold": self.pbo_threshold,
            "ensemble_passed": self.ensemble_passed,
            "ensemble_dominates_best_single": self.ensemble_dominates_best_single,
            "scope": (
                "governance-only independent validation; this report must not be supplied to "
                "adaptive factor-generation feedback"
            ),
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


class FactorEnsembleFormalValidator:
    """Evaluate the explicit K-single + 1-ensemble formal model denominator."""

    VERSION = "factor-ensemble-formal-validation-v1"

    def __init__(self, registry: SQLiteResearchRegistry) -> None:
        self.registry = registry

    def validate(
        self,
        evidence: FactorEnsembleValidationEvidence,
        *,
        dsr_probability_threshold: float = 0.95,
        pbo_threshold: float = 0.5,
        pbo_blocks: int = 8,
        bootstrap_samples: int = 1000,
        bootstrap_block_size: int | None = None,
        seed: int = 0,
    ) -> FactorEnsembleStatisticalReport:
        family = self.registry.get_family(evidence.source_family_id)
        if family.status is not ExperimentFamilyStatus.FROZEN:
            raise ValueError("source ExperimentFamily must remain FROZEN during validation")
        experiment_order = tuple(
            member.experiment_id for member in self.registry.family_members(evidence.source_family_id)
        )
        if evidence.single_experiment_order != experiment_order:
            raise ValueError("single-model validation denominator differs from frozen family")
        expected_trial_order = (*experiment_order, evidence.ensemble_trial.trial_id)
        if evidence.trial_order != expected_trial_order:
            raise ValueError("formal model denominator order is not canonical")
        if not 0.0 < dsr_probability_threshold < 1.0:
            raise ValueError("dsr_probability_threshold must be in (0, 1)")
        if not 0.0 <= pbo_threshold <= 1.0:
            raise ValueError("pbo_threshold must be in [0, 1]")

        matrix = np.column_stack(
            [np.asarray(trial.returns, dtype=float) for trial in evidence.trials]
        )
        raw_pvalues = tuple(one_sided_mean_pvalue(matrix[:, index]) for index in range(matrix.shape[1]))
        multiple = adjust_pvalues(
            raw_pvalues,
            method=family.correction_method,
            alpha=family.alpha,
        )
        trial_sharpes = tuple(sharpe_ratio(matrix[:, index]) for index in range(matrix.shape[1]))
        pbo = probability_of_backtest_overfitting(matrix, blocks=pbo_blocks)
        reality = whites_reality_check(
            matrix,
            bootstrap_samples=bootstrap_samples,
            block_size=bootstrap_block_size,
            seed=seed,
        )
        common_pass = (
            pbo.probability_of_backtest_overfitting <= pbo_threshold
            and reality.pvalue <= family.alpha
        )
        validations: list[FactorModelStatisticalValidation] = []
        for index, trial in enumerate(evidence.trials):
            dsr = deflated_sharpe_ratio(
                matrix[:, index],
                n_trials=matrix.shape[1],
                trial_sharpes=trial_sharpes,
            )
            passed = (
                multiple.rejected[index]
                and dsr.deflated_probability >= dsr_probability_threshold
                and common_pass
            )
            validations.append(
                FactorModelStatisticalValidation(
                    trial_id=trial.trial_id,
                    trial_kind=trial.trial_kind,
                    raw_pvalue=multiple.raw_pvalues[index],
                    adjusted_pvalue=multiple.adjusted_pvalues[index],
                    multiplicity_rejected=multiple.rejected[index],
                    observed_sharpe=float(trial_sharpes[index]),
                    deflated_sharpe=dsr,
                    passed=passed,
                )
            )

        single_count = len(experiment_order)
        best_single_index = min(
            range(single_count),
            key=lambda index: (-float(trial_sharpes[index]), experiment_order[index]),
        )
        ensemble_index = matrix.shape[1] - 1
        difference = matrix[:, ensemble_index] - matrix[:, best_single_index]
        comparison = FactorEnsembleIncrementalComparison(
            ensemble_trial_id=evidence.trials[ensemble_index].trial_id,
            best_single_trial_id=evidence.trials[best_single_index].trial_id,
            ensemble_sharpe=float(trial_sharpes[ensemble_index]),
            best_single_sharpe=float(trial_sharpes[best_single_index]),
            sharpe_improvement=float(
                trial_sharpes[ensemble_index] - trial_sharpes[best_single_index]
            ),
            mean_return_improvement=float(np.mean(difference)),
            differential_information_ratio=float(sharpe_ratio(difference)),
            paired_one_sided_pvalue=one_sided_mean_pvalue(difference),
            alpha=float(family.alpha),
        )
        return FactorEnsembleStatisticalReport(
            source_family_id=evidence.source_family_id,
            evidence_id=evidence.evidence_id,
            factor_quant_report_id=evidence.factor_quant_report_id,
            selection_id=evidence.selection_id,
            observation_count=len(evidence.timestamps),
            multiple_testing=multiple,
            pbo=pbo,
            reality_check=reality,
            trials=tuple(validations),
            incremental_comparison=comparison,
            dsr_probability_threshold=float(dsr_probability_threshold),
            pbo_threshold=float(pbo_threshold),
        )

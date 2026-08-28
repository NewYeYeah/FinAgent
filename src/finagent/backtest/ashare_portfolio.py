from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import MappingProxyType

import numpy as np
from scipy.stats import norm

from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.data.ashare_close import (
    AshareDailyCloseSnapshot,
    LocalAshareDailyCloseAdapter,
)
from finagent.data.ashare_execution import LocalAshareDailyExecutionAdapter
from finagent.domain._validation import require_non_empty
from finagent.domain.ashare_execution import (
    AshareAccountState,
    AshareExecutionCycle,
    AshareOrderDecisionStatus,
)
from finagent.domain.assets import AssetId
from finagent.domain.forecasts import AlphaForecast
from finagent.domain.portfolio import PortfolioState, PortfolioTarget
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.models.alpha.ashare_frozen import (
    AshareFrozenGeneratedFeatureAlphaModel,
)
from finagent.models.risk.shrinkage import HistoricalRiskForecastBuilder
from finagent.portfolio.mean_variance import MeanVarianceConfig, MeanVarianceOptimizer
from finagent.research.ashare_robust_program import (
    AshareExpandingWalkForwardPlan,
    AshareRobustFactorSelection,
)
from finagent.research.ashare_universe import AshareResearchUniverseProvider
from finagent.research.panel_feature_materializer import (
    PanelGeneratedFeatureMaterializer,
)
from finagent.services.ashare_execution import (
    AshareExecutionSession,
    AshareFeeSchedule,
    AshareInventoryLedger,
    AshareOrderCompiler,
    AshareOrderCompilerConfig,
)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(prefix: str, payload: object, length: int = 24) -> str:
    value = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:length]
    return f"{prefix}-{value}"


def _finite(value: float, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _newey_west_positive_mean_test(
    values: Sequence[float],
    lags: int,
) -> tuple[float, float]:
    array = np.asarray(tuple(values), dtype=float)
    if array.size < 2:
        return 0.0, 1.0
    centered = array - float(np.mean(array))
    count = array.size
    effective_lags = min(max(0, int(lags)), count - 1)
    long_run_variance = float(np.dot(centered, centered) / count)
    for lag in range(1, effective_lags + 1):
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / count)
        weight = 1.0 - lag / (effective_lags + 1.0)
        long_run_variance += 2.0 * weight * covariance
    long_run_variance = max(long_run_variance, 0.0)
    standard_error = (
        math.sqrt(long_run_variance / count)
        if long_run_variance > 1e-30
        else 0.0
    )
    if standard_error <= 1e-15:
        return 0.0, 1.0
    statistic = float(np.mean(array) / standard_error)
    return statistic, float(norm.sf(statistic))


def _circular_block_bootstrap_positive_mean(
    values: Sequence[float],
    *,
    samples: int,
    block_length: int,
    seed: int,
) -> tuple[float, float, float]:
    array = np.asarray(tuple(values), dtype=float)
    if array.size < 2:
        value = float(array[0]) if array.size else 0.0
        return 1.0, value, value
    count = array.size
    block = min(max(1, int(block_length)), count)
    blocks_needed = int(math.ceil(count / block))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, count, size=(samples, blocks_needed), endpoint=False)
    offsets = np.arange(block, dtype=int)
    indices = (starts[:, :, None] + offsets[None, None, :]) % count
    indices = indices.reshape(samples, -1)[:, :count]
    sample_means = np.mean(array[indices], axis=1)
    centered = array - float(np.mean(array))
    null_means = np.mean(centered[indices], axis=1)
    observed = float(np.mean(array))
    pvalue = float((1 + np.count_nonzero(null_means >= observed)) / (samples + 1))
    lower, upper = np.quantile(sample_means, (0.025, 0.975))
    return pvalue, float(lower), float(upper)


@dataclass(frozen=True, slots=True)
class AsharePortfolioValidationPolicy:
    min_net_annualized_return: float = 0.0
    min_net_sharpe: float = 0.0
    max_abs_drawdown: float = 0.35
    max_gross_to_net_return_drag: float = 0.10
    min_positive_fold_ratio: float = 0.50
    max_hac_pvalue: float = 0.10
    max_bootstrap_pvalue: float = 0.10
    max_rejected_order_ratio: float = 0.50
    max_ex_post_participation: float = 0.10
    max_cash_fallback_ratio: float = 0.25

    def __post_init__(self) -> None:
        values = (
            self.min_net_annualized_return,
            self.min_net_sharpe,
            self.max_abs_drawdown,
            self.max_gross_to_net_return_drag,
            self.min_positive_fold_ratio,
            self.max_hac_pvalue,
            self.max_bootstrap_pvalue,
            self.max_rejected_order_ratio,
            self.max_ex_post_participation,
            self.max_cash_fallback_ratio,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("A4 validation policy must be finite")
        bounded = (
            self.max_abs_drawdown,
            self.max_gross_to_net_return_drag,
            self.min_positive_fold_ratio,
            self.max_hac_pvalue,
            self.max_bootstrap_pvalue,
            self.max_rejected_order_ratio,
            self.max_ex_post_participation,
            self.max_cash_fallback_ratio,
        )
        if any(not 0.0 <= value <= 1.0 for value in bounded):
            raise ValueError("bounded A4 validation policy values must be in [0, 1]")

    def to_dict(self) -> dict[str, float]:
        return {
            "min_net_annualized_return": self.min_net_annualized_return,
            "min_net_sharpe": self.min_net_sharpe,
            "max_abs_drawdown": self.max_abs_drawdown,
            "max_gross_to_net_return_drag": self.max_gross_to_net_return_drag,
            "min_positive_fold_ratio": self.min_positive_fold_ratio,
            "max_hac_pvalue": self.max_hac_pvalue,
            "max_bootstrap_pvalue": self.max_bootstrap_pvalue,
            "max_rejected_order_ratio": self.max_rejected_order_ratio,
            "max_ex_post_participation": self.max_ex_post_participation,
            "max_cash_fallback_ratio": self.max_cash_fallback_ratio,
        }


@dataclass(frozen=True, slots=True)
class AsharePortfolioValidationConfig:
    initial_cash: float = 10_000_000.0
    rebalance_every: int = 5
    active_asset_count: int = 20
    min_active_assets: int = 5
    minimum_expected_return: float = 0.0
    risk_lookback: int = 120
    risk_min_observations: int = 60
    risk_aversion: float = 5.0
    target_cash_weight: float = 0.05
    max_asset_weight: float = 0.10
    optimizer_turnover_penalty: float = 0.01
    alpha_ridge: float = 1e-8
    alpha_min_observations: int = 250
    winsor_lower_quantile: float = 0.01
    winsor_upper_quantile: float = 0.99
    annualization: float = 252.0
    hac_lags: int = 5
    bootstrap_samples: int = 500
    bootstrap_block_length: int = 20
    bootstrap_seed: int = 20_260_828
    cash_fallback_on_model_error: bool = True
    policy: AsharePortfolioValidationPolicy = field(
        default_factory=AsharePortfolioValidationPolicy
    )

    def __post_init__(self) -> None:
        positive = (
            self.initial_cash,
            self.risk_aversion,
            self.max_asset_weight,
            self.annualization,
        )
        if any(not math.isfinite(value) or value <= 0 for value in positive):
            raise ValueError("positive A4 configuration values must be finite")
        integer_positive = (
            self.rebalance_every,
            self.active_asset_count,
            self.min_active_assets,
            self.risk_lookback,
            self.risk_min_observations,
            self.alpha_min_observations,
            self.bootstrap_samples,
            self.bootstrap_block_length,
        )
        if any(value < 1 for value in integer_positive):
            raise ValueError("integer A4 configuration values must be >= 1")
        if self.min_active_assets > self.active_asset_count:
            raise ValueError("min_active_assets cannot exceed active_asset_count")
        if self.risk_min_observations > self.risk_lookback:
            raise ValueError("risk_min_observations cannot exceed risk_lookback")
        if not 0.0 <= self.target_cash_weight < 1.0:
            raise ValueError("target_cash_weight must be in [0, 1)")
        if self.max_asset_weight * self.min_active_assets + 1e-12 < (
            1.0 - self.target_cash_weight
        ):
            raise ValueError(
                "max_asset_weight and min_active_assets cannot satisfy invested weight"
            )
        if self.optimizer_turnover_penalty < 0 or self.alpha_ridge < 0:
            raise ValueError("A4 penalties must be non-negative")
        if not math.isfinite(self.minimum_expected_return):
            raise ValueError("minimum_expected_return must be finite")
        if not 0.0 <= self.winsor_lower_quantile < self.winsor_upper_quantile <= 1.0:
            raise ValueError("invalid A4 winsorization quantiles")

    def to_dict(self) -> dict[str, object]:
        return {
            "initial_cash": self.initial_cash,
            "rebalance_every": self.rebalance_every,
            "active_asset_count": self.active_asset_count,
            "min_active_assets": self.min_active_assets,
            "minimum_expected_return": self.minimum_expected_return,
            "risk_lookback": self.risk_lookback,
            "risk_min_observations": self.risk_min_observations,
            "risk_aversion": self.risk_aversion,
            "target_cash_weight": self.target_cash_weight,
            "max_asset_weight": self.max_asset_weight,
            "optimizer_turnover_penalty": self.optimizer_turnover_penalty,
            "alpha_ridge": self.alpha_ridge,
            "alpha_min_observations": self.alpha_min_observations,
            "winsor_lower_quantile": self.winsor_lower_quantile,
            "winsor_upper_quantile": self.winsor_upper_quantile,
            "annualization": self.annualization,
            "hac_lags": self.hac_lags,
            "bootstrap_samples": self.bootstrap_samples,
            "bootstrap_block_length": self.bootstrap_block_length,
            "bootstrap_seed": self.bootstrap_seed,
            "cash_fallback_on_model_error": self.cash_fallback_on_model_error,
            "policy": self.policy.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AsharePortfolioValidationSpec:
    source_program_result_id: str
    source_report_digest: str
    source_program_spec_id: str
    source_selection_id: str
    data_version: str
    candidate_selection_id: str
    universe_policy_version: str
    plan_id: str
    reserve_id: str
    selected_feature_digests: tuple[str, ...]
    selected_weights: tuple[float, ...]
    selected_directions: tuple[int, ...]
    fee_schedule_id: str
    net_execution_config: Mapping[str, object]
    gross_execution_config: Mapping[str, object]
    validation_config: AsharePortfolioValidationConfig

    def __post_init__(self) -> None:
        for name in (
            "source_program_result_id",
            "source_report_digest",
            "source_program_spec_id",
            "source_selection_id",
            "data_version",
            "candidate_selection_id",
            "universe_policy_version",
            "plan_id",
            "reserve_id",
            "fee_schedule_id",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if len(set(self.selected_feature_digests)) != len(self.selected_feature_digests):
            raise ValueError("A4 selected factor digests must be unique")
        if not (
            len(self.selected_feature_digests)
            == len(self.selected_weights)
            == len(self.selected_directions)
        ):
            raise ValueError("A4 selected factor arrays must align")
        if any(value not in {-1, 1} for value in self.selected_directions):
            raise ValueError("A4 selected directions must be +/-1")
        if any(not math.isfinite(value) or value < 0 for value in self.selected_weights):
            raise ValueError("A4 selected weights must be finite and non-negative")
        if self.selected_feature_digests:
            if abs(sum(self.selected_weights) - 1.0) > 1e-9:
                raise ValueError("A4 selected weights must sum to one")
        elif self.selected_weights or self.selected_directions:
            raise ValueError("empty A4 factor family requires empty weights/directions")
        object.__setattr__(
            self,
            "net_execution_config",
            MappingProxyType(dict(self.net_execution_config)),
        )
        object.__setattr__(
            self,
            "gross_execution_config",
            MappingProxyType(dict(self.gross_execution_config)),
        )

    @property
    def spec_id(self) -> str:
        return _digest("ashare-portfolio-validation-spec", self.to_dict(False))

    def to_dict(self, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.ashare-portfolio-validation-spec.v1",
            "source_program_result_id": self.source_program_result_id,
            "source_report_digest": self.source_report_digest,
            "source_program_spec_id": self.source_program_spec_id,
            "source_selection_id": self.source_selection_id,
            "data_version": self.data_version,
            "candidate_selection_id": self.candidate_selection_id,
            "universe_policy_version": self.universe_policy_version,
            "plan_id": self.plan_id,
            "reserve_id": self.reserve_id,
            "selected_feature_digests": list(self.selected_feature_digests),
            "selected_weights": list(self.selected_weights),
            "selected_directions": list(self.selected_directions),
            "fee_schedule_id": self.fee_schedule_id,
            "net_execution_config": dict(self.net_execution_config),
            "gross_execution_config": dict(self.gross_execution_config),
            "validation_config": self.validation_config.to_dict(),
            "scope": "internal execution-aware walk-forward; reserve untouched",
        }
        if include_id:
            payload["spec_id"] = self.spec_id
        return payload


class SQLiteAsharePortfolioValidationSpecStore:
    """Immutable A4 portfolio-validation specification store."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ashare_portfolio_validation_specs (
                    source_program_result_id TEXT PRIMARY KEY,
                    spec_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def register(self, spec: AsharePortfolioValidationSpec) -> None:
        payload = _canonical_json(spec.to_dict())
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT spec_id, payload_json FROM ashare_portfolio_validation_specs "
                "WHERE source_program_result_id=?",
                (spec.source_program_result_id,),
            ).fetchone()
            if row is not None:
                if str(row[0]) != spec.spec_id or str(row[1]) != payload:
                    raise ValueError(
                        "A4 portfolio-validation specification is immutable for the "
                        "source ResearchProgram result"
                    )
                return
            connection.execute(
                "INSERT INTO ashare_portfolio_validation_specs VALUES (?, ?, ?)",
                (spec.source_program_result_id, spec.spec_id, payload),
            )


@dataclass(frozen=True, slots=True)
class AsharePortfolioMetrics:
    periods: int
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe: float
    max_drawdown: float

    def __post_init__(self) -> None:
        if self.periods < 1:
            raise ValueError("portfolio metrics require periods")
        values = (
            self.total_return,
            self.annualized_return,
            self.annualized_volatility,
            self.sharpe,
            self.max_drawdown,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("portfolio metrics must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "periods": self.periods,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "annualized_volatility": self.annualized_volatility,
            "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown,
        }


@dataclass(frozen=True, slots=True)
class AsharePortfolioPoint:
    session_date: date
    signal_asof: datetime
    rebalanced: bool
    cash_fallback: bool
    target_id: str
    net_nav: float
    gross_nav: float
    net_return: float
    gross_return: float
    fees: float
    slippage: float
    gross_traded_weight: float
    one_way_turnover: float
    target_turnover: float
    implementation_shortfall: float
    desired_order_count: int
    order_count: int
    fill_count: int
    rejected_order_count: int
    maximum_ex_post_participation: float
    reason_counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = (
            self.net_nav,
            self.gross_nav,
            self.net_return,
            self.gross_return,
            self.fees,
            self.slippage,
            self.gross_traded_weight,
            self.one_way_turnover,
            self.target_turnover,
            self.implementation_shortfall,
            self.maximum_ex_post_participation,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("A4 portfolio point metrics must be finite")
        if self.net_nav <= 0 or self.gross_nav <= 0:
            raise ValueError("A4 NAV must remain positive")
        counts = (
            self.desired_order_count,
            self.order_count,
            self.fill_count,
            self.rejected_order_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("A4 order counts must be non-negative")
        object.__setattr__(
            self,
            "reason_counts",
            MappingProxyType({str(key): int(value) for key, value in self.reason_counts.items()}),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "session_date": self.session_date.isoformat(),
            "signal_asof": self.signal_asof.isoformat(),
            "rebalanced": self.rebalanced,
            "cash_fallback": self.cash_fallback,
            "target_id": self.target_id,
            "net_nav": self.net_nav,
            "gross_nav": self.gross_nav,
            "net_return": self.net_return,
            "gross_return": self.gross_return,
            "fees": self.fees,
            "slippage": self.slippage,
            "gross_traded_weight": self.gross_traded_weight,
            "one_way_turnover": self.one_way_turnover,
            "target_turnover": self.target_turnover,
            "implementation_shortfall": self.implementation_shortfall,
            "desired_order_count": self.desired_order_count,
            "order_count": self.order_count,
            "fill_count": self.fill_count,
            "rejected_order_count": self.rejected_order_count,
            "maximum_ex_post_participation": self.maximum_ex_post_participation,
            "reason_counts": dict(self.reason_counts),
        }


@dataclass(frozen=True, slots=True)
class AsharePortfolioFoldResult:
    fold_id: str
    train_range: TimeRange
    test_range: TimeRange
    alpha_model_id: str
    alpha_calibration: Mapping[str, object]
    points: tuple[AsharePortfolioPoint, ...]
    net_metrics: AsharePortfolioMetrics
    gross_metrics: AsharePortfolioMetrics
    total_fees: float
    total_slippage: float
    total_gross_traded_weight: float
    total_one_way_turnover: float
    average_implementation_shortfall: float
    maximum_ex_post_participation: float
    reason_counts: Mapping[str, int]
    ledger_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "fold_id", require_non_empty(self.fold_id, "fold_id"))
        object.__setattr__(
            self,
            "alpha_model_id",
            require_non_empty(self.alpha_model_id, "alpha_model_id"),
        )
        object.__setattr__(
            self,
            "alpha_calibration",
            MappingProxyType(dict(self.alpha_calibration)),
        )
        object.__setattr__(
            self,
            "reason_counts",
            MappingProxyType({str(key): int(value) for key, value in self.reason_counts.items()}),
        )
        object.__setattr__(
            self,
            "ledger_digest",
            require_non_empty(self.ledger_digest, "ledger_digest"),
        )
        if not self.points:
            raise ValueError("A4 fold result requires points")

    def to_dict(self) -> dict[str, object]:
        return {
            "fold_id": self.fold_id,
            "train_range": [self.train_range.start.isoformat(), self.train_range.end.isoformat()],
            "test_range": [self.test_range.start.isoformat(), self.test_range.end.isoformat()],
            "alpha_model_id": self.alpha_model_id,
            "alpha_calibration": dict(self.alpha_calibration),
            "points": [point.to_dict() for point in self.points],
            "net_metrics": self.net_metrics.to_dict(),
            "gross_metrics": self.gross_metrics.to_dict(),
            "total_fees": self.total_fees,
            "total_slippage": self.total_slippage,
            "total_gross_traded_weight": self.total_gross_traded_weight,
            "total_one_way_turnover": self.total_one_way_turnover,
            "average_implementation_shortfall": self.average_implementation_shortfall,
            "maximum_ex_post_participation": self.maximum_ex_post_participation,
            "reason_counts": dict(self.reason_counts),
            "ledger_digest": self.ledger_digest,
        }


@dataclass(frozen=True, slots=True)
class AsharePortfolioAggregateResult:
    net_metrics: AsharePortfolioMetrics
    gross_metrics: AsharePortfolioMetrics
    gross_to_net_return_drag: float
    total_fees: float
    total_slippage: float
    total_gross_traded_weight: float
    total_one_way_turnover: float
    average_implementation_shortfall: float
    maximum_ex_post_participation: float
    positive_fold_ratio: float
    worst_fold_net_sharpe: float
    desired_order_count: int
    order_count: int
    fill_count: int
    rejected_order_count: int
    rejected_order_ratio: float
    rebalance_count: int
    cash_fallback_count: int
    cash_fallback_ratio: float
    hac_tstat: float
    hac_pvalue: float
    bootstrap_pvalue: float
    bootstrap_ci_lower: float
    bootstrap_ci_upper: float
    reason_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reason_counts",
            MappingProxyType({str(key): int(value) for key, value in self.reason_counts.items()}),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "net_metrics": self.net_metrics.to_dict(),
            "gross_metrics": self.gross_metrics.to_dict(),
            "gross_to_net_return_drag": self.gross_to_net_return_drag,
            "total_fees": self.total_fees,
            "total_slippage": self.total_slippage,
            "total_gross_traded_weight": self.total_gross_traded_weight,
            "total_one_way_turnover": self.total_one_way_turnover,
            "average_implementation_shortfall": self.average_implementation_shortfall,
            "maximum_ex_post_participation": self.maximum_ex_post_participation,
            "positive_fold_ratio": self.positive_fold_ratio,
            "worst_fold_net_sharpe": self.worst_fold_net_sharpe,
            "desired_order_count": self.desired_order_count,
            "order_count": self.order_count,
            "fill_count": self.fill_count,
            "rejected_order_count": self.rejected_order_count,
            "rejected_order_ratio": self.rejected_order_ratio,
            "rebalance_count": self.rebalance_count,
            "cash_fallback_count": self.cash_fallback_count,
            "cash_fallback_ratio": self.cash_fallback_ratio,
            "hac_tstat": self.hac_tstat,
            "hac_pvalue": self.hac_pvalue,
            "bootstrap_pvalue": self.bootstrap_pvalue,
            "bootstrap_ci_lower": self.bootstrap_ci_lower,
            "bootstrap_ci_upper": self.bootstrap_ci_upper,
            "reason_counts": dict(self.reason_counts),
        }


@dataclass(frozen=True, slots=True)
class AsharePortfolioValidationOutcome:
    status: str
    execution_validation_passed: bool
    promotion_eligible: bool
    reason_codes: tuple[str, ...]
    policy: AsharePortfolioValidationPolicy

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", require_non_empty(self.status, "status"))
        if not self.reason_codes:
            raise ValueError("A4 outcome requires reason codes")
        if self.promotion_eligible:
            raise ValueError("A4 internal validation cannot be promotion eligible")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "execution_validation_passed": self.execution_validation_passed,
            "promotion_eligible": self.promotion_eligible,
            "reason_codes": list(self.reason_codes),
            "policy": self.policy.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AsharePortfolioValidationResult:
    mode: str
    spec: AsharePortfolioValidationSpec
    source_research_status: str
    folds: tuple[AsharePortfolioFoldResult, ...]
    aggregate: AsharePortfolioAggregateResult | None
    outcome: AsharePortfolioValidationOutcome
    ledger_digest: str
    reserve_start: str
    reserve_end: str

    @property
    def result_id(self) -> str:
        return _digest(
            "ashare-portfolio-validation",
            self.to_dict(include_id=False, include_mode=False),
        )

    def to_dict(
        self,
        *,
        include_id: bool = True,
        include_mode: bool = True,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.ashare-portfolio-validation.v1",
            "scope": (
                "A4 internal execution-aware portfolio validation; no reserve "
                "consumption, promotion, PAPER, realtime or live-capital claim"
            ),
            "system_acceptance": {"passed": True, "status": "PASS"},
            "source_research_status": self.source_research_status,
            "validation_spec": self.spec.to_dict(),
            "folds": [fold.to_dict() for fold in self.folds],
            "aggregate": self.aggregate.to_dict() if self.aggregate is not None else None,
            "research_outcome": self.outcome.to_dict(),
            "ledger_digest": self.ledger_digest,
            "reserve": {
                "reserve_id": self.spec.reserve_id,
                "start": self.reserve_start,
                "end": self.reserve_end,
                "status": "untouched",
            },
        }
        if include_mode:
            payload["mode"] = self.mode
        if include_id:
            payload["portfolio_validation_id"] = self.result_id
        return payload

    def write_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return target


class AshareExecutionAwarePortfolioValidator:
    """A4 internal portfolio validator using A2.6 factors and A3 execution rules."""

    VERSION = "ashare-execution-aware-portfolio-validator-v1"

    def __init__(
        self,
        *,
        research_adapter,
        inference_adapter,
        execution_adapter: LocalAshareDailyExecutionAdapter,
        close_adapter: LocalAshareDailyCloseAdapter,
        universe_provider: AshareResearchUniverseProvider,
        artifacts: Sequence[GeneratedFeatureArtifact],
        selection: AshareRobustFactorSelection,
        config: AsharePortfolioValidationConfig,
        net_fee_schedule: AshareFeeSchedule,
        net_slippage_bps: float,
        require_price_limits: bool = True,
    ) -> None:
        if selection.status != "ROBUST_FACTOR_FAMILY_FROZEN":
            raise ValueError("A4 requires an A2.6 frozen robust factor family")
        by_digest = {artifact.digest: artifact for artifact in artifacts}
        if len(by_digest) != len(tuple(artifacts)):
            raise ValueError("A4 artifacts must be unique")
        selected = tuple(selection.components)
        missing = {component.feature_digest for component in selected} - set(by_digest)
        if missing:
            raise ValueError(f"A4 is missing frozen artifacts: {sorted(missing)}")
        self.research_adapter = research_adapter
        self.inference_adapter = inference_adapter
        self.execution_adapter = execution_adapter
        self.close_adapter = close_adapter
        self.universe_provider = universe_provider
        self.artifacts = tuple(by_digest[component.feature_digest] for component in selected)
        self.weights = tuple(component.weight for component in selected)
        self.directions = tuple(component.direction for component in selected)
        self.selection = selection
        self.config = config
        self.ledger = AshareInventoryLedger()
        self.net_session = AshareExecutionSession(
            compiler=AshareOrderCompiler(
                config=AshareOrderCompilerConfig(
                    require_prior_information=True,
                    require_price_limits=require_price_limits,
                    slippage_bps=net_slippage_bps,
                ),
                fee_schedule=net_fee_schedule,
            )
        )
        zero_fees = AshareFeeSchedule(
            broker_commission_rate=0.0,
            minimum_broker_commission=0.0,
            stamp_duty_sell_rate=0.0,
            transfer_fee_rate=0.0,
            sse_szse_handling_rate=0.0,
            bse_handling_rate=0.0,
            regulatory_fee_rate=0.0,
        )
        self.gross_session = AshareExecutionSession(
            compiler=AshareOrderCompiler(
                config=AshareOrderCompilerConfig(
                    require_prior_information=True,
                    require_price_limits=require_price_limits,
                    slippage_bps=0.0,
                ),
                fee_schedule=zero_fees,
            )
        )

    @staticmethod
    def _portfolio_state(state: AshareAccountState, asof: datetime) -> PortfolioState:
        return PortfolioState(
            asof=asof,
            base_currency="CNY",
            cash=state.cash,
            positions={
                asset: float(position.total_quantity)
                for asset, position in state.positions.items()
            },
            marks=state.marks,
        )

    @staticmethod
    def _mark_to_close(
        ledger: AshareInventoryLedger,
        state: AshareAccountState,
        snapshot: AshareDailyCloseSnapshot,
    ) -> AshareAccountState:
        state = ledger.roll_to_session(state, snapshot.session_date)
        marks = dict(state.marks)
        for asset, position in state.positions.items():
            if position.total_quantity <= 0:
                continue
            try:
                marks[asset] = snapshot.mark(asset)
            except KeyError:
                if asset not in marks:
                    raise
        return AshareAccountState(
            session_date=snapshot.session_date,
            cash=state.cash,
            positions=state.positions,
            marks=marks,
            base_currency=state.base_currency,
            metadata={
                **dict(state.metadata),
                "mark_clock": "exact_session_close_or_last_explicit_mark",
                "close_data_version": snapshot.data_version,
            },
        )

    @staticmethod
    def _metrics(returns: Sequence[float], annualization: float) -> AsharePortfolioMetrics:
        array = np.asarray(tuple(returns), dtype=float)
        if array.size < 1 or not np.isfinite(array).all():
            raise ValueError("A4 return series must be non-empty and finite")
        curve = np.cumprod(1.0 + array)
        if np.any(curve <= 0):
            raise ValueError("A4 compounded NAV must remain positive")
        total = float(curve[-1] - 1.0)
        annualized_return = float(curve[-1] ** (annualization / array.size) - 1.0)
        if array.size > 1:
            std = float(np.std(array, ddof=1))
            volatility = std * math.sqrt(annualization)
            sharpe = (
                float(np.mean(array) / std * math.sqrt(annualization))
                if std > 1e-15
                else 0.0
            )
        else:
            volatility = 0.0
            sharpe = 0.0
        running = np.maximum.accumulate(curve)
        drawdown = float(np.min(curve / running - 1.0))
        return AsharePortfolioMetrics(
            periods=int(array.size),
            total_return=total,
            annualized_return=annualized_return,
            annualized_volatility=volatility,
            sharpe=sharpe,
            max_drawdown=drawdown,
        )

    @staticmethod
    def _weights(state: AshareAccountState) -> dict[AssetId, float]:
        nav = state.nav
        if nav <= 0:
            raise ValueError("A4 account NAV must be positive")
        return {
            asset: position.total_quantity * state.marks[asset] / nav
            for asset, position in state.positions.items()
            if position.total_quantity > 0
        }

    @classmethod
    def _target_turnover(
        cls,
        state: AshareAccountState,
        target: PortfolioTarget,
    ) -> float:
        current = cls._weights(state)
        assets = sorted(set(current) | set(target.weights))
        risky = math.fsum(
            abs(target.weights.get(asset, 0.0) - current.get(asset, 0.0))
            for asset in assets
        )
        current_cash = state.cash / state.nav
        return 0.5 * math.fsum(
            (risky, abs(target.cash_weight - current_cash))
        )

    @classmethod
    def _implementation_shortfall(
        cls,
        state: AshareAccountState,
        target: PortfolioTarget,
    ) -> float:
        actual = cls._weights(state)
        assets = sorted(set(actual) | set(target.weights))
        risky = math.fsum(
            abs(target.weights.get(asset, 0.0) - actual.get(asset, 0.0))
            for asset in assets
        )
        actual_cash = state.cash / state.nav
        return 0.5 * math.fsum(
            (risky, abs(target.cash_weight - actual_cash))
        )

    @staticmethod
    def _reason_counts(cycle: AshareExecutionCycle | None) -> Counter[str]:
        output: Counter[str] = Counter()
        if cycle is None:
            return output
        for decision in cycle.compilation.decisions:
            output.update(decision.reason_codes)
        for value in cycle.execution.rejections.values():
            output.update((str(value),))
        return output

    @staticmethod
    def _participation(
        cycle: AshareExecutionCycle | None,
        snapshot,
    ) -> float:
        if cycle is None:
            return 0.0
        values: list[float] = []
        for fill in cycle.execution.fills:
            volume = snapshot.state(fill.asset).volume
            if volume > 0:
                values.append(fill.quantity / volume)
        return max(values, default=0.0)

    @staticmethod
    def _cash_target(
        *,
        asof: datetime,
        state: AshareAccountState,
        reason: str,
    ) -> PortfolioTarget:
        from finagent.domain.forecasts import ModelRef

        return PortfolioTarget(
            asof=asof,
            weights={asset: 0.0 for asset in state.positions},
            cash_weight=1.0,
            source=ModelRef("a4_cash_fallback", "v1"),
            metadata={"reason": reason},
        )

    def _risk_assets(
        self,
        alpha: AlphaForecast,
        risk_window,
    ) -> tuple[tuple[AssetId, ...], np.ndarray]:
        ranked = [
            asset
            for asset, value in sorted(
                alpha.expected_returns.items(),
                key=lambda item: (-item[1], item[0].key),
            )
            if value > self.config.minimum_expected_return
        ][: self.config.active_asset_count]
        if len(ranked) < self.config.min_active_assets:
            return (), np.empty((0, 0), dtype=float)
        returns = risk_window.feature_panel("simple_return_1")
        selected = list(ranked)
        while len(selected) >= self.config.min_active_assets:
            indices = [risk_window.asset_index(asset) for asset in selected]
            matrix = np.asarray(returns[:, indices], dtype=float)
            complete = matrix[np.all(np.isfinite(matrix), axis=1)]
            if complete.shape[0] >= self.config.risk_min_observations:
                return tuple(selected), complete
            missing_counts = np.sum(~np.isfinite(matrix), axis=0)
            remove_index = int(np.argmax(missing_counts))
            selected.pop(remove_index)
        return (), np.empty((0, 0), dtype=float)

    def _target(
        self,
        *,
        alpha_model: AshareFrozenGeneratedFeatureAlphaModel,
        signal_asof: datetime,
        state: AshareAccountState,
        universe: tuple[AssetId, ...],
    ) -> PortfolioTarget:
        if alpha_model.calibration.non_negative_slope <= 1e-15:
            return self._cash_target(
                asof=signal_asof,
                state=state,
                reason="NONPOSITIVE_ALPHA_CALIBRATION_SLOPE",
            )
        lookback = max(alpha_model.min_lookback, self.config.risk_lookback)
        fields = tuple(dict.fromkeys((*alpha_model.required_features, "simple_return_1")))
        window = self.research_adapter.feature_window(
            asof=signal_asof,
            universe=universe,
            features=fields,
            lookback=lookback,
        )
        formation = self.universe_provider.snapshot(window.timestamps[-1], universe)
        eligible = {asset: bool(formation.eligible.get(asset, False)) for asset in universe}
        alpha = alpha_model.predict(window, eligible=eligible)
        assets, returns = self._risk_assets(alpha, window)
        if len(assets) < self.config.min_active_assets:
            return self._cash_target(
                asof=signal_asof,
                state=state,
                reason="INSUFFICIENT_ACTIVE_ASSETS_OR_RISK_HISTORY",
            )
        active_alpha = AlphaForecast(
            asof=alpha.asof,
            horizon=alpha.horizon,
            expected_returns={asset: alpha.expected_returns[asset] for asset in assets},
            uncertainty={asset: alpha.uncertainty[asset] for asset in assets},
            source=alpha.source,
            metadata=alpha.metadata,
        )
        risk = HistoricalRiskForecastBuilder().build(
            asof=signal_asof,
            horizon=active_alpha.horizon,
            assets=assets,
            returns=returns,
        )
        optimizer = MeanVarianceOptimizer(
            MeanVarianceConfig(
                risk_aversion=self.config.risk_aversion,
                cash_weight=self.config.target_cash_weight,
                long_only=True,
                max_abs_weight=self.config.max_asset_weight,
                turnover_penalty=self.config.optimizer_turnover_penalty,
            )
        )
        portfolio_state = self._portfolio_state(state, signal_asof)
        target = optimizer.optimize(active_alpha, risk, portfolio_state)
        weights = dict(target.weights)
        for asset in state.positions:
            weights.setdefault(asset, 0.0)
        return PortfolioTarget(
            asof=target.asof,
            weights=weights,
            cash_weight=target.cash_weight,
            source=target.source,
            metadata={
                **dict(target.metadata),
                "a4_validator": self.VERSION,
                "alpha_model_id": alpha_model.artifact.digest,
                "eligible_assets": str(sum(eligible.values())),
                "risk_assets": str(len(assets)),
                "signal_timestamp": window.timestamps[-1].isoformat(),
            },
        )

    def _fold(
        self,
        *,
        fold,
        universe: tuple[AssetId, ...],
        primary_label: str,
    ) -> tuple[AsharePortfolioFoldResult, list[dict[str, object]]]:
        required = tuple(
            dict.fromkeys(
                field
                for artifact in self.artifacts
                for field in artifact.spec.input_fields
            )
        )
        train_request = DatasetRequest(
            universe=universe,
            features=required,
            labels=(primary_label,),
            splits={fold.train_split: fold.train},
            dataset_id=f"a4-{fold.fold_id}-train",
            metadata={"scope": "A4 internal training only"},
        )
        materializer = PanelGeneratedFeatureMaterializer(
            self.research_adapter,
            universe_provider=self.universe_provider,
        )
        alpha_model = AshareFrozenGeneratedFeatureAlphaModel(
            artifacts=self.artifacts,
            weights=self.weights,
            directions=self.directions,
            materializer=materializer,
            label_name=primary_label,
            ridge=self.config.alpha_ridge,
            min_observations=self.config.alpha_min_observations,
            winsor_lower_quantile=self.config.winsor_lower_quantile,
            winsor_upper_quantile=self.config.winsor_upper_quantile,
        )
        alpha_model.fit(train_request, split_name=fold.train_split)

        calendar_request = DatasetRequest(
            universe=universe,
            features=("close",),
            labels=(primary_label,),
            splits={fold.test_split: fold.test},
            dataset_id=f"a4-{fold.fold_id}-calendar",
            metadata={"scope": "A4 inference calendar; no forward rows"},
        )
        calendar_panel = self.inference_adapter.build_dataset(calendar_request).get_split(
            fold.test_split
        )
        sessions = tuple(timestamp.astimezone(UTC).date() for timestamp in calendar_panel.timestamps)
        if not sessions:
            raise ValueError(f"A4 fold {fold.fold_id!r} has no test sessions")

        initial_date = sessions[0] - timedelta(days=1)
        net_state = AshareAccountState(initial_date, self.config.initial_cash)
        gross_state = AshareAccountState(initial_date, self.config.initial_cash)
        previous_net_nav = self.config.initial_cash
        previous_gross_nav = self.config.initial_cash
        points: list[AsharePortfolioPoint] = []
        ledger_rows: list[dict[str, object]] = []
        fold_reasons: Counter[str] = Counter()

        for index, session_date in enumerate(sessions):
            execution_snapshot = self.execution_adapter.snapshot(session_date, universe)
            close_snapshot = self.close_adapter.snapshot(session_date, universe)
            net_signal_state = self.ledger.roll_to_session(net_state, session_date)
            gross_signal_state = self.ledger.roll_to_session(gross_state, session_date)
            net_pretrade_state = self.ledger.mark_to_snapshot(
                net_signal_state,
                execution_snapshot,
            )
            gross_pretrade_state = self.ledger.mark_to_snapshot(
                gross_signal_state,
                execution_snapshot,
            )
            signal_asof = execution_snapshot.asof - timedelta(microseconds=1)
            target: PortfolioTarget | None = None
            net_cycle: AshareExecutionCycle | None = None
            gross_cycle: AshareExecutionCycle | None = None
            rebalanced = index % self.config.rebalance_every == 0
            target_reason = "NOT_REBALANCE_SESSION"

            if rebalanced:
                try:
                    target = self._target(
                        alpha_model=alpha_model,
                        signal_asof=signal_asof,
                        state=net_signal_state,
                        universe=universe,
                    )
                    target_reason = target.metadata.get("reason", "MODEL_TARGET")
                except (KeyError, ValueError, RuntimeError) as exc:
                    if not self.config.cash_fallback_on_model_error:
                        raise
                    target = self._cash_target(
                        asof=signal_asof,
                        state=net_signal_state,
                        reason=f"MODEL_ERROR:{type(exc).__name__}",
                    )
                    target_reason = target.metadata["reason"]
                net_cycle = self.net_session.run(
                    target,
                    net_signal_state,
                    execution_snapshot,
                )
                gross_cycle = self.gross_session.run(
                    target,
                    gross_signal_state,
                    execution_snapshot,
                )
                net_open_state = net_cycle.state_after
                gross_open_state = gross_cycle.state_after
            else:
                net_open_state = net_pretrade_state
                gross_open_state = gross_pretrade_state

            cash_fallback = bool(
                target is not None and target.source.name == "a4_cash_fallback"
            )
            execution_target_deviation = (
                self._implementation_shortfall(net_open_state, target)
                if target is not None
                else 0.0
            )
            net_state = self._mark_to_close(self.ledger, net_open_state, close_snapshot)
            gross_state = self._mark_to_close(self.ledger, gross_open_state, close_snapshot)
            net_return = net_state.nav / previous_net_nav - 1.0
            gross_return = gross_state.nav / previous_gross_nav - 1.0
            previous_net_nav = net_state.nav
            previous_gross_nav = gross_state.nav

            fees = net_cycle.execution.total_fees if net_cycle is not None else 0.0
            slippage = (
                net_cycle.execution.total_slippage if net_cycle is not None else 0.0
            )
            fills = net_cycle.execution.fills if net_cycle is not None else ()
            traded_notional = sum(fill.notional for fill in fills)
            pretrade_nav = (
                net_cycle.compilation.pretrade_nav
                if net_cycle is not None
                else net_signal_state.nav
            )
            gross_traded_weight = (
                traded_notional / pretrade_nav if pretrade_nav > 0 else 0.0
            )
            one_way_turnover = 0.5 * gross_traded_weight
            reasons = self._reason_counts(net_cycle)
            reasons.update((target_reason,))
            fold_reasons.update(reasons)
            desired_order_count = (
                len(net_cycle.compilation.decisions) if net_cycle is not None else 0
            )
            order_count = len(net_cycle.execution.orders) if net_cycle is not None else 0
            fill_count = len(fills)
            rejected_count = (
                sum(
                    decision.status is AshareOrderDecisionStatus.REJECTED
                    for decision in net_cycle.compilation.decisions
                )
                + len(net_cycle.execution.rejections)
                if net_cycle is not None
                else 0
            )
            target_turnover = (
                self._target_turnover(net_pretrade_state, target)
                if target is not None
                else 0.0
            )
            shortfall = execution_target_deviation
            participation = self._participation(net_cycle, execution_snapshot)
            target_id = (
                _digest(
                    "a4-target",
                    {
                        "asof": target.asof.isoformat(),
                        "weights": {
                            asset.key: value for asset, value in sorted(target.weights.items())
                        },
                        "cash_weight": target.cash_weight,
                    },
                )
                if target is not None
                else ""
            )
            point = AsharePortfolioPoint(
                session_date=session_date,
                signal_asof=signal_asof,
                rebalanced=rebalanced,
                cash_fallback=cash_fallback,
                target_id=target_id,
                net_nav=net_state.nav,
                gross_nav=gross_state.nav,
                net_return=net_return,
                gross_return=gross_return,
                fees=fees,
                slippage=slippage,
                gross_traded_weight=gross_traded_weight,
                one_way_turnover=one_way_turnover,
                target_turnover=target_turnover,
                implementation_shortfall=shortfall,
                desired_order_count=desired_order_count,
                order_count=order_count,
                fill_count=fill_count,
                rejected_order_count=rejected_count,
                maximum_ex_post_participation=participation,
                reason_counts=reasons,
            )
            points.append(point)
            ledger_rows.append(
                {
                    "fold_id": fold.fold_id,
                    "point": point.to_dict(),
                    "target": (
                        {
                            "asof": target.asof.isoformat(),
                            "weights": {
                                asset.key: value
                                for asset, value in sorted(target.weights.items())
                            },
                            "cash_weight": target.cash_weight,
                            "metadata": dict(target.metadata),
                        }
                        if target is not None
                        else None
                    ),
                    "net_cycle": net_cycle.to_dict() if net_cycle is not None else None,
                    "gross_cycle": gross_cycle.to_dict() if gross_cycle is not None else None,
                    "net_close_state": net_state.to_dict(),
                    "gross_close_state": gross_state.to_dict(),
                    "ex_post_close_snapshot": close_snapshot.to_dict(),
                }
            )

        net_returns = [point.net_return for point in points]
        gross_returns = [point.gross_return for point in points]
        ledger_digest = _digest("a4-fold-ledger", ledger_rows, 64)
        return (
            AsharePortfolioFoldResult(
                fold_id=fold.fold_id,
                train_range=fold.train,
                test_range=fold.test,
                alpha_model_id=alpha_model.artifact.digest,
                alpha_calibration=alpha_model.calibration.to_dict(),
                points=tuple(points),
                net_metrics=self._metrics(net_returns, self.config.annualization),
                gross_metrics=self._metrics(gross_returns, self.config.annualization),
                total_fees=sum(point.fees for point in points),
                total_slippage=sum(point.slippage for point in points),
                total_gross_traded_weight=sum(
                    point.gross_traded_weight for point in points
                ),
                total_one_way_turnover=sum(point.one_way_turnover for point in points),
                average_implementation_shortfall=float(
                    np.mean(
                        [
                            point.implementation_shortfall
                            for point in points
                            if point.rebalanced
                        ]
                    )
                ),
                maximum_ex_post_participation=max(
                    point.maximum_ex_post_participation for point in points
                ),
                reason_counts=fold_reasons,
                ledger_digest=ledger_digest,
            ),
            ledger_rows,
        )

    def _aggregate(
        self,
        folds: Sequence[AsharePortfolioFoldResult],
    ) -> AsharePortfolioAggregateResult:
        net_returns = [point.net_return for fold in folds for point in fold.points]
        gross_returns = [point.gross_return for fold in folds for point in fold.points]
        net = self._metrics(net_returns, self.config.annualization)
        gross = self._metrics(gross_returns, self.config.annualization)
        desired_order_count = sum(
            point.desired_order_count for fold in folds for point in fold.points
        )
        order_count = sum(point.order_count for fold in folds for point in fold.points)
        fill_count = sum(point.fill_count for fold in folds for point in fold.points)
        rejected = sum(
            point.rejected_order_count for fold in folds for point in fold.points
        )
        rejected_ratio = (
            rejected / desired_order_count if desired_order_count else 0.0
        )
        rebalance_count = sum(
            point.rebalanced for fold in folds for point in fold.points
        )
        cash_fallback_count = sum(
            point.cash_fallback for fold in folds for point in fold.points
        )
        cash_fallback_ratio = (
            cash_fallback_count / rebalance_count if rebalance_count else 0.0
        )
        reasons: Counter[str] = Counter()
        for fold in folds:
            reasons.update(fold.reason_counts)
        hac_tstat, hac_pvalue = _newey_west_positive_mean_test(
            net_returns,
            self.config.hac_lags,
        )
        bootstrap_pvalue, ci_lower, ci_upper = (
            _circular_block_bootstrap_positive_mean(
                net_returns,
                samples=self.config.bootstrap_samples,
                block_length=self.config.bootstrap_block_length,
                seed=self.config.bootstrap_seed,
            )
        )
        return AsharePortfolioAggregateResult(
            net_metrics=net,
            gross_metrics=gross,
            gross_to_net_return_drag=gross.total_return - net.total_return,
            total_fees=sum(fold.total_fees for fold in folds),
            total_slippage=sum(fold.total_slippage for fold in folds),
            total_gross_traded_weight=sum(
                fold.total_gross_traded_weight for fold in folds
            ),
            total_one_way_turnover=sum(
                fold.total_one_way_turnover for fold in folds
            ),
            average_implementation_shortfall=float(
                np.mean(
                    [
                        point.implementation_shortfall
                        for fold in folds
                        for point in fold.points
                        if point.rebalanced
                    ]
                )
            ),
            maximum_ex_post_participation=max(
                fold.maximum_ex_post_participation for fold in folds
            ),
            positive_fold_ratio=float(
                np.mean([fold.net_metrics.total_return > 0 for fold in folds])
            ),
            worst_fold_net_sharpe=min(fold.net_metrics.sharpe for fold in folds),
            desired_order_count=desired_order_count,
            order_count=order_count,
            fill_count=fill_count,
            rejected_order_count=rejected,
            rejected_order_ratio=rejected_ratio,
            rebalance_count=rebalance_count,
            cash_fallback_count=cash_fallback_count,
            cash_fallback_ratio=cash_fallback_ratio,
            hac_tstat=hac_tstat,
            hac_pvalue=hac_pvalue,
            bootstrap_pvalue=bootstrap_pvalue,
            bootstrap_ci_lower=ci_lower,
            bootstrap_ci_upper=ci_upper,
            reason_counts=reasons,
        )

    def _outcome(
        self,
        aggregate: AsharePortfolioAggregateResult,
    ) -> AsharePortfolioValidationOutcome:
        policy = self.config.policy
        reasons: list[str] = []
        checks = (
            (
                aggregate.net_metrics.annualized_return
                >= policy.min_net_annualized_return,
                "NET_ANNUALIZED_RETURN_BELOW_THRESHOLD",
            ),
            (
                aggregate.net_metrics.sharpe >= policy.min_net_sharpe,
                "NET_SHARPE_BELOW_THRESHOLD",
            ),
            (
                abs(aggregate.net_metrics.max_drawdown) <= policy.max_abs_drawdown,
                "MAX_DRAWDOWN_ABOVE_THRESHOLD",
            ),
            (
                aggregate.gross_to_net_return_drag
                <= policy.max_gross_to_net_return_drag,
                "GROSS_TO_NET_DRAG_ABOVE_THRESHOLD",
            ),
            (
                aggregate.positive_fold_ratio >= policy.min_positive_fold_ratio,
                "POSITIVE_FOLD_RATIO_BELOW_THRESHOLD",
            ),
            (
                aggregate.hac_pvalue <= policy.max_hac_pvalue,
                "HAC_MEAN_RETURN_NOT_SIGNIFICANT",
            ),
            (
                aggregate.bootstrap_pvalue <= policy.max_bootstrap_pvalue,
                "BOOTSTRAP_MEAN_RETURN_NOT_SIGNIFICANT",
            ),
            (
                aggregate.rejected_order_ratio <= policy.max_rejected_order_ratio,
                "REJECTED_ORDER_RATIO_ABOVE_THRESHOLD",
            ),
            (
                aggregate.maximum_ex_post_participation
                <= policy.max_ex_post_participation,
                "EX_POST_PARTICIPATION_ABOVE_THRESHOLD",
            ),
            (
                aggregate.cash_fallback_ratio <= policy.max_cash_fallback_ratio,
                "CASH_FALLBACK_RATIO_ABOVE_THRESHOLD",
            ),
        )
        reasons.extend(code for passed, code in checks if not passed)
        passed = not reasons
        reasons.extend(("RESERVE_UNTOUCHED", "PROMOTION_REQUIRES_ONE_SHOT_RESERVE"))
        return AsharePortfolioValidationOutcome(
            status=(
                "EXECUTION_VALIDATION_PASSED_INTERNAL"
                if passed
                else "EXECUTION_VALIDATION_FAILED_INTERNAL"
            ),
            execution_validation_passed=passed,
            promotion_eligible=False,
            reason_codes=tuple(reasons),
            policy=policy,
        )

    def run(
        self,
        *,
        mode: str,
        spec: AsharePortfolioValidationSpec,
        plan: AshareExpandingWalkForwardPlan,
        universe: tuple[AssetId, ...],
        primary_label: str,
    ) -> tuple[AsharePortfolioValidationResult, tuple[dict[str, object], ...]]:
        if mode not in {"deterministic", "agent", "replay"}:
            raise ValueError("invalid A4 mode")
        fold_results: list[AsharePortfolioFoldResult] = []
        ledger_rows: list[dict[str, object]] = []
        for fold in plan.folds:
            fold_result, rows = self._fold(
                fold=fold,
                universe=universe,
                primary_label=primary_label,
            )
            fold_results.append(fold_result)
            ledger_rows.extend(rows)
        aggregate = self._aggregate(fold_results)
        outcome = self._outcome(aggregate)
        ledger_digest = _digest("a4-execution-ledger", ledger_rows, 64)
        final_result = AsharePortfolioValidationResult(
            mode=mode,
            spec=spec,
            source_research_status=self.selection.status,
            folds=tuple(fold_results),
            aggregate=aggregate,
            outcome=outcome,
            ledger_digest=ledger_digest,
            reserve_start=plan.reserve.start.isoformat(),
            reserve_end=plan.reserve.end.isoformat(),
        )
        return final_result, tuple(ledger_rows)


def no_robust_factor_result(
    *,
    mode: str,
    spec: AsharePortfolioValidationSpec,
    source_research_status: str,
    reserve_start: str,
    reserve_end: str,
) -> AsharePortfolioValidationResult:
    outcome = AsharePortfolioValidationOutcome(
        status="NO_ROBUST_FACTOR_FAMILY",
        execution_validation_passed=False,
        promotion_eligible=False,
        reason_codes=(
            "NO_A2P6_FACTOR_PASSED_PREREGISTERED_GATE",
            "NO_PORTFOLIO_BACKTEST_EXECUTED",
            "RESERVE_UNTOUCHED",
        ),
        policy=spec.validation_config.policy,
    )
    return AsharePortfolioValidationResult(
        mode=mode,
        spec=spec,
        source_research_status=source_research_status,
        folds=(),
        aggregate=None,
        outcome=outcome,
        ledger_digest=_digest("a4-execution-ledger", (), 64),
        reserve_start=reserve_start,
        reserve_end=reserve_end,
    )

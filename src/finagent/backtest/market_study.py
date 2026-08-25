from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from finagent.domain.assets import AssetId, AssetType
from finagent.models.alpha import ARAlphaModel, RandomWalkAlphaModel
from finagent.models.risk import GARCH11RiskModel
from finagent.portfolio import (
    EqualWeightOptimizer,
    MeanVarianceConfig,
    MeanVarianceOptimizer,
    MinimumVarianceOptimizer,
    PortfolioConstraintSet,
)
from finagent.ports import AlphaModel, PortfolioOptimizer
from finagent.services import StaticRiskGate, TimedSimulatedExchange

from .timed import TimedBacktestConfig, TimedEventDrivenBacktestEngine
from .walk_forward import (
    NestedPurgedWalkForwardSplitter,
    NestedWalkForwardConfig,
    WalkForwardConfig,
)

_CANDIDATES = frozenset({"equal_weight", "minimum_variance", "ar1_mean_variance"})


@dataclass(frozen=True, slots=True)
class MarketStudyConfig:
    outer_train_size: int = 756
    outer_test_size: int = 126
    outer_step_size: int = 126
    inner_train_size: int = 504
    inner_test_size: int = 63
    inner_step_size: int = 63
    purge_bars: int = 1
    embargo_bars: int = 5
    initial_cash: float = 1_000_000.0
    lookback: int = 60
    rebalance_every: int = 5
    execution_lag_events: int = 1
    cash_weight: float = 0.10
    max_weight: float = 0.60
    commission_bps: float = 1.0
    slippage_bps: float = 2.0
    impact_bps: float = 5.0
    max_participation_rate: float = 0.05
    garch_min_observations: int = 30
    correlation_lookback: int = 60
    ar_min_observations: int = 50
    risk_aversion: float = 30.0
    turnover_penalty: float = 0.0005
    candidate_names: tuple[str, ...] = (
        "equal_weight",
        "minimum_variance",
        "ar1_mean_variance",
    )

    def __post_init__(self) -> None:
        integer_positive = (
            self.outer_train_size,
            self.outer_test_size,
            self.outer_step_size,
            self.inner_train_size,
            self.inner_test_size,
            self.inner_step_size,
            self.lookback,
            self.rebalance_every,
            self.execution_lag_events,
            self.garch_min_observations,
            self.correlation_lookback,
            self.ar_min_observations,
        )
        if any(value <= 0 for value in integer_positive):
            raise ValueError("study sizes/lookbacks must be positive")
        if self.purge_bars < 1 or self.embargo_bars < 0:
            raise ValueError("purge_bars must be >= 1 and embargo_bars must be >= 0")
        if not 0 <= self.cash_weight < 1:
            raise ValueError("cash_weight must be in [0, 1)")
        if not 0 < self.max_weight <= 1:
            raise ValueError("max_weight must be in (0, 1]")
        if any(
            value < 0
            for value in (
                self.commission_bps,
                self.slippage_bps,
                self.impact_bps,
                self.turnover_penalty,
            )
        ):
            raise ValueError("cost parameters must be non-negative")
        if not 0 < self.max_participation_rate <= 1:
            raise ValueError("max_participation_rate must be in (0, 1]")
        names = tuple(str(name).strip() for name in self.candidate_names)
        if not names or len(names) != len(set(names)):
            raise ValueError("candidate_names must be unique and non-empty")
        unknown = set(names) - _CANDIDATES
        if unknown:
            raise ValueError(f"unknown market-study candidates: {sorted(unknown)}")
        object.__setattr__(self, "candidate_names", names)

    def splitter(self) -> NestedPurgedWalkForwardSplitter:
        return NestedPurgedWalkForwardSplitter(
            NestedWalkForwardConfig(
                outer=WalkForwardConfig(
                    train_size=self.outer_train_size,
                    test_size=self.outer_test_size,
                    step_size=self.outer_step_size,
                    purge_bars=self.purge_bars,
                    embargo_bars=self.embargo_bars,
                ),
                inner=WalkForwardConfig(
                    train_size=self.inner_train_size,
                    test_size=self.inner_test_size,
                    step_size=self.inner_step_size,
                    purge_bars=self.purge_bars,
                    embargo_bars=self.embargo_bars,
                ),
            )
        )


@dataclass(frozen=True, slots=True)
class MarketStudyFoldResult:
    outer_fold_index: int
    selected_candidate: str
    inner_mean_sharpe: Mapping[str, float]
    outer_metrics: Mapping[str, float]
    outer_start: str
    outer_end: str

    def to_dict(self) -> dict[str, object]:
        return {
            "outer_fold_index": self.outer_fold_index,
            "selected_candidate": self.selected_candidate,
            "inner_mean_sharpe": dict(self.inner_mean_sharpe),
            "outer_metrics": dict(self.outer_metrics),
            "outer_start": self.outer_start,
            "outer_end": self.outer_end,
        }


@dataclass(frozen=True, slots=True)
class MarketStudyResult:
    study_id: str
    data_version: str
    universe: tuple[str, ...]
    start: str
    end: str
    config: MarketStudyConfig
    folds: tuple[MarketStudyFoldResult, ...]
    aggregate_metrics: Mapping[str, float]

    def to_dict(self) -> dict[str, object]:
        return {
            "study_id": self.study_id,
            "data_version": self.data_version,
            "universe": list(self.universe),
            "start": self.start,
            "end": self.end,
            "config": asdict(self.config),
            "folds": [fold.to_dict() for fold in self.folds],
            "aggregate_metrics": dict(self.aggregate_metrics),
            "scope": "fixed-universe ETF M1; not Level 2 individual-equity certification",
        }

    def write_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return path


def _components(name: str, config: MarketStudyConfig):
    constraints = PortfolioConstraintSet(
        cash_weight=config.cash_weight,
        long_only=True,
        max_weight=config.max_weight,
        gross_limit=1.0,
    )
    alpha: AlphaModel
    optimizer: PortfolioOptimizer
    if name == "equal_weight":
        alpha = RandomWalkAlphaModel()
        optimizer = EqualWeightOptimizer(constraints)
    elif name == "minimum_variance":
        alpha = RandomWalkAlphaModel()
        optimizer = MinimumVarianceOptimizer(constraints)
    elif name == "ar1_mean_variance":
        alpha = ARAlphaModel(order=1, min_observations=config.ar_min_observations)
        optimizer = MeanVarianceOptimizer(
            MeanVarianceConfig(
                risk_aversion=config.risk_aversion,
                cash_weight=config.cash_weight,
                long_only=True,
                max_abs_weight=config.max_weight,
                turnover_penalty=config.turnover_penalty,
            )
        )
    else:
        raise KeyError(name)
    risk = GARCH11RiskModel(
        min_observations=config.garch_min_observations,
        correlation_lookback=config.correlation_lookback,
    )
    gate = StaticRiskGate(
        max_gross_exposure=1.0,
        max_abs_weight=config.max_weight,
        min_cash_weight=config.cash_weight - 1e-9,
    )
    return alpha, risk, optimizer, gate


def _run_candidate(adapter, dataset, name: str, config: MarketStudyConfig, *, test_split: str):
    alpha, risk, optimizer, gate = _components(name, config)
    engine = TimedEventDrivenBacktestEngine(
        adapter,
        adapter,
        config=TimedBacktestConfig(
            train_split="train",
            test_split=test_split,
            initial_cash=config.initial_cash,
            lookback=config.lookback,
            rebalance_every=config.rebalance_every,
            execution_lag_events=config.execution_lag_events,
            execution_price_field="open",
            annualization_factor=252.0,
        ),
        exchange=TimedSimulatedExchange(
            slippage_bps=config.slippage_bps,
            commission_bps=config.commission_bps,
            impact_bps=config.impact_bps,
            max_participation_rate=config.max_participation_rate,
        ),
    )
    result = engine.run(dataset, alpha, risk, optimizer, gate)
    if any(point.cash < -1e-8 for point in result.points):
        raise RuntimeError(
            "next-open execution produced negative cash; increase cash_weight or implement "
            "the Level 2 cash-feasibility execution planner"
        )
    return result


def _result_metrics(result) -> dict[str, float]:
    return {
        "total_return": float(result.total_return),
        "annualized_return": float(result.annualized_return),
        "annualized_volatility": float(result.annualized_volatility),
        "sharpe": float(result.sharpe),
        "max_drawdown": float(result.max_drawdown),
        "gross_traded_weight": float(result.total_turnover),
        "transaction_cost": float(result.total_transaction_cost),
    }


def _period_returns(result, initial_cash: float) -> list[float]:
    nav = np.asarray([initial_cash, *(point.nav for point in result.points)], dtype=float)
    return [float(value) for value in nav[1:] / nav[:-1] - 1.0]


def _aggregate(returns: list[float], turnover: float, cost: float) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    if values.size == 0:
        raise ValueError("nested study produced no out-of-sample period returns")
    wealth = np.cumprod(1.0 + values)
    total_return = float(wealth[-1] - 1.0)
    annualized_return = float(wealth[-1] ** (252.0 / len(values)) - 1.0)
    std = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    annualized_volatility = std * math.sqrt(252.0)
    sharpe = float(np.mean(values) / std * math.sqrt(252.0)) if std > 0 else 0.0
    running_max = np.maximum.accumulate(np.concatenate(([1.0], wealth)))
    full_wealth = np.concatenate(([1.0], wealth))
    max_drawdown = float(np.min(full_wealth / running_max - 1.0))
    return {
        "oos_periods": float(len(values)),
        "total_return": total_return,
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_volatility,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "gross_traded_weight": float(turnover),
        "transaction_cost": float(cost),
    }


def run_nested_market_study(
    adapter,
    *,
    universe: tuple[AssetId, ...],
    start: datetime,
    end: datetime,
    config: MarketStudyConfig | None = None,
) -> MarketStudyResult:
    config = config or MarketStudyConfig()
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("start must be timezone-aware")
    if end.tzinfo is None or end.utcoffset() is None:
        raise ValueError("end must be timezone-aware")
    if end <= start:
        raise ValueError("end must be later than start")
    if len(universe) < 2:
        raise ValueError("fixed-universe ETF study requires at least two assets")
    if len(set(universe)) != len(universe):
        raise ValueError("fixed-universe ETF study cannot contain duplicate assets")
    if any(asset.asset_type is not AssetType.ETF for asset in universe):
        raise ValueError("M1 market studies support ETF assets only")
    if len({asset.currency for asset in universe}) != 1:
        raise ValueError("FinAgent M1 market studies require one base currency")
    if config.max_weight * len(universe) + 1e-12 < 1.0 - config.cash_weight:
        raise ValueError("max_weight and cash_weight make the fixed universe infeasible")
    splitter = config.splitter()
    nested = splitter.build_datasets(
        adapter,
        universe=universe,
        features=("log_return_1", "squared_log_return_1"),
        labels=("forward_log_return_1",),
        start=start,
        end=end,
        dataset_id_prefix="real-market-m1",
    )
    folds: list[MarketStudyFoldResult] = []
    outer_returns: list[float] = []
    total_turnover = 0.0
    total_cost = 0.0

    for item in nested:
        inner_scores: dict[str, float] = {}
        for name in config.candidate_names:
            scores = [
                _run_candidate(adapter, dataset, name, config, test_split="validation").sharpe
                for dataset in item.inner_datasets
            ]
            inner_scores[name] = float(np.mean(scores))
        selected = min(
            config.candidate_names,
            key=lambda name: (-inner_scores[name], name),
        )
        outer = _run_candidate(
            adapter,
            item.outer_dataset,
            selected,
            config,
            test_split="test",
        )
        outer_returns.extend(_period_returns(outer, config.initial_cash))
        total_turnover += outer.total_turnover
        total_cost += outer.total_transaction_cost
        folds.append(
            MarketStudyFoldResult(
                outer_fold_index=item.fold.outer_fold.fold_index,
                selected_candidate=selected,
                inner_mean_sharpe=inner_scores,
                outer_metrics=_result_metrics(outer),
                outer_start=item.fold.outer_fold.test.start.isoformat(),
                outer_end=item.fold.outer_fold.test.end.isoformat(),
            )
        )

    digest_payload = {
        "data_version": adapter.data_version,
        "universe": [asset.key for asset in universe],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "config": asdict(config),
    }
    encoded = json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
    study_id = f"market-study-{hashlib.sha256(encoded).hexdigest()[:16]}"
    return MarketStudyResult(
        study_id=study_id,
        data_version=adapter.data_version,
        universe=tuple(asset.key for asset in universe),
        start=start.isoformat(),
        end=end.isoformat(),
        config=config,
        folds=tuple(folds),
        aggregate_metrics=_aggregate(outer_returns, total_turnover, total_cost),
    )

"""Frozen train-only sklearn Ridge over causal lagged factor-quality features."""

from __future__ import annotations

import math
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime
from importlib.metadata import version
from typing import Any

import numpy as np

from finagent.domain.research import TimeRange
from finagent.research.factor_performance import (
    FactorPerformanceHistory,
    QualityConfig,
    performance_features,
)
from finagent.research.market_state import utc_text
from finagent.research.us_baselines import _canonical_hash


@dataclass(frozen=True)
class RidgeConfig:
    alpha: float = 1.0
    minimum_train_samples: int = 8
    max_iter: int = 15000
    tol: float = 1e-8

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.alpha)
            or self.alpha <= 0
            or not math.isfinite(self.tol)
            or self.tol <= 0
        ):
            raise ValueError("Ridge alpha/tolerance must be finite and positive")
        if (
            type(self.minimum_train_samples) is not int
            or not 4 <= self.minimum_train_samples <= 10000
        ):
            raise ValueError("invalid Ridge minimum training count")
        if type(self.max_iter) is not int or not 1 <= self.max_iter <= 15000:
            raise ValueError("invalid Ridge iteration limit")


@dataclass(frozen=True)
class RidgeMetaModel:
    factor_ids: tuple[str, ...]
    train_window: TimeRange
    available_at: datetime
    quality_config: QualityConfig
    config: RidgeConfig
    training_id: str
    sample_count: int
    source_id: str | None
    scaler_mean: tuple[float, ...]
    scaler_scale: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    dependencies: tuple[tuple[str, str], ...]
    fallback_reason: str | None = None

    def __post_init__(self) -> None:
        if (
            self.available_at != self.train_window.end
            or tuple(sorted(set(self.factor_ids))) != self.factor_ids
        ):
            raise ValueError("invalid Ridge fit availability/factor pool")
        if any(len(v) != 2 for v in (self.scaler_mean, self.scaler_scale, self.coefficients)):
            raise ValueError("Ridge binds exactly two lagged quality features")
        if any(
            not math.isfinite(v)
            for v in (*self.scaler_mean, *self.scaler_scale, *self.coefficients, self.intercept)
        ):
            raise ValueError("Ridge fitted parameters must be finite")
        if min(self.scaler_scale) <= 0 or min(self.coefficients) < 0:
            raise ValueError("invalid Ridge scale/positive coefficients")

    @property
    def model_id(self) -> str:
        return str(_canonical_hash(self.to_dict(), prefix="ridge-meta-model"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "finagent.ridge-meta.v1",
            "factor_ids": self.factor_ids,
            "train_window": {
                "start": utc_text(self.train_window.start),
                "end": utc_text(self.train_window.end),
            },
            "available_at": utc_text(self.available_at),
            "config": asdict(self.config),
            "quality_config": asdict(self.quality_config),
            "training_id": self.training_id,
            "sample_count": self.sample_count,
            "source_id": self.source_id,
            "scaler_mean": self.scaler_mean,
            "scaler_scale": self.scaler_scale,
            "coefficients": self.coefficients,
            "intercept": self.intercept,
            "dependencies": dict(self.dependencies),
            "fallback_reason": self.fallback_reason,
            "estimator": "sklearn.linear_model.Ridge; positive=True; solver=lbfgs; fit_intercept=True",
            "features": [
                "previous_completed_sessions_mean_rank_ic",
                "previous_completed_sessions_mean_net_bps_at_5bp",
            ],
            "target": "next_session_standalone_5bp_net_bps",
            "update": "coefficients_frozen_after_train",
        }

    def predict(self, features: tuple[float, float]) -> float:
        # Inert fitted parameters; the solver itself is sklearn, not reimplemented.
        return self.intercept + math.fsum(
            c * (x - m) / s
            for x, m, s, c in zip(
                features, self.scaler_mean, self.scaler_scale, self.coefficients, strict=True
            )
        )


def fit_ridge_meta(
    factor_ids: tuple[str, ...],
    history: FactorPerformanceHistory,
    train_window: TimeRange,
    quality_config: QualityConfig,
    config: RidgeConfig,
) -> RidgeMetaModel:
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits

    if not factor_ids or tuple(sorted(set(factor_ids))) != factor_ids:
        raise ValueError("Ridge requires sorted unique factor IDs")
    # Both features and labels are reconstructed from this fold's matured rows.
    train = FactorPerformanceHistory(
        tuple(
            row
            for row in history.available(as_of=train_window.end).observations
            if train_window.contains(row.decision_time) and row.factor_id in factor_ids
        )
    )
    examples = []
    for row in train.observations:
        past = train.available(as_of=row.decision_time)
        features = performance_features(row.factor_id, past, quality_config)
        if features is not None and row.standalone_5bp_net_return is not None:
            examples.append(
                {
                    "factor_id": row.factor_id,
                    "decision_time": utc_text(row.decision_time),
                    "outcome_available_at": utc_text(row.outcome_available_at),
                    "features": features,
                    "target": row.standalone_5bp_net_return * 10000,
                }
            )
    reason = None
    mean: tuple[float, ...] = (0.0, 0.0)
    scale: tuple[float, ...] = (1.0, 1.0)
    coefficients: tuple[float, ...] = (0.0, 0.0)
    intercept = 0.0
    if len(examples) < config.minimum_train_samples:
        reason = "INSUFFICIENT_RIDGE_TRAIN_SAMPLES"
    else:
        x = np.asarray([r["features"] for r in examples], dtype=float)
        y = np.asarray([r["target"] for r in examples], dtype=float)
        scaler = StandardScaler()
        estimator = Ridge(
            alpha=config.alpha,
            positive=True,
            solver="lbfgs",
            max_iter=config.max_iter,
            tol=config.tol,
        )
        with threadpool_limits(limits=1), warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            try:
                estimator.fit(scaler.fit_transform(x), y)
            except ConvergenceWarning:
                reason = "RIDGE_NOT_CONVERGED"
        if reason is None:
            mean, scale = tuple(map(float, scaler.mean_)), tuple(map(float, scaler.scale_))
            coefficients, intercept = (
                tuple(map(float, estimator.coef_)),
                float(estimator.intercept_),
            )
            if (
                any(not math.isfinite(v) for v in (*mean, *scale, *coefficients, intercept))
                or min(coefficients) < 0
            ):
                raise ValueError("invalid fitted Ridge parameters")
    return RidgeMetaModel(
        factor_ids,
        train_window,
        train_window.end,
        quality_config,
        config,
        str(_canonical_hash(examples, prefix="ridge-training")),
        len(examples),
        train.observations[0].source_id if train.observations else None,
        mean,
        scale,
        coefficients,
        intercept,
        tuple(
            (name, version(name)) for name in ("scikit-learn", "numpy", "scipy", "threadpoolctl")
        ),
        reason,
    )

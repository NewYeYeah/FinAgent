"""Thin scikit-learn GMM adapter; all fitted transforms belong to one train window."""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from finagent.domain._validation import require_aware_datetime
from finagent.domain.research import TimeRange
from finagent.research.market_state import (
    MarketFeatureConfig,
    MarketFeatures,
    MarketStateRow,
    MarketStateSource,
    utc_text,
)
from finagent.research.us_baselines import _canonical_hash
from finagent.research.us_r3_economic_campaign import file_digest


@dataclass(frozen=True)
class GMMConfig:
    n_components: int = 4
    random_seed: int = 7
    n_init: int = 1
    max_iter: int = 200
    min_train_rows: int = 20
    reg_covar: float = 1e-6
    tol: float = 1e-3

    def __post_init__(self) -> None:
        for name, minimum, maximum in (
            ("n_components", 2, 8),
            ("random_seed", 0, 2**32 - 1),
            ("n_init", 1, 10),
            ("max_iter", 1, 1000),
            ("min_train_rows", 2, 32768),
        ):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"invalid GMM {name}")
        if self.min_train_rows < self.n_components:
            raise ValueError("min_train_rows must cover all components")
        if any(not math.isfinite(v) or v <= 0 for v in (self.reg_covar, self.tol)):
            raise ValueError("GMM regularization/tolerance must be finite and positive")


def _dependencies() -> dict[str, str]:
    return {name: version(name) for name in ("scikit-learn", "numpy", "scipy", "threadpoolctl")}


def market_state_implementation_id() -> str:
    root = Path(__file__).parent
    return str(
        _canonical_hash(
            {name: file_digest(root / name) for name in ("market_state.py", "market_state_gmm.py")},
            prefix="market-state-implementation",
        )
    )


@dataclass(frozen=True)
class MarketStateModel:
    source: MarketStateSource
    features: MarketFeatureConfig
    config: GMMConfig
    fit_window: TimeRange
    available_at: datetime
    train_digest: str
    train_rows: int
    implementation_id: str
    dependencies: tuple[tuple[str, str], ...]
    scaler_mean: tuple[float, ...]
    scaler_scale: tuple[float, ...]
    weights: tuple[float, ...]
    means: tuple[tuple[float, ...], ...]
    covariances: tuple[tuple[float, ...], ...]
    iterations: int

    def __post_init__(self) -> None:
        require_aware_datetime(self.available_at, "model available_at")
        if self.available_at < self.fit_window.end:
            raise ValueError("model available_at precedes fit window end")
        k = self.config.n_components
        if self.train_rows < self.config.min_train_rows or not self.train_digest:
            raise ValueError("invalid training evidence")
        if len(self.scaler_mean) != 2 or len(self.scaler_scale) != 2:
            raise ValueError("scaler must bind two features")
        if len(self.weights) != k or len(self.means) != k or len(self.covariances) != k:
            raise ValueError("component dimensions do not match configuration")
        if any(len(row) != 2 for row in (*self.means, *self.covariances)):
            raise ValueError("component feature dimensions do not match")
        values = (
            *self.scaler_mean,
            *self.scaler_scale,
            *self.weights,
            *(v for row in (*self.means, *self.covariances) for v in row),
        )
        if any(not math.isfinite(v) for v in values):
            raise ValueError("fitted parameters must be finite")
        if any(
            v <= 0
            for v in (
                *self.scaler_scale,
                *self.weights,
                *(v for row in self.covariances for v in row),
            )
        ):
            raise ValueError("invalid fitted scale/weight/covariance")
        if not math.isclose(math.fsum(self.weights), 1.0, abs_tol=1e-12):
            raise ValueError("mixture weights must sum to one")

    @property
    def model_id(self) -> str:
        return str(_canonical_hash(self.to_dict(include_id=False), prefix="market-state-model"))

    def to_dict(self, *, include_id: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": "finagent.market-state-gmm.v1",
            "estimator": "sklearn.mixture.GaussianMixture",
            "covariance_type": "diag",
            "inference": "P(S_t|X_<=t); frozen_train_parameters; no_sequence_smoothing",
            "source": asdict(self.source),
            "features": self.features.to_dict(),
            "config": asdict(self.config),
            "fit_window": {
                "start": utc_text(self.fit_window.start),
                "end": utc_text(self.fit_window.end),
            },
            "available_at": utc_text(self.available_at),
            "train_digest": self.train_digest,
            "train_rows": self.train_rows,
            "implementation_id": self.implementation_id,
            "dependencies": dict(self.dependencies),
            "scaler_mean": self.scaler_mean,
            "scaler_scale": self.scaler_scale,
            "weights": self.weights,
            "means": self.means,
            "covariances": self.covariances,
            "iterations": self.iterations,
            "state_interpretation": [
                {
                    "state": i,
                    "train_centroid": tuple(
                        m * s + u
                        for m, s, u in zip(mean, self.scaler_scale, self.scaler_mean, strict=True)
                    ),
                }
                for i, mean in enumerate(self.means)
            ],
            "state_mapping": "ascending_train_centroid_return_then_realized_volatility",
            "alpha_authority": False,
            "paper_authority": False,
            "live_authority": False,
        }
        if include_id:
            payload["model_id"] = self.model_id
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> MarketStateModel:
        """JSON parameters only: no pickle or executable model deserialization."""
        result = cls(
            MarketStateSource(**payload["source"]),
            MarketFeatureConfig(
                payload["features"]["proxy_asset"], payload["features"]["lookback_returns"]
            ),
            GMMConfig(**payload["config"]),
            TimeRange(
                *(datetime.fromisoformat(payload["fit_window"][key]) for key in ("start", "end"))
            ),
            datetime.fromisoformat(payload["available_at"]),
            payload["train_digest"],
            payload["train_rows"],
            payload["implementation_id"],
            tuple(sorted(payload["dependencies"].items())),
            tuple(payload["scaler_mean"]),
            tuple(payload["scaler_scale"]),
            tuple(payload["weights"]),
            tuple(tuple(row) for row in payload["means"]),
            tuple(tuple(row) for row in payload["covariances"]),
            payload["iterations"],
        )
        if _canonical_hash(dict(payload), prefix="check") != _canonical_hash(
            result.to_dict(), prefix="check"
        ):
            raise ValueError("model content identity mismatch")
        return result


def fit_market_state(
    features: MarketFeatures,
    fit_window: TimeRange,
    *,
    config: GMMConfig | None = None,
    available_at: datetime | None = None,
) -> MarketStateModel:
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.mixture import GaussianMixture
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits

    config = config or GMMConfig()
    available = available_at or fit_window.end
    require_aware_datetime(available, "model available_at")
    if available < fit_window.end:
        raise ValueError("model available_at precedes fit window end")
    train = tuple(row for row in features.rows if fit_window.contains(row.event_time))
    if any(row.available_at > fit_window.end for row in train):
        raise ValueError("training observation unavailable by fit cutoff")
    usable = [row for row in train if row.values is not None]
    if len(usable) < config.min_train_rows:
        raise ValueError("INSUFFICIENT_TRAIN_FEATURES")
    x = np.asarray([row.values for row in usable], dtype=np.float64)
    if len(np.unique(x, axis=0)) < config.n_components:
        raise ValueError("DEGENERATE_TRAIN_FEATURES")
    scaler = StandardScaler()
    model = GaussianMixture(
        n_components=config.n_components,
        covariance_type="diag",
        random_state=config.random_seed,
        n_init=config.n_init,
        max_iter=config.max_iter,
        reg_covar=config.reg_covar,
        tol=config.tol,
        init_params="kmeans",
        warm_start=False,
    )
    with threadpool_limits(limits=1), warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        try:
            model.fit(scaler.fit_transform(x))
        except ConvergenceWarning as exc:
            raise ValueError("GMM_NOT_CONVERGED") from exc
    if not model.converged_:
        raise ValueError("GMM_NOT_CONVERGED")
    # Fix label switching exclusively from train centroids. No outcome/holdout labels.
    centroids = scaler.inverse_transform(model.means_)
    order = sorted(range(config.n_components), key=lambda i: tuple(centroids[i]))
    return MarketStateModel(
        features.source,
        features.config,
        config,
        fit_window,
        available,
        _canonical_hash([row.to_dict() for row in train], prefix="market-state-train"),
        len(usable),
        market_state_implementation_id(),
        tuple(sorted(_dependencies().items())),
        tuple(float(v) for v in scaler.mean_),
        tuple(float(v) for v in scaler.scale_),
        tuple(float(model.weights_[i]) for i in order),
        tuple(tuple(float(v) for v in model.means_[i]) for i in order),
        tuple(tuple(float(v) for v in model.covariances_[i]) for i in order),
        int(model.n_iter_),
    )


def project_market_state(
    model: MarketStateModel,
    features: MarketFeatures,
    *,
    as_of: datetime,
) -> tuple[MarketStateRow, ...]:
    from sklearn.mixture import GaussianMixture
    from sklearn.preprocessing import StandardScaler
    from threadpoolctl import threadpool_limits

    require_aware_datetime(as_of, "as_of")
    if model.source != features.source or model.features != features.config:
        raise ValueError("market-state source/feature identity mismatch")
    if dict(model.dependencies) != _dependencies():
        raise ValueError("fitted dependency environment mismatch; refit a new model")
    if model.implementation_id != market_state_implementation_id():
        raise ValueError("fitted implementation mismatch; refit a new model")
    # Restore the fitted library objects from inert, validated JSON parameters.
    scaler = StandardScaler()
    scaler.mean_, scaler.scale_ = np.array(model.scaler_mean), np.array(model.scaler_scale)
    scaler.n_features_in_ = 2
    estimator = GaussianMixture(n_components=model.config.n_components, covariance_type="diag")
    estimator.weights_, estimator.means_ = np.array(model.weights), np.array(model.means)
    estimator.covariances_ = np.array(model.covariances)
    estimator.precisions_cholesky_ = 1 / np.sqrt(estimator.covariances_)
    estimator.n_features_in_ = 2
    result = []
    identity = model.model_id
    with threadpool_limits(limits=1):
        for row in features.rows:
            reason = row.unavailable_reason
            probabilities = None
            if row.available_at > as_of:
                reason = "OBSERVATION_NOT_AVAILABLE"
            elif row.event_time < model.fit_window.end:
                reason = "FIT_HISTORY_NOT_PROJECTION"
            elif row.available_at < model.available_at:
                reason = "MODEL_NOT_AVAILABLE"
            elif row.values is not None:
                values = estimator.predict_proba(scaler.transform([row.values]))[0]
                probabilities = tuple(float(v) for v in values)
            result.append(
                MarketStateRow(
                    identity,
                    row.event_time,
                    row.available_at,
                    row.session_id,
                    probabilities,
                    reason,
                )
            )
    return tuple(result)

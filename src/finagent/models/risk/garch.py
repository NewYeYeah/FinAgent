from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from finagent.domain.assets import AssetId
from finagent.domain.experiments import ArtifactRef
from finagent.domain.forecasts import ModelRef, RiskForecast
from finagent.domain.research import FeatureWindow, ResearchDataset
from finagent.models._utils import infer_horizon, model_artifact
from finagent.models.risk.covariance import EWMACovarianceEstimator


@dataclass(frozen=True, slots=True)
class GARCH11Parameters:
    omega: float
    alpha: float
    beta: float

    def __post_init__(self) -> None:
        if self.omega <= 0:
            raise ValueError("omega must be > 0")
        if self.alpha < 0 or self.beta < 0:
            raise ValueError("alpha and beta must be >= 0")
        if self.alpha + self.beta >= 1:
            raise ValueError("stationary GARCH requires alpha + beta < 1")


@dataclass(frozen=True, slots=True)
class GARCH11Estimator:
    min_observations: int = 30
    variance_floor: float = 1e-12

    def __post_init__(self) -> None:
        if self.min_observations < 10:
            raise ValueError("min_observations must be >= 10")
        if self.variance_floor <= 0:
            raise ValueError("variance_floor must be > 0")

    def fit(self, returns: np.ndarray) -> GARCH11Parameters:
        series = np.asarray(returns, dtype=float)
        series = series[np.isfinite(series)]
        if len(series) < self.min_observations:
            raise ValueError(
                f"GARCH requires at least {self.min_observations} finite observations, got {len(series)}"
            )
        # Scale decimal returns to percent units for a better-conditioned optimiser.
        x = series * 100.0
        sample_var = max(float(np.var(x, ddof=1)), 1e-8)

        def negative_log_likelihood(theta: np.ndarray) -> float:
            omega, alpha, beta = map(float, theta)
            if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.999:
                return 1e100
            variance = np.empty_like(x)
            variance[0] = sample_var
            for t in range(1, len(x)):
                variance[t] = omega + alpha * x[t - 1] ** 2 + beta * variance[t - 1]
                if not np.isfinite(variance[t]) or variance[t] <= 0:
                    return 1e100
            variance = np.maximum(variance, 1e-10)
            return float(
                0.5
                * np.sum(
                    np.log(2.0 * np.pi)
                    + np.log(variance)
                    + (x * x) / variance
                )
            )

        initial = np.asarray([sample_var * 0.05, 0.05, 0.90], dtype=float)
        result = minimize(
            negative_log_likelihood,
            initial,
            method="SLSQP",
            bounds=[(1e-10, sample_var * 20.0 + 1.0), (0.0, 0.999), (0.0, 0.999)],
            constraints=[{"type": "ineq", "fun": lambda t: 0.999 - t[1] - t[2]}],
            options={"maxiter": 1000, "ftol": 1e-10},
        )
        if not result.success or not np.all(np.isfinite(result.x)):
            # Stable fallback is preferable to silently returning an invalid model.
            omega_pct = sample_var * 0.05
            alpha = 0.05
            beta = 0.90
        else:
            omega_pct, alpha, beta = map(float, result.x)
        # Variance conversion from percent^2 back to decimal-return variance.
        return GARCH11Parameters(
            omega=max(omega_pct / 10000.0, self.variance_floor),
            alpha=float(alpha),
            beta=float(beta),
        )

    def forecast_variance(
        self,
        returns: np.ndarray,
        parameters: GARCH11Parameters,
    ) -> float:
        series = np.asarray(returns, dtype=float)
        series = series[np.isfinite(series)]
        if len(series) < 2:
            raise ValueError("at least two returns are required for GARCH forecasting")
        if parameters.alpha + parameters.beta < 0.999:
            variance = parameters.omega / (1.0 - parameters.alpha - parameters.beta)
        else:
            variance = float(np.var(series, ddof=1))
        variance = max(variance, self.variance_floor)
        for value in series:
            variance = (
                parameters.omega
                + parameters.alpha * float(value) ** 2
                + parameters.beta * variance
            )
            variance = max(variance, self.variance_floor)
        return float(variance)


class GARCH11RiskModel:
    """GARCH(1,1) marginal volatility + EWMA correlation risk model."""

    def __init__(
        self,
        *,
        return_feature: str = "log_return_1",
        min_observations: int = 30,
        covariance_decay: float = 0.94,
        covariance_shrinkage: float = 0.05,
        correlation_lookback: int = 60,
    ) -> None:
        if correlation_lookback < 2:
            raise ValueError("correlation_lookback must be >= 2")
        self.return_feature = return_feature
        self.estimator = GARCH11Estimator(min_observations=min_observations)
        self.covariance_estimator = EWMACovarianceEstimator(
            decay=covariance_decay,
            shrinkage=covariance_shrinkage,
        )
        self.correlation_lookback = int(correlation_lookback)
        self._parameters: dict[AssetId, GARCH11Parameters] = {}
        self._artifact: ArtifactRef | None = None
        self._horizon = None

    @property
    def required_features(self) -> tuple[str, ...]:
        return (self.return_feature,)

    @property
    def min_lookback(self) -> int:
        return max(self.correlation_lookback, 2)

    @property
    def parameters(self) -> dict[AssetId, GARCH11Parameters]:
        return dict(self._parameters)

    def fit(self, dataset: ResearchDataset, split: str = "train") -> ArtifactRef:
        panel = dataset.get_split(split)
        returns = panel.feature_panel(self.return_feature)
        parameters: dict[AssetId, GARCH11Parameters] = {}
        for idx, asset in enumerate(panel.assets):
            parameters[asset] = self.estimator.fit(returns[:, idx])
        self._parameters = parameters
        self._horizon = infer_horizon(panel)
        self._artifact = model_artifact(
            "garch11_ewma",
            dataset.artifact.digest,
            {
                "return_feature": self.return_feature,
                "split": split,
                "correlation_lookback": self.correlation_lookback,
                "covariance_decay": self.covariance_estimator.decay,
                "covariance_shrinkage": self.covariance_estimator.shrinkage,
                "parameters": {
                    asset.key: {
                        "omega": p.omega,
                        "alpha": p.alpha,
                        "beta": p.beta,
                    }
                    for asset, p in parameters.items()
                },
            },
        )
        return self._artifact

    def predict(self, window: FeatureWindow) -> RiskForecast:
        if self._artifact is None or self._horizon is None:
            raise RuntimeError("model must be fit before predict")
        feature_idx = window.feature_index(self.return_feature)
        assets = window.assets
        variances: list[float] = []
        for asset_idx, asset in enumerate(assets):
            parameters = self._parameters.get(asset)
            if parameters is None:
                raise ValueError(f"asset {asset.key} was not seen during fit")
            series = window.values[:, asset_idx, feature_idx]
            variances.append(self.estimator.forecast_variance(series, parameters))
        vol = np.sqrt(np.asarray(variances, dtype=float))

        return_panel = window.values[:, :, feature_idx]
        recent = return_panel[-self.correlation_lookback :]
        try:
            corr = self.covariance_estimator.correlation(recent)
        except ValueError:
            corr = np.eye(len(assets), dtype=float)
        covariance_matrix = np.outer(vol, vol) * corr
        covariance_matrix = (covariance_matrix + covariance_matrix.T) / 2.0

        covariance = {
            (left, right): float(covariance_matrix[i, j])
            for i, left in enumerate(assets)
            for j, right in enumerate(assets)
        }
        return RiskForecast(
            asof=window.asof,
            horizon=self._horizon,
            volatilities={asset: float(vol[idx]) for idx, asset in enumerate(assets)},
            covariance=covariance,
            source=ModelRef(
                name="garch11_ewma",
                version=self._artifact.version,
                artifact_id=self._artifact.artifact_id,
            ),
            metadata={
                "return_feature": self.return_feature,
                "correlation": "ewma",
                "covariance_decay": repr(self.covariance_estimator.decay),
            },
        )

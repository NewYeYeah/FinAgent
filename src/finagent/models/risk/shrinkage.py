from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

import numpy as np
from numpy.typing import NDArray

from finagent.domain.assets import AssetId
from finagent.domain.forecasts import ModelRef, RiskForecast


@dataclass(frozen=True, slots=True)
class OASCovarianceResult:
    covariance: NDArray[np.float64]
    shrinkage: float
    n_observations: int

    def __post_init__(self) -> None:
        matrix = np.asarray(self.covariance, dtype=float)
        if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
            raise ValueError("covariance must be a square matrix")
        if not np.all(np.isfinite(matrix)):
            raise ValueError("covariance must be finite")
        matrix = np.array((matrix + matrix.T) / 2.0, dtype=float, copy=True)
        matrix.setflags(write=False)
        if not 0.0 <= self.shrinkage <= 1.0:
            raise ValueError("shrinkage must be in [0, 1]")
        if self.n_observations < 2:
            raise ValueError("n_observations must be >= 2")
        object.__setattr__(self, "covariance", matrix)


class OASCovarianceEstimator:
    """Oracle-Approximating Shrinkage covariance estimator.

    The target is a scaled identity matrix. Complete aligned rows are used and the
    final matrix is projected to the PSD cone with an explicit eigenvalue floor.
    This provides a deterministic dependency-light alternative to a raw sample or
    hand-tuned EWMA covariance for Phase 4 portfolio research.
    """

    VERSION = "oas-v1"

    def __init__(self, *, min_eigenvalue: float = 1e-12) -> None:
        if min_eigenvalue < 0:
            raise ValueError("min_eigenvalue must be >= 0")
        self.min_eigenvalue = float(min_eigenvalue)

    def estimate_with_diagnostics(
        self,
        returns: NDArray[np.float64],
    ) -> OASCovarianceResult:
        matrix = np.asarray(returns, dtype=float)
        if matrix.ndim != 2:
            raise ValueError("returns must have shape (time, asset)")
        matrix = matrix[np.all(np.isfinite(matrix), axis=1)]
        if matrix.shape[0] < 2:
            raise ValueError("at least two complete return rows are required")
        if matrix.shape[1] < 1:
            raise ValueError("at least one asset column is required")

        centered = matrix - np.mean(matrix, axis=0, keepdims=True)
        n_samples, n_assets = centered.shape
        empirical = centered.T @ centered / float(n_samples)
        mu = float(np.trace(empirical)) / float(n_assets)
        alpha = float(np.mean(empirical * empirical))
        denominator = (n_samples + 1.0) * (alpha - (mu * mu) / float(n_assets))
        if denominator <= 1e-30:
            shrinkage = 1.0
        else:
            shrinkage = min((alpha + mu * mu) / denominator, 1.0)
        shrinkage = max(float(shrinkage), 0.0)
        target = np.eye(n_assets, dtype=float) * mu
        covariance = (1.0 - shrinkage) * empirical + shrinkage * target
        covariance = (covariance + covariance.T) / 2.0
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        eigenvalues = np.maximum(eigenvalues, self.min_eigenvalue)
        covariance = (eigenvectors * eigenvalues) @ eigenvectors.T
        covariance = (covariance + covariance.T) / 2.0
        return OASCovarianceResult(
            covariance=covariance,
            shrinkage=shrinkage,
            n_observations=n_samples,
        )

    def estimate(self, returns: NDArray[np.float64]) -> NDArray[np.float64]:
        return self.estimate_with_diagnostics(returns).covariance


class HistoricalRiskForecastBuilder:
    """Build a typed RiskForecast from an aligned historical return matrix."""

    VERSION = "historical-oas-risk-v1"

    def __init__(
        self,
        estimator: OASCovarianceEstimator | None = None,
        *,
        variance_scale: float = 1.0,
    ) -> None:
        if variance_scale <= 0 or not np.isfinite(variance_scale):
            raise ValueError("variance_scale must be finite and > 0")
        self.estimator = estimator or OASCovarianceEstimator()
        self.variance_scale = float(variance_scale)

    def build(
        self,
        *,
        asof: datetime,
        horizon: timedelta,
        assets: Sequence[AssetId],
        returns: NDArray[np.float64],
        source: ModelRef | None = None,
    ) -> RiskForecast:
        assets = tuple(assets)
        if not assets or len(set(assets)) != len(assets):
            raise ValueError("assets must be non-empty and unique")
        matrix = np.asarray(returns, dtype=float)
        if matrix.ndim != 2 or matrix.shape[1] != len(assets):
            raise ValueError("returns must have shape (time, len(assets))")
        result = self.estimator.estimate_with_diagnostics(matrix)
        covariance_matrix = np.asarray(result.covariance, dtype=float) * self.variance_scale
        volatilities = {
            asset: float(np.sqrt(max(covariance_matrix[idx, idx], 0.0)))
            for idx, asset in enumerate(assets)
        }
        covariance = {
            (left, right): float(covariance_matrix[i, j])
            for i, left in enumerate(assets)
            for j, right in enumerate(assets)
        }
        return RiskForecast(
            asof=asof,
            horizon=horizon,
            volatilities=volatilities,
            covariance=covariance,
            source=source or ModelRef(name="historical_oas_risk", version=self.VERSION),
            metadata={
                "estimator": self.estimator.VERSION,
                "shrinkage": repr(result.shrinkage),
                "n_observations": str(result.n_observations),
                "variance_scale": repr(self.variance_scale),
            },
        )

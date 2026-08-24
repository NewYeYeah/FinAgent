from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

import numpy as np
from numpy.typing import NDArray

from finagent.domain.assets import AssetId
from finagent.domain.forecasts import ModelRef, RiskForecast


@dataclass(frozen=True, slots=True)
class PCAFactorRiskResult:
    covariance: NDArray[np.float64]
    loadings: NDArray[np.float64]
    factor_variances: NDArray[np.float64]
    idiosyncratic_variances: NDArray[np.float64]
    explained_variance_ratio: float
    n_observations: int

    def __post_init__(self) -> None:
        covariance = np.asarray(self.covariance, dtype=float)
        loadings = np.asarray(self.loadings, dtype=float)
        factors = np.asarray(self.factor_variances, dtype=float)
        idio = np.asarray(self.idiosyncratic_variances, dtype=float)
        if covariance.ndim != 2 or covariance.shape[0] != covariance.shape[1]:
            raise ValueError("covariance must be square")
        n_assets = covariance.shape[0]
        if loadings.ndim != 2 or loadings.shape[0] != n_assets:
            raise ValueError("loadings must have shape (asset, factor)")
        if factors.shape != (loadings.shape[1],):
            raise ValueError("factor_variances shape mismatch")
        if idio.shape != (n_assets,):
            raise ValueError("idiosyncratic_variances shape mismatch")
        if not all(np.all(np.isfinite(value)) for value in (covariance, loadings, factors, idio)):
            raise ValueError("factor-risk arrays must be finite")
        if np.any(factors < 0) or np.any(idio < 0):
            raise ValueError("risk variances must be non-negative")
        if not 0.0 <= self.explained_variance_ratio <= 1.0 + 1e-12:
            raise ValueError("explained_variance_ratio must be in [0, 1]")
        if self.n_observations < 2:
            raise ValueError("n_observations must be >= 2")
        for name, value in (
            ("covariance", covariance),
            ("loadings", loadings),
            ("factor_variances", factors),
            ("idiosyncratic_variances", idio),
        ):
            array = np.array(value, dtype=float, copy=True)
            array.setflags(write=False)
            object.__setattr__(self, name, array)


class PCAFactorRiskEstimator:
    """Low-rank statistical factor covariance with diagonal residual risk.

    This is a research baseline for Phase 4, not a substitute for a production
    fundamental/industry factor model. Principal components are fitted only from the
    return matrix supplied by the caller.
    """

    VERSION = "pca-factor-risk-v1"

    def __init__(self, n_factors: int = 3, *, min_idiosyncratic_variance: float = 1e-10) -> None:
        if isinstance(n_factors, bool) or not isinstance(n_factors, int) or n_factors < 1:
            raise ValueError("n_factors must be an integer >= 1")
        if min_idiosyncratic_variance < 0:
            raise ValueError("min_idiosyncratic_variance must be >= 0")
        self.n_factors = n_factors
        self.min_idiosyncratic_variance = float(min_idiosyncratic_variance)

    def estimate(self, returns: NDArray[np.float64]) -> PCAFactorRiskResult:
        matrix = np.asarray(returns, dtype=float)
        if matrix.ndim != 2:
            raise ValueError("returns must have shape (time, asset)")
        matrix = matrix[np.all(np.isfinite(matrix), axis=1)]
        if matrix.shape[0] < 2 or matrix.shape[1] < 2:
            raise ValueError("PCA factor risk requires at least two observations and two assets")
        centered = matrix - np.mean(matrix, axis=0, keepdims=True)
        n_samples, n_assets = centered.shape
        n_factors = min(self.n_factors, n_assets, n_samples - 1)
        sample_covariance = centered.T @ centered / float(n_samples)
        eigenvalues, eigenvectors = np.linalg.eigh((sample_covariance + sample_covariance.T) / 2.0)
        order = np.argsort(eigenvalues)[::-1]
        selected_values = np.maximum(eigenvalues[order[:n_factors]], 0.0)
        selected_vectors = eigenvectors[:, order[:n_factors]]
        loadings = selected_vectors
        factor_covariance = selected_vectors @ np.diag(selected_values) @ selected_vectors.T
        residual = np.diag(sample_covariance - factor_covariance)
        idiosyncratic = np.maximum(residual, self.min_idiosyncratic_variance)
        covariance = factor_covariance + np.diag(idiosyncratic)
        covariance = (covariance + covariance.T) / 2.0
        eigvals, eigvecs = np.linalg.eigh(covariance)
        eigvals = np.maximum(eigvals, 0.0)
        covariance = (eigvecs * eigvals) @ eigvecs.T
        covariance = (covariance + covariance.T) / 2.0
        total_variance = float(np.maximum(eigenvalues, 0.0).sum())
        explained = float(selected_values.sum() / total_variance) if total_variance > 1e-30 else 0.0
        return PCAFactorRiskResult(
            covariance=covariance,
            loadings=loadings,
            factor_variances=selected_values,
            idiosyncratic_variances=idiosyncratic,
            explained_variance_ratio=min(max(explained, 0.0), 1.0),
            n_observations=n_samples,
        )


class PCAFactorRiskForecastBuilder:
    VERSION = "pca-factor-risk-forecast-v1"

    def __init__(self, estimator: PCAFactorRiskEstimator | None = None, *, variance_scale: float = 1.0) -> None:
        if variance_scale <= 0 or not np.isfinite(variance_scale):
            raise ValueError("variance_scale must be finite and > 0")
        self.estimator = estimator or PCAFactorRiskEstimator()
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
        result = self.estimator.estimate(matrix)
        covariance_matrix = np.asarray(result.covariance, dtype=float) * self.variance_scale
        return RiskForecast(
            asof=asof,
            horizon=horizon,
            volatilities={
                asset: float(np.sqrt(max(covariance_matrix[idx, idx], 0.0)))
                for idx, asset in enumerate(assets)
            },
            covariance={
                (left, right): float(covariance_matrix[i, j])
                for i, left in enumerate(assets)
                for j, right in enumerate(assets)
            },
            source=source or ModelRef(name="pca_factor_risk", version=self.VERSION),
            metadata={
                "estimator": self.estimator.VERSION,
                "n_factors": str(result.loadings.shape[1]),
                "explained_variance_ratio": repr(result.explained_variance_ratio),
                "n_observations": str(result.n_observations),
                "variance_scale": repr(self.variance_scale),
            },
        )

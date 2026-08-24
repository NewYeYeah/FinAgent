from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class EWMACovarianceEstimator:
    """Exponentially weighted covariance with optional diagonal shrinkage.

    Input shape is ``(time, asset)``. Rows containing any non-finite value are
    dropped to preserve a single aligned covariance sample. The result is projected
    onto the positive-semidefinite cone.
    """

    decay: float = 0.94
    shrinkage: float = 0.05
    min_eigenvalue: float = 1e-12

    def __post_init__(self) -> None:
        if not 0 < self.decay < 1:
            raise ValueError("decay must be in (0, 1)")
        if not 0 <= self.shrinkage <= 1:
            raise ValueError("shrinkage must be in [0, 1]")
        if self.min_eigenvalue < 0:
            raise ValueError("min_eigenvalue must be >= 0")

    def estimate(self, returns: NDArray[np.float64]) -> NDArray[np.float64]:
        matrix = np.asarray(returns, dtype=float)
        if matrix.ndim != 2:
            raise ValueError("returns must have shape (time, asset)")
        matrix = matrix[np.all(np.isfinite(matrix), axis=1)]
        if matrix.shape[0] < 2:
            raise ValueError("at least two complete return rows are required")
        n = matrix.shape[0]
        powers = np.arange(n - 1, -1, -1, dtype=float)
        weights = np.power(self.decay, powers)
        weights /= weights.sum()
        mean = np.sum(matrix * weights[:, None], axis=0)
        centered = matrix - mean
        cov = centered.T @ (centered * weights[:, None])
        diagonal = np.diag(np.diag(cov))
        cov = (1.0 - self.shrinkage) * cov + self.shrinkage * diagonal
        cov = (cov + cov.T) / 2.0
        eigvals, eigvecs = np.linalg.eigh(cov)
        eigvals = np.maximum(eigvals, self.min_eigenvalue)
        cov = (eigvecs * eigvals) @ eigvecs.T
        cov = (cov + cov.T) / 2.0
        return cov

    def correlation(self, returns: NDArray[np.float64]) -> NDArray[np.float64]:
        cov = self.estimate(returns)
        std = np.sqrt(np.maximum(np.diag(cov), self.min_eigenvalue))
        corr = cov / np.outer(std, std)
        corr = np.clip(corr, -1.0, 1.0)
        np.fill_diagonal(corr, 1.0)
        # Numerical projection and re-normalisation preserve PSD + unit diagonal.
        eigvals, eigvecs = np.linalg.eigh((corr + corr.T) / 2.0)
        eigvals = np.maximum(eigvals, self.min_eigenvalue)
        corr = (eigvecs * eigvals) @ eigvecs.T
        scale = np.sqrt(np.maximum(np.diag(corr), self.min_eigenvalue))
        corr = corr / np.outer(scale, scale)
        np.fill_diagonal(corr, 1.0)
        return (corr + corr.T) / 2.0

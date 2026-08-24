from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from finagent.domain.assets import AssetId
from finagent.domain.experiments import ArtifactRef
from finagent.domain.forecasts import AlphaForecast, ModelRef
from finagent.domain.research import FeatureWindow, ResearchDataset
from finagent.models._utils import infer_horizon, model_artifact


@dataclass(frozen=True, slots=True)
class ARMA11Fit:
    intercept: float
    phi: float
    theta: float
    residual_std: float
    observations: int


class ARMA11AlphaModel:
    """Per-asset ARMA(1,1) estimated by conditional sum of squares.

    The observed return sequence follows

    ``r_t = c + phi * r_{t-1} + theta * e_{t-1} + e_t``.

    Prediction reconstructs the latest residual from the PIT feature window, so no
    hidden mutable online state is required.
    """

    def __init__(
        self,
        *,
        return_feature: str = "log_return_1",
        min_observations: int = 30,
    ) -> None:
        if min_observations < 20:
            raise ValueError("min_observations must be >= 20")
        self.return_feature = return_feature
        self.min_observations = int(min_observations)
        self._fits: dict[AssetId, ARMA11Fit] = {}
        self._artifact: ArtifactRef | None = None
        self._horizon = None

    @property
    def required_features(self) -> tuple[str, ...]:
        return (self.return_feature,)

    @property
    def min_lookback(self) -> int:
        return 3

    @property
    def fits(self) -> dict[AssetId, ARMA11Fit]:
        return dict(self._fits)

    @staticmethod
    def _residuals(series: np.ndarray, c: float, phi: float, theta: float) -> np.ndarray:
        residuals = np.zeros_like(series)
        for t in range(1, len(series)):
            residuals[t] = series[t] - c - phi * series[t - 1] - theta * residuals[t - 1]
        return residuals

    def fit(self, dataset: ResearchDataset, split: str = "train") -> ArtifactRef:
        panel = dataset.get_split(split)
        returns = panel.feature_panel(self.return_feature)
        fits: dict[AssetId, ARMA11Fit] = {}
        for idx, asset in enumerate(panel.assets):
            series = returns[:, idx]
            series = series[np.isfinite(series)]
            if len(series) < self.min_observations:
                raise ValueError(
                    f"insufficient ARMA observations for {asset.key}: {len(series)} < {self.min_observations}"
                )

            def objective(theta_vec: np.ndarray) -> float:
                c, phi, theta = map(float, theta_vec)
                if abs(phi) >= 0.999 or abs(theta) >= 0.999:
                    return 1e100
                resid = self._residuals(series, c, phi, theta)
                return float(np.dot(resid[1:], resid[1:]))

            initial = np.asarray([float(np.mean(series)), 0.0, 0.0])
            result = minimize(
                objective,
                initial,
                method="L-BFGS-B",
                bounds=[(None, None), (-0.995, 0.995), (-0.995, 0.995)],
                options={"maxiter": 2000, "ftol": 1e-15},
            )
            if not result.success or not np.all(np.isfinite(result.x)):
                raise RuntimeError(f"ARMA fit failed for {asset.key}: {result.message}")
            c, phi, theta = map(float, result.x)
            residuals = self._residuals(series, c, phi, theta)
            residual_std = float(np.std(residuals[1:], ddof=1))
            fits[asset] = ARMA11Fit(c, phi, theta, residual_std, len(series))

        self._fits = fits
        self._horizon = infer_horizon(panel)
        self._artifact = model_artifact(
            "arma11",
            dataset.artifact.digest,
            {
                "return_feature": self.return_feature,
                "split": split,
                "fits": {
                    asset.key: {
                        "intercept": fit.intercept,
                        "phi": fit.phi,
                        "theta": fit.theta,
                        "residual_std": fit.residual_std,
                        "observations": fit.observations,
                    }
                    for asset, fit in fits.items()
                },
            },
        )
        return self._artifact

    def predict(self, window: FeatureWindow) -> AlphaForecast:
        if self._artifact is None or self._horizon is None:
            raise RuntimeError("model must be fit before predict")
        feature_idx = window.feature_index(self.return_feature)
        expected: dict[AssetId, float] = {}
        uncertainty: dict[AssetId, float] = {}
        for idx, asset in enumerate(window.assets):
            fit = self._fits.get(asset)
            if fit is None:
                raise ValueError(f"asset {asset.key} was not seen during fit")
            series = window.values[:, idx, feature_idx]
            series = series[np.isfinite(series)]
            if len(series) < 2:
                raise ValueError(f"ARMA prediction requires at least two returns for {asset.key}")
            residuals = self._residuals(series, fit.intercept, fit.phi, fit.theta)
            expected[asset] = float(
                fit.intercept + fit.phi * series[-1] + fit.theta * residuals[-1]
            )
            uncertainty[asset] = fit.residual_std
        return AlphaForecast(
            asof=window.asof,
            horizon=self._horizon,
            expected_returns=expected,
            uncertainty=uncertainty,
            source=ModelRef(
                name="arma11",
                version=self._artifact.version,
                artifact_id=self._artifact.artifact_id,
            ),
            metadata={"return_feature": self.return_feature},
        )

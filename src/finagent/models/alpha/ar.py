from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from finagent.domain.assets import AssetId
from finagent.domain.experiments import ArtifactRef
from finagent.domain.forecasts import AlphaForecast, ModelRef
from finagent.domain.research import FeatureWindow, ResearchDataset
from finagent.models._utils import infer_horizon, model_artifact


@dataclass(frozen=True, slots=True)
class ARFit:
    intercept: float
    coefficients: tuple[float, ...]
    residual_std: float
    observations: int


class ARAlphaModel:
    """Per-asset AR(p) alpha model fit by ordinary least squares.

    At row t the predictors are ``[r_t, r_{t-1}, ..., r_{t-p+1}]`` and the label is
    the forward return attached to row t. This keeps feature/label alignment explicit
    in the DataAdapter rather than hiding a shift inside the model.
    """

    def __init__(
        self,
        order: int = 1,
        *,
        return_feature: str = "log_return_1",
        label: str = "forward_log_return_1",
        min_observations: int = 20,
    ) -> None:
        if order <= 0:
            raise ValueError("order must be >= 1")
        if min_observations <= order + 1:
            raise ValueError("min_observations must exceed order + 1")
        self.order = int(order)
        self.return_feature = return_feature
        self.label = label
        self.min_observations = int(min_observations)
        self._fits: dict[AssetId, ARFit] = {}
        self._artifact: ArtifactRef | None = None
        self._horizon = None

    @property
    def required_features(self) -> tuple[str, ...]:
        return (self.return_feature,)

    @property
    def min_lookback(self) -> int:
        return self.order

    @property
    def fits(self) -> dict[AssetId, ARFit]:
        return dict(self._fits)

    def fit(self, dataset: ResearchDataset, split: str = "train") -> ArtifactRef:
        panel = dataset.get_split(split)
        if self.label not in panel.label_names:
            raise KeyError(f"dataset does not contain label {self.label!r}")
        returns = panel.feature_panel(self.return_feature)
        labels = panel.label_panel(self.label)
        fits: dict[AssetId, ARFit] = {}

        for asset_idx, asset in enumerate(panel.assets):
            x_series = returns[:, asset_idx]
            y_series = labels[:, asset_idx]
            rows: list[list[float]] = []
            targets: list[float] = []
            for t in range(self.order - 1, len(x_series)):
                lagged = [x_series[t - lag] for lag in range(self.order)]
                target = y_series[t]
                if np.isfinite(target) and np.all(np.isfinite(lagged)):
                    rows.append([1.0, *lagged])
                    targets.append(float(target))
            if len(rows) < self.min_observations:
                raise ValueError(
                    f"insufficient AR observations for {asset.key}: {len(rows)} < {self.min_observations}"
                )
            matrix = np.asarray(rows, dtype=float)
            target_vec = np.asarray(targets, dtype=float)
            beta, *_ = np.linalg.lstsq(matrix, target_vec, rcond=None)
            residuals = target_vec - matrix @ beta
            dof = max(len(target_vec) - len(beta), 1)
            residual_std = float(np.sqrt(np.sum(residuals**2) / dof))
            fits[asset] = ARFit(
                intercept=float(beta[0]),
                coefficients=tuple(float(v) for v in beta[1:]),
                residual_std=residual_std,
                observations=len(rows),
            )

        self._fits = fits
        self._horizon = infer_horizon(panel)
        self._artifact = model_artifact(
            f"ar_{self.order}",
            dataset.artifact.digest,
            {
                "order": self.order,
                "return_feature": self.return_feature,
                "label": self.label,
                "split": split,
                "fits": {
                    asset.key: {
                        "intercept": fit.intercept,
                        "coefficients": fit.coefficients,
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
        for asset_idx, asset in enumerate(window.assets):
            if asset not in self._fits:
                raise ValueError(f"asset {asset.key} was not seen during fit")
            series = window.values[:, asset_idx, feature_idx]
            finite = series[np.isfinite(series)]
            if len(finite) < self.order:
                raise ValueError(
                    f"feature window for {asset.key} needs {self.order} finite returns, got {len(finite)}"
                )
            latest = finite[-self.order :][::-1]
            fit = self._fits[asset]
            value = fit.intercept + float(np.dot(np.asarray(fit.coefficients), latest))
            expected[asset] = value
            uncertainty[asset] = fit.residual_std
        return AlphaForecast(
            asof=window.asof,
            horizon=self._horizon,
            expected_returns=expected,
            uncertainty=uncertainty,
            source=ModelRef(
                name=f"ar_{self.order}",
                version=self._artifact.version,
                artifact_id=self._artifact.artifact_id,
            ),
            metadata={"return_feature": self.return_feature, "label": self.label},
        )

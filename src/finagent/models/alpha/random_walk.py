from __future__ import annotations

import numpy as np

from finagent.domain.experiments import ArtifactRef
from finagent.domain.forecasts import AlphaForecast, ModelRef
from finagent.domain.research import FeatureWindow, ResearchDataset
from finagent.models._utils import infer_horizon, model_artifact


class RandomWalkAlphaModel:
    """Zero-drift benchmark for short-horizon returns."""

    def __init__(self, return_feature: str = "log_return_1") -> None:
        self.return_feature = return_feature
        self._artifact: ArtifactRef | None = None
        self._horizon = None
        self._residual_std: dict = {}

    @property
    def required_features(self) -> tuple[str, ...]:
        return (self.return_feature,)

    @property
    def min_lookback(self) -> int:
        return 2

    def fit(self, dataset: ResearchDataset, split: str = "train") -> ArtifactRef:
        panel = dataset.get_split(split)
        returns = panel.feature_panel(self.return_feature)
        residual_std = {}
        for idx, asset in enumerate(panel.assets):
            series = returns[:, idx]
            series = series[np.isfinite(series)]
            if len(series) < 2:
                raise ValueError(f"insufficient finite returns for {asset.key}")
            residual_std[asset] = float(np.std(series, ddof=1))
        self._residual_std = residual_std
        self._horizon = infer_horizon(panel)
        self._artifact = model_artifact(
            "random_walk",
            dataset.artifact.digest,
            {"return_feature": self.return_feature, "split": split},
        )
        return self._artifact

    def predict(self, window: FeatureWindow) -> AlphaForecast:
        if self._artifact is None or self._horizon is None:
            raise RuntimeError("model must be fit before predict")
        missing = set(window.assets) - set(self._residual_std)
        if missing:
            raise ValueError("window contains assets not seen during fit")
        return AlphaForecast(
            asof=window.asof,
            horizon=self._horizon,
            expected_returns={asset: 0.0 for asset in window.assets},
            uncertainty={asset: self._residual_std[asset] for asset in window.assets},
            source=ModelRef(
                name="random_walk",
                version=self._artifact.version,
                artifact_id=self._artifact.artifact_id,
            ),
            metadata={"benchmark": "zero_drift_random_walk"},
        )

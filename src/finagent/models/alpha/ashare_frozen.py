from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Mapping, Sequence

import numpy as np

from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.domain.experiments import ArtifactRef
from finagent.domain.forecasts import AlphaForecast, ModelRef
from finagent.domain.research import DatasetRequest, FeatureWindow
from finagent.models._utils import infer_horizon, model_artifact
from finagent.models.alpha.primitives import (
    cross_sectional_zscore,
    winsorize_cross_section,
)
from finagent.research.panel_feature_materializer import (
    PanelGeneratedFeatureMaterializer,
)
from finagent.sandbox import FeatureSandboxRequest, LocalFeatureSandbox


@dataclass(frozen=True, slots=True)
class AshareFrozenAlphaCalibration:
    intercept: float
    non_negative_slope: float
    residual_std: float
    observations: int
    raw_slope: float

    def __post_init__(self) -> None:
        numeric = (
            self.intercept,
            self.non_negative_slope,
            self.residual_std,
            self.raw_slope,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("A-share frozen alpha calibration must be finite")
        if self.non_negative_slope < 0 or self.residual_std <= 0:
            raise ValueError("invalid A-share frozen alpha calibration")
        if self.observations < 2:
            raise ValueError("A-share frozen alpha calibration requires observations")

    def to_dict(self) -> dict[str, object]:
        return {
            "intercept": self.intercept,
            "non_negative_slope": self.non_negative_slope,
            "raw_slope": self.raw_slope,
            "residual_std": self.residual_std,
            "observations": self.observations,
        }


class AshareFrozenGeneratedFeatureAlphaModel:
    """Panel-native alpha model for an A2.6 frozen robust factor family.

    The A2.6 directions and weights are immutable inputs.  Each generated factor is
    materialized through the existing sandbox, winsorized and z-scored within the
    eligible cross-section, then combined.  A pooled train-only linear calibration
    maps the frozen score to the requested forward-return label.  The calibration
    slope is constrained to be non-negative so a later portfolio stage cannot undo
    the direction frozen by internal walk-forward research.
    """

    VERSION = "ashare-frozen-generated-alpha-v1"

    def __init__(
        self,
        *,
        artifacts: Sequence[GeneratedFeatureArtifact],
        weights: Sequence[float],
        directions: Sequence[int],
        materializer: PanelGeneratedFeatureMaterializer,
        label_name: str = "forward_simple_return_1",
        ridge: float = 1e-8,
        min_observations: int = 250,
        winsor_lower_quantile: float = 0.01,
        winsor_upper_quantile: float = 0.99,
        sandbox: LocalFeatureSandbox | None = None,
        batch_size: int = 256,
    ) -> None:
        artifacts = tuple(artifacts)
        weights_array = np.asarray(tuple(weights), dtype=float)
        directions = tuple(int(value) for value in directions)
        if not artifacts or len({artifact.digest for artifact in artifacts}) != len(artifacts):
            raise ValueError("frozen A-share alpha requires unique artifacts")
        if weights_array.shape != (len(artifacts),) or len(directions) != len(artifacts):
            raise ValueError("frozen A-share alpha component arrays must align")
        if not np.all(np.isfinite(weights_array)) or np.any(weights_array < 0):
            raise ValueError("frozen A-share alpha weights must be finite and non-negative")
        total = float(weights_array.sum())
        if total <= 1e-15:
            raise ValueError("frozen A-share alpha weights require positive mass")
        if any(value not in {-1, 1} for value in directions):
            raise ValueError("frozen A-share alpha directions must be +/-1")
        if ridge < 0 or min_observations < 2 or batch_size < 1:
            raise ValueError("invalid frozen A-share alpha calibration settings")
        if not 0.0 <= winsor_lower_quantile < winsor_upper_quantile <= 1.0:
            raise ValueError("invalid frozen A-share alpha winsorization")
        label_name = label_name.strip()
        if not label_name:
            raise ValueError("label_name must be non-empty")

        self.artifacts = artifacts
        self.weights = tuple(float(value) for value in weights_array / total)
        self.directions = directions
        self.materializer = materializer
        self.label_name = label_name
        self.ridge = float(ridge)
        self.min_observations = int(min_observations)
        self.winsor_lower_quantile = float(winsor_lower_quantile)
        self.winsor_upper_quantile = float(winsor_upper_quantile)
        self.sandbox = sandbox or LocalFeatureSandbox()
        self.batch_size = int(batch_size)
        self._artifact: ArtifactRef | None = None
        self._calibration: AshareFrozenAlphaCalibration | None = None
        self._horizon: timedelta | None = None

    @property
    def required_features(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                field
                for artifact in self.artifacts
                for field in artifact.spec.input_fields
            )
        )

    @property
    def min_lookback(self) -> int:
        return max(artifact.spec.lookback for artifact in self.artifacts)

    @property
    def calibration(self) -> AshareFrozenAlphaCalibration:
        if self._calibration is None:
            raise RuntimeError("frozen A-share alpha must be fit first")
        return self._calibration

    @property
    def artifact(self) -> ArtifactRef:
        if self._artifact is None:
            raise RuntimeError("frozen A-share alpha must be fit first")
        return self._artifact

    def _combined_panel(
        self,
        request: DatasetRequest,
        split_name: str,
    ) -> tuple[np.ndarray, np.ndarray, object]:
        datasets = [
            self.materializer.materialize(artifact, request)
            for artifact in self.artifacts
        ]
        panels = [dataset.get_split(split_name) for dataset in datasets]
        first = panels[0]
        eligibility = np.array(first.eligibility_mask, dtype=bool, copy=True)
        for panel in panels[1:]:
            if (
                panel.timestamps != first.timestamps
                or panel.assets != first.assets
                or panel.label_names != first.label_names
            ):
                raise ValueError("frozen A-share factor panels are not aligned")
            if not np.array_equal(panel.label_values, first.label_values, equal_nan=True):
                raise ValueError("frozen A-share factor panels contain different labels")
            eligibility &= np.asarray(panel.eligibility_mask, dtype=bool)

        combined = np.full((first.n_times, first.n_assets), np.nan, dtype=float)
        for row in range(first.n_times):
            row_mask = eligibility[row].copy()
            component_rows = [panel.feature_values[row, :, 0] for panel in panels]
            for values in component_rows:
                row_mask &= np.isfinite(values)
            if int(row_mask.sum()) < 2:
                continue
            output = np.zeros(first.n_assets, dtype=float)
            for weight, direction, values in zip(
                self.weights,
                self.directions,
                component_rows,
                strict=True,
            ):
                winsorized = winsorize_cross_section(
                    values,
                    lower_quantile=self.winsor_lower_quantile,
                    upper_quantile=self.winsor_upper_quantile,
                    eligible=row_mask,
                )
                standardized = cross_sectional_zscore(winsorized, eligible=row_mask)
                output[row_mask] += weight * direction * standardized[row_mask]
            combined[row, row_mask] = output[row_mask]
            eligibility[row] &= row_mask
        return combined, eligibility, first

    def fit(self, request: DatasetRequest, *, split_name: str) -> ArtifactRef:
        if split_name not in request.splits:
            raise KeyError(f"training request has no split {split_name!r}")
        if self.label_name not in request.labels:
            raise KeyError(f"training request has no label {self.label_name!r}")
        missing = set(self.required_features) - set(request.features)
        if missing:
            raise KeyError(f"training request lacks factor inputs: {sorted(missing)}")

        score, eligibility, panel = self._combined_panel(request, split_name)
        labels = panel.label_panel(self.label_name)
        mask = eligibility & np.isfinite(score) & np.isfinite(labels)
        x = np.asarray(score[mask], dtype=float)
        y = np.asarray(labels[mask], dtype=float)
        if x.size < self.min_observations:
            raise ValueError(
                f"frozen A-share alpha calibration has {x.size} observations; "
                f"minimum is {self.min_observations}"
            )
        x_mean = float(np.mean(x))
        y_mean = float(np.mean(y))
        centered = x - x_mean
        denominator = float(np.dot(centered, centered) + self.ridge)
        raw_slope = (
            float(np.dot(centered, y - y_mean) / denominator)
            if denominator > 0
            else 0.0
        )
        slope = max(0.0, raw_slope)
        intercept = y_mean - slope * x_mean
        residual = y - (intercept + slope * x)
        residual_std = max(
            float(np.std(residual, ddof=1)) if residual.size > 1 else 0.0,
            1e-12,
        )
        self._calibration = AshareFrozenAlphaCalibration(
            intercept=intercept,
            non_negative_slope=slope,
            residual_std=residual_std,
            observations=int(x.size),
            raw_slope=raw_slope,
        )
        self._horizon = infer_horizon(panel)
        source_digest = "|".join(artifact.digest for artifact in self.artifacts)
        self._artifact = model_artifact(
            "ashare_frozen_generated_alpha",
            source_digest,
            {
                "version": self.VERSION,
                "training_dataset": panel.metadata.get("data_version", ""),
                "split": split_name,
                "label_name": self.label_name,
                "feature_digests": [artifact.digest for artifact in self.artifacts],
                "weights": list(self.weights),
                "directions": list(self.directions),
                "calibration": self._calibration.to_dict(),
            },
        )
        return self._artifact

    def _terminal_scores(
        self,
        artifact: GeneratedFeatureArtifact,
        window: FeatureWindow,
    ) -> np.ndarray:
        output = np.full(len(window.assets), np.nan, dtype=float)
        requests: list[FeatureSandboxRequest] = []
        indices: list[int] = []
        lookback = artifact.spec.lookback
        for asset_index in range(len(window.assets)):
            inputs: dict[str, list[float | None]] = {}
            valid = True
            for name in artifact.spec.input_fields:
                feature_index = window.feature_index(name)
                values = window.values[-lookback:, asset_index, feature_index]
                if not np.all(np.isfinite(values)):
                    valid = False
                    break
                inputs[name] = [float(value) for value in values]
            if valid:
                requests.append(FeatureSandboxRequest(artifact.spec, artifact.source, inputs))
                indices.append(asset_index)
        for start in range(0, len(requests), self.batch_size):
            results = self.sandbox.run_batch(tuple(requests[start : start + self.batch_size]))
            for offset, result in enumerate(results):
                value = result.values[-1]
                if value is not None and math.isfinite(float(value)):
                    output[indices[start + offset]] = float(value)
        return output

    def predict(
        self,
        window: FeatureWindow,
        *,
        eligible: Mapping[object, bool] | None = None,
    ) -> AlphaForecast:
        if self._artifact is None or self._calibration is None or self._horizon is None:
            raise RuntimeError("frozen A-share alpha must be fit before predict")
        missing = set(self.required_features) - set(window.feature_names)
        if missing:
            raise KeyError(f"prediction window lacks factor inputs: {sorted(missing)}")
        if window.lookback < self.min_lookback:
            raise ValueError("prediction window is shorter than factor lookback")

        component_values = [
            self._terminal_scores(artifact, window)
            for artifact in self.artifacts
        ]
        mask = np.ones(len(window.assets), dtype=bool)
        if eligible is not None:
            mask &= np.asarray(
                [bool(eligible.get(asset, False)) for asset in window.assets],
                dtype=bool,
            )
        for values in component_values:
            mask &= np.isfinite(values)
        if int(mask.sum()) < 1:
            raise ValueError("no eligible asset has complete frozen-factor inputs")

        combined = np.full(len(window.assets), np.nan, dtype=float)
        combined[mask] = 0.0
        for weight, direction, values in zip(
            self.weights,
            self.directions,
            component_values,
            strict=True,
        ):
            winsorized = winsorize_cross_section(
                values,
                lower_quantile=self.winsor_lower_quantile,
                upper_quantile=self.winsor_upper_quantile,
                eligible=mask,
            )
            standardized = cross_sectional_zscore(winsorized, eligible=mask)
            combined[mask] += weight * direction * standardized[mask]

        expected = {
            asset: (
                self._calibration.intercept
                + self._calibration.non_negative_slope * float(combined[index])
            )
            for index, asset in enumerate(window.assets)
            if mask[index] and np.isfinite(combined[index])
        }
        if not expected:
            raise ValueError("frozen A-share alpha produced no finite forecasts")
        return AlphaForecast(
            asof=window.asof,
            horizon=self._horizon,
            expected_returns=expected,
            uncertainty={
                asset: self._calibration.residual_std for asset in expected
            },
            source=ModelRef(
                name="ashare_frozen_generated_alpha",
                version=self._artifact.version,
                artifact_id=self._artifact.artifact_id,
            ),
            metadata={
                "version": self.VERSION,
                "feature_digests": "|".join(
                    artifact.digest for artifact in self.artifacts
                ),
                "weights": "|".join(repr(value) for value in self.weights),
                "directions": "|".join(str(value) for value in self.directions),
                "calibration_slope": repr(
                    self._calibration.non_negative_slope
                ),
            },
        )

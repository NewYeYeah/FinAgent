from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.domain.experiments import ArtifactRef
from finagent.domain.forecasts import AlphaForecast, ModelRef
from finagent.domain.research import FeatureWindow, ResearchDataset
from finagent.models._utils import infer_horizon, model_artifact
from finagent.sandbox import FeatureSandboxRequest, LocalFeatureSandbox


@dataclass(frozen=True, slots=True)
class GeneratedFeatureCalibration:
    intercept: float
    slope: float
    residual_std: float
    observations: int


class GeneratedFeatureAlphaModel:
    """Calibrate a validated generated feature into an ``AlphaForecast``.

    Generated code never receives a full panel.  During fit and predict each call is
    evaluated on one trailing PIT window, preserving the same sandbox boundary used
    by generated-feature research.  Calibration is a deterministic pooled linear
    regression with optional ridge shrinkage on the slope.
    """

    VERSION = "generated-feature-alpha-v1"

    def __init__(
        self,
        artifact: GeneratedFeatureArtifact,
        *,
        label_name: str = "forward_simple_return_1",
        ridge: float = 1e-8,
        min_observations: int = 30,
        sandbox: LocalFeatureSandbox | None = None,
        batch_size: int = 128,
    ) -> None:
        if ridge < 0:
            raise ValueError("ridge must be >= 0")
        if min_observations < 2:
            raise ValueError("min_observations must be >= 2")
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self.artifact = artifact
        self.label_name = label_name.strip()
        if not self.label_name:
            raise ValueError("label_name must be non-empty")
        self.ridge = float(ridge)
        self.min_observations = int(min_observations)
        self.sandbox = sandbox or LocalFeatureSandbox()
        self.batch_size = int(batch_size)
        self._artifact: ArtifactRef | None = None
        self._horizon = None
        self._calibration: GeneratedFeatureCalibration | None = None

    @property
    def required_features(self) -> tuple[str, ...]:
        return self.artifact.spec.input_fields

    @property
    def min_lookback(self) -> int:
        return self.artifact.spec.lookback

    @property
    def calibration(self) -> GeneratedFeatureCalibration:
        if self._calibration is None:
            raise RuntimeError("model must be fit before calibration is available")
        return self._calibration

    def _evaluate_requests(
        self,
        requests: list[FeatureSandboxRequest],
    ) -> list[float | None]:
        if not requests:
            return []
        run_batch = getattr(self.sandbox, "run_batch", None)
        output: list[float | None] = []
        if callable(run_batch):
            for start in range(0, len(requests), self.batch_size):
                results = run_batch(tuple(requests[start : start + self.batch_size]))
                for result in results:
                    last = result.values[-1]
                    output.append(None if last is None else float(last))
            return output
        for request in requests:
            result = self.sandbox.run(request)
            last = result.values[-1]
            output.append(None if last is None else float(last))
        return output

    def fit(self, dataset: ResearchDataset, split: str = "train") -> ArtifactRef:
        panel = dataset.get_split(split)
        if self.label_name not in panel.label_names:
            raise KeyError(f"label {self.label_name!r} not found in training split")
        missing = set(self.required_features) - set(panel.feature_names)
        if missing:
            raise KeyError(f"generated alpha training data missing features: {sorted(missing)}")

        lookback = self.min_lookback
        labels = panel.label_panel(self.label_name)
        requests: list[FeatureSandboxRequest] = []
        targets: list[float] = []
        for row in range(lookback - 1, panel.n_times):
            for asset_index in range(panel.n_assets):
                if not panel.eligibility_at(row)[asset_index]:
                    continue
                target = labels[row, asset_index]
                if not np.isfinite(target):
                    continue
                inputs: dict[str, list[float | None]] = {}
                valid = True
                for feature_name in self.required_features:
                    feature_index = panel.feature_names.index(feature_name)
                    values = panel.feature_values[
                        row - lookback + 1 : row + 1,
                        asset_index,
                        feature_index,
                    ]
                    if not np.all(np.isfinite(values)):
                        valid = False
                        break
                    inputs[feature_name] = [float(value) for value in values]
                if not valid:
                    continue
                requests.append(FeatureSandboxRequest(self.artifact.spec, self.artifact.source, inputs))
                targets.append(float(target))

        scores = self._evaluate_requests(requests)
        pairs = [
            (float(score), target)
            for score, target in zip(scores, targets)
            if score is not None and np.isfinite(score)
        ]
        if len(pairs) < self.min_observations:
            raise ValueError(
                f"generated alpha calibration has {len(pairs)} observations; "
                f"minimum is {self.min_observations}"
            )
        x = np.asarray([pair[0] for pair in pairs], dtype=float)
        y = np.asarray([pair[1] for pair in pairs], dtype=float)
        x_mean = float(np.mean(x))
        y_mean = float(np.mean(y))
        centered = x - x_mean
        denominator = float(np.dot(centered, centered) + self.ridge)
        slope = float(np.dot(centered, y - y_mean) / denominator) if denominator > 0 else 0.0
        intercept = y_mean - slope * x_mean
        residuals = y - (intercept + slope * x)
        residual_std = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0
        if not np.isfinite(residual_std):
            raise ValueError("generated alpha calibration produced non-finite uncertainty")
        residual_std = max(residual_std, 1e-12)

        self._calibration = GeneratedFeatureCalibration(
            intercept=intercept,
            slope=slope,
            residual_std=residual_std,
            observations=len(pairs),
        )
        self._horizon = infer_horizon(panel)
        self._artifact = model_artifact(
            "generated_feature_alpha",
            dataset.artifact.digest,
            {
                "feature_digest": self.artifact.digest,
                "label_name": self.label_name,
                "ridge": self.ridge,
                "split": split,
                "version": self.VERSION,
            },
        )
        return self._artifact

    def predict(self, window: FeatureWindow) -> AlphaForecast:
        if self._artifact is None or self._horizon is None or self._calibration is None:
            raise RuntimeError("model must be fit before predict")
        missing = set(self.required_features) - set(window.feature_names)
        if missing:
            raise KeyError(f"prediction window missing generated-alpha features: {sorted(missing)}")
        if window.lookback < self.min_lookback:
            raise ValueError("prediction window is shorter than generated feature lookback")

        requests: list[FeatureSandboxRequest] = []
        for asset_index, _asset in enumerate(window.assets):
            inputs: dict[str, list[float | None]] = {}
            for feature_name in self.required_features:
                feature_index = window.feature_names.index(feature_name)
                values = window.values[-self.min_lookback :, asset_index, feature_index]
                if not np.all(np.isfinite(values)):
                    raise ValueError("generated alpha prediction encountered non-finite PIT inputs")
                inputs[feature_name] = [float(value) for value in values]
            requests.append(FeatureSandboxRequest(self.artifact.spec, self.artifact.source, inputs))
        scores = self._evaluate_requests(requests)
        if len(scores) != len(window.assets) or any(score is None for score in scores):
            raise ValueError("generated feature did not produce a finite terminal score for every asset")

        expected_returns = {
            asset: self._calibration.intercept + self._calibration.slope * float(score)
            for asset, score in zip(window.assets, scores)
        }
        return AlphaForecast(
            asof=window.asof,
            horizon=self._horizon,
            expected_returns=expected_returns,
            uncertainty={asset: self._calibration.residual_std for asset in window.assets},
            source=ModelRef(
                name="generated_feature_alpha",
                version=self._artifact.version,
                artifact_id=self._artifact.artifact_id,
            ),
            metadata={
                "feature_id": self.artifact.spec.feature_id,
                "feature_digest": self.artifact.digest,
                "calibration_observations": str(self._calibration.observations),
            },
        )

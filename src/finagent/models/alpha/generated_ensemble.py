from __future__ import annotations

from typing import Sequence

import numpy as np

from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.domain.experiments import ArtifactRef
from finagent.domain.forecasts import AlphaForecast, ModelRef
from finagent.domain.research import FeatureWindow, ResearchDataset
from finagent.models._utils import model_artifact
from finagent.sandbox import LocalFeatureSandbox

from .calibration import AlphaForecastEnsembler
from .generated import GeneratedFeatureAlphaModel


class GeneratedFeatureEnsembleAlphaModel:
    """Standard ``AlphaModel`` adapter for a deterministic generated-factor ensemble.

    Every component is calibrated independently on the requested PIT training split by
    ``GeneratedFeatureAlphaModel``.  The resulting expected-return forecasts are then
    combined with frozen quantitative-research weights.  The LLM never estimates or
    changes ensemble weights inside this model.
    """

    VERSION = "generated-feature-ensemble-alpha-v1"

    def __init__(
        self,
        artifacts: Sequence[GeneratedFeatureArtifact],
        weights: Sequence[float],
        *,
        label_name: str = "forward_simple_return_1",
        ridge: float = 1e-8,
        min_observations: int = 30,
        sandbox: LocalFeatureSandbox | None = None,
        batch_size: int = 128,
    ) -> None:
        artifacts = tuple(artifacts)
        raw_weights = np.asarray(tuple(weights), dtype=float)
        if not artifacts:
            raise ValueError("generated feature ensemble requires artifacts")
        if len({artifact.digest for artifact in artifacts}) != len(artifacts):
            raise ValueError("generated feature ensemble contains duplicate artifacts")
        if raw_weights.shape != (len(artifacts),):
            raise ValueError("ensemble weights must match artifacts")
        if not np.all(np.isfinite(raw_weights)) or np.any(raw_weights < 0):
            raise ValueError("ensemble weights must be finite and non-negative")
        total = float(raw_weights.sum())
        if total <= 1e-15:
            raise ValueError("ensemble weights must have positive mass")
        label_name = label_name.strip()
        if not label_name:
            raise ValueError("label_name must be non-empty")

        self.artifacts = artifacts
        self.weights = tuple(float(value) for value in raw_weights / total)
        self.label_name = label_name
        shared_sandbox = sandbox or LocalFeatureSandbox()
        self.components = tuple(
            GeneratedFeatureAlphaModel(
                artifact,
                label_name=label_name,
                ridge=ridge,
                min_observations=min_observations,
                sandbox=shared_sandbox,
                batch_size=batch_size,
            )
            for artifact in artifacts
        )
        self.ensembler = AlphaForecastEnsembler()
        self._artifact: ArtifactRef | None = None
        self._component_artifacts: tuple[ArtifactRef, ...] = ()

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
    def component_artifacts(self) -> tuple[ArtifactRef, ...]:
        if not self._component_artifacts:
            raise RuntimeError("model must be fit before component artifacts are available")
        return self._component_artifacts

    def fit(self, dataset: ResearchDataset, split: str = "train") -> ArtifactRef:
        if not dataset.point_in_time:
            raise ValueError("generated feature ensemble requires a point-in-time dataset")
        missing = set(self.required_features) - set(dataset.features)
        if missing:
            raise KeyError(f"ensemble training data missing features: {sorted(missing)}")
        if self.label_name not in dataset.labels:
            raise KeyError(f"ensemble label {self.label_name!r} not found in dataset")

        component_artifacts = tuple(component.fit(dataset, split) for component in self.components)
        self._component_artifacts = component_artifacts
        self._artifact = model_artifact(
            "generated_feature_ensemble_alpha",
            dataset.artifact.digest,
            {
                "version": self.VERSION,
                "split": split,
                "label_name": self.label_name,
                "feature_digests": [artifact.digest for artifact in self.artifacts],
                "weights": list(self.weights),
                "component_model_digests": [artifact.digest for artifact in component_artifacts],
            },
        )
        return self._artifact

    def predict(self, window: FeatureWindow) -> AlphaForecast:
        if self._artifact is None:
            raise RuntimeError("model must be fit before predict")
        missing = set(self.required_features) - set(window.feature_names)
        if missing:
            raise KeyError(f"prediction window missing ensemble features: {sorted(missing)}")
        if window.lookback < self.min_lookback:
            raise ValueError("prediction window is shorter than ensemble min_lookback")

        forecasts = tuple(component.predict(window) for component in self.components)
        source = ModelRef(
            name="generated_feature_ensemble_alpha",
            version=self._artifact.version,
            artifact_id=self._artifact.artifact_id,
        )
        combined = self.ensembler.combine(forecasts, self.weights, source=source).forecast
        return AlphaForecast(
            asof=combined.asof,
            horizon=combined.horizon,
            expected_returns=combined.expected_returns,
            uncertainty=combined.uncertainty,
            source=combined.source,
            metadata={
                **dict(combined.metadata),
                "feature_ids": "|".join(artifact.spec.feature_id for artifact in self.artifacts),
                "feature_digests": "|".join(artifact.digest for artifact in self.artifacts),
                "weights": "|".join(repr(value) for value in self.weights),
                "label_name": self.label_name,
                "ensemble_version": self.VERSION,
            },
        )

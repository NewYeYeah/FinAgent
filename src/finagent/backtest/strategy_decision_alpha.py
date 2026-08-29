from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.domain.assets import AssetId
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.models.alpha.ashare_frozen import AshareFrozenGeneratedFeatureAlphaModel
from finagent.research.ashare_universe import AshareResearchUniverseProvider
from finagent.research.panel_feature_materializer import PanelGeneratedFeatureMaterializer


@dataclass(frozen=True, slots=True)
class StrategyDecisionAlphaFoldSpec:
    fold_id: str
    train_split: str
    train_range: TimeRange
    expected_alpha_model_id: str

    def __post_init__(self) -> None:
        if not self.fold_id.strip():
            raise ValueError("fold_id is required")
        if not self.train_split.strip():
            raise ValueError("train_split is required")
        if not self.expected_alpha_model_id.strip():
            raise ValueError("expected_alpha_model_id is required")


class AshareStrategyDecisionAlphaReplay:
    """Replay the exact frozen A4 AlphaModel at historical formation timestamps.

    This class deliberately stops before risk/optimizer/execution.  It only rebuilds
    the train-only calibration already bound into A4, verifies the resulting model
    artifact identity, and replays the same eligible cross-sectional forecast used by
    A4 formation.  No forward labels are requested by prediction windows.
    """

    def __init__(
        self,
        *,
        research_adapter,
        universe_provider: AshareResearchUniverseProvider,
        artifacts: Sequence[GeneratedFeatureArtifact],
        weights: Sequence[float],
        directions: Sequence[int],
        universe: Sequence[AssetId],
        primary_label: str,
        risk_lookback: int,
        alpha_ridge: float,
        alpha_min_observations: int,
        winsor_lower_quantile: float,
        winsor_upper_quantile: float,
        folds: Sequence[StrategyDecisionAlphaFoldSpec],
    ) -> None:
        self.research_adapter = research_adapter
        self.universe_provider = universe_provider
        self.artifacts = tuple(artifacts)
        self.weights = tuple(float(value) for value in weights)
        self.directions = tuple(int(value) for value in directions)
        self.universe = tuple(universe)
        self.primary_label = primary_label.strip()
        self.risk_lookback = int(risk_lookback)
        self.alpha_ridge = float(alpha_ridge)
        self.alpha_min_observations = int(alpha_min_observations)
        self.winsor_lower_quantile = float(winsor_lower_quantile)
        self.winsor_upper_quantile = float(winsor_upper_quantile)
        self._folds = {value.fold_id: value for value in folds}
        self._models: dict[str, AshareFrozenGeneratedFeatureAlphaModel] = {}

        if not self.artifacts or len({value.digest for value in self.artifacts}) != len(
            self.artifacts
        ):
            raise ValueError("V4-0 alpha replay requires unique frozen artifacts")
        if not (
            len(self.artifacts) == len(self.weights) == len(self.directions)
        ):
            raise ValueError("V4-0 frozen alpha component arrays must align")
        if not self.universe or len(set(self.universe)) != len(self.universe):
            raise ValueError("V4-0 alpha replay universe must be non-empty and unique")
        if not self.primary_label:
            raise ValueError("primary_label is required")
        if self.risk_lookback < 1:
            raise ValueError("risk_lookback must be >= 1")
        if len(self._folds) != len(tuple(folds)) or not self._folds:
            raise ValueError("V4-0 alpha replay requires unique fold specifications")

    def _model(self, fold_id: str) -> AshareFrozenGeneratedFeatureAlphaModel:
        existing = self._models.get(fold_id)
        if existing is not None:
            return existing
        try:
            fold = self._folds[fold_id]
        except KeyError as exc:
            raise KeyError(f"unknown V4-0 alpha replay fold: {fold_id}") from exc

        required = tuple(
            dict.fromkeys(
                field
                for artifact in self.artifacts
                for field in artifact.spec.input_fields
            )
        )
        request = DatasetRequest(
            universe=self.universe,
            features=required,
            labels=(self.primary_label,),
            splits={fold.train_split: fold.train_range},
            dataset_id=f"a4-{fold.fold_id}-train",
            metadata={"scope": "A4 internal training only"},
        )
        materializer = PanelGeneratedFeatureMaterializer(
            self.research_adapter,
            universe_provider=self.universe_provider,
        )
        model = AshareFrozenGeneratedFeatureAlphaModel(
            artifacts=self.artifacts,
            weights=self.weights,
            directions=self.directions,
            materializer=materializer,
            label_name=self.primary_label,
            ridge=self.alpha_ridge,
            min_observations=self.alpha_min_observations,
            winsor_lower_quantile=self.winsor_lower_quantile,
            winsor_upper_quantile=self.winsor_upper_quantile,
        )
        model.fit(request, split_name=fold.train_split)
        if model.artifact.digest != fold.expected_alpha_model_id:
            raise ValueError(
                "V4-0 alpha replay identity mismatch for "
                f"{fold_id}: {model.artifact.digest} != {fold.expected_alpha_model_id}"
            )
        self._models[fold_id] = model
        return model

    def snapshot(
        self,
        fold_id: str,
        signal_asof: datetime,
    ) -> Mapping[str, Mapping[str, object]]:
        if signal_asof.tzinfo is None or signal_asof.utcoffset() is None:
            raise ValueError("signal_asof must be timezone-aware")
        model = self._model(fold_id)
        calibration = model.calibration
        if calibration.non_negative_slope <= 1e-15:
            return {}

        lookback = max(model.min_lookback, self.risk_lookback)
        fields = tuple(dict.fromkeys((*model.required_features, "simple_return_1")))
        window = self.research_adapter.feature_window(
            asof=signal_asof,
            universe=self.universe,
            features=fields,
            lookback=lookback,
        )
        formation = self.universe_provider.snapshot(window.timestamps[-1], self.universe)
        eligible = {
            asset: bool(formation.eligible.get(asset, False)) for asset in self.universe
        }
        forecast = model.predict(window, eligible=eligible)
        if forecast.asof != window.asof:
            raise ValueError("V4-0 AlphaForecast asof differs from formation window")

        scores: dict[AssetId, float] = {}
        for asset, expected in forecast.expected_returns.items():
            score = (float(expected) - calibration.intercept) / (
                calibration.non_negative_slope
            )
            if not math.isfinite(score):
                raise ValueError(f"non-finite V4-0 alpha score for {asset.key}")
            scores[asset] = score
        ordered = sorted(scores, key=lambda asset: (-scores[asset], asset.key))
        ranks = {asset: index + 1 for index, asset in enumerate(ordered)}
        return {
            asset.key: {
                "score": scores[asset],
                "rank": ranks[asset],
                "expected_return": float(forecast.expected_returns[asset]),
                "uncertainty": (
                    float(forecast.uncertainty[asset])
                    if asset in forecast.uncertainty
                    else None
                ),
                "alpha_model_id": model.artifact.digest,
            }
            for asset in sorted(scores)
        }

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping, Sequence

import numpy as np

from finagent.domain.assets import AssetId
from finagent.domain.forecasts import AlphaForecast, ModelRef
from finagent.domain.research import ResearchDataset, ResearchSplit


@dataclass(frozen=True, slots=True)
class CrossSectionalCalibrationResult:
    feature_name: str
    label_name: str
    intercept: float
    slope: float
    residual_std: float
    r_squared: float
    n_observations: int
    n_periods: int

    def __post_init__(self) -> None:
        numeric = (self.intercept, self.slope, self.residual_std, self.r_squared)
        if not all(np.isfinite(value) for value in numeric):
            raise ValueError("calibration statistics must be finite")
        if self.residual_std < 0:
            raise ValueError("residual_std must be >= 0")
        if self.n_observations < 2 or self.n_periods < 1:
            raise ValueError("calibration result contains too few observations")


class CrossSectionalLinearAlphaCalibrator:
    """Map a cross-sectional feature score into an expected-return forecast.

    Training is deliberately transparent: each period's feature scores are standardized
    cross-sectionally and pooled into a ridge-regularized linear regression against a
    forward-return label. The caller controls which PIT-safe split is used for fitting.
    """

    VERSION = "cross-sectional-linear-v1"

    def __init__(
        self,
        *,
        ridge: float = 1e-6,
        min_cross_section: int = 3,
        min_periods: int = 10,
        winsor_z: float | None = 4.0,
    ) -> None:
        if ridge < 0:
            raise ValueError("ridge must be >= 0")
        if min_cross_section < 2:
            raise ValueError("min_cross_section must be >= 2")
        if min_periods < 2:
            raise ValueError("min_periods must be >= 2")
        if winsor_z is not None and winsor_z <= 0:
            raise ValueError("winsor_z must be > 0 when supplied")
        self.ridge = float(ridge)
        self.min_cross_section = int(min_cross_section)
        self.min_periods = int(min_periods)
        self.winsor_z = float(winsor_z) if winsor_z is not None else None
        self._result: CrossSectionalCalibrationResult | None = None

    @property
    def result(self) -> CrossSectionalCalibrationResult:
        if self._result is None:
            raise RuntimeError("calibrator has not been fitted")
        return self._result

    @staticmethod
    def _standardize(values: np.ndarray, winsor_z: float | None) -> np.ndarray | None:
        values = np.asarray(values, dtype=float)
        std = float(np.std(values, ddof=0))
        if std <= 1e-15:
            return None
        z = (values - float(np.mean(values))) / std
        if winsor_z is not None:
            z = np.clip(z, -winsor_z, winsor_z)
        return z

    def fit(
        self,
        split: ResearchSplit,
        *,
        feature_name: str,
        label_name: str,
    ) -> CrossSectionalCalibrationResult:
        feature = split.feature_panel(feature_name)
        label = split.label_panel(label_name)
        pooled_x: list[float] = []
        pooled_y: list[float] = []
        used_periods = 0

        for row in range(split.n_times):
            valid = np.isfinite(feature[row]) & np.isfinite(label[row])
            if int(valid.sum()) < self.min_cross_section:
                continue
            z = self._standardize(feature[row][valid], self.winsor_z)
            if z is None:
                continue
            pooled_x.extend(float(value) for value in z)
            pooled_y.extend(float(value) for value in label[row][valid])
            used_periods += 1

        if used_periods < self.min_periods:
            raise ValueError(
                f"only {used_periods} usable calibration periods; minimum is {self.min_periods}"
            )
        x = np.asarray(pooled_x, dtype=float)
        y = np.asarray(pooled_y, dtype=float)
        design = np.column_stack([np.ones_like(x), x])
        penalty = np.diag([0.0, self.ridge])
        beta = np.linalg.solve(design.T @ design + penalty, design.T @ y)
        fitted = design @ beta
        residual = y - fitted
        residual_std = float(np.sqrt(np.mean(residual * residual)))
        centered = y - float(np.mean(y))
        total_ss = float(centered @ centered)
        residual_ss = float(residual @ residual)
        r_squared = 1.0 - residual_ss / total_ss if total_ss > 1e-15 else 0.0
        result = CrossSectionalCalibrationResult(
            feature_name=feature_name,
            label_name=label_name,
            intercept=float(beta[0]),
            slope=float(beta[1]),
            residual_std=residual_std,
            r_squared=float(r_squared),
            n_observations=int(y.size),
            n_periods=used_periods,
        )
        self._result = result
        return result

    def fit_dataset(
        self,
        dataset: ResearchDataset,
        *,
        split_name: str,
        feature_name: str,
        label_name: str,
    ) -> CrossSectionalCalibrationResult:
        if not dataset.point_in_time:
            raise ValueError("alpha calibration requires a point-in-time ResearchDataset")
        return self.fit(
            dataset.get_split(split_name),
            feature_name=feature_name,
            label_name=label_name,
        )

    def forecast(
        self,
        *,
        asof: datetime,
        horizon: timedelta,
        scores: Mapping[AssetId, float],
        source: ModelRef | None = None,
    ) -> AlphaForecast:
        result = self.result
        if len(scores) < 2:
            raise ValueError("at least two cross-sectional scores are required")
        assets = tuple(sorted(scores))
        raw = np.asarray([float(scores[asset]) for asset in assets], dtype=float)
        if not np.all(np.isfinite(raw)):
            raise ValueError("scores must be finite")
        z = self._standardize(raw, self.winsor_z)
        if z is None:
            z = np.zeros_like(raw)
        expected = result.intercept + result.slope * z
        model_ref = source or ModelRef(
            name="cross_sectional_alpha_calibrator",
            version=self.VERSION,
        )
        return AlphaForecast(
            asof=asof,
            horizon=horizon,
            expected_returns={asset: float(expected[idx]) for idx, asset in enumerate(assets)},
            uncertainty={asset: result.residual_std for asset in assets},
            source=model_ref,
            metadata={
                "feature_name": result.feature_name,
                "label_name": result.label_name,
                "slope": repr(result.slope),
                "r_squared": repr(result.r_squared),
                "n_observations": str(result.n_observations),
            },
        )


@dataclass(frozen=True, slots=True)
class AlphaEnsembleResult:
    forecast: AlphaForecast
    normalized_weights: tuple[float, ...]


class AlphaForecastEnsembler:
    """Deterministically combine aligned AlphaForecast objects.

    Weights are supplied by quantitative research/governance code, not inferred by an
    LLM. They are normalized to sum to one; component uncertainty is combined under a
    zero-correlation approximation to keep the contract explicit and conservative.
    """

    VERSION = "alpha-ensemble-v1"

    def combine(
        self,
        forecasts: Sequence[AlphaForecast],
        weights: Sequence[float],
        *,
        source: ModelRef | None = None,
    ) -> AlphaEnsembleResult:
        forecasts = tuple(forecasts)
        raw_weights = np.asarray(tuple(weights), dtype=float)
        if not forecasts:
            raise ValueError("forecasts cannot be empty")
        if raw_weights.shape != (len(forecasts),):
            raise ValueError("weights must match number of forecasts")
        if not np.all(np.isfinite(raw_weights)):
            raise ValueError("ensemble weights must be finite")
        total = float(raw_weights.sum())
        if abs(total) <= 1e-15:
            raise ValueError("ensemble weights must have a non-zero sum")
        normalized = raw_weights / total

        first = forecasts[0]
        universe = set(first.expected_returns)
        for forecast in forecasts[1:]:
            if forecast.asof != first.asof or forecast.horizon != first.horizon:
                raise ValueError("all alpha forecasts must share asof and horizon")
            if set(forecast.expected_returns) != universe:
                raise ValueError("all alpha forecasts must share the same universe")

        expected: dict[AssetId, float] = {}
        uncertainty: dict[AssetId, float] = {}
        for asset in sorted(universe):
            component_returns = np.asarray(
                [forecast.expected_returns[asset] for forecast in forecasts], dtype=float
            )
            expected[asset] = float(normalized @ component_returns)
            component_uncertainty = np.asarray(
                [forecast.uncertainty.get(asset, 0.0) for forecast in forecasts], dtype=float
            )
            uncertainty[asset] = float(
                np.sqrt(np.sum((normalized * component_uncertainty) ** 2))
            )

        model_ref = source or ModelRef(name="alpha_ensemble", version=self.VERSION)
        combined = AlphaForecast(
            asof=first.asof,
            horizon=first.horizon,
            expected_returns=expected,
            uncertainty=uncertainty,
            source=model_ref,
            metadata={
                "components": ",".join(
                    f"{forecast.source.name}@{forecast.source.version}" for forecast in forecasts
                ),
                "weights": ",".join(repr(float(value)) for value in normalized),
            },
        )
        return AlphaEnsembleResult(
            forecast=combined,
            normalized_weights=tuple(float(value) for value in normalized),
        )

    @staticmethod
    def quality_weights(
        quality_scores: Sequence[float],
        *,
        floor: float = 0.0,
        power: float = 1.0,
    ) -> tuple[float, ...]:
        if power <= 0:
            raise ValueError("power must be > 0")
        scores = np.asarray(tuple(quality_scores), dtype=float)
        if scores.size == 0 or not np.all(np.isfinite(scores)):
            raise ValueError("quality_scores must be non-empty and finite")
        positive = np.maximum(scores - float(floor), 0.0) ** float(power)
        total = float(positive.sum())
        if total <= 1e-15:
            raise ValueError("quality scores contain no mass above floor")
        return tuple(float(value) for value in positive / total)

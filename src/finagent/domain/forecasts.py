from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Mapping

import numpy as np

from ._validation import (
    freeze_mapping,
    require_aware_datetime,
    require_finite,
    require_non_empty,
    require_non_negative,
)
from .assets import AssetId


@dataclass(frozen=True, slots=True)
class ModelRef:
    name: str
    version: str
    artifact_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", require_non_empty(self.name, "name"))
        object.__setattr__(self, "version", require_non_empty(self.version, "version"))
        object.__setattr__(self, "artifact_id", self.artifact_id.strip())


@dataclass(frozen=True, slots=True)
class AlphaForecast:
    """Expected-return forecast emitted by an alpha model."""

    asof: datetime
    horizon: timedelta
    expected_returns: Mapping[AssetId, float]
    source: ModelRef
    uncertainty: Mapping[AssetId, float] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        asof = require_aware_datetime(self.asof, "asof")
        if self.horizon <= timedelta(0):
            raise ValueError("horizon must be positive")
        expected_returns = freeze_mapping(
            {asset: require_finite(value, f"expected_returns[{asset.key}]") for asset, value in self.expected_returns.items()}
        )
        if not expected_returns:
            raise ValueError("expected_returns cannot be empty")

        uncertainty_raw = {
            asset: require_non_negative(value, f"uncertainty[{asset.key}]")
            for asset, value in self.uncertainty.items()
        }
        unknown = set(uncertainty_raw) - set(expected_returns)
        if unknown:
            keys = ", ".join(sorted(asset.key for asset in unknown))
            raise ValueError(f"uncertainty contains assets absent from expected_returns: {keys}")

        object.__setattr__(self, "asof", asof)
        object.__setattr__(self, "expected_returns", expected_returns)
        object.__setattr__(self, "uncertainty", freeze_mapping(uncertainty_raw))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class RiskForecast:
    """Volatility/covariance forecast with explicit numerical validation.

    Phase 1 adds positive-semidefinite validation in addition to completeness,
    symmetry and diagonal/volatility consistency.
    """

    asof: datetime
    horizon: timedelta
    volatilities: Mapping[AssetId, float]
    covariance: Mapping[tuple[AssetId, AssetId], float]
    source: ModelRef
    metadata: Mapping[str, str] = field(default_factory=dict)
    symmetry_tolerance: float = 1e-12

    def __post_init__(self) -> None:
        asof = require_aware_datetime(self.asof, "asof")
        if self.horizon <= timedelta(0):
            raise ValueError("horizon must be positive")
        if self.symmetry_tolerance < 0:
            raise ValueError("symmetry_tolerance must be >= 0")

        vols = {
            asset: require_non_negative(value, f"volatilities[{asset.key}]")
            for asset, value in self.volatilities.items()
        }
        if not vols:
            raise ValueError("volatilities cannot be empty")
        assets = set(vols)

        cov: dict[tuple[AssetId, AssetId], float] = {}
        for key, value in self.covariance.items():
            if not isinstance(key, tuple) or len(key) != 2:
                raise TypeError("covariance keys must be (AssetId, AssetId) tuples")
            left, right = key
            if left not in assets or right not in assets:
                raise ValueError("covariance contains an asset absent from volatilities")
            cov[(left, right)] = require_finite(value, f"covariance[{left.key},{right.key}]")

        missing: list[str] = []
        for left in assets:
            for right in assets:
                if (left, right) not in cov:
                    missing.append(f"({left.key}, {right.key})")
        if missing:
            raise ValueError(f"covariance matrix is incomplete; missing: {', '.join(sorted(missing))}")

        ordered_assets = tuple(sorted(assets))
        for left in assets:
            diagonal = cov[(left, left)]
            if diagonal < 0:
                raise ValueError(f"covariance diagonal for {left.key} must be >= 0")
            variance_from_vol = vols[left] ** 2
            if abs(diagonal - variance_from_vol) > max(self.symmetry_tolerance, 1e-10):
                raise ValueError(
                    f"covariance diagonal for {left.key} ({diagonal}) does not match volatility^2 ({variance_from_vol})"
                )
            for right in assets:
                if abs(cov[(left, right)] - cov[(right, left)]) > self.symmetry_tolerance:
                    raise ValueError(f"covariance matrix is not symmetric for {left.key}, {right.key}")

        matrix = np.asarray(
            [[cov[(left, right)] for right in ordered_assets] for left in ordered_assets],
            dtype=float,
        )
        minimum_eigenvalue = float(np.min(np.linalg.eigvalsh(matrix)))
        if minimum_eigenvalue < -max(self.symmetry_tolerance, 1e-10):
            raise ValueError(
                f"covariance matrix must be positive semidefinite; minimum eigenvalue={minimum_eigenvalue}"
            )

        object.__setattr__(self, "asof", asof)
        object.__setattr__(self, "volatilities", freeze_mapping(vols))
        object.__setattr__(self, "covariance", freeze_mapping(cov))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))

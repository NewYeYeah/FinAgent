from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

import numpy as np
from numpy.typing import NDArray

from ._validation import freeze_mapping, require_aware_datetime, require_non_empty
from .assets import AssetId
from .experiments import ArtifactRef, ArtifactType

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]


def _readonly_float_array(value: object, *, ndim: int, name: str) -> FloatArray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != ndim:
        raise ValueError(f"{name} must be {ndim}-dimensional, got shape {array.shape}")
    if np.isinf(array).any():
        raise ValueError(f"{name} cannot contain +/-inf")
    array = np.array(array, dtype=np.float64, copy=True, order="C")
    array.setflags(write=False)
    return array


def _readonly_bool_array(value: object, *, shape: tuple[int, ...], name: str) -> BoolArray:
    array = np.asarray(value, dtype=np.bool_)
    if array.shape != shape:
        raise ValueError(f"{name} must have shape {shape}, got {array.shape}")
    array = np.array(array, dtype=np.bool_, copy=True, order="C")
    array.setflags(write=False)
    return array


@dataclass(frozen=True, slots=True)
class TimeRange:
    """Half-open timezone-aware interval ``[start, end)``."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        start = require_aware_datetime(self.start, "start")
        end = require_aware_datetime(self.end, "end")
        if end <= start:
            raise ValueError("TimeRange.end must be later than start")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    def contains(self, value: datetime) -> bool:
        value = require_aware_datetime(value, "value")
        return self.start <= value < self.end


@dataclass(frozen=True, slots=True)
class ResearchSplit:
    """Canonical immutable numerical panel for one research split.

    Arrays use a stable panel layout:

    ``features.shape == (time, asset, feature)``
    ``labels.shape   == (time, asset, label)``

    ``eligibility_mask.shape == (time, asset)`` is the point-in-time *formation*
    contract. It records which assets were investable using information available at
    each timestamp and must never be inferred from forward-label availability.
    """

    timestamps: tuple[datetime, ...]
    assets: tuple[AssetId, ...]
    feature_names: tuple[str, ...]
    label_names: tuple[str, ...]
    feature_values: FloatArray
    label_values: FloatArray
    metadata: Mapping[str, str] = field(default_factory=dict)
    eligibility_mask: BoolArray | None = None

    def __post_init__(self) -> None:
        if not self.timestamps:
            raise ValueError("timestamps cannot be empty")
        timestamps = tuple(require_aware_datetime(ts, "timestamp") for ts in self.timestamps)
        if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
            raise ValueError("timestamps must be strictly increasing")
        if not self.assets:
            raise ValueError("assets cannot be empty")
        if len(set(self.assets)) != len(self.assets):
            raise ValueError("assets cannot contain duplicates")
        if not self.feature_names:
            raise ValueError("feature_names cannot be empty")
        if not self.label_names:
            raise ValueError("label_names cannot be empty")
        if len(set(self.feature_names)) != len(self.feature_names):
            raise ValueError("feature_names cannot contain duplicates")
        if len(set(self.label_names)) != len(self.label_names):
            raise ValueError("label_names cannot contain duplicates")
        feature_names = tuple(require_non_empty(name, "feature name") for name in self.feature_names)
        label_names = tuple(require_non_empty(name, "label name") for name in self.label_names)

        features = _readonly_float_array(self.feature_values, ndim=3, name="feature_values")
        labels = _readonly_float_array(self.label_values, ndim=3, name="label_values")
        expected_feature_shape = (len(timestamps), len(self.assets), len(feature_names))
        expected_label_shape = (len(timestamps), len(self.assets), len(label_names))
        if features.shape != expected_feature_shape:
            raise ValueError(
                f"feature_values shape must be {expected_feature_shape}, got {features.shape}"
            )
        if labels.shape != expected_label_shape:
            raise ValueError(
                f"label_values shape must be {expected_label_shape}, got {labels.shape}"
            )

        eligibility = self.eligibility_mask
        if eligibility is None:
            eligibility = np.ones((len(timestamps), len(self.assets)), dtype=np.bool_)
        eligibility = _readonly_bool_array(
            eligibility,
            shape=(len(timestamps), len(self.assets)),
            name="eligibility_mask",
        )

        object.__setattr__(self, "timestamps", timestamps)
        object.__setattr__(self, "feature_names", feature_names)
        object.__setattr__(self, "label_names", label_names)
        object.__setattr__(self, "feature_values", features)
        object.__setattr__(self, "label_values", labels)
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))
        object.__setattr__(self, "eligibility_mask", eligibility)

    @property
    def n_times(self) -> int:
        return len(self.timestamps)

    @property
    def n_assets(self) -> int:
        return len(self.assets)

    def feature_index(self, name: str) -> int:
        try:
            return self.feature_names.index(name)
        except ValueError as exc:
            raise KeyError(f"unknown feature {name!r}") from exc

    def label_index(self, name: str) -> int:
        try:
            return self.label_names.index(name)
        except ValueError as exc:
            raise KeyError(f"unknown label {name!r}") from exc

    def asset_index(self, asset: AssetId) -> int:
        try:
            return self.assets.index(asset)
        except ValueError as exc:
            raise KeyError(f"unknown asset {asset.key}") from exc

    def feature_panel(self, name: str) -> FloatArray:
        panel = self.feature_values[:, :, self.feature_index(name)]
        panel.setflags(write=False)
        return panel

    def label_panel(self, name: str) -> FloatArray:
        panel = self.label_values[:, :, self.label_index(name)]
        panel.setflags(write=False)
        return panel

    def eligibility_at(self, row: int) -> BoolArray:
        mask = self.eligibility_mask[row]
        mask.setflags(write=False)
        return mask

    def asset_feature(self, asset: AssetId, name: str) -> FloatArray:
        series = self.feature_values[:, self.asset_index(asset), self.feature_index(name)]
        series.setflags(write=False)
        return series

    def asset_label(self, asset: AssetId, name: str) -> FloatArray:
        series = self.label_values[:, self.asset_index(asset), self.label_index(name)]
        series.setflags(write=False)
        return series


@dataclass(frozen=True, slots=True)
class FeatureWindow:
    """Numerical inference input emitted by a DataAdapter.

    The stable layout is ``values[time, asset, feature]`` and contains only
    observations available at or before ``asof``.
    """

    asof: datetime
    timestamps: tuple[datetime, ...]
    assets: tuple[AssetId, ...]
    feature_names: tuple[str, ...]
    values: FloatArray
    data_version: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        asof = require_aware_datetime(self.asof, "asof")
        if not self.timestamps:
            raise ValueError("timestamps cannot be empty")
        timestamps = tuple(require_aware_datetime(ts, "timestamp") for ts in self.timestamps)
        if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
            raise ValueError("timestamps must be strictly increasing")
        if timestamps[-1] > asof:
            raise ValueError("feature window contains a timestamp later than asof")
        if not self.assets:
            raise ValueError("assets cannot be empty")
        if len(set(self.assets)) != len(self.assets):
            raise ValueError("assets cannot contain duplicates")
        if not self.feature_names:
            raise ValueError("feature_names cannot be empty")
        feature_names = tuple(require_non_empty(name, "feature name") for name in self.feature_names)
        if len(set(feature_names)) != len(feature_names):
            raise ValueError("feature_names cannot contain duplicates")
        values = _readonly_float_array(self.values, ndim=3, name="values")
        expected = (len(timestamps), len(self.assets), len(feature_names))
        if values.shape != expected:
            raise ValueError(f"values shape must be {expected}, got {values.shape}")

        object.__setattr__(self, "asof", asof)
        object.__setattr__(self, "timestamps", timestamps)
        object.__setattr__(self, "feature_names", feature_names)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "data_version", require_non_empty(self.data_version, "data_version"))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))

    @property
    def lookback(self) -> int:
        return len(self.timestamps)

    def feature_index(self, name: str) -> int:
        try:
            return self.feature_names.index(name)
        except ValueError as exc:
            raise KeyError(f"unknown feature {name!r}") from exc

    def asset_index(self, asset: AssetId) -> int:
        try:
            return self.assets.index(asset)
        except ValueError as exc:
            raise KeyError(f"unknown asset {asset.key}") from exc

    def feature_panel(self, name: str) -> FloatArray:
        panel = self.values[:, :, self.feature_index(name)]
        panel.setflags(write=False)
        return panel

    def asset_feature(self, asset: AssetId, name: str) -> FloatArray:
        series = self.values[:, self.asset_index(asset), self.feature_index(name)]
        series.setflags(write=False)
        return series


@dataclass(frozen=True, slots=True)
class DatasetRequest:
    """Framework-independent request sent to a DataAdapter."""

    universe: tuple[AssetId, ...]
    features: tuple[str, ...]
    labels: tuple[str, ...]
    splits: Mapping[str, TimeRange]
    dataset_id: str = "research-dataset"
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.universe:
            raise ValueError("universe cannot be empty")
        if len(set(self.universe)) != len(self.universe):
            raise ValueError("universe cannot contain duplicate assets")
        if not self.features:
            raise ValueError("features cannot be empty")
        if not self.labels:
            raise ValueError("labels cannot be empty")
        features = tuple(require_non_empty(name, "feature name") for name in self.features)
        labels = tuple(require_non_empty(name, "label name") for name in self.labels)
        if len(set(features)) != len(features):
            raise ValueError("features cannot contain duplicates")
        if len(set(labels)) != len(labels):
            raise ValueError("labels cannot contain duplicates")
        if not self.splits:
            raise ValueError("splits cannot be empty")
        for name, time_range in self.splits.items():
            require_non_empty(name, "split name")
            if not isinstance(time_range, TimeRange):
                raise TypeError("split values must be TimeRange instances")
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "splits", freeze_mapping(self.splits))
        object.__setattr__(self, "dataset_id", require_non_empty(self.dataset_id, "dataset_id"))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class ResearchDataset:
    """Reproducible PIT dataset manifest plus optional immutable numerical panels."""

    artifact: ArtifactRef
    universe: tuple[AssetId, ...]
    features: tuple[str, ...]
    labels: tuple[str, ...]
    splits: Mapping[str, TimeRange]
    point_in_time: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)
    panels: Mapping[str, ResearchSplit] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.artifact.artifact_type is not ArtifactType.DATASET:
            raise ValueError("ResearchDataset.artifact must have artifact_type=DATASET")
        if not self.universe:
            raise ValueError("universe cannot be empty")
        if len(set(self.universe)) != len(self.universe):
            raise ValueError("universe cannot contain duplicate assets")
        if not self.features:
            raise ValueError("features cannot be empty")
        if not self.labels:
            raise ValueError("labels cannot be empty")
        if len(set(self.features)) != len(self.features):
            raise ValueError("features cannot contain duplicates")
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("labels cannot contain duplicates")
        features = tuple(require_non_empty(name, "feature name") for name in self.features)
        labels = tuple(require_non_empty(name, "label name") for name in self.labels)
        if not self.splits:
            raise ValueError("splits cannot be empty")
        for split_name, split_range in self.splits.items():
            require_non_empty(split_name, "split name")
            if not isinstance(split_range, TimeRange):
                raise TypeError("split values must be TimeRange instances")

        panels = dict(self.panels)
        unknown_panels = set(panels) - set(self.splits)
        if unknown_panels:
            raise ValueError(f"panels contain unknown splits: {sorted(unknown_panels)}")
        for split_name, panel in panels.items():
            if not isinstance(panel, ResearchSplit):
                raise TypeError("panel values must be ResearchSplit instances")
            if panel.assets != self.universe:
                raise ValueError(f"panel {split_name!r} assets must match dataset universe order")
            if panel.feature_names != features:
                raise ValueError(f"panel {split_name!r} feature_names must match dataset features")
            if panel.label_names != labels:
                raise ValueError(f"panel {split_name!r} label_names must match dataset labels")
            time_range = self.splits[split_name]
            if any(not time_range.contains(ts) for ts in panel.timestamps):
                raise ValueError(f"panel {split_name!r} contains timestamps outside its TimeRange")

        object.__setattr__(self, "features", features)
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "splits", freeze_mapping(self.splits))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))
        object.__setattr__(self, "panels", MappingProxyType(panels))

    def get_split(self, name: str) -> ResearchSplit:
        try:
            return self.panels[name]
        except KeyError as exc:
            if name not in self.splits:
                raise KeyError(f"unknown split {name!r}") from exc
            raise RuntimeError(
                f"split {name!r} has no numerical panel materialized by the DataAdapter"
            ) from exc

    @property
    def is_materialized(self) -> bool:
        return bool(self.panels) and set(self.panels) == set(self.splits)

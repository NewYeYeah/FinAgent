from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from ._validation import freeze_mapping, require_aware_datetime, require_non_empty
from .assets import AssetId
from .experiments import ArtifactRef, ArtifactType


@dataclass(frozen=True, slots=True)
class TimeRange:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        start = require_aware_datetime(self.start, "start")
        end = require_aware_datetime(self.end, "end")
        if end <= start:
            raise ValueError("TimeRange.end must be later than start")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)


@dataclass(frozen=True, slots=True)
class ResearchDataset:
    """Schema-level reference to a reproducible point-in-time research dataset.

    Phase 0.5 intentionally does not carry a pandas object across module boundaries.
    Data adapters may materialize tables internally, but other modules receive this
    typed contract plus an immutable artifact reference.
    """

    artifact: ArtifactRef
    universe: tuple[AssetId, ...]
    features: tuple[str, ...]
    labels: tuple[str, ...]
    splits: Mapping[str, TimeRange]
    point_in_time: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)

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
        for name in self.features:
            require_non_empty(name, "feature name")
        for name in self.labels:
            require_non_empty(name, "label name")
        if not self.splits:
            raise ValueError("splits cannot be empty")
        for split_name, split_range in self.splits.items():
            require_non_empty(split_name, "split name")
            if not isinstance(split_range, TimeRange):
                raise TypeError("split values must be TimeRange instances")
        object.__setattr__(self, "splits", freeze_mapping(self.splits))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))

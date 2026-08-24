from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping

from ._validation import freeze_mapping, require_aware_datetime, require_non_empty
from .assets import AssetId


class ArtifactType(str, Enum):
    DATASET = "dataset"
    FACTOR = "factor"
    MODEL = "model"
    CODE = "code"
    REPORT = "report"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    artifact_id: str
    artifact_type: ArtifactType
    version: str
    digest: str
    uri: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", require_non_empty(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "version", require_non_empty(self.version, "version"))
        object.__setattr__(self, "digest", require_non_empty(self.digest, "digest").lower())
        object.__setattr__(self, "uri", self.uri.strip())


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    """Immutable definition of one research experiment.

    The fingerprint deliberately includes data, code, universe, parameters and seed
    so results are not identified only by a factor expression or display name.
    """

    experiment_id: str
    hypothesis: str
    dataset: ArtifactRef
    code: ArtifactRef
    universe: tuple[AssetId, ...]
    parameters: Mapping[str, str | int | float | bool]
    seed: int
    parent_artifacts: tuple[ArtifactRef, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "experiment_id", require_non_empty(self.experiment_id, "experiment_id"))
        object.__setattr__(self, "hypothesis", require_non_empty(self.hypothesis, "hypothesis"))
        if not self.universe:
            raise ValueError("universe cannot be empty")
        if len(set(self.universe)) != len(self.universe):
            raise ValueError("universe cannot contain duplicate assets")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TypeError("seed must be an int, not bool")
        object.__setattr__(self, "parameters", freeze_mapping(self.parameters))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))

    @property
    def fingerprint(self) -> str:
        payload = {
            "experiment_id": self.experiment_id,
            "hypothesis": self.hypothesis,
            "dataset": {
                "id": self.dataset.artifact_id,
                "version": self.dataset.version,
                "digest": self.dataset.digest,
            },
            "code": {
                "id": self.code.artifact_id,
                "version": self.code.version,
                "digest": self.code.digest,
            },
            "universe": sorted(asset.key for asset in self.universe),
            "parameters": sorted((str(k), repr(v)) for k, v in self.parameters.items()),
            "seed": self.seed,
            "parents": sorted(
                (ref.artifact_id, ref.version, ref.digest) for ref in self.parent_artifacts
            ),
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class ExperimentRunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ExperimentRun:
    run_id: str
    spec_fingerprint: str
    status: ExperimentRunStatus
    started_at: datetime
    finished_at: datetime | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    stdout_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", require_non_empty(self.run_id, "run_id"))
        object.__setattr__(
            self,
            "spec_fingerprint",
            require_non_empty(self.spec_fingerprint, "spec_fingerprint"),
        )
        started_at = require_aware_datetime(self.started_at, "started_at")
        finished_at = self.finished_at
        if finished_at is not None:
            finished_at = require_aware_datetime(finished_at, "finished_at")
            if finished_at < started_at:
                raise ValueError("finished_at cannot be earlier than started_at")
        if self.status in {ExperimentRunStatus.SUCCEEDED, ExperimentRunStatus.FAILED} and finished_at is None:
            raise ValueError("terminal experiment runs require finished_at")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "finished_at", finished_at)
        object.__setattr__(self, "environment", freeze_mapping(self.environment))
        object.__setattr__(self, "stdout_digest", self.stdout_digest.strip().lower())


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    run_id: str
    metrics: Mapping[str, float]
    passed: bool
    produced_artifacts: tuple[ArtifactRef, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        from ._validation import require_finite

        object.__setattr__(self, "run_id", require_non_empty(self.run_id, "run_id"))
        metrics = {name: require_finite(value, f"metrics[{name}]") for name, value in self.metrics.items()}
        object.__setattr__(self, "metrics", freeze_mapping(metrics))
        object.__setattr__(self, "notes", self.notes.strip())

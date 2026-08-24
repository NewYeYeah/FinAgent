from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping

from ._validation import freeze_mapping, require_aware_datetime, require_finite, require_non_empty
from .experiments import ArtifactRef, ArtifactType


class ModelStage(str, Enum):
    """Governance stage for a model artifact.

    Stage changes are explicit registry events.  The LLM/agent layer may request a
    transition later, but it never bypasses this deterministic lifecycle.
    """

    CANDIDATE = "candidate"
    VALIDATED = "validated"
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"
    RETIRED = "retired"


_ALLOWED_TRANSITIONS: dict[ModelStage, frozenset[ModelStage]] = {
    ModelStage.CANDIDATE: frozenset({ModelStage.VALIDATED, ModelStage.RETIRED}),
    ModelStage.VALIDATED: frozenset({ModelStage.PAPER, ModelStage.RETIRED}),
    ModelStage.PAPER: frozenset({ModelStage.SHADOW, ModelStage.RETIRED}),
    ModelStage.SHADOW: frozenset({ModelStage.LIVE, ModelStage.RETIRED}),
    ModelStage.LIVE: frozenset({ModelStage.RETIRED}),
    ModelStage.RETIRED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class RegisteredModel:
    model_id: str
    family: str
    artifact: ArtifactRef
    stage: ModelStage
    created_at: datetime
    metrics: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.artifact.artifact_type is not ArtifactType.MODEL:
            raise ValueError("registered model artifact must have artifact_type=MODEL")
        object.__setattr__(self, "model_id", require_non_empty(self.model_id, "model_id"))
        object.__setattr__(self, "family", require_non_empty(self.family, "family"))
        object.__setattr__(self, "created_at", require_aware_datetime(self.created_at, "created_at"))
        metrics = {
            require_non_empty(str(name), "metric name"): require_finite(value, f"metrics[{name}]")
            for name, value in self.metrics.items()
        }
        object.__setattr__(self, "metrics", freeze_mapping(metrics))
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class ModelStageEvent:
    model_id: str
    from_stage: ModelStage
    to_stage: ModelStage
    changed_at: datetime
    reason: str
    actor: str = "system"

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_id", require_non_empty(self.model_id, "model_id"))
        if self.to_stage not in _ALLOWED_TRANSITIONS[self.from_stage]:
            raise ValueError(
                f"illegal model stage transition: {self.from_stage.value} -> {self.to_stage.value}"
            )
        object.__setattr__(self, "changed_at", require_aware_datetime(self.changed_at, "changed_at"))
        object.__setattr__(self, "reason", require_non_empty(self.reason, "reason"))
        object.__setattr__(self, "actor", require_non_empty(self.actor, "actor"))


def validate_model_transition(from_stage: ModelStage, to_stage: ModelStage) -> None:
    if to_stage not in _ALLOWED_TRANSITIONS[from_stage]:
        raise ValueError(f"illegal model stage transition: {from_stage.value} -> {to_stage.value}")

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping

from ._validation import freeze_mapping, require_aware_datetime, require_non_empty, require_finite


class ExperimentFamilyStatus(str, Enum):
    OPEN = "open"
    FROZEN = "frozen"
    CLOSED = "closed"


class CorrectionMethod(str, Enum):
    BONFERRONI = "bonferroni"
    HOLM = "holm"
    BENJAMINI_HOCHBERG = "benjamini_hochberg"


@dataclass(frozen=True, slots=True)
class ExperimentFamily:
    """Pre-registered collection of related research trials.

    Families exist to make the multiplicity denominator explicit before outcomes are
    inspected.  New experiments may only be attached while the family is OPEN.
    Statistical evaluation should happen only after the family has been FROZEN.
    """

    family_id: str
    research_question: str
    primary_metric: str
    created_at: datetime
    alpha: float = 0.05
    correction_method: CorrectionMethod = CorrectionMethod.HOLM
    status: ExperimentFamilyStatus = ExperimentFamilyStatus.OPEN
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "family_id", require_non_empty(self.family_id, "family_id"))
        object.__setattr__(
            self,
            "research_question",
            require_non_empty(self.research_question, "research_question"),
        )
        object.__setattr__(
            self,
            "primary_metric",
            require_non_empty(self.primary_metric, "primary_metric"),
        )
        object.__setattr__(self, "created_at", require_aware_datetime(self.created_at, "created_at"))
        alpha = require_finite(self.alpha, "alpha")
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be strictly between 0 and 1")
        object.__setattr__(self, "alpha", alpha)
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class FamilyMembership:
    family_id: str
    experiment_id: str
    added_at: datetime
    role: str = "variant"

    def __post_init__(self) -> None:
        object.__setattr__(self, "family_id", require_non_empty(self.family_id, "family_id"))
        object.__setattr__(
            self,
            "experiment_id",
            require_non_empty(self.experiment_id, "experiment_id"),
        )
        object.__setattr__(self, "added_at", require_aware_datetime(self.added_at, "added_at"))
        object.__setattr__(self, "role", require_non_empty(self.role, "role"))


def validate_family_transition(
    from_status: ExperimentFamilyStatus,
    to_status: ExperimentFamilyStatus,
) -> None:
    allowed = {
        ExperimentFamilyStatus.OPEN: {ExperimentFamilyStatus.FROZEN},
        ExperimentFamilyStatus.FROZEN: {ExperimentFamilyStatus.CLOSED},
        ExperimentFamilyStatus.CLOSED: set(),
    }
    if to_status not in allowed[from_status]:
        raise ValueError(
            f"invalid experiment-family transition: {from_status.value} -> {to_status.value}"
        )

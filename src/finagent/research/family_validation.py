from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from finagent.domain.experiment_family import ExperimentFamilyStatus
from finagent.research.registry import SQLiteResearchRegistry
from finagent.research.validation import FamilyValidationReport, validate_experiment_family


@dataclass(frozen=True, slots=True)
class RegisteredFamilyValidation:
    family_id: str
    experiment_order: tuple[str, ...]
    selected_experiment_id: str
    report: FamilyValidationReport


class ExperimentFamilyValidator:
    """Bind anti-overfitting statistics to the pre-registered family denominator."""

    def __init__(self, registry: SQLiteResearchRegistry) -> None:
        self.registry = registry

    def validate(
        self,
        family_id: str,
        *,
        trial_returns: Mapping[str, Sequence[float]],
        pvalues: Mapping[str, float],
        selected_experiment_id: str,
        dsr_probability_threshold: float = 0.95,
        pbo_threshold: float = 0.5,
        pbo_blocks: int = 8,
        bootstrap_samples: int = 1000,
        bootstrap_block_size: int | None = None,
        seed: int = 0,
    ) -> RegisteredFamilyValidation:
        family = self.registry.get_family(family_id)
        if family.status is not ExperimentFamilyStatus.FROZEN:
            raise ValueError("experiment family must be FROZEN before statistical validation")
        members = self.registry.family_members(family_id)
        experiment_order = tuple(member.experiment_id for member in members)
        if not experiment_order:
            raise ValueError("experiment family has no registered members")
        expected = set(experiment_order)
        if set(trial_returns) != expected or set(pvalues) != expected:
            raise ValueError(
                "trial_returns and pvalues must contain exactly the pre-registered family members"
            )
        if selected_experiment_id not in expected:
            raise ValueError("selected_experiment_id is not a member of the family")

        lengths = {len(trial_returns[experiment_id]) for experiment_id in experiment_order}
        if len(lengths) != 1:
            raise ValueError("all family return series must have the same number of observations")
        matrix = np.column_stack(
            [
                np.asarray(trial_returns[experiment_id], dtype=float)
                for experiment_id in experiment_order
            ]
        )
        ordered_pvalues = tuple(
            float(pvalues[experiment_id]) for experiment_id in experiment_order
        )
        selected_index = experiment_order.index(selected_experiment_id)
        report = validate_experiment_family(
            matrix,
            ordered_pvalues,
            selected_index=selected_index,
            correction_method=family.correction_method,
            alpha=family.alpha,
            dsr_probability_threshold=dsr_probability_threshold,
            pbo_threshold=pbo_threshold,
            pbo_blocks=pbo_blocks,
            bootstrap_samples=bootstrap_samples,
            bootstrap_block_size=bootstrap_block_size,
            seed=seed,
        )
        return RegisteredFamilyValidation(
            family_id=family_id,
            experiment_order=experiment_order,
            selected_experiment_id=selected_experiment_id,
            report=report,
        )

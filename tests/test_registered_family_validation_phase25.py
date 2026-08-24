from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiment_family import ExperimentFamily, ExperimentFamilyStatus
from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentSpec
from finagent.research import ExperimentFamilyValidator, SQLiteResearchRegistry

UTC = timezone.utc


def _spec(experiment_id: str, order: int) -> ExperimentSpec:
    asset = AssetId("AAA", AssetType.EQUITY, venue="XNAS", currency="USD")
    return ExperimentSpec(
        experiment_id=experiment_id,
        hypothesis=f"AR({order})",
        dataset=ArtifactRef("dataset", ArtifactType.DATASET, "1", "a" * 64),
        code=ArtifactRef(f"code-{order}", ArtifactType.CODE, "1", f"{order}" * 64),
        universe=(asset,),
        parameters={"order": order},
        seed=order,
    )


def test_registered_family_validator_requires_frozen_complete_denominator(tmp_path) -> None:
    registry = SQLiteResearchRegistry(tmp_path / "registry.db")
    family = ExperimentFamily(
        family_id="ar-orders",
        research_question="Which AR order is robust?",
        primary_metric="sharpe",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    registry.register_family(family)
    for order in (1, 2, 3):
        spec = _spec(f"ar-{order}", order)
        registry.register_experiment(spec)
        registry.add_experiment_to_family(
            family.family_id,
            spec.experiment_id,
            added_at=datetime(2026, 1, 2, tzinfo=UTC),
        )

    validator = ExperimentFamilyValidator(registry)
    rng = np.random.default_rng(8)
    trial_returns = {
        "ar-1": rng.normal(0.004, 0.008, 240),
        "ar-2": rng.normal(0.0, 0.01, 240),
        "ar-3": rng.normal(-0.001, 0.01, 240),
    }
    pvalues = {"ar-1": 0.001, "ar-2": 0.4, "ar-3": 0.8}

    with pytest.raises(ValueError, match="FROZEN"):
        validator.validate(
            family.family_id,
            trial_returns=trial_returns,
            pvalues=pvalues,
            selected_experiment_id="ar-1",
            bootstrap_samples=99,
        )

    registry.transition_family(family.family_id, ExperimentFamilyStatus.FROZEN)
    with pytest.raises(ValueError, match="exactly"):
        validator.validate(
            family.family_id,
            trial_returns={"ar-1": trial_returns["ar-1"]},
            pvalues={"ar-1": 0.001},
            selected_experiment_id="ar-1",
            bootstrap_samples=99,
        )

    result = validator.validate(
        family.family_id,
        trial_returns=trial_returns,
        pvalues=pvalues,
        selected_experiment_id="ar-1",
        bootstrap_samples=99,
        seed=9,
    )
    assert result.experiment_order == ("ar-1", "ar-2", "ar-3")
    assert result.selected_experiment_id == "ar-1"
    assert result.report.multiple_testing.rejected[0]

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiment_family import (
    CorrectionMethod,
    ExperimentFamily,
    ExperimentFamilyStatus,
)
from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentSpec
from finagent.research.registry import SQLiteResearchRegistry

UTC = timezone.utc


def _make_spec() -> ExperimentSpec:
    asset = AssetId("AAA", AssetType.EQUITY, venue="XNAS", currency="USD")
    return ExperimentSpec(
        experiment_id="exp-family-1",
        hypothesis="AR order improves next-return prediction",
        dataset=ArtifactRef("dataset", ArtifactType.DATASET, "1", "a" * 64),
        code=ArtifactRef("code", ArtifactType.CODE, "1", "b" * 64),
        universe=(asset,),
        parameters={"order": 1},
        seed=42,
    )


def test_experiment_family_must_be_frozen_before_no_more_trials_can_be_added(tmp_path) -> None:
    registry = SQLiteResearchRegistry(tmp_path / "research.db")
    spec = _make_spec()
    registry.register_experiment(spec)
    family = ExperimentFamily(
        family_id="ar-grid-001",
        research_question="Does AR order improve next-return prediction?",
        primary_metric="sharpe",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        correction_method=CorrectionMethod.HOLM,
    )
    registry.register_family(family)
    membership = registry.add_experiment_to_family(
        family.family_id,
        spec.experiment_id,
        added_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert membership.experiment_id == spec.experiment_id
    assert len(registry.family_members(family.family_id)) == 1

    frozen = registry.transition_family(family.family_id, ExperimentFamilyStatus.FROZEN)
    assert frozen.status is ExperimentFamilyStatus.FROZEN
    with pytest.raises(ValueError, match="OPEN"):
        registry.add_experiment_to_family(
            family.family_id,
            spec.experiment_id,
            added_at=datetime(2026, 1, 3, tzinfo=UTC),
        )
    closed = registry.transition_family(family.family_id, ExperimentFamilyStatus.CLOSED)
    assert closed.status is ExperimentFamilyStatus.CLOSED


def test_empty_family_cannot_be_frozen(tmp_path) -> None:
    registry = SQLiteResearchRegistry(tmp_path / "research.db")
    registry.register_family(
        ExperimentFamily(
            family_id="empty",
            research_question="pre-registered question",
            primary_metric="sharpe",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    with pytest.raises(ValueError, match="empty"):
        registry.transition_family("empty", ExperimentFamilyStatus.FROZEN)


def test_reregistering_experiment_or_family_preserves_membership(tmp_path) -> None:
    registry = SQLiteResearchRegistry(tmp_path / "research.db")
    spec = _make_spec()
    family = ExperimentFamily(
        family_id="stable-family",
        research_question="Does this remain registered?",
        primary_metric="sharpe",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    registry.register_experiment(spec)
    registry.register_family(family)
    registry.add_experiment_to_family(
        family.family_id,
        spec.experiment_id,
        added_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    registry.register_experiment(spec)
    registry.register_family(family)
    assert tuple(member.experiment_id for member in registry.family_members(family.family_id)) == (
        spec.experiment_id,
    )

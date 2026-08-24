import pytest

from finagent.domain.experiments import ArtifactRef, ArtifactType
from finagent.domain.model_registry import ModelStage, RegisteredModel
from finagent.research import SQLiteResearchRegistry


def test_model_registry_enforces_governed_stage_transitions(tmp_path, now):
    registry = SQLiteResearchRegistry(tmp_path / "registry.db")
    artifact = ArtifactRef("model:ar:1", ArtifactType.MODEL, "phase2", "c" * 64)
    model = RegisteredModel(
        model_id="ar-production-candidate",
        family="AR",
        artifact=artifact,
        stage=ModelStage.CANDIDATE,
        created_at=now,
        metrics={"sharpe": 0.8},
    )
    registry.register_model(model)
    validated = registry.promote_model(
        model.model_id,
        ModelStage.VALIDATED,
        changed_at=now,
        reason="walk-forward gates passed",
        actor="research-policy",
    )
    paper = registry.promote_model(
        model.model_id,
        ModelStage.PAPER,
        changed_at=now,
        reason="approved for paper trading",
        actor="human",
    )
    assert validated.stage is ModelStage.VALIDATED
    assert paper.stage is ModelStage.PAPER
    history = registry.model_history(model.model_id)
    assert [event.to_stage for event in history] == [ModelStage.VALIDATED, ModelStage.PAPER]


def test_model_registry_rejects_stage_jump_and_direct_rewrite(tmp_path, now):
    registry = SQLiteResearchRegistry(tmp_path / "registry.db")
    artifact = ArtifactRef("model:risk:1", ArtifactType.MODEL, "phase2", "d" * 64)
    model = RegisteredModel("risk-1", "GARCH", artifact, ModelStage.CANDIDATE, now)
    registry.register_model(model)
    with pytest.raises(ValueError, match="illegal model stage transition"):
        registry.promote_model(
            "risk-1", ModelStage.LIVE, changed_at=now, reason="skip controls"
        )
    with pytest.raises(ValueError, match="promote_model"):
        registry.register_model(
            RegisteredModel("risk-1", "GARCH", artifact, ModelStage.VALIDATED, now)
        )
    assert registry.get_model("risk-1").stage is ModelStage.CANDIDATE

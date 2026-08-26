from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from finagent.domain.assets import AssetId
from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentResult, ExperimentSpec
from finagent.memory import (
    AgentResearchMemoryView,
    EvidenceVisibility,
    FailureCategory,
    FailureStage,
    ResearchMemoryService,
    SQLiteMemoryVisibilityStore,
    SQLiteResearchMemoryStore,
    SQLiteScopedEvidenceWriter,
)


NOW = datetime(2026, 8, 26, 4, 30, tzinfo=timezone.utc)


def _memory(tmp_path):
    path = tmp_path / "memory.sqlite"
    store = SQLiteResearchMemoryStore(path)
    visibility = SQLiteMemoryVisibilityStore(path)
    memory = ResearchMemoryService(store)
    writer = SQLiteScopedEvidenceWriter(store, visibility)
    return store, visibility, memory, writer


def _spec(experiment_id: str = "exp-holdout") -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=experiment_id,
        hypothesis="frozen strategy survives sealed holdout",
        dataset=ArtifactRef("dataset", ArtifactType.DATASET, "v1", "d" * 64),
        code=ArtifactRef("code", ArtifactType.CODE, "v1", "c" * 64),
        universe=(AssetId("AAA"), AssetId("BBB")),
        parameters={"order": 1},
        seed=7,
    )


def _seed_experiment(memory: ResearchMemoryService, experiment_id: str = "exp-holdout") -> None:
    memory.create_hypothesis(
        "hyp-holdout",
        "frozen strategy survives sealed holdout",
        "final OOS evidence must never become adaptive Agent memory",
        NOW,
    )
    memory.register_experiment(
        "hyp-holdout",
        _spec(experiment_id),
        NOW + timedelta(seconds=1),
    )


def test_sealed_result_and_visibility_commit_together(tmp_path) -> None:
    store, visibility, memory, writer = _memory(tmp_path)
    _seed_experiment(memory)
    result = ExperimentResult(
        "run-sealed",
        {"net_sharpe": 1.15, "net_return": 0.08},
        True,
        notes="one-shot holdout result",
    )
    written = writer.register_result(
        "exp-holdout",
        result,
        NOW + timedelta(seconds=2),
        visibility=EvidenceVisibility.SEALED_HOLDOUT,
        program_id="program-1",
    )

    assert store.get_node("result:run-sealed") == written.node
    assert visibility.get("result:run-sealed") == written.scope
    assert written.scope.visibility is EvidenceVisibility.SEALED_HOLDOUT

    view = AgentResearchMemoryView(memory, visibility, program_id="program-1")
    summary = view.summary("hyp-holdout")
    assert summary.node_counts.get("result", 0) == 0
    assert summary.truncated is True


def test_scoped_result_write_rolls_back_when_lineage_is_invalid(tmp_path) -> None:
    store, visibility, _, writer = _memory(tmp_path)
    result = ExperimentResult("run-rollback", {"net_return": -0.01}, False)

    with pytest.raises(KeyError, match="lineage endpoint"):
        writer.register_result(
            "missing-experiment",
            result,
            NOW,
            visibility=EvidenceVisibility.SEALED_HOLDOUT,
            program_id="program-1",
        )

    assert store.node_exists("result:run-rollback") is False
    assert visibility.get("result:run-rollback") is None


def test_sensitive_scope_cannot_be_added_after_raw_result_was_exposed(tmp_path) -> None:
    store, visibility, memory, writer = _memory(tmp_path)
    _seed_experiment(memory)
    result = ExperimentResult("run-legacy", {"net_return": 0.02}, True)
    created_at = NOW + timedelta(seconds=2)
    memory.register_result("exp-holdout", result, created_at)

    with pytest.raises(ValueError, match="retroactive classification"):
        writer.register_result(
            "exp-holdout",
            result,
            created_at,
            visibility=EvidenceVisibility.SEALED_HOLDOUT,
            program_id="program-1",
        )

    assert store.node_exists("result:run-legacy") is True
    assert visibility.get("result:run-legacy") is None


def test_scoped_result_write_is_idempotent_but_scope_is_immutable(tmp_path) -> None:
    _, visibility, memory, writer = _memory(tmp_path)
    _seed_experiment(memory)
    result = ExperimentResult("run-idempotent", {"net_return": 0.03}, True)
    created_at = NOW + timedelta(seconds=2)

    first = writer.register_result(
        "exp-holdout",
        result,
        created_at,
        visibility=EvidenceVisibility.SEALED_HOLDOUT,
        program_id="program-1",
    )
    second = writer.register_result(
        "exp-holdout",
        result,
        created_at,
        visibility=EvidenceVisibility.SEALED_HOLDOUT,
        program_id="program-1",
    )
    assert second == first

    with pytest.raises(ValueError, match="visibility.*immutable"):
        writer.register_result(
            "exp-holdout",
            result,
            created_at,
            visibility=EvidenceVisibility.VALIDATION,
            program_id="program-1",
        )
    assert visibility.get("result:run-idempotent") == first.scope


def test_scoped_failure_row_node_lineage_and_scope_are_atomic(tmp_path) -> None:
    store, visibility, memory, writer = _memory(tmp_path)
    _seed_experiment(memory)

    failure, written = writer.record_failure(
        failure_id="failure-holdout",
        category=FailureCategory.STATISTICAL,
        stage=FailureStage.VALIDATION,
        summary="sealed holdout failed the deterministic promotion threshold",
        observed_at=NOW + timedelta(seconds=3),
        visibility=EvidenceVisibility.SEALED_HOLDOUT,
        program_id="program-1",
        hypothesis_id="hyp-holdout",
        experiment_id="exp-holdout",
        related_node_keys=("experiment:exp-holdout",),
    )

    assert store.failures(experiment_id="exp-holdout") == (failure,)
    assert store.get_node("failure:failure-holdout") == written.node
    assert visibility.get("failure:failure-holdout") == written.scope

    view = AgentResearchMemoryView(memory, visibility, program_id="program-1")
    assert view.failures(experiment_id="exp-holdout") == ()


def test_scoped_failure_write_rolls_back_on_missing_related_node(tmp_path) -> None:
    store, visibility, _, writer = _memory(tmp_path)

    with pytest.raises(KeyError, match="failure related node"):
        writer.record_failure(
            failure_id="failure-rollback",
            category=FailureCategory.DATA,
            stage=FailureStage.VALIDATION,
            summary="holdout dataset identity mismatch",
            observed_at=NOW,
            visibility=EvidenceVisibility.SEALED_HOLDOUT,
            program_id="program-1",
            related_node_keys=("experiment:missing",),
        )

    assert store.failures() == ()
    assert store.node_exists("failure:failure-rollback") is False
    assert visibility.get("failure:failure-rollback") is None


def test_scoped_writer_rejects_different_sqlite_databases(tmp_path) -> None:
    memory_store = SQLiteResearchMemoryStore(tmp_path / "memory-a.sqlite")
    visibility_store = SQLiteMemoryVisibilityStore(tmp_path / "memory-b.sqlite")

    with pytest.raises(ValueError, match="same SQLite database"):
        SQLiteScopedEvidenceWriter(memory_store, visibility_store)

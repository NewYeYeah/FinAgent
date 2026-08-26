from __future__ import annotations

from dataclasses import dataclass

import pytest

from finagent.research import (
    ResearchProgram,
    ResearchProgramStatus,
    SQLiteResearchProgramStore,
)


@dataclass(frozen=True)
class _Plan:
    program_id: str
    family_id: str
    alpha: float = 0.01
    variants: tuple[object, ...] = ("candidate-a",)

    def fingerprint(self, task_id: str) -> str:
        return f"{task_id}:{self.program_id}:{self.family_id}:{self.variants!r}:{self.alpha}"


def _store(tmp_path, *, holdout: str = "sealed-oos") -> SQLiteResearchProgramStore:
    store = SQLiteResearchProgramStore(tmp_path / "programs.sqlite")
    store.register(
        ResearchProgram(
            program_id="program-122",
            alpha_budget=0.05,
            max_families=4,
            max_experiments=8,
            sealed_holdout_id=holdout,
        )
    )
    return store


def test_holdout_requires_frozen_program_and_close_requires_holdout_consumption(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(PermissionError, match="requires a frozen research program"):
        store.consume_sealed_holdout("program-122", actor="reviewer")

    frozen = store.freeze_program("program-122", actor="research-lead")
    assert frozen.from_status is ResearchProgramStatus.OPEN
    assert frozen.to_status is ResearchProgramStatus.FROZEN
    assert store.get("program-122").status is ResearchProgramStatus.FROZEN

    with pytest.raises(PermissionError, match="cannot close before its sealed holdout"):
        store.close_program("program-122", actor="research-lead")

    access = store.consume_sealed_holdout("program-122", actor="reviewer")
    assert access["holdout_id"] == "sealed-oos"

    closed = store.close_program("program-122", actor="research-lead")
    assert closed.from_status is ResearchProgramStatus.FROZEN
    assert closed.to_status is ResearchProgramStatus.CLOSED
    assert store.get("program-122").status is ResearchProgramStatus.CLOSED


def test_freeze_blocks_new_search_but_preserves_exact_reserved_plan_replay(tmp_path):
    store = _store(tmp_path)
    reserved = _Plan("program-122", "family-existing")
    first = store.reserve_plan(reserved, task_id="task-existing")

    store.freeze_program("program-122", actor="research-lead")

    replay = store.reserve_plan(reserved, task_id="task-existing")
    assert replay == first

    with pytest.raises(PermissionError, match="new research reservations require an open program"):
        store.reserve_plan(
            _Plan("program-122", "family-new"),
            task_id="task-new",
        )

    with pytest.raises(ValueError, match="already reserved by a different plan"):
        store.reserve_plan(
            _Plan("program-122", "family-existing", variants=("candidate-b",)),
            task_id="task-existing",
        )


def test_lifecycle_transitions_are_append_only_and_idempotent(tmp_path):
    store = _store(tmp_path)

    first_freeze = store.freeze_program("program-122", actor="lead", reason="freeze search")
    second_freeze = store.freeze_program("program-122", actor="different-actor")
    assert second_freeze == first_freeze
    assert len(store.lifecycle_events("program-122")) == 1

    store.consume_sealed_holdout("program-122", actor="reviewer")
    first_close = store.close_program("program-122", actor="lead", reason="final decision")
    second_close = store.close_program("program-122", actor="different-actor")
    assert second_close == first_close

    events = store.lifecycle_events("program-122")
    assert [event.to_status for event in events] == [
        ResearchProgramStatus.FROZEN,
        ResearchProgramStatus.CLOSED,
    ]
    snapshot = store.lifecycle_snapshot("program-122")
    assert snapshot.status is ResearchProgramStatus.CLOSED
    assert snapshot.holdout_consumed
    assert snapshot.frozen_at == first_freeze.occurred_at
    assert snapshot.closed_at == first_close.occurred_at


def test_program_without_holdout_can_close_after_freeze(tmp_path):
    store = _store(tmp_path, holdout="")
    store.freeze_program("program-122", actor="lead")
    closed = store.close_program("program-122", actor="lead")
    assert closed.to_status is ResearchProgramStatus.CLOSED
    assert not store.lifecycle_snapshot("program-122").holdout_consumed


def test_closed_program_cannot_consume_holdout_or_open_new_search(tmp_path):
    store = _store(tmp_path)
    store.freeze_program("program-122", actor="lead")
    store.consume_sealed_holdout("program-122", actor="reviewer")
    store.close_program("program-122", actor="lead")

    with pytest.raises(PermissionError, match="requires a frozen research program"):
        store.consume_sealed_holdout("program-122", actor="reviewer-2")

    with pytest.raises(PermissionError, match="new research reservations require an open program"):
        store.reserve_plan(_Plan("program-122", "family-late"), task_id="late")

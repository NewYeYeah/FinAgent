from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
import threading

import pytest

from finagent.research.ashare_reserve import SQLiteReserveEligibilityStore
from finagent.research.ashare_reserve_lifecycle import (
    RESERVE_CONSUMPTION_PROTOCOL_ID,
    ReserveConsumptionClaim,
    ReserveConsumptionState,
    SQLiteReserveConsumptionStore,
)
from finagent.research.ashare_reserve_runner import (
    AshareReserveOneShotRunner,
    ReserveAccessState,
    ReserveAlreadyConsumedError,
    ReserveTerminalEvidence,
    ReserveTerminalStatus,
    SQLiteReserveTerminalEvidenceStore,
)

from tests.test_ashare_reserve_runner_a5 import FakeEngine, StepClock, _runner


NOW = datetime(2026, 8, 29, 3, 59, tzinfo=UTC)


def _claim_for(seal, *, actor: str, claimed_at: datetime, execution_id: str | None = None):
    return ReserveConsumptionClaim(
        execution_id=execution_id or AshareReserveOneShotRunner.execution_id(seal),
        seal_id=seal.seal_id,
        reserve_id=seal.reserve_id,
        program_result_id=seal.program_result_id,
        portfolio_validation_id=seal.portfolio_validation_id,
        protocol_digest=seal.protocol_digest,
        runtime_code_git_sha="a5-runtime-sha",
        authorized_by=actor,
        claimed_at=claimed_at,
    )


class ClaimCheckingEngine(FakeEngine):
    def __init__(self) -> None:
        super().__init__()
        self.store: SQLiteReserveConsumptionStore | None = None
        self.seal = None
        self.claim_seen_before_evaluate = False

    def evaluate(self, *, seal, a26_report, a4_report):
        assert self.store is not None
        claim = self.store.get_claim_for_seal(seal.seal_id)
        assert claim.state is ReserveConsumptionState.CONSUMED
        assert claim.claimed_at <= datetime.now(UTC)
        self.claim_seen_before_evaluate = True
        return super().evaluate(seal=seal, a26_report=a26_report, a4_report=a4_report)


def test_a5p3_claim_is_durable_before_first_reserve_evaluation(tmp_path: Path) -> None:
    engine = ClaimCheckingEngine()
    runner, _, seal, a26, a4 = _runner(tmp_path, engine)
    engine.store = runner.consumption_store
    engine.seal = seal

    result = runner.run(
        seal=seal,
        a26_report=a26,
        a4_report=a4,
        runtime_code_git_sha="a5-runtime-sha",
        actor="human-operator",
    )

    assert engine.claim_seen_before_evaluate is True
    claim = runner.consumption_store.get_claim_for_reserve(seal.reserve_id)
    assert result.terminal.consumption_claim_id == claim.claim_id
    assert result.terminal.consumed_at == claim.claimed_at
    assert result.terminal.reserve_access_state is ReserveAccessState.ACCESSED
    assert result.terminal.to_dict()["consumed_state_persistence"] == "DURABLE_PRE_ACCESS_V1"
    assert result.terminal.to_dict()["automatic_retry_allowed"] is False


def test_a5p3_concurrent_claim_has_exactly_one_acquirer(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir(parents=True)
    _, _, seal, _, _ = _runner(seed, FakeEngine())
    store = SQLiteReserveConsumptionStore(tmp_path / "consumption.sqlite")
    barrier = threading.Barrier(2)
    claims = (
        _claim_for(seal, actor="operator-a", claimed_at=NOW),
        _claim_for(seal, actor="operator-b", claimed_at=NOW + timedelta(seconds=1)),
    )

    def attempt(claim: ReserveConsumptionClaim):
        barrier.wait()
        return store.claim(claim)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, claims))

    assert sum(result.acquired for result in results) == 1
    persisted = store.get_claim_for_reserve(seal.reserve_id)
    assert persisted.claim_id == claims[0].claim_id == claims[1].claim_id
    assert persisted.state is ReserveConsumptionState.CONSUMED
    assert RESERVE_CONSUMPTION_PROTOCOL_ID == "a5-pre-access-consumed-claim-v1"


def test_a5p3_existing_consumed_claim_without_terminal_blocks_reaccess(tmp_path: Path) -> None:
    engine = FakeEngine()
    runner, _, seal, a26, a4 = _runner(tmp_path, engine)
    claim = _claim_for(seal, actor="human-operator", claimed_at=NOW)
    assert runner.consumption_store.claim(claim).acquired is True

    with pytest.raises(ReserveAlreadyConsumedError, match="explicit recovery"):
        runner.run(
            seal=seal,
            a26_report=a26,
            a4_report=a4,
            runtime_code_git_sha="a5-runtime-sha",
            actor="second-operator",
        )
    assert engine.evaluate_calls == 0


def test_a5p3_interrupted_claim_recovers_to_terminal_fail_without_reaccess(tmp_path: Path) -> None:
    engine = FakeEngine()
    runner, _, seal, _, _ = _runner(tmp_path, engine)
    claim = _claim_for(seal, actor="human-operator", claimed_at=NOW)
    runner.consumption_store.claim(claim)

    recovered = runner.recover_interrupted(seal_id=seal.seal_id, actor="recovery-operator")
    terminal = recovered.terminal
    assert terminal.status is ReserveTerminalStatus.FAIL
    assert terminal.error_type == "InterruptedReserveExecution"
    assert terminal.reserve_access_state is ReserveAccessState.UNKNOWN_AFTER_CONSUMED_CLAIM
    assert "RECOVERED_WITHOUT_RESERVE_REACCESS" in terminal.reason_codes
    assert engine.evaluate_calls == 0

    audit = runner.audit_lifecycle(seal=seal)
    assert audit.recovery_terminal is True
    assert audit.terminal_evidence_id == terminal.terminal_evidence_id
    assert audit.to_dict()["automatic_retry_allowed"] is False


def test_a5p3_terminal_without_audit_is_reconciled_without_second_evaluation(tmp_path: Path) -> None:
    engine = FakeEngine()
    runner, _, seal, a26, a4 = _runner(tmp_path, engine)
    first = runner.run(
        seal=seal,
        a26_report=a26,
        a4_report=a4,
        runtime_code_git_sha="a5-runtime-sha",
        actor="human-operator",
    )
    claim = runner.consumption_store.get_claim_for_seal(seal.seal_id)
    with sqlite3.connect(runner.consumption_store.path) as connection:
        connection.execute("DELETE FROM reserve_consumption_audits WHERE claim_id=?", (claim.claim_id,))

    second = runner.run(
        seal=seal,
        a26_report=a26,
        a4_report=a4,
        runtime_code_git_sha="a5-runtime-sha",
        actor="second-operator",
    )
    assert second.terminal.terminal_evidence_id == first.terminal.terminal_evidence_id
    assert second.ledger_bytes == first.ledger_bytes
    assert engine.evaluate_calls == 1
    assert runner.consumption_store.get_audit_for_claim(claim.claim_id).terminal_evidence_id == (
        first.terminal.terminal_evidence_id
    )


def test_a5p3_replay_audit_detects_durable_ledger_tampering(tmp_path: Path) -> None:
    runner, terminal_store, seal, a26, a4 = _runner(tmp_path, FakeEngine())
    result = runner.run(
        seal=seal,
        a26_report=a26,
        a4_report=a4,
        runtime_code_git_sha="a5-runtime-sha",
        actor="human-operator",
    )
    assert result.ledger_bytes is not None
    with sqlite3.connect(terminal_store.path) as connection:
        connection.execute(
            "UPDATE reserve_terminal_artifacts SET ledger_bytes=? WHERE terminal_evidence_id=?",
            (b'{}\n', result.terminal.terminal_evidence_id),
        )

    with pytest.raises(ValueError, match="failed SHA-256 verification"):
        runner.audit_lifecycle(seal=seal)


def test_a5p3_store_reopen_replays_same_claim_terminal_and_audit(tmp_path: Path) -> None:
    engine = FakeEngine()
    runner, terminal_store, seal, a26, a4 = _runner(tmp_path, engine)
    first = runner.run(
        seal=seal,
        a26_report=a26,
        a4_report=a4,
        runtime_code_git_sha="a5-runtime-sha",
        actor="human-operator",
    )

    reopened = AshareReserveOneShotRunner(
        eligibility_store=SQLiteReserveEligibilityStore(runner.eligibility_store.path),
        consumption_store=SQLiteReserveConsumptionStore(runner.consumption_store.path),
        terminal_store=SQLiteReserveTerminalEvidenceStore(terminal_store.path),
        engine=FakeEngine(),
        clock=StepClock(),
    )
    audit = reopened.audit_lifecycle(seal=seal)
    second = reopened.run(
        seal=seal,
        a26_report=a26,
        a4_report=a4,
        runtime_code_git_sha="a5-runtime-sha",
        actor="audit-operator",
    )
    assert audit.terminal_evidence_id == first.terminal.terminal_evidence_id
    assert second.terminal.terminal_evidence_id == first.terminal.terminal_evidence_id
    assert second.ledger_bytes == first.ledger_bytes
    assert reopened.engine.evaluate_calls == 0  # type: ignore[attr-defined]


def test_a5p3_terminal_v2_round_trip_binds_consumption_claim(tmp_path: Path) -> None:
    runner, _, seal, a26, a4 = _runner(tmp_path, FakeEngine())
    terminal = runner.run(
        seal=seal,
        a26_report=a26,
        a4_report=a4,
        runtime_code_git_sha="a5-runtime-sha",
        actor="human-operator",
    ).terminal
    payload = terminal.to_dict()
    parsed = ReserveTerminalEvidence.from_dict(payload)
    assert parsed.terminal_evidence_id == terminal.terminal_evidence_id
    assert parsed.consumption_claim_id == terminal.consumption_claim_id
    assert parsed.to_dict()["schema_version"] == "finagent.ashare-reserve-terminal-evidence.v2"


def test_a5p3_conflicting_second_claim_cannot_rebind_reserve(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir(parents=True)
    _, _, seal, _, _ = _runner(seed, FakeEngine())
    store = SQLiteReserveConsumptionStore(tmp_path / "consumption.sqlite")
    first = _claim_for(seal, actor="operator-a", claimed_at=NOW)
    store.claim(first)
    conflicting = replace(first, execution_id="different-execution")
    with pytest.raises(ValueError, match="different CONSUMED claim"):
        store.claim(conflicting)


class FailingConsumptionStore:
    def __init__(self) -> None:
        self.claim_calls = 0

    def get_claim_for_seal(self, seal_id: str):
        raise KeyError(seal_id)

    def claim(self, proposed):
        self.claim_calls += 1
        raise OSError("synthetic durable claim failure")


class FailingTerminalStore(SQLiteReserveTerminalEvidenceStore):
    def register(self, evidence, *, ledger_bytes=None) -> None:
        raise OSError("synthetic terminal persistence failure")


def test_a5p3_claim_persistence_failure_prevents_reserve_evaluation(tmp_path: Path) -> None:
    engine = FakeEngine()
    runner, terminal_store, seal, a26, a4 = _runner(tmp_path, engine)
    failing = FailingConsumptionStore()
    unsafe = AshareReserveOneShotRunner(
        eligibility_store=runner.eligibility_store,
        consumption_store=failing,  # type: ignore[arg-type]
        terminal_store=terminal_store,
        engine=engine,
        clock=StepClock(),
    )
    with pytest.raises(OSError, match="durable claim failure"):
        unsafe.run(
            seal=seal,
            a26_report=a26,
            a4_report=a4,
            runtime_code_git_sha="a5-runtime-sha",
            actor="human-operator",
        )
    assert failing.claim_calls == 1
    assert engine.evaluate_calls == 0


def test_a5p3_terminal_persistence_failure_leaves_consumed_and_blocks_retry(tmp_path: Path) -> None:
    engine = FakeEngine()
    runner, _, seal, a26, a4 = _runner(tmp_path, engine)
    failing_terminal = FailingTerminalStore(tmp_path / "failing-terminal.sqlite")
    unsafe = AshareReserveOneShotRunner(
        eligibility_store=runner.eligibility_store,
        consumption_store=runner.consumption_store,
        terminal_store=failing_terminal,
        engine=engine,
        clock=StepClock(),
    )
    with pytest.raises(OSError, match="terminal persistence failure"):
        unsafe.run(
            seal=seal,
            a26_report=a26,
            a4_report=a4,
            runtime_code_git_sha="a5-runtime-sha",
            actor="human-operator",
        )
    assert engine.evaluate_calls == 1
    claim = runner.consumption_store.get_claim_for_seal(seal.seal_id)
    assert claim.state is ReserveConsumptionState.CONSUMED

    healthy_terminal = SQLiteReserveTerminalEvidenceStore(tmp_path / "healthy-terminal.sqlite")
    restarted = AshareReserveOneShotRunner(
        eligibility_store=runner.eligibility_store,
        consumption_store=runner.consumption_store,
        terminal_store=healthy_terminal,
        engine=engine,
        clock=StepClock(),
    )
    with pytest.raises(ReserveAlreadyConsumedError, match="explicit recovery"):
        restarted.run(
            seal=seal,
            a26_report=a26,
            a4_report=a4,
            runtime_code_git_sha="a5-runtime-sha",
            actor="retry-operator",
        )
    assert engine.evaluate_calls == 1

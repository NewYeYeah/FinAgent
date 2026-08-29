from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

from finagent.domain._validation import require_aware_datetime, require_non_empty

from .ashare_reserve import ReserveEligibilitySeal, SQLiteReserveEligibilityStore

RESERVE_TERMINAL_SCHEMA = "finagent.ashare-reserve-terminal-evidence.v1"
RESERVE_EXECUTION_PROTOCOL_ID = "a5-one-shot-reserve-execution-v1"
FINAL_TRAINING_RULE_ID = "all-pre-reserve-half-open-v1"
TERMINAL_POLICY_RULE_ID = "reuse-frozen-a4-economic-policy-v1"


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        _thaw_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _identity(prefix: str, value: object, length: int = 24) -> str:
    return f"{prefix}-{_sha256_json(value)[:length]}"


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a JSON object")
    return value


def _sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a JSON array")
    return value


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(json.loads(_canonical_json(value)))


def reserve_execution_ledger_bytes(rows: Sequence[Mapping[str, object]]) -> bytes:
    """Serialize the terminal reserve ledger deterministically as canonical JSONL."""

    if not rows:
        raise ValueError("A5 reserve execution ledger cannot be empty")
    return ("\n".join(_canonical_json(dict(row)) for row in rows) + "\n").encode("utf-8")


def reserve_execution_ledger_digest(rows: Sequence[Mapping[str, object]]) -> str:
    return f"a5-reserve-execution-ledger-{_sha256_json([dict(row) for row in rows])}"


class ReserveTerminalStatus(str, Enum):
    PASS = "RESERVE_PASS"
    FAIL = "RESERVE_FAIL"


@dataclass(frozen=True, slots=True)
class ReservePortfolioEvaluation:
    """Deterministic engine output before A5 governance assigns terminal status."""

    engine_id: str
    reserve_dataset_digest: str
    fold: Mapping[str, object]
    aggregate: Mapping[str, object]
    policy: Mapping[str, object]
    failed_reason_codes: tuple[str, ...]
    ledger_rows: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "engine_id", require_non_empty(self.engine_id, "engine_id"))
        object.__setattr__(
            self,
            "reserve_dataset_digest",
            require_non_empty(self.reserve_dataset_digest, "reserve_dataset_digest"),
        )
        if not self.ledger_rows:
            raise ValueError("A5 reserve evaluation requires a non-empty execution ledger")
        object.__setattr__(self, "fold", _freeze_mapping(self.fold))
        object.__setattr__(self, "aggregate", _freeze_mapping(self.aggregate))
        object.__setattr__(self, "policy", _freeze_mapping(self.policy))
        normalized_failed = tuple(
            require_non_empty(str(code), "failed_reason_code")
            for code in self.failed_reason_codes
        )
        if len(set(normalized_failed)) != len(normalized_failed):
            raise ValueError("A5 failed policy reason codes must be unique")
        object.__setattr__(self, "failed_reason_codes", normalized_failed)
        object.__setattr__(
            self,
            "ledger_rows",
            tuple(_freeze_mapping(dict(row)) for row in self.ledger_rows),
        )

    @property
    def ledger_digest(self) -> str:
        return reserve_execution_ledger_digest(self.ledger_rows)

    @property
    def ledger_file_sha256(self) -> str:
        return _sha256_bytes(reserve_execution_ledger_bytes(self.ledger_rows))

    @property
    def fold_digest(self) -> str:
        return _sha256_json(dict(self.fold))

    @property
    def aggregate_digest(self) -> str:
        return _sha256_json(dict(self.aggregate))


class ReserveEvaluationEngine(Protocol):
    """A5 engine boundary: preflight is guaranteed not to access reserve observations."""

    def preflight(
        self,
        *,
        seal: ReserveEligibilitySeal,
        a26_report: Mapping[str, Any],
        a4_report: Mapping[str, Any],
    ) -> None: ...

    def evaluate(
        self,
        *,
        seal: ReserveEligibilitySeal,
        a26_report: Mapping[str, Any],
        a4_report: Mapping[str, Any],
    ) -> ReservePortfolioEvaluation: ...


@dataclass(frozen=True, slots=True)
class ReserveTerminalEvidence:
    execution_id: str
    seal_id: str
    reserve_id: str
    program_result_id: str
    portfolio_validation_id: str
    protocol_digest: str
    execution_protocol_id: str
    final_training_rule_id: str
    terminal_policy_rule_id: str
    runtime_code_git_sha: str
    authorized_by: str
    status: ReserveTerminalStatus
    reserve_dataset_digest: str
    reserve_ledger_digest: str
    reserve_ledger_file_sha256: str
    fold_digest: str
    aggregate_digest: str
    fold: Mapping[str, object] | None
    aggregate: Mapping[str, object] | None
    policy: Mapping[str, object]
    reason_codes: tuple[str, ...]
    engine_id: str
    started_at: datetime
    finished_at: datetime
    error_type: str = ""
    error_message: str = ""

    def __post_init__(self) -> None:
        for name in (
            "execution_id",
            "seal_id",
            "reserve_id",
            "program_result_id",
            "portfolio_validation_id",
            "protocol_digest",
            "execution_protocol_id",
            "final_training_rule_id",
            "terminal_policy_rule_id",
            "runtime_code_git_sha",
            "authorized_by",
            "reserve_dataset_digest",
            "reserve_ledger_digest",
            "reserve_ledger_file_sha256",
            "fold_digest",
            "aggregate_digest",
            "engine_id",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if self.execution_protocol_id != RESERVE_EXECUTION_PROTOCOL_ID:
            raise ValueError("terminal evidence uses an unknown A5 execution protocol")
        if self.final_training_rule_id != FINAL_TRAINING_RULE_ID:
            raise ValueError("terminal evidence uses an unknown final-training rule")
        if self.terminal_policy_rule_id != TERMINAL_POLICY_RULE_ID:
            raise ValueError("terminal evidence uses an unknown terminal policy rule")
        started_at = require_aware_datetime(self.started_at, "started_at")
        finished_at = require_aware_datetime(self.finished_at, "finished_at")
        if finished_at < started_at:
            raise ValueError("A5 terminal finished_at cannot precede started_at")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "finished_at", finished_at)
        object.__setattr__(self, "policy", _freeze_mapping(self.policy))
        normalized_reasons = tuple(
            require_non_empty(str(code), "reason_code") for code in self.reason_codes
        )
        if not normalized_reasons:
            raise ValueError("A5 terminal evidence requires reason codes")
        if len(set(normalized_reasons)) != len(normalized_reasons):
            raise ValueError("A5 terminal reason codes must be unique")
        object.__setattr__(self, "reason_codes", normalized_reasons)
        if self.fold is not None:
            object.__setattr__(self, "fold", _freeze_mapping(self.fold))
        if self.aggregate is not None:
            object.__setattr__(self, "aggregate", _freeze_mapping(self.aggregate))
        object.__setattr__(self, "error_type", self.error_type.strip())
        object.__setattr__(self, "error_message", self.error_message.strip())
        execution_failure = bool(self.error_type)
        if execution_failure:
            if self.status is not ReserveTerminalStatus.FAIL:
                raise ValueError("execution failure must terminate as RESERVE_FAIL")
            if self.fold is not None or self.aggregate is not None:
                raise ValueError("execution-failure RESERVE_FAIL cannot carry a completed portfolio")
        elif self.error_message:
            raise ValueError("error_message requires error_type")
        elif self.fold is None or self.aggregate is None:
            raise ValueError("economic RESERVE_PASS/FAIL require completed fold and aggregate evidence")
        if self.status is ReserveTerminalStatus.PASS and any(
            code.startswith("POLICY_") for code in self.reason_codes
        ):
            raise ValueError("RESERVE_PASS cannot include failed policy reason codes")
        if self.status is ReserveTerminalStatus.PASS and execution_failure:
            raise ValueError("RESERVE_PASS cannot represent an execution failure")
        if self.status is ReserveTerminalStatus.PASS and "RESERVE_PASS_TERMINAL" not in self.reason_codes:
            raise ValueError("RESERVE_PASS must carry RESERVE_PASS_TERMINAL")
        if self.status is ReserveTerminalStatus.FAIL and "RESERVE_FAIL_TERMINAL" not in self.reason_codes:
            raise ValueError("RESERVE_FAIL must carry RESERVE_FAIL_TERMINAL")

    def identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": RESERVE_TERMINAL_SCHEMA,
            "execution_id": self.execution_id,
            "seal_id": self.seal_id,
            "reserve_id": self.reserve_id,
            "program_result_id": self.program_result_id,
            "portfolio_validation_id": self.portfolio_validation_id,
            "protocol_digest": self.protocol_digest,
            "execution_protocol_id": self.execution_protocol_id,
            "final_training_rule_id": self.final_training_rule_id,
            "terminal_policy_rule_id": self.terminal_policy_rule_id,
            "runtime_code_git_sha": self.runtime_code_git_sha,
            "status": self.status.value,
            "reserve_dataset_digest": self.reserve_dataset_digest,
            "reserve_ledger_digest": self.reserve_ledger_digest,
            "reserve_ledger_file_sha256": self.reserve_ledger_file_sha256,
            "fold_digest": self.fold_digest,
            "aggregate_digest": self.aggregate_digest,
            "fold": dict(self.fold) if self.fold is not None else None,
            "aggregate": dict(self.aggregate) if self.aggregate is not None else None,
            "policy": dict(self.policy),
            "reason_codes": list(self.reason_codes),
            "engine_id": self.engine_id,
            "execution_failed": bool(self.error_type),
            "error_type": self.error_type,
            "error_message_sha256": (
                _sha256_bytes(self.error_message.encode("utf-8")) if self.error_type else ""
            ),
            "promotion_eligible": False,
            "reserve_accessed": True,
            "terminal": True,
            "consumed_state_persistence": "PENDING_A5_3",
        }

    @property
    def terminal_evidence_id(self) -> str:
        return _identity("ashare-reserve-terminal", self.identity_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_dict(),
            "terminal_evidence_id": self.terminal_evidence_id,
            "authorized_by": self.authorized_by,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "error_type": self.error_type,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ReserveTerminalEvidence":
        if raw.get("schema_version") != RESERVE_TERMINAL_SCHEMA:
            raise ValueError("unsupported A5 reserve terminal evidence schema")
        try:
            status = ReserveTerminalStatus(str(raw.get("status")))
        except ValueError as exc:
            raise ValueError("invalid A5 reserve terminal status") from exc
        fold_raw = raw.get("fold")
        aggregate_raw = raw.get("aggregate")
        result = cls(
            execution_id=require_non_empty(str(raw.get("execution_id", "")), "execution_id"),
            seal_id=require_non_empty(str(raw.get("seal_id", "")), "seal_id"),
            reserve_id=require_non_empty(str(raw.get("reserve_id", "")), "reserve_id"),
            program_result_id=require_non_empty(
                str(raw.get("program_result_id", "")), "program_result_id"
            ),
            portfolio_validation_id=require_non_empty(
                str(raw.get("portfolio_validation_id", "")), "portfolio_validation_id"
            ),
            protocol_digest=require_non_empty(
                str(raw.get("protocol_digest", "")), "protocol_digest"
            ),
            execution_protocol_id=require_non_empty(
                str(raw.get("execution_protocol_id", "")), "execution_protocol_id"
            ),
            final_training_rule_id=require_non_empty(
                str(raw.get("final_training_rule_id", "")), "final_training_rule_id"
            ),
            terminal_policy_rule_id=require_non_empty(
                str(raw.get("terminal_policy_rule_id", "")), "terminal_policy_rule_id"
            ),
            runtime_code_git_sha=require_non_empty(
                str(raw.get("runtime_code_git_sha", "")), "runtime_code_git_sha"
            ),
            authorized_by=require_non_empty(str(raw.get("authorized_by", "")), "authorized_by"),
            status=status,
            reserve_dataset_digest=require_non_empty(
                str(raw.get("reserve_dataset_digest", "")), "reserve_dataset_digest"
            ),
            reserve_ledger_digest=require_non_empty(
                str(raw.get("reserve_ledger_digest", "")), "reserve_ledger_digest"
            ),
            reserve_ledger_file_sha256=require_non_empty(
                str(raw.get("reserve_ledger_file_sha256", "")), "reserve_ledger_file_sha256"
            ),
            fold_digest=require_non_empty(str(raw.get("fold_digest", "")), "fold_digest"),
            aggregate_digest=require_non_empty(
                str(raw.get("aggregate_digest", "")), "aggregate_digest"
            ),
            fold=_mapping(fold_raw, "fold") if fold_raw is not None else None,
            aggregate=(
                _mapping(aggregate_raw, "aggregate") if aggregate_raw is not None else None
            ),
            policy=_mapping(raw.get("policy"), "policy"),
            reason_codes=tuple(str(value) for value in _sequence(raw.get("reason_codes"), "reason_codes")),
            engine_id=require_non_empty(str(raw.get("engine_id", "")), "engine_id"),
            started_at=datetime.fromisoformat(
                require_non_empty(str(raw.get("started_at", "")), "started_at")
            ),
            finished_at=datetime.fromisoformat(
                require_non_empty(str(raw.get("finished_at", "")), "finished_at")
            ),
            error_type=str(raw.get("error_type", "")),
            error_message=str(raw.get("error_message", "")),
        )
        provided = str(raw.get("terminal_evidence_id", "")).strip()
        if provided and provided != result.terminal_evidence_id:
            raise ValueError("A5 terminal evidence identity does not match payload")
        if raw.get("promotion_eligible") is not False:
            raise PermissionError("A5 terminal evidence cannot promote directly")
        if raw.get("reserve_accessed") is not True or raw.get("terminal") is not True:
            raise ValueError("A5 terminal evidence access/terminal flags are invalid")
        if raw.get("consumed_state_persistence") != "PENDING_A5_3":
            raise ValueError("A5-2 terminal evidence cannot claim durable consumed-state persistence")
        if raw.get("execution_failed") is not bool(result.error_type):
            raise ValueError("A5 terminal execution_failed flag is inconsistent")
        expected_error_digest = (
            _sha256_bytes(result.error_message.encode("utf-8")) if result.error_type else ""
        )
        if str(raw.get("error_message_sha256", "")) != expected_error_digest:
            raise ValueError("A5 terminal error message digest is inconsistent")
        return result

    def write_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if target.exists() and target.read_text(encoding="utf-8") != encoded:
            raise ValueError("A5 terminal evidence output is immutable")
        target.write_text(encoded, encoding="utf-8")
        return target


@dataclass(frozen=True, slots=True)
class ReserveRunArtifacts:
    terminal: ReserveTerminalEvidence
    ledger_bytes: bytes | None

    def __post_init__(self) -> None:
        if self.terminal.error_type:
            if self.ledger_bytes not in (None, b""):
                raise ValueError("execution-failure RESERVE_FAIL cannot claim a completed ledger artifact")
            return
        if self.ledger_bytes is None:
            # Idempotent re-inspection of existing terminal evidence never re-opens the
            # reserve. A5-3 will provide durable ledger replay/recovery.
            return
        if _sha256_bytes(self.ledger_bytes) != self.terminal.reserve_ledger_file_sha256:
            raise ValueError("reserve ledger bytes do not match terminal evidence")

    def write(self, *, terminal_path: str | Path, ledger_path: str | Path) -> tuple[Path, Path]:
        if self.terminal.error_type or self.ledger_bytes is None:
            raise PermissionError("no completed in-memory reserve ledger is available to write")
        terminal_target = self.terminal.write_json(terminal_path)
        ledger_target = Path(ledger_path)
        ledger_target.parent.mkdir(parents=True, exist_ok=True)
        if ledger_target.exists() and ledger_target.read_bytes() != self.ledger_bytes:
            raise ValueError("A5 reserve execution ledger output is immutable")
        ledger_target.write_bytes(self.ledger_bytes)
        return terminal_target, ledger_target


class SQLiteReserveTerminalEvidenceStore:
    """Append-only A5-2 terminal evidence store.

    It prevents a completed terminal run from being accessed twice, but it is *not* the
    crash-safe consumed-state authority. A5-3 will add the pre-access atomic claim and
    persistent CONSUMED lifecycle required for production execution.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reserve_terminal_evidence (
                    terminal_evidence_id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL UNIQUE,
                    seal_id TEXT NOT NULL UNIQUE,
                    reserve_id TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def register(self, evidence: ReserveTerminalEvidence) -> None:
        encoded = _canonical_json(evidence.to_dict())
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT terminal_evidence_id, payload_json
                FROM reserve_terminal_evidence
                WHERE execution_id=? OR seal_id=? OR reserve_id=? OR terminal_evidence_id=?
                """,
                (
                    evidence.execution_id,
                    evidence.seal_id,
                    evidence.reserve_id,
                    evidence.terminal_evidence_id,
                ),
            ).fetchone()
            if row is not None:
                if row[0] == evidence.terminal_evidence_id and row[1] == encoded:
                    return
                raise ValueError("reserve already has different terminal evidence")
            connection.execute(
                "INSERT INTO reserve_terminal_evidence VALUES (?, ?, ?, ?, ?)",
                (
                    evidence.terminal_evidence_id,
                    evidence.execution_id,
                    evidence.seal_id,
                    evidence.reserve_id,
                    encoded,
                ),
            )

    def get_for_seal(self, seal_id: str) -> ReserveTerminalEvidence:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM reserve_terminal_evidence WHERE seal_id=?",
                (seal_id,),
            ).fetchone()
        if row is None:
            raise KeyError(seal_id)
        return ReserveTerminalEvidence.from_dict(_mapping(json.loads(row[0]), "terminal evidence"))

    def get_for_reserve(self, reserve_id: str) -> ReserveTerminalEvidence:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM reserve_terminal_evidence WHERE reserve_id=?",
                (reserve_id,),
            ).fetchone()
        if row is None:
            raise KeyError(reserve_id)
        return ReserveTerminalEvidence.from_dict(_mapping(json.loads(row[0]), "terminal evidence"))


class AshareReserveOneShotRunner:
    """A5-2 deterministic runner over one reviewed eligibility seal.

    The runner deliberately does not implement durable pre-access consumption claiming.
    That crash-safety boundary belongs to A5-3, so production reserve access remains
    disabled by governance until A5-3 lands even though the deterministic engine and
    terminal evidence path are complete here.
    """

    def __init__(
        self,
        *,
        eligibility_store: SQLiteReserveEligibilityStore,
        terminal_store: SQLiteReserveTerminalEvidenceStore,
        engine: ReserveEvaluationEngine,
        clock,
    ) -> None:
        self.eligibility_store = eligibility_store
        self.terminal_store = terminal_store
        self.engine = engine
        self.clock = clock

    @staticmethod
    def _report_digest(report: Mapping[str, Any]) -> str:
        return _sha256_json(report)

    @staticmethod
    def execution_id(seal: ReserveEligibilitySeal) -> str:
        return _identity(
            "ashare-reserve-run",
            {
                "seal_id": seal.seal_id,
                "reserve_id": seal.reserve_id,
                "protocol_id": RESERVE_EXECUTION_PROTOCOL_ID,
            },
        )

    def _preflight(
        self,
        *,
        seal: ReserveEligibilitySeal,
        a26_report: Mapping[str, Any],
        a4_report: Mapping[str, Any],
        runtime_code_git_sha: str,
    ) -> ReserveTerminalEvidence | None:
        persisted = ReserveEligibilitySeal.from_dict(self.eligibility_store.get(seal.seal_id))
        if _canonical_json(persisted.to_dict()) != _canonical_json(seal.to_dict()):
            raise ValueError("A5 runner seal differs from the exact persisted eligibility seal")
        if runtime_code_git_sha != seal.code_git_sha:
            raise PermissionError("A5 runtime Git identity differs from the reviewed eligibility seal")
        if self._report_digest(a26_report) != seal.program_report_sha256:
            raise ValueError("A5 runtime A2.6 report differs from the eligibility seal")
        if self._report_digest(a4_report) != seal.portfolio_report_sha256:
            raise ValueError("A5 runtime A4 report differs from the eligibility seal")
        try:
            existing = self.terminal_store.get_for_seal(seal.seal_id)
        except KeyError:
            existing = None
        if existing is not None:
            if existing.execution_id != self.execution_id(seal):
                raise ValueError("existing A5 terminal evidence belongs to a different execution")
            return existing
        self.engine.preflight(seal=seal, a26_report=a26_report, a4_report=a4_report)
        return None

    def run(
        self,
        *,
        seal: ReserveEligibilitySeal,
        a26_report: Mapping[str, Any],
        a4_report: Mapping[str, Any],
        runtime_code_git_sha: str,
        actor: str,
    ) -> ReserveRunArtifacts:
        actor = require_non_empty(actor, "actor")
        runtime_code_git_sha = require_non_empty(runtime_code_git_sha, "runtime_code_git_sha")
        existing = self._preflight(
            seal=seal,
            a26_report=a26_report,
            a4_report=a4_report,
            runtime_code_git_sha=runtime_code_git_sha,
        )
        if existing is not None:
            # An idempotent repeat may inspect the already-persisted terminal report, but
            # A5-2 never accesses the reserve again. The full ledger bytes are not stored
            # here; A5-3/audit bundle owns durable artifact recovery.
            return ReserveRunArtifacts(terminal=existing, ledger_bytes=None)

        started_at = require_aware_datetime(self.clock(), "A5 started_at")
        execution_id = self.execution_id(seal)
        try:
            evaluation = self.engine.evaluate(
                seal=seal,
                a26_report=a26_report,
                a4_report=a4_report,
            )
            ledger_bytes = reserve_execution_ledger_bytes(evaluation.ledger_rows)
            failed = tuple(f"POLICY_{code}" for code in evaluation.failed_reason_codes)
            if failed:
                status = ReserveTerminalStatus.FAIL
                reasons = (*failed, "RESERVE_FAIL_TERMINAL", "PROMOTION_REQUIRES_A6")
            else:
                status = ReserveTerminalStatus.PASS
                reasons = ("RESERVE_POLICY_PASSED", "RESERVE_PASS_TERMINAL", "PROMOTION_REQUIRES_A6")
            terminal = ReserveTerminalEvidence(
                execution_id=execution_id,
                seal_id=seal.seal_id,
                reserve_id=seal.reserve_id,
                program_result_id=seal.program_result_id,
                portfolio_validation_id=seal.portfolio_validation_id,
                protocol_digest=seal.protocol_digest,
                execution_protocol_id=RESERVE_EXECUTION_PROTOCOL_ID,
                final_training_rule_id=FINAL_TRAINING_RULE_ID,
                terminal_policy_rule_id=TERMINAL_POLICY_RULE_ID,
                runtime_code_git_sha=runtime_code_git_sha,
                authorized_by=actor,
                status=status,
                reserve_dataset_digest=evaluation.reserve_dataset_digest,
                reserve_ledger_digest=evaluation.ledger_digest,
                reserve_ledger_file_sha256=evaluation.ledger_file_sha256,
                fold_digest=evaluation.fold_digest,
                aggregate_digest=evaluation.aggregate_digest,
                fold=evaluation.fold,
                aggregate=evaluation.aggregate,
                policy=evaluation.policy,
                reason_codes=reasons,
                engine_id=evaluation.engine_id,
                started_at=started_at,
                finished_at=require_aware_datetime(self.clock(), "A5 finished_at"),
            )
            self.terminal_store.register(terminal)
            return ReserveRunArtifacts(terminal=terminal, ledger_bytes=ledger_bytes)
        except Exception as exc:
            finished_at = require_aware_datetime(self.clock(), "A5 error finished_at")
            terminal = ReserveTerminalEvidence(
                execution_id=execution_id,
                seal_id=seal.seal_id,
                reserve_id=seal.reserve_id,
                program_result_id=seal.program_result_id,
                portfolio_validation_id=seal.portfolio_validation_id,
                protocol_digest=seal.protocol_digest,
                execution_protocol_id=RESERVE_EXECUTION_PROTOCOL_ID,
                final_training_rule_id=FINAL_TRAINING_RULE_ID,
                terminal_policy_rule_id=TERMINAL_POLICY_RULE_ID,
                runtime_code_git_sha=runtime_code_git_sha,
                authorized_by=actor,
                status=ReserveTerminalStatus.FAIL,
                reserve_dataset_digest="unavailable-after-terminal-error",
                reserve_ledger_digest="unavailable-after-terminal-error",
                reserve_ledger_file_sha256="unavailable-after-terminal-error",
                fold_digest="unavailable-after-terminal-error",
                aggregate_digest="unavailable-after-terminal-error",
                fold=None,
                aggregate=None,
                policy={},
                reason_codes=(
                    "EXECUTION_FAILURE",
                    "RESERVE_FAIL_TERMINAL",
                    "AUTOMATIC_RETRY_FORBIDDEN",
                    "A5_3_CONSUMED_STATE_REQUIRED_FOR_PRODUCTION",
                ),
                engine_id=type(self.engine).__name__,
                started_at=started_at,
                finished_at=finished_at,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            self.terminal_store.register(terminal)
            return ReserveRunArtifacts(terminal=terminal, ledger_bytes=None)

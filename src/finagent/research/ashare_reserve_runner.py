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
from .ashare_reserve_lifecycle import (
    RESERVE_CONSUMPTION_PROTOCOL_ID,
    ReserveConsumptionAudit,
    ReserveConsumptionClaim,
    SQLiteReserveConsumptionStore,
)

RESERVE_TERMINAL_SCHEMA = "finagent.ashare-reserve-terminal-evidence.v1"
RESERVE_TERMINAL_SCHEMA_V2 = "finagent.ashare-reserve-terminal-evidence.v2"
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


class ReserveAccessState(str, Enum):
    LEGACY_ACCESSED = "LEGACY_ACCESSED"
    ACCESSED = "ACCESSED"
    UNKNOWN_AFTER_CONSUMED_CLAIM = "UNKNOWN_AFTER_CONSUMED_CLAIM"


class ReserveAlreadyConsumedError(PermissionError):
    """Raised when a durable A5-3 claim exists but no reusable terminal result exists."""


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
    consumption_claim_id: str = ""
    consumed_at: datetime | None = None
    reserve_access_state: ReserveAccessState = ReserveAccessState.LEGACY_ACCESSED

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
        object.__setattr__(self, "consumption_claim_id", self.consumption_claim_id.strip())
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

        if self.consumption_claim_id:
            if self.consumed_at is None:
                raise ValueError("A5-3 terminal evidence requires consumed_at")
            object.__setattr__(
                self,
                "consumed_at",
                require_aware_datetime(self.consumed_at, "consumed_at"),
            )
            if self.reserve_access_state is ReserveAccessState.LEGACY_ACCESSED:
                raise ValueError("A5-3 terminal evidence requires an explicit reserve access state")
            if self.started_at < self.consumed_at:
                raise ValueError("A5-3 terminal execution cannot start before durable consumption")
        else:
            if self.consumed_at is not None:
                raise ValueError("legacy A5-2 terminal evidence cannot carry consumed_at")
            if self.reserve_access_state is not ReserveAccessState.LEGACY_ACCESSED:
                raise ValueError("legacy A5-2 terminal evidence cannot claim A5-3 access state")

    @property
    def schema_version(self) -> str:
        return RESERVE_TERMINAL_SCHEMA_V2 if self.consumption_claim_id else RESERVE_TERMINAL_SCHEMA

    def identity_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
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
            "terminal": True,
        }
        if self.consumption_claim_id:
            payload.update(
                {
                    "consumption_claim_id": self.consumption_claim_id,
                    "consumed_at": self.consumed_at.isoformat() if self.consumed_at else "",
                    "consumption_protocol_id": RESERVE_CONSUMPTION_PROTOCOL_ID,
                    "consumed_state_persistence": "DURABLE_PRE_ACCESS_V1",
                    "reserve_access_state": self.reserve_access_state.value,
                    "automatic_retry_allowed": False,
                }
            )
        else:
            payload.update(
                {
                    "reserve_accessed": True,
                    "consumed_state_persistence": "PENDING_A5_3",
                }
            )
        return payload

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
        schema = raw.get("schema_version")
        if schema not in {RESERVE_TERMINAL_SCHEMA, RESERVE_TERMINAL_SCHEMA_V2}:
            raise ValueError("unsupported A5 reserve terminal evidence schema")
        try:
            status = ReserveTerminalStatus(str(raw.get("status")))
        except ValueError as exc:
            raise ValueError("invalid A5 reserve terminal status") from exc
        fold_raw = raw.get("fold")
        aggregate_raw = raw.get("aggregate")
        if schema == RESERVE_TERMINAL_SCHEMA_V2:
            if raw.get("consumption_protocol_id") != RESERVE_CONSUMPTION_PROTOCOL_ID:
                raise ValueError("unknown A5-3 reserve consumption protocol")
            if raw.get("consumed_state_persistence") != "DURABLE_PRE_ACCESS_V1":
                raise ValueError("A5-3 terminal evidence lacks durable pre-access consumption")
            if raw.get("automatic_retry_allowed") is not False:
                raise PermissionError("A5-3 terminal evidence cannot permit automatic retry")
            try:
                access_state = ReserveAccessState(str(raw.get("reserve_access_state")))
            except ValueError as exc:
                raise ValueError("invalid A5-3 reserve access state") from exc
            consumption_claim_id = require_non_empty(
                str(raw.get("consumption_claim_id", "")), "consumption_claim_id"
            )
            consumed_at: datetime | None = datetime.fromisoformat(
                require_non_empty(str(raw.get("consumed_at", "")), "consumed_at")
            )
        else:
            if raw.get("reserve_accessed") is not True or raw.get("terminal") is not True:
                raise ValueError("A5 terminal evidence access/terminal flags are invalid")
            if raw.get("consumed_state_persistence") != "PENDING_A5_3":
                raise ValueError("A5-2 terminal evidence cannot claim durable consumed-state persistence")
            access_state = ReserveAccessState.LEGACY_ACCESSED
            consumption_claim_id = ""
            consumed_at = None

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
            reason_codes=tuple(
                str(value) for value in _sequence(raw.get("reason_codes"), "reason_codes")
            ),
            engine_id=require_non_empty(str(raw.get("engine_id", "")), "engine_id"),
            started_at=datetime.fromisoformat(
                require_non_empty(str(raw.get("started_at", "")), "started_at")
            ),
            finished_at=datetime.fromisoformat(
                require_non_empty(str(raw.get("finished_at", "")), "finished_at")
            ),
            error_type=str(raw.get("error_type", "")),
            error_message=str(raw.get("error_message", "")),
            consumption_claim_id=consumption_claim_id,
            consumed_at=consumed_at,
            reserve_access_state=access_state,
        )
        provided = str(raw.get("terminal_evidence_id", "")).strip()
        if provided and provided != result.terminal_evidence_id:
            raise ValueError("A5 terminal evidence identity does not match payload")
        if raw.get("promotion_eligible") is not False:
            raise PermissionError("A5 terminal evidence cannot promote directly")
        if raw.get("terminal") is not True:
            raise ValueError("A5 terminal flag is invalid")
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
    """Append-only terminal evidence and durable ledger artifact store.

    A5-3 keeps the irreversible state transition in `SQLiteReserveConsumptionStore`,
    while this store atomically persists one terminal payload and, for completed
    economic evaluations, the exact canonical reserve JSONL ledger bytes.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA journal_mode=WAL")
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reserve_terminal_artifacts (
                    terminal_evidence_id TEXT PRIMARY KEY,
                    ledger_file_sha256 TEXT NOT NULL,
                    ledger_bytes BLOB NOT NULL,
                    FOREIGN KEY(terminal_evidence_id)
                        REFERENCES reserve_terminal_evidence(terminal_evidence_id)
                )
                """
            )

    @staticmethod
    def _ledger_rows(data: bytes) -> tuple[Mapping[str, object], ...]:
        rows: list[Mapping[str, object]] = []
        for number, raw_line in enumerate(data.decode("utf-8-sig").splitlines(), 1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"A5 reserve ledger line {number} is invalid JSON") from exc
            rows.append(_mapping(value, f"A5 reserve ledger line {number}"))
        if not rows:
            raise ValueError("A5 reserve ledger artifact cannot be empty")
        return tuple(rows)

    @classmethod
    def _validate_ledger(cls, evidence: ReserveTerminalEvidence, ledger_bytes: bytes) -> None:
        if evidence.error_type:
            raise ValueError("execution-failure terminal evidence cannot persist a ledger")
        if _sha256_bytes(ledger_bytes) != evidence.reserve_ledger_file_sha256:
            raise ValueError("persisted reserve ledger SHA-256 differs from terminal evidence")
        rows = cls._ledger_rows(ledger_bytes)
        if reserve_execution_ledger_digest(rows) != evidence.reserve_ledger_digest:
            raise ValueError("persisted reserve ledger digest differs from terminal evidence")

    def register(
        self,
        evidence: ReserveTerminalEvidence,
        *,
        ledger_bytes: bytes | None = None,
    ) -> None:
        if evidence.schema_version == RESERVE_TERMINAL_SCHEMA_V2 and not evidence.error_type:
            if ledger_bytes is None:
                raise ValueError("A5-3 completed terminal evidence requires durable ledger bytes")
        if ledger_bytes is not None:
            self._validate_ledger(evidence, ledger_bytes)
        encoded = _canonical_json(evidence.to_dict())
        with sqlite3.connect(self.path) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
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
                if row[0] != evidence.terminal_evidence_id or row[1] != encoded:
                    raise ValueError("reserve already has different terminal evidence")
                if ledger_bytes is not None:
                    artifact = connection.execute(
                        """
                        SELECT ledger_file_sha256, ledger_bytes
                        FROM reserve_terminal_artifacts
                        WHERE terminal_evidence_id=?
                        """,
                        (evidence.terminal_evidence_id,),
                    ).fetchone()
                    if artifact is None:
                        raise ValueError("terminal evidence exists without its durable reserve ledger")
                    if artifact[0] != evidence.reserve_ledger_file_sha256 or bytes(artifact[1]) != ledger_bytes:
                        raise ValueError("stored reserve ledger conflicts with terminal evidence")
                return
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
            if ledger_bytes is not None:
                connection.execute(
                    "INSERT INTO reserve_terminal_artifacts VALUES (?, ?, ?)",
                    (
                        evidence.terminal_evidence_id,
                        evidence.reserve_ledger_file_sha256,
                        ledger_bytes,
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

    def get_ledger_for_terminal(self, terminal_evidence_id: str) -> bytes:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT ledger_file_sha256, ledger_bytes
                FROM reserve_terminal_artifacts
                WHERE terminal_evidence_id=?
                """,
                (terminal_evidence_id,),
            ).fetchone()
        if row is None:
            raise KeyError(terminal_evidence_id)
        data = bytes(row[1])
        if _sha256_bytes(data) != str(row[0]):
            raise ValueError("durable reserve ledger artifact failed SHA-256 verification")
        return data


@dataclass(frozen=True, slots=True)
class ReserveLifecycleAuditReport:
    reserve_id: str
    seal_id: str
    execution_id: str
    claim_id: str
    terminal_evidence_id: str
    audit_id: str
    terminal_status: ReserveTerminalStatus
    terminal_payload_sha256: str
    ledger_file_sha256: str
    recovery_terminal: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "reserve_id": self.reserve_id,
            "seal_id": self.seal_id,
            "execution_id": self.execution_id,
            "claim_id": self.claim_id,
            "terminal_evidence_id": self.terminal_evidence_id,
            "audit_id": self.audit_id,
            "terminal_status": self.terminal_status.value,
            "terminal_payload_sha256": self.terminal_payload_sha256,
            "ledger_file_sha256": self.ledger_file_sha256,
            "recovery_terminal": self.recovery_terminal,
            "state": "CONSUMED",
            "pre_access_claim_verified": True,
            "terminal_link_verified": True,
            "ledger_replay_verified": True,
            "automatic_retry_allowed": False,
        }


class AshareReserveOneShotRunner:
    """A5-3 crash-safe one-shot runner over one reviewed eligibility seal.

    All zero-access validation runs first. The runner then commits an irreversible
    `CONSUMED` claim through `SQLiteReserveConsumptionStore`. Only the transaction that
    newly acquires that claim may call the reserve engine. A pre-existing claim without
    terminal evidence blocks execution and requires explicit crash recovery; it is never
    interpreted as permission to re-open the reserve.
    """

    def __init__(
        self,
        *,
        eligibility_store: SQLiteReserveEligibilityStore,
        consumption_store: SQLiteReserveConsumptionStore,
        terminal_store: SQLiteReserveTerminalEvidenceStore,
        engine: ReserveEvaluationEngine,
        clock,
    ) -> None:
        self.eligibility_store = eligibility_store
        self.consumption_store = consumption_store
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

    def _build_claim(
        self,
        *,
        seal: ReserveEligibilitySeal,
        runtime_code_git_sha: str,
        actor: str,
        claimed_at: datetime,
    ) -> ReserveConsumptionClaim:
        return ReserveConsumptionClaim(
            execution_id=self.execution_id(seal),
            seal_id=seal.seal_id,
            reserve_id=seal.reserve_id,
            program_result_id=seal.program_result_id,
            portfolio_validation_id=seal.portfolio_validation_id,
            protocol_digest=seal.protocol_digest,
            runtime_code_git_sha=runtime_code_git_sha,
            authorized_by=actor,
            claimed_at=claimed_at,
        )

    def _validate_claim_terminal(
        self,
        *,
        claim: ReserveConsumptionClaim,
        terminal: ReserveTerminalEvidence,
    ) -> None:
        if terminal.schema_version != RESERVE_TERMINAL_SCHEMA_V2:
            raise PermissionError("legacy A5-2 terminal evidence is not a durable A5-3 lifecycle")
        expected = (
            (terminal.execution_id, claim.execution_id, "execution"),
            (terminal.seal_id, claim.seal_id, "seal"),
            (terminal.reserve_id, claim.reserve_id, "reserve"),
            (terminal.protocol_digest, claim.protocol_digest, "protocol"),
            (terminal.runtime_code_git_sha, claim.runtime_code_git_sha, "runtime Git"),
            (terminal.consumption_claim_id, claim.claim_id, "consumption claim"),
        )
        for actual, frozen, name in expected:
            if actual != frozen:
                raise ValueError(f"A5 terminal {name} identity differs from CONSUMED claim")
        if terminal.consumed_at != claim.claimed_at:
            raise ValueError("A5 terminal consumed_at differs from durable claim timestamp")

    def _terminal_payload_sha256(self, terminal: ReserveTerminalEvidence) -> str:
        return _sha256_json(terminal.to_dict())

    def _reconcile_audit(
        self,
        *,
        claim: ReserveConsumptionClaim,
        terminal: ReserveTerminalEvidence,
        ledger_bytes: bytes | None,
        recovery_terminal: bool,
    ) -> ReserveConsumptionAudit:
        self._validate_claim_terminal(claim=claim, terminal=terminal)
        ledger_sha = ""
        if not terminal.error_type:
            if ledger_bytes is None:
                raise ValueError("completed A5 terminal evidence has no durable ledger for audit")
            if _sha256_bytes(ledger_bytes) != terminal.reserve_ledger_file_sha256:
                raise ValueError("A5 audit ledger SHA-256 differs from terminal evidence")
            ledger_sha = terminal.reserve_ledger_file_sha256
        audit = ReserveConsumptionAudit(
            claim_id=claim.claim_id,
            execution_id=claim.execution_id,
            seal_id=claim.seal_id,
            reserve_id=claim.reserve_id,
            terminal_evidence_id=terminal.terminal_evidence_id,
            terminal_status=terminal.status.value,
            terminal_payload_sha256=self._terminal_payload_sha256(terminal),
            ledger_file_sha256=ledger_sha,
            finalized_at=require_aware_datetime(self.clock(), "A5 audit finalized_at"),
            recovery_terminal=recovery_terminal,
        )
        return self.consumption_store.finalize(audit)

    def _existing_artifacts(
        self,
        *,
        claim: ReserveConsumptionClaim,
        terminal: ReserveTerminalEvidence,
    ) -> ReserveRunArtifacts:
        self._validate_claim_terminal(claim=claim, terminal=terminal)
        ledger_bytes: bytes | None = None
        if not terminal.error_type:
            ledger_bytes = self.terminal_store.get_ledger_for_terminal(terminal.terminal_evidence_id)
        try:
            audit = self.consumption_store.get_audit_for_claim(claim.claim_id)
        except KeyError:
            audit = self._reconcile_audit(
                claim=claim,
                terminal=terminal,
                ledger_bytes=ledger_bytes,
                recovery_terminal="RECOVERED_WITHOUT_RESERVE_REACCESS" in terminal.reason_codes,
            )
        if audit.terminal_evidence_id != terminal.terminal_evidence_id:
            raise ValueError("A5 consumption audit points to different terminal evidence")
        if audit.terminal_payload_sha256 != self._terminal_payload_sha256(terminal):
            raise ValueError("A5 consumption audit terminal payload digest drifted")
        return ReserveRunArtifacts(terminal=terminal, ledger_bytes=ledger_bytes)

    def _preflight(
        self,
        *,
        seal: ReserveEligibilitySeal,
        a26_report: Mapping[str, Any],
        a4_report: Mapping[str, Any],
        runtime_code_git_sha: str,
    ) -> ReserveRunArtifacts | None:
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
            terminal = self.terminal_store.get_for_seal(seal.seal_id)
        except KeyError:
            terminal = None
        try:
            claim = self.consumption_store.get_claim_for_seal(seal.seal_id)
        except KeyError:
            claim = None

        if terminal is not None:
            if claim is None:
                raise PermissionError(
                    "terminal evidence exists without an A5-3 durable CONSUMED claim"
                )
            return self._existing_artifacts(claim=claim, terminal=terminal)
        if claim is not None:
            raise ReserveAlreadyConsumedError(
                "reserve is already CONSUMED without terminal evidence; explicit recovery is required"
            )

        # Engine preflight is a zero-reserve-access contract. The irreversible claim is
        # deliberately committed only after all of these checks pass.
        self.engine.preflight(seal=seal, a26_report=a26_report, a4_report=a4_report)
        return None

    def _persist_terminal(
        self,
        *,
        claim: ReserveConsumptionClaim,
        terminal: ReserveTerminalEvidence,
        ledger_bytes: bytes | None,
        recovery_terminal: bool,
    ) -> ReserveRunArtifacts:
        self.terminal_store.register(terminal, ledger_bytes=ledger_bytes)
        self._reconcile_audit(
            claim=claim,
            terminal=terminal,
            ledger_bytes=ledger_bytes,
            recovery_terminal=recovery_terminal,
        )
        return ReserveRunArtifacts(terminal=terminal, ledger_bytes=ledger_bytes)

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
            return existing

        claimed_at = require_aware_datetime(self.clock(), "A5 CONSUMED claimed_at")
        proposed = self._build_claim(
            seal=seal,
            runtime_code_git_sha=runtime_code_git_sha,
            actor=actor,
            claimed_at=claimed_at,
        )
        claim_result = self.consumption_store.claim(proposed)
        claim = claim_result.claim
        if not claim_result.acquired:
            # Another contender committed CONSUMED first. Never call evaluate() from this
            # process. If it has already finished, the immutable terminal may be reused;
            # otherwise the operator must explicitly recover the interrupted claim.
            try:
                terminal = self.terminal_store.get_for_seal(seal.seal_id)
            except KeyError as exc:
                raise ReserveAlreadyConsumedError(
                    "reserve CONSUMED claim was acquired elsewhere; reserve re-access is forbidden"
                ) from exc
            return self._existing_artifacts(claim=claim, terminal=terminal)

        started_at = claim.claimed_at
        execution_id = claim.execution_id
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
                reasons = (
                    "RESERVE_POLICY_PASSED",
                    "RESERVE_PASS_TERMINAL",
                    "PROMOTION_REQUIRES_A6",
                )
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
                consumption_claim_id=claim.claim_id,
                consumed_at=claim.claimed_at,
                reserve_access_state=ReserveAccessState.ACCESSED,
            )
        except Exception as exc:
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
                    "EXECUTION_FAILURE_AFTER_DURABLE_CONSUMPTION",
                    "RESERVE_FAIL_TERMINAL",
                    "AUTOMATIC_RETRY_FORBIDDEN",
                ),
                engine_id=type(self.engine).__name__,
                started_at=started_at,
                finished_at=require_aware_datetime(self.clock(), "A5 error finished_at"),
                error_type=type(exc).__name__,
                error_message=str(exc),
                consumption_claim_id=claim.claim_id,
                consumed_at=claim.claimed_at,
                reserve_access_state=ReserveAccessState.UNKNOWN_AFTER_CONSUMED_CLAIM,
            )
            ledger_bytes = None

        # Persistence failures are intentionally *not* converted into a second terminal
        # attempt. The CONSUMED claim already blocks re-access; explicit recovery closes
        # a claim that lacks durable terminal evidence.
        return self._persist_terminal(
            claim=claim,
            terminal=terminal,
            ledger_bytes=ledger_bytes,
            recovery_terminal=False,
        )

    def recover_interrupted(self, *, seal_id: str, actor: str) -> ReserveRunArtifacts:
        """Close a CONSUMED-without-terminal crash as FAIL without reserve re-access."""

        actor = require_non_empty(actor, "actor")
        claim = self.consumption_store.get_claim_for_seal(require_non_empty(seal_id, "seal_id"))
        try:
            terminal = self.terminal_store.get_for_seal(claim.seal_id)
        except KeyError:
            terminal = None
        if terminal is not None:
            return self._existing_artifacts(claim=claim, terminal=terminal)
        terminal = ReserveTerminalEvidence(
            execution_id=claim.execution_id,
            seal_id=claim.seal_id,
            reserve_id=claim.reserve_id,
            program_result_id=claim.program_result_id,
            portfolio_validation_id=claim.portfolio_validation_id,
            protocol_digest=claim.protocol_digest,
            execution_protocol_id=RESERVE_EXECUTION_PROTOCOL_ID,
            final_training_rule_id=FINAL_TRAINING_RULE_ID,
            terminal_policy_rule_id=TERMINAL_POLICY_RULE_ID,
            runtime_code_git_sha=claim.runtime_code_git_sha,
            authorized_by=claim.authorized_by,
            status=ReserveTerminalStatus.FAIL,
            reserve_dataset_digest="unavailable-after-interrupted-consumed-claim",
            reserve_ledger_digest="unavailable-after-interrupted-consumed-claim",
            reserve_ledger_file_sha256="unavailable-after-interrupted-consumed-claim",
            fold_digest="unavailable-after-interrupted-consumed-claim",
            aggregate_digest="unavailable-after-interrupted-consumed-claim",
            fold=None,
            aggregate=None,
            policy={},
            reason_codes=(
                "INTERRUPTED_AFTER_DURABLE_CONSUMPTION",
                "RECOVERED_WITHOUT_RESERVE_REACCESS",
                "RESERVE_FAIL_TERMINAL",
                "AUTOMATIC_RETRY_FORBIDDEN",
            ),
            engine_id="a5-crash-recovery-no-reaccess-v1",
            started_at=claim.claimed_at,
            finished_at=require_aware_datetime(self.clock(), "A5 recovery finished_at"),
            error_type="InterruptedReserveExecution",
            error_message=(
                "durable CONSUMED claim had no terminal evidence; "
                f"closed without reserve re-access by {actor}"
            ),
            consumption_claim_id=claim.claim_id,
            consumed_at=claim.claimed_at,
            reserve_access_state=ReserveAccessState.UNKNOWN_AFTER_CONSUMED_CLAIM,
        )
        return self._persist_terminal(
            claim=claim,
            terminal=terminal,
            ledger_bytes=None,
            recovery_terminal=True,
        )

    def audit_lifecycle(self, *, seal: ReserveEligibilitySeal) -> ReserveLifecycleAuditReport:
        """Replay persisted A5-3 identities and artifacts without opening reserve data."""

        persisted = ReserveEligibilitySeal.from_dict(self.eligibility_store.get(seal.seal_id))
        if _canonical_json(persisted.to_dict()) != _canonical_json(seal.to_dict()):
            raise ValueError("A5 audit eligibility seal differs from caller seal")
        claim = self.consumption_store.get_claim_for_seal(seal.seal_id)
        terminal = self.terminal_store.get_for_seal(seal.seal_id)
        self._validate_claim_terminal(claim=claim, terminal=terminal)
        audit = self.consumption_store.get_audit_for_claim(claim.claim_id)
        expected_payload_sha = self._terminal_payload_sha256(terminal)
        if audit.terminal_evidence_id != terminal.terminal_evidence_id:
            raise ValueError("A5 replay audit terminal identity drifted")
        if audit.terminal_payload_sha256 != expected_payload_sha:
            raise ValueError("A5 replay audit terminal payload digest drifted")
        ledger_sha = ""
        if not terminal.error_type:
            ledger = self.terminal_store.get_ledger_for_terminal(terminal.terminal_evidence_id)
            if _sha256_bytes(ledger) != terminal.reserve_ledger_file_sha256:
                raise ValueError("A5 replay audit reserve ledger SHA-256 drifted")
            rows = SQLiteReserveTerminalEvidenceStore._ledger_rows(ledger)
            if reserve_execution_ledger_digest(rows) != terminal.reserve_ledger_digest:
                raise ValueError("A5 replay audit reserve ledger digest drifted")
            ledger_sha = terminal.reserve_ledger_file_sha256
            if audit.ledger_file_sha256 != ledger_sha:
                raise ValueError("A5 consumption audit ledger identity drifted")
        elif audit.ledger_file_sha256:
            raise ValueError("execution-failure consumption audit cannot claim a reserve ledger")
        return ReserveLifecycleAuditReport(
            reserve_id=seal.reserve_id,
            seal_id=seal.seal_id,
            execution_id=claim.execution_id,
            claim_id=claim.claim_id,
            terminal_evidence_id=terminal.terminal_evidence_id,
            audit_id=audit.audit_id,
            terminal_status=terminal.status,
            terminal_payload_sha256=expected_payload_sha,
            ledger_file_sha256=ledger_sha,
            recovery_terminal=audit.recovery_terminal,
        )

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from finagent.domain._validation import require_aware_datetime, require_non_empty

RESERVE_CONSUMPTION_CLAIM_SCHEMA = "finagent.ashare-reserve-consumption-claim.v1"
RESERVE_CONSUMPTION_AUDIT_SCHEMA = "finagent.ashare-reserve-consumption-audit.v1"
RESERVE_CONSUMPTION_PROTOCOL_ID = "a5-pre-access-consumed-claim-v1"


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


class ReserveConsumptionState(str, Enum):
    CONSUMED = "CONSUMED"


@dataclass(frozen=True, slots=True)
class ReserveConsumptionClaim:
    """Irreversible A5-3 claim committed before any reserve observation access.

    The claim identity is deterministic and deliberately excludes actor/time metadata so
    concurrent contenders for the same sealed execution converge on one claim identity.
    Only the transaction that inserts the row receives acquisition authority.
    """

    execution_id: str
    seal_id: str
    reserve_id: str
    program_result_id: str
    portfolio_validation_id: str
    protocol_digest: str
    runtime_code_git_sha: str
    authorized_by: str
    claimed_at: datetime
    state: ReserveConsumptionState = ReserveConsumptionState.CONSUMED

    def __post_init__(self) -> None:
        for name in (
            "execution_id",
            "seal_id",
            "reserve_id",
            "program_result_id",
            "portfolio_validation_id",
            "protocol_digest",
            "runtime_code_git_sha",
            "authorized_by",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if self.state is not ReserveConsumptionState.CONSUMED:
            raise ValueError("A5-3 reserve state is irreversible and must be CONSUMED")
        object.__setattr__(self, "claimed_at", require_aware_datetime(self.claimed_at, "claimed_at"))

    def identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": RESERVE_CONSUMPTION_CLAIM_SCHEMA,
            "execution_id": self.execution_id,
            "seal_id": self.seal_id,
            "reserve_id": self.reserve_id,
            "program_result_id": self.program_result_id,
            "portfolio_validation_id": self.portfolio_validation_id,
            "protocol_digest": self.protocol_digest,
            "runtime_code_git_sha": self.runtime_code_git_sha,
            "consumption_protocol_id": RESERVE_CONSUMPTION_PROTOCOL_ID,
            "state": self.state.value,
            "pre_access_commit_required": True,
            "irreversible": True,
            "automatic_retry_allowed": False,
        }

    @property
    def claim_id(self) -> str:
        return _identity("ashare-reserve-consumed", self.identity_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_dict(),
            "claim_id": self.claim_id,
            "authorized_by": self.authorized_by,
            "claimed_at": self.claimed_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ReserveConsumptionClaim":
        if raw.get("schema_version") != RESERVE_CONSUMPTION_CLAIM_SCHEMA:
            raise ValueError("unsupported A5 reserve consumption claim schema")
        if raw.get("consumption_protocol_id") != RESERVE_CONSUMPTION_PROTOCOL_ID:
            raise ValueError("unknown A5 reserve consumption protocol")
        if raw.get("pre_access_commit_required") is not True:
            raise PermissionError("reserve claim does not prove pre-access persistence")
        if raw.get("irreversible") is not True or raw.get("automatic_retry_allowed") is not False:
            raise PermissionError("reserve claim does not preserve one-shot irreversibility")
        try:
            state = ReserveConsumptionState(str(raw.get("state")))
        except ValueError as exc:
            raise ValueError("invalid A5 reserve consumption state") from exc
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
            runtime_code_git_sha=require_non_empty(
                str(raw.get("runtime_code_git_sha", "")), "runtime_code_git_sha"
            ),
            authorized_by=require_non_empty(str(raw.get("authorized_by", "")), "authorized_by"),
            claimed_at=datetime.fromisoformat(
                require_non_empty(str(raw.get("claimed_at", "")), "claimed_at")
            ),
            state=state,
        )
        provided = str(raw.get("claim_id", "")).strip()
        if provided and provided != result.claim_id:
            raise ValueError("A5 reserve consumption claim identity does not match payload")
        return result


@dataclass(frozen=True, slots=True)
class ReserveConsumptionClaimResult:
    claim: ReserveConsumptionClaim
    acquired: bool


@dataclass(frozen=True, slots=True)
class ReserveConsumptionAudit:
    """Append-only link from the durable pre-access claim to one terminal result."""

    claim_id: str
    execution_id: str
    seal_id: str
    reserve_id: str
    terminal_evidence_id: str
    terminal_status: str
    terminal_payload_sha256: str
    ledger_file_sha256: str
    finalized_at: datetime
    recovery_terminal: bool

    def __post_init__(self) -> None:
        for name in (
            "claim_id",
            "execution_id",
            "seal_id",
            "reserve_id",
            "terminal_evidence_id",
            "terminal_status",
            "terminal_payload_sha256",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if self.terminal_status not in {"RESERVE_PASS", "RESERVE_FAIL"}:
            raise ValueError("A5 consumption audit terminal status must be PASS or FAIL")
        if len(self.terminal_payload_sha256) != 64:
            raise ValueError("terminal_payload_sha256 must be a full SHA-256 digest")
        ledger_hash = self.ledger_file_sha256.strip()
        if ledger_hash and len(ledger_hash) != 64:
            raise ValueError("ledger_file_sha256 must be empty or a full SHA-256 digest")
        object.__setattr__(self, "ledger_file_sha256", ledger_hash)
        object.__setattr__(
            self,
            "finalized_at",
            require_aware_datetime(self.finalized_at, "finalized_at"),
        )

    def identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": RESERVE_CONSUMPTION_AUDIT_SCHEMA,
            "claim_id": self.claim_id,
            "execution_id": self.execution_id,
            "seal_id": self.seal_id,
            "reserve_id": self.reserve_id,
            "terminal_evidence_id": self.terminal_evidence_id,
            "terminal_status": self.terminal_status,
            "terminal_payload_sha256": self.terminal_payload_sha256,
            "ledger_file_sha256": self.ledger_file_sha256,
            "recovery_terminal": self.recovery_terminal,
            "state": ReserveConsumptionState.CONSUMED.value,
            "automatic_retry_allowed": False,
        }

    @property
    def audit_id(self) -> str:
        return _identity("ashare-reserve-consumption-audit", self.identity_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_dict(),
            "audit_id": self.audit_id,
            "finalized_at": self.finalized_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ReserveConsumptionAudit":
        if raw.get("schema_version") != RESERVE_CONSUMPTION_AUDIT_SCHEMA:
            raise ValueError("unsupported A5 reserve consumption audit schema")
        if raw.get("state") != ReserveConsumptionState.CONSUMED.value:
            raise ValueError("A5 reserve audit must preserve CONSUMED state")
        if raw.get("automatic_retry_allowed") is not False:
            raise PermissionError("A5 reserve audit cannot permit automatic retry")
        if not isinstance(raw.get("recovery_terminal"), bool):
            raise TypeError("recovery_terminal must be a JSON boolean")
        result = cls(
            claim_id=require_non_empty(str(raw.get("claim_id", "")), "claim_id"),
            execution_id=require_non_empty(str(raw.get("execution_id", "")), "execution_id"),
            seal_id=require_non_empty(str(raw.get("seal_id", "")), "seal_id"),
            reserve_id=require_non_empty(str(raw.get("reserve_id", "")), "reserve_id"),
            terminal_evidence_id=require_non_empty(
                str(raw.get("terminal_evidence_id", "")), "terminal_evidence_id"
            ),
            terminal_status=require_non_empty(
                str(raw.get("terminal_status", "")), "terminal_status"
            ),
            terminal_payload_sha256=require_non_empty(
                str(raw.get("terminal_payload_sha256", "")), "terminal_payload_sha256"
            ),
            ledger_file_sha256=str(raw.get("ledger_file_sha256", "")),
            finalized_at=datetime.fromisoformat(
                require_non_empty(str(raw.get("finalized_at", "")), "finalized_at")
            ),
            recovery_terminal=raw["recovery_terminal"],
        )
        provided = str(raw.get("audit_id", "")).strip()
        if provided and provided != result.audit_id:
            raise ValueError("A5 reserve consumption audit identity does not match payload")
        return result


class SQLiteReserveConsumptionStore:
    """Crash-safe A5-3 reserve state authority.

    `claim()` uses `BEGIN IMMEDIATE` plus uniqueness constraints and FULL synchronous
    durability. A successful insert is the irreversible `UNTOUCHED -> CONSUMED`
    transition. Callers must not read reserve observations unless `acquired` is True.
    A pre-existing claim is never a license to re-run the reserve.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reserve_consumption_claims (
                    claim_id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL UNIQUE,
                    seal_id TEXT NOT NULL UNIQUE,
                    reserve_id TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reserve_consumption_audits (
                    audit_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL UNIQUE,
                    execution_id TEXT NOT NULL UNIQUE,
                    reserve_id TEXT NOT NULL UNIQUE,
                    terminal_evidence_id TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(claim_id) REFERENCES reserve_consumption_claims(claim_id)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @staticmethod
    def _same_execution(left: ReserveConsumptionClaim, right: ReserveConsumptionClaim) -> bool:
        return left.identity_dict() == right.identity_dict()

    def claim(self, proposed: ReserveConsumptionClaim) -> ReserveConsumptionClaimResult:
        connection = self._connect()
        try:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT payload_json
                FROM reserve_consumption_claims
                WHERE claim_id=? OR execution_id=? OR seal_id=? OR reserve_id=?
                """,
                (
                    proposed.claim_id,
                    proposed.execution_id,
                    proposed.seal_id,
                    proposed.reserve_id,
                ),
            ).fetchone()
            if row is not None:
                existing = ReserveConsumptionClaim.from_dict(
                    _mapping(json.loads(row[0]), "reserve consumption claim")
                )
                if not self._same_execution(existing, proposed):
                    raise ValueError("reserve identity already has a different CONSUMED claim")
                connection.commit()
                return ReserveConsumptionClaimResult(claim=existing, acquired=False)
            connection.execute(
                "INSERT INTO reserve_consumption_claims VALUES (?, ?, ?, ?, ?)",
                (
                    proposed.claim_id,
                    proposed.execution_id,
                    proposed.seal_id,
                    proposed.reserve_id,
                    _canonical_json(proposed.to_dict()),
                ),
            )
            connection.commit()
            return ReserveConsumptionClaimResult(claim=proposed, acquired=True)
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def _get_claim(self, field: str, value: str) -> ReserveConsumptionClaim:
        if field not in {"claim_id", "execution_id", "seal_id", "reserve_id"}:
            raise ValueError("unsupported reserve claim lookup")
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM reserve_consumption_claims WHERE {field}=?",
                (value,),
            ).fetchone()
        if row is None:
            raise KeyError(value)
        return ReserveConsumptionClaim.from_dict(
            _mapping(json.loads(row[0]), "reserve consumption claim")
        )

    def get_claim(self, claim_id: str) -> ReserveConsumptionClaim:
        return self._get_claim("claim_id", claim_id)

    def get_claim_for_execution(self, execution_id: str) -> ReserveConsumptionClaim:
        return self._get_claim("execution_id", execution_id)

    def get_claim_for_seal(self, seal_id: str) -> ReserveConsumptionClaim:
        return self._get_claim("seal_id", seal_id)

    def get_claim_for_reserve(self, reserve_id: str) -> ReserveConsumptionClaim:
        return self._get_claim("reserve_id", reserve_id)

    def finalize(self, audit: ReserveConsumptionAudit) -> ReserveConsumptionAudit:
        connection = self._connect()
        try:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            claim_row = connection.execute(
                "SELECT payload_json FROM reserve_consumption_claims WHERE claim_id=?",
                (audit.claim_id,),
            ).fetchone()
            if claim_row is None:
                raise KeyError(audit.claim_id)
            claim = ReserveConsumptionClaim.from_dict(
                _mapping(json.loads(claim_row[0]), "reserve consumption claim")
            )
            if (
                claim.execution_id != audit.execution_id
                or claim.seal_id != audit.seal_id
                or claim.reserve_id != audit.reserve_id
            ):
                raise ValueError("terminal audit does not bind the exact CONSUMED claim")
            row = connection.execute(
                """
                SELECT payload_json
                FROM reserve_consumption_audits
                WHERE audit_id=? OR claim_id=? OR execution_id=? OR reserve_id=?
                   OR terminal_evidence_id=?
                """,
                (
                    audit.audit_id,
                    audit.claim_id,
                    audit.execution_id,
                    audit.reserve_id,
                    audit.terminal_evidence_id,
                ),
            ).fetchone()
            if row is not None:
                existing = ReserveConsumptionAudit.from_dict(
                    _mapping(json.loads(row[0]), "reserve consumption audit")
                )
                if existing.identity_dict() != audit.identity_dict():
                    raise ValueError("reserve CONSUMED claim already has different terminal audit")
                connection.commit()
                return existing
            connection.execute(
                "INSERT INTO reserve_consumption_audits VALUES (?, ?, ?, ?, ?, ?)",
                (
                    audit.audit_id,
                    audit.claim_id,
                    audit.execution_id,
                    audit.reserve_id,
                    audit.terminal_evidence_id,
                    _canonical_json(audit.to_dict()),
                ),
            )
            connection.commit()
            return audit
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def get_audit_for_claim(self, claim_id: str) -> ReserveConsumptionAudit:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM reserve_consumption_audits WHERE claim_id=?",
                (claim_id,),
            ).fetchone()
        if row is None:
            raise KeyError(claim_id)
        return ReserveConsumptionAudit.from_dict(
            _mapping(json.loads(row[0]), "reserve consumption audit")
        )

    def get_audit_for_reserve(self, reserve_id: str) -> ReserveConsumptionAudit:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM reserve_consumption_audits WHERE reserve_id=?",
                (reserve_id,),
            ).fetchone()
        if row is None:
            raise KeyError(reserve_id)
        return ReserveConsumptionAudit.from_dict(
            _mapping(json.loads(row[0]), "reserve consumption audit")
        )

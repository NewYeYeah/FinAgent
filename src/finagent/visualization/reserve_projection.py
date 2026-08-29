from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from finagent.research.ashare_reserve import ReserveEligibilitySeal
from finagent.research.ashare_reserve_lifecycle import (
    ReserveConsumptionAudit,
    ReserveConsumptionClaim,
)
from finagent.research.ashare_reserve_runner import (
    ReserveTerminalEvidence,
    reserve_execution_ledger_digest,
)

from .semantic import EvidenceContractError


RESERVE_WORKSPACE_SCHEMA = "finagent.workspace.reserve-lifecycle.v1"
RESERVE_LIST_SCHEMA = "finagent.workspace.reserve-list.v1"
RESERVE_LEDGER_SCHEMA = "finagent.workspace.reserve-ledger.v1"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceContractError(f"{name} must be a JSON object")
    return value



def _sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise EvidenceContractError(f"{name} must be a JSON array")
    return value

def _json_rows(data: bytes) -> tuple[Mapping[str, object], ...]:
    rows: list[Mapping[str, object]] = []
    for number, raw in enumerate(data.decode("utf-8-sig").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EvidenceContractError(f"reserve ledger line {number} is invalid JSON") from exc
        if not isinstance(value, Mapping):
            raise EvidenceContractError(f"reserve ledger line {number} must be an object")
        rows.append(dict(value))
    if not rows:
        raise EvidenceContractError("reserve ledger artifact is empty")
    return tuple(rows)


def _readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def _payload_rows(path: Path, table: str) -> tuple[Mapping[str, Any], ...]:
    with _readonly(path) as connection:
        try:
            rows = connection.execute(f"SELECT payload_json FROM {table}").fetchall()
        except sqlite3.OperationalError as exc:
            raise EvidenceContractError(f"{path}: missing expected A5 table {table}") from exc
    values: list[Mapping[str, Any]] = []
    for (encoded,) in rows:
        try:
            values.append(_mapping(json.loads(str(encoded)), f"{table}.payload_json"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EvidenceContractError(f"{path}: invalid JSON payload in {table}") from exc
    return tuple(values)


class ReserveWorkspaceProjection:
    """Read-only A5 lifecycle projection over the three authoritative SQLite stores.

    The projection never creates SQLite files and never instantiates the mutable store
    classes. Every request opens existing databases with SQLite ``mode=ro`` and
    ``query_only`` so the Workspace cannot claim, execute, recover, or promote a reserve.
    """

    def __init__(
        self,
        *,
        eligibility_path: str | Path | None = None,
        consumption_path: str | Path | None = None,
        terminal_path: str | Path | None = None,
    ) -> None:
        self.eligibility_path = Path(eligibility_path).expanduser() if eligibility_path else None
        self.consumption_path = Path(consumption_path).expanduser() if consumption_path else None
        self.terminal_path = Path(terminal_path).expanduser() if terminal_path else None

    def configuration(self) -> dict[str, object]:
        paths = {
            "eligibility": self.eligibility_path,
            "consumption": self.consumption_path,
            "terminal": self.terminal_path,
        }
        return {
            "configured": any(path is not None for path in paths.values()),
            "available": {name: bool(path and path.is_file()) for name, path in paths.items()},
            "read_only": True,
        }

    def _load(self) -> tuple[
        dict[str, ReserveEligibilitySeal],
        dict[str, ReserveConsumptionClaim],
        dict[str, ReserveConsumptionAudit],
        dict[str, ReserveTerminalEvidence],
        dict[str, bytes],
        list[str],
    ]:
        seals: dict[str, ReserveEligibilitySeal] = {}
        claims: dict[str, ReserveConsumptionClaim] = {}
        audits: dict[str, ReserveConsumptionAudit] = {}
        terminals: dict[str, ReserveTerminalEvidence] = {}
        ledgers: dict[str, bytes] = {}
        warnings: list[str] = []

        if self.eligibility_path and self.eligibility_path.is_file():
            try:
                for raw in _payload_rows(self.eligibility_path, "reserve_eligibility_seals"):
                    seal = ReserveEligibilitySeal.from_dict(raw)
                    if seal.reserve_id in seals and seals[seal.reserve_id].seal_id != seal.seal_id:
                        raise EvidenceContractError("reserve has conflicting eligibility seals")
                    seals[seal.reserve_id] = seal
            except (ValueError, TypeError, PermissionError, sqlite3.Error) as exc:
                raise EvidenceContractError(f"eligibility store: {exc}") from exc
        elif self.eligibility_path:
            warnings.append(f"A5 eligibility store is unavailable: {self.eligibility_path}")

        if self.consumption_path and self.consumption_path.is_file():
            try:
                for raw in _payload_rows(self.consumption_path, "reserve_consumption_claims"):
                    claim = ReserveConsumptionClaim.from_dict(raw)
                    if claim.reserve_id in claims and claims[claim.reserve_id].claim_id != claim.claim_id:
                        raise EvidenceContractError("reserve has conflicting CONSUMED claims")
                    claims[claim.reserve_id] = claim
                for raw in _payload_rows(self.consumption_path, "reserve_consumption_audits"):
                    audit = ReserveConsumptionAudit.from_dict(raw)
                    if audit.reserve_id in audits and audits[audit.reserve_id].audit_id != audit.audit_id:
                        raise EvidenceContractError("reserve has conflicting consumption audits")
                    audits[audit.reserve_id] = audit
            except (ValueError, TypeError, PermissionError, sqlite3.Error) as exc:
                raise EvidenceContractError(f"consumption store: {exc}") from exc
        elif self.consumption_path:
            warnings.append(f"A5 consumption store is unavailable: {self.consumption_path}")

        if self.terminal_path and self.terminal_path.is_file():
            try:
                for raw in _payload_rows(self.terminal_path, "reserve_terminal_evidence"):
                    terminal = ReserveTerminalEvidence.from_dict(raw)
                    if terminal.reserve_id in terminals and terminals[terminal.reserve_id].terminal_evidence_id != terminal.terminal_evidence_id:
                        raise EvidenceContractError("reserve has conflicting terminal evidence")
                    terminals[terminal.reserve_id] = terminal
                with _readonly(self.terminal_path) as connection:
                    try:
                        artifacts = connection.execute(
                            "SELECT terminal_evidence_id, ledger_file_sha256, ledger_bytes FROM reserve_terminal_artifacts"
                        ).fetchall()
                    except sqlite3.OperationalError as exc:
                        raise EvidenceContractError(
                            f"{self.terminal_path}: missing expected A5 table reserve_terminal_artifacts"
                        ) from exc
                for terminal_id, stored_sha, blob in artifacts:
                    data = bytes(blob)
                    actual = _sha256_bytes(data)
                    if actual != str(stored_sha):
                        raise EvidenceContractError(
                            f"terminal {terminal_id}: ledger artifact failed SHA-256 verification"
                        )
                    ledgers[str(terminal_id)] = data
            except (ValueError, TypeError, PermissionError, sqlite3.Error) as exc:
                raise EvidenceContractError(f"terminal store: {exc}") from exc
        elif self.terminal_path:
            warnings.append(f"A5 terminal store is unavailable: {self.terminal_path}")

        return seals, claims, audits, terminals, ledgers, warnings

    @staticmethod
    def _check(name: str, passed: bool, detail: str) -> dict[str, object]:
        return {"name": name, "passed": passed, "detail": detail}

    def _item(
        self,
        reserve_id: str,
        *,
        seals: Mapping[str, ReserveEligibilitySeal],
        claims: Mapping[str, ReserveConsumptionClaim],
        audits: Mapping[str, ReserveConsumptionAudit],
        terminals: Mapping[str, ReserveTerminalEvidence],
        ledgers: Mapping[str, bytes],
    ) -> dict[str, object]:
        seal = seals.get(reserve_id)
        claim = claims.get(reserve_id)
        terminal = terminals.get(reserve_id)
        audit = audits.get(reserve_id)
        checks: list[dict[str, object]] = []

        if seal is not None and claim is not None:
            checks.extend(
                [
                    self._check("claim.seal_id", claim.seal_id == seal.seal_id, "CONSUMED claim binds the reviewed eligibility seal"),
                    self._check("claim.protocol_digest", claim.protocol_digest == seal.protocol_digest, "CONSUMED claim preserves frozen protocol identity"),
                    self._check("claim.program_result_id", claim.program_result_id == seal.program_result_id, "CONSUMED claim binds the frozen A2.6 result"),
                    self._check("claim.portfolio_validation_id", claim.portfolio_validation_id == seal.portfolio_validation_id, "CONSUMED claim binds the frozen A4 result"),
                ]
            )
        elif claim is not None:
            checks.append(self._check("eligibility seal", False, "CONSUMED claim exists without its eligibility seal in the configured Workspace stores"))

        ledger_summary: dict[str, object] = {
            "available": False,
            "row_count": 0,
            "semantic_digest": "",
            "file_sha256": "",
            "authority": "authoritative",
        }
        if terminal is not None:
            if claim is not None:
                checks.extend(
                    [
                        self._check("terminal.claim_id", terminal.consumption_claim_id == claim.claim_id, "Terminal evidence binds the durable pre-access claim"),
                        self._check("terminal.execution_id", terminal.execution_id == claim.execution_id, "Terminal evidence binds the one-shot execution"),
                        self._check("terminal.consumed_at", terminal.consumed_at == claim.claimed_at, "Terminal evidence preserves the durable consumption timestamp"),
                    ]
                )
            elif terminal.schema_version.endswith(".v2"):
                checks.append(self._check("consumption claim", False, "A5-3 terminal exists without its durable CONSUMED claim"))

            data = ledgers.get(terminal.terminal_evidence_id)
            if terminal.error_type:
                checks.append(self._check("ledger absence", data is None, "Execution-failure terminal must not claim a completed reserve ledger"))
            else:
                if data is None:
                    checks.append(self._check("ledger artifact", False, "Completed terminal evidence is missing the immutable reserve ledger"))
                else:
                    rows = _json_rows(data)
                    semantic = reserve_execution_ledger_digest(rows)
                    file_sha = _sha256_bytes(data)
                    checks.extend(
                        [
                            self._check("ledger.file_sha256", file_sha == terminal.reserve_ledger_file_sha256, "Exact ledger bytes match terminal evidence"),
                            self._check("ledger.semantic_digest", semantic == terminal.reserve_ledger_digest, "Canonical ledger rows match terminal evidence"),
                        ]
                    )
                    ledger_summary = {
                        "available": True,
                        "row_count": len(rows),
                        "semantic_digest": semantic,
                        "file_sha256": file_sha,
                        "authority": "authoritative",
                    }

        if audit is not None:
            if claim is None or terminal is None:
                checks.append(self._check("audit parents", False, "Consumption audit exists without claim and terminal parents"))
            else:
                terminal_sha = _sha256_json(terminal.to_dict())
                checks.extend(
                    [
                        self._check("audit.claim_id", audit.claim_id == claim.claim_id, "Audit binds the durable CONSUMED claim"),
                        self._check("audit.terminal_id", audit.terminal_evidence_id == terminal.terminal_evidence_id, "Audit binds terminal evidence"),
                        self._check("audit.terminal_payload", audit.terminal_payload_sha256 == terminal_sha, "Audit terminal payload digest is reproducible"),
                        self._check("audit.ledger_sha256", audit.ledger_file_sha256 == str(ledger_summary["file_sha256"]), "Audit ledger hash matches the immutable artifact"),
                    ]
                )

        failed = [check for check in checks if not bool(check["passed"])]
        if claim is None:
            state = "UNTOUCHED"
            a5_status = "ELIGIBILITY_SEALED" if seal is not None else "LOCKED_NOT_CONSUMED"
        elif terminal is None:
            state = "CONSUMED"
            a5_status = "CONSUMED_INTERRUPTED"
        else:
            state = "CONSUMED"
            a5_status = terminal.status.value

        integrity = "FAIL" if failed else ("PASS" if audit is not None else "INCOMPLETE")
        nodes: list[dict[str, object]] = []
        edges: list[dict[str, str]] = []
        if seal is not None:
            nodes.append({"evidence_id": seal.seal_id, "evidence_type": "ReserveEligibilitySeal", "stage": "A5-1", "authority": "authoritative", "status": "complete", "label": "Eligibility seal"})
        if claim is not None:
            nodes.append({"evidence_id": claim.claim_id, "evidence_type": "ReserveConsumptionClaim", "stage": "A5-3", "authority": "authoritative", "status": "CONSUMED", "label": "Durable CONSUMED claim"})
            if seal is not None:
                edges.append({"parent_id": seal.seal_id, "child_id": claim.claim_id, "relation": "authorizes_pre_access_consumption"})
        if terminal is not None:
            nodes.append({"evidence_id": terminal.terminal_evidence_id, "evidence_type": "ReserveTerminalEvidence", "stage": "A5-2/A5-3", "authority": "authoritative", "status": terminal.status.value, "label": "Terminal reserve result"})
            if claim is not None:
                edges.append({"parent_id": claim.claim_id, "child_id": terminal.terminal_evidence_id, "relation": "terminates_one_shot_execution"})
        if audit is not None:
            nodes.append({"evidence_id": audit.audit_id, "evidence_type": "ReserveConsumptionAudit", "stage": "A5-3", "authority": "authoritative", "status": "verified", "label": "Lifecycle replay audit"})
            if terminal is not None:
                edges.append({"parent_id": terminal.terminal_evidence_id, "child_id": audit.audit_id, "relation": "audited_by"})

        return {
            "schema_version": RESERVE_WORKSPACE_SCHEMA,
            "read_only": True,
            "authority": "authoritative",
            "reserve_id": reserve_id,
            "state": state,
            "a5_status": a5_status,
            "promotion_eligible": False,
            "automatic_retry_allowed": False if claim is not None else None,
            "program_result_id": seal.program_result_id if seal else (claim.program_result_id if claim else ""),
            "portfolio_validation_id": seal.portfolio_validation_id if seal else (claim.portfolio_validation_id if claim else ""),
            "seal": seal.to_dict() if seal else None,
            "claim": claim.to_dict() if claim else None,
            "terminal": terminal.to_dict() if terminal else None,
            "audit": audit.to_dict() if audit else None,
            "ledger": ledger_summary,
            "integrity": {
                "status": integrity,
                "checks": checks,
                "failed_count": len(failed),
                "fully_audited": integrity == "PASS",
            },
            "lineage": {"nodes": nodes, "edges": edges},
        }

    def list(self) -> dict[str, object]:
        seals, claims, audits, terminals, ledgers, warnings = self._load()
        reserve_ids = sorted(set(seals) | set(claims) | set(terminals) | set(audits))
        items = [
            self._item(
                reserve_id,
                seals=seals,
                claims=claims,
                audits=audits,
                terminals=terminals,
                ledgers=ledgers,
            )
            for reserve_id in reserve_ids
        ]
        return {
            "schema_version": RESERVE_LIST_SCHEMA,
            "read_only": True,
            "configured": self.configuration()["configured"],
            "configuration": self.configuration(),
            "items": items,
            "warnings": warnings,
        }

    def get(self, reserve_id: str) -> dict[str, object]:
        payload = self.list()
        for item in _sequence(payload.get("items"), "reserve items"):
            if isinstance(item, Mapping) and item.get("reserve_id") == reserve_id:
                if _mapping(item.get("integrity"), "integrity").get("status") == "FAIL":
                    raise EvidenceContractError(f"reserve {reserve_id} failed lifecycle integrity checks")
                return dict(item)
        raise KeyError(reserve_id)

    def find_for_a4(self, validation_id: str) -> dict[str, object] | None:
        payload = self.list()
        for item in _sequence(payload.get("items"), "reserve items"):
            if isinstance(item, Mapping) and item.get("portfolio_validation_id") == validation_id:
                return dict(item)
        return None

    def find_for_program(self, program_result_id: str) -> dict[str, object] | None:
        payload = self.list()
        for item in _sequence(payload.get("items"), "reserve items"):
            if isinstance(item, Mapping) and item.get("program_result_id") == program_result_id:
                return dict(item)
        return None

    def ledger(self, reserve_id: str) -> dict[str, object]:
        seals, claims, audits, terminals, ledgers, _ = self._load()
        if reserve_id not in set(seals) | set(claims) | set(terminals) | set(audits):
            raise KeyError(reserve_id)
        terminal = terminals.get(reserve_id)
        if terminal is None or terminal.error_type:
            raise KeyError(reserve_id)
        data = ledgers.get(terminal.terminal_evidence_id)
        if data is None:
            raise EvidenceContractError("completed terminal evidence has no durable ledger artifact")
        rows = _json_rows(data)
        if _sha256_bytes(data) != terminal.reserve_ledger_file_sha256:
            raise EvidenceContractError("reserve ledger file SHA-256 differs from terminal evidence")
        if reserve_execution_ledger_digest(rows) != terminal.reserve_ledger_digest:
            raise EvidenceContractError("reserve ledger semantic digest differs from terminal evidence")
        return {
            "schema_version": RESERVE_LEDGER_SCHEMA,
            "read_only": True,
            "authority": "authoritative",
            "reserve_id": reserve_id,
            "terminal_evidence_id": terminal.terminal_evidence_id,
            "row_count": len(rows),
            "semantic_digest": terminal.reserve_ledger_digest,
            "file_sha256": terminal.reserve_ledger_file_sha256,
            "rows": [dict(row) for row in rows],
        }

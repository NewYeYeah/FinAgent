"""Durable R3 admission: reserve before calls, fail closed on uncertain outcomes."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finagent.agents.r3_contracts import (
    ContractError,
    ResearchRuntimePolicy,
    canonical_json,
    identifier,
    integer,
    number,
)


@dataclass(frozen=True, slots=True)
class Reservation:
    request_id: str
    slot: int
    ordinal: int
    lease: str | None
    result: dict[str, Any] | None = None


class ResearchLedger:
    """One immutable run binding per database. The Agent never gets this object/path.

    BEGIN IMMEDIATE serializes all admission/accounting across processes. At
    most one call is outstanding per run; a crash cannot trigger an automatic
    duplicate provider call. This is application-level control, not an OS jail.
    """

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        binding: Mapping[str, object],
        policy: ResearchRuntimePolicy,
        now: float,
    ) -> None:
        identifier(run_id)
        number(now)
        self.path = path
        self.policy = policy
        self.run_id = run_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS run (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), run_id TEXT NOT NULL,
                binding TEXT NOT NULL, created REAL NOT NULL, deadline REAL NOT NULL,
                last_clock REAL NOT NULL, status TEXT NOT NULL)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS attempts (
                request_id TEXT PRIMARY KEY, slot INTEGER NOT NULL, ordinal INTEGER NOT NULL,
                lease TEXT NOT NULL, state TEXT NOT NULL, charged_tokens INTEGER NOT NULL,
                charged_cost INTEGER NOT NULL, evaluation_reserved INTEGER NOT NULL DEFAULT 0,
                wire_digest TEXT, candidate_id TEXT, proposal_json TEXT, result_json TEXT,
                UNIQUE(slot, ordinal))""")
            row = connection.execute("SELECT run_id,binding FROM run WHERE singleton=1").fetchone()
            frozen = canonical_json({**binding, "policy": policy.to_dict()})
            if row is None:
                connection.execute(
                    "INSERT INTO run VALUES (1,?,?,?,?,?,?)",
                    (run_id, frozen, now, now + policy.maximum_run_seconds, now, "ACTIVE"),
                )
            elif row[0] != run_id or row[1] != frozen:
                raise ContractError("run_binding_mismatch")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _clock(connection: sqlite3.Connection, now: float) -> str:
        number(now)
        row = connection.execute("SELECT * FROM run WHERE singleton=1").fetchone()
        if row is None:
            raise ContractError("missing_run")
        status = str(row["status"])
        if status == "ACTIVE":
            if now < row["last_clock"]:
                status = "CLOCK_REGRESSION"
            elif now >= row["deadline"]:
                status = "TIME_BUDGET_EXHAUSTED"
            connection.execute(
                "UPDATE run SET last_clock=?, status=?", (max(now, row["last_clock"]), status)
            )
        return status

    def reserve(self, request_id: str, slot: int, *, now: float) -> Reservation:
        identifier(request_id)
        integer(slot, 0, self.policy.maximum_slots - 1)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM attempts WHERE request_id=?", (request_id,)
            ).fetchone()
            if existing is not None:
                if existing["slot"] != slot:
                    raise ContractError("request_slot_conflict")
                result = (
                    json.loads(existing["result_json"])
                    if existing["result_json"]
                    else {"outcome": "PENDING_RECONCILIATION"}
                )
                return Reservation(request_id, slot, existing["ordinal"], None, result)
            status = self._clock(connection, now)
            if status != "ACTIVE":
                return Reservation(request_id, slot, 0, None, {"outcome": status})
            if connection.execute("SELECT 1 FROM attempts WHERE state='PENDING'").fetchone():
                return Reservation(request_id, slot, 0, None, {"outcome": "RUN_BUSY"})
            if connection.execute(
                "SELECT 1 FROM attempts WHERE slot=? AND state IN ('SUBMITTED','DUPLICATE')",
                (slot,),
            ).fetchone():
                return Reservation(request_id, slot, 0, None, {"outcome": "SLOT_CLOSED"})
            ordinal = (
                connection.execute(
                    "SELECT COUNT(*) FROM attempts WHERE slot=?", (slot,)
                ).fetchone()[0]
                + 1
            )
            if ordinal > self.policy.maximum_attempts_per_slot:
                return Reservation(
                    request_id, slot, ordinal, None, {"outcome": "SLOT_ATTEMPTS_EXHAUSTED"}
                )
            count, tokens, cost = connection.execute(
                "SELECT COUNT(*),COALESCE(SUM(charged_tokens),0),COALESCE(SUM(charged_cost),0) FROM attempts"
            ).fetchone()
            if (
                count >= self.policy.maximum_attempts
                or tokens + self.policy.tokens_per_call > self.policy.maximum_tokens
                or cost + self.policy.cost_per_call_microusd > self.policy.maximum_cost_microusd
            ):
                connection.execute("UPDATE run SET status='RUN_BUDGET_EXHAUSTED'")
                return Reservation(
                    request_id, slot, ordinal, None, {"outcome": "RUN_BUDGET_EXHAUSTED"}
                )
            lease = uuid.uuid4().hex
            connection.execute(
                """INSERT INTO attempts
                (request_id,slot,ordinal,lease,state,charged_tokens,charged_cost)
                VALUES (?,?,?,?,'PENDING',?,?)""",
                (
                    request_id,
                    slot,
                    ordinal,
                    lease,
                    self.policy.tokens_per_call,
                    self.policy.cost_per_call_microusd,
                ),
            )
            return Reservation(request_id, slot, ordinal, lease)

    def active(self, reservation: Reservation, *, now: float, evaluation: bool = False) -> bool:
        with self._transaction() as connection:
            if self._clock(connection, now) != "ACTIVE":
                return False
            row = connection.execute(
                "SELECT lease,state FROM attempts WHERE request_id=?", (reservation.request_id,)
            ).fetchone()
            if row is None or row[0] != reservation.lease or row[1] != "PENDING":
                return False
            if evaluation:
                count = connection.execute(
                    "SELECT COALESCE(SUM(evaluation_reserved),0) FROM attempts"
                ).fetchone()[0]
                if count >= self.policy.maximum_evaluations:
                    return False
                connection.execute(
                    "UPDATE attempts SET evaluation_reserved=1 WHERE request_id=?",
                    (reservation.request_id,),
                )
            return True

    def finish(
        self,
        reservation: Reservation,
        result: Mapping[str, object],
        *,
        tokens: int | None = None,
        cost: int | None = None,
        wire_digest: str | None = None,
        candidate_id: str | None = None,
        proposal_json: str | None = None,
        halt: str | None = None,
    ) -> dict[str, Any]:
        if tokens is not None:
            integer(tokens)
        if cost is not None:
            integer(cost)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM attempts WHERE request_id=?", (reservation.request_id,)
            ).fetchone()
            if row is None or row["lease"] != reservation.lease or row["state"] != "PENDING":
                raise ContractError("reservation_no_longer_owned")
            payload = dict(result)
            if (
                payload["outcome"] == "SUBMITTED"
                and connection.execute(
                    "SELECT 1 FROM attempts WHERE candidate_id=? AND state='SUBMITTED'",
                    (candidate_id,),
                ).fetchone()
            ):
                payload["outcome"] = "DUPLICATE"
            if (tokens is not None and tokens > self.policy.tokens_per_call) or (
                cost is not None and cost > self.policy.cost_per_call_microusd
            ):
                halt = "PROVIDER_ACCOUNTING_BREACH"
                payload = {"outcome": halt}
                candidate_id = proposal_json = None
            connection.execute(
                """UPDATE attempts SET state=?,charged_tokens=?,charged_cost=?,
                wire_digest=?,candidate_id=?,proposal_json=?,result_json=? WHERE request_id=?""",
                (
                    payload["outcome"],
                    tokens if tokens is not None else row["charged_tokens"],
                    cost if cost is not None else row["charged_cost"],
                    wire_digest,
                    candidate_id,
                    proposal_json,
                    canonical_json(payload),
                    reservation.request_id,
                ),
            )
            if halt is not None:
                connection.execute("UPDATE run SET status=?", (halt,))
            return payload

    def recall(self) -> list[dict[str, Any]]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT result_json FROM attempts WHERE result_json IS NOT NULL ORDER BY rowid DESC LIMIT 6"
            ).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]

    def proposal(self, candidate_id: str) -> str | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT proposal_json FROM attempts WHERE candidate_id=? AND proposal_json IS NOT NULL ORDER BY rowid LIMIT 1",
                (candidate_id,),
            ).fetchone()
        return str(row[0]) if row else None

    def abandon_pending(self) -> int:
        """Trusted operator only, after workers stop. Never refund unknown usage."""
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE attempts SET state='ABANDONED_UNCERTAIN',result_json=? WHERE state='PENDING'",
                (canonical_json({"outcome": "ABANDONED_UNCERTAIN"}),),
            )
            if cursor.rowcount:
                connection.execute("UPDATE run SET status='STOPPED_UNCERTAIN'")
            return cursor.rowcount

    def snapshot(self) -> dict[str, object]:
        with self._transaction() as connection:
            run = connection.execute("SELECT * FROM run WHERE singleton=1").fetchone()
            rows = connection.execute(
                "SELECT request_id,slot,ordinal,state,charged_tokens,charged_cost,evaluation_reserved,wire_digest,candidate_id FROM attempts ORDER BY rowid"
            ).fetchall()
            if run is None:
                raise ContractError("missing_run")
            attempts = [dict(row) for row in rows]
            return {
                "run_id": run["run_id"],
                "status": run["status"],
                "binding": json.loads(run["binding"]),
                "attempt_count": len(rows),
                "attempts": attempts,
                "charged_tokens": sum(row["charged_tokens"] for row in rows),
                "charged_cost_microusd": sum(row["charged_cost"] for row in rows),
                "evaluation_calls": sum(row["evaluation_reserved"] for row in rows),
                "deadline": run["deadline"],
                "alpha_authority": False,
            }

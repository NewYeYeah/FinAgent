"""Small durable research registry over FactorGraph, not a computation engine."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from finagent.domain._validation import require_aware_datetime, require_non_empty
from finagent.research.market_state import utc_text
from finagent.research.us_a1_factor_graph import (
    FactorComplexityBudget,
    FactorDenominatorPolicy,
    FactorGraphSpec,
    FactorInputField,
    FactorNode,
    FactorOperator,
    FactorZeroDenominatorAction,
)
from finagent.research.us_a1_factor_validation import validate_factor_graph
from finagent.research.us_baselines import _canonical_hash


class FactorStatus(StrEnum):
    PROPOSED = "PROPOSED"
    TESTING = "TESTING"
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


class FactorOrigin(StrEnum):
    MANUAL = "manual"
    PROGRAMMATIC = "programmatic"
    AGENT = "agent"


_TRANSITIONS = {
    FactorStatus.PROPOSED: {FactorStatus.TESTING, FactorStatus.REJECTED, FactorStatus.RETIRED},
    FactorStatus.TESTING: {
        FactorStatus.ACTIVE,
        FactorStatus.DORMANT,
        FactorStatus.REJECTED,
        FactorStatus.RETIRED,
    },
    FactorStatus.ACTIVE: {FactorStatus.DORMANT, FactorStatus.RETIRED},
    FactorStatus.DORMANT: {FactorStatus.TESTING, FactorStatus.ACTIVE, FactorStatus.RETIRED},
    FactorStatus.REJECTED: set(),
    FactorStatus.RETIRED: set(),
}


def _json(payload: object) -> str:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


@dataclass(frozen=True)
class FactorRegistration:
    graph: FactorGraphSpec
    family: str
    mechanism: str
    hypothesis: str
    origin: FactorOrigin
    provenance: tuple[tuple[str, str], ...]
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("family", "mechanism", "hypothesis"):
            require_non_empty(getattr(self, name), name)
        if not isinstance(self.origin, FactorOrigin):
            raise TypeError("explicit factor origin required")
        require_aware_datetime(self.created_at, "created_at")
        if not self.provenance or len(dict(self.provenance)) != len(self.provenance):
            raise ValueError("nonempty unique provenance required")
        for key, value in self.provenance:
            require_non_empty(key, "provenance key")
            require_non_empty(value, "provenance value")
        _ = self.factor_id

    @property
    def factor_id(self) -> str:
        validation = validate_factor_graph(self.graph)
        if not validation.valid or validation.canonicalization is None:
            raise ValueError(f"invalid FactorGraph: {validation.blockers}")
        return str(validation.canonicalization.candidate_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "finagent.factor-registration.v1",
            "factor_id": self.factor_id,
            "graph": self.graph.to_dict(),
            "family": self.family,
            "mechanism": self.mechanism,
            "hypothesis": self.hypothesis,
            "origin": self.origin.value,
            "provenance": dict(self.provenance),
            "created_at": utc_text(self.created_at),
            "activation_scope": "research_only_no_alpha_paper_or_live_authority",
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> FactorRegistration:
        """Restore the registry's canonical inert graph; verify the full definition."""
        graph = payload["graph"]
        nodes = []
        for raw in graph["nodes"]:
            node = dict(raw)
            node["operator"] = FactorOperator(node["operator"])
            node["inputs"], node["regime_labels"] = (
                tuple(node["inputs"]),
                tuple(node["regime_labels"]),
            )
            if node["input_field"] is not None:
                node["input_field"] = FactorInputField(node["input_field"])
            if node["denominator_policy"] is not None:
                policy = dict(node["denominator_policy"])
                policy["action"] = FactorZeroDenominatorAction(policy["action"])
                node["denominator_policy"] = FactorDenominatorPolicy(**policy)
            nodes.append(FactorNode(**node))
        values = {field.name: graph[field.name] for field in fields(FactorGraphSpec)}
        values["nodes"] = tuple(nodes)
        values["budget"] = FactorComplexityBudget(
            **{field.name: graph["budget"][field.name] for field in fields(FactorComplexityBudget)}
        )
        result = cls(
            FactorGraphSpec(**values),
            payload["family"],
            payload["mechanism"],
            payload["hypothesis"],
            FactorOrigin(payload["origin"]),
            tuple(sorted(payload["provenance"].items())),
            datetime.fromisoformat(payload["created_at"]),
        )
        canonical = result.to_dict()
        if _json({key: payload[key] for key in canonical}) != _json(canonical):
            raise ValueError("factor registration content identity mismatch")
        return result


class FactorLibrary:
    """Append-only lifecycle and evaluation history, with idempotent exact replay.

    An ACTIVE factor means a research pool member. Metrics never auto-promote it.
    The caller owns the trusted local registration/evaluation boundary.
    """

    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        if read_only:
            self._db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        if read_only:
            return
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS factors (
                factor_id TEXT PRIMARY KEY, definition TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS lifecycle (
                factor_id TEXT NOT NULL REFERENCES factors, sequence INTEGER NOT NULL,
                status TEXT NOT NULL, available_at TEXT NOT NULL,
                actor TEXT NOT NULL, reason TEXT NOT NULL, evaluation_id TEXT,
                PRIMARY KEY (factor_id, sequence));
            CREATE TABLE IF NOT EXISTS evaluations (
                evaluation_id TEXT PRIMARY KEY, factor_id TEXT NOT NULL REFERENCES factors,
                model_id TEXT NOT NULL, available_at TEXT NOT NULL, payload TEXT NOT NULL);
        """)

    def close(self) -> None:
        self._db.close()

    def register(self, definition: FactorRegistration) -> str:
        identity, payload = definition.factor_id, _json(definition.to_dict())
        with self._db:
            row = self._db.execute(
                "SELECT definition FROM factors WHERE factor_id=?", (identity,)
            ).fetchone()
            if row is not None:
                if row["definition"] != payload:
                    raise ValueError("duplicate factor identity with conflicting graph/provenance")
                return identity
            self._db.execute("INSERT INTO factors VALUES (?, ?)", (identity, payload))
            self._db.execute(
                "INSERT INTO lifecycle VALUES (?, 0, ?, ?, ?, ?, NULL)",
                (
                    identity,
                    FactorStatus.PROPOSED.value,
                    utc_text(definition.created_at),
                    definition.origin.value,
                    "registered hypothesis",
                ),
            )
        return identity

    def get(self, factor_id: str, *, as_of: datetime | None = None) -> dict[str, Any]:
        row = self._db.execute(
            "SELECT definition FROM factors WHERE factor_id=?", (factor_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown factor: {factor_id}")
        history = [
            dict(item)
            for item in self._db.execute(
                "SELECT * FROM lifecycle WHERE factor_id=? ORDER BY sequence", (factor_id,)
            )
        ]
        if as_of is not None:
            cutoff = utc_text(as_of)
            history = [item for item in history if item["available_at"] <= cutoff]
        if not history:
            raise KeyError("factor not available at requested time")
        return {
            **json.loads(row["definition"]),
            "status": history[-1]["status"],
            "lifecycle": history,
        }

    def list_factors(self, *, status: FactorStatus | None = None) -> tuple[dict[str, Any], ...]:
        rows = self._db.execute("SELECT factor_id FROM factors ORDER BY factor_id").fetchall()
        result = tuple(self.get(row["factor_id"]) for row in rows)
        return tuple(row for row in result if status is None or row["status"] == status.value)

    def transition(
        self,
        factor_id: str,
        status: FactorStatus,
        *,
        at: datetime,
        actor: str,
        reason: str,
        evaluation_id: str | None = None,
    ) -> None:
        require_non_empty(actor, "actor")
        require_non_empty(reason, "reason")
        stamp = utc_text(at)
        with self._db:
            # Reserve the writer before checking state, so concurrent transitions serialize.
            self._db.execute("BEGIN IMMEDIATE")
            previous = self.get(factor_id)["lifecycle"][-1]
            if (
                previous["status"],
                previous["available_at"],
                previous["actor"],
                previous["reason"],
                previous["evaluation_id"],
            ) == (status.value, stamp, actor, reason, evaluation_id):
                return
            if status not in _TRANSITIONS[FactorStatus(previous["status"])]:
                raise ValueError("invalid factor lifecycle transition")
            if stamp < previous["available_at"]:
                raise ValueError("lifecycle time cannot move backwards")
            if status is FactorStatus.ACTIVE:
                evidence = self._db.execute(
                    "SELECT 1 FROM evaluations WHERE evaluation_id=? AND factor_id=? AND available_at<=?",
                    (evaluation_id, factor_id, stamp),
                ).fetchone()
                if evidence is None:
                    raise ValueError("ACTIVE requires an available evaluation of this factor")
            self._db.execute(
                "INSERT INTO lifecycle VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    factor_id,
                    previous["sequence"] + 1,
                    status.value,
                    stamp,
                    actor,
                    reason,
                    evaluation_id,
                ),
            )

    def record_evaluation(self, report: dict[str, Any]) -> str:
        identity = report["evaluation_id"]
        content = {k: v for k, v in report.items() if k != "evaluation_id"}
        if identity != _canonical_hash(content, prefix="factor-evaluation"):
            raise ValueError("evaluation content identity mismatch")
        if any(
            report.get(name) is not False
            for name in ("alpha_authority", "paper_authority", "live_authority")
        ):
            raise ValueError("FactorLibrary evaluations cannot grant authority")
        at = datetime.fromisoformat(report["available_at"])
        start = datetime.fromisoformat(report["window"]["start"])
        end = datetime.fromisoformat(report["window"]["end"])
        if start >= end or at < end:
            raise ValueError("evaluation window/outcome availability mismatch")
        factor = self.get(report["factor_id"], as_of=start)
        if factor["status"] not in (
            FactorStatus.TESTING,
            FactorStatus.ACTIVE,
            FactorStatus.DORMANT,
        ):
            raise ValueError("factor must enter TESTING before evaluation")
        payload = _json(report)
        with self._db:
            row = self._db.execute(
                "SELECT payload FROM evaluations WHERE evaluation_id=?", (identity,)
            ).fetchone()
            if row is not None:
                if row["payload"] != payload:
                    raise ValueError("conflicting evaluation replay")
                return str(identity)
            self._db.execute(
                "INSERT INTO evaluations VALUES (?, ?, ?, ?, ?)",
                (identity, report["factor_id"], report["model_id"], utc_text(at), payload),
            )
        return str(identity)

    def evaluations(
        self, factor_id: str, *, as_of: datetime | None = None
    ) -> tuple[dict[str, Any], ...]:
        self.get(factor_id, as_of=as_of)
        rows = self._db.execute(
            "SELECT available_at, payload FROM evaluations WHERE factor_id=? ORDER BY available_at, evaluation_id",
            (factor_id,),
        ).fetchall()
        cutoff = utc_text(as_of) if as_of is not None else None
        return tuple(
            json.loads(row["payload"])
            for row in rows
            if cutoff is None or row["available_at"] <= cutoff
        )

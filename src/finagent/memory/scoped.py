from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from finagent.domain.experiments import ExperimentResult

from .domain import (
    FailureCategory,
    FailureRecord,
    FailureStage,
    LineageEdge,
    LineageRelation,
    MemoryNode,
    MemoryNodeType,
)
from .store import SQLiteResearchMemoryStore
from .visibility import EvidenceScope, EvidenceVisibility, SQLiteMemoryVisibilityStore


@dataclass(frozen=True, slots=True)
class ScopedEvidenceWrite:
    node: MemoryNode
    scope: EvidenceScope
    edges: tuple[LineageEdge, ...]


class SQLiteScopedEvidenceWriter:
    """Atomically persist memory evidence, lineage, and Agent visibility.

    Sensitive evidence must never exist as an unscoped memory node, because legacy
    unbound nodes remain Agent-readable for backward compatibility. This writer uses
    one SQLite transaction for the evidence node, its lineage edges, any normalized
    failure row, and the immutable visibility binding.
    """

    def __init__(
        self,
        memory_store: SQLiteResearchMemoryStore,
        visibility_store: SQLiteMemoryVisibilityStore,
    ) -> None:
        memory_path = Path(memory_store.path).resolve()
        visibility_path = Path(visibility_store.path).resolve()
        if memory_path != visibility_path:
            raise ValueError("memory and visibility stores must use the same SQLite database")
        self.memory_store = memory_store
        self.visibility_store = visibility_store
        self.path = memory_path

    @staticmethod
    def _encode(payload: dict[str, object]) -> str:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    @classmethod
    def _node_payload(cls, node: MemoryNode) -> str:
        return cls._encode(
            {
                "label": node.label,
                "created_at": node.created_at.isoformat(),
                "metadata": dict(node.metadata),
            }
        )

    @classmethod
    def _edge_payload(cls, edge: LineageEdge) -> str:
        return cls._encode(
            {
                "created_at": edge.created_at.isoformat(),
                "metadata": dict(edge.metadata),
            }
        )

    @classmethod
    def _failure_payload(cls, failure: FailureRecord) -> str:
        return cls._encode(
            {
                "summary": failure.summary,
                "related_node_keys": list(failure.related_node_keys),
                "metadata": dict(failure.metadata),
            }
        )

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        con = sqlite3.connect(path)
        con.execute("PRAGMA foreign_keys = ON")
        return con

    @staticmethod
    def _scope_row(con: sqlite3.Connection, evidence_key: str):
        return con.execute(
            "SELECT evidence_key, visibility, program_id, recorded_at "
            "FROM memory_evidence_visibility WHERE evidence_key=?",
            (evidence_key,),
        ).fetchone()

    @classmethod
    def _register_node(cls, con: sqlite3.Connection, node: MemoryNode) -> None:
        encoded = cls._node_payload(node)
        row = con.execute(
            "SELECT node_type, node_id, payload_json FROM memory_nodes WHERE node_key=?",
            (node.key,),
        ).fetchone()
        candidate = (node.node_type.value, node.node_id, encoded)
        if row is not None:
            if tuple(row) != candidate:
                raise ValueError(f"memory node {node.key!r} is immutable")
            return
        con.execute(
            "INSERT INTO memory_nodes VALUES (?, ?, ?, ?)",
            (node.key, node.node_type.value, node.node_id, encoded),
        )

    @classmethod
    def _register_edge(cls, con: sqlite3.Connection, edge: LineageEdge) -> None:
        missing = [
            key
            for key in (edge.source_key, edge.target_key)
            if con.execute(
                "SELECT 1 FROM memory_nodes WHERE node_key=?",
                (key,),
            ).fetchone()
            is None
        ]
        if missing:
            raise KeyError(f"lineage endpoint(s) not registered: {missing}")
        encoded = cls._edge_payload(edge)
        row = con.execute(
            "SELECT source_key, target_key, relation, payload_json "
            "FROM lineage_edges WHERE edge_id=?",
            (edge.edge_id,),
        ).fetchone()
        candidate = (edge.source_key, edge.target_key, edge.relation.value, encoded)
        if row is not None:
            if tuple(row) != candidate:
                raise ValueError(f"lineage edge {edge.edge_id!r} is immutable")
            return
        con.execute(
            "INSERT INTO lineage_edges VALUES (?, ?, ?, ?, ?)",
            (
                edge.edge_id,
                edge.source_key,
                edge.target_key,
                edge.relation.value,
                encoded,
            ),
        )

    @classmethod
    def _bind_scope(cls, con: sqlite3.Connection, scope: EvidenceScope) -> None:
        if con.execute(
            "SELECT 1 FROM memory_nodes WHERE node_key=?",
            (scope.evidence_key,),
        ).fetchone() is None:
            raise KeyError(f"memory node {scope.evidence_key!r} is not registered")
        existing = cls._scope_row(con, scope.evidence_key)
        candidate = (
            scope.evidence_key,
            scope.visibility.value,
            scope.program_id,
            scope.recorded_at.isoformat(),
        )
        if existing is not None:
            if tuple(existing) != candidate:
                raise ValueError(
                    f"evidence visibility for {scope.evidence_key!r} is immutable"
                )
            return
        con.execute(
            "INSERT INTO memory_evidence_visibility VALUES (?, ?, ?, ?)",
            candidate,
        )

    @classmethod
    def _reject_retroactive_sensitive_scope(
        cls,
        con: sqlite3.Connection,
        node: MemoryNode,
        visibility: EvidenceVisibility,
    ) -> None:
        if visibility is EvidenceVisibility.SHARED:
            return
        node_exists = con.execute(
            "SELECT 1 FROM memory_nodes WHERE node_key=?",
            (node.key,),
        ).fetchone()
        if node_exists is not None and cls._scope_row(con, node.key) is None:
            raise ValueError(
                "sensitive evidence already exists without a visibility scope; "
                "retroactive classification is forbidden"
            )

    def _register_scoped_graph(
        self,
        node: MemoryNode,
        edges: tuple[LineageEdge, ...],
        *,
        visibility: EvidenceVisibility,
        program_id: str,
    ) -> ScopedEvidenceWrite:
        scope = EvidenceScope(
            evidence_key=node.key,
            visibility=visibility,
            program_id=program_id,
            recorded_at=node.created_at,
        )
        with self._connect(self.path) as con:
            con.execute("BEGIN IMMEDIATE")
            self._reject_retroactive_sensitive_scope(con, node, visibility)
            self._register_node(con, node)
            for edge in edges:
                self._register_edge(con, edge)
            self._bind_scope(con, scope)
        return ScopedEvidenceWrite(node=node, scope=scope, edges=edges)

    def register_result(
        self,
        experiment_id: str,
        result: ExperimentResult,
        created_at,
        *,
        visibility: EvidenceVisibility,
        program_id: str,
    ) -> ScopedEvidenceWrite:
        node = MemoryNode(
            MemoryNodeType.RESULT,
            result.run_id,
            result.run_id,
            created_at,
            {
                "passed": "true" if result.passed else "false",
                "metrics": json.dumps(
                    dict(result.metrics),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "notes": result.notes,
                "artifacts": json.dumps(
                    [artifact.digest for artifact in result.produced_artifacts],
                    separators=(",", ":"),
                ),
            },
        )
        edge = LineageEdge(
            f"experiment:{experiment_id}",
            node.key,
            LineageRelation.PRODUCED,
            created_at,
        )
        return self._register_scoped_graph(
            node,
            (edge,),
            visibility=visibility,
            program_id=program_id,
        )

    def record_failure(
        self,
        *,
        failure_id: str,
        category: FailureCategory,
        stage: FailureStage,
        summary: str,
        observed_at,
        visibility: EvidenceVisibility,
        program_id: str,
        hypothesis_id: str = "",
        experiment_id: str = "",
        related_node_keys: tuple[str, ...] = (),
        metadata: dict[str, str] | None = None,
    ) -> tuple[FailureRecord, ScopedEvidenceWrite]:
        failure = FailureRecord(
            failure_id=failure_id,
            category=category,
            stage=stage,
            summary=summary,
            observed_at=observed_at,
            hypothesis_id=hypothesis_id,
            experiment_id=experiment_id,
            related_node_keys=related_node_keys,
            metadata=metadata or {},
        )
        node = MemoryNode(
            MemoryNodeType.FAILURE,
            failure.failure_id,
            failure.summary,
            failure.observed_at,
            {"category": failure.category.value, "stage": failure.stage.value},
        )
        scope = EvidenceScope(
            evidence_key=node.key,
            visibility=visibility,
            program_id=program_id,
            recorded_at=node.created_at,
        )

        with self._connect(self.path) as con:
            con.execute("BEGIN IMMEDIATE")
            self._reject_retroactive_sensitive_scope(con, node, visibility)
            for key in failure.related_node_keys:
                if con.execute(
                    "SELECT 1 FROM memory_nodes WHERE node_key=?",
                    (key,),
                ).fetchone() is None:
                    raise KeyError(f"failure related node not registered: {key}")

            encoded_failure = self._failure_payload(failure)
            existing_failure = con.execute(
                "SELECT hypothesis_id, experiment_id, category, stage, observed_at, "
                "payload_json FROM research_failures WHERE failure_id=?",
                (failure.failure_id,),
            ).fetchone()
            candidate_failure = (
                failure.hypothesis_id,
                failure.experiment_id,
                failure.category.value,
                failure.stage.value,
                failure.observed_at.isoformat(),
                encoded_failure,
            )
            if existing_failure is not None:
                if tuple(existing_failure) != candidate_failure:
                    raise ValueError(
                        f"failure record {failure.failure_id!r} is immutable"
                    )
            else:
                con.execute(
                    "INSERT INTO research_failures VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (failure.failure_id, *candidate_failure),
                )

            self._register_node(con, node)
            sources = list(failure.related_node_keys)
            if failure.hypothesis_id:
                hypothesis_key = f"hypothesis:{failure.hypothesis_id}"
                if con.execute(
                    "SELECT 1 FROM memory_nodes WHERE node_key=?",
                    (hypothesis_key,),
                ).fetchone():
                    sources.append(hypothesis_key)
            if failure.experiment_id:
                experiment_key = f"experiment:{failure.experiment_id}"
                if con.execute(
                    "SELECT 1 FROM memory_nodes WHERE node_key=?",
                    (experiment_key,),
                ).fetchone():
                    sources.append(experiment_key)

            edges = tuple(
                LineageEdge(
                    source_key,
                    node.key,
                    LineageRelation.FAILED_AS,
                    failure.observed_at,
                )
                for source_key in sorted(set(sources))
            )
            for edge in edges:
                self._register_edge(con, edge)
            self._bind_scope(con, scope)

        return failure, ScopedEvidenceWrite(node=node, scope=scope, edges=edges)

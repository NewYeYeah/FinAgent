from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

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


class AtomicScopedEvidenceWriter:
    """Persist sensitive evidence and its Agent visibility in one SQLite transaction.

    Legacy unbound memory is intentionally Agent-readable. Therefore attaching a
    sensitive scope to an already committed unbound node is forbidden: that would mean
    the evidence may already have been consumed adaptively before being hidden.
    """

    def __init__(
        self,
        memory_store: SQLiteResearchMemoryStore,
        visibility_store: SQLiteMemoryVisibilityStore,
    ) -> None:
        if memory_store.path.resolve() != visibility_store.path.resolve():
            raise ValueError("memory and visibility stores must use the same SQLite database")
        self.memory_store = memory_store
        self.visibility_store = visibility_store

    @staticmethod
    def _scope_candidate(scope: EvidenceScope) -> tuple[str, str, str, str]:
        return (
            scope.evidence_key,
            scope.visibility.value,
            scope.program_id,
            scope.recorded_at.isoformat(),
        )

    def _check_or_insert_scope(self, con, scope: EvidenceScope, *, node_preexisted: bool) -> None:
        existing = con.execute(
            "SELECT evidence_key, visibility, program_id, recorded_at "
            "FROM memory_evidence_visibility WHERE evidence_key=?",
            (scope.evidence_key,),
        ).fetchone()
        candidate = self._scope_candidate(scope)
        if existing is not None:
            if tuple(existing) != candidate:
                raise ValueError(f"evidence visibility for {scope.evidence_key!r} is immutable")
            return
        if node_preexisted:
            raise ValueError(
                "cannot retroactively classify already-committed unbound evidence as sensitive"
            )
        con.execute(
            "INSERT INTO memory_evidence_visibility VALUES (?, ?, ?, ?)",
            candidate,
        )

    def _check_or_insert_node(self, con, node: MemoryNode) -> bool:
        encoded = self.memory_store._encode(self.memory_store._node_payload(node))
        existing = con.execute(
            "SELECT node_type, node_id, payload_json FROM memory_nodes WHERE node_key=?",
            (node.key,),
        ).fetchone()
        candidate = (node.node_type.value, node.node_id, encoded)
        if existing is not None:
            if tuple(existing) != candidate:
                raise ValueError(f"memory node {node.key!r} is immutable")
            return True
        con.execute(
            "INSERT INTO memory_nodes VALUES (?, ?, ?, ?)",
            (node.key, node.node_type.value, node.node_id, encoded),
        )
        return False

    def _check_or_insert_edge(self, con, edge: LineageEdge) -> None:
        encoded = self.memory_store._encode(self.memory_store._edge_payload(edge))
        missing = [
            key
            for key in (edge.source_key, edge.target_key)
            if con.execute("SELECT 1 FROM memory_nodes WHERE node_key=?", (key,)).fetchone()
            is None
        ]
        if missing:
            raise KeyError(f"lineage endpoint(s) not registered: {missing}")
        existing = con.execute(
            "SELECT source_key, target_key, relation, payload_json "
            "FROM lineage_edges WHERE edge_id=?",
            (edge.edge_id,),
        ).fetchone()
        candidate = (edge.source_key, edge.target_key, edge.relation.value, encoded)
        if existing is not None:
            if tuple(existing) != candidate:
                raise ValueError(f"lineage edge {edge.edge_id!r} is immutable")
            return
        con.execute(
            "INSERT INTO lineage_edges VALUES (?, ?, ?, ?, ?)",
            (edge.edge_id, edge.source_key, edge.target_key, edge.relation.value, encoded),
        )

    def register_result_from_source(
        self,
        *,
        source_key: str,
        result: ExperimentResult,
        created_at: datetime,
        visibility: EvidenceVisibility,
        program_id: str,
        extra_metadata: Mapping[str, str] | None = None,
    ) -> ScopedEvidenceWrite:
        metadata = {
            "passed": "true" if result.passed else "false",
            "metrics": json.dumps(
                dict(result.metrics), sort_keys=True, separators=(",", ":")
            ),
            "notes": result.notes,
            "artifacts": json.dumps(
                [artifact.digest for artifact in result.produced_artifacts], separators=(",", ":")
            ),
            **{str(key): str(value) for key, value in (extra_metadata or {}).items()},
        }
        node = MemoryNode(
            MemoryNodeType.RESULT,
            result.run_id,
            result.run_id,
            created_at,
            metadata,
        )
        edge = LineageEdge(source_key, node.key, LineageRelation.PRODUCED, created_at)
        scope = EvidenceScope(node.key, visibility, program_id, created_at)

        with self.memory_store._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            if con.execute(
                "SELECT 1 FROM memory_nodes WHERE node_key=?",
                (source_key,),
            ).fetchone() is None:
                raise KeyError(f"source memory node {source_key!r} is not registered")
            node_preexisted = self._check_or_insert_node(con, node)
            self._check_or_insert_scope(con, scope, node_preexisted=node_preexisted)
            self._check_or_insert_edge(con, edge)
        return ScopedEvidenceWrite(node=node, scope=scope)

    def register_result(
        self,
        *,
        experiment_id: str,
        result: ExperimentResult,
        created_at: datetime,
        visibility: EvidenceVisibility,
        program_id: str,
        extra_metadata: Mapping[str, str] | None = None,
    ) -> ScopedEvidenceWrite:
        return self.register_result_from_source(
            source_key=f"experiment:{experiment_id}",
            result=result,
            created_at=created_at,
            visibility=visibility,
            program_id=program_id,
            extra_metadata=extra_metadata,
        )

    def register_failure(
        self,
        *,
        failure_id: str,
        category: FailureCategory,
        stage: FailureStage,
        summary: str,
        observed_at: datetime,
        visibility: EvidenceVisibility,
        program_id: str,
        hypothesis_id: str = "",
        experiment_id: str = "",
        related_node_keys: tuple[str, ...] = (),
        metadata: Mapping[str, str] | None = None,
    ) -> ScopedEvidenceWrite:
        item = FailureRecord(
            failure_id=failure_id,
            category=category,
            stage=stage,
            summary=summary,
            observed_at=observed_at,
            hypothesis_id=hypothesis_id,
            experiment_id=experiment_id,
            related_node_keys=related_node_keys,
            metadata=dict(metadata or {}),
        )
        node = MemoryNode(
            MemoryNodeType.FAILURE,
            item.failure_id,
            item.summary,
            item.observed_at,
            {"category": item.category.value, "stage": item.stage.value},
        )
        scope = EvidenceScope(node.key, visibility, program_id, observed_at)
        failure_encoded = self.memory_store._encode(self.memory_store._failure_payload(item))

        with self.memory_store._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            existing_failure = con.execute(
                "SELECT hypothesis_id, experiment_id, category, stage, observed_at, payload_json "
                "FROM research_failures WHERE failure_id=?",
                (item.failure_id,),
            ).fetchone()
            failure_candidate = (
                item.hypothesis_id,
                item.experiment_id,
                item.category.value,
                item.stage.value,
                item.observed_at.isoformat(),
                failure_encoded,
            )
            if existing_failure is not None and tuple(existing_failure) != failure_candidate:
                raise ValueError(f"failure record {item.failure_id!r} is immutable")
            for key in item.related_node_keys:
                if con.execute(
                    "SELECT 1 FROM memory_nodes WHERE node_key=?", (key,)
                ).fetchone() is None:
                    raise KeyError(f"failure related node not registered: {key}")

            node_preexisted = con.execute(
                "SELECT 1 FROM memory_nodes WHERE node_key=?", (node.key,)
            ).fetchone() is not None
            if existing_failure is not None and not node_preexisted:
                raise RuntimeError("failure record exists without its canonical memory node")
            if existing_failure is None:
                con.execute(
                    "INSERT INTO research_failures VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (item.failure_id, *failure_candidate),
                )
            self._check_or_insert_node(con, node)
            self._check_or_insert_scope(con, scope, node_preexisted=node_preexisted)

            sources = list(item.related_node_keys)
            if item.hypothesis_id:
                key = f"hypothesis:{item.hypothesis_id}"
                if con.execute("SELECT 1 FROM memory_nodes WHERE node_key=?", (key,)).fetchone():
                    sources.append(key)
            if item.experiment_id:
                key = f"experiment:{item.experiment_id}"
                if con.execute("SELECT 1 FROM memory_nodes WHERE node_key=?", (key,)).fetchone():
                    sources.append(key)
            for source_key in sorted(set(sources)):
                self._check_or_insert_edge(
                    con,
                    LineageEdge(
                        source_key,
                        node.key,
                        LineageRelation.FAILED_AS,
                        item.observed_at,
                    ),
                )
        return ScopedEvidenceWrite(node=node, scope=scope)

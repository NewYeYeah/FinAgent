from __future__ import annotations

import json
import sqlite3
from collections import deque
from datetime import datetime
from pathlib import Path

from .domain import (
    FailureCategory,
    FailureRecord,
    FailureStage,
    HypothesisDisposition,
    LineageEdge,
    LineageRelation,
    MemoryGraph,
    MemoryNode,
    MemoryNodeType,
    ResearchHypothesisRevision,
)


class SQLiteResearchMemoryStore:
    """Relational, auditable Phase 5.5 evidence memory.

    Structured experiment and operational state remains in its source registries. This
    store records stable cross-registry identities, append-only hypothesis revisions,
    lineage edges and normalized failure evidence. It is intentionally not a vector DB.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_nodes (
                    node_key TEXT PRIMARY KEY,
                    node_type TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_node_identity
                    ON memory_nodes(node_type, node_id);

                CREATE TABLE IF NOT EXISTS lineage_edges (
                    edge_id TEXT PRIMARY KEY,
                    source_key TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(source_key) REFERENCES memory_nodes(node_key),
                    FOREIGN KEY(target_key) REFERENCES memory_nodes(node_key)
                );
                CREATE INDEX IF NOT EXISTS idx_lineage_source ON lineage_edges(source_key);
                CREATE INDEX IF NOT EXISTS idx_lineage_target ON lineage_edges(target_key);

                CREATE TABLE IF NOT EXISTS hypothesis_revisions (
                    hypothesis_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(hypothesis_id, revision)
                );

                CREATE TABLE IF NOT EXISTS research_failures (
                    failure_id TEXT PRIMARY KEY,
                    hypothesis_id TEXT NOT NULL,
                    experiment_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_failures_hypothesis
                    ON research_failures(hypothesis_id, observed_at);
                CREATE INDEX IF NOT EXISTS idx_failures_experiment
                    ON research_failures(experiment_id, observed_at);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.execute("PRAGMA foreign_keys = ON")
        return con

    @staticmethod
    def _encode(payload: dict[str, object]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)

    @staticmethod
    def _node_payload(node: MemoryNode) -> dict[str, object]:
        return {
            "label": node.label,
            "created_at": node.created_at.isoformat(),
            "metadata": dict(node.metadata),
        }

    @staticmethod
    def _edge_payload(edge: LineageEdge) -> dict[str, object]:
        return {
            "created_at": edge.created_at.isoformat(),
            "metadata": dict(edge.metadata),
        }

    @staticmethod
    def _hypothesis_payload(item: ResearchHypothesisRevision) -> dict[str, object]:
        return {
            "statement": item.statement,
            "rationale": item.rationale,
            "tags": list(item.tags),
            "disposition": item.disposition.value,
            "fingerprint": item.fingerprint,
            "metadata": dict(item.metadata),
        }

    @staticmethod
    def _failure_payload(item: FailureRecord) -> dict[str, object]:
        return {
            "summary": item.summary,
            "related_node_keys": list(item.related_node_keys),
            "metadata": dict(item.metadata),
        }

    def register_node(self, node: MemoryNode) -> None:
        encoded = self._encode(self._node_payload(node))
        with self._connect() as con:
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

    def node_exists(self, node_key: str) -> bool:
        with self._connect() as con:
            return con.execute("SELECT 1 FROM memory_nodes WHERE node_key=?", (node_key,)).fetchone() is not None

    def get_node(self, node_key: str) -> MemoryNode:
        with self._connect() as con:
            row = con.execute(
                "SELECT node_type, node_id, payload_json FROM memory_nodes WHERE node_key=?",
                (node_key,),
            ).fetchone()
        if row is None:
            raise KeyError(node_key)
        payload = json.loads(row[2])
        return MemoryNode(
            node_type=MemoryNodeType(row[0]),
            node_id=row[1],
            label=payload["label"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            metadata=payload.get("metadata", {}),
        )

    def list_nodes(self, node_type: MemoryNodeType | None = None) -> tuple[MemoryNode, ...]:
        with self._connect() as con:
            if node_type is None:
                rows = con.execute("SELECT node_key FROM memory_nodes ORDER BY node_key").fetchall()
            else:
                rows = con.execute(
                    "SELECT node_key FROM memory_nodes WHERE node_type=? ORDER BY node_key",
                    (node_type.value,),
                ).fetchall()
        return tuple(self.get_node(row[0]) for row in rows)

    def register_edge(self, edge: LineageEdge) -> None:
        encoded = self._encode(self._edge_payload(edge))
        with self._connect() as con:
            missing = [
                key
                for key in (edge.source_key, edge.target_key)
                if con.execute("SELECT 1 FROM memory_nodes WHERE node_key=?", (key,)).fetchone() is None
            ]
            if missing:
                raise KeyError(f"lineage endpoint(s) not registered: {missing}")
            row = con.execute(
                "SELECT source_key, target_key, relation, payload_json FROM lineage_edges WHERE edge_id=?",
                (edge.edge_id,),
            ).fetchone()
            candidate = (edge.source_key, edge.target_key, edge.relation.value, encoded)
            if row is not None:
                if tuple(row) != candidate:
                    raise ValueError(f"lineage edge {edge.edge_id!r} is immutable")
                return
            con.execute(
                "INSERT INTO lineage_edges VALUES (?, ?, ?, ?, ?)",
                (edge.edge_id, edge.source_key, edge.target_key, edge.relation.value, encoded),
            )

    def _edge_from_row(self, row) -> LineageEdge:
        payload = json.loads(row[4])
        return LineageEdge(
            source_key=row[1],
            target_key=row[2],
            relation=LineageRelation(row[3]),
            created_at=datetime.fromisoformat(payload["created_at"]),
            metadata=payload.get("metadata", {}),
        )

    def edges_for(self, node_key: str, *, direction: str = "both") -> tuple[LineageEdge, ...]:
        if direction not in {"out", "in", "both"}:
            raise ValueError("direction must be one of: out, in, both")
        clauses = []
        params: list[str] = []
        if direction in {"out", "both"}:
            clauses.append("source_key=?")
            params.append(node_key)
        if direction in {"in", "both"}:
            clauses.append("target_key=?")
            params.append(node_key)
        query = (
            "SELECT edge_id, source_key, target_key, relation, payload_json FROM lineage_edges WHERE "
            + " OR ".join(clauses)
            + " ORDER BY edge_id"
        )
        with self._connect() as con:
            rows = con.execute(query, tuple(params)).fetchall()
        return tuple(self._edge_from_row(row) for row in rows)

    def traverse(
        self,
        start_key: str,
        *,
        direction: str = "both",
        max_depth: int = 6,
        max_nodes: int = 100,
    ) -> MemoryGraph:
        if max_depth < 0:
            raise ValueError("max_depth must be >= 0")
        if max_nodes < 1:
            raise ValueError("max_nodes must be >= 1")
        start = self.get_node(start_key)
        nodes: dict[str, MemoryNode] = {start.key: start}
        edges: dict[str, LineageEdge] = {}
        queue = deque([(start.key, 0)])
        truncated = False
        while queue:
            key, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in self.edges_for(key, direction=direction):
                edges[edge.edge_id] = edge
                neighbor_keys: list[str] = []
                if direction in {"out", "both"} and edge.source_key == key:
                    neighbor_keys.append(edge.target_key)
                if direction in {"in", "both"} and edge.target_key == key:
                    neighbor_keys.append(edge.source_key)
                for neighbor_key in neighbor_keys:
                    if neighbor_key in nodes:
                        continue
                    if len(nodes) >= max_nodes:
                        truncated = True
                        continue
                    node = self.get_node(neighbor_key)
                    nodes[neighbor_key] = node
                    queue.append((neighbor_key, depth + 1))
        visible = set(nodes)
        filtered_edges = tuple(
            edge
            for edge in sorted(edges.values(), key=lambda item: item.edge_id)
            if edge.source_key in visible and edge.target_key in visible
        )
        return MemoryGraph(
            nodes=tuple(nodes[key] for key in sorted(nodes)),
            edges=filtered_edges,
            truncated=truncated,
        )

    def register_hypothesis_revision(self, item: ResearchHypothesisRevision) -> None:
        payload = self._hypothesis_payload(item)
        encoded = self._encode(payload)
        with self._connect() as con:
            existing = con.execute(
                "SELECT created_at, payload_json FROM hypothesis_revisions WHERE hypothesis_id=? AND revision=?",
                (item.hypothesis_id, item.revision),
            ).fetchone()
            candidate = (item.created_at.isoformat(), encoded)
            if existing is not None:
                if tuple(existing) != candidate:
                    raise ValueError(
                        f"hypothesis revision {item.hypothesis_id!r}/{item.revision} is immutable"
                    )
                return
            row = con.execute(
                "SELECT MAX(revision) FROM hypothesis_revisions WHERE hypothesis_id=?",
                (item.hypothesis_id,),
            ).fetchone()
            latest = row[0] if row and row[0] is not None else 0
            if item.revision != latest + 1:
                raise ValueError("hypothesis revisions must be append-only and contiguous")
            if item.revision == 1:
                node = MemoryNode(
                    MemoryNodeType.HYPOTHESIS,
                    item.hypothesis_id,
                    item.hypothesis_id,
                    item.created_at,
                    {"initial_fingerprint": item.fingerprint},
                )
                node_encoded = self._encode(self._node_payload(node))
                node_row = con.execute(
                    "SELECT node_type, node_id, payload_json FROM memory_nodes WHERE node_key=?",
                    (node.key,),
                ).fetchone()
                node_candidate = (node.node_type.value, node.node_id, node_encoded)
                if node_row is not None and tuple(node_row) != node_candidate:
                    raise ValueError(f"memory node {node.key!r} is immutable")
                if node_row is None:
                    con.execute(
                        "INSERT INTO memory_nodes VALUES (?, ?, ?, ?)",
                        (node.key, node.node_type.value, node.node_id, node_encoded),
                    )
            con.execute(
                "INSERT INTO hypothesis_revisions VALUES (?, ?, ?, ?)",
                (item.hypothesis_id, item.revision, item.created_at.isoformat(), encoded),
            )

    def _hypothesis_from_row(self, hypothesis_id: str, row) -> ResearchHypothesisRevision:
        payload = json.loads(row[2])
        return ResearchHypothesisRevision(
            hypothesis_id=hypothesis_id,
            revision=int(row[0]),
            statement=payload["statement"],
            rationale=payload["rationale"],
            created_at=datetime.fromisoformat(row[1]),
            tags=tuple(payload.get("tags", ())),
            disposition=HypothesisDisposition(payload["disposition"]),
            metadata=payload.get("metadata", {}),
        )

    def hypothesis_history(self, hypothesis_id: str) -> tuple[ResearchHypothesisRevision, ...]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT revision, created_at, payload_json FROM hypothesis_revisions WHERE hypothesis_id=? ORDER BY revision",
                (hypothesis_id,),
            ).fetchall()
        if not rows:
            raise KeyError(hypothesis_id)
        return tuple(self._hypothesis_from_row(hypothesis_id, row) for row in rows)

    def latest_hypothesis(self, hypothesis_id: str) -> ResearchHypothesisRevision:
        return self.hypothesis_history(hypothesis_id)[-1]

    def list_latest_hypotheses(self) -> tuple[ResearchHypothesisRevision, ...]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT DISTINCT hypothesis_id FROM hypothesis_revisions ORDER BY hypothesis_id"
            ).fetchall()
        return tuple(self.latest_hypothesis(row[0]) for row in rows)

    def register_failure(self, item: FailureRecord) -> None:
        encoded = self._encode(self._failure_payload(item))
        with self._connect() as con:
            existing = con.execute(
                "SELECT hypothesis_id, experiment_id, category, stage, observed_at, payload_json FROM research_failures WHERE failure_id=?",
                (item.failure_id,),
            ).fetchone()
            candidate = (
                item.hypothesis_id,
                item.experiment_id,
                item.category.value,
                item.stage.value,
                item.observed_at.isoformat(),
                encoded,
            )
            if existing is not None:
                if tuple(existing) != candidate:
                    raise ValueError(f"failure record {item.failure_id!r} is immutable")
                return
            for key in item.related_node_keys:
                if con.execute("SELECT 1 FROM memory_nodes WHERE node_key=?", (key,)).fetchone() is None:
                    raise KeyError(f"failure related node not registered: {key}")
            con.execute(
                "INSERT INTO research_failures VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item.failure_id, *candidate),
            )

            failure_node = MemoryNode(
                MemoryNodeType.FAILURE,
                item.failure_id,
                item.summary,
                item.observed_at,
                {"category": item.category.value, "stage": item.stage.value},
            )
            failure_encoded = self._encode(self._node_payload(failure_node))
            con.execute(
                "INSERT INTO memory_nodes VALUES (?, ?, ?, ?) ON CONFLICT(node_key) DO NOTHING",
                (failure_node.key, failure_node.node_type.value, failure_node.node_id, failure_encoded),
            )
            sources = list(item.related_node_keys)
            if item.hypothesis_id:
                key = f"{MemoryNodeType.HYPOTHESIS.value}:{item.hypothesis_id}"
                if con.execute("SELECT 1 FROM memory_nodes WHERE node_key=?", (key,)).fetchone():
                    sources.append(key)
            if item.experiment_id:
                key = f"{MemoryNodeType.EXPERIMENT.value}:{item.experiment_id}"
                if con.execute("SELECT 1 FROM memory_nodes WHERE node_key=?", (key,)).fetchone():
                    sources.append(key)
            for source_key in sorted(set(sources)):
                edge = LineageEdge(source_key, failure_node.key, LineageRelation.FAILED_AS, item.observed_at)
                edge_encoded = self._encode(self._edge_payload(edge))
                con.execute(
                    "INSERT INTO lineage_edges VALUES (?, ?, ?, ?, ?) ON CONFLICT(edge_id) DO NOTHING",
                    (edge.edge_id, edge.source_key, edge.target_key, edge.relation.value, edge_encoded),
                )

    def failures(
        self,
        *,
        hypothesis_id: str | None = None,
        experiment_id: str | None = None,
        category: FailureCategory | None = None,
    ) -> tuple[FailureRecord, ...]:
        clauses: list[str] = []
        params: list[str] = []
        if hypothesis_id is not None:
            clauses.append("hypothesis_id=?")
            params.append(hypothesis_id)
        if experiment_id is not None:
            clauses.append("experiment_id=?")
            params.append(experiment_id)
        if category is not None:
            clauses.append("category=?")
            params.append(category.value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as con:
            rows = con.execute(
                "SELECT failure_id, hypothesis_id, experiment_id, category, stage, observed_at, payload_json "
                f"FROM research_failures{where} ORDER BY observed_at, failure_id",
                tuple(params),
            ).fetchall()
        output: list[FailureRecord] = []
        for row in rows:
            payload = json.loads(row[6])
            output.append(
                FailureRecord(
                    failure_id=row[0],
                    hypothesis_id=row[1],
                    experiment_id=row[2],
                    category=FailureCategory(row[3]),
                    stage=FailureStage(row[4]),
                    observed_at=datetime.fromisoformat(row[5]),
                    summary=payload["summary"],
                    related_node_keys=tuple(payload.get("related_node_keys", ())),
                    metadata=payload.get("metadata", {}),
                )
            )
        return tuple(output)

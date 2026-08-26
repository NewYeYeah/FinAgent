from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .domain import MemoryGraph, MemoryNodeType, ResearchMemorySummary
from .service import ResearchMemoryService


class EvidenceVisibility(str, Enum):
    """Research-memory visibility class for adaptive Agent reads.

    This is deliberately separate from persistence/audit visibility. The underlying
    memory store always retains the evidence; this enum only governs whether an
    adaptive research Agent may consume it as prior information.
    """

    SHARED = "shared"
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    SEALED_HOLDOUT = "sealed_holdout"
    OPERATIONAL = "operational"


@dataclass(frozen=True, slots=True)
class EvidenceScope:
    evidence_key: str
    visibility: EvidenceVisibility
    program_id: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        key = self.evidence_key.strip()
        program_id = self.program_id.strip()
        if not key:
            raise ValueError("evidence_key must be non-empty")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        if self.visibility in {
            EvidenceVisibility.DEVELOPMENT,
            EvidenceVisibility.VALIDATION,
            EvidenceVisibility.SEALED_HOLDOUT,
        } and not program_id:
            raise ValueError(f"{self.visibility.value} evidence requires program_id")
        if self.visibility is EvidenceVisibility.SHARED and program_id:
            raise ValueError("shared evidence must not be owned by one research program")
        object.__setattr__(self, "evidence_key", key)
        object.__setattr__(self, "program_id", program_id)


class SQLiteMemoryVisibilityStore:
    """Immutable evidence-scope registry colocated with structured memory.

    The table is intentionally orthogonal to ``memory_nodes``. Existing Phase 5.5
    memory remains backward compatible: an unbound legacy node is treated as shared
    for Agent reads. Newly sensitive evidence can be classified without rewriting the
    immutable memory-node payload.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_evidence_visibility (
                    evidence_key TEXT PRIMARY KEY,
                    visibility TEXT NOT NULL,
                    program_id TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    @staticmethod
    def _from_row(row) -> EvidenceScope:
        return EvidenceScope(
            evidence_key=str(row[0]),
            visibility=EvidenceVisibility(str(row[1])),
            program_id=str(row[2]),
            recorded_at=datetime.fromisoformat(str(row[3])),
        )

    def bind(
        self,
        evidence_key: str,
        visibility: EvidenceVisibility,
        *,
        program_id: str = "",
        recorded_at: datetime | None = None,
    ) -> EvidenceScope:
        scope = EvidenceScope(
            evidence_key=evidence_key,
            visibility=visibility,
            program_id=program_id,
            recorded_at=recorded_at or datetime.now(timezone.utc),
        )
        with self._connect() as con:
            existing = con.execute(
                "SELECT evidence_key, visibility, program_id, recorded_at "
                "FROM memory_evidence_visibility WHERE evidence_key=?",
                (scope.evidence_key,),
            ).fetchone()
            candidate = (
                scope.evidence_key,
                scope.visibility.value,
                scope.program_id,
                scope.recorded_at.isoformat(),
            )
            if existing is not None:
                if tuple(existing) != candidate:
                    raise ValueError(f"evidence visibility for {scope.evidence_key!r} is immutable")
                return self._from_row(existing)
            con.execute(
                "INSERT INTO memory_evidence_visibility VALUES (?, ?, ?, ?)",
                candidate,
            )
        return scope

    def get(self, evidence_key: str) -> EvidenceScope | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT evidence_key, visibility, program_id, recorded_at "
                "FROM memory_evidence_visibility WHERE evidence_key=?",
                (evidence_key,),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def agent_can_read(self, evidence_key: str, *, program_id: str = "") -> bool:
        """Return whether an adaptive research Agent may read this evidence.

        Unbound Phase 5.5 evidence remains readable for backward compatibility.
        Sealed-holdout and operational evidence are never adaptive-research inputs.
        Development/validation evidence is restricted to its owning program. Evidence
        that should become prior knowledge for a later program must be explicitly
        published as a separate SHARED memory artifact rather than relabeling a bound
        record after results are known.
        """

        scope = self.get(evidence_key)
        if scope is None or scope.visibility is EvidenceVisibility.SHARED:
            return True
        if scope.visibility in {
            EvidenceVisibility.SEALED_HOLDOUT,
            EvidenceVisibility.OPERATIONAL,
        }:
            return False
        return bool(program_id) and scope.program_id == program_id.strip()


class AgentResearchMemoryView:
    """Program-scoped read facade for tools exposed to an adaptive research Agent."""

    def __init__(
        self,
        memory: ResearchMemoryService,
        visibility: SQLiteMemoryVisibilityStore,
        *,
        program_id: str = "",
    ) -> None:
        self.memory = memory
        self.visibility = visibility
        self.program_id = program_id.strip()

    def _visible(self, evidence_key: str) -> bool:
        return self.visibility.agent_can_read(evidence_key, program_id=self.program_id)

    def _visible_graph(self, graph: MemoryGraph) -> MemoryGraph:
        nodes = tuple(node for node in graph.nodes if self._visible(node.key))
        visible = {node.key for node in nodes}
        edges = tuple(
            edge
            for edge in graph.edges
            if edge.source_key in visible and edge.target_key in visible
        )
        hidden = len(nodes) != len(graph.nodes) or len(edges) != len(graph.edges)
        return MemoryGraph(nodes=nodes, edges=edges, truncated=graph.truncated or hidden)

    def list_hypotheses(self, *, limit: int = 50):
        items = self.memory.list_hypotheses(limit=500)
        visible = tuple(
            item
            for item in items
            if self._visible(f"{MemoryNodeType.HYPOTHESIS.value}:{item.hypothesis_id}")
        )
        return visible[:limit]

    def find_similar_hypotheses(
        self,
        statement: str,
        *,
        tags: tuple[str, ...] = (),
        exclude_hypothesis_id: str = "",
        limit: int = 5,
    ):
        # Ask for a bounded superset before filtering so one hidden match does not
        # suppress visible alternatives. Phase 5.5 itself caps this query at 50.
        matches = self.memory.find_similar_hypotheses(
            statement,
            tags=tags,
            exclude_hypothesis_id=exclude_hypothesis_id,
            limit=50,
        )
        visible = tuple(
            item
            for item in matches
            if self._visible(f"{MemoryNodeType.HYPOTHESIS.value}:{item.entity_id}")
        )
        return visible[:limit]

    def traverse(
        self,
        node_key: str,
        *,
        direction: str = "both",
        max_depth: int = 6,
        max_nodes: int = 100,
    ) -> MemoryGraph:
        if not self._visible(node_key):
            raise PermissionError("requested memory evidence is not visible to this research Agent")
        graph = self.memory.store.traverse(
            node_key,
            direction=direction,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )
        return self._visible_graph(graph)

    def failures(
        self,
        *,
        hypothesis_id: str | None = None,
        experiment_id: str | None = None,
        category=None,
    ):
        items = self.memory.store.failures(
            hypothesis_id=hypothesis_id,
            experiment_id=experiment_id,
            category=category,
        )
        return tuple(
            item
            for item in items
            if self._visible(f"{MemoryNodeType.FAILURE.value}:{item.failure_id}")
        )

    def summary(
        self,
        hypothesis_id: str,
        *,
        max_nodes: int = 40,
        max_failures: int = 20,
        max_depth: int = 8,
    ) -> ResearchMemorySummary:
        if max_failures < 0 or max_failures > 200:
            raise ValueError("max_failures must be in [0, 200]")
        hypothesis_key = f"{MemoryNodeType.HYPOTHESIS.value}:{hypothesis_id}"
        if not self._visible(hypothesis_key):
            raise PermissionError("hypothesis is not visible to this research Agent")
        history = self.memory.store.hypothesis_history(hypothesis_id)
        graph = self.traverse(
            hypothesis_key,
            max_depth=max_depth,
            max_nodes=max_nodes,
        )
        all_failures = self.failures(hypothesis_id=hypothesis_id)
        failures = all_failures[:max_failures]
        counts: dict[str, int] = {}
        for node in graph.nodes:
            counts[node.node_type.value] = counts.get(node.node_type.value, 0) + 1
        return ResearchMemorySummary(
            hypothesis=history[-1],
            revision_count=len(history),
            node_counts=counts,
            graph=graph,
            failures=failures,
            truncated=graph.truncated or len(failures) < len(all_failures),
        )

    def recommend_budget(
        self,
        *,
        statement: str,
        requested_max_experiments: int,
        tags: tuple[str, ...] = (),
        hypothesis_id: str = "",
    ):
        similar = self.find_similar_hypotheses(
            statement,
            tags=tags,
            exclude_hypothesis_id=hypothesis_id,
            limit=5,
        )
        duplicate_score = similar[0].score if similar else 0.0
        threshold = self.memory.budget_policy.similarity_warn_threshold
        related_ids = tuple(match.entity_id for match in similar if match.score >= threshold)
        prior_failures = 0
        supporting_results = 0
        ids_to_check = list(related_ids)
        if hypothesis_id:
            ids_to_check.append(hypothesis_id)
        for candidate_id in sorted(set(ids_to_check)):
            prior_failures += len(self.failures(hypothesis_id=candidate_id))
            try:
                graph = self.traverse(
                    f"{MemoryNodeType.HYPOTHESIS.value}:{candidate_id}",
                    max_depth=8,
                    max_nodes=200,
                )
            except (KeyError, PermissionError):
                continue
            supporting_results += sum(
                1
                for node in graph.nodes
                if node.node_type is MemoryNodeType.RESULT
                and node.metadata.get("passed") == "true"
            )
        return self.memory.budget_policy.recommend(
            requested_max_experiments=requested_max_experiments,
            duplicate_score=duplicate_score,
            similar_hypothesis_ids=related_ids,
            prior_failure_count=prior_failures,
            supporting_result_count=supporting_results,
        )

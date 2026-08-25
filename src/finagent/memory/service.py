from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from finagent.domain.experiments import ExperimentResult, ExperimentSpec
from finagent.domain.model_registry import RegisteredModel

from .domain import (
    BudgetRecommendation,
    FailureCategory,
    FailureRecord,
    FailureStage,
    HypothesisDisposition,
    LineageEdge,
    LineageRelation,
    MemoryNode,
    MemoryNodeType,
    ResearchHypothesisRevision,
    ResearchMemorySummary,
    SimilarityMatch,
)
from .store import SQLiteResearchMemoryStore


_LATIN = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[\u3400-\u9fff]+")


def _tokens(text: str) -> frozenset[str]:
    lowered = " ".join(text.lower().split())
    tokens: set[str] = set(_LATIN.findall(lowered))
    for chunk in _CJK.findall(lowered):
        if len(chunk) == 1:
            tokens.add(chunk)
        else:
            tokens.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
    return frozenset(tokens)


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a = set(left)
    b = set(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _hypothesis_score(statement_a: str, tags_a: tuple[str, ...], statement_b: str, tags_b: tuple[str, ...]) -> float:
    text_score = _jaccard(_tokens(statement_a), _tokens(statement_b))
    if tags_a or tags_b:
        return 0.85 * text_score + 0.15 * _jaccard(tags_a, tags_b)
    return text_score


def _load_json(text: str, default):
    try:
        return json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return default


@dataclass(frozen=True, slots=True)
class EvidenceAwareBudgetPolicy:
    """Deterministic budget recommendation that can only preserve or reduce budget."""

    duplicate_block_threshold: float = 0.92
    similarity_warn_threshold: float = 0.75
    failure_penalty_threshold: int = 3

    def __post_init__(self) -> None:
        if not 0 < self.similarity_warn_threshold <= self.duplicate_block_threshold <= 1:
            raise ValueError("similarity thresholds must satisfy 0 < warn <= block <= 1")
        if self.failure_penalty_threshold < 1:
            raise ValueError("failure_penalty_threshold must be >= 1")

    def recommend(
        self,
        *,
        requested_max_experiments: int,
        duplicate_score: float,
        similar_hypothesis_ids: tuple[str, ...],
        prior_failure_count: int,
        supporting_result_count: int,
    ) -> BudgetRecommendation:
        if requested_max_experiments < 1:
            raise ValueError("requested_max_experiments must be >= 1")
        recommended = requested_max_experiments
        reasons: list[str] = []
        if duplicate_score >= self.duplicate_block_threshold:
            recommended = 0
            reasons.append("near-duplicate hypothesis should reuse existing evidence before new trials")
        elif duplicate_score >= self.similarity_warn_threshold:
            recommended = max(1, math.ceil(recommended / 2))
            reasons.append("similar prior hypothesis reduces the new-search budget")
        if recommended > 0 and prior_failure_count >= self.failure_penalty_threshold:
            penalty = min(2, prior_failure_count // self.failure_penalty_threshold)
            recommended = max(1, recommended - penalty)
            reasons.append("repeated related failures reduce the search budget")
        if supporting_result_count:
            reasons.append("historical supporting results do not expand the requested budget")
        if not reasons:
            reasons.append("no structured evidence requires reducing the requested budget")
        return BudgetRecommendation(
            requested_max_experiments=requested_max_experiments,
            recommended_max_experiments=recommended,
            duplicate_score=duplicate_score,
            similar_hypothesis_ids=similar_hypothesis_ids,
            prior_failure_count=prior_failure_count,
            supporting_result_count=supporting_result_count,
            reasons=tuple(reasons),
        )


class ResearchMemoryService:
    """Typed Phase 5.5 facade for hypothesis evolution, lineage and evidence queries."""

    def __init__(
        self,
        store: SQLiteResearchMemoryStore,
        *,
        budget_policy: EvidenceAwareBudgetPolicy | None = None,
    ) -> None:
        self.store = store
        self.budget_policy = budget_policy or EvidenceAwareBudgetPolicy()

    def create_hypothesis(
        self,
        hypothesis_id: str,
        statement: str,
        rationale: str,
        created_at: datetime,
        *,
        tags: tuple[str, ...] = (),
        metadata: dict[str, str] | None = None,
    ) -> ResearchHypothesisRevision:
        item = ResearchHypothesisRevision(
            hypothesis_id=hypothesis_id,
            revision=1,
            statement=statement,
            rationale=rationale,
            created_at=created_at,
            tags=tags,
            metadata=metadata or {},
        )
        self.store.register_hypothesis_revision(item)
        return item

    def revise_hypothesis(
        self,
        hypothesis_id: str,
        statement: str,
        rationale: str,
        created_at: datetime,
        *,
        tags: tuple[str, ...] | None = None,
        disposition: HypothesisDisposition | None = None,
        metadata: dict[str, str] | None = None,
    ) -> ResearchHypothesisRevision:
        previous = self.store.latest_hypothesis(hypothesis_id)
        item = ResearchHypothesisRevision(
            hypothesis_id=hypothesis_id,
            revision=previous.revision + 1,
            statement=statement,
            rationale=rationale,
            created_at=created_at,
            tags=previous.tags if tags is None else tags,
            disposition=previous.disposition if disposition is None else disposition,
            metadata=metadata or {},
        )
        self.store.register_hypothesis_revision(item)
        return item

    def register_generated_feature(self, hypothesis_id: str, artifact) -> MemoryNode:
        spec = artifact.spec
        node = MemoryNode(
            MemoryNodeType.FEATURE,
            artifact.digest,
            spec.name,
            artifact.generated_at,
            {
                "feature_id": spec.feature_id,
                "feature_hypothesis": spec.hypothesis,
                "input_fields": json.dumps(list(spec.input_fields), separators=(",", ":")),
                "lookback": str(spec.lookback),
                "source_digest": artifact.validation.source_digest,
                "generator_id": artifact.generator_id,
            },
        )
        self.store.register_node(node)
        self.store.register_edge(
            LineageEdge(
                f"hypothesis:{hypothesis_id}",
                node.key,
                LineageRelation.IMPLEMENTS,
                artifact.generated_at,
            )
        )
        return node

    def register_experiment(
        self,
        hypothesis_id: str,
        spec: ExperimentSpec,
        created_at: datetime,
        *,
        feature_digest: str = "",
    ) -> MemoryNode:
        node = MemoryNode(
            MemoryNodeType.EXPERIMENT,
            spec.experiment_id,
            spec.experiment_id,
            created_at,
            {
                "fingerprint": spec.fingerprint,
                "hypothesis": spec.hypothesis,
                "dataset_digest": spec.dataset.digest,
                "code_digest": spec.code.digest,
                "universe": json.dumps(sorted(asset.key for asset in spec.universe), separators=(",", ":")),
                "parameters": json.dumps(dict(spec.parameters), sort_keys=True, separators=(",", ":")),
                "seed": str(spec.seed),
            },
        )
        self.store.register_node(node)
        self.store.register_edge(
            LineageEdge(
                f"hypothesis:{hypothesis_id}",
                node.key,
                LineageRelation.TESTED_BY,
                created_at,
            )
        )
        if feature_digest:
            self.store.register_edge(
                LineageEdge(
                    f"feature:{feature_digest}",
                    node.key,
                    LineageRelation.USES,
                    created_at,
                )
            )
        return node

    def register_result(
        self,
        experiment_id: str,
        result: ExperimentResult,
        created_at: datetime,
    ) -> MemoryNode:
        node = MemoryNode(
            MemoryNodeType.RESULT,
            result.run_id,
            result.run_id,
            created_at,
            {
                "passed": "true" if result.passed else "false",
                "metrics": json.dumps(dict(result.metrics), sort_keys=True, separators=(",", ":")),
                "notes": result.notes,
                "artifacts": json.dumps(
                    [artifact.digest for artifact in result.produced_artifacts], separators=(",", ":")
                ),
            },
        )
        self.store.register_node(node)
        self.store.register_edge(
            LineageEdge(
                f"experiment:{experiment_id}",
                node.key,
                LineageRelation.PRODUCED,
                created_at,
            )
        )
        return node

    def register_model(
        self,
        model: RegisteredModel,
        *,
        source_result_id: str,
    ) -> MemoryNode:
        node = MemoryNode(
            MemoryNodeType.MODEL,
            model.model_id,
            model.model_id,
            model.created_at,
            {
                "family": model.family,
                "stage": model.stage.value,
                "artifact_digest": model.artifact.digest,
                "metrics": json.dumps(dict(model.metrics), sort_keys=True, separators=(",", ":")),
            },
        )
        self.store.register_node(node)
        self.store.register_edge(
            LineageEdge(
                f"result:{source_result_id}",
                node.key,
                LineageRelation.PROMOTED_TO,
                model.created_at,
            )
        )
        return node

    def register_operational_outcome(
        self,
        *,
        source_key: str,
        outcome_type: MemoryNodeType,
        outcome_id: str,
        label: str,
        observed_at: datetime,
        metrics: dict[str, float | int | str] | None = None,
        relation: LineageRelation = LineageRelation.INFORMED,
    ) -> MemoryNode:
        allowed = {
            MemoryNodeType.PORTFOLIO_SNAPSHOT,
            MemoryNodeType.PAPER_ORDER,
            MemoryNodeType.PAPER_FILL,
            MemoryNodeType.RECONCILIATION,
            MemoryNodeType.SHADOW_REPORT,
        }
        if outcome_type not in allowed:
            raise ValueError("outcome_type is not an operational evidence node")
        node = MemoryNode(
            outcome_type,
            outcome_id,
            label,
            observed_at,
            {str(k): str(v) for k, v in (metrics or {}).items()},
        )
        self.store.register_node(node)
        self.store.register_edge(LineageEdge(source_key, node.key, relation, observed_at))
        return node

    def record_failure(
        self,
        *,
        failure_id: str,
        category: FailureCategory,
        stage: FailureStage,
        summary: str,
        observed_at: datetime,
        hypothesis_id: str = "",
        experiment_id: str = "",
        related_node_keys: tuple[str, ...] = (),
        metadata: dict[str, str] | None = None,
    ) -> FailureRecord:
        item = FailureRecord(
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
        self.store.register_failure(item)
        return item

    def list_hypotheses(self, *, limit: int = 50) -> tuple[ResearchHypothesisRevision, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be in [1, 500]")
        return self.store.list_latest_hypotheses()[:limit]

    def find_similar_hypotheses(
        self,
        statement: str,
        *,
        tags: tuple[str, ...] = (),
        exclude_hypothesis_id: str = "",
        limit: int = 5,
    ) -> tuple[SimilarityMatch, ...]:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be in [1, 50]")
        matches: list[SimilarityMatch] = []
        normalized_tags = tuple(sorted({tag.strip().lower() for tag in tags if tag.strip()}))
        for item in self.store.list_latest_hypotheses():
            if item.hypothesis_id == exclude_hypothesis_id:
                continue
            score = _hypothesis_score(statement, normalized_tags, item.statement, item.tags)
            matches.append(
                SimilarityMatch(item.hypothesis_id, score, "deterministic text/tag Jaccard similarity")
            )
        matches.sort(key=lambda item: (-item.score, item.entity_id))
        return tuple(matches[:limit])

    def find_similar_experiments(
        self,
        spec: ExperimentSpec,
        *,
        limit: int = 5,
    ) -> tuple[SimilarityMatch, ...]:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be in [1, 50]")
        matches: list[SimilarityMatch] = []
        target_universe = {asset.key for asset in spec.universe}
        target_parameters = {f"{key}={value!r}" for key, value in spec.parameters.items()}
        for node in self.store.list_nodes(MemoryNodeType.EXPERIMENT):
            meta = node.metadata
            if meta.get("fingerprint") == spec.fingerprint:
                score = 1.0
            else:
                hypothesis_score = _jaccard(_tokens(spec.hypothesis), _tokens(meta.get("hypothesis", "")))
                universe_score = _jaccard(target_universe, _load_json(meta.get("universe", "[]"), []))
                prior_parameters = _load_json(meta.get("parameters", "{}"), {})
                parameter_score = _jaccard(
                    target_parameters,
                    {f"{key}={value!r}" for key, value in prior_parameters.items()},
                )
                dataset_score = 1.0 if meta.get("dataset_digest") == spec.dataset.digest else 0.0
                code_score = 1.0 if meta.get("code_digest") == spec.code.digest else 0.0
                score = (
                    0.40 * hypothesis_score
                    + 0.20 * universe_score
                    + 0.15 * parameter_score
                    + 0.15 * dataset_score
                    + 0.10 * code_score
                )
            matches.append(SimilarityMatch(node.node_id, score, "experiment signature similarity"))
        matches.sort(key=lambda item: (-item.score, item.entity_id))
        return tuple(matches[:limit])

    def find_similar_features(self, artifact, *, limit: int = 5) -> tuple[SimilarityMatch, ...]:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be in [1, 50]")
        matches: list[SimilarityMatch] = []
        for node in self.store.list_nodes(MemoryNodeType.FEATURE):
            if node.node_id == artifact.digest:
                continue
            fields = tuple(_load_json(node.metadata.get("input_fields", "[]"), []))
            prior_lookback = int(node.metadata.get("lookback", "1"))
            lookback_score = min(prior_lookback, artifact.spec.lookback) / max(prior_lookback, artifact.spec.lookback)
            score = (
                0.60
                * _hypothesis_score(
                    artifact.spec.hypothesis,
                    (),
                    node.metadata.get("feature_hypothesis", ""),
                    (),
                )
                + 0.25 * _jaccard(artifact.spec.input_fields, fields)
                + 0.15 * lookback_score
            )
            matches.append(SimilarityMatch(node.node_id, score, "feature hypothesis/input/lookback similarity"))
        matches.sort(key=lambda item: (-item.score, item.entity_id))
        return tuple(matches[:limit])

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
        history = self.store.hypothesis_history(hypothesis_id)
        graph = self.store.traverse(
            f"hypothesis:{hypothesis_id}",
            max_depth=max_depth,
            max_nodes=max_nodes,
        )
        all_failures = self.store.failures(hypothesis_id=hypothesis_id)
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
    ) -> BudgetRecommendation:
        similar = self.find_similar_hypotheses(
            statement,
            tags=tags,
            exclude_hypothesis_id=hypothesis_id,
            limit=5,
        )
        duplicate_score = similar[0].score if similar else 0.0
        related_ids = tuple(match.entity_id for match in similar if match.score >= self.budget_policy.similarity_warn_threshold)
        prior_failures = 0
        supporting_results = 0
        ids_to_check = list(related_ids)
        if hypothesis_id:
            ids_to_check.append(hypothesis_id)
        for candidate_id in sorted(set(ids_to_check)):
            prior_failures += len(self.store.failures(hypothesis_id=candidate_id))
            try:
                graph = self.store.traverse(f"hypothesis:{candidate_id}", max_depth=8, max_nodes=200)
            except KeyError:
                continue
            supporting_results += sum(
                1
                for node in graph.nodes
                if node.node_type is MemoryNodeType.RESULT and node.metadata.get("passed") == "true"
            )
        return self.budget_policy.recommend(
            requested_max_experiments=requested_max_experiments,
            duplicate_score=duplicate_score,
            similar_hypothesis_ids=related_ids,
            prior_failure_count=prior_failures,
            supporting_result_count=supporting_results,
        )

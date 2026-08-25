from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping

from finagent.domain._validation import freeze_mapping, require_aware_datetime, require_non_empty


class HypothesisDisposition(str, Enum):
    OPEN = "open"
    SUPPORTED = "supported"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    RETIRED = "retired"


class MemoryNodeType(str, Enum):
    HYPOTHESIS = "hypothesis"
    FEATURE = "feature"
    ARTIFACT = "artifact"
    EXPERIMENT = "experiment"
    RESULT = "result"
    MODEL = "model"
    PORTFOLIO_SNAPSHOT = "portfolio_snapshot"
    PAPER_ORDER = "paper_order"
    PAPER_FILL = "paper_fill"
    RECONCILIATION = "reconciliation"
    SHADOW_REPORT = "shadow_report"
    FAILURE = "failure"


class LineageRelation(str, Enum):
    IMPLEMENTS = "implements"
    TESTED_BY = "tested_by"
    USES = "uses"
    PRODUCED = "produced"
    PROMOTED_TO = "promoted_to"
    INFORMED = "informed"
    EXECUTED_AS = "executed_as"
    FILLED_BY = "filled_by"
    RECONCILED_BY = "reconciled_by"
    SHADOWED_BY = "shadowed_by"
    FAILED_AS = "failed_as"


class FailureCategory(str, Enum):
    DATA = "data"
    LEAKAGE = "leakage"
    STATISTICAL = "statistical"
    MODEL_FIT = "model_fit"
    NUMERICAL = "numerical"
    COST = "cost"
    TURNOVER = "turnover"
    LIQUIDITY = "liquidity"
    RISK = "risk"
    EXECUTION = "execution"
    RECONCILIATION = "reconciliation"
    OPERATIONAL = "operational"
    POLICY = "policy"
    DUPLICATE = "duplicate"
    UNKNOWN = "unknown"


class FailureStage(str, Enum):
    HYPOTHESIS = "hypothesis"
    FEATURE_GENERATION = "feature_generation"
    MATERIALIZATION = "materialization"
    EXPERIMENT = "experiment"
    VALIDATION = "validation"
    MODEL = "model"
    PORTFOLIO = "portfolio"
    EXECUTION = "execution"
    RECONCILIATION = "reconciliation"
    OPERATIONAL = "operational"


def _normalized_tags(values: tuple[str, ...]) -> tuple[str, ...]:
    tags = tuple(sorted({require_non_empty(value, "tag").strip().lower() for value in values}))
    return tags


@dataclass(frozen=True, slots=True)
class ResearchHypothesisRevision:
    hypothesis_id: str
    revision: int
    statement: str
    rationale: str
    created_at: datetime
    tags: tuple[str, ...] = ()
    disposition: HypothesisDisposition = HypothesisDisposition.OPEN
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "hypothesis_id", require_non_empty(self.hypothesis_id, "hypothesis_id"))
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("revision must be an integer >= 1")
        object.__setattr__(self, "statement", require_non_empty(self.statement, "statement"))
        object.__setattr__(self, "rationale", require_non_empty(self.rationale, "rationale"))
        object.__setattr__(self, "created_at", require_aware_datetime(self.created_at, "created_at"))
        object.__setattr__(self, "tags", _normalized_tags(self.tags))
        object.__setattr__(self, "metadata", freeze_mapping({str(k): str(v) for k, v in self.metadata.items()}))

    @property
    def fingerprint(self) -> str:
        payload = {
            "statement": " ".join(self.statement.lower().split()),
            "rationale": " ".join(self.rationale.lower().split()),
            "tags": list(self.tags),
            "disposition": self.disposition.value,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class MemoryNode:
    node_type: MemoryNodeType
    node_id: str
    label: str
    created_at: datetime
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", require_non_empty(self.node_id, "node_id"))
        object.__setattr__(self, "label", require_non_empty(self.label, "label"))
        object.__setattr__(self, "created_at", require_aware_datetime(self.created_at, "created_at"))
        object.__setattr__(self, "metadata", freeze_mapping({str(k): str(v) for k, v in self.metadata.items()}))

    @property
    def key(self) -> str:
        return f"{self.node_type.value}:{self.node_id}"


@dataclass(frozen=True, slots=True)
class LineageEdge:
    source_key: str
    target_key: str
    relation: LineageRelation
    created_at: datetime
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_key", require_non_empty(self.source_key, "source_key"))
        object.__setattr__(self, "target_key", require_non_empty(self.target_key, "target_key"))
        if self.source_key == self.target_key:
            raise ValueError("lineage edges cannot be self-referential")
        object.__setattr__(self, "created_at", require_aware_datetime(self.created_at, "created_at"))
        object.__setattr__(self, "metadata", freeze_mapping({str(k): str(v) for k, v in self.metadata.items()}))

    @property
    def edge_id(self) -> str:
        payload = f"{self.source_key}|{self.relation.value}|{self.target_key}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FailureRecord:
    failure_id: str
    category: FailureCategory
    stage: FailureStage
    summary: str
    observed_at: datetime
    hypothesis_id: str = ""
    experiment_id: str = ""
    related_node_keys: tuple[str, ...] = ()
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "failure_id", require_non_empty(self.failure_id, "failure_id"))
        object.__setattr__(self, "summary", require_non_empty(self.summary, "summary"))
        object.__setattr__(self, "observed_at", require_aware_datetime(self.observed_at, "observed_at"))
        object.__setattr__(self, "hypothesis_id", self.hypothesis_id.strip())
        object.__setattr__(self, "experiment_id", self.experiment_id.strip())
        keys = tuple(require_non_empty(value, "related_node_key") for value in self.related_node_keys)
        if len(keys) != len(set(keys)):
            raise ValueError("related_node_keys cannot contain duplicates")
        object.__setattr__(self, "related_node_keys", keys)
        object.__setattr__(self, "metadata", freeze_mapping({str(k): str(v) for k, v in self.metadata.items()}))


@dataclass(frozen=True, slots=True)
class SimilarityMatch:
    entity_id: str
    score: float
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", require_non_empty(self.entity_id, "entity_id"))
        if not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("similarity score must be in [0, 1]")
        object.__setattr__(self, "score", float(self.score))
        object.__setattr__(self, "reason", require_non_empty(self.reason, "reason"))


@dataclass(frozen=True, slots=True)
class MemoryGraph:
    nodes: tuple[MemoryNode, ...]
    edges: tuple[LineageEdge, ...]
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class BudgetRecommendation:
    requested_max_experiments: int
    recommended_max_experiments: int
    duplicate_score: float
    similar_hypothesis_ids: tuple[str, ...]
    prior_failure_count: int
    supporting_result_count: int
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.requested_max_experiments < 1:
            raise ValueError("requested_max_experiments must be >= 1")
        if not 0 <= self.recommended_max_experiments <= self.requested_max_experiments:
            raise ValueError("recommended budget must be between zero and the requested budget")
        if not 0.0 <= self.duplicate_score <= 1.0:
            raise ValueError("duplicate_score must be in [0, 1]")
        if self.prior_failure_count < 0 or self.supporting_result_count < 0:
            raise ValueError("evidence counts must be non-negative")


@dataclass(frozen=True, slots=True)
class ResearchMemorySummary:
    hypothesis: ResearchHypothesisRevision
    revision_count: int
    node_counts: Mapping[str, int]
    graph: MemoryGraph
    failures: tuple[FailureRecord, ...]
    truncated: bool

    def __post_init__(self) -> None:
        if self.revision_count < 1:
            raise ValueError("revision_count must be >= 1")
        object.__setattr__(self, "node_counts", freeze_mapping({str(k): int(v) for k, v in self.node_counts.items()}))

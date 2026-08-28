from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any


class EvidenceContractError(ValueError):
    """Raised when an authoritative artifact cannot be projected safely."""


class EvidenceAuthority(str, Enum):
    AUTHORITATIVE = "authoritative"
    DERIVED = "derived"
    DIAGNOSTIC = "diagnostic"


class EvidenceStage(str, Enum):
    DATA_CERTIFICATION = "data_certification"
    SYSTEM_SMOKE = "system_smoke"
    A2_FACTOR_ACCEPTANCE = "a2_factor_acceptance"
    A2P6_ROBUST_RESEARCH = "a2p6_robust_research"
    A3_EXECUTION_SMOKE = "a3_execution_smoke"
    A4_PORTFOLIO_VALIDATION = "a4_portfolio_validation"
    AGENT_RUN = "agent_run"
    UNKNOWN = "unknown"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _payload_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(dict(value)).encode()).hexdigest()


def _text(value: object, *, required: bool = False, name: str = "value") -> str:
    result = "" if value is None else str(value).strip()
    if required and not result:
        raise EvidenceContractError(f"{name} must be non-empty")
    return result


def _mapping(value: object, name: str, *, required: bool = True) -> Mapping[str, Any]:
    if value is None and not required:
        return {}
    if not isinstance(value, Mapping):
        raise EvidenceContractError(f"{name} must be a JSON object")
    return value


def _sequence(value: object, name: str, *, required: bool = True) -> Sequence[Any]:
    if value is None and not required:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise EvidenceContractError(f"{name} must be a JSON array")
    return value


def _number(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceContractError(f"expected finite number, got {value!r}") from exc
    if not math.isfinite(result):
        raise EvidenceContractError(f"expected finite number, got {value!r}")
    return result


def _integer(value: object, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceContractError(f"expected integer, got {value!r}") from exc


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    evidence_id: str
    evidence_type: str
    schema_version: str
    stage: EvidenceStage
    authority: EvidenceAuthority
    artifact_digest: str
    source_uri: str = ""
    parent_ids: tuple[str, ...] = ()
    program_id: str = ""
    spec_id: str = ""
    data_version: str = ""
    git_sha: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("evidence_id", "evidence_type", "schema_version", "artifact_digest"):
            if not _text(getattr(self, name)):
                raise EvidenceContractError(f"EvidenceRef.{name} must be non-empty")
        parents = tuple(_text(value, required=True, name="parent_id") for value in self.parent_ids)
        if self.evidence_id in parents or len(set(parents)) != len(parents):
            raise EvidenceContractError("EvidenceRef parent_ids must be unique and non-self")
        object.__setattr__(self, "parent_ids", parents)
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "schema_version": self.schema_version,
            "stage": self.stage.value,
            "authority": self.authority.value,
            "artifact_digest": self.artifact_digest,
            "source_uri": self.source_uri,
            "parent_ids": list(self.parent_ids),
            "program_id": self.program_id,
            "spec_id": self.spec_id,
            "data_version": self.data_version,
            "git_sha": self.git_sha,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class LineageNode:
    evidence_id: str
    evidence_type: str
    stage: EvidenceStage
    authority: EvidenceAuthority
    status: str = ""
    label: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "stage": self.stage.value,
            "authority": self.authority.value,
            "status": self.status,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class LineageEdge:
    parent_id: str
    child_id: str
    relation: str = "depends_on"

    def __post_init__(self) -> None:
        if not self.parent_id or not self.child_id or self.parent_id == self.child_id:
            raise EvidenceContractError("invalid lineage edge")
        if not self.relation:
            raise EvidenceContractError("lineage relation must be non-empty")

    def to_dict(self) -> dict[str, str]:
        return {
            "parent_id": self.parent_id,
            "child_id": self.child_id,
            "relation": self.relation,
        }


@dataclass(frozen=True, slots=True)
class LineageGraph:
    nodes: tuple[LineageNode, ...]
    edges: tuple[LineageEdge, ...]

    def __post_init__(self) -> None:
        ids = {node.evidence_id for node in self.nodes}
        if not ids or len(ids) != len(self.nodes):
            raise EvidenceContractError("lineage nodes must be unique and non-empty")
        if any(edge.parent_id not in ids or edge.child_id not in ids for edge in self.edges):
            raise EvidenceContractError("lineage edge references an unknown node")
        pairs = {(edge.parent_id, edge.child_id, edge.relation) for edge in self.edges}
        if len(pairs) != len(self.edges):
            raise EvidenceContractError("lineage edges must be unique")
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in ids}
        for edge in self.edges:
            adjacency[edge.parent_id].append(edge.child_id)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise EvidenceContractError("lineage graph must be acyclic")
            if node_id in visited:
                return
            visiting.add(node_id)
            for child in adjacency[node_id]:
                visit(child)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in sorted(ids):
            visit(node_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }


@dataclass(frozen=True, slots=True)
class FoldEvidence:
    fold_id: str
    train_start: str = ""
    train_end: str = ""
    test_start: str = ""
    test_end: str = ""
    metrics: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.fold_id:
            raise EvidenceContractError("fold_id must be non-empty")
        metrics = {str(key): _number(value) for key, value in self.metrics.items()}
        object.__setattr__(self, "metrics", MappingProxyType(metrics))

    def to_dict(self) -> dict[str, object]:
        return {
            "fold_id": self.fold_id,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True, slots=True)
class FactorEvidence:
    feature_id: str
    feature_digest: str
    hypothesis: str = ""
    selected: bool = False
    weight: float = 0.0
    direction: int = 0
    status: str = ""
    reason_codes: tuple[str, ...] = ()
    metrics: Mapping[str, float] = field(default_factory=dict)
    folds: tuple[FoldEvidence, ...] = ()

    def __post_init__(self) -> None:
        if not self.feature_id or not self.feature_digest:
            raise EvidenceContractError("factor evidence requires id and digest")
        if self.direction not in {-1, 0, 1}:
            raise EvidenceContractError("factor direction must be -1, 0 or 1")
        if not math.isfinite(float(self.weight)) or self.weight < 0:
            raise EvidenceContractError("factor weight must be finite and non-negative")
        reasons = tuple(_text(value, required=True, name="reason_code") for value in self.reason_codes)
        metrics = {str(key): _number(value) for key, value in self.metrics.items()}
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "metrics", MappingProxyType(metrics))

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "feature_digest": self.feature_digest,
            "hypothesis": self.hypothesis,
            "selected": self.selected,
            "weight": self.weight,
            "direction": self.direction,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "metrics": dict(self.metrics),
            "folds": [fold.to_dict() for fold in self.folds],
        }


@dataclass(frozen=True, slots=True)
class PortfolioPointEvidence:
    session_date: str
    net_nav: float
    gross_nav: float
    net_return: float
    gross_return: float
    fees: float = 0.0
    slippage: float = 0.0
    one_way_turnover: float = 0.0
    implementation_shortfall: float = 0.0
    maximum_ex_post_participation: float = 0.0
    desired_order_count: int = 0
    order_count: int = 0
    fill_count: int = 0
    rejected_order_count: int = 0
    cash_fallback: bool = False

    def __post_init__(self) -> None:
        if not self.session_date:
            raise EvidenceContractError("portfolio point requires session_date")
        for name in (
            "net_nav",
            "gross_nav",
            "net_return",
            "gross_return",
            "fees",
            "slippage",
            "one_way_turnover",
            "implementation_shortfall",
            "maximum_ex_post_participation",
        ):
            _number(getattr(self, name))
        if self.net_nav <= 0 or self.gross_nav <= 0:
            raise EvidenceContractError("portfolio NAV must be positive")
        for name in (
            "desired_order_count",
            "order_count",
            "fill_count",
            "rejected_order_count",
        ):
            if int(getattr(self, name)) < 0:
                raise EvidenceContractError("portfolio order counts must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "session_date": self.session_date,
            "net_nav": self.net_nav,
            "gross_nav": self.gross_nav,
            "net_return": self.net_return,
            "gross_return": self.gross_return,
            "fees": self.fees,
            "slippage": self.slippage,
            "one_way_turnover": self.one_way_turnover,
            "implementation_shortfall": self.implementation_shortfall,
            "maximum_ex_post_participation": self.maximum_ex_post_participation,
            "desired_order_count": self.desired_order_count,
            "order_count": self.order_count,
            "fill_count": self.fill_count,
            "rejected_order_count": self.rejected_order_count,
            "cash_fallback": self.cash_fallback,
        }


@dataclass(frozen=True, slots=True)
class PortfolioEvidence:
    metrics: Mapping[str, float]
    points: tuple[PortfolioPointEvidence, ...] = ()
    fold_metrics: tuple[FoldEvidence, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "metrics",
            MappingProxyType({str(key): _number(value) for key, value in self.metrics.items()}),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "metrics": dict(self.metrics),
            "points": [point.to_dict() for point in self.points],
            "fold_metrics": [fold.to_dict() for fold in self.fold_metrics],
        }


@dataclass(frozen=True, slots=True)
class ExecutionEvidence:
    desired_order_count: int = 0
    order_count: int = 0
    fill_count: int = 0
    rejected_order_count: int = 0
    rejected_order_ratio: float = 0.0
    cash_fallback_count: int = 0
    cash_fallback_ratio: float = 0.0
    reason_counts: Mapping[str, int] = field(default_factory=dict)
    costs: Mapping[str, float] = field(default_factory=dict)
    maximum_ex_post_participation: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "desired_order_count",
            "order_count",
            "fill_count",
            "rejected_order_count",
            "cash_fallback_count",
        ):
            if int(getattr(self, name)) < 0:
                raise EvidenceContractError("execution counts must be non-negative")
        for name in (
            "rejected_order_ratio",
            "cash_fallback_ratio",
            "maximum_ex_post_participation",
        ):
            value = _number(getattr(self, name))
            if value < 0:
                raise EvidenceContractError("execution ratios must be non-negative")
        object.__setattr__(
            self,
            "reason_counts",
            MappingProxyType({str(key): int(value) for key, value in self.reason_counts.items()}),
        )
        object.__setattr__(
            self,
            "costs",
            MappingProxyType({str(key): _number(value) for key, value in self.costs.items()}),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "desired_order_count": self.desired_order_count,
            "order_count": self.order_count,
            "fill_count": self.fill_count,
            "rejected_order_count": self.rejected_order_count,
            "rejected_order_ratio": self.rejected_order_ratio,
            "cash_fallback_count": self.cash_fallback_count,
            "cash_fallback_ratio": self.cash_fallback_ratio,
            "reason_counts": dict(self.reason_counts),
            "costs": dict(self.costs),
            "maximum_ex_post_participation": self.maximum_ex_post_participation,
        }


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    root: EvidenceRef
    refs: tuple[EvidenceRef, ...]
    system_status: str
    research_status: str
    reserve_status: str
    promotion_eligible: bool
    factors: tuple[FactorEvidence, ...] = ()
    portfolio: PortfolioEvidence | None = None
    execution: ExecutionEvidence | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.system_status or not self.research_status or not self.reserve_status:
            raise EvidenceContractError("evidence bundle statuses must be non-empty")
        ids = {ref.evidence_id for ref in self.refs}
        if len(ids) != len(self.refs) or self.root.evidence_id not in ids:
            raise EvidenceContractError("bundle refs must be unique and contain root")
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        self.lineage()

    def ref(self, evidence_id: str) -> EvidenceRef:
        for value in self.refs:
            if value.evidence_id == evidence_id:
                return value
        raise KeyError(evidence_id)

    def lineage(self) -> LineageGraph:
        statuses = {self.root.evidence_id: self.research_status}
        nodes = tuple(
            LineageNode(
                evidence_id=ref.evidence_id,
                evidence_type=ref.evidence_type,
                stage=ref.stage,
                authority=ref.authority,
                status=statuses.get(ref.evidence_id, _text(ref.metadata.get("status"))),
                label=_text(ref.metadata.get("label"), required=False),
            )
            for ref in self.refs
        )
        edges = tuple(
            LineageEdge(parent_id=parent, child_id=ref.evidence_id)
            for ref in self.refs
            for parent in ref.parent_ids
        )
        return LineageGraph(nodes=nodes, edges=edges)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.visualization.evidence-bundle.v1",
            "root": self.root.to_dict(),
            "refs": [ref.to_dict() for ref in self.refs],
            "system_status": self.system_status,
            "research_status": self.research_status,
            "reserve_status": self.reserve_status,
            "promotion_eligible": self.promotion_eligible,
            "factors": [factor.to_dict() for factor in self.factors],
            "portfolio": self.portfolio.to_dict() if self.portfolio is not None else None,
            "execution": self.execution.to_dict() if self.execution is not None else None,
            "lineage": self.lineage().to_dict(),
            "metadata": dict(self.metadata),
        }


def _ref(
    *,
    evidence_id: str,
    evidence_type: str,
    schema_version: str,
    stage: EvidenceStage,
    digest: str,
    source_uri: str,
    parent_ids: Sequence[str] = (),
    program_id: str = "",
    spec_id: str = "",
    data_version: str = "",
    git_sha: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> EvidenceRef:
    return EvidenceRef(
        evidence_id=evidence_id,
        evidence_type=evidence_type,
        schema_version=schema_version,
        stage=stage,
        authority=EvidenceAuthority.AUTHORITATIVE,
        artifact_digest=digest,
        source_uri=source_uri,
        parent_ids=tuple(parent_ids),
        program_id=program_id,
        spec_id=spec_id,
        data_version=data_version,
        git_sha=git_sha,
        metadata=metadata or {},
    )


def _factor_acceptance_bundle(
    payload: Mapping[str, Any],
    *,
    source_uri: str,
    git_sha: str,
) -> EvidenceBundle:
    schema = _text(payload.get("schema_version"), required=True, name="schema_version")
    root_id = _text(payload.get("acceptance_id"), required=True, name="acceptance_id")
    data_version = _text(payload.get("data_version"), required=True, name="data_version")
    outcome = _mapping(payload.get("research_outcome"), "research_outcome", required=False)
    reserve = _mapping(payload.get("reserve"), "reserve", required=False)
    universe = _mapping(payload.get("candidate_universe"), "candidate_universe", required=False)
    frozen = _mapping(payload.get("frozen_ensemble"), "frozen_ensemble", required=False)
    development = _mapping(payload.get("development_report"), "development_report")
    validation = _mapping(payload.get("validation_report"), "validation_report")
    dev_candidates = {
        _text(_mapping(value, "development candidate").get("feature_digest")): _mapping(
            value, "development candidate"
        )
        for value in _sequence(development.get("candidates"), "development candidates")
    }
    val_candidates = {
        _text(_mapping(value, "validation candidate").get("feature_digest")): _mapping(
            value, "validation candidate"
        )
        for value in _sequence(validation.get("candidates"), "validation candidates")
    }
    components = {
        _text(_mapping(value, "ensemble component").get("feature_digest")): _mapping(
            value, "ensemble component"
        )
        for value in _sequence(frozen.get("components"), "frozen components", required=False)
    }
    factors: list[FactorEvidence] = []
    denominator = _sequence(payload.get("candidate_denominator"), "candidate_denominator")
    for raw in denominator:
        entry = _mapping(raw, "candidate denominator entry")
        digest = _text(entry.get("feature_digest"), required=True, name="feature_digest")
        dev = dev_candidates.get(digest, {})
        val = val_candidates.get(digest, {})
        dev_primary = _primary_metrics(dev)
        val_primary = _primary_metrics(val)
        dev_quant = _mapping(dev.get("quantile_diagnostics"), "dev quantile", required=False)
        val_quant = _mapping(val.get("quantile_diagnostics"), "val quantile", required=False)
        component = components.get(digest, {})
        factors.append(
            FactorEvidence(
                feature_id=_text(entry.get("feature_id"), required=True, name="feature_id"),
                feature_digest=digest,
                hypothesis=_text(entry.get("hypothesis")),
                selected=bool(component),
                weight=_number(component.get("weight")),
                direction=_integer(component.get("direction"), 0),
                status="SELECTED" if component else "CANDIDATE",
                metrics={
                    "development_rank_ic": _number(dev_primary.get("rank_ic")),
                    "development_rank_icir": _number(dev_primary.get("rank_icir")),
                    "validation_rank_ic": _number(val_primary.get("rank_ic")),
                    "validation_rank_icir": _number(val_primary.get("rank_icir")),
                    "development_long_short_sharpe": _number(dev_quant.get("long_short_sharpe")),
                    "validation_long_short_sharpe": _number(val_quant.get("long_short_sharpe")),
                    "development_coverage": _number(dev.get("coverage")),
                    "validation_coverage": _number(val.get("coverage")),
                },
            )
        )
    refs: list[EvidenceRef] = []
    universe_id = _text(universe.get("selection_id"))
    if universe_id:
        refs.append(
            _ref(
                evidence_id=universe_id,
                evidence_type="candidate_universe",
                schema_version=_text(universe.get("schema_version")) or "unknown",
                stage=EvidenceStage.A2_FACTOR_ACCEPTANCE,
                digest=universe_id,
                source_uri=source_uri,
                data_version=data_version,
                git_sha=git_sha,
                metadata={"label": "Candidate universe"},
            )
        )
    ensemble_id = _text(frozen.get("ensemble_id"))
    if ensemble_id:
        refs.append(
            _ref(
                evidence_id=ensemble_id,
                evidence_type="frozen_factor_ensemble",
                schema_version=_text(frozen.get("schema_version")) or "unknown",
                stage=EvidenceStage.A2_FACTOR_ACCEPTANCE,
                digest=ensemble_id,
                source_uri=source_uri,
                parent_ids=(universe_id,) if universe_id else (),
                data_version=data_version,
                git_sha=git_sha,
                metadata={"label": "Frozen factor ensemble"},
            )
        )
    root_parents = tuple(value for value in (ensemble_id, universe_id) if value)
    root = _ref(
        evidence_id=root_id,
        evidence_type="ashare_factor_research_acceptance",
        schema_version=schema,
        stage=EvidenceStage.A2_FACTOR_ACCEPTANCE,
        digest=_payload_digest(payload),
        source_uri=source_uri,
        parent_ids=root_parents,
        data_version=data_version,
        git_sha=git_sha,
        metadata={"label": "A2 factor acceptance"},
    )
    refs.append(root)
    return EvidenceBundle(
        root=root,
        refs=tuple(refs),
        system_status=_system_status(payload),
        research_status=_text(outcome.get("status")) or "LEGACY_REPORT_NO_RESEARCH_VERDICT",
        reserve_status=_text(reserve.get("status")) or "unknown",
        promotion_eligible=bool(outcome.get("promotion_eligible", False)),
        factors=tuple(factors),
        metadata={"mode": _text(payload.get("mode")), "source_schema": schema},
    )


def _primary_metrics(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    label = _text(candidate.get("primary_label"))
    horizons = _mapping(candidate.get("horizon_diagnostics"), "horizons", required=False)
    if label and label in horizons:
        return _mapping(horizons[label], f"horizon {label}")
    if horizons:
        return _mapping(next(iter(horizons.values())), "primary horizon")
    return {}


def _robust_program_bundle(
    payload: Mapping[str, Any],
    *,
    source_uri: str,
    git_sha: str,
) -> EvidenceBundle:
    schema = _text(payload.get("schema_version"), required=True, name="schema_version")
    root_id = _text(payload.get("program_result_id"), required=True, name="program_result_id")
    program = _mapping(payload.get("program_spec"), "program_spec")
    program_id = _text(program.get("program_id"), required=True, name="program_id")
    spec_id = _text(program.get("spec_id"), required=True, name="spec_id")
    data_version = _text(payload.get("data_version"), required=True, name="data_version")
    walk_forward = _mapping(payload.get("walk_forward_report"), "walk_forward_report")
    gate = _mapping(payload.get("gate_report"), "gate_report")
    selection = _mapping(payload.get("frozen_selection"), "frozen_selection")
    reserve = _mapping(payload.get("reserve"), "reserve")
    outcome = _mapping(payload.get("research_outcome"), "research_outcome")
    denominator = {
        _text(_mapping(value, "candidate").get("feature_digest")): _mapping(value, "candidate")
        for value in _sequence(payload.get("candidate_denominator"), "candidate_denominator")
    }
    gates = {
        _text(_mapping(value, "gate candidate").get("feature_digest")): _mapping(
            value, "gate candidate"
        )
        for value in _sequence(gate.get("candidates"), "gate candidates")
    }
    components = {
        _text(_mapping(value, "selection component").get("feature_digest")): _mapping(
            value, "selection component"
        )
        for value in _sequence(selection.get("components"), "selection components", required=False)
    }
    factors: list[FactorEvidence] = []
    for raw in _sequence(walk_forward.get("candidates"), "walk-forward candidates"):
        candidate = _mapping(raw, "walk-forward candidate")
        digest = _text(candidate.get("feature_digest"), required=True, name="feature_digest")
        entry = denominator.get(digest, {})
        evaluation = gates.get(digest, {})
        component = components.get(digest, {})
        hac = _mapping(candidate.get("hac"), "candidate hac", required=False)
        bootstrap = _mapping(candidate.get("block_bootstrap"), "candidate bootstrap", required=False)
        fold_evidence = tuple(
            FoldEvidence(
                fold_id=_text(fold.get("fold_id"), required=True, name="fold_id"),
                metrics={
                    "train_rank_ic": _number(fold.get("train_rank_ic")),
                    "train_rank_icir": _number(fold.get("train_rank_icir")),
                    "test_rank_ic": _number(fold.get("test_rank_ic")),
                    "test_rank_icir": _number(fold.get("test_rank_icir")),
                    "test_long_short_sharpe": _number(fold.get("test_long_short_sharpe")),
                    "coverage": _number(fold.get("coverage")),
                    "turnover": _number(fold.get("mean_one_way_turnover")),
                },
            )
            for fold in (
                _mapping(value, "candidate fold")
                for value in _sequence(candidate.get("folds"), "candidate folds")
            )
        )
        factors.append(
            FactorEvidence(
                feature_id=_text(candidate.get("feature_id"), required=True, name="feature_id"),
                feature_digest=digest,
                hypothesis=_text(entry.get("hypothesis")),
                selected=bool(component),
                weight=_number(component.get("weight")),
                direction=_integer(component.get("direction"), _integer(candidate.get("dominant_direction"), 0)),
                status="PASS" if bool(evaluation.get("passed")) else "FAIL",
                reason_codes=tuple(
                    _text(value, required=True, name="reason_code")
                    for value in _sequence(
                        evaluation.get("reason_codes"),
                        "gate reason codes",
                        required=False,
                    )
                ),
                metrics={
                    "pooled_rank_ic": _number(candidate.get("pooled_rank_ic")),
                    "pooled_rank_icir": _number(candidate.get("pooled_rank_icir")),
                    "mean_fold_rank_icir": _number(candidate.get("mean_fold_rank_icir")),
                    "worst_fold_rank_icir": _number(candidate.get("worst_fold_rank_icir")),
                    "positive_fold_ratio": _number(candidate.get("positive_fold_ratio")),
                    "direction_consistency": _number(candidate.get("direction_consistency")),
                    "mean_fold_long_short_sharpe": _number(candidate.get("mean_fold_long_short_sharpe")),
                    "coverage_mean": _number(candidate.get("coverage_mean")),
                    "coverage_min": _number(candidate.get("coverage_min")),
                    "turnover": _number(candidate.get("mean_one_way_turnover")),
                    "hac_pvalue": _number(hac.get("raw_pvalue"), 1.0),
                    "holm_pvalue": _number(hac.get("holm_adjusted_pvalue"), 1.0),
                    "bh_qvalue": _number(hac.get("bh_qvalue"), 1.0),
                    "bootstrap_pvalue": _number(bootstrap.get("pvalue"), 1.0),
                },
                folds=fold_evidence,
            )
        )
    walk_id = _text(walk_forward.get("report_id"), required=True, name="walk_forward.report_id")
    gate_id = _text(gate.get("gate_report_id"), required=True, name="gate_report_id")
    selection_id = _text(selection.get("selection_id"), required=True, name="selection_id")
    refs = [
        _ref(
            evidence_id=spec_id,
            evidence_type="ashare_research_program_spec",
            schema_version=_text(program.get("schema_version")) or "unknown",
            stage=EvidenceStage.A2P6_ROBUST_RESEARCH,
            digest=spec_id,
            source_uri=source_uri,
            program_id=program_id,
            spec_id=spec_id,
            data_version=data_version,
            git_sha=git_sha,
            metadata={"label": "ResearchProgram spec"},
        ),
        _ref(
            evidence_id=walk_id,
            evidence_type="walk_forward_factor_report",
            schema_version=_text(walk_forward.get("schema_version")) or "unknown",
            stage=EvidenceStage.A2P6_ROBUST_RESEARCH,
            digest=walk_id,
            source_uri=source_uri,
            parent_ids=(spec_id,),
            program_id=program_id,
            spec_id=spec_id,
            data_version=data_version,
            git_sha=git_sha,
            metadata={"label": "Walk-forward evidence"},
        ),
        _ref(
            evidence_id=gate_id,
            evidence_type="robust_candidate_gate",
            schema_version=_text(gate.get("schema_version")) or "unknown",
            stage=EvidenceStage.A2P6_ROBUST_RESEARCH,
            digest=gate_id,
            source_uri=source_uri,
            parent_ids=(walk_id,),
            program_id=program_id,
            spec_id=spec_id,
            data_version=data_version,
            git_sha=git_sha,
            metadata={"label": "Preregistered gate"},
        ),
        _ref(
            evidence_id=selection_id,
            evidence_type="robust_factor_selection",
            schema_version=_text(selection.get("schema_version")) or "unknown",
            stage=EvidenceStage.A2P6_ROBUST_RESEARCH,
            digest=selection_id,
            source_uri=source_uri,
            parent_ids=(gate_id,),
            program_id=program_id,
            spec_id=spec_id,
            data_version=data_version,
            git_sha=git_sha,
            metadata={"label": "Frozen factor family", "status": _text(selection.get("status"))},
        ),
    ]
    root = _ref(
        evidence_id=root_id,
        evidence_type="ashare_robust_research_program",
        schema_version=schema,
        stage=EvidenceStage.A2P6_ROBUST_RESEARCH,
        digest=_payload_digest(payload),
        source_uri=source_uri,
        parent_ids=(selection_id,),
        program_id=program_id,
        spec_id=spec_id,
        data_version=data_version,
        git_sha=git_sha,
        metadata={"label": "A2.6 robust ResearchProgram", "status": _text(outcome.get("status"))},
    )
    refs.append(root)
    return EvidenceBundle(
        root=root,
        refs=tuple(refs),
        system_status=_system_status(payload),
        research_status=_text(outcome.get("status"), required=True, name="research status"),
        reserve_status=_text(reserve.get("status"), required=True, name="reserve status"),
        promotion_eligible=bool(outcome.get("promotion_eligible", False)),
        factors=tuple(factors),
        metadata={
            "mode": _text(payload.get("mode")),
            "program_status": _text(payload.get("program_status")),
            "source_schema": schema,
        },
    )


def _portfolio_validation_bundle(
    payload: Mapping[str, Any],
    *,
    source_uri: str,
    git_sha: str,
) -> EvidenceBundle:
    schema = _text(payload.get("schema_version"), required=True, name="schema_version")
    root_id = _text(
        payload.get("portfolio_validation_id"),
        required=True,
        name="portfolio_validation_id",
    )
    spec = _mapping(payload.get("validation_spec"), "validation_spec")
    spec_id = _text(spec.get("spec_id"), required=True, name="validation spec id")
    source_program_id = _text(
        spec.get("source_program_result_id"),
        required=True,
        name="source_program_result_id",
    )
    data_version = _text(spec.get("data_version"), required=True, name="data_version")
    outcome = _mapping(payload.get("research_outcome"), "research_outcome")
    reserve = _mapping(payload.get("reserve"), "reserve")
    ledger_digest = _text(payload.get("ledger_digest"), required=True, name="ledger_digest")
    aggregate = _mapping(payload.get("aggregate"), "aggregate", required=False)
    portfolio: PortfolioEvidence | None = None
    execution: ExecutionEvidence | None = None
    if aggregate:
        net = _mapping(aggregate.get("net_metrics"), "net_metrics")
        gross = _mapping(aggregate.get("gross_metrics"), "gross_metrics")
        points: list[PortfolioPointEvidence] = []
        fold_metrics: list[FoldEvidence] = []
        for raw_fold in _sequence(payload.get("folds"), "portfolio folds", required=False):
            fold = _mapping(raw_fold, "portfolio fold")
            train = _sequence(fold.get("train_range"), "train_range", required=False)
            test = _sequence(fold.get("test_range"), "test_range", required=False)
            fold_net = _mapping(fold.get("net_metrics"), "fold net metrics", required=False)
            fold_gross = _mapping(fold.get("gross_metrics"), "fold gross metrics", required=False)
            fold_metrics.append(
                FoldEvidence(
                    fold_id=_text(fold.get("fold_id"), required=True, name="fold_id"),
                    train_start=_text(train[0]) if len(train) == 2 else "",
                    train_end=_text(train[1]) if len(train) == 2 else "",
                    test_start=_text(test[0]) if len(test) == 2 else "",
                    test_end=_text(test[1]) if len(test) == 2 else "",
                    metrics={
                        "net_total_return": _number(fold_net.get("total_return")),
                        "net_sharpe": _number(fold_net.get("sharpe")),
                        "net_max_drawdown": _number(fold_net.get("max_drawdown")),
                        "gross_total_return": _number(fold_gross.get("total_return")),
                        "gross_sharpe": _number(fold_gross.get("sharpe")),
                        "fees": _number(fold.get("total_fees")),
                        "slippage": _number(fold.get("total_slippage")),
                        "implementation_shortfall": _number(
                            fold.get("average_implementation_shortfall")
                        ),
                    },
                )
            )
            for raw_point in _sequence(fold.get("points"), "portfolio points", required=False):
                point = _mapping(raw_point, "portfolio point")
                points.append(
                    PortfolioPointEvidence(
                        session_date=_text(point.get("session_date"), required=True, name="session_date"),
                        net_nav=_number(point.get("net_nav")),
                        gross_nav=_number(point.get("gross_nav")),
                        net_return=_number(point.get("net_return")),
                        gross_return=_number(point.get("gross_return")),
                        fees=_number(point.get("fees")),
                        slippage=_number(point.get("slippage")),
                        one_way_turnover=_number(point.get("one_way_turnover")),
                        implementation_shortfall=_number(point.get("implementation_shortfall")),
                        maximum_ex_post_participation=_number(
                            point.get("maximum_ex_post_participation")
                        ),
                        desired_order_count=_integer(point.get("desired_order_count")),
                        order_count=_integer(point.get("order_count")),
                        fill_count=_integer(point.get("fill_count")),
                        rejected_order_count=_integer(point.get("rejected_order_count")),
                        cash_fallback=bool(point.get("cash_fallback", False)),
                    )
                )
        portfolio = PortfolioEvidence(
            metrics={
                "net_total_return": _number(net.get("total_return")),
                "net_annualized_return": _number(net.get("annualized_return")),
                "net_volatility": _number(net.get("annualized_volatility")),
                "net_sharpe": _number(net.get("sharpe")),
                "net_max_drawdown": _number(net.get("max_drawdown")),
                "gross_total_return": _number(gross.get("total_return")),
                "gross_annualized_return": _number(gross.get("annualized_return")),
                "gross_sharpe": _number(gross.get("sharpe")),
                "gross_to_net_return_drag": _number(aggregate.get("gross_to_net_return_drag")),
                "positive_fold_ratio": _number(aggregate.get("positive_fold_ratio")),
                "worst_fold_net_sharpe": _number(aggregate.get("worst_fold_net_sharpe")),
                "hac_pvalue": _number(aggregate.get("hac_pvalue"), 1.0),
                "bootstrap_pvalue": _number(aggregate.get("bootstrap_pvalue"), 1.0),
            },
            points=tuple(points),
            fold_metrics=tuple(fold_metrics),
        )
        reason_counts = _mapping(aggregate.get("reason_counts"), "reason_counts", required=False)
        execution = ExecutionEvidence(
            desired_order_count=_integer(aggregate.get("desired_order_count")),
            order_count=_integer(aggregate.get("order_count")),
            fill_count=_integer(aggregate.get("fill_count")),
            rejected_order_count=_integer(aggregate.get("rejected_order_count")),
            rejected_order_ratio=_number(aggregate.get("rejected_order_ratio")),
            cash_fallback_count=_integer(aggregate.get("cash_fallback_count")),
            cash_fallback_ratio=_number(aggregate.get("cash_fallback_ratio")),
            reason_counts={str(key): int(value) for key, value in reason_counts.items()},
            costs={
                "fees": _number(aggregate.get("total_fees")),
                "slippage": _number(aggregate.get("total_slippage")),
                "gross_to_net_return_drag": _number(aggregate.get("gross_to_net_return_drag")),
            },
            maximum_ex_post_participation=_number(
                aggregate.get("maximum_ex_post_participation")
            ),
        )
    refs = [
        _ref(
            evidence_id=source_program_id,
            evidence_type="ashare_robust_research_program",
            schema_version="finagent.ashare-robust-research-program.v1",
            stage=EvidenceStage.A2P6_ROBUST_RESEARCH,
            digest=_text(spec.get("source_report_digest")) or source_program_id,
            source_uri=source_uri,
            data_version=data_version,
            git_sha=git_sha,
            metadata={"label": "Source A2.6 ResearchProgram", "external": True},
        ),
        _ref(
            evidence_id=spec_id,
            evidence_type="ashare_portfolio_validation_spec",
            schema_version=_text(spec.get("schema_version")) or "unknown",
            stage=EvidenceStage.A4_PORTFOLIO_VALIDATION,
            digest=spec_id,
            source_uri=source_uri,
            parent_ids=(source_program_id,),
            spec_id=spec_id,
            data_version=data_version,
            git_sha=git_sha,
            metadata={"label": "A4 validation spec"},
        ),
        _ref(
            evidence_id=ledger_digest,
            evidence_type="ashare_execution_ledger",
            schema_version="finagent.ashare-execution-ledger.v1",
            stage=EvidenceStage.A4_PORTFOLIO_VALIDATION,
            digest=ledger_digest,
            source_uri=source_uri,
            parent_ids=(spec_id,),
            spec_id=spec_id,
            data_version=data_version,
            git_sha=git_sha,
            metadata={"label": "Execution ledger"},
        ),
    ]
    root = _ref(
        evidence_id=root_id,
        evidence_type="ashare_portfolio_validation",
        schema_version=schema,
        stage=EvidenceStage.A4_PORTFOLIO_VALIDATION,
        digest=_payload_digest(payload),
        source_uri=source_uri,
        parent_ids=(ledger_digest,),
        spec_id=spec_id,
        data_version=data_version,
        git_sha=git_sha,
        metadata={"label": "A4 portfolio validation", "status": _text(outcome.get("status"))},
    )
    refs.append(root)
    return EvidenceBundle(
        root=root,
        refs=tuple(refs),
        system_status=_system_status(payload),
        research_status=_text(outcome.get("status"), required=True, name="research status"),
        reserve_status=_text(reserve.get("status"), required=True, name="reserve status"),
        promotion_eligible=bool(outcome.get("promotion_eligible", False)),
        portfolio=portfolio,
        execution=execution,
        metadata={
            "mode": _text(payload.get("mode")),
            "source_research_status": _text(payload.get("source_research_status")),
            "source_schema": schema,
        },
    )


def _diagnostic_root(
    payload: Mapping[str, Any],
    *,
    source_uri: str,
    git_sha: str,
    evidence_type: str,
    stage: EvidenceStage,
    label: str,
    data_version: str,
    status: str,
    metadata: Mapping[str, Any] | None = None,
) -> EvidenceRef:
    schema = _text(payload.get("schema_version"), required=True, name="schema_version")
    digest = _payload_digest(payload)
    return EvidenceRef(
        evidence_id=f"{evidence_type}-{digest[:24]}",
        evidence_type=evidence_type,
        schema_version=schema,
        stage=stage,
        authority=EvidenceAuthority.DIAGNOSTIC,
        artifact_digest=digest,
        source_uri=source_uri,
        data_version=data_version,
        git_sha=git_sha,
        metadata={"label": label, "status": status, **dict(metadata or {})},
    )


def _local_ashare_certification_bundle(
    payload: Mapping[str, Any],
    *,
    source_uri: str,
    git_sha: str,
) -> EvidenceBundle:
    passed = bool(payload.get("passed", False))
    data_version = _text(payload.get("data_version")) or "unknown"
    issues = tuple(
        _mapping(value, "certification issue")
        for value in _sequence(payload.get("issues"), "issues", required=False)
    )
    errors = sum(1 for issue in issues if _text(issue.get("severity")) == "error")
    warnings = sum(1 for issue in issues if _text(issue.get("severity")) == "warning")
    status = "PASS" if passed else "FAIL"
    root = _diagnostic_root(
        payload,
        source_uri=source_uri,
        git_sha=git_sha,
        evidence_type="local_ashare_certification",
        stage=EvidenceStage.DATA_CERTIFICATION,
        label="Local A-share data certification",
        data_version=data_version,
        status=status,
        metadata={
            "root": _text(payload.get("root")),
            "issue_count": len(issues),
            "error_count": errors,
            "warning_count": warnings,
        },
    )
    return EvidenceBundle(
        root=root,
        refs=(root,),
        system_status=status,
        research_status=f"DATA_CERTIFICATION_{status}",
        reserve_status="not_applicable",
        promotion_eligible=False,
        metadata={"source_schema": root.schema_version, "diagnostic": True},
    )


def _local_ashare_system_smoke_bundle(
    payload: Mapping[str, Any],
    *,
    source_uri: str,
    git_sha: str,
) -> EvidenceBundle:
    passed = bool(payload.get("passed", False))
    dataset = _mapping(payload.get("research_dataset"), "research_dataset", required=False)
    security_master = _mapping(payload.get("security_master"), "security_master", required=False)
    data_version = (
        _text(dataset.get("data_version"))
        or _text(payload.get("frozen_dataset_version"))
        or "unknown"
    )
    status = "PASS" if passed else "FAIL"
    root = _diagnostic_root(
        payload,
        source_uri=source_uri,
        git_sha=git_sha,
        evidence_type="local_ashare_system_smoke",
        stage=EvidenceStage.SYSTEM_SMOKE,
        label="Local A-share system smoke",
        data_version=data_version,
        status=status,
        metadata={
            "dataset_digest": _text(dataset.get("digest")),
            "survivorship_certified": bool(security_master.get("survivorship_certified", False)),
            "scope": _text(payload.get("scope")),
        },
    )
    return EvidenceBundle(
        root=root,
        refs=(root,),
        system_status=status,
        research_status=f"SYSTEM_SMOKE_{status}",
        reserve_status="not_applicable",
        promotion_eligible=False,
        metadata={"source_schema": root.schema_version, "diagnostic": True},
    )


def _ashare_execution_smoke_bundle(
    payload: Mapping[str, Any],
    *,
    source_uri: str,
    git_sha: str,
) -> EvidenceBundle:
    passed = bool(payload.get("passed", False))
    data_version = _text(payload.get("data_version")) or "unknown"
    checks = _mapping(payload.get("checks"), "checks", required=False)
    boundaries = _mapping(payload.get("boundaries"), "boundaries", required=False)
    status = "PASS" if passed else "FAIL"
    root = _diagnostic_root(
        payload,
        source_uri=source_uri,
        git_sha=git_sha,
        evidence_type="ashare_execution_smoke",
        stage=EvidenceStage.A3_EXECUTION_SMOKE,
        label="A3 execution semantics smoke",
        data_version=data_version,
        status=status,
        metadata={
            "scope": _text(payload.get("scope")),
            "check_count": len(checks),
            "reserve_consumed": bool(boundaries.get("reserve_consumed", False)),
            "promotion_eligible": bool(boundaries.get("promotion_eligible", False)),
        },
    )
    return EvidenceBundle(
        root=root,
        refs=(root,),
        system_status=status,
        research_status=f"A3_EXECUTION_SMOKE_{status}",
        reserve_status="not_applicable",
        promotion_eligible=False,
        metadata={"source_schema": root.schema_version, "diagnostic": True},
    )


def _system_status(payload: Mapping[str, Any]) -> str:
    system = _mapping(payload.get("system_acceptance"), "system_acceptance", required=False)
    if system:
        return _text(system.get("status")) or ("PASS" if bool(system.get("passed")) else "FAIL")
    return "PASS" if bool(payload.get("passed")) else "UNKNOWN"


def parse_evidence_report(
    raw: str | bytes | Mapping[str, Any],
    *,
    source_uri: str = "",
    git_sha: str = "",
) -> EvidenceBundle:
    if isinstance(raw, Mapping):
        payload = dict(raw)
    else:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise EvidenceContractError("evidence report is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise EvidenceContractError("evidence report root must be a JSON object")
    schema = _text(payload.get("schema_version"), required=True, name="schema_version")
    if schema == "finagent.local-ashare-certification.v1":
        return _local_ashare_certification_bundle(payload, source_uri=source_uri, git_sha=git_sha)
    if schema == "finagent.local-ashare-system-smoke.v1":
        return _local_ashare_system_smoke_bundle(payload, source_uri=source_uri, git_sha=git_sha)
    if schema.startswith("finagent.ashare-factor-research-acceptance.v"):
        return _factor_acceptance_bundle(payload, source_uri=source_uri, git_sha=git_sha)
    if schema == "finagent.ashare-robust-research-program.v1":
        return _robust_program_bundle(payload, source_uri=source_uri, git_sha=git_sha)
    if schema == "finagent.ashare-execution-smoke.v1":
        return _ashare_execution_smoke_bundle(payload, source_uri=source_uri, git_sha=git_sha)
    if schema == "finagent.ashare-portfolio-validation.v1":
        return _portfolio_validation_bundle(payload, source_uri=source_uri, git_sha=git_sha)
    raise EvidenceContractError(f"unsupported evidence schema: {schema}")


def load_evidence_report(path: str | Path, *, git_sha: str = "") -> EvidenceBundle:
    source = Path(path).expanduser()
    return parse_evidence_report(
        source.read_text(encoding="utf-8"),
        source_uri=str(source),
        git_sha=git_sha,
    )

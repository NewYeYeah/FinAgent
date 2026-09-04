from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from finagent.research.us_r1_gate import canonical_us_r1_alpha_gate_policy
from finagent.research.us_r2_candidate_cache import (
    FROZEN_CANDIDATE_COUNT,
    validate_us_r2_candidate_denominator,
)
from finagent.research.us_r2_evaluation_policy import (
    canonical_us_r2_statistical_evaluation_policy,
)
from finagent.research.us_r2_frozen_protocol import (
    FROZEN_CANDIDATE_DENOMINATOR_ID,
    FROZEN_REGIME_LABELS,
    canonical_us_r2_frozen_protocol,
    validate_us_r2_frozen_protocol,
)
from finagent.research.us_r2_protocol import USR2Terminal


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{field_name} must be an array")
    return value


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    return value.strip()


def _integer(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    return value


def _number(value: object, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be numeric")
    rendered = float(value)
    if not math.isfinite(rendered):
        raise ValueError(f"{field_name} must be finite")
    return rendered


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _texts(value: object, field_name: str) -> tuple[str, ...]:
    return tuple(_text(item, f"{field_name}[]") for item in _sequence(value, field_name))


def _validate_content_id(
    document: Mapping[str, object],
    *,
    identity_field: str,
    prefix: str,
) -> str:
    actual = _text(document.get(identity_field), identity_field)
    payload = dict(document)
    del payload[identity_field]
    expected = _canonical_hash(payload, prefix=prefix)
    if actual != expected:
        raise ValueError(f"{identity_field} content identity mismatch")
    return actual


@dataclass(frozen=True, slots=True)
class USR2AlphaGatePolicy:
    frozen_protocol_id: str
    denominator_id: str
    evaluation_policy_id: str
    inherited_r1_alpha_gate_policy_id: str
    required_fold_count: int
    required_regime_count: int
    required_fold_regime_cell_count: int
    min_primary_mean_rank_ic: float
    min_worst_fold_regime_rank_ic: float
    min_mean_fold_regime_rank_icir: float
    min_worst_fold_regime_rank_icir: float
    min_positive_fold_regime_ratio: float
    max_raw_hac_pvalue: float
    max_holm_adjusted_pvalue: float
    max_bh_qvalue: float
    max_session_bootstrap_pvalue: float
    min_session_bootstrap_ci_lower: float
    min_frequency_sign_consistency: float
    min_decay_sign_consistency: float
    min_coverage: float
    min_quantile_monotonicity: float
    min_mean_long_short_return_bps: float
    max_mean_one_way_turnover: float
    min_return_per_turnover_bps: float
    schema_version: str = "finagent.us-r2-alpha-gate-policy.v1"

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-alpha-gate-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "frozen_protocol_id": self.frozen_protocol_id,
            "denominator_id": self.denominator_id,
            "evaluation_policy_id": self.evaluation_policy_id,
            "inherited_r1_alpha_gate_policy_id": self.inherited_r1_alpha_gate_policy_id,
            "required_fold_count": self.required_fold_count,
            "required_regime_count": self.required_regime_count,
            "required_fold_regime_cell_count": self.required_fold_regime_cell_count,
            "min_primary_mean_rank_ic": self.min_primary_mean_rank_ic,
            "min_worst_fold_regime_rank_ic": self.min_worst_fold_regime_rank_ic,
            "min_mean_fold_regime_rank_icir": self.min_mean_fold_regime_rank_icir,
            "min_worst_fold_regime_rank_icir": self.min_worst_fold_regime_rank_icir,
            "min_positive_fold_regime_ratio": self.min_positive_fold_regime_ratio,
            "max_raw_hac_pvalue": self.max_raw_hac_pvalue,
            "max_holm_adjusted_pvalue": self.max_holm_adjusted_pvalue,
            "max_bh_qvalue": self.max_bh_qvalue,
            "max_session_bootstrap_pvalue": self.max_session_bootstrap_pvalue,
            "min_session_bootstrap_ci_lower": self.min_session_bootstrap_ci_lower,
            "min_frequency_sign_consistency": self.min_frequency_sign_consistency,
            "min_decay_sign_consistency": self.min_decay_sign_consistency,
            "min_coverage": self.min_coverage,
            "min_quantile_monotonicity": self.min_quantile_monotonicity,
            "min_mean_long_short_return_bps": self.min_mean_long_short_return_bps,
            "max_mean_one_way_turnover": self.max_mean_one_way_turnover,
            "min_return_per_turnover_bps": self.min_return_per_turnover_bps,
            "frequency_requirement": "every_regime_passes_inherited_2_of_3_sign_rule",
            "decay_requirement": "every_regime_passes_inherited_2_of_3_sign_rule",
            "candidate_denominator_preserved": True,
            "performance_filter_applied": False,
            "thresholds_relaxed": False,
            "positive_terminal": USR2Terminal.ROBUST_FACTOR_FAMILY.value,
            "negative_terminal": USR2Terminal.NO_ROBUST_FACTOR_FAMILY.value,
            "technical_terminal": USR2Terminal.SYSTEM_FAILURE.value,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


def canonical_us_r2_alpha_gate_policy() -> USR2AlphaGatePolicy:
    frozen = canonical_us_r2_frozen_protocol()
    inherited = canonical_us_r1_alpha_gate_policy()
    evaluation = canonical_us_r2_statistical_evaluation_policy()
    return USR2AlphaGatePolicy(
        frozen_protocol_id=frozen.freeze_id,
        denominator_id=FROZEN_CANDIDATE_DENOMINATOR_ID,
        evaluation_policy_id=evaluation.policy_id,
        inherited_r1_alpha_gate_policy_id=inherited.policy_id,
        required_fold_count=len(frozen.walk_forward_protocol.folds),
        required_regime_count=len(FROZEN_REGIME_LABELS),
        required_fold_regime_cell_count=(
            len(frozen.walk_forward_protocol.folds) * len(FROZEN_REGIME_LABELS)
        ),
        min_primary_mean_rank_ic=inherited.min_primary_mean_rank_ic,
        min_worst_fold_regime_rank_ic=inherited.min_worst_fold_rank_ic,
        min_mean_fold_regime_rank_icir=inherited.min_mean_fold_rank_icir,
        min_worst_fold_regime_rank_icir=inherited.min_worst_fold_rank_icir,
        min_positive_fold_regime_ratio=inherited.min_positive_fold_ratio,
        max_raw_hac_pvalue=inherited.max_raw_hac_pvalue,
        max_holm_adjusted_pvalue=inherited.max_holm_adjusted_pvalue,
        max_bh_qvalue=inherited.max_bh_qvalue,
        max_session_bootstrap_pvalue=inherited.max_session_bootstrap_pvalue,
        min_session_bootstrap_ci_lower=inherited.min_session_bootstrap_ci_lower,
        min_frequency_sign_consistency=inherited.min_frequency_sign_consistency,
        min_decay_sign_consistency=inherited.min_decay_sign_consistency,
        min_coverage=inherited.min_coverage,
        min_quantile_monotonicity=inherited.min_quantile_monotonicity,
        min_mean_long_short_return_bps=inherited.min_mean_long_short_return_bps,
        max_mean_one_way_turnover=inherited.max_mean_one_way_turnover,
        min_return_per_turnover_bps=inherited.min_return_per_turnover_bps,
    )


@dataclass(frozen=True, slots=True)
class USR2FinalCandidateEvidence:
    candidate_id: str
    fold_regime_cell_count: int
    mean_directed_rank_ic: float
    worst_fold_regime_rank_ic: float
    regime_mean_directed_rank_ic: tuple[tuple[str, float], ...]
    worst_regime_mean_directed_rank_ic: float
    mean_fold_regime_rank_icir: float
    worst_fold_regime_rank_icir: float
    positive_fold_regime_ratio: float
    raw_hac_pvalue: float
    holm_adjusted_pvalue: float
    bh_qvalue: float
    session_bootstrap_pvalue: float
    session_bootstrap_ci_lower: float
    session_bootstrap_ci_upper: float
    frequency_sign_consistency_by_regime: tuple[tuple[str, float], ...]
    all_regimes_frequency_passed: bool
    decay_sign_consistency_by_regime: tuple[tuple[str, float], ...]
    all_regimes_decay_passed: bool
    coverage_mean: float
    coverage_min: float
    quantile_monotonicity: float
    mean_long_short_return_bps: float
    mean_one_way_turnover: float
    return_per_turnover_bps: float
    schema_version: str = "finagent.us-r2-final-candidate-evidence.v1"

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("US-R2 final candidate_id must be non-empty")
        if self.fold_regime_cell_count < 1:
            raise ValueError("US-R2 final candidate requires fold-regime cells")
        if tuple(name for name, _value in self.regime_mean_directed_rank_ic) != (
            FROZEN_REGIME_LABELS
        ):
            raise ValueError("US-R2 final candidate regime means changed order")
        if tuple(name for name, _value in self.frequency_sign_consistency_by_regime) != (
            FROZEN_REGIME_LABELS
        ):
            raise ValueError("US-R2 final candidate frequency regimes changed order")
        if tuple(name for name, _value in self.decay_sign_consistency_by_regime) != (
            FROZEN_REGIME_LABELS
        ):
            raise ValueError("US-R2 final candidate decay regimes changed order")
        for field_name in (
            "mean_directed_rank_ic",
            "worst_fold_regime_rank_ic",
            "worst_regime_mean_directed_rank_ic",
            "mean_fold_regime_rank_icir",
            "worst_fold_regime_rank_icir",
            "session_bootstrap_ci_lower",
            "session_bootstrap_ci_upper",
            "coverage_mean",
            "coverage_min",
            "quantile_monotonicity",
            "mean_long_short_return_bps",
            "mean_one_way_turnover",
            "return_per_turnover_bps",
        ):
            if not math.isfinite(float(getattr(self, field_name))):
                raise ValueError(f"{field_name} must be finite")
        for field_name in (
            "positive_fold_regime_ratio",
            "raw_hac_pvalue",
            "holm_adjusted_pvalue",
            "bh_qvalue",
            "session_bootstrap_pvalue",
            "coverage_mean",
            "coverage_min",
        ):
            value = float(getattr(self, field_name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be in [0,1]")
        if self.session_bootstrap_ci_upper < self.session_bootstrap_ci_lower:
            raise ValueError("US-R2 final bootstrap interval is invalid")
        if self.mean_one_way_turnover < 0.0:
            raise ValueError("US-R2 final turnover must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "fold_regime_cell_count": self.fold_regime_cell_count,
            "mean_directed_rank_ic": self.mean_directed_rank_ic,
            "worst_fold_regime_rank_ic": self.worst_fold_regime_rank_ic,
            "regime_mean_directed_rank_ic": dict(self.regime_mean_directed_rank_ic),
            "worst_regime_mean_directed_rank_ic": self.worst_regime_mean_directed_rank_ic,
            "mean_fold_regime_rank_icir": self.mean_fold_regime_rank_icir,
            "worst_fold_regime_rank_icir": self.worst_fold_regime_rank_icir,
            "positive_fold_regime_ratio": self.positive_fold_regime_ratio,
            "rank_ic_inference": {
                "raw_hac_pvalue": self.raw_hac_pvalue,
                "holm_adjusted_pvalue": self.holm_adjusted_pvalue,
                "bh_qvalue": self.bh_qvalue,
                "session_bootstrap_pvalue": self.session_bootstrap_pvalue,
                "session_bootstrap_ci_lower": self.session_bootstrap_ci_lower,
                "session_bootstrap_ci_upper": self.session_bootstrap_ci_upper,
            },
            "frequency_sign_consistency_by_regime": dict(self.frequency_sign_consistency_by_regime),
            "all_regimes_frequency_passed": self.all_regimes_frequency_passed,
            "decay_sign_consistency_by_regime": dict(self.decay_sign_consistency_by_regime),
            "all_regimes_decay_passed": self.all_regimes_decay_passed,
            "coverage_mean": self.coverage_mean,
            "coverage_min": self.coverage_min,
            "quantile_monotonicity": self.quantile_monotonicity,
            "mean_long_short_return_bps": self.mean_long_short_return_bps,
            "mean_one_way_turnover": self.mean_one_way_turnover,
            "return_per_turnover_bps": self.return_per_turnover_bps,
        }


@dataclass(frozen=True, slots=True)
class USR2FinalFamilyEvidence:
    frozen_protocol_id: str
    denominator_id: str
    primary_statistics_report_id: str
    pooled_inference_report_id: str
    candidate_robustness_report_id: str
    candidates: tuple[USR2FinalCandidateEvidence, ...]
    technical_blockers: tuple[str, ...] = ()
    schema_version: str = "finagent.us-r2-final-family-evidence.v1"

    def __post_init__(self) -> None:
        ids = tuple(item.candidate_id for item in self.candidates)
        if len(ids) != FROZEN_CANDIDATE_COUNT or len(ids) != len(set(ids)):
            raise ValueError("US-R2 final family requires 37 unique candidates")
        blockers = tuple(item.strip() for item in self.technical_blockers if item.strip())
        if len(blockers) != len(self.technical_blockers) or len(blockers) != len(set(blockers)):
            raise ValueError("US-R2 final technical blockers must be unique and non-empty")

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-final-family-evidence")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "frozen_protocol_id": self.frozen_protocol_id,
            "denominator_id": self.denominator_id,
            "primary_statistics_report_id": self.primary_statistics_report_id,
            "pooled_inference_report_id": self.pooled_inference_report_id,
            "candidate_robustness_report_id": self.candidate_robustness_report_id,
            "candidate_count": len(self.candidates),
            "candidate_ids": [item.candidate_id for item in self.candidates],
            "candidates": [item.to_dict() for item in self.candidates],
            "technical_blockers": list(self.technical_blockers),
            "candidate_denominator_preserved": True,
            "performance_filter_applied": False,
            "candidate_selection_applied": False,
            "alpha_gate_evaluated": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


@dataclass(frozen=True, slots=True)
class USR2CandidateGateAssessment:
    candidate_id: str
    passed: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "passed": self.passed,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class USR2AlphaGateAssessment:
    policy_id: str
    family_evidence_id: str
    denominator_id: str
    terminal: USR2Terminal
    candidates: tuple[USR2CandidateGateAssessment, ...]
    robust_candidate_ids: tuple[str, ...]
    technical_blockers: tuple[str, ...]
    schema_version: str = "finagent.us-r2-alpha-gate-assessment.v1"

    def __post_init__(self) -> None:
        candidate_ids = tuple(item.candidate_id for item in self.candidates)
        if len(candidate_ids) != FROZEN_CANDIDATE_COUNT:
            raise ValueError("US-R2 Alpha Gate assessment requires 37 candidates")
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("US-R2 Alpha Gate assessment contains duplicate candidates")
        passing = tuple(item.candidate_id for item in self.candidates if item.passed)
        if self.terminal is USR2Terminal.ROBUST_FACTOR_FAMILY:
            if not passing or passing != self.robust_candidate_ids:
                raise ValueError("ROBUST_FACTOR_FAMILY requires exact passing candidate IDs")
        elif self.robust_candidate_ids:
            raise ValueError("non-positive US-R2 terminal cannot retain robust candidates")
        if self.terminal is USR2Terminal.NO_ROBUST_FACTOR_FAMILY and passing:
            raise ValueError("NO_ROBUST_FACTOR_FAMILY cannot contain a passing candidate")
        if self.terminal is USR2Terminal.SYSTEM_FAILURE and not self.technical_blockers:
            raise ValueError("SYSTEM_FAILURE requires technical blockers")

    @property
    def assessment_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-alpha-gate-assessment")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "family_evidence_id": self.family_evidence_id,
            "denominator_id": self.denominator_id,
            "terminal": self.terminal.value,
            "candidate_count": len(self.candidates),
            "candidates": [item.to_dict() for item in self.candidates],
            "robust_candidate_ids": list(self.robust_candidate_ids),
            "technical_blockers": list(self.technical_blockers),
            "alpha_gate_evaluated": True,
            "recommendation_authority": "deterministic_preregistered_policy_only",
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["assessment_id"] = self.assessment_id
        return payload


@dataclass(frozen=True, slots=True)
class USR2InferenceEvidenceGraph:
    frozen_protocol_id: str
    denominator_id: str
    primary_statistics_report_id: str
    pooled_inference_report_id: str
    candidate_robustness_report_id: str
    family_evidence_id: str
    alpha_gate_policy_id: str
    alpha_gate_assessment_id: str
    schema_version: str = "finagent.us-r2-inference-evidence-graph.v1"

    @property
    def graph_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-inference-graph")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        nodes = (
            self.frozen_protocol_id,
            self.denominator_id,
            self.primary_statistics_report_id,
            self.pooled_inference_report_id,
            self.candidate_robustness_report_id,
            self.family_evidence_id,
            self.alpha_gate_policy_id,
            self.alpha_gate_assessment_id,
        )
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "nodes": list(nodes),
            "edges": [
                [self.frozen_protocol_id, self.family_evidence_id],
                [self.denominator_id, self.family_evidence_id],
                [self.primary_statistics_report_id, self.family_evidence_id],
                [self.pooled_inference_report_id, self.family_evidence_id],
                [self.candidate_robustness_report_id, self.family_evidence_id],
                [self.family_evidence_id, self.alpha_gate_assessment_id],
                [self.alpha_gate_policy_id, self.alpha_gate_assessment_id],
            ],
            "market_data_read": False,
            "candidate_feature_recomputation": False,
            "candidate_selection_applied": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["graph_id"] = self.graph_id
        return payload


@dataclass(frozen=True, slots=True)
class USR2FinalArtifacts:
    policy: USR2AlphaGatePolicy
    family: USR2FinalFamilyEvidence
    assessment: USR2AlphaGateAssessment
    graph: USR2InferenceEvidenceGraph


def _candidate_gate(
    candidate: USR2FinalCandidateEvidence,
    policy: USR2AlphaGatePolicy,
) -> USR2CandidateGateAssessment:
    checks = (
        (
            candidate.fold_regime_cell_count == policy.required_fold_regime_cell_count,
            "FOLD_REGIME_CELL_COUNT_CHANGED",
        ),
        (
            candidate.mean_directed_rank_ic >= policy.min_primary_mean_rank_ic,
            "PRIMARY_MEAN_RANK_IC_BELOW_THRESHOLD",
        ),
        (
            candidate.worst_fold_regime_rank_ic >= policy.min_worst_fold_regime_rank_ic,
            "WORST_FOLD_REGIME_RANK_IC_BELOW_THRESHOLD",
        ),
        (
            candidate.mean_fold_regime_rank_icir >= policy.min_mean_fold_regime_rank_icir,
            "MEAN_FOLD_REGIME_RANK_ICIR_BELOW_THRESHOLD",
        ),
        (
            candidate.worst_fold_regime_rank_icir >= policy.min_worst_fold_regime_rank_icir,
            "WORST_FOLD_REGIME_RANK_ICIR_BELOW_THRESHOLD",
        ),
        (
            candidate.positive_fold_regime_ratio >= policy.min_positive_fold_regime_ratio,
            "POSITIVE_FOLD_REGIME_RATIO_BELOW_THRESHOLD",
        ),
        (candidate.raw_hac_pvalue <= policy.max_raw_hac_pvalue, "HAC_NOT_SIGNIFICANT"),
        (
            candidate.holm_adjusted_pvalue <= policy.max_holm_adjusted_pvalue,
            "HOLM_ADJUSTED_PVALUE_ABOVE_THRESHOLD",
        ),
        (candidate.bh_qvalue <= policy.max_bh_qvalue, "BH_QVALUE_ABOVE_THRESHOLD"),
        (
            candidate.session_bootstrap_pvalue <= policy.max_session_bootstrap_pvalue,
            "SESSION_BOOTSTRAP_NOT_SIGNIFICANT",
        ),
        (
            candidate.session_bootstrap_ci_lower > policy.min_session_bootstrap_ci_lower,
            "SESSION_BOOTSTRAP_CI_CROSSES_ZERO",
        ),
        (
            candidate.all_regimes_frequency_passed,
            "FREQUENCY_SIGN_INCONSISTENT_IN_ONE_OR_MORE_REGIMES",
        ),
        (
            candidate.all_regimes_decay_passed,
            "DECAY_SIGN_INCONSISTENT_IN_ONE_OR_MORE_REGIMES",
        ),
        (candidate.coverage_min >= policy.min_coverage, "COVERAGE_BELOW_THRESHOLD"),
        (
            candidate.quantile_monotonicity >= policy.min_quantile_monotonicity,
            "QUANTILE_MONOTONICITY_BELOW_THRESHOLD",
        ),
        (
            candidate.mean_long_short_return_bps >= policy.min_mean_long_short_return_bps,
            "GROSS_LONG_SHORT_RETURN_BELOW_THRESHOLD",
        ),
        (
            candidate.mean_one_way_turnover <= policy.max_mean_one_way_turnover,
            "TURNOVER_ABOVE_THRESHOLD",
        ),
        (
            candidate.return_per_turnover_bps >= policy.min_return_per_turnover_bps,
            "RETURN_PER_TURNOVER_BELOW_THRESHOLD",
        ),
    )
    reasons = tuple(reason for passed, reason in checks if not passed)
    return USR2CandidateGateAssessment(candidate.candidate_id, not reasons, reasons)


def assess_us_r2_alpha_gate(
    family: USR2FinalFamilyEvidence,
    policy: USR2AlphaGatePolicy | None = None,
) -> USR2AlphaGateAssessment:
    active = policy or canonical_us_r2_alpha_gate_policy()
    if family.denominator_id != active.denominator_id:
        raise ValueError("US-R2 family and Alpha Gate denominator differ")
    candidates = tuple(_candidate_gate(item, active) for item in family.candidates)
    passing = tuple(item.candidate_id for item in candidates if item.passed)
    if family.technical_blockers:
        terminal = USR2Terminal.SYSTEM_FAILURE
        passing = ()
    elif passing:
        terminal = USR2Terminal.ROBUST_FACTOR_FAMILY
    else:
        terminal = USR2Terminal.NO_ROBUST_FACTOR_FAMILY
    return USR2AlphaGateAssessment(
        policy_id=active.policy_id,
        family_evidence_id=family.evidence_id,
        denominator_id=family.denominator_id,
        terminal=terminal,
        candidates=candidates,
        robust_candidate_ids=passing,
        technical_blockers=family.technical_blockers,
    )


def _candidate_documents(
    document: Mapping[str, object],
    *,
    field_name: str = "candidates",
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        _mapping(item, f"{field_name}[]")
        for item in _sequence(document.get(field_name), field_name)
    )


def build_us_r2_final_artifacts_from_documents(
    *,
    frozen_protocol_document: Mapping[str, object],
    denominator_document: Mapping[str, object],
    primary_statistics_document: Mapping[str, object],
    pooled_inference_document: Mapping[str, object],
    candidate_robustness_document: Mapping[str, object],
) -> USR2FinalArtifacts:
    frozen = validate_us_r2_frozen_protocol(frozen_protocol_document)
    denominator = validate_us_r2_candidate_denominator(denominator_document)
    policy = canonical_us_r2_alpha_gate_policy()
    if frozen.freeze_id != policy.frozen_protocol_id:
        raise ValueError("US-R2 final Gate frozen protocol identity changed")
    if denominator.denominator_id != policy.denominator_id:
        raise ValueError("US-R2 final Gate denominator identity changed")
    candidate_ids = tuple(item.candidate.candidate_id for item in denominator.candidates)

    primary_id = _validate_content_id(
        primary_statistics_document,
        identity_field="report_id",
        prefix="us-r2-primary-statistics",
    )
    pooled_id = _validate_content_id(
        pooled_inference_document,
        identity_field="report_id",
        prefix="us-r2-pooled-inference",
    )
    robustness_id = _validate_content_id(
        candidate_robustness_document,
        identity_field="report_id",
        prefix="us-r2-candidate-robustness",
    )
    for document, name in (
        (primary_statistics_document, "primary statistics"),
        (pooled_inference_document, "pooled inference"),
        (candidate_robustness_document, "candidate robustness"),
    ):
        if not _boolean(document.get("passed"), f"{name}.passed"):
            raise ValueError(f"US-R2 final Gate requires passed {name} evidence")
        if _texts(document.get("blockers", document.get("technical_blockers")), f"{name}.blockers"):
            raise ValueError(f"US-R2 final Gate requires blocker-free {name} evidence")
        if _boolean(
            document.get("candidate_selection_applied", False),
            f"{name}.candidate_selection_applied",
        ):
            raise ValueError(f"US-R2 final Gate forbids selection in {name} evidence")
        if _boolean(
            document.get("performance_filter_applied", False), f"{name}.performance_filter_applied"
        ):
            raise ValueError(f"US-R2 final Gate forbids performance filtering in {name} evidence")
        if _boolean(document.get("alpha_gate_evaluated"), f"{name}.alpha_gate_evaluated"):
            raise ValueError(
                f"US-R2 final Gate source already claims Alpha Gate evaluation: {name}"
            )

    if (
        _text(
            primary_statistics_document.get("evaluation_policy_id"), "primary.evaluation_policy_id"
        )
        != policy.evaluation_policy_id
    ):
        raise ValueError("US-R2 primary statistics evaluation policy changed")
    if (
        _text(pooled_inference_document.get("evaluation_policy_id"), "pooled.evaluation_policy_id")
        != policy.evaluation_policy_id
    ):
        raise ValueError("US-R2 pooled inference evaluation policy changed")
    if (
        _text(
            candidate_robustness_document.get("evaluation_policy_id"),
            "robustness.evaluation_policy_id",
        )
        != policy.evaluation_policy_id
    ):
        raise ValueError("US-R2 candidate robustness evaluation policy changed")
    if (
        _text(pooled_inference_document.get("denominator_id"), "pooled.denominator_id")
        != policy.denominator_id
    ):
        raise ValueError("US-R2 pooled inference denominator changed")
    if (
        _text(
            pooled_inference_document.get("primary_statistics_report_id"),
            "pooled.primary_statistics_report_id",
        )
        != primary_id
    ):
        raise ValueError("US-R2 pooled inference primary report lineage changed")
    if (
        _text(
            candidate_robustness_document.get("primary_statistics_report_id"),
            "robustness.primary_statistics_report_id",
        )
        != primary_id
    ):
        raise ValueError("US-R2 robustness primary report lineage changed")

    primary_slices = tuple(
        _mapping(item, "primary.slices[]")
        for item in _sequence(primary_statistics_document.get("slices"), "primary.slices")
    )
    expected_slice_count = FROZEN_CANDIDATE_COUNT * policy.required_fold_regime_cell_count
    if len(primary_slices) != expected_slice_count:
        raise ValueError("US-R2 primary fold-regime denominator is incomplete")
    pooled_candidates = _candidate_documents(pooled_inference_document)
    robustness_candidates = _candidate_documents(candidate_robustness_document)
    pooled_ids = tuple(
        _text(item.get("candidate_id"), "pooled.candidate_id") for item in pooled_candidates
    )
    robustness_ids = tuple(
        _text(item.get("candidate_id"), "robustness.candidate_id") for item in robustness_candidates
    )
    if pooled_ids != candidate_ids or robustness_ids != candidate_ids:
        raise ValueError("US-R2 final Gate candidate denominator order changed")
    primary_by_candidate: dict[str, list[Mapping[str, object]]] = {
        candidate_id: [] for candidate_id in candidate_ids
    }
    seen_cells: set[tuple[str, str, str]] = set()
    expected_folds = tuple(item.fold_id for item in frozen.walk_forward_protocol.folds)
    for item in primary_slices:
        candidate_id = _text(item.get("candidate_id"), "primary.candidate_id")
        fold_id = _text(item.get("fold_id"), "primary.fold_id")
        regime = _text(item.get("regime"), "primary.regime")
        cell = (candidate_id, fold_id, regime)
        if candidate_id not in primary_by_candidate or cell in seen_cells:
            raise ValueError("US-R2 primary fold-regime denominator changed or duplicated")
        if fold_id not in expected_folds or regime not in FROZEN_REGIME_LABELS:
            raise ValueError("US-R2 primary fold/regime label changed")
        if not _boolean(item.get("passed"), "primary.slice.passed") or _texts(
            item.get("blockers"), "primary.slice.blockers"
        ):
            raise ValueError("US-R2 final Gate requires every primary cell to be admitted")
        seen_cells.add(cell)
        primary_by_candidate[candidate_id].append(item)

    final_candidates: list[USR2FinalCandidateEvidence] = []
    for candidate_id, pooled, robustness in zip(
        candidate_ids, pooled_candidates, robustness_candidates, strict=True
    ):
        cells = primary_by_candidate[candidate_id]
        if len(cells) != policy.required_fold_regime_cell_count:
            raise ValueError("US-R2 candidate primary fold-regime cells are incomplete")
        rank_values = tuple(
            _number(item.get("mean_directed_rank_ic"), "primary.mean_directed_rank_ic")
            for item in cells
        )
        icir_values = tuple(
            _number(item.get("directed_rank_icir"), "primary.directed_rank_icir") for item in cells
        )
        regime_means: list[tuple[str, float]] = []
        for regime in FROZEN_REGIME_LABELS:
            primary_regime_cells = [item for item in cells if item.get("regime") == regime]
            weights = tuple(
                _integer(item.get("period_count"), "primary.period_count")
                for item in primary_regime_cells
            )
            values = tuple(
                _number(item.get("mean_directed_rank_ic"), "primary.mean_directed_rank_ic")
                for item in primary_regime_cells
            )
            denominator_count = sum(weights)
            if len(primary_regime_cells) != policy.required_fold_count or denominator_count <= 0:
                raise ValueError("US-R2 per-regime primary evidence is incomplete")
            regime_means.append(
                (
                    regime,
                    math.fsum(value * weight for value, weight in zip(values, weights, strict=True))
                    / denominator_count,
                )
            )

        raw = _mapping(pooled.get("raw"), "pooled.raw")
        inference = _mapping(raw.get("rank_ic_inference"), "pooled.rank_ic_inference")
        multiplicity = _mapping(pooled.get("multiplicity"), "pooled.multiplicity")
        robustness_regime_cells = tuple(
            _mapping(item, "robustness.regime_cells[]")
            for item in _sequence(robustness.get("regime_cells"), "robustness.regime_cells")
        )
        if (
            tuple(
                _text(item.get("regime"), "robustness.regime") for item in robustness_regime_cells
            )
            != FROZEN_REGIME_LABELS
        ):
            raise ValueError("US-R2 robustness regime denominator/order changed")
        frequency = tuple(
            (
                _text(item.get("regime"), "robustness.regime"),
                _number(item.get("frequency_sign_consistency"), "frequency_sign_consistency"),
            )
            for item in robustness_regime_cells
        )
        decay = tuple(
            (
                _text(item.get("regime"), "robustness.regime"),
                _number(item.get("decay_sign_consistency"), "decay_sign_consistency"),
            )
            for item in robustness_regime_cells
        )
        frequency_passed = _boolean(
            robustness.get("all_regimes_frequency_passed"),
            "robustness.all_regimes_frequency_passed",
        )
        decay_passed = _boolean(
            robustness.get("all_regimes_decay_passed"),
            "robustness.all_regimes_decay_passed",
        )
        if frequency_passed != all(
            value >= policy.min_frequency_sign_consistency for _regime, value in frequency
        ):
            raise ValueError("US-R2 frequency robustness summary is inconsistent")
        if decay_passed != all(
            value >= policy.min_decay_sign_consistency for _regime, value in decay
        ):
            raise ValueError("US-R2 decay robustness summary is inconsistent")
        final_candidates.append(
            USR2FinalCandidateEvidence(
                candidate_id=candidate_id,
                fold_regime_cell_count=len(cells),
                mean_directed_rank_ic=_number(
                    raw.get("mean_directed_rank_ic"), "pooled.mean_directed_rank_ic"
                ),
                worst_fold_regime_rank_ic=min(rank_values),
                regime_mean_directed_rank_ic=tuple(regime_means),
                worst_regime_mean_directed_rank_ic=min(value for _regime, value in regime_means),
                mean_fold_regime_rank_icir=math.fsum(icir_values) / len(icir_values),
                worst_fold_regime_rank_icir=min(icir_values),
                positive_fold_regime_ratio=sum(value > 0.0 for value in rank_values)
                / len(rank_values),
                raw_hac_pvalue=_number(inference.get("raw_hac_pvalue"), "pooled.raw_hac_pvalue"),
                holm_adjusted_pvalue=_number(
                    multiplicity.get("holm_adjusted_rank_ic_pvalue"), "pooled.holm_adjusted_pvalue"
                ),
                bh_qvalue=_number(multiplicity.get("bh_rank_ic_qvalue"), "pooled.bh_qvalue"),
                session_bootstrap_pvalue=_number(
                    inference.get("session_block_bootstrap_pvalue"), "pooled.bootstrap_pvalue"
                ),
                session_bootstrap_ci_lower=_number(
                    inference.get("session_block_bootstrap_ci_lower"), "pooled.bootstrap_ci_lower"
                ),
                session_bootstrap_ci_upper=_number(
                    inference.get("session_block_bootstrap_ci_upper"), "pooled.bootstrap_ci_upper"
                ),
                frequency_sign_consistency_by_regime=frequency,
                all_regimes_frequency_passed=frequency_passed,
                decay_sign_consistency_by_regime=decay,
                all_regimes_decay_passed=decay_passed,
                coverage_mean=_number(raw.get("coverage_mean"), "pooled.coverage_mean"),
                coverage_min=_number(raw.get("coverage_min"), "pooled.coverage_min"),
                quantile_monotonicity=_number(
                    raw.get("directed_quantile_monotonicity"), "pooled.quantile_monotonicity"
                ),
                mean_long_short_return_bps=_number(
                    raw.get("mean_directed_long_short_return_bps"),
                    "pooled.mean_long_short_return_bps",
                ),
                mean_one_way_turnover=_number(
                    raw.get("mean_one_way_turnover"), "pooled.mean_one_way_turnover"
                ),
                return_per_turnover_bps=_number(
                    raw.get("return_per_turnover_bps"), "pooled.return_per_turnover_bps"
                ),
            )
        )

    family = USR2FinalFamilyEvidence(
        frozen_protocol_id=frozen.freeze_id,
        denominator_id=denominator.denominator_id,
        primary_statistics_report_id=primary_id,
        pooled_inference_report_id=pooled_id,
        candidate_robustness_report_id=robustness_id,
        candidates=tuple(final_candidates),
    )
    assessment = assess_us_r2_alpha_gate(family, policy)
    graph = USR2InferenceEvidenceGraph(
        frozen_protocol_id=frozen.freeze_id,
        denominator_id=denominator.denominator_id,
        primary_statistics_report_id=primary_id,
        pooled_inference_report_id=pooled_id,
        candidate_robustness_report_id=robustness_id,
        family_evidence_id=family.evidence_id,
        alpha_gate_policy_id=policy.policy_id,
        alpha_gate_assessment_id=assessment.assessment_id,
    )
    return USR2FinalArtifacts(policy=policy, family=family, assessment=assessment, graph=graph)


@dataclass(frozen=True, slots=True)
class USR2AlphaGateReview:
    assessment_id: str
    inference_graph_id: str
    reviewer_id: str
    reviewed_at: str
    review_notes: str
    terminal: USR2Terminal
    thresholds_unchanged_attested: bool
    evidence_lineage_attested: bool
    denominator_preserved_attested: bool
    execution_gate_separation_attested: bool
    live_capital_separation_attested: bool
    assessment_terminal: USR2Terminal
    schema_version: str = "finagent.us-r2-alpha-gate-review.v1"

    def __post_init__(self) -> None:
        if not self.reviewer_id.strip() or not self.review_notes.strip():
            raise ValueError("US-R2 reviewer identity and notes are required")
        parsed = datetime.fromisoformat(self.reviewed_at)
        if parsed.tzinfo is None:
            raise ValueError("US-R2 reviewed_at must be timezone-aware")
        allowed = {self.assessment_terminal, USR2Terminal.SYSTEM_FAILURE}
        if self.terminal not in allowed:
            raise ValueError(
                "US-R2 review may accept the assessment or downgrade to SYSTEM_FAILURE"
            )
        if not all(
            (
                self.thresholds_unchanged_attested,
                self.evidence_lineage_attested,
                self.denominator_preserved_attested,
                self.execution_gate_separation_attested,
                self.live_capital_separation_attested,
            )
        ):
            raise ValueError("US-R2 final review requires every boundary attestation")

    @property
    def alpha_gate_authority(self) -> bool:
        return self.terminal is not USR2Terminal.SYSTEM_FAILURE

    @property
    def alpha_authority(self) -> bool:
        return self.terminal is USR2Terminal.ROBUST_FACTOR_FAMILY

    @property
    def supports_us_x0_progression(self) -> bool:
        return self.alpha_authority

    @property
    def review_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-alpha-gate-review")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "assessment_id": self.assessment_id,
            "inference_graph_id": self.inference_graph_id,
            "reviewer_id": self.reviewer_id,
            "reviewed_at": self.reviewed_at,
            "review_notes": self.review_notes,
            "assessment_terminal": self.assessment_terminal.value,
            "terminal": self.terminal.value,
            "thresholds_unchanged_attested": self.thresholds_unchanged_attested,
            "evidence_lineage_attested": self.evidence_lineage_attested,
            "denominator_preserved_attested": self.denominator_preserved_attested,
            "execution_gate_separation_attested": self.execution_gate_separation_attested,
            "live_capital_separation_attested": self.live_capital_separation_attested,
            "alpha_gate_authority": self.alpha_gate_authority,
            "alpha_authority": self.alpha_authority,
            "supports_us_x0_progression": self.supports_us_x0_progression,
            "status_authority": False,
            "stage_exit_authority": False,
            "execution_authority": False,
            "order_authority": False,
            "paper_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["review_id"] = self.review_id
        return payload


@dataclass(frozen=True, slots=True)
class USR2ReviewedEvidenceManifest:
    frozen_protocol_id: str
    denominator_id: str
    alpha_gate_policy_id: str
    final_family_evidence_id: str
    alpha_gate_assessment_id: str
    inference_graph_id: str
    alpha_gate_review_id: str
    terminal: USR2Terminal
    robust_candidate_ids: tuple[str, ...]
    schema_version: str = "finagent.us-r2-reviewed-evidence-manifest.v1"

    @property
    def manifest_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-reviewed-evidence")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "frozen_protocol_id": self.frozen_protocol_id,
            "denominator_id": self.denominator_id,
            "alpha_gate_policy_id": self.alpha_gate_policy_id,
            "final_family_evidence_id": self.final_family_evidence_id,
            "alpha_gate_assessment_id": self.alpha_gate_assessment_id,
            "inference_graph_id": self.inference_graph_id,
            "alpha_gate_review_id": self.alpha_gate_review_id,
            "terminal": self.terminal.value,
            "robust_candidate_ids": list(self.robust_candidate_ids),
            "alpha_gate_authority": self.terminal is not USR2Terminal.SYSTEM_FAILURE,
            "alpha_authority": self.terminal is USR2Terminal.ROBUST_FACTOR_FAMILY,
            "supports_us_x0_progression": self.terminal is USR2Terminal.ROBUST_FACTOR_FAMILY,
            "execution_authority": False,
            "order_authority": False,
            "paper_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["manifest_id"] = self.manifest_id
        return payload


def finalize_us_r2_alpha_gate_review(
    artifacts: USR2FinalArtifacts,
    *,
    reviewer_id: str,
    reviewed_at: datetime,
    review_notes: str,
    terminal: USR2Terminal | None = None,
) -> tuple[USR2AlphaGateReview, USR2ReviewedEvidenceManifest]:
    chosen = artifacts.assessment.terminal if terminal is None else terminal
    review = USR2AlphaGateReview(
        assessment_id=artifacts.assessment.assessment_id,
        inference_graph_id=artifacts.graph.graph_id,
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at.isoformat(),
        review_notes=review_notes,
        terminal=chosen,
        thresholds_unchanged_attested=True,
        evidence_lineage_attested=True,
        denominator_preserved_attested=True,
        execution_gate_separation_attested=True,
        live_capital_separation_attested=True,
        assessment_terminal=artifacts.assessment.terminal,
    )
    robust_ids = (
        artifacts.assessment.robust_candidate_ids
        if chosen is USR2Terminal.ROBUST_FACTOR_FAMILY
        else ()
    )
    manifest = USR2ReviewedEvidenceManifest(
        frozen_protocol_id=artifacts.policy.frozen_protocol_id,
        denominator_id=artifacts.policy.denominator_id,
        alpha_gate_policy_id=artifacts.policy.policy_id,
        final_family_evidence_id=artifacts.family.evidence_id,
        alpha_gate_assessment_id=artifacts.assessment.assessment_id,
        inference_graph_id=artifacts.graph.graph_id,
        alpha_gate_review_id=review.review_id,
        terminal=chosen,
        robust_candidate_ids=robust_ids,
    )
    return review, manifest

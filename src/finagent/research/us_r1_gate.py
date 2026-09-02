from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from finagent.domain.market_bars import BarInterval
from finagent.research.factor_stability import adjust_family_pvalues
from finagent.research.us_r1_inference import (
    USR1FoldSeries,
    USR1FoldSummary,
    newey_west_mean_test,
    session_block_bootstrap_mean_test,
    summarize_us_r1_fold,
)
from finagent.research.us_r1_protocol import (
    USR1CandidateDenominator,
    USR1ResearchProtocol,
    USR1Terminal,
    canonical_us_r1_research_protocol,
)


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _finite(value: float, field_name: str) -> float:
    rendered = float(value)
    if not math.isfinite(rendered):
        raise ValueError(f"{field_name} must be finite")
    return rendered


def _bounded(value: float, field_name: str) -> float:
    rendered = _finite(value, field_name)
    if not 0.0 <= rendered <= 1.0:
        raise ValueError(f"{field_name} must be in [0,1]")
    return rendered


@dataclass(frozen=True, slots=True)
class USR1RawCandidateEvidence:
    candidate_id: str
    dominant_direction: int
    folds: tuple[USR1FoldSummary, ...]
    primary_mean_rank_ic: float
    worst_fold_rank_ic: float
    mean_fold_rank_icir: float
    worst_fold_rank_icir: float
    positive_fold_ratio: float
    hac_lags: int
    hac_tstat: float
    raw_hac_pvalue: float
    session_bootstrap_pvalue: float
    session_bootstrap_ci_lower: float
    session_bootstrap_ci_upper: float
    mean_long_short_return_bps: float
    mean_one_way_turnover: float
    return_per_turnover_bps: float
    coverage_mean: float
    coverage_min: float
    quantile_monotonicity: float
    frequency_rank_ic: Mapping[str, float]
    frequency_sign_consistency: float
    decay_rank_ic: Mapping[str, float]
    decay_sign_consistency: float
    schema_version: str = "finagent.us-r1-raw-candidate-evidence.v1"

    def __post_init__(self) -> None:
        candidate = self.candidate_id.strip()
        if not candidate:
            raise ValueError("candidate_id must be non-empty")
        object.__setattr__(self, "candidate_id", candidate)
        if self.dominant_direction not in {-1, 1}:
            raise ValueError("dominant_direction must be -1 or 1")
        if len(self.folds) < 3 or len({fold.fold_id for fold in self.folds}) != len(self.folds):
            raise ValueError("US-R1 robust evidence requires at least three unique folds")
        for field_name in (
            "primary_mean_rank_ic",
            "worst_fold_rank_ic",
            "mean_fold_rank_icir",
            "worst_fold_rank_icir",
            "hac_tstat",
            "session_bootstrap_ci_lower",
            "session_bootstrap_ci_upper",
            "mean_long_short_return_bps",
            "mean_one_way_turnover",
            "return_per_turnover_bps",
            "quantile_monotonicity",
        ):
            _finite(getattr(self, field_name), field_name)
        if self.hac_lags < 0:
            raise ValueError("hac_lags must be non-negative")
        for field_name in (
            "positive_fold_ratio",
            "raw_hac_pvalue",
            "session_bootstrap_pvalue",
            "coverage_mean",
            "coverage_min",
            "frequency_sign_consistency",
            "decay_sign_consistency",
        ):
            _bounded(getattr(self, field_name), field_name)
        if self.session_bootstrap_ci_upper < self.session_bootstrap_ci_lower:
            raise ValueError("session bootstrap confidence interval is invalid")
        if self.mean_one_way_turnover < 0:
            raise ValueError("mean_one_way_turnover must be non-negative")
        frequencies = {str(key): _finite(value, f"frequency_rank_ic[{key}]") for key, value in self.frequency_rank_ic.items()}
        if set(frequencies) != {"5m", "15m", "30m"}:
            raise ValueError("US-R1 frequency evidence must be exactly 5m/15m/30m")
        decay = {str(key): _finite(value, f"decay_rank_ic[{key}]") for key, value in self.decay_rank_ic.items()}
        if set(decay) != {"30m", "60m", "120m"}:
            raise ValueError("US-R1 decay evidence must be exactly 30m/60m/120m")
        object.__setattr__(self, "frequency_rank_ic", frequencies)
        object.__setattr__(self, "decay_rank_ic", decay)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "dominant_direction": self.dominant_direction,
            "folds": [fold.to_dict() for fold in self.folds],
            "primary_mean_rank_ic": self.primary_mean_rank_ic,
            "worst_fold_rank_ic": self.worst_fold_rank_ic,
            "mean_fold_rank_icir": self.mean_fold_rank_icir,
            "worst_fold_rank_icir": self.worst_fold_rank_icir,
            "positive_fold_ratio": self.positive_fold_ratio,
            "hac": {"lags": self.hac_lags, "tstat": self.hac_tstat, "raw_pvalue": self.raw_hac_pvalue},
            "session_block_bootstrap": {
                "pvalue": self.session_bootstrap_pvalue,
                "ci_lower": self.session_bootstrap_ci_lower,
                "ci_upper": self.session_bootstrap_ci_upper,
            },
            "mean_long_short_return_bps": self.mean_long_short_return_bps,
            "mean_one_way_turnover": self.mean_one_way_turnover,
            "return_per_turnover_bps": self.return_per_turnover_bps,
            "coverage_mean": self.coverage_mean,
            "coverage_min": self.coverage_min,
            "quantile_monotonicity": self.quantile_monotonicity,
            "frequency_rank_ic": dict(self.frequency_rank_ic),
            "frequency_sign_consistency": self.frequency_sign_consistency,
            "decay_rank_ic": dict(self.decay_rank_ic),
            "decay_sign_consistency": self.decay_sign_consistency,
        }


@dataclass(frozen=True, slots=True)
class USR1CandidateRobustEvidence:
    raw: USR1RawCandidateEvidence
    holm_adjusted_pvalue: float
    bh_qvalue: float
    schema_version: str = "finagent.us-r1-candidate-robust-evidence.v1"

    def __post_init__(self) -> None:
        _bounded(self.holm_adjusted_pvalue, "holm_adjusted_pvalue")
        _bounded(self.bh_qvalue, "bh_qvalue")

    @property
    def candidate_id(self) -> str:
        return self.raw.candidate_id

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "raw": self.raw.to_dict(),
            "candidate_id": self.candidate_id,
            "multiplicity": {
                "raw_hac_pvalue": self.raw.raw_hac_pvalue,
                "holm_adjusted_pvalue": self.holm_adjusted_pvalue,
                "bh_qvalue": self.bh_qvalue,
            },
        }


def build_us_r1_raw_candidate_evidence(
    *,
    candidate_id: str,
    dominant_direction: int,
    primary_folds: Sequence[USR1FoldSeries],
    robustness_rank_ic: Mapping[BarInterval, float],
    decay_rank_ic: Mapping[int, float],
    protocol: USR1ResearchProtocol | None = None,
) -> USR1RawCandidateEvidence:
    active = protocol or canonical_us_r1_research_protocol()
    if dominant_direction not in {-1, 1}:
        raise ValueError("dominant_direction must be -1 or 1")
    folds = tuple(
        summarize_us_r1_fold(fold, direction=dominant_direction)
        for fold in primary_folds
    )
    if len(folds) < 3:
        raise ValueError("US-R1 candidate evidence requires at least three primary folds")
    points = tuple(point for fold in primary_folds for point in fold.points)
    normalized_rank_ic = tuple(dominant_direction * point.rank_ic for point in points)
    normalized_return = tuple(dominant_direction * point.long_short_return_bps for point in points)
    hac_tstat, raw_hac_pvalue = newey_west_mean_test(
        normalized_rank_ic,
        lags=active.hac_lags(active.primary_interval),
    )
    bootstrap_pvalue, ci_lower, ci_upper = session_block_bootstrap_mean_test(
        points,
        direction=dominant_direction,
        samples=active.bootstrap_samples,
        block_sessions=active.bootstrap_block_sessions,
        seed=active.bootstrap_seed,
    )
    primary_mean_rank_ic = float(np.mean(normalized_rank_ic))
    mean_turnover = float(np.mean([point.one_way_turnover for point in points]))
    mean_return = float(np.mean(normalized_return))
    return_per_turnover = mean_return / mean_turnover if mean_turnover > 1e-12 else 0.0
    robustness = {interval: dominant_direction * float(value) for interval, value in robustness_rank_ic.items()}
    if set(robustness) != {BarInterval.MINUTE_5, BarInterval.MINUTE_30}:
        raise ValueError("US-R1 robustness_rank_ic must contain exactly 5m and 30m")
    frequency = {
        "5m": robustness[BarInterval.MINUTE_5],
        "15m": primary_mean_rank_ic,
        "30m": robustness[BarInterval.MINUTE_30],
    }
    decay_normalized = {int(horizon): dominant_direction * float(value) for horizon, value in decay_rank_ic.items()}
    if set(decay_normalized) != {30, 120}:
        raise ValueError("US-R1 decay_rank_ic must contain exactly 30m and 120m")
    decay = {
        "30m": decay_normalized[30],
        "60m": primary_mean_rank_ic,
        "120m": decay_normalized[120],
    }
    return USR1RawCandidateEvidence(
        candidate_id=candidate_id,
        dominant_direction=dominant_direction,
        folds=folds,
        primary_mean_rank_ic=primary_mean_rank_ic,
        worst_fold_rank_ic=min(fold.mean_rank_ic for fold in folds),
        mean_fold_rank_icir=float(np.mean([fold.rank_icir for fold in folds])),
        worst_fold_rank_icir=min(fold.rank_icir for fold in folds),
        positive_fold_ratio=sum(fold.mean_rank_ic > 0.0 for fold in folds) / len(folds),
        hac_lags=active.hac_lags(active.primary_interval),
        hac_tstat=hac_tstat,
        raw_hac_pvalue=raw_hac_pvalue,
        session_bootstrap_pvalue=bootstrap_pvalue,
        session_bootstrap_ci_lower=ci_lower,
        session_bootstrap_ci_upper=ci_upper,
        mean_long_short_return_bps=mean_return,
        mean_one_way_turnover=mean_turnover,
        return_per_turnover_bps=return_per_turnover,
        coverage_mean=float(np.mean([point.coverage for point in points])),
        coverage_min=float(np.min([point.coverage for point in points])),
        quantile_monotonicity=float(
            np.mean([dominant_direction * point.quantile_monotonicity for point in points])
        ),
        frequency_rank_ic=frequency,
        frequency_sign_consistency=sum(value > 0.0 for value in frequency.values()) / 3.0,
        decay_rank_ic=decay,
        decay_sign_consistency=sum(value > 0.0 for value in decay.values()) / 3.0,
    )


@dataclass(frozen=True, slots=True)
class USR1FamilyEvidence:
    protocol_id: str
    denominator_id: str
    candidates: tuple[USR1CandidateRobustEvidence, ...]
    technical_blockers: tuple[str, ...] = ()
    schema_version: str = "finagent.us-r1-family-evidence.v1"

    def __post_init__(self) -> None:
        protocol = canonical_us_r1_research_protocol()
        if self.protocol_id != protocol.protocol_id:
            raise ValueError("US-R1 family evidence/protocol identity mismatch")
        if not self.denominator_id.strip():
            raise ValueError("denominator_id must be non-empty")
        if not self.candidates:
            raise ValueError("US-R1 family evidence requires candidates")
        ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("US-R1 family evidence contains duplicate candidates")
        blockers = tuple(item.strip() for item in self.technical_blockers if item.strip())
        if len(blockers) != len(self.technical_blockers) or len(blockers) != len(set(blockers)):
            raise ValueError("US-R1 technical blockers must be unique and non-empty")
        object.__setattr__(self, "technical_blockers", blockers)

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-family-evidence")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "denominator_id": self.denominator_id,
            "candidate_count": len(self.candidates),
            "candidate_ids": [item.candidate_id for item in self.candidates],
            "candidates": [item.to_dict() for item in self.candidates],
            "technical_blockers": list(self.technical_blockers),
            "multiplicity_semantics": "Holm_and_BH_over_exact_frozen_structural_denominator",
            "status_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


def build_us_r1_family_evidence(
    denominator: USR1CandidateDenominator,
    raw_candidates: Sequence[USR1RawCandidateEvidence],
    *,
    technical_blockers: tuple[str, ...] = (),
) -> USR1FamilyEvidence:
    expected_ids = tuple(item.candidate.candidate_id for item in denominator.candidates)
    by_id = {candidate.candidate_id: candidate for candidate in raw_candidates}
    if len(by_id) != len(raw_candidates):
        raise ValueError("US-R1 raw candidate evidence contains duplicate candidates")
    if set(by_id) != set(expected_ids):
        raise ValueError("US-R1 inference denominator differs from frozen candidate denominator")
    adjusted = adjust_family_pvalues(
        {candidate_id: by_id[candidate_id].raw_hac_pvalue for candidate_id in expected_ids}
    )
    candidates = tuple(
        USR1CandidateRobustEvidence(
            raw=by_id[candidate_id],
            holm_adjusted_pvalue=adjusted[candidate_id][0],
            bh_qvalue=adjusted[candidate_id][1],
        )
        for candidate_id in expected_ids
    )
    return USR1FamilyEvidence(
        protocol_id=denominator.protocol_id,
        denominator_id=denominator.denominator_id,
        candidates=candidates,
        technical_blockers=technical_blockers,
    )


@dataclass(frozen=True, slots=True)
class USR1AlphaGatePolicy:
    protocol_id: str
    min_fold_count: int = 3
    min_primary_mean_rank_ic: float = 0.01
    min_worst_fold_rank_ic: float = 0.0
    min_mean_fold_rank_icir: float = 0.0
    min_worst_fold_rank_icir: float = -0.05
    min_positive_fold_ratio: float = 2.0 / 3.0
    max_raw_hac_pvalue: float = 0.05
    max_holm_adjusted_pvalue: float = 0.10
    max_bh_qvalue: float = 0.10
    max_session_bootstrap_pvalue: float = 0.05
    min_session_bootstrap_ci_lower: float = 0.0
    min_frequency_sign_consistency: float = 2.0 / 3.0
    min_decay_sign_consistency: float = 2.0 / 3.0
    min_coverage: float = 0.80
    min_quantile_monotonicity: float = 0.25
    min_mean_long_short_return_bps: float = 1.0
    max_mean_one_way_turnover: float = 1.0
    min_return_per_turnover_bps: float = 1.0
    schema_version: str = "finagent.us-r1-alpha-gate-policy.v1"

    def __post_init__(self) -> None:
        if self.protocol_id != canonical_us_r1_research_protocol().protocol_id:
            raise ValueError("US-R1 Alpha Gate policy/protocol identity mismatch")
        if self.min_fold_count < 3:
            raise ValueError("US-R1 Alpha Gate requires at least three folds")
        for field_name in (
            "min_primary_mean_rank_ic",
            "min_worst_fold_rank_ic",
            "min_mean_fold_rank_icir",
            "min_worst_fold_rank_icir",
            "min_session_bootstrap_ci_lower",
            "min_quantile_monotonicity",
            "min_mean_long_short_return_bps",
            "max_mean_one_way_turnover",
            "min_return_per_turnover_bps",
        ):
            _finite(getattr(self, field_name), field_name)
        for field_name in (
            "min_positive_fold_ratio",
            "max_raw_hac_pvalue",
            "max_holm_adjusted_pvalue",
            "max_bh_qvalue",
            "max_session_bootstrap_pvalue",
            "min_frequency_sign_consistency",
            "min_decay_sign_consistency",
            "min_coverage",
        ):
            _bounded(getattr(self, field_name), field_name)
        if self.max_mean_one_way_turnover < 0:
            raise ValueError("max_mean_one_way_turnover must be non-negative")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-alpha-gate-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "min_fold_count": self.min_fold_count,
            "min_primary_mean_rank_ic": self.min_primary_mean_rank_ic,
            "min_worst_fold_rank_ic": self.min_worst_fold_rank_ic,
            "min_mean_fold_rank_icir": self.min_mean_fold_rank_icir,
            "min_worst_fold_rank_icir": self.min_worst_fold_rank_icir,
            "min_positive_fold_ratio": self.min_positive_fold_ratio,
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
            "positive_terminal": USR1Terminal.ROBUST_FACTOR_FAMILY.value,
            "negative_terminal": USR1Terminal.NO_ROBUST_FACTOR_FAMILY.value,
            "technical_terminal": USR1Terminal.SYSTEM_FAILURE.value,
            "execution_cost_boundary": (
                "gross_research_economic_floor_only_exact_cfd_costs_deferred_to_US-X0_X1"
            ),
            "status_authority": False,
            "stage_exit_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


def canonical_us_r1_alpha_gate_policy() -> USR1AlphaGatePolicy:
    return USR1AlphaGatePolicy(protocol_id=canonical_us_r1_research_protocol().protocol_id)


@dataclass(frozen=True, slots=True)
class USR1CandidateGateAssessment:
    candidate_id: str
    passed: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"candidate_id": self.candidate_id, "passed": self.passed, "reasons": list(self.reasons)}


def _candidate_gate(
    candidate: USR1CandidateRobustEvidence,
    policy: USR1AlphaGatePolicy,
) -> USR1CandidateGateAssessment:
    raw = candidate.raw
    checks = (
        (len(raw.folds) >= policy.min_fold_count, "FOLD_COUNT_BELOW_THRESHOLD"),
        (raw.primary_mean_rank_ic >= policy.min_primary_mean_rank_ic, "PRIMARY_MEAN_RANK_IC_BELOW_THRESHOLD"),
        (raw.worst_fold_rank_ic >= policy.min_worst_fold_rank_ic, "WORST_FOLD_RANK_IC_BELOW_THRESHOLD"),
        (raw.mean_fold_rank_icir >= policy.min_mean_fold_rank_icir, "MEAN_FOLD_RANK_ICIR_BELOW_THRESHOLD"),
        (raw.worst_fold_rank_icir >= policy.min_worst_fold_rank_icir, "WORST_FOLD_RANK_ICIR_BELOW_THRESHOLD"),
        (raw.positive_fold_ratio >= policy.min_positive_fold_ratio, "POSITIVE_FOLD_RATIO_BELOW_THRESHOLD"),
        (raw.raw_hac_pvalue <= policy.max_raw_hac_pvalue, "HAC_NOT_SIGNIFICANT"),
        (candidate.holm_adjusted_pvalue <= policy.max_holm_adjusted_pvalue, "HOLM_ADJUSTED_PVALUE_ABOVE_THRESHOLD"),
        (candidate.bh_qvalue <= policy.max_bh_qvalue, "BH_QVALUE_ABOVE_THRESHOLD"),
        (raw.session_bootstrap_pvalue <= policy.max_session_bootstrap_pvalue, "SESSION_BOOTSTRAP_NOT_SIGNIFICANT"),
        (raw.session_bootstrap_ci_lower > policy.min_session_bootstrap_ci_lower, "SESSION_BOOTSTRAP_CI_CROSSES_ZERO"),
        (raw.frequency_sign_consistency >= policy.min_frequency_sign_consistency, "FREQUENCY_SIGN_INCONSISTENT"),
        (raw.decay_sign_consistency >= policy.min_decay_sign_consistency, "DECAY_SIGN_INCONSISTENT"),
        (raw.coverage_min >= policy.min_coverage, "COVERAGE_BELOW_THRESHOLD"),
        (raw.quantile_monotonicity >= policy.min_quantile_monotonicity, "QUANTILE_MONOTONICITY_BELOW_THRESHOLD"),
        (raw.mean_long_short_return_bps >= policy.min_mean_long_short_return_bps, "GROSS_LONG_SHORT_RETURN_BELOW_THRESHOLD"),
        (raw.mean_one_way_turnover <= policy.max_mean_one_way_turnover, "TURNOVER_ABOVE_THRESHOLD"),
        (raw.return_per_turnover_bps >= policy.min_return_per_turnover_bps, "RETURN_PER_TURNOVER_BELOW_THRESHOLD"),
    )
    reasons = tuple(reason for passed, reason in checks if not passed)
    return USR1CandidateGateAssessment(candidate_id=candidate.candidate_id, passed=not reasons, reasons=reasons)


@dataclass(frozen=True, slots=True)
class USR1AlphaGateAssessment:
    policy_id: str
    family_evidence_id: str
    denominator_id: str
    terminal: USR1Terminal
    candidates: tuple[USR1CandidateGateAssessment, ...]
    robust_candidate_ids: tuple[str, ...]
    technical_blockers: tuple[str, ...]
    schema_version: str = "finagent.us-r1-alpha-gate-assessment.v1"

    def __post_init__(self) -> None:
        for field_name in ("policy_id", "family_evidence_id", "denominator_id"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must be non-empty")
        if not self.candidates:
            raise ValueError("US-R1 Alpha Gate assessment requires candidates")
        if len(self.robust_candidate_ids) != len(set(self.robust_candidate_ids)):
            raise ValueError("robust_candidate_ids must be unique")
        if self.terminal is USR1Terminal.ROBUST_FACTOR_FAMILY and not self.robust_candidate_ids:
            raise ValueError("ROBUST_FACTOR_FAMILY requires passing candidate IDs")
        if self.terminal is USR1Terminal.NO_ROBUST_FACTOR_FAMILY and self.robust_candidate_ids:
            raise ValueError("NO_ROBUST_FACTOR_FAMILY cannot contain passing candidate IDs")
        if self.terminal is USR1Terminal.SYSTEM_FAILURE and not self.technical_blockers:
            raise ValueError("SYSTEM_FAILURE requires technical blockers")

    @property
    def assessment_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-alpha-gate-assessment")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "family_evidence_id": self.family_evidence_id,
            "denominator_id": self.denominator_id,
            "terminal": self.terminal.value,
            "candidates": [item.to_dict() for item in self.candidates],
            "robust_candidate_ids": list(self.robust_candidate_ids),
            "technical_blockers": list(self.technical_blockers),
            "recommendation_authority": "deterministic_preregistered_policy_only",
            "status_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["assessment_id"] = self.assessment_id
        return payload


def assess_us_r1_alpha_gate(
    family: USR1FamilyEvidence,
    policy: USR1AlphaGatePolicy | None = None,
) -> USR1AlphaGateAssessment:
    active = policy or canonical_us_r1_alpha_gate_policy()
    if family.protocol_id != active.protocol_id:
        raise ValueError("US-R1 Alpha Gate family/policy protocol mismatch")
    candidates = tuple(_candidate_gate(candidate, active) for candidate in family.candidates)
    passing = tuple(item.candidate_id for item in candidates if item.passed)
    if family.technical_blockers:
        terminal = USR1Terminal.SYSTEM_FAILURE
        passing = ()
    elif passing:
        terminal = USR1Terminal.ROBUST_FACTOR_FAMILY
    else:
        terminal = USR1Terminal.NO_ROBUST_FACTOR_FAMILY
    return USR1AlphaGateAssessment(
        policy_id=active.policy_id,
        family_evidence_id=family.evidence_id,
        denominator_id=family.denominator_id,
        terminal=terminal,
        candidates=candidates,
        robust_candidate_ids=passing,
        technical_blockers=family.technical_blockers,
    )


@dataclass(frozen=True, slots=True)
class USR1AlphaGateReview:
    assessment: USR1AlphaGateAssessment
    reviewer_id: str
    reviewed_at: datetime
    terminal: USR1Terminal
    review_notes: str
    thresholds_unchanged_attested: bool
    evidence_lineage_attested: bool
    agent_value_gate_separation_attested: bool
    execution_gate_separation_attested: bool
    live_capital_separation_attested: bool
    schema_version: str = "finagent.us-r1-alpha-gate-review.v1"

    def __post_init__(self) -> None:
        reviewer = self.reviewer_id.strip()
        notes = self.review_notes.strip()
        if not reviewer:
            raise ValueError("reviewer_id must be non-empty")
        if not notes or len(notes) > 2000:
            raise ValueError("review_notes must contain 1..2000 characters")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        object.__setattr__(self, "reviewer_id", reviewer)
        object.__setattr__(self, "review_notes", notes)
        object.__setattr__(self, "reviewed_at", self.reviewed_at.astimezone(UTC))
        if not all(
            (
                self.thresholds_unchanged_attested,
                self.evidence_lineage_attested,
                self.agent_value_gate_separation_attested,
                self.execution_gate_separation_attested,
                self.live_capital_separation_attested,
            )
        ):
            raise ValueError("all US-R1 Alpha Gate review attestations must be true")
        allowed = {self.assessment.terminal, USR1Terminal.SYSTEM_FAILURE}
        if self.terminal not in allowed:
            raise ValueError("US-R1 reviewer may accept the assessment or downgrade to SYSTEM_FAILURE only")
        if self.terminal is USR1Terminal.SYSTEM_FAILURE and self.assessment.terminal is not USR1Terminal.SYSTEM_FAILURE and len(notes) < 20:
            raise ValueError("downgrading US-R1 review to SYSTEM_FAILURE requires substantive notes")

    @property
    def review_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-alpha-gate-review")

    @property
    def supports_us_x0_progression(self) -> bool:
        return self.terminal is USR1Terminal.ROBUST_FACTOR_FAMILY

    @property
    def alpha_authority(self) -> bool:
        return True

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "assessment": self.assessment.to_dict(),
            "assessment_id": self.assessment.assessment_id,
            "reviewer_id": self.reviewer_id,
            "reviewed_at": self.reviewed_at.isoformat(),
            "terminal": self.terminal.value,
            "review_notes": self.review_notes,
            "attestations": {
                "thresholds_unchanged_after_results": self.thresholds_unchanged_attested,
                "evidence_lineage_verified": self.evidence_lineage_attested,
                "agent_value_gate_is_separate": self.agent_value_gate_separation_attested,
                "cfd_execution_gate_is_separate": self.execution_gate_separation_attested,
                "live_capital_gate_is_separate": self.live_capital_separation_attested,
            },
            "supports_us_x0_progression": self.supports_us_x0_progression,
            "alpha_authority": self.alpha_authority,
            "status_authority": False,
            "stage_exit_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["review_id"] = self.review_id
        return payload


def finalize_us_r1_alpha_gate_review(
    assessment: USR1AlphaGateAssessment,
    *,
    reviewer_id: str,
    reviewed_at: datetime,
    review_notes: str,
    terminal: USR1Terminal | None = None,
    thresholds_unchanged_attested: bool,
    evidence_lineage_attested: bool,
    agent_value_gate_separation_attested: bool,
    execution_gate_separation_attested: bool,
    live_capital_separation_attested: bool,
) -> USR1AlphaGateReview:
    return USR1AlphaGateReview(
        assessment=assessment,
        reviewer_id=reviewer_id,
        reviewed_at=reviewed_at,
        terminal=assessment.terminal if terminal is None else terminal,
        review_notes=review_notes,
        thresholds_unchanged_attested=thresholds_unchanged_attested,
        evidence_lineage_attested=evidence_lineage_attested,
        agent_value_gate_separation_attested=agent_value_gate_separation_attested,
        execution_gate_separation_attested=execution_gate_separation_attested,
        live_capital_separation_attested=live_capital_separation_attested,
    )

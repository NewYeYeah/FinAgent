from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from finagent.domain.market_bars import BarInterval
from finagent.research.factor_stability import adjust_family_pvalues
from finagent.research.us_r1_inference import (
    USR1PeriodMetricPoint,
    newey_west_mean_test,
    session_block_bootstrap_mean_test,
)
from finagent.research.us_r1_protocol import (
    USR1CandidateDenominator,
    canonical_us_r1_research_protocol,
)
from finagent.research.us_r2_candidate_cache import validate_us_r2_candidate_denominator
from finagent.research.us_r2_evaluation_policy import (
    USR2StatisticalEvaluationPolicy,
    canonical_us_r2_statistical_evaluation_policy,
)
from finagent.research.us_r2_frozen_protocol import FROZEN_REGIME_LABELS
from finagent.research.us_r2_primary_runtime import parse_us_r2_primary_direction_evidence
from finagent.research.us_r2_primary_statistics import (
    FROZEN_CANDIDATE_COUNT,
    METRIC_AVAILABLE,
    PRIMARY_METRIC_FILENAME,
    USR2AnnualPrimaryMetricArrays,
    USR2AnnualPrimaryMetricEvidence,
    USR2PrimaryDirectionEvidenceSet,
    USR2PrimaryStatisticsPlan,
    _days_to_date,
    _integer,
    _mapping,
    _sequence,
    _text,
    _us_to_datetime,
    load_us_r2_primary_metric_npz,
    parse_us_r2_annual_primary_metric_evidence,
)

FROZEN_PRIMARY_EVALUATION_POLICY_ID = "us-r2-statistical-evaluation-policy-385ae550f8a69dc0bcbcd9b2"
FROZEN_PRIMARY_STATISTICS_PLAN_ID = "us-r2-primary-statistics-plan-d52413a72d50cd2bf0b0b1a4"
FROZEN_PRIMARY_DIRECTION_EVIDENCE_ID = "us-r2-primary-direction-set-baf85b7070311daad95e7ada"
FROZEN_PRIMARY_STATISTICS_REPORT_ID = "us-r2-primary-statistics-39329ed645222038a8e29fef"
POOLED_INFERENCE_REPORT_FILENAME = "us_r2_pooled_inference_report.json"
POOLED_INFERENCE_YEARS = tuple(range(2006, 2027))


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _rehash_document(document: Mapping[str, object], *, id_field: str, prefix: str) -> str:
    claimed = _text(document.get(id_field), id_field)
    payload = dict(document)
    del payload[id_field]
    if claimed != _canonical_hash(payload, prefix=prefix):
        raise ValueError(f"{id_field} content-addressed identity mismatch")
    return claimed


def parse_us_r2_primary_statistics_plan(
    document: Mapping[str, object],
    denominator: USR1CandidateDenominator,
) -> USR2PrimaryStatisticsPlan:
    candidate_ids = tuple(
        _text(item, "candidate_ids[]")
        for item in _sequence(document.get("candidate_ids"), "candidate_ids")
    )
    plan = USR2PrimaryStatisticsPlan(
        frozen_protocol_id=_text(document.get("frozen_protocol_id"), "frozen_protocol_id"),
        evaluation_policy_id=_text(document.get("evaluation_policy_id"), "evaluation_policy_id"),
        candidate_cache_batch_evidence_id=_text(
            document.get("candidate_cache_batch_evidence_id"),
            "candidate_cache_batch_evidence_id",
        ),
        candidate_cache_plan_id=_text(
            document.get("candidate_cache_plan_id"), "candidate_cache_plan_id"
        ),
        compiled_candidate_batch_id=_text(
            document.get("compiled_candidate_batch_id"), "compiled_candidate_batch_id"
        ),
        regime_projection_evidence_id=_text(
            document.get("regime_projection_evidence_id"), "regime_projection_evidence_id"
        ),
        denominator_id=_text(document.get("denominator_id"), "denominator_id"),
        candidate_ids=candidate_ids,
    )
    if dict(document) != plan.to_dict():
        raise ValueError("US-R2 primary statistics plan differs from its canonical content")
    expected_ids = tuple(item.candidate.candidate_id for item in denominator.candidates)
    if candidate_ids != expected_ids:
        raise ValueError("US-R2 pooled inference denominator/order differs from frozen R1")
    if plan.denominator_id != denominator.denominator_id:
        raise ValueError("US-R2 primary statistics plan/denominator identity mismatch")
    if plan.plan_id != FROZEN_PRIMARY_STATISTICS_PLAN_ID:
        raise ValueError("US-R2 pooled inference requires the reviewed primary-statistics plan")
    if plan.evaluation_policy_id != FROZEN_PRIMARY_EVALUATION_POLICY_ID:
        raise ValueError("US-R2 pooled inference primary evaluation-policy identity mismatch")
    return plan


@dataclass(frozen=True, slots=True)
class USR2PrimaryStatisticsReportGate:
    report_id: str
    plan_id: str
    evaluation_policy_id: str
    direction_evidence_id: str
    annual_metric_evidence_ids: tuple[str, ...]
    slice_count: int


def validate_us_r2_primary_statistics_report_gate(
    document: Mapping[str, object],
    *,
    plan: USR2PrimaryStatisticsPlan,
    direction: USR2PrimaryDirectionEvidenceSet,
    policy: USR2StatisticalEvaluationPolicy,
) -> USR2PrimaryStatisticsReportGate:
    if _text(document.get("schema_version"), "schema_version") != (
        "finagent.us-r2-primary-statistics-report.v1"
    ):
        raise ValueError("US-R2 pooled inference requires primary statistics report v1")
    report_id = _rehash_document(
        document,
        id_field="report_id",
        prefix="us-r2-primary-statistics",
    )
    if report_id != FROZEN_PRIMARY_STATISTICS_REPORT_ID:
        raise ValueError("US-R2 pooled inference requires the reviewed real primary report")
    if _text(document.get("plan_id"), "plan_id") != plan.plan_id:
        raise ValueError("US-R2 primary report/plan identity mismatch")
    if _text(document.get("evaluation_policy_id"), "evaluation_policy_id") != policy.policy_id:
        raise ValueError("US-R2 primary report/evaluation-policy identity mismatch")
    if _text(document.get("direction_evidence_id"), "direction_evidence_id") != direction.evidence_id:
        raise ValueError("US-R2 primary report/direction identity mismatch")
    if document.get("passed") is not True or document.get("blockers") != []:
        raise ValueError("US-R2 primary report must be passed and blocker-free")
    slice_count = _integer(document.get("slice_count"), "slice_count")
    expected_slice_count = FROZEN_CANDIDATE_COUNT * policy.required_primary_cell_count
    if slice_count != expected_slice_count:
        raise ValueError("US-R2 primary report does not contain the exact 740-cell denominator")
    raw_slices = _sequence(document.get("slices"), "slices")
    if len(raw_slices) != slice_count:
        raise ValueError("US-R2 primary report slice_count/content mismatch")
    expected_keys = {
        (candidate_id, fold_id, regime)
        for candidate_id in plan.candidate_ids
        for fold_id in ("us-r2-fold-01", "us-r2-fold-02", "us-r2-fold-03", "us-r2-fold-04", "us-r2-fold-05")
        for regime in FROZEN_REGIME_LABELS
    }
    observed_keys: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(raw_slices):
        item = _mapping(raw, f"slices[{index}]")
        key = (
            _text(item.get("candidate_id"), "candidate_id"),
            _text(item.get("fold_id"), "fold_id"),
            _text(item.get("regime"), "regime"),
        )
        if key in observed_keys:
            raise ValueError("US-R2 primary report repeats a candidate/fold/regime cell")
        observed_keys.add(key)
        if item.get("passed") is not True or item.get("blockers") != []:
            raise ValueError("US-R2 pooled inference cannot admit a blocked primary cell")
        if _integer(item.get("direction"), "direction") != direction.direction(key[0]):
            raise ValueError("US-R2 primary report cell direction differs from frozen direction")
        if _integer(item.get("period_count"), "period_count") < policy.minimum_oos_periods_per_fold_regime:
            raise ValueError("US-R2 primary report cell violates the frozen period floor")
        if _integer(item.get("session_count"), "session_count") < policy.minimum_oos_sessions_per_fold_regime:
            raise ValueError("US-R2 primary report cell violates the frozen session floor")
    if observed_keys != expected_keys:
        raise ValueError("US-R2 primary report cell key set differs from 37 x 5 x 4")
    annual_ids = tuple(
        _text(item, "annual_metric_evidence_ids[]")
        for item in _sequence(
            document.get("annual_metric_evidence_ids"), "annual_metric_evidence_ids"
        )
    )
    if len(annual_ids) != len(POOLED_INFERENCE_YEARS) or len(set(annual_ids)) != len(annual_ids):
        raise ValueError("US-R2 primary report annual metric evidence denominator is incomplete")
    for field_name in (
        "hac_bootstrap_multiplicity_evaluated",
        "frequency_robustness_evaluated",
        "decay_robustness_evaluated",
        "alpha_gate_evaluated",
        "terminal_authority",
        "stage_exit_authority",
        "alpha_authority",
        "execution_authority",
    ):
        if document.get(field_name) is not False:
            raise ValueError(f"US-R2 primary report unexpectedly grants/evaluates {field_name}")
    return USR2PrimaryStatisticsReportGate(
        report_id=report_id,
        plan_id=plan.plan_id,
        evaluation_policy_id=policy.policy_id,
        direction_evidence_id=direction.evidence_id,
        annual_metric_evidence_ids=annual_ids,
        slice_count=slice_count,
    )


def validate_and_load_us_r2_primary_metric_year(
    *,
    year: int,
    data_path: Path,
    evidence_document: Mapping[str, object],
    expected_evidence_id: str,
    plan: USR2PrimaryStatisticsPlan,
) -> tuple[USR2AnnualPrimaryMetricArrays, USR2AnnualPrimaryMetricEvidence]:
    if year not in POOLED_INFERENCE_YEARS:
        raise ValueError("US-R2 pooled inference year falls outside 2006-2026")
    evidence = parse_us_r2_annual_primary_metric_evidence(evidence_document)
    if evidence.evidence_id != expected_evidence_id:
        raise ValueError(f"US-R2 primary annual evidence identity mismatch for {year}")
    if evidence.year != year or evidence.plan_id != plan.plan_id or not evidence.passed:
        raise ValueError(f"US-R2 primary annual evidence is not admitted for {year}")
    target = data_path.expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(f"US-R2 primary metric NPZ is missing for {year}: {target}")
    if target.name != PRIMARY_METRIC_FILENAME or evidence.output_filename != target.name:
        raise ValueError("US-R2 primary metric annual filename differs from the frozen layout")
    if target.stat().st_size != evidence.output_size_bytes:
        raise ValueError(f"US-R2 primary metric NPZ size mismatch for {year}")
    if _sha256_file(target) != evidence.content_sha256:
        raise ValueError(f"US-R2 primary metric NPZ SHA-256 mismatch for {year}")
    arrays = load_us_r2_primary_metric_npz(target, candidate_count=len(plan.candidate_ids))
    if arrays.row_count != evidence.metric_formation_count:
        raise ValueError(f"US-R2 primary metric row count mismatch for {year}")
    counts = np.bincount(arrays.status_codes.ravel(), minlength=6)
    if int(counts[METRIC_AVAILABLE]) != evidence.available_metric_count:
        raise ValueError(f"US-R2 primary metric available count mismatch for {year}")
    if arrays.row_count > 1 and np.any(arrays.formation_at_us[1:] <= arrays.formation_at_us[:-1]):
        raise ValueError(f"US-R2 primary metric formation clock is not strictly ordered for {year}")
    return arrays, evidence


def collect_us_r2_pooled_candidate_points(
    annual_arrays: Sequence[tuple[int, USR2AnnualPrimaryMetricArrays]],
    *,
    candidate_slot: int,
) -> tuple[tuple[USR1PeriodMetricPoint, ...], tuple[int, ...]]:
    if tuple(year for year, _arrays in annual_arrays) != POOLED_INFERENCE_YEARS:
        raise ValueError("US-R2 pooled inference requires annual metric caches in exact 2006-2026 order")
    if candidate_slot < 0:
        raise ValueError("candidate_slot must be non-negative")
    points: list[USR1PeriodMetricPoint] = []
    regime_codes: list[int] = []
    previous_formation: int | None = None
    for year, arrays in annual_arrays:
        if candidate_slot >= arrays.candidate_count:
            raise ValueError("candidate_slot exceeds primary metric candidate width")
        if arrays.row_count and previous_formation is not None:
            if int(arrays.formation_at_us[0]) <= previous_formation:
                raise ValueError("US-R2 pooled metric years overlap or are out of chronological order")
        available_indices = np.flatnonzero(arrays.status_codes[:, candidate_slot] == METRIC_AVAILABLE)
        for index in available_indices:
            formation_us = int(arrays.formation_at_us[index])
            if previous_formation is not None and formation_us <= previous_formation:
                raise ValueError("US-R2 pooled candidate points are not strictly chronological")
            previous_formation = formation_us
            regime_code = int(arrays.regime_codes[index])
            if not 0 <= regime_code < len(FROZEN_REGIME_LABELS):
                raise ValueError("US-R2 pooled candidate point has invalid regime code")
            points.append(
                USR1PeriodMetricPoint(
                    event_time=_us_to_datetime(formation_us),
                    session_id=_days_to_date(int(arrays.session_date_days[index])).isoformat(),
                    rank_ic=float(arrays.rank_ic[index, candidate_slot]),
                    long_short_return_bps=float(
                        arrays.long_short_return_bps[index, candidate_slot]
                    ),
                    one_way_turnover=float(arrays.one_way_turnover[index, candidate_slot]),
                    coverage=float(arrays.coverage[index, candidate_slot]),
                    quantile_monotonicity=float(
                        arrays.quantile_monotonicity[index, candidate_slot]
                    ),
                )
            )
            regime_codes.append(regime_code)
        if arrays.row_count:
            previous_formation = int(arrays.formation_at_us[-1])
    return tuple(points), tuple(regime_codes)


def _long_short_bootstrap_points(
    points: Sequence[USR1PeriodMetricPoint],
) -> tuple[USR1PeriodMetricPoint, ...]:
    return tuple(
        USR1PeriodMetricPoint(
            event_time=point.event_time,
            session_id=point.session_id,
            rank_ic=point.long_short_return_bps,
            long_short_return_bps=point.long_short_return_bps,
            one_way_turnover=point.one_way_turnover,
            coverage=point.coverage,
            quantile_monotonicity=point.quantile_monotonicity,
        )
        for point in points
    )


@dataclass(frozen=True, slots=True)
class USR2RawPooledCandidateInference:
    candidate_id: str
    direction: int
    period_count: int
    session_count: int
    regime_period_counts: tuple[tuple[str, int], ...]
    mean_directed_rank_ic: float
    rank_ic_hac_lags: int
    rank_ic_hac_tstat: float
    rank_ic_raw_hac_pvalue: float
    rank_ic_bootstrap_pvalue: float
    rank_ic_bootstrap_ci_lower: float
    rank_ic_bootstrap_ci_upper: float
    mean_directed_long_short_return_bps: float
    long_short_hac_tstat: float
    long_short_raw_hac_pvalue: float
    long_short_bootstrap_pvalue: float
    long_short_bootstrap_ci_lower_bps: float
    long_short_bootstrap_ci_upper_bps: float
    mean_one_way_turnover: float
    return_per_turnover_bps: float
    coverage_mean: float
    coverage_min: float
    directed_quantile_monotonicity: float
    schema_version: str = "finagent.us-r2-raw-pooled-candidate-inference.v1"

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or self.direction not in {-1, 1}:
            raise ValueError("US-R2 pooled candidate identity/direction is invalid")
        if self.period_count < 1 or self.session_count < 1:
            raise ValueError("US-R2 pooled candidate inference requires periods and sessions")
        if tuple(name for name, _count in self.regime_period_counts) != FROZEN_REGIME_LABELS:
            raise ValueError("US-R2 pooled candidate regime count order differs from frozen labels")
        for _name, count in self.regime_period_counts:
            if count < 1:
                raise ValueError("US-R2 pooled candidate must retain every frozen regime")
        for field_name in (
            "mean_directed_rank_ic",
            "rank_ic_hac_tstat",
            "rank_ic_bootstrap_ci_lower",
            "rank_ic_bootstrap_ci_upper",
            "mean_directed_long_short_return_bps",
            "long_short_hac_tstat",
            "long_short_bootstrap_ci_lower_bps",
            "long_short_bootstrap_ci_upper_bps",
            "mean_one_way_turnover",
            "return_per_turnover_bps",
            "coverage_mean",
            "coverage_min",
            "directed_quantile_monotonicity",
        ):
            _finite(getattr(self, field_name), field_name)
        for field_name in (
            "rank_ic_raw_hac_pvalue",
            "rank_ic_bootstrap_pvalue",
            "long_short_raw_hac_pvalue",
            "long_short_bootstrap_pvalue",
            "coverage_mean",
            "coverage_min",
        ):
            _bounded(getattr(self, field_name), field_name)
        if self.mean_one_way_turnover < 0.0:
            raise ValueError("US-R2 pooled turnover must be non-negative")
        if self.rank_ic_bootstrap_ci_upper < self.rank_ic_bootstrap_ci_lower:
            raise ValueError("US-R2 RankIC bootstrap interval is invalid")
        if self.long_short_bootstrap_ci_upper_bps < self.long_short_bootstrap_ci_lower_bps:
            raise ValueError("US-R2 long-short bootstrap interval is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "direction": self.direction,
            "period_count": self.period_count,
            "session_count": self.session_count,
            "regime_period_counts": dict(self.regime_period_counts),
            "mean_directed_rank_ic": self.mean_directed_rank_ic,
            "rank_ic_inference": {
                "hac_lags": self.rank_ic_hac_lags,
                "hac_tstat": self.rank_ic_hac_tstat,
                "raw_hac_pvalue": self.rank_ic_raw_hac_pvalue,
                "session_block_bootstrap_pvalue": self.rank_ic_bootstrap_pvalue,
                "session_block_bootstrap_ci_lower": self.rank_ic_bootstrap_ci_lower,
                "session_block_bootstrap_ci_upper": self.rank_ic_bootstrap_ci_upper,
            },
            "mean_directed_long_short_return_bps": self.mean_directed_long_short_return_bps,
            "long_short_diagnostic_inference": {
                "hac_lags": self.rank_ic_hac_lags,
                "hac_tstat": self.long_short_hac_tstat,
                "raw_hac_pvalue": self.long_short_raw_hac_pvalue,
                "session_block_bootstrap_pvalue": self.long_short_bootstrap_pvalue,
                "session_block_bootstrap_ci_lower_bps": self.long_short_bootstrap_ci_lower_bps,
                "session_block_bootstrap_ci_upper_bps": self.long_short_bootstrap_ci_upper_bps,
                "multiplicity_applied": False,
                "gate_authority": False,
            },
            "mean_one_way_turnover": self.mean_one_way_turnover,
            "return_per_turnover_bps": self.return_per_turnover_bps,
            "coverage_mean": self.coverage_mean,
            "coverage_min": self.coverage_min,
            "directed_quantile_monotonicity": self.directed_quantile_monotonicity,
        }


def build_us_r2_raw_pooled_candidate_inference(
    *,
    candidate_id: str,
    direction: int,
    points: Sequence[USR1PeriodMetricPoint],
    regime_codes: Sequence[int],
    policy: USR2StatisticalEvaluationPolicy | None = None,
) -> USR2RawPooledCandidateInference:
    active = policy or canonical_us_r2_statistical_evaluation_policy()
    if len(points) != len(regime_codes):
        raise ValueError("US-R2 pooled points/regime metadata length mismatch")
    minimum_periods = active.required_primary_cell_count * active.minimum_oos_periods_per_fold_regime
    minimum_sessions = active.required_primary_cell_count * active.minimum_oos_sessions_per_fold_regime
    if len(points) < minimum_periods:
        raise ValueError(f"US-R2 pooled primary periods are incomplete: {len(points)}<{minimum_periods}")
    session_count = len({point.session_id for point in points})
    if session_count < minimum_sessions:
        raise ValueError(
            f"US-R2 pooled primary sessions are incomplete: {session_count}<{minimum_sessions}"
        )
    regime_counts = tuple(
        (label, sum(int(code) == index for code in regime_codes))
        for index, label in enumerate(FROZEN_REGIME_LABELS)
    )
    minimum_per_regime = active.required_fold_count * active.minimum_oos_periods_per_fold_regime
    if any(count < minimum_per_regime for _label, count in regime_counts):
        raise ValueError("US-R2 pooled primary series violates the inherited per-regime period floor")
    r1 = canonical_us_r1_research_protocol()
    hac_lags = r1.hac_lags(BarInterval.MINUTE_15)
    directed_rank_ic = tuple(direction * point.rank_ic for point in points)
    rank_hac_tstat, rank_raw_pvalue = newey_west_mean_test(directed_rank_ic, lags=hac_lags)
    rank_boot_pvalue, rank_ci_lower, rank_ci_upper = session_block_bootstrap_mean_test(
        points,
        direction=direction,
        samples=r1.bootstrap_samples,
        block_sessions=r1.bootstrap_block_sessions,
        seed=r1.bootstrap_seed,
    )
    directed_long_short = tuple(direction * point.long_short_return_bps for point in points)
    long_hac_tstat, long_raw_pvalue = newey_west_mean_test(
        directed_long_short,
        lags=hac_lags,
    )
    long_boot_pvalue, long_ci_lower, long_ci_upper = session_block_bootstrap_mean_test(
        _long_short_bootstrap_points(points),
        direction=direction,
        samples=r1.bootstrap_samples,
        block_sessions=r1.bootstrap_block_sessions,
        seed=r1.bootstrap_seed,
    )
    mean_turnover = float(np.mean([point.one_way_turnover for point in points]))
    mean_return = float(np.mean(np.asarray(directed_long_short, dtype=np.float64)))
    return_per_turnover = mean_return / mean_turnover if mean_turnover > 1e-12 else 0.0
    return USR2RawPooledCandidateInference(
        candidate_id=candidate_id,
        direction=direction,
        period_count=len(points),
        session_count=session_count,
        regime_period_counts=regime_counts,
        mean_directed_rank_ic=float(np.mean(np.asarray(directed_rank_ic, dtype=np.float64))),
        rank_ic_hac_lags=hac_lags,
        rank_ic_hac_tstat=rank_hac_tstat,
        rank_ic_raw_hac_pvalue=rank_raw_pvalue,
        rank_ic_bootstrap_pvalue=rank_boot_pvalue,
        rank_ic_bootstrap_ci_lower=rank_ci_lower,
        rank_ic_bootstrap_ci_upper=rank_ci_upper,
        mean_directed_long_short_return_bps=mean_return,
        long_short_hac_tstat=long_hac_tstat,
        long_short_raw_hac_pvalue=long_raw_pvalue,
        long_short_bootstrap_pvalue=long_boot_pvalue,
        long_short_bootstrap_ci_lower_bps=long_ci_lower,
        long_short_bootstrap_ci_upper_bps=long_ci_upper,
        mean_one_way_turnover=mean_turnover,
        return_per_turnover_bps=return_per_turnover,
        coverage_mean=float(np.mean([point.coverage for point in points])),
        coverage_min=float(np.min([point.coverage for point in points])),
        directed_quantile_monotonicity=float(
            np.mean([direction * point.quantile_monotonicity for point in points])
        ),
    )


@dataclass(frozen=True, slots=True)
class USR2PooledCandidateInference:
    raw: USR2RawPooledCandidateInference
    holm_adjusted_rank_ic_pvalue: float
    bh_rank_ic_qvalue: float
    schema_version: str = "finagent.us-r2-pooled-candidate-inference.v1"

    def __post_init__(self) -> None:
        _bounded(self.holm_adjusted_rank_ic_pvalue, "holm_adjusted_rank_ic_pvalue")
        _bounded(self.bh_rank_ic_qvalue, "bh_rank_ic_qvalue")

    @property
    def candidate_id(self) -> str:
        return self.raw.candidate_id

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "raw": self.raw.to_dict(),
            "multiplicity": {
                "method_denominator": "all_37_frozen_r1_candidates",
                "raw_rank_ic_hac_pvalue": self.raw.rank_ic_raw_hac_pvalue,
                "holm_adjusted_rank_ic_pvalue": self.holm_adjusted_rank_ic_pvalue,
                "bh_rank_ic_qvalue": self.bh_rank_ic_qvalue,
                "candidate_selection_before_adjustment": False,
            },
        }


def adjust_us_r2_pooled_rank_ic_pvalues(
    candidate_ids: Sequence[str],
    raw_pvalues: Mapping[str, float],
) -> dict[str, tuple[float, float]]:
    ordered_ids = tuple(candidate_ids)
    if len(ordered_ids) != FROZEN_CANDIDATE_COUNT or len(set(ordered_ids)) != len(ordered_ids):
        raise ValueError("US-R2 multiplicity requires exactly 37 unique frozen candidates")
    if set(raw_pvalues) != set(ordered_ids):
        raise ValueError("US-R2 multiplicity raw-p denominator differs from frozen candidates")
    return adjust_family_pvalues({candidate_id: raw_pvalues[candidate_id] for candidate_id in ordered_ids})


@dataclass(frozen=True, slots=True)
class USR2PooledInferenceReport:
    primary_statistics_report_id: str
    primary_statistics_plan_id: str
    evaluation_policy_id: str
    direction_evidence_id: str
    denominator_id: str
    annual_metric_evidence_ids: tuple[str, ...]
    candidates: tuple[USR2PooledCandidateInference, ...]
    technical_blockers: tuple[str, ...] = ()
    schema_version: str = "finagent.us-r2-pooled-inference-report.v1"

    @property
    def passed(self) -> bool:
        return len(self.candidates) == FROZEN_CANDIDATE_COUNT and not self.technical_blockers

    @property
    def report_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-pooled-inference")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "primary_statistics_report_id": self.primary_statistics_report_id,
            "primary_statistics_plan_id": self.primary_statistics_plan_id,
            "evaluation_policy_id": self.evaluation_policy_id,
            "direction_evidence_id": self.direction_evidence_id,
            "denominator_id": self.denominator_id,
            "candidate_count": len(self.candidates),
            "candidate_ids": [item.candidate_id for item in self.candidates],
            "annual_metric_evidence_ids": list(self.annual_metric_evidence_ids),
            "candidates": [item.to_dict() for item in self.candidates],
            "technical_blockers": list(self.technical_blockers),
            "passed": self.passed,
            "scope": "pooled_primary_15m_60m_inference_only",
            "temporal_pooling_order": "chronological_formation_time_never_regime_grouped",
            "rank_ic_hac_evaluated": True,
            "rank_ic_session_block_bootstrap_evaluated": True,
            "long_short_hac_diagnostic_evaluated": True,
            "long_short_session_block_bootstrap_diagnostic_evaluated": True,
            "multiplicity_methods": ["HOLM", "BH"],
            "multiplicity_denominator": "all_37_frozen_r1_candidates",
            "frequency_robustness_evaluated": False,
            "decay_robustness_evaluated": False,
            "candidate_selection_applied": False,
            "performance_filter_applied": False,
            "alpha_gate_evaluated": False,
            "terminal_authority": False,
            "status_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "order_authority": False,
            "paper_authority": False,
            "live_capital_authority": False,
            "raw_minute_source_access": False,
            "annual_base_parquet_access": False,
            "candidate_cache_npz_access": False,
            "candidate_feature_recomputation": False,
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


def build_us_r2_pooled_inference_report(
    annual_arrays: Sequence[tuple[int, USR2AnnualPrimaryMetricArrays]],
    *,
    plan: USR2PrimaryStatisticsPlan,
    direction: USR2PrimaryDirectionEvidenceSet,
    primary_gate: USR2PrimaryStatisticsReportGate,
    denominator: USR1CandidateDenominator,
    policy: USR2StatisticalEvaluationPolicy | None = None,
) -> USR2PooledInferenceReport:
    active = policy or canonical_us_r2_statistical_evaluation_policy()
    if primary_gate.report_id != FROZEN_PRIMARY_STATISTICS_REPORT_ID:
        raise ValueError("US-R2 pooled inference primary report identity mismatch")
    if direction.evidence_id != FROZEN_PRIMARY_DIRECTION_EVIDENCE_ID or not direction.passed:
        raise ValueError("US-R2 pooled inference requires the reviewed complete direction evidence")
    if plan.plan_id != FROZEN_PRIMARY_STATISTICS_PLAN_ID:
        raise ValueError("US-R2 pooled inference plan identity mismatch")
    expected_ids = tuple(item.candidate.candidate_id for item in denominator.candidates)
    if plan.candidate_ids != expected_ids or len(expected_ids) != FROZEN_CANDIDATE_COUNT:
        raise ValueError("US-R2 pooled inference denominator differs from the frozen 37")
    raw_candidates: list[USR2RawPooledCandidateInference] = []
    for slot, candidate_id in enumerate(plan.candidate_ids):
        points, regime_codes = collect_us_r2_pooled_candidate_points(
            annual_arrays,
            candidate_slot=slot,
        )
        raw_candidates.append(
            build_us_r2_raw_pooled_candidate_inference(
                candidate_id=candidate_id,
                direction=direction.direction(candidate_id),
                points=points,
                regime_codes=regime_codes,
                policy=active,
            )
        )
    adjusted = adjust_us_r2_pooled_rank_ic_pvalues(
        plan.candidate_ids,
        {item.candidate_id: item.rank_ic_raw_hac_pvalue for item in raw_candidates},
    )
    by_id = {item.candidate_id: item for item in raw_candidates}
    candidates = tuple(
        USR2PooledCandidateInference(
            raw=by_id[candidate_id],
            holm_adjusted_rank_ic_pvalue=adjusted[candidate_id][0],
            bh_rank_ic_qvalue=adjusted[candidate_id][1],
        )
        for candidate_id in plan.candidate_ids
    )
    return USR2PooledInferenceReport(
        primary_statistics_report_id=primary_gate.report_id,
        primary_statistics_plan_id=plan.plan_id,
        evaluation_policy_id=active.policy_id,
        direction_evidence_id=direction.evidence_id,
        denominator_id=denominator.denominator_id,
        annual_metric_evidence_ids=primary_gate.annual_metric_evidence_ids,
        candidates=candidates,
    )


def validate_us_r2_pooled_inputs(
    *,
    denominator_document: Mapping[str, object],
    policy_document: Mapping[str, object],
    plan_document: Mapping[str, object],
    direction_document: Mapping[str, object],
    primary_report_document: Mapping[str, object],
) -> tuple[
    USR1CandidateDenominator,
    USR2StatisticalEvaluationPolicy,
    USR2PrimaryStatisticsPlan,
    USR2PrimaryDirectionEvidenceSet,
    USR2PrimaryStatisticsReportGate,
]:
    denominator = validate_us_r2_candidate_denominator(denominator_document)
    policy = canonical_us_r2_statistical_evaluation_policy()
    if dict(policy_document) != policy.to_dict() or policy.policy_id != FROZEN_PRIMARY_EVALUATION_POLICY_ID:
        raise ValueError("US-R2 pooled inference requires the frozen primary evaluation policy")
    plan = parse_us_r2_primary_statistics_plan(plan_document, denominator)
    direction = parse_us_r2_primary_direction_evidence(direction_document, plan=plan)
    if direction.evidence_id != FROZEN_PRIMARY_DIRECTION_EVIDENCE_ID:
        raise ValueError("US-R2 pooled inference direction identity differs from reviewed evidence")
    primary_gate = validate_us_r2_primary_statistics_report_gate(
        primary_report_document,
        plan=plan,
        direction=direction,
        policy=policy,
    )
    return denominator, policy, plan, direction, primary_gate

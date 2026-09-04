from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np

from finagent.research.us_r2_candidate_cache import USR2AnnualCandidateCacheArrays
from finagent.research.us_r2_evaluation_policy import (
    USR2StatisticalEvaluationPolicy,
    canonical_us_r2_statistical_evaluation_policy,
)
from finagent.research.us_r2_frozen_protocol import canonical_us_r2_frozen_protocol
from finagent.research.us_r2_primary_statistics import (
    METRIC_AVAILABLE,
    METRIC_BOUNDARY_UNREALIZED,
    METRIC_INSUFFICIENT_CROSS_SECTION,
    METRIC_RANK_IC_UNDEFINED,
    METRIC_UNCLASSIFIED_MISSING_LABEL,
    USR2CandidateDirectionEvidence,
    USR2PrimaryDirectionEvidenceSet,
    USR2PrimaryStatisticsPlan,
    _candidate_status_and_rank_ic,
    _days_to_date,
    _formation_ranges,
    _partial_label_formation,
    _us_to_datetime,
    _validate_formation,
)


def build_us_r2_primary_direction_evidence_exact(
    annual_arrays: Iterable[tuple[int, USR2AnnualCandidateCacheArrays]],
    *,
    plan: USR2PrimaryStatisticsPlan,
    source_annual_evidence_ids: Mapping[int, str],
    policy: USR2StatisticalEvaluationPolicy | None = None,
) -> USR2PrimaryDirectionEvidenceSet:
    """Freeze direction with the same NumPy mean reduction used by accepted R1.

    Candidate RankIC values are retained as compact Python float lists during the five-year
    TRAIN reduction. This is bounded (~37 candidates x TRAIN formations) and avoids changing
    direction around zero through a different streaming summation order.
    """

    active = policy or canonical_us_r2_statistical_evaluation_policy()
    frozen = canonical_us_r2_frozen_protocol()
    fold = frozen.walk_forward_protocol.folds[0]
    candidate_count = len(plan.candidate_ids)
    rank_values: list[list[float]] = [[] for _ in range(candidate_count)]
    boundary = np.zeros(candidate_count, dtype=np.int64)
    partial = np.zeros(candidate_count, dtype=np.int64)
    insufficient = np.zeros(candidate_count, dtype=np.int64)
    blockers: list[list[str]] = [[] for _ in range(candidate_count)]
    seen_years: list[int] = []

    for year, arrays in annual_arrays:
        seen_years.append(year)
        for start, end in _formation_ranges(arrays):
            session_day = _validate_formation(arrays, start, end)
            session_date = _days_to_date(session_day)
            if not fold.train_start <= session_date < fold.train_end:
                continue
            reasons = arrays.label_reason_codes[start:end]
            if _partial_label_formation(reasons):
                partial += 1
                continue
            asset_codes = arrays.asset_codes[start:end]
            labels = arrays.label_values[start:end]
            label_available = arrays.label_available[start:end]
            values = arrays.candidate_values[start:end, :]
            formation_at = _us_to_datetime(int(arrays.available_at_us[start])).isoformat()
            for slot in range(candidate_count):
                status, rank_ic, _valid = _candidate_status_and_rank_ic(
                    asset_codes=asset_codes,
                    candidate_values=values[:, slot],
                    label_values=labels,
                    label_available=label_available,
                    label_reason_codes=reasons,
                    minimum_cross_section=active.minimum_cross_section,
                )
                if status == METRIC_AVAILABLE:
                    if rank_ic is None:
                        raise RuntimeError("available direction metric lost RankIC")
                    rank_values[slot].append(rank_ic)
                elif status == METRIC_BOUNDARY_UNREALIZED:
                    boundary[slot] += 1
                elif status == METRIC_INSUFFICIENT_CROSS_SECTION:
                    insufficient[slot] += 1
                elif status == METRIC_UNCLASSIFIED_MISSING_LABEL:
                    blockers[slot].append(f"unclassified_missing_label:{formation_at}")
                elif status == METRIC_RANK_IC_UNDEFINED:
                    blockers[slot].append(f"rank_ic_undefined:{formation_at}")
                else:
                    raise RuntimeError("unexpected direction metric status")

    expected_years = tuple(range(fold.train_start.year, fold.train_end.year))
    if tuple(seen_years) != expected_years:
        raise ValueError("US-R2 direction input years must be exactly fold-01 TRAIN 2001-2005")
    candidates: list[USR2CandidateDirectionEvidence] = []
    for slot, candidate_id in enumerate(plan.candidate_ids):
        candidate_blockers = list(dict.fromkeys(blockers[slot]))
        period_count = len(rank_values[slot])
        if period_count < active.minimum_train_periods:
            candidate_blockers.append(
                f"insufficient_metric_periods:{period_count}<{active.minimum_train_periods}"
            )
        mean_rank_ic = (
            None
            if period_count == 0
            else float(np.mean(np.asarray(rank_values[slot], dtype=np.float64)))
        )
        direction = (
            None
            if mean_rank_ic is None or candidate_blockers
            else (1 if mean_rank_ic >= 0.0 else -1)
        )
        candidates.append(
            USR2CandidateDirectionEvidence(
                candidate_id=candidate_id,
                period_count=period_count,
                boundary_unrealized_period_count=int(boundary[slot]),
                partial_label_omitted_period_count=int(partial[slot]),
                insufficient_cross_section_period_count=int(insufficient[slot]),
                mean_raw_rank_ic=mean_rank_ic,
                direction=direction,
                blockers=tuple(candidate_blockers),
            )
        )
    return USR2PrimaryDirectionEvidenceSet(
        plan_id=plan.plan_id,
        evaluation_policy_id=active.policy_id,
        candidate_cache_batch_evidence_id=plan.candidate_cache_batch_evidence_id,
        source_fold_id=fold.fold_id,
        source_years=expected_years,
        source_annual_evidence_ids=tuple(source_annual_evidence_ids[year] for year in expected_years),
        candidates=tuple(candidates),
    )

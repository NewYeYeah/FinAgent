from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from finagent.research.us_r2_candidate_cache import USR2AnnualCandidateCacheEvidence
from finagent.research.us_r2_primary_statistics import (
    FROZEN_CANDIDATE_COUNT,
    METRIC_AVAILABLE,
    USR2AnnualPrimaryMetricArrays,
    USR2AnnualPrimaryMetricEvidence,
    USR2CandidateDirectionEvidence,
    USR2PrimaryDirectionEvidenceSet,
    USR2PrimaryStatisticsPlan,
    _METRIC_STATUS_NAMES,
    _integer,
    _mapping,
    _sequence,
    _text,
)


def build_us_r2_primary_metric_materialization_evidence(
    *,
    plan: USR2PrimaryStatisticsPlan,
    year: int,
    fold_id: str,
    source_evidence: USR2AnnualCandidateCacheEvidence,
    source_formation_count: int,
    regime_unavailable_session_count: int,
    arrays: USR2AnnualPrimaryMetricArrays,
    output_filename: str,
    content_sha256: str,
    output_size_bytes: int,
) -> USR2AnnualPrimaryMetricEvidence:
    """Attest the metric cache itself without converting research outcomes to system failures."""

    counts = np.bincount(arrays.status_codes.ravel(), minlength=len(_METRIC_STATUS_NAMES))
    return USR2AnnualPrimaryMetricEvidence(
        plan_id=plan.plan_id,
        year=year,
        fold_id=fold_id,
        source_candidate_cache_evidence_id=source_evidence.evidence_id,
        source_candidate_row_count=source_evidence.row_count,
        source_formation_count=source_formation_count,
        metric_formation_count=arrays.row_count,
        candidate_count=arrays.candidate_count,
        available_metric_count=int(counts[METRIC_AVAILABLE]),
        status_counts=tuple(
            (name, int(counts[index])) for index, name in enumerate(_METRIC_STATUS_NAMES)
        ),
        regime_unavailable_session_count=regime_unavailable_session_count,
        output_filename=output_filename,
        output_size_bytes=output_size_bytes,
        content_sha256=content_sha256,
        blockers=(),
    )


def parse_us_r2_primary_direction_evidence(
    document: Mapping[str, object],
    *,
    plan: USR2PrimaryStatisticsPlan,
) -> USR2PrimaryDirectionEvidenceSet:
    raw_candidates = _sequence(document.get("candidates"), "candidates")
    candidates: list[USR2CandidateDirectionEvidence] = []
    for index, raw in enumerate(raw_candidates):
        item = _mapping(raw, f"candidates[{index}]")
        mean_raw = item.get("mean_raw_rank_ic")
        direction_raw = item.get("direction")
        candidate = USR2CandidateDirectionEvidence(
            candidate_id=_text(item.get("candidate_id"), "candidate_id"),
            period_count=_integer(item.get("period_count"), "period_count"),
            boundary_unrealized_period_count=_integer(
                item.get("boundary_unrealized_period_count"), "boundary_unrealized_period_count"
            ),
            partial_label_omitted_period_count=_integer(
                item.get("partial_label_omitted_period_count"), "partial_label_omitted_period_count"
            ),
            insufficient_cross_section_period_count=_integer(
                item.get("insufficient_cross_section_period_count"),
                "insufficient_cross_section_period_count",
            ),
            mean_raw_rank_ic=(None if mean_raw is None else float(mean_raw)),
            direction=(None if direction_raw is None else _integer(direction_raw, "direction")),
            blockers=tuple(
                _text(value, "blockers[]")
                for value in _sequence(item.get("blockers"), "blockers")
            ),
        )
        if dict(item) != candidate.to_dict():
            raise ValueError("US-R2 direction candidate content identity mismatch")
        candidates.append(candidate)
    evidence = USR2PrimaryDirectionEvidenceSet(
        plan_id=_text(document.get("plan_id"), "plan_id"),
        evaluation_policy_id=_text(document.get("evaluation_policy_id"), "evaluation_policy_id"),
        candidate_cache_batch_evidence_id=_text(
            document.get("candidate_cache_batch_evidence_id"),
            "candidate_cache_batch_evidence_id",
        ),
        source_fold_id=_text(document.get("source_fold_id"), "source_fold_id"),
        source_years=tuple(
            _integer(value, "source_years[]")
            for value in _sequence(document.get("source_years"), "source_years")
        ),
        source_annual_evidence_ids=tuple(
            _text(value, "source_annual_evidence_ids[]")
            for value in _sequence(
                document.get("source_annual_evidence_ids"), "source_annual_evidence_ids"
            )
        ),
        candidates=tuple(candidates),
    )
    if dict(document) != evidence.to_dict():
        raise ValueError("US-R2 primary direction evidence content identity mismatch")
    if evidence.plan_id != plan.plan_id:
        raise ValueError("US-R2 primary direction evidence/plan identity mismatch")
    if evidence.evaluation_policy_id != plan.evaluation_policy_id:
        raise ValueError("US-R2 primary direction evidence/policy identity mismatch")
    if evidence.candidate_cache_batch_evidence_id != plan.candidate_cache_batch_evidence_id:
        raise ValueError("US-R2 primary direction evidence/source batch identity mismatch")
    if tuple(item.candidate_id for item in evidence.candidates) != plan.candidate_ids:
        raise ValueError("US-R2 primary direction candidate denominator/order mismatch")
    if len(evidence.candidates) != FROZEN_CANDIDATE_COUNT:
        raise ValueError("US-R2 primary direction evidence must retain all 37 candidates")
    return evidence

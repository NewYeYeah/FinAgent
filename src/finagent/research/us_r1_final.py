from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from finagent.domain.market_bars import BarInterval
from finagent.research.us_r1_direction import USR1DirectionPreparationReport
from finagent.research.us_r1_evaluation_policy import USR1StatisticalEvaluationPolicy
from finagent.research.us_r1_gate import (
    USR1AlphaGateAssessment,
    USR1AlphaGatePolicy,
    USR1FamilyEvidence,
    assess_us_r1_alpha_gate,
    build_us_r1_family_evidence,
    build_us_r1_raw_candidate_evidence,
)
from finagent.research.us_r1_protocol import (
    USR1CandidateDenominator,
    USR1Terminal,
    canonical_us_r1_research_protocol,
)
from finagent.research.us_r1_review import USR1AlphaGateReview
from finagent.research.us_r1_statistics import (
    USR1DirectionEvidenceSet,
    USR1FoldStatisticsReport,
    USR1PeriodMetricArtifact,
    USR1PeriodMetricRecord,
    build_us_r1_fold_series,
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


def _mean_rank_ic(
    records: Sequence[USR1PeriodMetricRecord],
    *,
    candidate_id: str,
    interval: BarInterval,
    horizon: int,
) -> float:
    values = [
        record.point.rank_ic
        for record in records
        if record.candidate_id == candidate_id
        and record.signal_interval is interval
        and record.label_horizon_trading_minutes == horizon
    ]
    if not values:
        raise ValueError(
            f"US-R1 required rank-IC slice is empty for {candidate_id}: "
            f"{interval.value}/{horizon}m"
        )
    return float(np.mean(values))


@dataclass(frozen=True, slots=True)
class USR1TechnicalFailureFamilyEvidence(USR1FamilyEvidence):
    """No-statistics family evidence used only when the frozen denominator is incomplete."""

    def __post_init__(self) -> None:
        if self.protocol_id != canonical_us_r1_research_protocol().protocol_id:
            raise ValueError("US-R1 technical family/protocol identity mismatch")
        if not self.denominator_id.strip():
            raise ValueError("US-R1 technical family requires denominator_id")
        if self.candidates:
            raise ValueError("US-R1 technical family must not fabricate candidate statistics")
        blockers = tuple(item.strip() for item in self.technical_blockers if item.strip())
        if not blockers or len(blockers) != len(self.technical_blockers):
            raise ValueError("US-R1 technical family requires explicit technical blockers")
        if len(blockers) != len(set(blockers)):
            raise ValueError("US-R1 technical family blockers must be unique")
        object.__setattr__(self, "technical_blockers", blockers)


@dataclass(frozen=True, slots=True)
class USR1TechnicalFailureAlphaGateAssessment(USR1AlphaGateAssessment):
    """SYSTEM_FAILURE recommendation with no fabricated candidate Gate metrics."""

    def __post_init__(self) -> None:
        for field_name in ("policy_id", "family_evidence_id", "denominator_id"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must be non-empty")
        if self.terminal is not USR1Terminal.SYSTEM_FAILURE:
            raise ValueError("technical Alpha Gate assessment must be SYSTEM_FAILURE")
        if self.candidates or self.robust_candidate_ids:
            raise ValueError("technical Alpha Gate assessment cannot fabricate candidate results")
        blockers = tuple(item.strip() for item in self.technical_blockers if item.strip())
        if not blockers or len(blockers) != len(self.technical_blockers):
            raise ValueError("technical Alpha Gate assessment requires explicit blockers")
        if len(blockers) != len(set(blockers)):
            raise ValueError("technical Alpha Gate blockers must be unique")
        object.__setattr__(self, "technical_blockers", blockers)


@dataclass(frozen=True, slots=True)
class USR1InferenceEvidenceGraph:
    research_protocol_id: str
    walk_forward_protocol_id: str
    formation_policy_id: str
    evaluation_policy_id: str
    denominator_id: str
    alpha_gate_policy_id: str
    fold_materialization_manifest_ids: tuple[str, ...]
    direction_preparation_report_id: str
    direction_evidence_id: str | None
    fold_statistics_report_ids: tuple[str, ...]
    period_metric_artifact_ids: tuple[str, ...]
    family_evidence_id: str
    alpha_gate_assessment_id: str
    terminal: USR1Terminal
    robust_candidate_ids: tuple[str, ...]
    technical_blockers: tuple[str, ...]
    schema_version: str = "finagent.us-r1-inference-evidence-graph.v1"

    def __post_init__(self) -> None:
        for values, label in (
            (self.fold_materialization_manifest_ids, "materialization manifests"),
            (self.fold_statistics_report_ids, "fold statistics reports"),
            (self.period_metric_artifact_ids, "period metric artifacts"),
        ):
            if (
                len(values) != 3
                or len(set(values)) != 3
                or any(not item.strip() for item in values)
            ):
                raise ValueError(f"US-R1 inference graph requires exactly three unique {label}")
        if not self.direction_preparation_report_id.strip():
            raise ValueError("US-R1 inference graph requires direction preparation evidence")
        if self.terminal is USR1Terminal.SYSTEM_FAILURE:
            if not self.technical_blockers:
                raise ValueError("SYSTEM_FAILURE graph requires technical blockers")
            if self.robust_candidate_ids:
                raise ValueError("SYSTEM_FAILURE graph cannot contain robust candidate IDs")
        else:
            if self.direction_evidence_id is None or not self.direction_evidence_id.strip():
                raise ValueError("complete US-R1 inference graph requires frozen direction evidence")
            if self.technical_blockers:
                raise ValueError("complete US-R1 inference graph cannot carry technical blockers")
        if self.terminal is USR1Terminal.ROBUST_FACTOR_FAMILY and not self.robust_candidate_ids:
            raise ValueError("positive US-R1 graph requires robust candidate IDs")
        if self.terminal is USR1Terminal.NO_ROBUST_FACTOR_FAMILY and self.robust_candidate_ids:
            raise ValueError("negative US-R1 graph cannot contain robust candidate IDs")

    @property
    def graph_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-inference-graph")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "research_protocol_id": self.research_protocol_id,
            "walk_forward_protocol_id": self.walk_forward_protocol_id,
            "formation_policy_id": self.formation_policy_id,
            "evaluation_policy_id": self.evaluation_policy_id,
            "denominator_id": self.denominator_id,
            "alpha_gate_policy_id": self.alpha_gate_policy_id,
            "fold_materialization_manifest_ids": list(self.fold_materialization_manifest_ids),
            "direction_preparation_report_id": self.direction_preparation_report_id,
            "direction_evidence_id": self.direction_evidence_id,
            "fold_statistics_report_ids": list(self.fold_statistics_report_ids),
            "period_metric_artifact_ids": list(self.period_metric_artifact_ids),
            "family_evidence_id": self.family_evidence_id,
            "alpha_gate_assessment_id": self.alpha_gate_assessment_id,
            "terminal": self.terminal.value,
            "robust_candidate_ids": list(self.robust_candidate_ids),
            "technical_blockers": list(self.technical_blockers),
            "evidence_semantics": (
                "materialization_to_period_metrics_to_dependence_aware_multiplicity_corrected_gate"
            ),
            "technical_failure_semantics": (
                "no_hac_bootstrap_or_multiplicity_when_required_pre_gate_evidence_is_incomplete"
            ),
            "status_authority": False,
            "stage_exit_authority": False,
            "alpha_gate_authority": False,
            "alpha_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["graph_id"] = self.graph_id
        return payload


@dataclass(frozen=True, slots=True)
class USR1FinalInferenceArtifacts:
    family: USR1FamilyEvidence
    assessment: USR1AlphaGateAssessment
    graph: USR1InferenceEvidenceGraph


def build_us_r1_final_inference_artifacts(
    denominator: USR1CandidateDenominator,
    direction_preparation: USR1DirectionPreparationReport,
    direction_evidence: USR1DirectionEvidenceSet | None,
    fold_records: Sequence[Sequence[USR1PeriodMetricRecord]],
    fold_reports: Sequence[USR1FoldStatisticsReport],
    metric_artifacts: Sequence[USR1PeriodMetricArtifact],
    *,
    research_protocol_id: str,
    walk_forward_protocol_id: str,
    formation_policy_id: str,
    evaluation_policy: USR1StatisticalEvaluationPolicy,
    alpha_gate_policy: USR1AlphaGatePolicy,
    fold_materialization_manifest_ids: tuple[str, str, str],
) -> USR1FinalInferenceArtifacts:
    if direction_preparation.denominator_id != denominator.denominator_id:
        raise ValueError("US-R1 direction preparation/denominator identity mismatch")
    if direction_preparation.evaluation_policy_id != evaluation_policy.policy_id:
        raise ValueError("US-R1 direction preparation/evaluation-policy identity mismatch")
    if direction_evidence is not None:
        if direction_evidence.denominator_id != denominator.denominator_id:
            raise ValueError("US-R1 direction/denominator identity mismatch")
        if direction_evidence.evaluation_policy_id != evaluation_policy.policy_id:
            raise ValueError("US-R1 direction/evaluation-policy identity mismatch")
    if len(fold_records) != 3 or len(fold_reports) != 3 or len(metric_artifacts) != 3:
        raise ValueError("US-R1 final inference requires exactly three folds")
    ordered_reports = tuple(sorted(fold_reports, key=lambda item: item.fold_ordinal))
    ordered_artifacts = tuple(sorted(metric_artifacts, key=lambda item: item.fold_ordinal))
    if tuple(item.fold_ordinal for item in ordered_reports) != (1, 2, 3):
        raise ValueError("US-R1 fold statistics ordinals must be exactly 1,2,3")
    if tuple(item.fold_ordinal for item in ordered_artifacts) != (1, 2, 3):
        raise ValueError("US-R1 period metric artifact ordinals must be exactly 1,2,3")
    for report, artifact in zip(ordered_reports, ordered_artifacts, strict=True):
        if report.denominator_id != denominator.denominator_id:
            raise ValueError("US-R1 fold statistics/denominator identity mismatch")
        if report.evaluation_policy_id != evaluation_policy.policy_id:
            raise ValueError("US-R1 fold statistics/evaluation-policy identity mismatch")
        if report.period_metric_artifact_id != artifact.artifact_id:
            raise ValueError("US-R1 fold statistics/period-metric artifact mismatch")

    technical_blockers = tuple(
        dict.fromkeys(
            (*direction_preparation.blockers,)
            + tuple(
                blocker
                for report in ordered_reports
                for blocker in report.blockers
            )
        )
    )
    if technical_blockers:
        family: USR1FamilyEvidence = USR1TechnicalFailureFamilyEvidence(
            protocol_id=denominator.protocol_id,
            denominator_id=denominator.denominator_id,
            candidates=(),
            technical_blockers=technical_blockers,
        )
        assessment: USR1AlphaGateAssessment = USR1TechnicalFailureAlphaGateAssessment(
            policy_id=alpha_gate_policy.policy_id,
            family_evidence_id=family.evidence_id,
            denominator_id=denominator.denominator_id,
            terminal=USR1Terminal.SYSTEM_FAILURE,
            candidates=(),
            robust_candidate_ids=(),
            technical_blockers=technical_blockers,
        )
    else:
        if direction_evidence is None:
            raise RuntimeError("US-R1 complete precheck is missing direction evidence")
        all_records = tuple(record for records in fold_records for record in records)
        raw_candidates = []
        for provenance in denominator.candidates:
            candidate_id = provenance.candidate.candidate_id
            direction = direction_evidence.direction(candidate_id)
            primary_folds = tuple(
                build_us_r1_fold_series(
                    all_records,
                    candidate_id=candidate_id,
                    fold_id=report.fold_id,
                    interval=BarInterval.MINUTE_15,
                    horizon=60,
                )
                for report in ordered_reports
            )
            robustness = {
                BarInterval.MINUTE_5: _mean_rank_ic(
                    all_records,
                    candidate_id=candidate_id,
                    interval=BarInterval.MINUTE_5,
                    horizon=60,
                ),
                BarInterval.MINUTE_30: _mean_rank_ic(
                    all_records,
                    candidate_id=candidate_id,
                    interval=BarInterval.MINUTE_30,
                    horizon=60,
                ),
            }
            decay = {
                30: _mean_rank_ic(
                    all_records,
                    candidate_id=candidate_id,
                    interval=BarInterval.MINUTE_15,
                    horizon=30,
                ),
                120: _mean_rank_ic(
                    all_records,
                    candidate_id=candidate_id,
                    interval=BarInterval.MINUTE_15,
                    horizon=120,
                ),
            }
            raw_candidates.append(
                build_us_r1_raw_candidate_evidence(
                    candidate_id=candidate_id,
                    dominant_direction=direction,
                    primary_folds=primary_folds,
                    robustness_rank_ic=robustness,
                    decay_rank_ic=decay,
                )
            )
        family = build_us_r1_family_evidence(denominator, raw_candidates)
        assessment = assess_us_r1_alpha_gate(family, alpha_gate_policy)

    graph = USR1InferenceEvidenceGraph(
        research_protocol_id=research_protocol_id,
        walk_forward_protocol_id=walk_forward_protocol_id,
        formation_policy_id=formation_policy_id,
        evaluation_policy_id=evaluation_policy.policy_id,
        denominator_id=denominator.denominator_id,
        alpha_gate_policy_id=alpha_gate_policy.policy_id,
        fold_materialization_manifest_ids=fold_materialization_manifest_ids,
        direction_preparation_report_id=direction_preparation.report_id,
        direction_evidence_id=(
            None if direction_evidence is None else direction_evidence.evidence_id
        ),
        fold_statistics_report_ids=tuple(item.report_id for item in ordered_reports),
        period_metric_artifact_ids=tuple(item.artifact_id for item in ordered_artifacts),
        family_evidence_id=family.evidence_id,
        alpha_gate_assessment_id=assessment.assessment_id,
        terminal=assessment.terminal,
        robust_candidate_ids=assessment.robust_candidate_ids,
        technical_blockers=assessment.technical_blockers,
    )
    return USR1FinalInferenceArtifacts(family=family, assessment=assessment, graph=graph)


@dataclass(frozen=True, slots=True)
class USR1ReviewedEvidenceManifest:
    inference_graph_id: str
    family_evidence_id: str
    alpha_gate_assessment_id: str
    alpha_gate_review_id: str
    denominator_id: str
    terminal: USR1Terminal
    robust_candidate_ids: tuple[str, ...]
    schema_version: str = "finagent.us-r1-reviewed-evidence-manifest.v1"

    @property
    def manifest_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-reviewed-evidence")

    @property
    def alpha_gate_authority(self) -> bool:
        return True

    @property
    def alpha_authority(self) -> bool:
        return self.terminal is USR1Terminal.ROBUST_FACTOR_FAMILY

    @property
    def supports_us_x0_progression(self) -> bool:
        return self.alpha_authority

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "inference_graph_id": self.inference_graph_id,
            "family_evidence_id": self.family_evidence_id,
            "alpha_gate_assessment_id": self.alpha_gate_assessment_id,
            "alpha_gate_review_id": self.alpha_gate_review_id,
            "denominator_id": self.denominator_id,
            "terminal": self.terminal.value,
            "robust_candidate_ids": list(self.robust_candidate_ids),
            "alpha_gate_authority": self.alpha_gate_authority,
            "alpha_authority": self.alpha_authority,
            "supports_us_x0_progression": self.supports_us_x0_progression,
            "status_authority": False,
            "stage_exit_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["manifest_id"] = self.manifest_id
        return payload


def build_us_r1_reviewed_evidence_manifest(
    artifacts: USR1FinalInferenceArtifacts,
    review: USR1AlphaGateReview,
) -> USR1ReviewedEvidenceManifest:
    if review.assessment.assessment_id != artifacts.assessment.assessment_id:
        raise ValueError("US-R1 review/assessment identity mismatch")
    if review.assessment.family_evidence_id != artifacts.family.evidence_id:
        raise ValueError("US-R1 review/family evidence identity mismatch")
    if review.terminal is not artifacts.assessment.terminal and (
        review.terminal is not USR1Terminal.SYSTEM_FAILURE
    ):
        raise ValueError("US-R1 review may only accept assessment or downgrade to SYSTEM_FAILURE")
    robust_candidate_ids = (
        artifacts.assessment.robust_candidate_ids
        if review.terminal is USR1Terminal.ROBUST_FACTOR_FAMILY
        else ()
    )
    return USR1ReviewedEvidenceManifest(
        inference_graph_id=artifacts.graph.graph_id,
        family_evidence_id=artifacts.family.evidence_id,
        alpha_gate_assessment_id=artifacts.assessment.assessment_id,
        alpha_gate_review_id=review.review_id,
        denominator_id=artifacts.family.denominator_id,
        terminal=review.terminal,
        robust_candidate_ids=robust_candidate_ids,
    )

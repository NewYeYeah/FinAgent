from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from finagent.domain.market_bars import BarInterval
from finagent.research.us_r1_evaluation_policy import USR1StatisticalEvaluationPolicy
from finagent.research.us_r1_materialization import (
    USR1CandidateObservation,
    USR1ObservationRole,
)
from finagent.research.us_r1_protocol import USR1CandidateDenominator
from finagent.research.us_r1_statistics import (
    USR1CandidateDirectionEvidence,
    USR1CandidateSliceStatistics,
    USR1DirectionEvidenceSet,
    evaluate_us_r1_candidate_slice,
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


@dataclass(frozen=True, slots=True)
class USR1DirectionPreparationReport:
    denominator_id: str
    evaluation_policy_id: str
    source_fold_id: str
    source_fold_manifest_id: str
    candidate_train_statistics: tuple[USR1CandidateSliceStatistics, ...]
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-r1-direction-preparation-report.v1"

    def __post_init__(self) -> None:
        if not self.candidate_train_statistics:
            raise ValueError("US-R1 direction preparation requires candidate TRAIN statistics")
        ids = tuple(item.candidate_id for item in self.candidate_train_statistics)
        if len(ids) != len(set(ids)):
            raise ValueError("US-R1 direction preparation cannot repeat candidates")
        cleaned = tuple(item.strip() for item in self.blockers if item.strip())
        if len(cleaned) != len(self.blockers) or len(cleaned) != len(set(cleaned)):
            raise ValueError("US-R1 direction preparation blockers must be unique/non-empty")
        object.__setattr__(self, "blockers", cleaned)

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def report_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-direction-preparation")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "denominator_id": self.denominator_id,
            "evaluation_policy_id": self.evaluation_policy_id,
            "source_fold_id": self.source_fold_id,
            "source_fold_manifest_id": self.source_fold_manifest_id,
            "candidate_count": len(self.candidate_train_statistics),
            "candidate_ids": [item.candidate_id for item in self.candidate_train_statistics],
            "candidate_train_statistics": [
                item.to_dict() for item in self.candidate_train_statistics
            ],
            "passed": self.passed,
            "blockers": list(self.blockers),
            "direction_emission_semantics": (
                "emit_directions_only_when_all_frozen_denominator_candidates_have_valid_train_statistics"
            ),
            "status_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


def prepare_us_r1_direction_evidence(
    train_observations: tuple[USR1CandidateObservation, ...],
    denominator: USR1CandidateDenominator,
    *,
    fold_id: str,
    fold_materialization_manifest_id: str,
    policy: USR1StatisticalEvaluationPolicy,
) -> tuple[USR1DirectionPreparationReport, USR1DirectionEvidenceSet | None]:
    statistics_items: list[USR1CandidateSliceStatistics] = []
    directions: list[USR1CandidateDirectionEvidence] = []
    blockers: list[str] = []
    for provenance in denominator.candidates:
        candidate_id = provenance.candidate.candidate_id
        statistics, _points = evaluate_us_r1_candidate_slice(
            train_observations,
            candidate_id=candidate_id,
            role=USR1ObservationRole.TRAIN,
            signal_interval=BarInterval.MINUTE_15,
            label_horizon_trading_minutes=60,
            policy=policy,
            minimum_periods=policy.minimum_train_periods,
        )
        statistics_items.append(statistics)
        if not statistics.passed or statistics.mean_raw_rank_ic is None:
            reasons = statistics.blockers or ("mean_rank_ic_unavailable",)
            blockers.extend(f"candidate:{candidate_id}:{reason}" for reason in reasons)
            continue
        mean_rank_ic = statistics.mean_raw_rank_ic
        directions.append(
            USR1CandidateDirectionEvidence(
                candidate_id=candidate_id,
                evaluation_policy_id=policy.policy_id,
                source_fold_id=fold_id,
                source_fold_manifest_id=fold_materialization_manifest_id,
                train_statistics_id=statistics.statistics_id,
                train_period_count=statistics.period_count,
                train_mean_rank_ic=mean_rank_ic,
                direction=1 if mean_rank_ic >= 0.0 else -1,
            )
        )
    report = USR1DirectionPreparationReport(
        denominator_id=denominator.denominator_id,
        evaluation_policy_id=policy.policy_id,
        source_fold_id=fold_id,
        source_fold_manifest_id=fold_materialization_manifest_id,
        candidate_train_statistics=tuple(statistics_items),
        blockers=tuple(dict.fromkeys(blockers)),
    )
    if not report.passed:
        return report, None
    if len(directions) != len(denominator.candidates):
        raise RuntimeError("US-R1 direction preparation passed without complete directions")
    return report, USR1DirectionEvidenceSet(
        denominator_id=denominator.denominator_id,
        evaluation_policy_id=policy.policy_id,
        source_fold_id=fold_id,
        source_fold_manifest_id=fold_materialization_manifest_id,
        candidates=tuple(directions),
    )

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from finagent.research.us_baseline_evaluation import USBaselineEvaluationReport
from finagent.research.us_baseline_walkforward import (
    USBaselineFoldExecutionSpec,
    USBaselineWalkForwardProtocol,
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


def _mean(values: tuple[float, ...]) -> float | None:
    return sum(values) / len(values) if values else None


@dataclass(frozen=True, slots=True)
class USBaselineWalkForwardCandidateAggregate:
    feature_id: str
    feature_spec_id: str
    fold_count: int
    valid_fold_count: int
    mean_rank_ic: float | None
    worst_fold_rank_ic: float | None
    mean_gross_return: float | None
    worst_fold_gross_return: float | None
    mean_one_way_turnover: float | None
    maximum_one_way_turnover: float | None
    mean_feature_coverage: float
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-baseline-walk-forward-candidate-aggregate.v1"

    @property
    def valid(self) -> bool:
        return self.valid_fold_count == self.fold_count and not self.blockers

    @property
    def aggregate_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-baseline-wf-candidate")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "feature_id": self.feature_id,
            "feature_spec_id": self.feature_spec_id,
            "fold_count": self.fold_count,
            "valid_fold_count": self.valid_fold_count,
            "mean_rank_ic": self.mean_rank_ic,
            "worst_fold_rank_ic": self.worst_fold_rank_ic,
            "mean_gross_return": self.mean_gross_return,
            "worst_fold_gross_return": self.worst_fold_gross_return,
            "mean_one_way_turnover": self.mean_one_way_turnover,
            "maximum_one_way_turnover": self.maximum_one_way_turnover,
            "mean_feature_coverage": self.mean_feature_coverage,
            "valid": self.valid,
            "blockers": list(self.blockers),
        }
        if include_id:
            payload["aggregate_id"] = self.aggregate_id
        return payload


@dataclass(frozen=True, slots=True)
class USBaselineWalkForwardAggregateReport:
    protocol_id: str
    run_spec_id: str
    denominator_id: str
    fold_execution_spec_ids: tuple[str, ...]
    fold_evaluation_report_ids: tuple[str, ...]
    candidates: tuple[USBaselineWalkForwardCandidateAggregate, ...]
    schema_version: str = "finagent.us-baseline-walk-forward-aggregate-report.v1"

    def __post_init__(self) -> None:
        if not self.protocol_id or not self.run_spec_id or not self.denominator_id:
            raise ValueError("aggregate report identities must be non-empty")
        if not self.fold_execution_spec_ids or not self.fold_evaluation_report_ids:
            raise ValueError("aggregate report requires fold evidence")
        if len(self.fold_execution_spec_ids) != len(self.fold_evaluation_report_ids):
            raise ValueError("fold execution/evaluation evidence counts must match")
        feature_ids = tuple(item.feature_id for item in self.candidates)
        if not feature_ids or len(feature_ids) != len(set(feature_ids)):
            raise ValueError("aggregate report requires unique candidate feature ids")

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(
            f"candidate:{candidate.feature_id}:{blocker}"
            for candidate in self.candidates
            for blocker in candidate.blockers
        )

    @property
    def passed(self) -> bool:
        return not self.blockers and all(item.valid for item in self.candidates)

    @property
    def report_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-baseline-walk-forward-aggregate")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "run_spec_id": self.run_spec_id,
            "denominator_id": self.denominator_id,
            "fold_execution_spec_ids": list(self.fold_execution_spec_ids),
            "fold_evaluation_report_ids": list(self.fold_evaluation_report_ids),
            "candidate_count": len(self.candidates),
            "passed": self.passed,
            "blockers": list(self.blockers),
            "candidates": [item.to_dict() for item in self.candidates],
            "scope": "split_bound_cost_free_manual_baseline_diagnostics",
            "stage_exit_authority": False,
            "factor_selection_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


def aggregate_us_b0_walk_forward(
    protocol: USBaselineWalkForwardProtocol,
    execution_specs: tuple[USBaselineFoldExecutionSpec, ...],
    evaluation_reports: tuple[USBaselineEvaluationReport, ...],
) -> USBaselineWalkForwardAggregateReport:
    if len(execution_specs) != len(protocol.folds):
        raise ValueError("walk-forward requires one execution spec per frozen fold")
    if len(evaluation_reports) != len(protocol.folds):
        raise ValueError("walk-forward requires one evaluation report per frozen fold")

    run_spec_ids = {item.run_spec_id for item in execution_specs}
    if len(run_spec_ids) != 1:
        raise ValueError("walk-forward fold execution specs must share one run-spec identity")
    run_spec_id = next(iter(run_spec_ids))
    for fold, execution in zip(protocol.folds, execution_specs, strict=True):
        if execution.protocol_id != protocol.protocol_id:
            raise ValueError("fold execution spec protocol identity mismatch")
        if execution.fold_id != fold.fold_id or execution.fold_ordinal != fold.ordinal:
            raise ValueError("fold execution spec does not bind the frozen fold")
        if execution.evaluation_start != fold.evaluation_start:
            raise ValueError("fold execution evaluation_start mismatch")
        if execution.evaluation_end != fold.evaluation_end:
            raise ValueError("fold execution evaluation_end mismatch")

    denominator_ids = {report.denominator_id for report in evaluation_reports}
    if len(denominator_ids) != 1:
        raise ValueError("walk-forward evaluation reports must share one denominator")
    denominator_id = next(iter(denominator_ids))
    for execution, report in zip(execution_specs, evaluation_reports, strict=True):
        if report.run_spec.spec_id != execution.run_spec_id:
            raise ValueError("fold evaluation report/run-spec identity mismatch")
        if report.denominator_id != denominator_id:
            raise ValueError("fold evaluation denominator drift")

    feature_orders = [tuple(item.feature_id for item in report.candidates) for report in evaluation_reports]
    if any(order != feature_orders[0] for order in feature_orders[1:]):
        raise ValueError("walk-forward candidate denominator/order drift across folds")

    aggregates: list[USBaselineWalkForwardCandidateAggregate] = []
    fold_count = len(evaluation_reports)
    for candidate_index, feature_id in enumerate(feature_orders[0]):
        rows = tuple(report.candidates[candidate_index] for report in evaluation_reports)
        spec_ids = {row.feature_spec_id for row in rows}
        if len(spec_ids) != 1:
            raise ValueError(f"feature spec identity drift across folds: {feature_id}")
        rank_ics = tuple(row.mean_rank_ic for row in rows if row.mean_rank_ic is not None)
        gross_returns = tuple(
            row.mean_gross_return for row in rows if row.mean_gross_return is not None
        )
        turnovers = tuple(
            row.mean_one_way_turnover
            for row in rows
            if row.mean_one_way_turnover is not None
        )
        blockers = tuple(
            f"fold:{fold.ordinal}:{blocker}"
            for fold, row in zip(protocol.folds, rows, strict=True)
            for blocker in row.blockers
        )
        aggregates.append(
            USBaselineWalkForwardCandidateAggregate(
                feature_id=feature_id,
                feature_spec_id=next(iter(spec_ids)),
                fold_count=fold_count,
                valid_fold_count=sum(row.valid for row in rows),
                mean_rank_ic=_mean(rank_ics),
                worst_fold_rank_ic=min(rank_ics) if rank_ics else None,
                mean_gross_return=_mean(gross_returns),
                worst_fold_gross_return=min(gross_returns) if gross_returns else None,
                mean_one_way_turnover=_mean(turnovers),
                maximum_one_way_turnover=max(turnovers) if turnovers else None,
                mean_feature_coverage=sum(row.feature_coverage for row in rows) / fold_count,
                blockers=blockers,
            )
        )

    return USBaselineWalkForwardAggregateReport(
        protocol_id=protocol.protocol_id,
        run_spec_id=run_spec_id,
        denominator_id=denominator_id,
        fold_execution_spec_ids=tuple(item.execution_spec_id for item in execution_specs),
        fold_evaluation_report_ids=tuple(item.report_id for item in evaluation_reports),
        candidates=tuple(aggregates),
    )

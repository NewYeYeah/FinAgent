from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from finagent.research.us_agent_value_experiment import (
    RunEvaluationLink,
    USAgentValuePredecessorBinding,
)
from finagent.research.us_agent_value_generation import CandidateGenerationRun
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValueExperimentProtocol,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_manual_candidates,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_baseline_evaluation import (
    USBaselineCandidateEvidence,
    USBaselineObservation,
    USBaselineRunSpec,
    evaluate_us_baseline_candidate,
)
from finagent.research.us_baseline_materialization import (
    USBaselineMaterializationDiagnostics,
    materialize_us_baseline_observations,
)
from finagent.research.us_baseline_walkforward import canonical_us_b0_pilot_walk_forward
from finagent.research.us_baselines import (
    USBaselineCandidateDenominator,
    USBaselineFeatureSpec,
    USBaselineProtocol,
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
class USAgentValueEvaluationDenominator:
    protocol_id: str
    generation_run_id: str
    generation_run_spec_id: str
    arm: USAgentValueArm
    candidate_ids: tuple[str, ...]
    protocol: USBaselineProtocol
    candidates: tuple[USBaselineFeatureSpec, ...]
    schema_version: str = "finagent.us-agent-value-evaluation-denominator.v1"

    def __post_init__(self) -> None:
        for field_name in ("protocol_id", "generation_run_id", "generation_run_spec_id"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if len(self.candidate_ids) != len(self.candidates):
            raise ValueError("A0 evaluation denominator candidate/spec counts must match")
        if len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("A0 evaluation denominator candidate identities must be unique")
        feature_ids = tuple(item.feature_id for item in self.candidates)
        feature_spec_ids = tuple(item.spec_id for item in self.candidates)
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("A0 evaluation denominator feature identities must be unique")
        if len(feature_spec_ids) != len(set(feature_spec_ids)):
            raise ValueError("A0 evaluation denominator feature specs must be unique")
        if any(item.protocol_id != self.protocol.protocol_id for item in self.candidates):
            raise ValueError("A0 compiled feature/protocol identity mismatch")

    @property
    def denominator_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-evaluation-denominator",
        )

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "generation_run_id": self.generation_run_id,
            "generation_run_spec_id": self.generation_run_spec_id,
            "arm": self.arm.value,
            "candidate_count": self.candidate_count,
            "candidate_ids": list(self.candidate_ids),
            "baseline_protocol": self.protocol.to_dict(),
            "feature_spec_ids": [item.spec_id for item in self.candidates],
            "features": [item.to_dict() for item in self.candidates],
            "scope": "accepted_structural_candidates_compiled_to_shared_us_intraday_evaluator",
            "selection_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["denominator_id"] = self.denominator_id
        return payload


def compile_us_a0_evaluation_denominator(
    protocol: USAgentValueExperimentProtocol,
    generation_run: CandidateGenerationRun,
) -> USAgentValueEvaluationDenominator:
    if generation_run.spec.protocol_id != protocol.protocol_id:
        raise ValueError("A0 generation run/protocol identity mismatch")
    if generation_run.spec.phase is not protocol.phase:
        raise ValueError("A0 generation run phase mismatch")
    accepted = generation_run.accepted_candidates
    compiled = tuple(item.compile_feature_spec() for item in accepted)
    baseline_protocol = USBaselineProtocol()
    return USAgentValueEvaluationDenominator(
        protocol_id=protocol.protocol_id,
        generation_run_id=generation_run.run_id,
        generation_run_spec_id=generation_run.spec.run_spec_id,
        arm=generation_run.spec.arm,
        candidate_ids=tuple(item.candidate_id for item in accepted),
        protocol=baseline_protocol,
        candidates=compiled,
    )


@dataclass(frozen=True, slots=True)
class USAgentValueEvaluationBinding:
    protocol_id: str
    predecessor_binding_id: str
    generation_run_id: str
    generation_run_spec_id: str
    arm: USAgentValueArm
    source_us_b0_run_spec_id: str
    denominator: USAgentValueEvaluationDenominator
    run_spec: USBaselineRunSpec
    schema_version: str = "finagent.us-agent-value-evaluation-binding.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "protocol_id",
            "predecessor_binding_id",
            "generation_run_id",
            "generation_run_spec_id",
            "source_us_b0_run_spec_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.denominator.protocol_id != self.protocol_id:
            raise ValueError("A0 denominator/protocol identity mismatch")
        if self.denominator.generation_run_id != self.generation_run_id:
            raise ValueError("A0 denominator/generation-run identity mismatch")
        if self.denominator.generation_run_spec_id != self.generation_run_spec_id:
            raise ValueError("A0 denominator/generation-run-spec identity mismatch")
        if self.denominator.arm is not self.arm:
            raise ValueError("A0 denominator/search-arm mismatch")
        if self.run_spec.denominator_id != self.denominator.denominator_id:
            raise ValueError("A0 baseline run-spec/denominator identity mismatch")

    @property
    def binding_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-evaluation-binding",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "predecessor_binding_id": self.predecessor_binding_id,
            "generation_run_id": self.generation_run_id,
            "generation_run_spec_id": self.generation_run_spec_id,
            "arm": self.arm.value,
            "source_us_b0_run_spec_id": self.source_us_b0_run_spec_id,
            "denominator": self.denominator.to_dict(),
            "run_spec": self.run_spec.to_dict(),
            "same_certification_report": True,
            "same_engineering_universe": True,
            "same_signal_interval": True,
            "same_label": True,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["binding_id"] = self.binding_id
        return payload


def bind_us_a0_evaluation(
    protocol: USAgentValueExperimentProtocol,
    predecessor: USAgentValuePredecessorBinding,
    generation_run: CandidateGenerationRun,
    source_us_b0_run_spec: USBaselineRunSpec,
) -> USAgentValueEvaluationBinding:
    if predecessor.us_b0_walk_forward_protocol_id != protocol.us_b0_walk_forward_protocol_id:
        raise ValueError("A0 predecessor/protocol walk-forward identity mismatch")
    if source_us_b0_run_spec.spec_id != predecessor.us_b0_run_spec_id:
        raise ValueError("A0 source US-B0 run-spec identity mismatch")
    if source_us_b0_run_spec.denominator_id != predecessor.us_b0_denominator_id:
        raise ValueError("A0 source US-B0 denominator identity mismatch")
    denominator = compile_us_a0_evaluation_denominator(protocol, generation_run)
    run_spec = USBaselineRunSpec(
        certification_report_id=source_us_b0_run_spec.certification_report_id,
        certification_outcome=source_us_b0_run_spec.certification_outcome,
        engineering_universe_id=source_us_b0_run_spec.engineering_universe_id,
        denominator_id=denominator.denominator_id,
        label_name=source_us_b0_run_spec.label_name,
        signal_interval=source_us_b0_run_spec.signal_interval,
        minimum_cross_section=source_us_b0_run_spec.minimum_cross_section,
        minimum_evaluated_periods=source_us_b0_run_spec.minimum_evaluated_periods,
        minimum_ic_periods=source_us_b0_run_spec.minimum_ic_periods,
        fail_on_partial_realized_label=source_us_b0_run_spec.fail_on_partial_realized_label,
    )
    return USAgentValueEvaluationBinding(
        protocol_id=protocol.protocol_id,
        predecessor_binding_id=predecessor.binding_id,
        generation_run_id=generation_run.run_id,
        generation_run_spec_id=generation_run.spec.run_spec_id,
        arm=generation_run.spec.arm,
        source_us_b0_run_spec_id=source_us_b0_run_spec.spec_id,
        denominator=denominator,
        run_spec=run_spec,
    )


@dataclass(frozen=True, slots=True)
class USAgentValueFoldExecutionSpec:
    evaluation_binding_id: str
    protocol_id: str
    generation_run_id: str
    denominator_id: str
    run_spec_id: str
    fold_id: str
    fold_ordinal: int
    evaluation_start: str
    evaluation_end: str
    schema_version: str = "finagent.us-agent-value-fold-execution-spec.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "evaluation_binding_id",
            "protocol_id",
            "generation_run_id",
            "denominator_id",
            "run_spec_id",
            "fold_id",
            "evaluation_start",
            "evaluation_end",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.fold_ordinal < 1:
            raise ValueError("fold_ordinal must be >= 1")

    @property
    def execution_spec_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-fold-execution",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "evaluation_binding_id": self.evaluation_binding_id,
            "protocol_id": self.protocol_id,
            "generation_run_id": self.generation_run_id,
            "denominator_id": self.denominator_id,
            "run_spec_id": self.run_spec_id,
            "fold_id": self.fold_id,
            "fold_ordinal": self.fold_ordinal,
            "evaluation_start": self.evaluation_start,
            "evaluation_end": self.evaluation_end,
            "purpose": "controlled_agent_value_arm_evaluation",
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["execution_spec_id"] = self.execution_spec_id
        return payload


def bind_us_a0_fold_execution_specs(
    protocol: USAgentValueExperimentProtocol,
    binding: USAgentValueEvaluationBinding,
) -> tuple[USAgentValueFoldExecutionSpec, ...]:
    if binding.protocol_id != protocol.protocol_id:
        raise ValueError("A0 evaluation binding/protocol identity mismatch")
    walk_forward = canonical_us_b0_pilot_walk_forward()
    if walk_forward.protocol_id != protocol.us_b0_walk_forward_protocol_id:
        raise ValueError("A0 protocol does not bind the canonical US-B0 walk-forward")
    return tuple(
        USAgentValueFoldExecutionSpec(
            evaluation_binding_id=binding.binding_id,
            protocol_id=protocol.protocol_id,
            generation_run_id=binding.generation_run_id,
            denominator_id=binding.denominator.denominator_id,
            run_spec_id=binding.run_spec.spec_id,
            fold_id=fold.fold_id,
            fold_ordinal=fold.ordinal,
            evaluation_start=fold.evaluation_start.isoformat(),
            evaluation_end=fold.evaluation_end.isoformat(),
        )
        for fold in walk_forward.folds
    )


def materialize_us_a0_observations(
    rows: Sequence[Mapping[str, object]],
    denominator: USAgentValueEvaluationDenominator,
    *,
    expected_assets: Sequence[str],
) -> tuple[
    dict[str, tuple[USBaselineObservation, ...]],
    USBaselineMaterializationDiagnostics,
]:
    """Reuse the exact US-B0 formation/label materializer without constructing MANUAL evidence.

    The underlying implementation consumes only ``protocol``, ``candidates`` and their feature
    semantics. The cast is a typing bridge only; the A0 denominator keeps its own content identity
    and is never serialized or represented as a MANUAL US-B0 denominator.
    """

    baseline_view = cast(USBaselineCandidateDenominator, denominator)
    return materialize_us_baseline_observations(
        rows,
        baseline_view,
        expected_assets=expected_assets,
    )


@dataclass(frozen=True, slots=True)
class USAgentValueFoldEvaluationReport:
    evaluation_binding_id: str
    generation_run_id: str
    arm: USAgentValueArm
    execution_spec: USAgentValueFoldExecutionSpec
    run_spec_id: str
    denominator_id: str
    candidate_ids: tuple[str, ...]
    feature_ids: tuple[str, ...]
    feature_spec_ids: tuple[str, ...]
    candidates: tuple[USBaselineCandidateEvidence, ...]
    schema_version: str = "finagent.us-agent-value-fold-evaluation-report.v1"

    def __post_init__(self) -> None:
        size = len(self.candidate_ids)
        if size == 0:
            raise ValueError("fold evaluation report requires at least one accepted candidate")
        if not (
            size
            == len(self.feature_ids)
            == len(self.feature_spec_ids)
            == len(self.candidates)
        ):
            raise ValueError("fold evaluation candidate identity arrays must have equal length")
        if len(set(self.candidate_ids)) != size:
            raise ValueError("fold evaluation candidate identities must be unique")
        if self.execution_spec.evaluation_binding_id != self.evaluation_binding_id:
            raise ValueError("fold report/execution binding identity mismatch")
        if self.execution_spec.generation_run_id != self.generation_run_id:
            raise ValueError("fold report/execution generation-run identity mismatch")
        if self.execution_spec.denominator_id != self.denominator_id:
            raise ValueError("fold report/execution denominator identity mismatch")
        if self.execution_spec.run_spec_id != self.run_spec_id:
            raise ValueError("fold report/execution run-spec identity mismatch")
        for index, evidence in enumerate(self.candidates):
            if evidence.feature_id != self.feature_ids[index]:
                raise ValueError("fold candidate feature identity mismatch")
            if evidence.feature_spec_id != self.feature_spec_ids[index]:
                raise ValueError("fold candidate feature-spec identity mismatch")
            if evidence.run_spec_id != self.run_spec_id:
                raise ValueError("fold candidate/run-spec identity mismatch")

    @property
    def valid_candidate_count(self) -> int:
        return sum(item.valid for item in self.candidates)

    @property
    def report_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-fold-evaluation",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "evaluation_binding_id": self.evaluation_binding_id,
            "generation_run_id": self.generation_run_id,
            "arm": self.arm.value,
            "execution_spec": self.execution_spec.to_dict(),
            "run_spec_id": self.run_spec_id,
            "denominator_id": self.denominator_id,
            "candidate_count": len(self.candidates),
            "valid_candidate_count": self.valid_candidate_count,
            "candidate_ids": list(self.candidate_ids),
            "feature_ids": list(self.feature_ids),
            "feature_spec_ids": list(self.feature_spec_ids),
            "candidates": [item.to_dict() for item in self.candidates],
            "metric_authority": "shared_us_baseline_candidate_evaluator",
            "selection_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


def evaluate_us_a0_fold(
    binding: USAgentValueEvaluationBinding,
    execution_spec: USAgentValueFoldExecutionSpec,
    observations_by_feature: Mapping[str, Sequence[USBaselineObservation]],
) -> USAgentValueFoldEvaluationReport:
    denominator = binding.denominator
    if denominator.candidate_count == 0:
        raise ValueError("zero-candidate generation runs do not require fold evaluation")
    if execution_spec.evaluation_binding_id != binding.binding_id:
        raise ValueError("A0 fold execution spec/evaluation binding mismatch")
    expected_features = tuple(item.feature_id for item in denominator.candidates)
    unexpected = sorted(set(observations_by_feature).difference(expected_features))
    if unexpected:
        raise ValueError(f"A0 observations contain features outside denominator: {unexpected}")
    evidence = tuple(
        evaluate_us_baseline_candidate(
            feature,
            observations_by_feature.get(feature.feature_id, ()),
            run_spec=binding.run_spec,
        )
        for feature in denominator.candidates
    )
    return USAgentValueFoldEvaluationReport(
        evaluation_binding_id=binding.binding_id,
        generation_run_id=binding.generation_run_id,
        arm=binding.arm,
        execution_spec=execution_spec,
        run_spec_id=binding.run_spec.spec_id,
        denominator_id=denominator.denominator_id,
        candidate_ids=denominator.candidate_ids,
        feature_ids=expected_features,
        feature_spec_ids=tuple(item.spec_id for item in denominator.candidates),
        candidates=evidence,
    )


@dataclass(frozen=True, slots=True)
class USAgentValueCandidateEvaluationAggregate:
    candidate_id: str
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
    invalid_reasons: tuple[str, ...]
    schema_version: str = "finagent.us-agent-value-candidate-evaluation-aggregate.v1"

    @property
    def valid(self) -> bool:
        return self.valid_fold_count == self.fold_count and not self.invalid_reasons

    @property
    def aggregate_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-candidate-evaluation",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
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
            "invalid_reasons": list(self.invalid_reasons),
        }
        if include_id:
            payload["aggregate_id"] = self.aggregate_id
        return payload


class USAgentValueRunEvaluationStatus(StrEnum):
    EVALUATED = "EVALUATED"
    NO_ACCEPTED_CANDIDATES = "NO_ACCEPTED_CANDIDATES"


@dataclass(frozen=True, slots=True)
class USAgentValueRunEvaluationReport:
    evaluation_binding_id: str
    generation_run_id: str
    arm: USAgentValueArm
    denominator_id: str
    run_spec_id: str
    status: USAgentValueRunEvaluationStatus
    fold_evaluation_report_ids: tuple[str, ...]
    candidates: tuple[USAgentValueCandidateEvaluationAggregate, ...]
    schema_version: str = "finagent.us-agent-value-run-evaluation-report.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "evaluation_binding_id",
            "generation_run_id",
            "denominator_id",
            "run_spec_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.status is USAgentValueRunEvaluationStatus.NO_ACCEPTED_CANDIDATES:
            if self.fold_evaluation_report_ids or self.candidates:
                raise ValueError("zero-candidate run cannot carry fold financial evidence")
        else:
            if len(self.fold_evaluation_report_ids) != 3:
                raise ValueError("A0 evaluated run requires exactly three frozen fold reports")
            if len(set(self.fold_evaluation_report_ids)) != 3:
                raise ValueError("A0 fold evaluation report identities must be unique")
            if not self.candidates:
                raise ValueError("evaluated A0 run requires candidate aggregates")

    @property
    def evaluated_candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def valid_candidate_count(self) -> int:
        return sum(item.valid for item in self.candidates)

    @property
    def best_mean_rank_ic(self) -> float | None:
        values = tuple(
            float(item.mean_rank_ic)
            for item in self.candidates
            if item.valid and item.mean_rank_ic is not None
        )
        return max(values) if values else None

    @property
    def best_worst_fold_rank_ic(self) -> float | None:
        values = tuple(
            float(item.worst_fold_rank_ic)
            for item in self.candidates
            if item.valid and item.worst_fold_rank_ic is not None
        )
        return max(values) if values else None

    @property
    def report_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-run-evaluation",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "evaluation_binding_id": self.evaluation_binding_id,
            "generation_run_id": self.generation_run_id,
            "arm": self.arm.value,
            "denominator_id": self.denominator_id,
            "run_spec_id": self.run_spec_id,
            "status": self.status.value,
            "fold_evaluation_report_ids": list(self.fold_evaluation_report_ids),
            "evaluated_candidate_count": self.evaluated_candidate_count,
            "valid_candidate_count": self.valid_candidate_count,
            "best_mean_rank_ic": self.best_mean_rank_ic,
            "best_worst_fold_rank_ic": self.best_worst_fold_rank_ic,
            "candidates": [item.to_dict() for item in self.candidates],
            "evidence_complete": True,
            "candidate_invalidity_is_research_result_not_system_blocker": True,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


def aggregate_us_a0_run_evaluation(
    binding: USAgentValueEvaluationBinding,
    fold_reports: tuple[USAgentValueFoldEvaluationReport, ...],
) -> USAgentValueRunEvaluationReport:
    denominator = binding.denominator
    if denominator.candidate_count == 0:
        if fold_reports:
            raise ValueError("zero-candidate A0 run must not carry fold evaluation reports")
        return USAgentValueRunEvaluationReport(
            evaluation_binding_id=binding.binding_id,
            generation_run_id=binding.generation_run_id,
            arm=binding.arm,
            denominator_id=denominator.denominator_id,
            run_spec_id=binding.run_spec.spec_id,
            status=USAgentValueRunEvaluationStatus.NO_ACCEPTED_CANDIDATES,
            fold_evaluation_report_ids=(),
            candidates=(),
        )

    execution_specs = bind_us_a0_fold_execution_specs(
        canonical_us_a0_experiment_protocol(
            USAgentValuePhase.PILOT
            if binding.run_spec.signal_interval == "15m" and len(denominator.candidate_ids) <= 16
            else USAgentValuePhase.FORMAL
        ),
        binding,
    )
    if len(fold_reports) != len(execution_specs):
        raise ValueError("A0 run aggregation requires all three frozen fold reports")
    for expected, report in zip(execution_specs, fold_reports, strict=True):
        if report.evaluation_binding_id != binding.binding_id:
            raise ValueError("A0 fold report/evaluation binding mismatch")
        if report.execution_spec.execution_spec_id != expected.execution_spec_id:
            raise ValueError("A0 fold report does not bind the frozen execution spec")
        if report.candidate_ids != denominator.candidate_ids:
            raise ValueError("A0 candidate denominator/order drift across folds")

    aggregates: list[USAgentValueCandidateEvaluationAggregate] = []
    fold_count = len(fold_reports)
    for index, candidate_id in enumerate(denominator.candidate_ids):
        rows = tuple(report.candidates[index] for report in fold_reports)
        feature = denominator.candidates[index]
        rank_ics = tuple(row.mean_rank_ic for row in rows if row.mean_rank_ic is not None)
        gross_returns = tuple(
            row.mean_gross_return for row in rows if row.mean_gross_return is not None
        )
        turnovers = tuple(
            row.mean_one_way_turnover for row in rows if row.mean_one_way_turnover is not None
        )
        invalid_reasons = tuple(
            f"fold:{fold_index}:{reason}"
            for fold_index, row in enumerate(rows, start=1)
            for reason in row.blockers
        )
        aggregates.append(
            USAgentValueCandidateEvaluationAggregate(
                candidate_id=candidate_id,
                feature_id=feature.feature_id,
                feature_spec_id=feature.spec_id,
                fold_count=fold_count,
                valid_fold_count=sum(row.valid for row in rows),
                mean_rank_ic=_mean(rank_ics),
                worst_fold_rank_ic=min(rank_ics) if rank_ics else None,
                mean_gross_return=_mean(gross_returns),
                worst_fold_gross_return=min(gross_returns) if gross_returns else None,
                mean_one_way_turnover=_mean(turnovers),
                maximum_one_way_turnover=max(turnovers) if turnovers else None,
                mean_feature_coverage=sum(row.feature_coverage for row in rows) / fold_count,
                invalid_reasons=invalid_reasons,
            )
        )
    return USAgentValueRunEvaluationReport(
        evaluation_binding_id=binding.binding_id,
        generation_run_id=binding.generation_run_id,
        arm=binding.arm,
        denominator_id=denominator.denominator_id,
        run_spec_id=binding.run_spec.spec_id,
        status=USAgentValueRunEvaluationStatus.EVALUATED,
        fold_evaluation_report_ids=tuple(item.report_id for item in fold_reports),
        candidates=tuple(aggregates),
    )


def build_run_evaluation_link(
    generation_run: CandidateGenerationRun,
    evaluation_report: USAgentValueRunEvaluationReport,
) -> RunEvaluationLink:
    if generation_run.run_id != evaluation_report.generation_run_id:
        raise ValueError("A0 run evaluation report/generation-run identity mismatch")
    if generation_run.spec.arm is not evaluation_report.arm:
        raise ValueError("A0 run evaluation report/search-arm mismatch")
    if len(generation_run.accepted_candidates) != evaluation_report.evaluated_candidate_count:
        raise ValueError("A0 evaluated candidate count must equal accepted structural candidates")
    return RunEvaluationLink(
        generation_run_id=generation_run.run_id,
        authoritative_evidence_id=evaluation_report.report_id,
        evaluated_candidate_count=evaluation_report.evaluated_candidate_count,
        valid_candidate_count=evaluation_report.valid_candidate_count,
        best_mean_rank_ic=evaluation_report.best_mean_rank_ic,
        best_worst_fold_rank_ic=evaluation_report.best_worst_fold_rank_ic,
        blockers=(),
    )


def validate_us_a0_preregistration_bundle(
    document: Mapping[str, object],
    phase: USAgentValuePhase,
) -> USAgentValueExperimentProtocol:
    vocabulary = canonical_us_a0_primitive_vocabulary()
    protocol = canonical_us_a0_experiment_protocol(phase)
    manual = canonical_us_a0_manual_candidates()[: protocol.candidate_budget_per_run]
    expected: dict[str, object] = {
        "schema_version": "finagent.us-agent-value-preregistration-bundle.v1",
        "phase": phase.value,
        "vocabulary": vocabulary.to_dict(),
        "protocol": protocol.to_dict(),
        "manual_candidates": [candidate.to_dict() for candidate in manual],
        "manual_candidate_count": len(manual),
        "scope": "pre_result_controlled_experiment_preregistration_only",
        "status_authority": False,
        "stage_exit_authority": False,
        "agent_value_gate_authority": False,
        "alpha_authority": False,
    }
    expected["bundle_id"] = _canonical_hash(
        expected,
        prefix="us-agent-value-preregistration",
    )
    if dict(document) != expected:
        raise ValueError("US-A0 preregistration artifact does not match the exact frozen canonical bundle")
    return protocol

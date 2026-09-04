from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from finagent.research.us_baseline_evaluation import (
    USBaselineCandidateEvidence,
    USBaselineEvaluationReport,
    USBaselineRunSpec,
)
from finagent.research.us_baseline_walkforward import (
    USBaselineFoldExecutionSpec,
    USBaselineWalkForwardProtocol,
    bind_us_b0_fold_execution_specs,
    canonical_us_b0_pilot_walk_forward,
)
from finagent.research.us_baseline_walkforward_aggregate import (
    USBaselineWalkForwardAggregateReport,
    aggregate_us_b0_walk_forward,
)

_MATERIALIZATION_SCHEMA = "finagent.us-baseline-materialization-report.v1"
_EVALUATION_SCHEMA = "finagent.us-baseline-evaluation-report.v1"
_RUN_SPEC_SCHEMA = "finagent.us-baseline-run-spec.v1"
_CANDIDATE_SCHEMA = "finagent.us-baseline-candidate-evidence.v1"


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
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be integer-like")
    result = int(value)
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field_name} must be integer-like")
    return result


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _optional_float(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be numeric or null")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _float(value: object, field_name: str) -> float:
    result = _optional_float(value, field_name)
    if result is None:
        raise ValueError(f"{field_name} must be numeric")
    return result


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    return tuple(_text(item, f"{field_name}[]") for item in _sequence(value, field_name))


def validate_canonical_us_b0_protocol_document(
    document: Mapping[str, object],
) -> USBaselineWalkForwardProtocol:
    """Require the exact preregistered pilot protocol, not merely a matching schema."""

    protocol = canonical_us_b0_pilot_walk_forward()
    if dict(document) != protocol.to_dict():
        raise ValueError(
            "US-B0 formal execution requires the exact canonical preregistered walk-forward artifact"
        )
    return protocol


def _parse_run_spec(document: Mapping[str, object]) -> USBaselineRunSpec:
    if _text(document.get("schema_version"), "run_spec.schema_version") != _RUN_SPEC_SCHEMA:
        raise ValueError("unsupported US-B0 run-spec schema")
    run_spec = USBaselineRunSpec(
        certification_report_id=_text(
            document.get("certification_report_id"),
            "run_spec.certification_report_id",
        ),
        certification_outcome=_text(
            document.get("certification_outcome"),
            "run_spec.certification_outcome",
        ),
        engineering_universe_id=_text(
            document.get("engineering_universe_id"),
            "run_spec.engineering_universe_id",
        ),
        denominator_id=_text(document.get("denominator_id"), "run_spec.denominator_id"),
        label_name=_text(document.get("label_name"), "run_spec.label_name"),
        signal_interval=_text(document.get("signal_interval"), "run_spec.signal_interval"),
        minimum_cross_section=_integer(
            document.get("minimum_cross_section"),
            "run_spec.minimum_cross_section",
        ),
        minimum_evaluated_periods=_integer(
            document.get("minimum_evaluated_periods"),
            "run_spec.minimum_evaluated_periods",
        ),
        minimum_ic_periods=_integer(
            document.get("minimum_ic_periods"),
            "run_spec.minimum_ic_periods",
        ),
        fail_on_partial_realized_label=_boolean(
            document.get("fail_on_partial_realized_label"),
            "run_spec.fail_on_partial_realized_label",
        ),
    )
    if _text(document.get("spec_id"), "run_spec.spec_id") != run_spec.spec_id:
        raise ValueError("US-B0 run-spec content identity mismatch")
    return run_spec


def parse_us_baseline_evaluation_report(
    document: Mapping[str, object],
) -> USBaselineEvaluationReport:
    """Reconstruct and re-hash an authoritative evaluation report without recomputing statistics."""

    if _text(document.get("schema_version"), "evaluation.schema_version") != _EVALUATION_SCHEMA:
        raise ValueError("unsupported US-B0 evaluation report schema")
    run_spec = _parse_run_spec(_mapping(document.get("run_spec"), "evaluation.run_spec"))
    denominator_id = _text(document.get("denominator_id"), "evaluation.denominator_id")
    if denominator_id != run_spec.denominator_id:
        raise ValueError("evaluation denominator/run-spec identity mismatch")

    candidates: list[USBaselineCandidateEvidence] = []
    for index, raw_candidate in enumerate(
        _sequence(document.get("candidates"), "evaluation.candidates")
    ):
        candidate_document = _mapping(raw_candidate, f"evaluation.candidates[{index}]")
        if (
            _text(
                candidate_document.get("schema_version"),
                f"evaluation.candidates[{index}].schema_version",
            )
            != _CANDIDATE_SCHEMA
        ):
            raise ValueError("unsupported US-B0 candidate evidence schema")
        candidate = USBaselineCandidateEvidence(
            feature_id=_text(
                candidate_document.get("feature_id"),
                f"evaluation.candidates[{index}].feature_id",
            ),
            feature_spec_id=_text(
                candidate_document.get("feature_spec_id"),
                f"evaluation.candidates[{index}].feature_spec_id",
            ),
            run_spec_id=_text(
                candidate_document.get("run_spec_id"),
                f"evaluation.candidates[{index}].run_spec_id",
            ),
            observation_count=_integer(
                candidate_document.get("observation_count"),
                f"evaluation.candidates[{index}].observation_count",
            ),
            eligible_cell_count=_integer(
                candidate_document.get("eligible_cell_count"),
                f"evaluation.candidates[{index}].eligible_cell_count",
            ),
            valid_feature_cell_count=_integer(
                candidate_document.get("valid_feature_cell_count"),
                f"evaluation.candidates[{index}].valid_feature_cell_count",
            ),
            evaluated_periods=_integer(
                candidate_document.get("evaluated_periods"),
                f"evaluation.candidates[{index}].evaluated_periods",
            ),
            ic_periods=_integer(
                candidate_document.get("ic_periods"),
                f"evaluation.candidates[{index}].ic_periods",
            ),
            boundary_unrealized_periods=_integer(
                candidate_document.get("boundary_unrealized_periods"),
                f"evaluation.candidates[{index}].boundary_unrealized_periods",
            ),
            mean_rank_ic=_optional_float(
                candidate_document.get("mean_rank_ic"),
                f"evaluation.candidates[{index}].mean_rank_ic",
            ),
            mean_gross_return=_optional_float(
                candidate_document.get("mean_gross_return"),
                f"evaluation.candidates[{index}].mean_gross_return",
            ),
            mean_one_way_turnover=_optional_float(
                candidate_document.get("mean_one_way_turnover"),
                f"evaluation.candidates[{index}].mean_one_way_turnover",
            ),
            mean_gross_traded_weight=_optional_float(
                candidate_document.get("mean_gross_traded_weight"),
                f"evaluation.candidates[{index}].mean_gross_traded_weight",
            ),
            feature_coverage=_float(
                candidate_document.get("feature_coverage"),
                f"evaluation.candidates[{index}].feature_coverage",
            ),
            blockers=_strings(
                candidate_document.get("blockers", ()),
                f"evaluation.candidates[{index}].blockers",
            ),
            partial_realized_label_omitted_periods=_integer(
                candidate_document.get("partial_realized_label_omitted_periods", 0),
                f"evaluation.candidates[{index}].partial_realized_label_omitted_periods",
            ),
        )
        if candidate.run_spec_id != run_spec.spec_id:
            raise ValueError("candidate/run-spec identity mismatch")
        if _text(
            candidate_document.get("evidence_id"),
            f"evaluation.candidates[{index}].evidence_id",
        ) != candidate.evidence_id:
            raise ValueError("candidate evidence content identity mismatch")
        if _boolean(
            candidate_document.get("valid"),
            f"evaluation.candidates[{index}].valid",
        ) is not candidate.valid:
            raise ValueError("candidate valid flag does not match blockers")
        candidates.append(candidate)

    report = USBaselineEvaluationReport(
        run_spec=run_spec,
        denominator_id=denominator_id,
        candidates=tuple(candidates),
    )
    if _integer(
        document.get("candidate_count"),
        "evaluation.candidate_count",
    ) != len(report.candidates):
        raise ValueError("evaluation candidate_count mismatch")
    if _integer(
        document.get("valid_candidate_count"),
        "evaluation.valid_candidate_count",
    ) != report.valid_candidate_count:
        raise ValueError("evaluation valid_candidate_count mismatch")
    if _strings(document.get("blockers", ()), "evaluation.blockers") != report.blockers:
        raise ValueError("evaluation blocker summary mismatch")
    if _text(document.get("report_id"), "evaluation.report_id") != report.report_id:
        raise ValueError("evaluation report content identity mismatch")
    return report


def _recompute_input_plan_id(document: Mapping[str, object]) -> str:
    payload = {
        "schema_version": _text(document.get("schema_version"), "input_plan.schema_version"),
        "run_spec_id": _text(document.get("run_spec_id"), "input_plan.run_spec_id"),
        "resampled_plan_id": _text(
            document.get("resampled_plan_id"),
            "input_plan.resampled_plan_id",
        ),
        "label_plan_id": _text(document.get("label_plan_id"), "input_plan.label_plan_id"),
        "resampling_evidence_id": _text(
            document.get("resampling_evidence_id"),
            "input_plan.resampling_evidence_id",
        ),
        "label_evidence_id": _text(
            document.get("label_evidence_id"),
            "input_plan.label_evidence_id",
        ),
        "source_data_version": _text(
            document.get("source_data_version"),
            "input_plan.source_data_version",
        ),
        "data_version": _text(document.get("data_version"), "input_plan.data_version"),
        "partition_months": list(
            _strings(document.get("partition_months", ()), "input_plan.partition_months")
        ),
        "output_columns": list(
            _strings(document.get("output_columns", ()), "input_plan.output_columns")
        ),
    }
    return _canonical_hash(payload, prefix="us-baseline-input-plan")


def _recompute_observation_artifact_id(document: Mapping[str, object]) -> str:
    payload = {
        "schema_version": _text(
            document.get("schema_version"),
            "observation_artifact.schema_version",
        ),
        "run_spec_id": _text(
            document.get("run_spec_id"),
            "observation_artifact.run_spec_id",
        ),
        "denominator_id": _text(
            document.get("denominator_id"),
            "observation_artifact.denominator_id",
        ),
        "row_count": _integer(
            document.get("row_count"),
            "observation_artifact.row_count",
        ),
        "content_sha256": _text(
            document.get("content_sha256"),
            "observation_artifact.content_sha256",
        ).lower(),
    }
    return _canonical_hash(payload, prefix="us-baseline-observations")


def _recompute_materialization_report_id(document: Mapping[str, object]) -> str:
    run_spec = _mapping(document.get("run_spec"), "materialization.run_spec")
    input_plan = _mapping(document.get("input_plan"), "materialization.input_plan")
    input_materialization = _mapping(
        document.get("input_materialization"),
        "materialization.input_materialization",
    )
    observation_artifact = _mapping(
        document.get("observation_artifact"),
        "materialization.observation_artifact",
    )
    diagnostics = _mapping(document.get("diagnostics"), "materialization.diagnostics")
    engineering_assets = _strings(
        document.get("engineering_assets", ()),
        "materialization.engineering_assets",
    )
    payload = {
        "schema_version": _text(
            document.get("schema_version"),
            "materialization.schema_version",
        ),
        "run_spec_id": _text(run_spec.get("spec_id"), "materialization.run_spec.spec_id"),
        "input_plan_id": _text(input_plan.get("plan_id"), "materialization.input_plan.plan_id"),
        "input_materialization_id": _text(
            input_materialization.get("materialization_id"),
            "materialization.input_materialization.materialization_id",
        ),
        "observation_artifact_id": _text(
            observation_artifact.get("artifact_id"),
            "materialization.observation_artifact.artifact_id",
        ),
        "diagnostics": dict(diagnostics),
        "evaluation_report_id": _text(
            document.get("evaluation_report_id"),
            "materialization.evaluation_report_id",
        ),
        "engineering_assets": list(engineering_assets),
    }
    return _canonical_hash(payload, prefix="us-baseline-materialization")


@dataclass(frozen=True, slots=True)
class USBaselineFoldRunManifest:
    execution_spec: USBaselineFoldExecutionSpec
    materialization_report_id: str
    evaluation_report_id: str
    input_plan_id: str
    input_materialization_id: str
    observation_artifact_id: str
    engineering_universe_id: str
    engineering_asset_count: int
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-baseline-fold-run-manifest.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "materialization_report_id",
            "evaluation_report_id",
            "input_plan_id",
            "input_materialization_id",
            "observation_artifact_id",
            "engineering_universe_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if not 20 <= self.engineering_asset_count <= 30:
            raise ValueError("formal fold manifest EngineeringUniverse size must be in 20..30")

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def manifest_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-baseline-fold-run",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "execution_spec": self.execution_spec.to_dict(),
            "materialization_report_id": self.materialization_report_id,
            "evaluation_report_id": self.evaluation_report_id,
            "input_plan_id": self.input_plan_id,
            "input_materialization_id": self.input_materialization_id,
            "observation_artifact_id": self.observation_artifact_id,
            "engineering_universe_id": self.engineering_universe_id,
            "engineering_asset_count": self.engineering_asset_count,
            "passed": self.passed,
            "blockers": list(self.blockers),
            "window_binding": "runner_enforced_exact_frozen_fold_evaluation_window",
            "status_authority": False,
            "stage_exit_authority": False,
            "factor_selection_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["manifest_id"] = self.manifest_id
        return payload


def build_us_b0_fold_run_manifest(
    execution_spec: USBaselineFoldExecutionSpec,
    materialization_document: Mapping[str, object],
    evaluation_report: USBaselineEvaluationReport,
) -> USBaselineFoldRunManifest:
    if (
        _text(
            materialization_document.get("schema_version"),
            "materialization.schema_version",
        )
        != _MATERIALIZATION_SCHEMA
    ):
        raise ValueError("unsupported US-B0 materialization report schema")
    run_spec = _parse_run_spec(
        _mapping(materialization_document.get("run_spec"), "materialization.run_spec")
    )
    if run_spec.spec_id != execution_spec.run_spec_id:
        raise ValueError("fold materialization/run execution-spec identity mismatch")
    if run_spec.spec_id != evaluation_report.run_spec.spec_id:
        raise ValueError("fold materialization/evaluation run-spec identity mismatch")

    report_id = _text(
        materialization_document.get("report_id"),
        "materialization.report_id",
    )
    if report_id != _recompute_materialization_report_id(materialization_document):
        raise ValueError("materialization report content identity mismatch")

    evaluation_report_id = _text(
        materialization_document.get("evaluation_report_id"),
        "materialization.evaluation_report_id",
    )
    if evaluation_report_id != evaluation_report.report_id:
        raise ValueError("materialization/evaluation report identity mismatch")

    input_plan = _mapping(materialization_document.get("input_plan"), "materialization.input_plan")
    input_plan_id = _text(input_plan.get("plan_id"), "materialization.input_plan.plan_id")
    if input_plan_id != _recompute_input_plan_id(input_plan):
        raise ValueError("materialization input-plan content identity mismatch")
    if _text(input_plan.get("run_spec_id"), "materialization.input_plan.run_spec_id") != run_spec.spec_id:
        raise ValueError("materialization input-plan/run-spec identity mismatch")

    input_materialization = _mapping(
        materialization_document.get("input_materialization"),
        "materialization.input_materialization",
    )
    if _text(
        input_materialization.get("plan_id"),
        "materialization.input_materialization.plan_id",
    ) != input_plan_id:
        raise ValueError("input materialization/input-plan identity mismatch")
    input_materialization_id = _text(
        input_materialization.get("materialization_id"),
        "materialization.input_materialization.materialization_id",
    )

    observation_artifact = _mapping(
        materialization_document.get("observation_artifact"),
        "materialization.observation_artifact",
    )
    observation_artifact_id = _text(
        observation_artifact.get("artifact_id"),
        "materialization.observation_artifact.artifact_id",
    )
    if observation_artifact_id != _recompute_observation_artifact_id(observation_artifact):
        raise ValueError("observation artifact content identity mismatch")
    if _text(
        observation_artifact.get("run_spec_id"),
        "materialization.observation_artifact.run_spec_id",
    ) != run_spec.spec_id:
        raise ValueError("observation artifact/run-spec identity mismatch")
    if _text(
        observation_artifact.get("denominator_id"),
        "materialization.observation_artifact.denominator_id",
    ) != run_spec.denominator_id:
        raise ValueError("observation artifact/denominator identity mismatch")

    engineering_assets = _strings(
        materialization_document.get("engineering_assets", ()),
        "materialization.engineering_assets",
    )
    engineering_asset_count = _integer(
        materialization_document.get("engineering_asset_count"),
        "materialization.engineering_asset_count",
    )
    if engineering_asset_count != len(engineering_assets):
        raise ValueError("materialization engineering asset count mismatch")
    if len(set(engineering_assets)) != len(engineering_assets):
        raise ValueError("materialization EngineeringUniverse assets must be unique")

    for field_name in (
        "stage_exit_authority",
        "factor_selection_authority",
        "alpha_authority",
    ):
        if _boolean(
            materialization_document.get(field_name),
            f"materialization.{field_name}",
        ):
            raise ValueError(f"US-B0 fold materialization cannot claim {field_name}")

    materialization_blockers = _strings(
        materialization_document.get("blockers", ()),
        "materialization.blockers",
    )
    materialization_passed = _boolean(
        materialization_document.get("passed"),
        "materialization.passed",
    )
    if materialization_passed is not (not materialization_blockers):
        raise ValueError("materialization passed flag does not match blockers")
    blockers = list(materialization_blockers)
    blockers.extend(f"evaluation:{item}" for item in evaluation_report.blockers)

    return USBaselineFoldRunManifest(
        execution_spec=execution_spec,
        materialization_report_id=report_id,
        evaluation_report_id=evaluation_report.report_id,
        input_plan_id=input_plan_id,
        input_materialization_id=input_materialization_id,
        observation_artifact_id=observation_artifact_id,
        engineering_universe_id=run_spec.engineering_universe_id,
        engineering_asset_count=engineering_asset_count,
        blockers=tuple(dict.fromkeys(blockers)),
    )


@dataclass(frozen=True, slots=True)
class USBaselineWalkForwardEvidenceGraph:
    protocol_id: str
    run_spec_id: str
    denominator_id: str
    fold_manifests: tuple[USBaselineFoldRunManifest, ...]
    aggregate_report_id: str
    aggregate_candidate_count: int
    aggregate_valid_candidate_count: int
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-baseline-walk-forward-evidence-graph.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "protocol_id",
            "run_spec_id",
            "denominator_id",
            "aggregate_report_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if not self.fold_manifests:
            raise ValueError("walk-forward evidence graph requires fold manifests")
        if self.aggregate_candidate_count < 1:
            raise ValueError("aggregate_candidate_count must be positive")
        if not 0 <= self.aggregate_valid_candidate_count <= self.aggregate_candidate_count:
            raise ValueError("aggregate valid-candidate count is invalid")

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def ready_for_us_a0_candidate(self) -> bool:
        return self.passed and self.aggregate_valid_candidate_count == self.aggregate_candidate_count

    @property
    def graph_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-baseline-walk-forward-evidence",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "run_spec_id": self.run_spec_id,
            "denominator_id": self.denominator_id,
            "fold_count": len(self.fold_manifests),
            "fold_manifests": [item.to_dict() for item in self.fold_manifests],
            "fold_manifest_ids": [item.manifest_id for item in self.fold_manifests],
            "fold_execution_spec_ids": [
                item.execution_spec.execution_spec_id for item in self.fold_manifests
            ],
            "fold_materialization_report_ids": [
                item.materialization_report_id for item in self.fold_manifests
            ],
            "fold_evaluation_report_ids": [
                item.evaluation_report_id for item in self.fold_manifests
            ],
            "aggregate_report_id": self.aggregate_report_id,
            "aggregate_candidate_count": self.aggregate_candidate_count,
            "aggregate_valid_candidate_count": self.aggregate_valid_candidate_count,
            "passed": self.passed,
            "ready_for_us_a0_candidate": self.ready_for_us_a0_candidate,
            "blockers": list(self.blockers),
            "scope": "split_bound_manual_baseline_evidence_graph",
            "status_authority": False,
            "stage_exit_authority": False,
            "factor_selection_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["graph_id"] = self.graph_id
        return payload


def assemble_us_b0_walk_forward_evidence(
    protocol: USBaselineWalkForwardProtocol,
    materialization_documents: Sequence[Mapping[str, object]],
    evaluation_documents: Sequence[Mapping[str, object]],
) -> tuple[
    tuple[USBaselineFoldRunManifest, ...],
    USBaselineWalkForwardAggregateReport,
    USBaselineWalkForwardEvidenceGraph,
]:
    if len(materialization_documents) != len(protocol.folds):
        raise ValueError("US-B0 assembly requires one materialization report per frozen fold")
    if len(evaluation_documents) != len(protocol.folds):
        raise ValueError("US-B0 assembly requires one evaluation report per frozen fold")

    evaluations = tuple(parse_us_baseline_evaluation_report(item) for item in evaluation_documents)
    run_spec_ids = {item.run_spec.spec_id for item in evaluations}
    if len(run_spec_ids) != 1:
        raise ValueError("US-B0 fold evaluations must share one run-spec identity")
    run_spec = evaluations[0].run_spec
    execution_specs = bind_us_b0_fold_execution_specs(protocol, run_spec)
    manifests = tuple(
        build_us_b0_fold_run_manifest(execution, materialization, evaluation)
        for execution, materialization, evaluation in zip(
            execution_specs,
            materialization_documents,
            evaluations,
            strict=True,
        )
    )
    aggregate = aggregate_us_b0_walk_forward(protocol, execution_specs, evaluations)

    blockers: list[str] = []
    for manifest in manifests:
        blockers.extend(
            f"fold:{manifest.execution_spec.fold_ordinal}:{item}"
            for item in manifest.blockers
        )
    blockers.extend(f"aggregate:{item}" for item in aggregate.blockers)
    graph = USBaselineWalkForwardEvidenceGraph(
        protocol_id=protocol.protocol_id,
        run_spec_id=run_spec.spec_id,
        denominator_id=run_spec.denominator_id,
        fold_manifests=manifests,
        aggregate_report_id=aggregate.report_id,
        aggregate_candidate_count=len(aggregate.candidates),
        aggregate_valid_candidate_count=sum(item.valid for item in aggregate.candidates),
        blockers=tuple(dict.fromkeys(blockers)),
    )
    return manifests, aggregate, graph

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from finagent.research.us_agent_value_comparison import (
    AgentValueComparisonSnapshot,
    build_agent_value_comparison_snapshot,
)
from finagent.research.us_agent_value_execution import (
    USAgentValueExecutionPlan,
    parse_candidate_generation_run,
)
from finagent.research.us_agent_value_experiment import (
    AgentValueExperiment,
    RunEvaluationLink,
    SearchArmResult,
    USAgentValuePredecessorBinding,
    build_search_arm_result,
)
from finagent.research.us_agent_value_generation import CandidateGenerationRun
from finagent.research.us_agent_value_protocol import USAgentValueExperimentProtocol


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


def _float_or_none(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be numeric or null")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    return tuple(
        _text(item, f"{field_name}[]") for item in _sequence(value, field_name)
    )


def _require_false_authority(
    document: Mapping[str, object],
    field_name: str,
) -> None:
    if _boolean(document.get(field_name), field_name):
        raise ValueError(f"US-A0 evidence cannot claim {field_name}")


def _validate_candidate_aggregate(
    document: Mapping[str, object],
    index: int,
    *,
    generation_run: CandidateGenerationRun,
) -> tuple[bool, float | None, float | None]:
    prefix = f"run_evaluation.candidates[{index}]"
    if _text(document.get("schema_version"), f"{prefix}.schema_version") != (
        "finagent.us-agent-value-candidate-evaluation-aggregate.v1"
    ):
        raise ValueError("unsupported A0 candidate-evaluation aggregate schema")
    claimed_id = _text(document.get("aggregate_id"), f"{prefix}.aggregate_id")
    payload = dict(document)
    del payload["aggregate_id"]
    if claimed_id != _canonical_hash(
        payload,
        prefix="us-agent-value-candidate-evaluation",
    ):
        raise ValueError("A0 candidate-evaluation aggregate content identity mismatch")

    expected_candidate = generation_run.accepted_candidates[index]
    expected_feature = expected_candidate.compile_feature_spec()
    if _text(document.get("candidate_id"), f"{prefix}.candidate_id") != (
        expected_candidate.candidate_id
    ):
        raise ValueError("A0 candidate aggregate/generation candidate identity mismatch")
    if _text(document.get("feature_id"), f"{prefix}.feature_id") != (
        expected_feature.feature_id
    ):
        raise ValueError("A0 candidate aggregate compiled feature identity mismatch")
    if _text(document.get("feature_spec_id"), f"{prefix}.feature_spec_id") != (
        expected_feature.spec_id
    ):
        raise ValueError("A0 candidate aggregate compiled feature-spec identity mismatch")

    fold_count = _integer(document.get("fold_count"), f"{prefix}.fold_count")
    valid_fold_count = _integer(
        document.get("valid_fold_count"),
        f"{prefix}.valid_fold_count",
    )
    if fold_count != 3 or not 0 <= valid_fold_count <= fold_count:
        raise ValueError("A0 candidate aggregate must bind exactly three frozen folds")
    invalid_reasons = _strings(
        document.get("invalid_reasons", ()),
        f"{prefix}.invalid_reasons",
    )
    expected_valid = valid_fold_count == fold_count and not invalid_reasons
    if _boolean(document.get("valid"), f"{prefix}.valid") is not expected_valid:
        raise ValueError("A0 candidate aggregate valid flag is inconsistent")

    mean_rank_ic = _float_or_none(
        document.get("mean_rank_ic"),
        f"{prefix}.mean_rank_ic",
    )
    worst_fold_rank_ic = _float_or_none(
        document.get("worst_fold_rank_ic"),
        f"{prefix}.worst_fold_rank_ic",
    )
    for metric in (
        "mean_gross_return",
        "worst_fold_gross_return",
        "mean_one_way_turnover",
        "maximum_one_way_turnover",
    ):
        _float_or_none(document.get(metric), f"{prefix}.{metric}")
    coverage = _float_or_none(
        document.get("mean_feature_coverage"),
        f"{prefix}.mean_feature_coverage",
    )
    if coverage is None or not 0.0 <= coverage <= 1.0:
        raise ValueError("A0 candidate aggregate feature coverage must be in [0,1]")
    return expected_valid, mean_rank_ic, worst_fold_rank_ic


def _validate_run_evaluation_document(
    document: Mapping[str, object],
    generation_run: CandidateGenerationRun,
) -> tuple[str, str, tuple[str, ...], str]:
    if _text(document.get("schema_version"), "run_evaluation.schema_version") != (
        "finagent.us-agent-value-run-evaluation-report.v1"
    ):
        raise ValueError("unsupported A0 run-evaluation report schema")
    claimed_id = _text(document.get("report_id"), "run_evaluation.report_id")
    payload = dict(document)
    del payload["report_id"]
    if claimed_id != _canonical_hash(payload, prefix="us-agent-value-run-evaluation"):
        raise ValueError("A0 run-evaluation report content identity mismatch")
    evaluation_binding_id = _text(
        document.get("evaluation_binding_id"),
        "run_evaluation.evaluation_binding_id",
    )
    _text(document.get("denominator_id"), "run_evaluation.denominator_id")
    _text(document.get("run_spec_id"), "run_evaluation.run_spec_id")
    if _text(
        document.get("generation_run_id"),
        "run_evaluation.generation_run_id",
    ) != generation_run.run_id:
        raise ValueError("A0 run-evaluation/generation-run identity mismatch")
    if _text(document.get("arm"), "run_evaluation.arm") != (
        generation_run.spec.arm.value
    ):
        raise ValueError("A0 run-evaluation/search-arm mismatch")

    status = _text(document.get("status"), "run_evaluation.status")
    if status not in {"EVALUATED", "NO_ACCEPTED_CANDIDATES"}:
        raise ValueError("unsupported A0 run-evaluation status")
    evaluated_count = _integer(
        document.get("evaluated_candidate_count"),
        "run_evaluation.evaluated_candidate_count",
    )
    valid_count = _integer(
        document.get("valid_candidate_count"),
        "run_evaluation.valid_candidate_count",
    )
    if evaluated_count != len(generation_run.accepted_candidates):
        raise ValueError(
            "A0 evaluated candidate count differs from accepted generation candidates"
        )
    if not 0 <= valid_count <= evaluated_count:
        raise ValueError("A0 run-evaluation valid candidate count is invalid")

    candidate_documents = tuple(
        _mapping(raw, f"run_evaluation.candidates[{index}]")
        for index, raw in enumerate(
            _sequence(document.get("candidates", ()), "run_evaluation.candidates")
        )
    )
    if len(candidate_documents) != evaluated_count:
        raise ValueError("A0 run-evaluation candidate array count mismatch")
    summaries = tuple(
        _validate_candidate_aggregate(
            candidate,
            index,
            generation_run=generation_run,
        )
        for index, candidate in enumerate(candidate_documents)
    )
    computed_valid_count = sum(valid for valid, _, _ in summaries)
    if valid_count != computed_valid_count:
        raise ValueError(
            "A0 run-evaluation valid candidate count differs from candidate aggregates"
        )

    valid_mean_rank_ics = tuple(
        float(mean_rank_ic)
        for valid, mean_rank_ic, _ in summaries
        if valid and mean_rank_ic is not None
    )
    valid_worst_rank_ics = tuple(
        float(worst_rank_ic)
        for valid, _, worst_rank_ic in summaries
        if valid and worst_rank_ic is not None
    )
    expected_best_mean = max(valid_mean_rank_ics) if valid_mean_rank_ics else None
    expected_best_worst = max(valid_worst_rank_ics) if valid_worst_rank_ics else None
    if _float_or_none(
        document.get("best_mean_rank_ic"),
        "run_evaluation.best_mean_rank_ic",
    ) != expected_best_mean:
        raise ValueError("A0 run-evaluation best mean RankIC summary is inconsistent")
    if _float_or_none(
        document.get("best_worst_fold_rank_ic"),
        "run_evaluation.best_worst_fold_rank_ic",
    ) != expected_best_worst:
        raise ValueError("A0 run-evaluation best worst-fold RankIC summary is inconsistent")

    fold_report_ids = _strings(
        document.get("fold_evaluation_report_ids", ()),
        "run_evaluation.fold_evaluation_report_ids",
    )
    if status == "NO_ACCEPTED_CANDIDATES":
        if evaluated_count != 0 or valid_count != 0 or candidate_documents:
            raise ValueError("NO_ACCEPTED_CANDIDATES run cannot carry financial evidence")
        if fold_report_ids:
            raise ValueError("NO_ACCEPTED_CANDIDATES run cannot carry fold evidence")
    else:
        if evaluated_count < 1:
            raise ValueError("EVALUATED run requires accepted candidates")
        if len(fold_report_ids) != 3 or len(set(fold_report_ids)) != 3:
            raise ValueError(
                "EVALUATED A0 run requires three unique fold-evaluation reports"
            )

    if not _boolean(document.get("evidence_complete"), "run_evaluation.evidence_complete"):
        raise ValueError("A0 run-evaluation report must be evidence-complete")
    if not _boolean(
        document.get("candidate_invalidity_is_research_result_not_system_blocker"),
        "run_evaluation.candidate_invalidity_is_research_result_not_system_blocker",
    ):
        raise ValueError("A0 run-evaluation report changed candidate-invalidity semantics")
    for field_name in (
        "stage_exit_authority",
        "agent_value_gate_authority",
        "alpha_authority",
    ):
        _require_false_authority(document, field_name)
    return claimed_id, status, fold_report_ids, evaluation_binding_id


def _parse_evaluation_link(
    document: Mapping[str, object],
    generation_run: CandidateGenerationRun,
    run_evaluation_document: Mapping[str, object],
    run_evaluation_report_id: str,
) -> RunEvaluationLink:
    blockers = _strings(document.get("blockers", ()), "evaluation_link.blockers")
    link = RunEvaluationLink(
        generation_run_id=_text(
            document.get("generation_run_id"),
            "evaluation_link.generation_run_id",
        ),
        authoritative_evidence_id=_text(
            document.get("authoritative_evidence_id"),
            "evaluation_link.authoritative_evidence_id",
        ),
        evaluated_candidate_count=_integer(
            document.get("evaluated_candidate_count"),
            "evaluation_link.evaluated_candidate_count",
        ),
        valid_candidate_count=_integer(
            document.get("valid_candidate_count"),
            "evaluation_link.valid_candidate_count",
        ),
        best_mean_rank_ic=_float_or_none(
            document.get("best_mean_rank_ic"),
            "evaluation_link.best_mean_rank_ic",
        ),
        best_worst_fold_rank_ic=_float_or_none(
            document.get("best_worst_fold_rank_ic"),
            "evaluation_link.best_worst_fold_rank_ic",
        ),
        blockers=blockers,
    )
    if dict(document) != link.to_dict():
        raise ValueError("A0 evaluation-link content identity mismatch")
    if link.generation_run_id != generation_run.run_id:
        raise ValueError("A0 evaluation-link/generation-run identity mismatch")
    if link.authoritative_evidence_id != run_evaluation_report_id:
        raise ValueError("A0 evaluation link does not bind the run-evaluation report")
    scalar_pairs = (
        (
            link.evaluated_candidate_count,
            _integer(
                run_evaluation_document.get("evaluated_candidate_count"),
                "run_evaluation.evaluated_candidate_count",
            ),
        ),
        (
            link.valid_candidate_count,
            _integer(
                run_evaluation_document.get("valid_candidate_count"),
                "run_evaluation.valid_candidate_count",
            ),
        ),
        (
            link.best_mean_rank_ic,
            _float_or_none(
                run_evaluation_document.get("best_mean_rank_ic"),
                "run_evaluation.best_mean_rank_ic",
            ),
        ),
        (
            link.best_worst_fold_rank_ic,
            _float_or_none(
                run_evaluation_document.get("best_worst_fold_rank_ic"),
                "run_evaluation.best_worst_fold_rank_ic",
            ),
        ),
    )
    if any(left != right for left, right in scalar_pairs):
        raise ValueError(
            "A0 evaluation-link metrics differ from authoritative run evaluation"
        )
    return link


def _validate_fold_materialization_manifest(
    document: Mapping[str, object],
    *,
    execution_plan: USAgentValueExecutionPlan,
    generation_run: CandidateGenerationRun,
    evaluation_binding_id: str,
) -> tuple[str, int, str]:
    if _text(document.get("schema_version"), "fold_manifest.schema_version") != (
        "finagent.us-agent-value-fold-materialization-manifest.v1"
    ):
        raise ValueError("unsupported A0 fold-materialization manifest schema")
    claimed_id = _text(document.get("manifest_id"), "fold_manifest.manifest_id")
    payload = dict(document)
    del payload["manifest_id"]
    if claimed_id != _canonical_hash(
        payload,
        prefix="us-agent-value-fold-materialization",
    ):
        raise ValueError("A0 fold-materialization manifest content identity mismatch")
    if _text(
        document.get("execution_plan_id"),
        "fold_manifest.execution_plan_id",
    ) != execution_plan.plan_id:
        raise ValueError("A0 fold manifest/execution-plan identity mismatch")
    if _text(
        document.get("preregistration_bundle_id"),
        "fold_manifest.preregistration_bundle_id",
    ) != execution_plan.preregistration_bundle_id:
        raise ValueError("A0 fold manifest/preregistration identity mismatch")
    if _text(
        document.get("generation_run_id"),
        "fold_manifest.generation_run_id",
    ) != generation_run.run_id:
        raise ValueError("A0 fold manifest/generation-run identity mismatch")
    if _text(
        document.get("evaluation_binding_id"),
        "fold_manifest.evaluation_binding_id",
    ) != evaluation_binding_id:
        raise ValueError("A0 fold manifest/evaluation-binding identity mismatch")
    ordinal = _integer(document.get("fold_ordinal"), "fold_manifest.fold_ordinal")
    if ordinal not in (1, 2, 3):
        raise ValueError("A0 fold manifest ordinal must be 1..3")
    if not _boolean(document.get("technical_passed"), "fold_manifest.technical_passed"):
        raise ValueError("A0 experiment assembly requires technically passing fold evidence")
    if _strings(
        document.get("technical_blockers", ()),
        "fold_manifest.technical_blockers",
    ):
        raise ValueError("technically passing A0 fold evidence cannot carry blockers")
    if not _boolean(
        document.get("candidate_invalidity_is_not_a_technical_blocker"),
        "fold_manifest.candidate_invalidity_is_not_a_technical_blocker",
    ):
        raise ValueError("A0 fold manifest changed candidate-invalidity semantics")
    for field_name in (
        "stage_exit_authority",
        "agent_value_gate_authority",
        "alpha_authority",
    ):
        _require_false_authority(document, field_name)
    return (
        claimed_id,
        ordinal,
        _text(
            document.get("fold_evaluation_report_id"),
            "fold_manifest.fold_evaluation_report_id",
        ),
    )


@dataclass(frozen=True, slots=True)
class ParsedUSAgentValueRunEvidence:
    generation_run: CandidateGenerationRun
    evaluation_link: RunEvaluationLink
    run_evaluation_report_id: str
    run_evaluation_status: str
    run_evidence_manifest_id: str
    evaluation_binding_id: str
    predecessor_binding_id: str
    fold_materialization_manifest_ids: tuple[str, ...]
    schema_version: str = "finagent.us-agent-value-parsed-run-evidence.v1"

    @property
    def run_spec_id(self) -> str:
        return self.generation_run.spec.run_spec_id

    @property
    def run_id(self) -> str:
        return self.generation_run.run_id

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generation_run_id": self.run_id,
            "generation_run_spec_id": self.run_spec_id,
            "arm": self.generation_run.spec.arm.value,
            "phase": self.generation_run.spec.phase.value,
            "evaluation_link_id": self.evaluation_link.link_id,
            "run_evaluation_report_id": self.run_evaluation_report_id,
            "run_evaluation_status": self.run_evaluation_status,
            "run_evidence_manifest_id": self.run_evidence_manifest_id,
            "evaluation_binding_id": self.evaluation_binding_id,
            "predecessor_binding_id": self.predecessor_binding_id,
            "fold_materialization_manifest_ids": list(
                self.fold_materialization_manifest_ids
            ),
            "technical_passed": True,
        }


def parse_us_a0_run_evidence_bundle(
    *,
    execution_plan: USAgentValueExecutionPlan,
    predecessor: USAgentValuePredecessorBinding,
    generation_document: Mapping[str, object],
    run_evaluation_document: Mapping[str, object],
    evaluation_link_document: Mapping[str, object],
    run_manifest_document: Mapping[str, object],
) -> ParsedUSAgentValueRunEvidence:
    generation_run = parse_candidate_generation_run(generation_document, execution_plan)
    (
        run_evaluation_report_id,
        run_status,
        fold_report_ids,
        run_evaluation_binding_id,
    ) = _validate_run_evaluation_document(
        run_evaluation_document,
        generation_run,
    )
    evaluation_link = _parse_evaluation_link(
        evaluation_link_document,
        generation_run,
        run_evaluation_document,
        run_evaluation_report_id,
    )

    if _text(run_manifest_document.get("schema_version"), "run_manifest.schema_version") != (
        "finagent.us-agent-value-run-evidence-manifest.v1"
    ):
        raise ValueError("unsupported A0 run-evidence manifest schema")
    claimed_manifest_id = _text(
        run_manifest_document.get("manifest_id"),
        "run_manifest.manifest_id",
    )
    payload = dict(run_manifest_document)
    del payload["manifest_id"]
    if claimed_manifest_id != _canonical_hash(
        payload,
        prefix="us-agent-value-run-evidence",
    ):
        raise ValueError("A0 run-evidence manifest content identity mismatch")
    if _text(
        run_manifest_document.get("execution_plan_id"),
        "run_manifest.execution_plan_id",
    ) != execution_plan.plan_id:
        raise ValueError("A0 run manifest/execution-plan identity mismatch")
    if _text(
        run_manifest_document.get("preregistration_bundle_id"),
        "run_manifest.preregistration_bundle_id",
    ) != execution_plan.preregistration_bundle_id:
        raise ValueError("A0 run manifest/preregistration identity mismatch")
    if _text(
        run_manifest_document.get("predecessor_binding_id"),
        "run_manifest.predecessor_binding_id",
    ) != predecessor.binding_id:
        raise ValueError("A0 run manifest/predecessor identity mismatch")
    if _text(
        run_manifest_document.get("generation_run_id"),
        "run_manifest.generation_run_id",
    ) != generation_run.run_id:
        raise ValueError("A0 run manifest/generation-run identity mismatch")
    if _text(
        run_manifest_document.get("generation_run_spec_id"),
        "run_manifest.generation_run_spec_id",
    ) != generation_run.spec.run_spec_id:
        raise ValueError("A0 run manifest/generation-run-spec identity mismatch")
    if _text(run_manifest_document.get("arm"), "run_manifest.arm") != (
        generation_run.spec.arm.value
    ):
        raise ValueError("A0 run manifest/search-arm mismatch")
    if _text(run_manifest_document.get("phase"), "run_manifest.phase") != (
        generation_run.spec.phase.value
    ):
        raise ValueError("A0 run manifest/phase mismatch")
    evaluation_binding_id = _text(
        run_manifest_document.get("evaluation_binding_id"),
        "run_manifest.evaluation_binding_id",
    )
    if evaluation_binding_id != run_evaluation_binding_id:
        raise ValueError("A0 run manifest/run-evaluation binding identity mismatch")
    if _text(
        run_manifest_document.get("run_evaluation_report_id"),
        "run_manifest.run_evaluation_report_id",
    ) != run_evaluation_report_id:
        raise ValueError("A0 run manifest/run-evaluation identity mismatch")
    if _text(
        run_manifest_document.get("run_evaluation_link_id"),
        "run_manifest.run_evaluation_link_id",
    ) != evaluation_link.link_id:
        raise ValueError("A0 run manifest/evaluation-link identity mismatch")
    if _text(
        run_manifest_document.get("run_evaluation_status"),
        "run_manifest.run_evaluation_status",
    ) != run_status:
        raise ValueError("A0 run manifest/run-evaluation status mismatch")
    if not _boolean(
        run_manifest_document.get("technical_passed"),
        "run_manifest.technical_passed",
    ):
        raise ValueError("A0 experiment assembly requires technically passing run evidence")
    if _strings(
        run_manifest_document.get("technical_blockers", ()),
        "run_manifest.technical_blockers",
    ):
        raise ValueError("technically passing A0 run evidence cannot carry blockers")
    if not _boolean(
        run_manifest_document.get(
            "candidate_invalidity_is_research_result_not_system_blocker"
        ),
        "run_manifest.candidate_invalidity_is_research_result_not_system_blocker",
    ):
        raise ValueError("A0 run manifest changed candidate-invalidity semantics")
    for field_name in (
        "status_authority",
        "stage_exit_authority",
        "agent_value_gate_authority",
        "alpha_authority",
    ):
        _require_false_authority(run_manifest_document, field_name)

    raw_fold_manifests = tuple(
        _mapping(raw, f"run_manifest.fold_manifests[{index}]")
        for index, raw in enumerate(
            _sequence(
                run_manifest_document.get("fold_manifests", ()),
                "run_manifest.fold_manifests",
            )
        )
    )
    top_level_fold_manifest_ids = _strings(
        run_manifest_document.get("fold_manifest_ids", ()),
        "run_manifest.fold_manifest_ids",
    )
    parsed_fold_ids: list[str] = []
    parsed_ordinals: list[int] = []
    parsed_fold_report_ids: list[str] = []
    for raw_fold in raw_fold_manifests:
        fold_id, ordinal, fold_report_id = _validate_fold_materialization_manifest(
            raw_fold,
            execution_plan=execution_plan,
            generation_run=generation_run,
            evaluation_binding_id=evaluation_binding_id,
        )
        parsed_fold_ids.append(fold_id)
        parsed_ordinals.append(ordinal)
        parsed_fold_report_ids.append(fold_report_id)

    if tuple(parsed_fold_ids) != top_level_fold_manifest_ids:
        raise ValueError("A0 run manifest fold-manifest identity list mismatch")
    if run_status == "NO_ACCEPTED_CANDIDATES":
        if raw_fold_manifests or fold_report_ids:
            raise ValueError("zero-candidate run evidence cannot carry fold evidence")
    else:
        if tuple(parsed_ordinals) != (1, 2, 3):
            raise ValueError("A0 run manifest must preserve frozen fold order 1,2,3")
        if tuple(parsed_fold_report_ids) != fold_report_ids:
            raise ValueError(
                "A0 run manifest fold-evaluation IDs differ from run evaluation"
            )

    return ParsedUSAgentValueRunEvidence(
        generation_run=generation_run,
        evaluation_link=evaluation_link,
        run_evaluation_report_id=run_evaluation_report_id,
        run_evaluation_status=run_status,
        run_evidence_manifest_id=claimed_manifest_id,
        evaluation_binding_id=evaluation_binding_id,
        predecessor_binding_id=predecessor.binding_id,
        fold_materialization_manifest_ids=tuple(parsed_fold_ids),
    )


@dataclass(frozen=True, slots=True)
class AgentValueExperimentEvidenceGraph:
    execution_plan_id: str
    preregistration_bundle_id: str
    predecessor_binding_id: str
    experiment_id: str
    comparison_snapshot_id: str
    arm_result_ids: tuple[str, ...]
    generation_run_ids: tuple[str, ...]
    run_evidence_manifest_ids: tuple[str, ...]
    run_evaluation_report_ids: tuple[str, ...]
    run_evaluation_link_ids: tuple[str, ...]
    evidence_complete: bool
    ready_for_agent_value_gate_review: bool
    schema_version: str = "finagent.us-agent-value-experiment-evidence-graph.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "execution_plan_id",
            "preregistration_bundle_id",
            "predecessor_binding_id",
            "experiment_id",
            "comparison_snapshot_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if len(self.arm_result_ids) != 3 or len(set(self.arm_result_ids)) != 3:
            raise ValueError("A0 experiment evidence graph requires three unique arm results")
        count = len(self.generation_run_ids)
        if count < 3:
            raise ValueError("A0 experiment evidence graph requires all planned runs")
        if not (
            count
            == len(self.run_evidence_manifest_ids)
            == len(self.run_evaluation_report_ids)
            == len(self.run_evaluation_link_ids)
        ):
            raise ValueError("A0 experiment evidence graph run evidence arrays must align")
        for values in (
            self.generation_run_ids,
            self.run_evidence_manifest_ids,
            self.run_evaluation_report_ids,
            self.run_evaluation_link_ids,
        ):
            if len(values) != len(set(values)):
                raise ValueError("A0 experiment evidence graph run identities must be unique")
        if self.ready_for_agent_value_gate_review and not self.evidence_complete:
            raise ValueError(
                "Agent-value review readiness requires complete experiment evidence"
            )

    @property
    def graph_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-experiment-evidence",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "execution_plan_id": self.execution_plan_id,
            "preregistration_bundle_id": self.preregistration_bundle_id,
            "predecessor_binding_id": self.predecessor_binding_id,
            "experiment_id": self.experiment_id,
            "comparison_snapshot_id": self.comparison_snapshot_id,
            "arm_result_ids": list(self.arm_result_ids),
            "generation_run_ids": list(self.generation_run_ids),
            "run_evidence_manifest_ids": list(self.run_evidence_manifest_ids),
            "run_evaluation_report_ids": list(self.run_evaluation_report_ids),
            "run_evaluation_link_ids": list(self.run_evaluation_link_ids),
            "evidence_complete": self.evidence_complete,
            "ready_for_agent_value_gate_review": (
                self.ready_for_agent_value_gate_review
            ),
            "agent_value_gate_decision": "UNDECIDED_REQUIRES_SEPARATE_REVIEW",
            "scope": "content_addressed_three_arm_agent_value_experiment_evidence_graph",
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["graph_id"] = self.graph_id
        return payload


def assemble_us_a0_experiment_evidence(
    *,
    protocol: USAgentValueExperimentProtocol,
    execution_plan: USAgentValueExecutionPlan,
    predecessor: USAgentValuePredecessorBinding,
    run_evidence: Sequence[ParsedUSAgentValueRunEvidence],
) -> tuple[
    tuple[SearchArmResult, ...],
    AgentValueExperiment,
    AgentValueComparisonSnapshot,
    AgentValueExperimentEvidenceGraph,
]:
    if (
        execution_plan.protocol_id != protocol.protocol_id
        or execution_plan.phase is not protocol.phase
    ):
        raise ValueError(
            "A0 experiment assembly execution-plan/protocol identity mismatch"
        )

    by_spec_id: dict[str, ParsedUSAgentValueRunEvidence] = {}
    for item in run_evidence:
        if item.predecessor_binding_id != predecessor.binding_id:
            raise ValueError("A0 run evidence mixes predecessor identities")
        if item.run_spec_id in by_spec_id:
            raise ValueError(
                "duplicate A0 run evidence for one execution-plan run spec"
            )
        by_spec_id[item.run_spec_id] = item
    expected_spec_ids = tuple(spec.run_spec_id for spec in execution_plan.run_specs)
    if set(by_spec_id) != set(expected_spec_ids):
        missing = sorted(set(expected_spec_ids).difference(by_spec_id))
        extra = sorted(set(by_spec_id).difference(expected_spec_ids))
        raise ValueError(
            "A0 experiment run-evidence set does not match execution plan; "
            f"missing={missing}, extra={extra}"
        )
    ordered = tuple(by_spec_id[spec_id] for spec_id in expected_spec_ids)

    arm_results: list[SearchArmResult] = []
    for arm in protocol.arms:
        arm_items = tuple(
            item for item in ordered if item.generation_run.spec.arm is arm
        )
        planned_specs = tuple(
            spec for spec in execution_plan.run_specs if spec.arm is arm
        )
        if tuple(item.generation_run.spec for item in arm_items) != planned_specs:
            raise ValueError(
                f"{arm.value} run evidence does not preserve execution-plan run order"
            )
        arm_results.append(
            build_search_arm_result(
                protocol,
                arm,
                tuple(item.generation_run for item in arm_items),
                tuple(item.evaluation_link for item in arm_items),
            )
        )
    arm_tuple = tuple(arm_results)
    experiment = AgentValueExperiment(
        protocol=protocol,
        predecessor=predecessor,
        arm_results=arm_tuple,
    )
    comparison = build_agent_value_comparison_snapshot(
        arm_tuple[0],
        arm_tuple[1],
        arm_tuple[2],
    )
    graph = AgentValueExperimentEvidenceGraph(
        execution_plan_id=execution_plan.plan_id,
        preregistration_bundle_id=execution_plan.preregistration_bundle_id,
        predecessor_binding_id=predecessor.binding_id,
        experiment_id=experiment.experiment_id,
        comparison_snapshot_id=comparison.snapshot_id,
        arm_result_ids=tuple(result.result_id for result in arm_tuple),
        generation_run_ids=tuple(item.run_id for item in ordered),
        run_evidence_manifest_ids=tuple(
            item.run_evidence_manifest_id for item in ordered
        ),
        run_evaluation_report_ids=tuple(
            item.run_evaluation_report_id for item in ordered
        ),
        run_evaluation_link_ids=tuple(
            item.evaluation_link.link_id for item in ordered
        ),
        evidence_complete=experiment.evidence_complete,
        ready_for_agent_value_gate_review=(
            experiment.ready_for_agent_value_gate_review
        ),
    )
    return arm_tuple, experiment, comparison, graph

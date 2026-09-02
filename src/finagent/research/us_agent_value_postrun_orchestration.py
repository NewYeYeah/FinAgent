from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from finagent.research.us_agent_value_assembly import (
    AgentValueExperimentEvidenceGraph,
    ParsedUSAgentValueRunEvidence,
    assemble_us_a0_experiment_evidence,
)
from finagent.research.us_agent_value_comparison import AgentValueComparisonSnapshot
from finagent.research.us_agent_value_execution import USAgentValueExecutionPlan
from finagent.research.us_agent_value_experiment import (
    AgentValueExperiment,
    SearchArmResult,
    USAgentValuePredecessorBinding,
)
from finagent.research.us_agent_value_gate import (
    USAgentValueGateAssessment,
    USAgentValueGateDecision,
    USAgentValueGatePolicy,
    USAgentValueGateReview,
    assess_us_a0_agent_value_gate,
    finalize_us_a0_agent_value_gate_review,
)
from finagent.research.us_agent_value_orchestration import (
    USAgentValuePilotOrchestrationCheckpoint,
    USAgentValuePilotOrchestrationState,
    advance_us_a0_pilot_orchestration_checkpoint,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueExperimentProtocol,
    USAgentValuePhase,
)
from finagent.research.us_agent_value_run_orchestration import USAgentValuePilotRunProgress


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


@dataclass(frozen=True, slots=True)
class USAgentValuePilotExperimentAssemblyManifest:
    execution_plan_id: str
    run_evidence_complete_checkpoint_id: str
    run_progress_id: str
    predecessor_binding_id: str
    gate_policy_id: str
    arm_result_ids: tuple[str, ...]
    experiment_id: str
    comparison_snapshot_id: str
    evidence_graph_id: str
    gate_assessment_id: str
    schema_version: str = "finagent.us-agent-value-pilot-experiment-assembly-manifest.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "execution_plan_id",
            "run_evidence_complete_checkpoint_id",
            "run_progress_id",
            "predecessor_binding_id",
            "gate_policy_id",
            "experiment_id",
            "comparison_snapshot_id",
            "evidence_graph_id",
            "gate_assessment_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if len(self.arm_result_ids) != 3 or len(set(self.arm_result_ids)) != 3:
            raise ValueError("PILOT experiment assembly requires three unique arm-result IDs")
        if any(not value.strip() for value in self.arm_result_ids):
            raise ValueError("PILOT experiment arm-result IDs must be non-empty")

    @property
    def manifest_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-pilot-experiment-assembly",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "execution_plan_id": self.execution_plan_id,
            "run_evidence_complete_checkpoint_id": self.run_evidence_complete_checkpoint_id,
            "run_progress_id": self.run_progress_id,
            "predecessor_binding_id": self.predecessor_binding_id,
            "gate_policy_id": self.gate_policy_id,
            "arm_result_ids": list(self.arm_result_ids),
            "experiment_id": self.experiment_id,
            "comparison_snapshot_id": self.comparison_snapshot_id,
            "evidence_graph_id": self.evidence_graph_id,
            "gate_assessment_id": self.gate_assessment_id,
            "assembly_semantics": "deterministic_from_committed_run_evidence_no_row_level_recomputation",
            "assessment_semantics": "preregistered_machine_recommendation_before_independent_review",
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["manifest_id"] = self.manifest_id
        return payload


@dataclass(frozen=True, slots=True)
class USAgentValuePilotExperimentArtifacts:
    arm_results: tuple[SearchArmResult, ...]
    experiment: AgentValueExperiment
    comparison: AgentValueComparisonSnapshot
    evidence_graph: AgentValueExperimentEvidenceGraph
    assessment: USAgentValueGateAssessment
    assembly_manifest: USAgentValuePilotExperimentAssemblyManifest
    checkpoint: USAgentValuePilotOrchestrationCheckpoint


def build_us_a0_pilot_experiment_artifacts(
    *,
    protocol: USAgentValueExperimentProtocol,
    execution_plan: USAgentValueExecutionPlan,
    predecessor: USAgentValuePredecessorBinding,
    run_evidence: Sequence[ParsedUSAgentValueRunEvidence],
    gate_policy: USAgentValueGatePolicy,
    run_checkpoint: USAgentValuePilotOrchestrationCheckpoint,
    run_progress: USAgentValuePilotRunProgress,
) -> USAgentValuePilotExperimentArtifacts:
    if protocol.phase is not USAgentValuePhase.PILOT:
        raise ValueError("post-run orchestration v1 is PILOT-only")
    if gate_policy.phase is not USAgentValuePhase.PILOT:
        raise ValueError("PILOT post-run orchestration requires PILOT Gate policy")
    if run_checkpoint.state is not USAgentValuePilotOrchestrationState.RUN_EVIDENCE_COMPLETE:
        raise ValueError("experiment assembly requires RUN_EVIDENCE_COMPLETE checkpoint")
    if run_checkpoint.execution_plan_id != execution_plan.plan_id:
        raise ValueError("experiment assembly checkpoint/execution-plan identity mismatch")
    if run_progress.execution_plan_id != execution_plan.plan_id:
        raise ValueError("experiment assembly run-progress/execution-plan identity mismatch")
    if run_progress.launch_bundle_id != run_checkpoint.launch_bundle_id:
        raise ValueError("experiment assembly run-progress/launch identity mismatch")
    if run_progress.runtime_policy_id != run_checkpoint.runtime_policy_id:
        raise ValueError("experiment assembly run-progress/runtime-policy identity mismatch")
    if run_progress.agent_generated_checkpoint_id != run_checkpoint.previous_checkpoint_id:
        raise ValueError("experiment assembly run-progress/Agent checkpoint lineage mismatch")
    if run_progress.predecessor_binding_id != predecessor.binding_id:
        raise ValueError("experiment assembly run-progress/predecessor identity mismatch")
    if len(run_progress.completed_runs) != 3:
        raise ValueError("experiment assembly requires the three committed PILOT runs")
    progress_manifest_ids = tuple(
        item.run_evidence_manifest_id for item in run_progress.completed_runs
    )
    if run_checkpoint.run_evidence_manifest_ids != progress_manifest_ids:
        raise ValueError("RUN_EVIDENCE_COMPLETE checkpoint/run-progress manifest mismatch")
    expected_spec_ids = tuple(spec.run_spec_id for spec in execution_plan.run_specs)
    if tuple(item.run_spec_id for item in run_progress.completed_runs) != expected_spec_ids:
        raise ValueError("experiment assembly run-progress differs from ExecutionPlan order")
    if tuple(item.run_evidence_manifest_id for item in run_evidence) != progress_manifest_ids:
        raise ValueError("experiment assembly parsed evidence differs from committed run progress")

    arm_results, experiment, comparison, graph = assemble_us_a0_experiment_evidence(
        protocol=protocol,
        execution_plan=execution_plan,
        predecessor=predecessor,
        run_evidence=run_evidence,
    )
    assessment = assess_us_a0_agent_value_gate(
        policy=gate_policy,
        execution_plan=execution_plan,
        experiment=experiment,
        comparison=comparison,
        evidence_graph=graph,
    )
    manifest = USAgentValuePilotExperimentAssemblyManifest(
        execution_plan_id=execution_plan.plan_id,
        run_evidence_complete_checkpoint_id=run_checkpoint.checkpoint_id,
        run_progress_id=run_progress.progress_id,
        predecessor_binding_id=predecessor.binding_id,
        gate_policy_id=gate_policy.policy_id,
        arm_result_ids=tuple(result.result_id for result in arm_results),
        experiment_id=experiment.experiment_id,
        comparison_snapshot_id=comparison.snapshot_id,
        evidence_graph_id=graph.graph_id,
        gate_assessment_id=assessment.assessment_id,
    )
    checkpoint = advance_us_a0_pilot_orchestration_checkpoint(
        run_checkpoint,
        state=USAgentValuePilotOrchestrationState.EXPERIMENT_ASSEMBLED,
        experiment_evidence_graph_id=graph.graph_id,
    )
    return USAgentValuePilotExperimentArtifacts(
        arm_results=arm_results,
        experiment=experiment,
        comparison=comparison,
        evidence_graph=graph,
        assessment=assessment,
        assembly_manifest=manifest,
        checkpoint=checkpoint,
    )


def validate_us_a0_pilot_experiment_documents(
    artifacts: USAgentValuePilotExperimentArtifacts,
    *,
    arm_documents: Sequence[Mapping[str, object]],
    experiment_document: Mapping[str, object],
    comparison_document: Mapping[str, object],
    graph_document: Mapping[str, object],
    assessment_document: Mapping[str, object],
    manifest_document: Mapping[str, object],
    checkpoint_document: Mapping[str, object],
) -> None:
    expected_arm_documents = tuple(result.to_dict() for result in artifacts.arm_results)
    if tuple(dict(item) for item in arm_documents) != expected_arm_documents:
        raise ValueError("stored PILOT arm-result evidence differs from deterministic assembly")
    expected_pairs = (
        (experiment_document, artifacts.experiment.to_dict(), "experiment"),
        (comparison_document, artifacts.comparison.to_dict(), "comparison"),
        (graph_document, artifacts.evidence_graph.to_dict(), "evidence graph"),
        (assessment_document, artifacts.assessment.to_dict(), "Gate assessment"),
        (manifest_document, artifacts.assembly_manifest.to_dict(), "assembly manifest"),
        (checkpoint_document, artifacts.checkpoint.to_dict(), "EXPERIMENT_ASSEMBLED checkpoint"),
    )
    for actual, expected, label in expected_pairs:
        if dict(actual) != expected:
            raise ValueError(f"stored PILOT {label} differs from deterministic reconstruction")


def parse_us_a0_pilot_experiment_assembly_manifest(
    document: Mapping[str, object],
) -> USAgentValuePilotExperimentAssemblyManifest:
    raw_arm_ids = _sequence(document.get("arm_result_ids"), "assembly_manifest.arm_result_ids")
    if any(not isinstance(item, str) for item in raw_arm_ids):
        raise TypeError("assembly_manifest.arm_result_ids must contain strings")
    manifest = USAgentValuePilotExperimentAssemblyManifest(
        execution_plan_id=_text(
            document.get("execution_plan_id"), "assembly_manifest.execution_plan_id"
        ),
        run_evidence_complete_checkpoint_id=_text(
            document.get("run_evidence_complete_checkpoint_id"),
            "assembly_manifest.run_evidence_complete_checkpoint_id",
        ),
        run_progress_id=_text(document.get("run_progress_id"), "assembly_manifest.run_progress_id"),
        predecessor_binding_id=_text(
            document.get("predecessor_binding_id"), "assembly_manifest.predecessor_binding_id"
        ),
        gate_policy_id=_text(document.get("gate_policy_id"), "assembly_manifest.gate_policy_id"),
        arm_result_ids=tuple(str(item) for item in raw_arm_ids),
        experiment_id=_text(document.get("experiment_id"), "assembly_manifest.experiment_id"),
        comparison_snapshot_id=_text(
            document.get("comparison_snapshot_id"), "assembly_manifest.comparison_snapshot_id"
        ),
        evidence_graph_id=_text(
            document.get("evidence_graph_id"), "assembly_manifest.evidence_graph_id"
        ),
        gate_assessment_id=_text(
            document.get("gate_assessment_id"), "assembly_manifest.gate_assessment_id"
        ),
    )
    if dict(document) != manifest.to_dict():
        raise ValueError("US-A0 PILOT experiment assembly manifest content identity mismatch")
    return manifest


def validate_us_a0_pilot_gate_review_document(
    document: Mapping[str, object],
    *,
    assessment: USAgentValueGateAssessment,
) -> USAgentValueGateReview:
    nested_assessment = _mapping(document.get("assessment"), "gate_review.assessment")
    if dict(nested_assessment) != assessment.to_dict():
        raise ValueError("PILOT Gate review embeds a different deterministic assessment")
    attestations = _mapping(document.get("attestations"), "gate_review.attestations")
    required_attestations = {
        "thresholds_unchanged_after_result",
        "evidence_lineage_verified",
        "alpha_gate_is_separate",
        "project_stage_authority_is_separate",
    }
    if set(attestations) != required_attestations:
        raise ValueError("PILOT Gate review attestation set mismatch")
    reviewed_at = datetime.fromisoformat(_text(document.get("reviewed_at"), "gate_review.reviewed_at"))
    review = finalize_us_a0_agent_value_gate_review(
        assessment,
        reviewer_id=_text(document.get("reviewer_id"), "gate_review.reviewer_id"),
        reviewed_at=reviewed_at,
        review_notes=_text(document.get("review_notes"), "gate_review.review_notes"),
        decision=USAgentValueGateDecision(
            _text(document.get("decision"), "gate_review.decision")
        ),
        thresholds_unchanged_attested=_boolean(
            attestations.get("thresholds_unchanged_after_result"),
            "gate_review.attestations.thresholds_unchanged_after_result",
        ),
        evidence_lineage_attested=_boolean(
            attestations.get("evidence_lineage_verified"),
            "gate_review.attestations.evidence_lineage_verified",
        ),
        alpha_gate_separation_attested=_boolean(
            attestations.get("alpha_gate_is_separate"),
            "gate_review.attestations.alpha_gate_is_separate",
        ),
        stage_authority_separation_attested=_boolean(
            attestations.get("project_stage_authority_is_separate"),
            "gate_review.attestations.project_stage_authority_is_separate",
        ),
    )
    if dict(document) != review.to_dict():
        raise ValueError("US-A0 PILOT Gate review content identity mismatch")
    return review


def build_us_a0_pilot_gate_reviewed_checkpoint(
    *,
    experiment_checkpoint: USAgentValuePilotOrchestrationCheckpoint,
    assembly_manifest: USAgentValuePilotExperimentAssemblyManifest,
    review: USAgentValueGateReview,
) -> USAgentValuePilotOrchestrationCheckpoint:
    if experiment_checkpoint.state is not USAgentValuePilotOrchestrationState.EXPERIMENT_ASSEMBLED:
        raise ValueError("Gate review requires EXPERIMENT_ASSEMBLED checkpoint")
    if experiment_checkpoint.experiment_evidence_graph_id != assembly_manifest.evidence_graph_id:
        raise ValueError("Gate review checkpoint/assembly graph identity mismatch")
    if review.assessment.phase is not USAgentValuePhase.PILOT:
        raise ValueError("Gate-reviewed checkpoint v1 requires PILOT review")
    if review.assessment.evidence_graph_id != assembly_manifest.evidence_graph_id:
        raise ValueError("Gate review assessment/assembly graph identity mismatch")
    if review.assessment.assessment_id != assembly_manifest.gate_assessment_id:
        raise ValueError("Gate review assessment/assembly assessment identity mismatch")
    return advance_us_a0_pilot_orchestration_checkpoint(
        experiment_checkpoint,
        state=USAgentValuePilotOrchestrationState.GATE_REVIEWED,
        gate_review_id=review.review_id,
    )

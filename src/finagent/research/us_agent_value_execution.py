from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from finagent.research.us_agent_value_evaluation import (
    USAgentValueEvaluationBinding,
    USAgentValueFoldEvaluationReport,
    USAgentValueRunEvaluationReport,
    USAgentValueRunEvaluationStatus,
    validate_us_a0_preregistration_bundle,
)
from finagent.research.us_agent_value_experiment import (
    RunEvaluationLink,
    USAgentValuePredecessorBinding,
)
from finagent.research.us_agent_value_generation import (
    CandidateGenerationEvent,
    CandidateGenerationRun,
    CandidateGenerationRunSpec,
    CandidateGenerationUsage,
    CandidateValidationStatus,
    StructuredCandidateProposal,
    agent_run_spec,
    canonical_manual_run_spec,
    programmatic_run_spec,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValueCandidateSpec,
    USAgentValueExperimentProtocol,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_baseline_materialization import USBaselineMaterializationDiagnostics
from finagent.research.us_baselines import USBaselineFeatureKind


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


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name)


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be integer-like")
    result = int(value)
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field_name} must be integer-like")
    return result


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _datetime(value: object, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, field_name))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def _phase_from_preregistration(document: Mapping[str, object]) -> USAgentValuePhase:
    return USAgentValuePhase(_text(document.get("phase"), "preregistration.phase"))


@dataclass(frozen=True, slots=True)
class USAgentValueExecutionPlan:
    preregistration_bundle_id: str
    protocol_id: str
    vocabulary_id: str
    phase: USAgentValuePhase
    run_specs: tuple[CandidateGenerationRunSpec, ...]
    schema_version: str = "finagent.us-agent-value-execution-plan.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "preregistration_bundle_id",
            "protocol_id",
            "vocabulary_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)

        protocol = canonical_us_a0_experiment_protocol(self.phase)
        vocabulary = canonical_us_a0_primitive_vocabulary()
        if self.protocol_id != protocol.protocol_id:
            raise ValueError("execution plan phase/protocol identity mismatch")
        if self.vocabulary_id != vocabulary.vocabulary_id:
            raise ValueError("execution plan vocabulary identity mismatch")
        if not self.run_specs:
            raise ValueError("execution plan requires generation run specs")
        if any(item.protocol_id != self.protocol_id for item in self.run_specs):
            raise ValueError("execution plan run-spec/protocol identity mismatch")
        if any(item.phase is not self.phase for item in self.run_specs):
            raise ValueError("execution plan run-spec phase mismatch")
        if any(item.candidate_budget != protocol.candidate_budget_per_run for item in self.run_specs):
            raise ValueError("execution plan run-spec budget mismatch")

        spec_ids = tuple(item.run_spec_id for item in self.run_specs)
        if len(spec_ids) != len(set(spec_ids)):
            raise ValueError("execution plan run-spec identities must be unique")

        by_arm = {
            arm: tuple(item for item in self.run_specs if item.arm is arm)
            for arm in USAgentValueArm
        }
        manual = by_arm[USAgentValueArm.MANUAL]
        programmatic = by_arm[USAgentValueArm.PROGRAMMATIC]
        agent = by_arm[USAgentValueArm.AGENT]
        if len(manual) != 1 or manual[0] != canonical_manual_run_spec(protocol):
            raise ValueError("execution plan requires the exact canonical MANUAL run spec")
        if len(programmatic) != len(agent):
            raise ValueError("PROGRAMMATIC and AGENT must have equal independent-run counts")
        if len(programmatic) < protocol.minimum_runs(USAgentValueArm.PROGRAMMATIC):
            raise ValueError("execution plan does not satisfy PROGRAMMATIC run minimum")
        if len(agent) < protocol.minimum_runs(USAgentValueArm.AGENT):
            raise ValueError("execution plan does not satisfy AGENT run minimum")

        for arm, items in by_arm.items():
            ordinals = tuple(item.run_ordinal for item in items)
            if ordinals != tuple(range(1, len(items) + 1)):
                raise ValueError(f"{arm.value} execution-plan ordinals must be consecutive from one")
        seeds = tuple(item.random_seed for item in programmatic)
        if None in seeds or len(seeds) != len(set(seeds)):
            raise ValueError("execution plan PROGRAMMATIC seeds must be present and unique")

    @property
    def plan_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-execution-plan",
        )

    def run_spec(self, run_spec_id: str) -> CandidateGenerationRunSpec:
        match = next((item for item in self.run_specs if item.run_spec_id == run_spec_id), None)
        if match is None:
            raise ValueError("generation run spec is not authorized by the frozen execution plan")
        return match

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "preregistration_bundle_id": self.preregistration_bundle_id,
            "protocol_id": self.protocol_id,
            "vocabulary_id": self.vocabulary_id,
            "phase": self.phase.value,
            "run_spec_count": len(self.run_specs),
            "run_spec_ids": [item.run_spec_id for item in self.run_specs],
            "run_specs": [item.to_dict() for item in self.run_specs],
            "budget_scope": "exact_pre_generation_independent_run_plan",
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["plan_id"] = self.plan_id
        return payload


def build_us_a0_execution_plan(
    protocol: USAgentValueExperimentProtocol,
    *,
    preregistration_bundle_id: str,
    programmatic_seeds: tuple[int, ...],
    agent_provider_id: str,
    agent_model_id: str,
    agent_prompt_template_id: str,
    agent_generator_id: str = "us_a0_structured_agent_generator_v1",
) -> USAgentValueExecutionPlan:
    if not programmatic_seeds:
        raise ValueError("execution plan requires at least one PROGRAMMATIC seed")
    run_specs: list[CandidateGenerationRunSpec] = [canonical_manual_run_spec(protocol)]
    run_specs.extend(
        programmatic_run_spec(protocol, run_ordinal=index, random_seed=seed)
        for index, seed in enumerate(programmatic_seeds, start=1)
    )
    run_specs.extend(
        agent_run_spec(
            protocol,
            run_ordinal=index,
            provider_id=agent_provider_id,
            model_id=agent_model_id,
            prompt_template_id=agent_prompt_template_id,
            generator_id=agent_generator_id,
        )
        for index in range(1, len(programmatic_seeds) + 1)
    )
    return USAgentValueExecutionPlan(
        preregistration_bundle_id=preregistration_bundle_id,
        protocol_id=protocol.protocol_id,
        vocabulary_id=protocol.vocabulary_id,
        phase=protocol.phase,
        run_specs=tuple(run_specs),
    )


def _parse_run_spec(document: Mapping[str, object]) -> CandidateGenerationRunSpec:
    spec = CandidateGenerationRunSpec(
        protocol_id=_text(document.get("protocol_id"), "run_spec.protocol_id"),
        phase=USAgentValuePhase(_text(document.get("phase"), "run_spec.phase")),
        arm=USAgentValueArm(_text(document.get("arm"), "run_spec.arm")),
        run_ordinal=_integer(document.get("run_ordinal"), "run_spec.run_ordinal"),
        candidate_budget=_integer(document.get("candidate_budget"), "run_spec.candidate_budget"),
        generator_id=_text(document.get("generator_id"), "run_spec.generator_id"),
        random_seed=(
            None
            if document.get("random_seed") is None
            else _integer(document.get("random_seed"), "run_spec.random_seed")
        ),
        provider_id=_optional_text(document.get("provider_id"), "run_spec.provider_id"),
        model_id=_optional_text(document.get("model_id"), "run_spec.model_id"),
        prompt_template_id=_optional_text(
            document.get("prompt_template_id"),
            "run_spec.prompt_template_id",
        ),
    )
    if dict(document) != spec.to_dict():
        raise ValueError("generation run-spec content identity mismatch")
    return spec


def validate_us_a0_execution_plan(
    document: Mapping[str, object],
    preregistration_document: Mapping[str, object],
) -> tuple[USAgentValueExperimentProtocol, USAgentValueExecutionPlan]:
    phase = _phase_from_preregistration(preregistration_document)
    protocol = validate_us_a0_preregistration_bundle(preregistration_document, phase)
    run_specs = tuple(
        _parse_run_spec(_mapping(raw, f"execution_plan.run_specs[{index}]"))
        for index, raw in enumerate(
            _sequence(document.get("run_specs"), "execution_plan.run_specs")
        )
    )
    plan = USAgentValueExecutionPlan(
        preregistration_bundle_id=_text(
            document.get("preregistration_bundle_id"),
            "execution_plan.preregistration_bundle_id",
        ),
        protocol_id=_text(document.get("protocol_id"), "execution_plan.protocol_id"),
        vocabulary_id=_text(document.get("vocabulary_id"), "execution_plan.vocabulary_id"),
        phase=USAgentValuePhase(_text(document.get("phase"), "execution_plan.phase")),
        run_specs=run_specs,
    )
    if plan.preregistration_bundle_id != _text(
        preregistration_document.get("bundle_id"),
        "preregistration.bundle_id",
    ):
        raise ValueError("execution plan/preregistration bundle identity mismatch")
    if plan.protocol_id != protocol.protocol_id or plan.phase is not protocol.phase:
        raise ValueError("execution plan/preregistration protocol identity mismatch")
    if dict(document) != plan.to_dict():
        raise ValueError("US-A0 execution plan content identity mismatch")
    return protocol, plan


def _parse_usage(document: Mapping[str, object]) -> CandidateGenerationUsage:
    usage = CandidateGenerationUsage(
        llm_calls=_integer(document.get("llm_calls"), "usage.llm_calls"),
        input_tokens=_integer(document.get("input_tokens"), "usage.input_tokens"),
        output_tokens=_integer(document.get("output_tokens"), "usage.output_tokens"),
        latency_ms=_number(document.get("latency_ms"), "usage.latency_ms"),
        cost_usd=_number(document.get("cost_usd"), "usage.cost_usd"),
    )
    if dict(document) != usage.to_dict():
        raise ValueError("generation usage content mismatch")
    return usage


def _parse_candidate(document: Mapping[str, object]) -> USAgentValueCandidateSpec:
    vocabulary = canonical_us_a0_primitive_vocabulary()
    kind = USBaselineFeatureKind(_text(document.get("kind"), "candidate.kind"))
    candidate = vocabulary.candidate(
        kind,
        _integer(document.get("window_bars"), "candidate.window_bars"),
    )
    if dict(document) != candidate.to_dict():
        raise ValueError("candidate structural content identity mismatch")
    return candidate


def _parse_proposal(document: Mapping[str, object]) -> StructuredCandidateProposal:
    proposal = StructuredCandidateProposal(
        kind=_text(document.get("kind"), "proposal.kind"),
        window_bars=_integer(document.get("window_bars"), "proposal.window_bars"),
        hypothesis_summary=_text(
            document.get("hypothesis_summary"),
            "proposal.hypothesis_summary",
        ),
        generated_at=_datetime(document.get("generated_at"), "proposal.generated_at"),
        usage=_parse_usage(_mapping(document.get("usage"), "proposal.usage")),
        parent_candidate_id=_optional_text(
            document.get("parent_candidate_id"),
            "proposal.parent_candidate_id",
        ),
    )
    if dict(document) != proposal.to_dict():
        raise ValueError("structured proposal content identity mismatch")
    return proposal


def _parse_event(document: Mapping[str, object]) -> CandidateGenerationEvent:
    raw_candidate = document.get("candidate")
    candidate = (
        None
        if raw_candidate is None
        else _parse_candidate(_mapping(raw_candidate, "event.candidate"))
    )
    event = CandidateGenerationEvent(
        run_spec_id=_text(document.get("run_spec_id"), "event.run_spec_id"),
        arm=USAgentValueArm(_text(document.get("arm"), "event.arm")),
        slot_index=_integer(document.get("slot_index"), "event.slot_index"),
        attempt_index=_integer(document.get("attempt_index"), "event.attempt_index"),
        proposal=_parse_proposal(_mapping(document.get("proposal"), "event.proposal")),
        status=CandidateValidationStatus(_text(document.get("status"), "event.status")),
        candidate=candidate,
        validation_reason=_optional_text(
            document.get("validation_reason"),
            "event.validation_reason",
        ),
        duplicate_of_candidate_id=_optional_text(
            document.get("duplicate_of_candidate_id"),
            "event.duplicate_of_candidate_id",
        ),
    )
    if dict(document) != event.to_dict():
        raise ValueError("candidate generation event content identity mismatch")
    return event


def parse_candidate_generation_run(
    document: Mapping[str, object],
    execution_plan: USAgentValueExecutionPlan,
) -> CandidateGenerationRun:
    spec = _parse_run_spec(_mapping(document.get("spec"), "generation_run.spec"))
    authorized = execution_plan.run_spec(spec.run_spec_id)
    if authorized != spec:
        raise ValueError("generation run spec differs from execution-plan authorization")
    events = tuple(
        _parse_event(_mapping(raw, f"generation_run.events[{index}]"))
        for index, raw in enumerate(_sequence(document.get("events"), "generation_run.events"))
    )
    run = CandidateGenerationRun(spec=spec, events=events)
    if dict(document) != run.to_dict():
        raise ValueError("candidate generation run content identity mismatch")
    return run


@dataclass(frozen=True, slots=True)
class USAgentValueFoldMaterializationManifest:
    execution_plan_id: str
    preregistration_bundle_id: str
    generation_run_id: str
    evaluation_binding_id: str
    fold_execution_spec_id: str
    fold_ordinal: int
    input_plan_id: str
    input_materialization_id: str
    observation_artifact_id: str
    diagnostics: USBaselineMaterializationDiagnostics
    fold_evaluation_report_id: str
    engineering_asset_count: int
    schema_version: str = "finagent.us-agent-value-fold-materialization-manifest.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "execution_plan_id",
            "preregistration_bundle_id",
            "generation_run_id",
            "evaluation_binding_id",
            "fold_execution_spec_id",
            "input_plan_id",
            "input_materialization_id",
            "observation_artifact_id",
            "fold_evaluation_report_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.fold_ordinal < 1:
            raise ValueError("fold_ordinal must be positive")
        if not 20 <= self.engineering_asset_count <= 30:
            raise ValueError("A0 formal EngineeringUniverse size must be in 20..30")

    @property
    def technical_passed(self) -> bool:
        return self.diagnostics.passed

    @property
    def manifest_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-fold-materialization",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "execution_plan_id": self.execution_plan_id,
            "preregistration_bundle_id": self.preregistration_bundle_id,
            "generation_run_id": self.generation_run_id,
            "evaluation_binding_id": self.evaluation_binding_id,
            "fold_execution_spec_id": self.fold_execution_spec_id,
            "fold_ordinal": self.fold_ordinal,
            "input_plan_id": self.input_plan_id,
            "input_materialization_id": self.input_materialization_id,
            "observation_artifact_id": self.observation_artifact_id,
            "diagnostics": self.diagnostics.to_dict(),
            "fold_evaluation_report_id": self.fold_evaluation_report_id,
            "engineering_asset_count": self.engineering_asset_count,
            "technical_passed": self.technical_passed,
            "technical_blockers": list(self.diagnostics.blockers),
            "candidate_invalidity_is_not_a_technical_blocker": True,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["manifest_id"] = self.manifest_id
        return payload


@dataclass(frozen=True, slots=True)
class USAgentValueRunEvidenceManifest:
    execution_plan_id: str
    preregistration_bundle_id: str
    predecessor_binding_id: str
    generation_run_id: str
    generation_run_spec_id: str
    evaluation_binding_id: str
    arm: USAgentValueArm
    phase: USAgentValuePhase
    fold_manifests: tuple[USAgentValueFoldMaterializationManifest, ...]
    run_evaluation_report_id: str
    run_evaluation_link_id: str
    run_evaluation_status: USAgentValueRunEvaluationStatus
    technical_blockers: tuple[str, ...] = ()
    schema_version: str = "finagent.us-agent-value-run-evidence-manifest.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "execution_plan_id",
            "preregistration_bundle_id",
            "predecessor_binding_id",
            "generation_run_id",
            "generation_run_spec_id",
            "evaluation_binding_id",
            "run_evaluation_report_id",
            "run_evaluation_link_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        canonical = canonical_us_a0_experiment_protocol(self.phase)
        if self.run_evaluation_status is USAgentValueRunEvaluationStatus.NO_ACCEPTED_CANDIDATES:
            if self.fold_manifests:
                raise ValueError("zero-candidate run evidence cannot carry fold manifests")
        else:
            if len(self.fold_manifests) != 3:
                raise ValueError("evaluated A0 run evidence requires exactly three fold manifests")
            ordinals = tuple(item.fold_ordinal for item in self.fold_manifests)
            if ordinals != (1, 2, 3):
                raise ValueError("A0 run evidence fold manifest order must be 1,2,3")
            if len({item.manifest_id for item in self.fold_manifests}) != 3:
                raise ValueError("A0 run evidence fold manifest identities must be unique")
        if canonical.phase is not self.phase:  # pragma: no cover - enum/canonical invariant
            raise RuntimeError("unexpected A0 phase identity")

    @property
    def technical_passed(self) -> bool:
        return not self.technical_blockers and all(item.technical_passed for item in self.fold_manifests)

    @property
    def manifest_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-run-evidence",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "execution_plan_id": self.execution_plan_id,
            "preregistration_bundle_id": self.preregistration_bundle_id,
            "predecessor_binding_id": self.predecessor_binding_id,
            "generation_run_id": self.generation_run_id,
            "generation_run_spec_id": self.generation_run_spec_id,
            "evaluation_binding_id": self.evaluation_binding_id,
            "arm": self.arm.value,
            "phase": self.phase.value,
            "fold_manifest_ids": [item.manifest_id for item in self.fold_manifests],
            "fold_manifests": [item.to_dict() for item in self.fold_manifests],
            "run_evaluation_report_id": self.run_evaluation_report_id,
            "run_evaluation_link_id": self.run_evaluation_link_id,
            "run_evaluation_status": self.run_evaluation_status.value,
            "technical_passed": self.technical_passed,
            "technical_blockers": list(self.technical_blockers),
            "candidate_invalidity_is_research_result_not_system_blocker": True,
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["manifest_id"] = self.manifest_id
        return payload


def build_us_a0_run_evidence_manifest(
    *,
    execution_plan: USAgentValueExecutionPlan,
    predecessor: USAgentValuePredecessorBinding,
    generation_run: CandidateGenerationRun,
    evaluation_binding: USAgentValueEvaluationBinding,
    fold_manifests: tuple[USAgentValueFoldMaterializationManifest, ...],
    run_evaluation: USAgentValueRunEvaluationReport,
    evaluation_link: RunEvaluationLink,
) -> USAgentValueRunEvidenceManifest:
    if generation_run.spec.run_spec_id != evaluation_binding.generation_run_spec_id:
        raise ValueError("run evidence generation/evaluation binding mismatch")
    if run_evaluation.generation_run_id != generation_run.run_id:
        raise ValueError("run evidence evaluation/generation identity mismatch")
    if evaluation_link.generation_run_id != generation_run.run_id:
        raise ValueError("run evidence link/generation identity mismatch")
    if evaluation_link.authoritative_evidence_id != run_evaluation.report_id:
        raise ValueError("run evidence link does not bind the run evaluation report")
    technical_blockers = tuple(
        f"fold:{item.fold_ordinal}:{blocker}"
        for item in fold_manifests
        for blocker in item.diagnostics.blockers
    )
    return USAgentValueRunEvidenceManifest(
        execution_plan_id=execution_plan.plan_id,
        preregistration_bundle_id=execution_plan.preregistration_bundle_id,
        predecessor_binding_id=predecessor.binding_id,
        generation_run_id=generation_run.run_id,
        generation_run_spec_id=generation_run.spec.run_spec_id,
        evaluation_binding_id=evaluation_binding.binding_id,
        arm=generation_run.spec.arm,
        phase=generation_run.spec.phase,
        fold_manifests=fold_manifests,
        run_evaluation_report_id=run_evaluation.report_id,
        run_evaluation_link_id=evaluation_link.link_id,
        run_evaluation_status=run_evaluation.status,
        technical_blockers=technical_blockers,
    )

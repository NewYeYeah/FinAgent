from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from finagent.research.us_agent_value_authority import require_us_a0_stage_authority
from finagent.research.us_agent_value_execution import (
    USAgentValueExecutionPlan,
    parse_candidate_generation_run,
    validate_us_a0_execution_plan,
)
from finagent.research.us_agent_value_generation import (
    CandidateGenerationRun,
    build_candidate_generation_run,
    deterministic_programmatic_proposal_slots,
    manual_proposal_slots,
)
from finagent.research.us_agent_value_gate import (
    USAgentValueGatePolicy,
    validate_us_a0_agent_value_gate_policy,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValueExperimentProtocol,
    USAgentValuePhase,
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


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


@dataclass(frozen=True, slots=True)
class USAgentValuePilotLaunchBundle:
    preregistration_bundle_id: str
    protocol_id: str
    vocabulary_id: str
    execution_plan_id: str
    gate_policy_id: str
    control_generated_at: datetime
    manual_generation_run_id: str
    programmatic_generation_run_ids: tuple[str, ...]
    agent_run_spec_ids: tuple[str, ...]
    expected_run_spec_ids: tuple[str, ...]
    agent_provider_id: str
    agent_model_id: str
    agent_prompt_template_id: str
    phase: USAgentValuePhase = USAgentValuePhase.PILOT
    schema_version: str = "finagent.us-agent-value-pilot-launch-bundle.v1"

    def __post_init__(self) -> None:
        if self.phase is not USAgentValuePhase.PILOT:
            raise ValueError("US-A0 launch bundle v1 is PILOT-only")
        for field_name in (
            "preregistration_bundle_id",
            "protocol_id",
            "vocabulary_id",
            "execution_plan_id",
            "gate_policy_id",
            "manual_generation_run_id",
            "agent_provider_id",
            "agent_model_id",
            "agent_prompt_template_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        object.__setattr__(
            self,
            "control_generated_at",
            _aware_utc(self.control_generated_at, "control_generated_at"),
        )
        if len(self.programmatic_generation_run_ids) != 1:
            raise ValueError("PILOT launch bundle requires exactly one PROGRAMMATIC control run")
        if len(self.agent_run_spec_ids) != 1:
            raise ValueError("PILOT launch bundle requires exactly one AGENT run spec")
        if len(self.expected_run_spec_ids) != 3 or len(set(self.expected_run_spec_ids)) != 3:
            raise ValueError("PILOT launch bundle requires exactly three unique run-spec identities")
        if not all(value.strip() for value in self.programmatic_generation_run_ids):
            raise ValueError("PROGRAMMATIC control run identities must be non-empty")
        if not all(value.strip() for value in self.agent_run_spec_ids):
            raise ValueError("AGENT run-spec identities must be non-empty")

    @property
    def launch_bundle_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-pilot-launch-bundle",
        )

    @property
    def frozen_control_run_ids(self) -> tuple[str, ...]:
        return (self.manual_generation_run_id, *self.programmatic_generation_run_ids)

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "phase": self.phase.value,
            "preregistration_bundle_id": self.preregistration_bundle_id,
            "protocol_id": self.protocol_id,
            "vocabulary_id": self.vocabulary_id,
            "execution_plan_id": self.execution_plan_id,
            "gate_policy_id": self.gate_policy_id,
            "control_generated_at": self.control_generated_at.isoformat(),
            "manual_generation_run_id": self.manual_generation_run_id,
            "programmatic_generation_run_ids": list(self.programmatic_generation_run_ids),
            "agent_run_spec_ids": list(self.agent_run_spec_ids),
            "expected_run_spec_ids": list(self.expected_run_spec_ids),
            "agent_provider_id": self.agent_provider_id,
            "agent_model_id": self.agent_model_id,
            "agent_prompt_template_id": self.agent_prompt_template_id,
            "control_generation_scope": "deterministic_pre_result_control_evidence_only",
            "agent_generation_scope": "run_spec_frozen_real_run_id_pending_external_execution",
            "provider_smoke_scope": "engineering_diagnostic_separate_from_research_authority",
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["launch_bundle_id"] = self.launch_bundle_id
        return payload


@dataclass(frozen=True, slots=True)
class USAgentValuePilotLaunchArtifacts:
    protocol: USAgentValueExperimentProtocol
    execution_plan: USAgentValueExecutionPlan
    gate_policy: USAgentValueGatePolicy
    launch_bundle: USAgentValuePilotLaunchBundle
    manual_run: CandidateGenerationRun
    programmatic_runs: tuple[CandidateGenerationRun, ...]

    @property
    def control_runs(self) -> tuple[CandidateGenerationRun, ...]:
        return (self.manual_run, *self.programmatic_runs)


def build_us_a0_pilot_launch_artifacts(
    *,
    preregistration_document: Mapping[str, object],
    execution_plan_document: Mapping[str, object],
    gate_policy_document: Mapping[str, object],
    control_generated_at: datetime,
) -> USAgentValuePilotLaunchArtifacts:
    protocol, execution_plan = validate_us_a0_execution_plan(
        execution_plan_document,
        preregistration_document,
    )
    if protocol.phase is not USAgentValuePhase.PILOT:
        raise ValueError("PILOT launch artifacts require a PILOT preregistration/ExecutionPlan")
    gate_policy = validate_us_a0_agent_value_gate_policy(
        dict(gate_policy_document),
        USAgentValuePhase.PILOT,
    )
    if gate_policy.protocol_id != protocol.protocol_id:
        raise ValueError("PILOT launch Gate policy/protocol identity mismatch")

    generated_at = _aware_utc(control_generated_at, "control_generated_at")
    manual_specs = tuple(
        item for item in execution_plan.run_specs if item.arm is USAgentValueArm.MANUAL
    )
    programmatic_specs = tuple(
        item for item in execution_plan.run_specs if item.arm is USAgentValueArm.PROGRAMMATIC
    )
    agent_specs = tuple(
        item for item in execution_plan.run_specs if item.arm is USAgentValueArm.AGENT
    )
    if len(manual_specs) != 1 or len(programmatic_specs) != 1 or len(agent_specs) != 1:
        raise ValueError("PILOT launch requires exact 1/1/1 MANUAL/PROGRAMMATIC/AGENT run specs")

    manual_run = build_candidate_generation_run(
        protocol,
        manual_specs[0],
        manual_proposal_slots(protocol, generated_at=generated_at),
    )
    programmatic_runs: list[CandidateGenerationRun] = []
    for spec in programmatic_specs:
        if spec.random_seed is None:  # pragma: no cover - ExecutionPlan invariant
            raise RuntimeError("PROGRAMMATIC launch run spec is missing its frozen seed")
        programmatic_runs.append(
            build_candidate_generation_run(
                protocol,
                spec,
                deterministic_programmatic_proposal_slots(
                    protocol,
                    random_seed=spec.random_seed,
                    generated_at=generated_at,
                ),
            )
        )

    agent_spec = agent_specs[0]
    if agent_spec.provider_id is None or agent_spec.model_id is None or agent_spec.prompt_template_id is None:
        raise RuntimeError("AGENT launch run spec is missing frozen provider identity")
    launch_bundle = USAgentValuePilotLaunchBundle(
        preregistration_bundle_id=execution_plan.preregistration_bundle_id,
        protocol_id=protocol.protocol_id,
        vocabulary_id=protocol.vocabulary_id,
        execution_plan_id=execution_plan.plan_id,
        gate_policy_id=gate_policy.policy_id,
        control_generated_at=generated_at,
        manual_generation_run_id=manual_run.run_id,
        programmatic_generation_run_ids=tuple(run.run_id for run in programmatic_runs),
        agent_run_spec_ids=tuple(spec.run_spec_id for spec in agent_specs),
        expected_run_spec_ids=tuple(spec.run_spec_id for spec in execution_plan.run_specs),
        agent_provider_id=agent_spec.provider_id,
        agent_model_id=agent_spec.model_id,
        agent_prompt_template_id=agent_spec.prompt_template_id,
    )
    return USAgentValuePilotLaunchArtifacts(
        protocol=protocol,
        execution_plan=execution_plan,
        gate_policy=gate_policy,
        launch_bundle=launch_bundle,
        manual_run=manual_run,
        programmatic_runs=tuple(programmatic_runs),
    )


def validate_us_a0_pilot_launch_bundle(
    document: Mapping[str, object],
    *,
    preregistration_document: Mapping[str, object],
    execution_plan_document: Mapping[str, object],
    gate_policy_document: Mapping[str, object],
) -> USAgentValuePilotLaunchArtifacts:
    generated_at = datetime.fromisoformat(
        _text(document.get("control_generated_at"), "launch.control_generated_at")
    )
    artifacts = build_us_a0_pilot_launch_artifacts(
        preregistration_document=preregistration_document,
        execution_plan_document=execution_plan_document,
        gate_policy_document=gate_policy_document,
        control_generated_at=generated_at,
    )
    if dict(document) != artifacts.launch_bundle.to_dict():
        raise ValueError("US-A0 PILOT launch bundle content identity mismatch")
    return artifacts


def validate_us_a0_pilot_control_documents(
    artifacts: USAgentValuePilotLaunchArtifacts,
    control_documents: tuple[Mapping[str, object], ...],
) -> tuple[CandidateGenerationRun, ...]:
    expected = artifacts.control_runs
    if len(control_documents) != len(expected):
        raise ValueError("PILOT launch requires the exact frozen MANUAL/PROGRAMMATIC control documents")
    parsed = tuple(
        parse_candidate_generation_run(document, artifacts.execution_plan)
        for document in control_documents
    )
    if tuple(run.run_id for run in parsed) != tuple(run.run_id for run in expected):
        raise ValueError("PILOT control generation-run identities differ from the frozen launch bundle")
    if tuple(run.spec.arm for run in parsed) != tuple(run.spec.arm for run in expected):
        raise ValueError("PILOT control generation-run arm/order mismatch")
    return parsed


@dataclass(frozen=True, slots=True)
class USAgentValuePilotLaunchReadiness:
    launch_bundle_id: str
    execution_plan_id: str
    current_stage: str
    ready_for_external_agent_generation: bool
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-agent-value-pilot-launch-readiness.v1"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "launch_bundle_id": self.launch_bundle_id,
            "execution_plan_id": self.execution_plan_id,
            "current_stage": self.current_stage,
            "ready_for_external_agent_generation": self.ready_for_external_agent_generation,
            "blockers": list(self.blockers),
            "research_authority": False,
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }


def assess_us_a0_pilot_launch_readiness(
    status_document: Mapping[str, object],
    launch_bundle: USAgentValuePilotLaunchBundle,
) -> USAgentValuePilotLaunchReadiness:
    current_stage = str(status_document.get("current_stage", "")).strip()
    blockers: list[str] = []
    try:
        require_us_a0_stage_authority(status_document)
    except (TypeError, ValueError):
        blockers.append("us_a0_stage_authority_not_ready")
    return USAgentValuePilotLaunchReadiness(
        launch_bundle_id=launch_bundle.launch_bundle_id,
        execution_plan_id=launch_bundle.execution_plan_id,
        current_stage=current_stage,
        ready_for_external_agent_generation=not blockers,
        blockers=tuple(blockers),
    )

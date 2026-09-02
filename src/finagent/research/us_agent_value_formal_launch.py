from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

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
from finagent.research.us_agent_value_gate_authority import (
    require_us_a0_pilot_formal_progression_authority,
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


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class USAgentValueFormalLaunchBundle:
    preregistration_bundle_id: str
    protocol_id: str
    vocabulary_id: str
    execution_plan_id: str
    gate_policy_id: str
    pilot_gate_review_id: str
    control_generated_at: datetime
    manual_generation_run_id: str
    programmatic_generation_run_ids: tuple[str, ...]
    agent_run_spec_ids: tuple[str, ...]
    expected_run_spec_ids: tuple[str, ...]
    agent_provider_id: str
    agent_model_id: str
    agent_prompt_template_id: str
    phase: USAgentValuePhase = USAgentValuePhase.FORMAL
    schema_version: str = "finagent.us-agent-value-formal-launch-bundle.v1"

    def __post_init__(self) -> None:
        if self.phase is not USAgentValuePhase.FORMAL:
            raise ValueError("US-A0 FORMAL launch bundle requires FORMAL phase")
        for field_name in (
            "preregistration_bundle_id",
            "protocol_id",
            "vocabulary_id",
            "execution_plan_id",
            "gate_policy_id",
            "pilot_gate_review_id",
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
        if len(self.programmatic_generation_run_ids) != 3:
            raise ValueError("FORMAL launch requires exactly three PROGRAMMATIC control runs")
        if len(self.agent_run_spec_ids) != 3:
            raise ValueError("FORMAL launch requires exactly three AGENT run specs")
        if len(self.expected_run_spec_ids) != 7 or len(set(self.expected_run_spec_ids)) != 7:
            raise ValueError("FORMAL launch requires exactly seven unique run-spec identities")
        for values, label in (
            (self.programmatic_generation_run_ids, "PROGRAMMATIC generation-run"),
            (self.agent_run_spec_ids, "AGENT run-spec"),
        ):
            if any(not value.strip() for value in values) or len(values) != len(set(values)):
                raise ValueError(f"FORMAL {label} identities must be unique and non-empty")

    @property
    def launch_bundle_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-formal-launch-bundle",
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
            "pilot_gate_review_id": self.pilot_gate_review_id,
            "control_generated_at": self.control_generated_at.isoformat(),
            "manual_generation_run_id": self.manual_generation_run_id,
            "programmatic_generation_run_ids": list(self.programmatic_generation_run_ids),
            "agent_run_spec_ids": list(self.agent_run_spec_ids),
            "expected_run_spec_ids": list(self.expected_run_spec_ids),
            "agent_provider_id": self.agent_provider_id,
            "agent_model_id": self.agent_model_id,
            "agent_prompt_template_id": self.agent_prompt_template_id,
            "control_generation_scope": "post_pilot_review_pre_formal_result_control_evidence_only",
            "agent_generation_scope": "three_independent_run_specs_frozen_real_run_ids_pending",
            "agent_run_isolation": "no_cross_run_candidate_or_result_feedback",
            "status_authority": False,
            "stage_exit_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["launch_bundle_id"] = self.launch_bundle_id
        return payload


@dataclass(frozen=True, slots=True)
class USAgentValueFormalLaunchArtifacts:
    protocol: USAgentValueExperimentProtocol
    execution_plan: USAgentValueExecutionPlan
    gate_policy: USAgentValueGatePolicy
    pilot_gate_review_id: str
    launch_bundle: USAgentValueFormalLaunchBundle
    manual_run: CandidateGenerationRun
    programmatic_runs: tuple[CandidateGenerationRun, ...]

    @property
    def control_runs(self) -> tuple[CandidateGenerationRun, ...]:
        return (self.manual_run, *self.programmatic_runs)


def build_us_a0_formal_launch_artifacts(
    *,
    preregistration_document: Mapping[str, object],
    execution_plan_document: Mapping[str, object],
    gate_policy_document: Mapping[str, object],
    status_document: Mapping[str, object],
    pilot_gate_review_document: Mapping[str, object],
    control_generated_at: datetime,
) -> USAgentValueFormalLaunchArtifacts:
    protocol, execution_plan = validate_us_a0_execution_plan(
        execution_plan_document,
        preregistration_document,
    )
    if protocol.phase is not USAgentValuePhase.FORMAL:
        raise ValueError("FORMAL launch requires a FORMAL preregistration/ExecutionPlan")
    gate_policy = validate_us_a0_agent_value_gate_policy(
        dict(gate_policy_document),
        USAgentValuePhase.FORMAL,
    )
    if gate_policy.protocol_id != protocol.protocol_id:
        raise ValueError("FORMAL launch Gate policy/protocol identity mismatch")
    pilot_review_id = require_us_a0_pilot_formal_progression_authority(
        status_document,
        pilot_gate_review_document,
    )

    manual_specs = tuple(
        item for item in execution_plan.run_specs if item.arm is USAgentValueArm.MANUAL
    )
    programmatic_specs = tuple(
        item for item in execution_plan.run_specs if item.arm is USAgentValueArm.PROGRAMMATIC
    )
    agent_specs = tuple(
        item for item in execution_plan.run_specs if item.arm is USAgentValueArm.AGENT
    )
    if len(manual_specs) != 1 or len(programmatic_specs) != 3 or len(agent_specs) != 3:
        raise ValueError("FORMAL launch requires exact 1/3/3 MANUAL/PROGRAMMATIC/AGENT run specs")

    generated_at = _aware_utc(control_generated_at, "control_generated_at")
    manual_run = build_candidate_generation_run(
        protocol,
        manual_specs[0],
        manual_proposal_slots(protocol, generated_at=generated_at),
    )
    programmatic_runs: list[CandidateGenerationRun] = []
    for spec in programmatic_specs:
        if spec.random_seed is None:  # pragma: no cover - ExecutionPlan invariant
            raise RuntimeError("FORMAL PROGRAMMATIC run spec is missing its frozen seed")
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

    provider_ids = {spec.provider_id for spec in agent_specs}
    model_ids = {spec.model_id for spec in agent_specs}
    prompt_ids = {spec.prompt_template_id for spec in agent_specs}
    if None in provider_ids or None in model_ids or None in prompt_ids:
        raise RuntimeError("FORMAL AGENT run specs are missing frozen provider identity")
    if len(provider_ids) != 1 or len(model_ids) != 1 or len(prompt_ids) != 1:
        raise ValueError("FORMAL AGENT runs must share provider/model/prompt identity")
    provider_id = next(iter(provider_ids))
    model_id = next(iter(model_ids))
    prompt_id = next(iter(prompt_ids))
    assert provider_id is not None and model_id is not None and prompt_id is not None

    launch = USAgentValueFormalLaunchBundle(
        preregistration_bundle_id=execution_plan.preregistration_bundle_id,
        protocol_id=protocol.protocol_id,
        vocabulary_id=protocol.vocabulary_id,
        execution_plan_id=execution_plan.plan_id,
        gate_policy_id=gate_policy.policy_id,
        pilot_gate_review_id=pilot_review_id,
        control_generated_at=generated_at,
        manual_generation_run_id=manual_run.run_id,
        programmatic_generation_run_ids=tuple(run.run_id for run in programmatic_runs),
        agent_run_spec_ids=tuple(spec.run_spec_id for spec in agent_specs),
        expected_run_spec_ids=tuple(spec.run_spec_id for spec in execution_plan.run_specs),
        agent_provider_id=provider_id,
        agent_model_id=model_id,
        agent_prompt_template_id=prompt_id,
    )
    return USAgentValueFormalLaunchArtifacts(
        protocol=protocol,
        execution_plan=execution_plan,
        gate_policy=gate_policy,
        pilot_gate_review_id=pilot_review_id,
        launch_bundle=launch,
        manual_run=manual_run,
        programmatic_runs=tuple(programmatic_runs),
    )


def validate_us_a0_formal_launch_bundle(
    document: Mapping[str, object],
    *,
    preregistration_document: Mapping[str, object],
    execution_plan_document: Mapping[str, object],
    gate_policy_document: Mapping[str, object],
    status_document: Mapping[str, object],
    pilot_gate_review_document: Mapping[str, object],
) -> USAgentValueFormalLaunchArtifacts:
    generated_at = datetime.fromisoformat(
        _text(document.get("control_generated_at"), "formal_launch.control_generated_at")
    )
    artifacts = build_us_a0_formal_launch_artifacts(
        preregistration_document=preregistration_document,
        execution_plan_document=execution_plan_document,
        gate_policy_document=gate_policy_document,
        status_document=status_document,
        pilot_gate_review_document=pilot_gate_review_document,
        control_generated_at=generated_at,
    )
    if dict(document) != artifacts.launch_bundle.to_dict():
        raise ValueError("US-A0 FORMAL launch bundle content identity mismatch")
    return artifacts


def validate_us_a0_formal_control_documents(
    artifacts: USAgentValueFormalLaunchArtifacts,
    control_documents: tuple[Mapping[str, object], ...],
) -> tuple[CandidateGenerationRun, ...]:
    expected = artifacts.control_runs
    if len(control_documents) != len(expected):
        raise ValueError("FORMAL launch requires exact MANUAL plus three PROGRAMMATIC controls")
    parsed = tuple(
        parse_candidate_generation_run(document, artifacts.execution_plan)
        for document in control_documents
    )
    if tuple(run.run_id for run in parsed) != tuple(run.run_id for run in expected):
        raise ValueError("FORMAL control generation-run identities differ from frozen launch bundle")
    if tuple(run.spec for run in parsed) != tuple(run.spec for run in expected):
        raise ValueError("FORMAL control generation-run spec/order mismatch")
    return parsed

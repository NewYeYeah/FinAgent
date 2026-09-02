from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from finagent.research.us_agent_value_execution import (
    USAgentValueExecutionPlan,
    parse_candidate_generation_run,
    validate_us_a0_execution_plan,
)
from finagent.research.us_agent_value_gate import USAgentValueGateDecision
from finagent.research.us_agent_value_generation import CandidateGenerationRun
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValueCandidateSpec,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_baselines import USBaselineFeatureKind
from finagent.research.us_r1_authority import USR1StageAuthority, require_us_r1_stage_authority
from finagent.research.us_r1_protocol import (
    USR1AgentScope,
    USR1CandidateDenominator,
    USR1CandidateProvenance,
    canonical_us_r1_research_protocol,
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


def _rehash_document(
    document: Mapping[str, object],
    *,
    id_field: str,
    prefix: str,
    field_name: str,
) -> str:
    claimed = _text(document.get(id_field), f"{field_name}.{id_field}")
    payload = dict(document)
    del payload[id_field]
    if claimed != _canonical_hash(payload, prefix=prefix):
        raise ValueError(f"{field_name} content identity mismatch")
    return claimed


def _parse_candidate(document: Mapping[str, object]) -> USAgentValueCandidateSpec:
    vocabulary = canonical_us_a0_primitive_vocabulary()
    kind = USBaselineFeatureKind(_text(document.get("kind"), "candidate.kind"))
    candidate = vocabulary.candidate(
        kind,
        _integer(document.get("window_bars"), "candidate.window_bars"),
    )
    if dict(document) != candidate.to_dict():
        raise ValueError("US-R1 candidate structural content identity mismatch")
    return candidate


def parse_us_r1_candidate_denominator(
    document: Mapping[str, object],
) -> USR1CandidateDenominator:
    raw_candidates = _sequence(document.get("candidates"), "denominator.candidates")
    candidates: list[USR1CandidateProvenance] = []
    for index, raw in enumerate(raw_candidates):
        item = _mapping(raw, f"denominator.candidates[{index}]")
        candidate = _parse_candidate(
            _mapping(item.get("candidate"), f"denominator.candidates[{index}].candidate")
        )
        if _text(item.get("candidate_id"), "candidate_id") != candidate.candidate_id:
            raise ValueError("US-R1 candidate provenance candidate_id mismatch")
        source_arms = tuple(
            USAgentValueArm(_text(value, "source_arms[]"))
            for value in _sequence(item.get("source_arms"), "source_arms")
        )
        source_run_ids = tuple(
            _text(value, "source_run_ids[]")
            for value in _sequence(item.get("source_run_ids"), "source_run_ids")
        )
        provenance = USR1CandidateProvenance(
            candidate=candidate,
            source_arms=source_arms,
            source_run_ids=source_run_ids,
        )
        if dict(item) != provenance.to_dict():
            raise ValueError("US-R1 candidate provenance content identity mismatch")
        candidates.append(provenance)
    denominator = USR1CandidateDenominator(
        protocol_id=_text(document.get("protocol_id"), "denominator.protocol_id"),
        a0_phase=USAgentValuePhase(_text(document.get("a0_phase"), "denominator.a0_phase")),
        a0_experiment_id=_text(
            document.get("a0_experiment_id"), "denominator.a0_experiment_id"
        ),
        a0_gate_review_id=_text(
            document.get("a0_gate_review_id"), "denominator.a0_gate_review_id"
        ),
        a0_gate_decision=USAgentValueGateDecision(
            _text(document.get("a0_gate_decision"), "denominator.a0_gate_decision")
        ),
        agent_scope=USR1AgentScope(_text(document.get("agent_scope"), "denominator.agent_scope")),
        candidates=tuple(candidates),
    )
    if dict(document) != denominator.to_dict():
        raise ValueError("US-R1 candidate denominator content identity mismatch")
    return denominator


def validate_terminal_a0_review_document(
    document: Mapping[str, object],
    *,
    authority: USR1StageAuthority,
) -> tuple[str, USAgentValuePhase, USAgentValueGateDecision, str]:
    if _text(document.get("schema_version"), "gate_review.schema_version") != (
        "finagent.us-agent-value-gate-review.v1"
    ):
        raise ValueError("US-R1 requires A0 Gate review schema v1")
    review_id = _rehash_document(
        document,
        id_field="review_id",
        prefix="us-agent-value-gate-review",
        field_name="gate_review",
    )
    if review_id != authority.a0_terminal_gate_review_id:
        raise ValueError("A0 Gate review identity does not match US-R1 stage authority")
    phase = USAgentValuePhase(_text(document.get("phase"), "gate_review.phase"))
    decision = USAgentValueGateDecision(_text(document.get("decision"), "gate_review.decision"))
    assessment = _mapping(document.get("assessment"), "gate_review.assessment")
    assessment_id = _rehash_document(
        assessment,
        id_field="assessment_id",
        prefix="us-agent-value-gate-assessment",
        field_name="gate_review.assessment",
    )
    if _text(document.get("assessment_id"), "gate_review.assessment_id") != assessment_id:
        raise ValueError("A0 Gate review assessment identity mismatch")
    experiment_id = _text(assessment.get("experiment_id"), "gate_review.assessment.experiment_id")
    evidence_graph_id = _text(
        assessment.get("evidence_graph_id"), "gate_review.assessment.evidence_graph_id"
    )
    if experiment_id != authority.a0_experiment_id:
        raise ValueError("A0 experiment identity does not match US-R1 stage authority")
    if evidence_graph_id != authority.a0_evidence_graph_id:
        raise ValueError("A0 evidence graph identity does not match US-R1 stage authority")
    if _text(assessment.get("phase"), "gate_review.assessment.phase") != phase.value:
        raise ValueError("A0 Gate review assessment phase mismatch")
    assessment_decision = USAgentValueGateDecision(
        _text(assessment.get("decision"), "gate_review.assessment.decision")
    )
    if decision not in {assessment_decision, USAgentValueGateDecision.INCONCLUSIVE}:
        raise ValueError("A0 Gate review may only accept or conservatively downgrade assessment")
    if assessment_decision is USAgentValueGateDecision.INCONCLUSIVE and decision is not assessment_decision:
        raise ValueError("A0 INCONCLUSIVE assessment cannot be upgraded for US-R1 handoff")
    if phase is USAgentValuePhase.PILOT:
        if decision not in {
            USAgentValueGateDecision.PILOT_DO_NOT_PROCEED_TO_FORMAL,
            USAgentValueGateDecision.INCONCLUSIVE,
        }:
            raise ValueError("US-R1 requires a terminal PILOT review or completed FORMAL review")
        if _boolean(
            document.get("agent_value_gate_authority"),
            "gate_review.agent_value_gate_authority",
        ):
            raise ValueError("PILOT review cannot claim final Agent Value Gate authority")
    else:
        if decision not in {
            USAgentValueGateDecision.FORMAL_INCREMENTAL_VALUE_SUPPORTED,
            USAgentValueGateDecision.FORMAL_NO_INCREMENTAL_VALUE,
            USAgentValueGateDecision.INCONCLUSIVE,
        }:
            raise ValueError("US-R1 FORMAL predecessor decision is not terminal")
        if not _boolean(
            document.get("agent_value_gate_authority"),
            "gate_review.agent_value_gate_authority",
        ):
            raise ValueError("completed FORMAL review must claim Agent Value Gate authority")
    attestations = _mapping(document.get("attestations"), "gate_review.attestations")
    required = {
        "thresholds_unchanged_after_result",
        "evidence_lineage_verified",
        "alpha_gate_is_separate",
        "project_stage_authority_is_separate",
    }
    if set(attestations) != required or any(
        _boolean(attestations.get(key), f"gate_review.attestations.{key}") is not True
        for key in required
    ):
        raise ValueError("US-R1 requires the exact fully-attested A0 Gate review")
    for field_name in ("status_authority", "stage_exit_authority", "alpha_authority"):
        if _boolean(document.get(field_name), f"gate_review.{field_name}") is not False:
            raise ValueError(f"A0 Gate review must keep {field_name}=false")
    return review_id, phase, decision, experiment_id


def _validate_a0_experiment_document(
    document: Mapping[str, object],
    *,
    execution_plan: USAgentValueExecutionPlan,
    authority: USR1StageAuthority,
) -> tuple[
    USAgentValuePhase,
    tuple[tuple[USAgentValueArm, tuple[str, ...], tuple[str, ...]], ...],
]:
    if _text(document.get("schema_version"), "experiment.schema_version") != (
        "finagent.agent-value-experiment.v1"
    ):
        raise ValueError("US-R1 requires A0 AgentValueExperiment schema v1")
    experiment_id = _rehash_document(
        document,
        id_field="experiment_id",
        prefix="us-agent-value-experiment",
        field_name="experiment",
    )
    if experiment_id != authority.a0_experiment_id:
        raise ValueError("A0 experiment identity does not match US-R1 stage authority")
    protocol_document = _mapping(document.get("protocol"), "experiment.protocol")
    phase = USAgentValuePhase(_text(protocol_document.get("phase"), "experiment.protocol.phase"))
    protocol = canonical_us_a0_experiment_protocol(phase)
    if dict(protocol_document) != protocol.to_dict():
        raise ValueError("A0 experiment protocol differs from canonical preregistration")
    if execution_plan.protocol_id != protocol.protocol_id or execution_plan.phase is not phase:
        raise ValueError("A0 experiment/execution-plan protocol mismatch")
    raw_arm_results = _sequence(document.get("arm_results"), "experiment.arm_results")
    arm_result_ids = tuple(
        _text(item, "experiment.arm_result_ids[]")
        for item in _sequence(document.get("arm_result_ids"), "experiment.arm_result_ids")
    )
    if len(raw_arm_results) != 3 or len(arm_result_ids) != 3:
        raise ValueError("A0 experiment must contain exactly three search arms")
    parsed: list[tuple[USAgentValueArm, tuple[str, ...], tuple[str, ...]]] = []
    for index, raw in enumerate(raw_arm_results):
        arm_document = _mapping(raw, f"experiment.arm_results[{index}]")
        result_id = _rehash_document(
            arm_document,
            id_field="result_id",
            prefix="us-agent-value-search-arm-result",
            field_name=f"experiment.arm_results[{index}]",
        )
        if result_id != arm_result_ids[index]:
            raise ValueError("A0 experiment arm-result identity/order mismatch")
        arm = USAgentValueArm(_text(arm_document.get("arm"), "arm_result.arm"))
        if arm is not protocol.arms[index]:
            raise ValueError("A0 experiment arm order differs from canonical protocol")
        if _text(arm_document.get("phase"), "arm_result.phase") != phase.value:
            raise ValueError("A0 experiment arm phase mismatch")
        if _text(arm_document.get("protocol_id"), "arm_result.protocol_id") != protocol.protocol_id:
            raise ValueError("A0 experiment arm protocol mismatch")
        arm_run_ids = tuple(
            _text(item, "arm_result.generation_run_ids[]")
            for item in _sequence(
                arm_document.get("generation_run_ids"), "arm_result.generation_run_ids"
            )
        )
        spec_ids = tuple(
            _text(item, "arm_result.generation_run_spec_ids[]")
            for item in _sequence(
                arm_document.get("generation_run_spec_ids"),
                "arm_result.generation_run_spec_ids",
            )
        )
        if len(arm_run_ids) != len(spec_ids) or len(arm_run_ids) < protocol.minimum_runs(arm):
            raise ValueError("A0 experiment arm run denominator is incomplete")
        parsed.append((arm, arm_run_ids, spec_ids))
    return phase, tuple(parsed)


def build_authorized_us_r1_candidate_denominator_from_documents(
    *,
    status_document: Mapping[str, object],
    preregistration_document: Mapping[str, object],
    execution_plan_document: Mapping[str, object],
    experiment_document: Mapping[str, object],
    gate_review_document: Mapping[str, object],
    generation_run_documents: Sequence[Mapping[str, object]],
) -> USR1CandidateDenominator:
    authority = require_us_r1_stage_authority(status_document)
    protocol, execution_plan = validate_us_a0_execution_plan(
        execution_plan_document,
        preregistration_document,
    )
    phase, arm_runs = _validate_a0_experiment_document(
        experiment_document,
        execution_plan=execution_plan,
        authority=authority,
    )
    review_id, review_phase, decision, experiment_id = validate_terminal_a0_review_document(
        gate_review_document,
        authority=authority,
    )
    if review_phase is not phase or experiment_id != authority.a0_experiment_id:
        raise ValueError("A0 terminal review/experiment phase or identity mismatch")
    if protocol.phase is not phase:
        raise ValueError("A0 preregistration/experiment phase mismatch")

    parsed_runs = tuple(
        parse_candidate_generation_run(document, execution_plan)
        for document in generation_run_documents
    )
    by_id = {run.run_id: run for run in parsed_runs}
    if len(by_id) != len(parsed_runs):
        raise ValueError("A0 generation-run input contains duplicate run IDs")
    expected_run_ids = tuple(run_id for _, run_ids, _ in arm_runs for run_id in run_ids)
    if set(by_id) != set(expected_run_ids):
        raise ValueError("A0 generation-run documents differ from experiment denominator")

    ordered_runs: list[tuple[USAgentValueArm, CandidateGenerationRun]] = []
    for arm, arm_run_ids, spec_ids in arm_runs:
        for index, run_id in enumerate(arm_run_ids):
            run = by_id[run_id]
            if run.spec.run_spec_id != spec_ids[index]:
                raise ValueError("A0 generation run-spec identity differs from experiment")
            if run.spec.arm is not arm or run.spec.phase is not phase:
                raise ValueError("A0 generation run arm/phase differs from experiment")
            ordered_runs.append((arm, run))

    provenance: dict[
        str,
        tuple[USAgentValueCandidateSpec, list[USAgentValueArm], list[str]],
    ] = {}
    order: list[str] = []
    for arm, run in ordered_runs:
        for candidate in run.accepted_candidates:
            candidate_id = candidate.candidate_id
            if candidate_id not in provenance:
                provenance[candidate_id] = (candidate, [], [])
                order.append(candidate_id)
            stored, arms, provenance_run_ids = provenance[candidate_id]
            if stored != candidate:
                raise ValueError("A0 candidate structural identity collision during R1 handoff")
            if arm not in arms:
                arms.append(arm)
            if run.run_id not in provenance_run_ids:
                provenance_run_ids.append(run.run_id)

    candidate_provenance = tuple(
        USR1CandidateProvenance(
            candidate=provenance[candidate_id][0],
            source_arms=tuple(provenance[candidate_id][1]),
            source_run_ids=tuple(provenance[candidate_id][2]),
        )
        for candidate_id in order
    )
    agent_scope = (
        USR1AgentScope.RETAINED
        if decision is USAgentValueGateDecision.FORMAL_INCREMENTAL_VALUE_SUPPORTED
        else USR1AgentScope.CONTRACTED
    )
    return USR1CandidateDenominator(
        protocol_id=canonical_us_r1_research_protocol().protocol_id,
        a0_phase=phase,
        a0_experiment_id=authority.a0_experiment_id,
        a0_gate_review_id=review_id,
        a0_gate_decision=decision,
        agent_scope=agent_scope,
        candidates=candidate_provenance,
    )

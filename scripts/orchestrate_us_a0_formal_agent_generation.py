from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.agents.providers import SQLiteLLMCallStore, load_configured_llm, load_llm_profile
from finagent.research.us_agent_value_execution import validate_us_a0_execution_plan
from finagent.research.us_agent_value_formal_generation import (
    USAgentValueFormalAgentRunProgress,
    USAgentValueFormalAgentSlotEvidence,
    advance_us_a0_formal_agent_run_progress,
    build_us_a0_formal_agent_generation_run,
    formal_agent_request_id,
    parse_us_a0_formal_agent_attempt,
    parse_us_a0_formal_agent_run_progress,
    parse_us_a0_formal_agent_slot,
    validate_us_a0_formal_slot_sequence,
)
from finagent.research.us_agent_value_formal_launch import validate_us_a0_formal_launch_bundle
from finagent.research.us_agent_value_formal_provider import (
    FormalRuntimeBoundDeepSeekAttemptProvider,
)
from finagent.research.us_agent_value_formal_runtime import (
    USAgentValueFormalOrchestrationState,
    advance_us_a0_formal_orchestration_checkpoint,
    parse_us_a0_formal_orchestration_checkpoint,
    validate_us_a0_formal_deepseek_runtime_policy,
)
from finagent.research.us_agent_value_generation import CandidateValidationStatus
from finagent.research.us_agent_value_protocol import USAgentValueArm


def _read_json(path: Path) -> Mapping[str, object]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _read_status(path: Path) -> Mapping[str, object]:
    with path.expanduser().resolve().open("rb") as handle:
        return cast(Mapping[str, object], tomllib.load(handle))


def _write_once(path: Path, document: Mapping[str, object]) -> Path:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(dict(document), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
    except FileExistsError as exc:
        raise SystemExit(f"FORMAL generation evidence already exists and cannot be overwritten: {target}") from exc
    return target


def _call_store_record(store: SQLiteLLMCallStore, request_id: str) -> object | None:
    try:
        return store.get(request_id)
    except KeyError:
        return None


def _require_no_orphaned_call(
    store: SQLiteLLMCallStore,
    request_id: str,
    evidence_path: Path,
) -> None:
    if evidence_path.exists():
        return
    record = _call_store_record(store, request_id)
    if record is not None:
        status = str(getattr(record, "status", "unknown"))
        raise SystemExit(
            "FORMAL provider call exists without immutable attempt evidence; refuse to rerun and "
            f"expand trial budget: request_id={request_id}, status={status}, evidence={evidence_path}"
        )


def _run_has_any_evidence(run_dir: Path) -> bool:
    return run_dir.exists() and any(path.is_file() for path in run_dir.rglob("*"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate all three preregistered FORMAL Agent runs with slot-level resume safety. "
            "Each initial/repair attempt is written once; orphaned provider-call telemetry blocks "
            "reruns rather than expanding the frozen 32-slot budget."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, required=True)
    parser.add_argument("--pilot-gate-review", type=Path, required=True)
    parser.add_argument("--launch-bundle", type=Path, required=True)
    parser.add_argument("--runtime-policy", type=Path, required=True)
    parser.add_argument("--prepared-checkpoint", type=Path, required=True)
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    parser.add_argument("--llm-config", type=Path, default=Path("configs/llm.toml"))
    parser.add_argument("--llm-profile", default="deepseek_official_v4_flash")
    parser.add_argument("--secrets", type=Path, default=None)
    parser.add_argument(
        "--call-store",
        type=Path,
        default=Path("data/us_a0/formal_llm_calls.db"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("reports/us_a0/formal_generation"),
    )
    parser.add_argument(
        "--checkpoint-output",
        type=Path,
        default=Path("reports/us_a0/formal_launch/checkpoint_01_agent_generation_complete.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    preregistration = _read_json(args.preregistration)
    execution_plan_document = _read_json(args.execution_plan)
    protocol, execution_plan = validate_us_a0_execution_plan(
        execution_plan_document,
        preregistration,
    )
    gate_policy = _read_json(args.gate_policy)
    pilot_review = _read_json(args.pilot_gate_review)
    status = _read_status(args.status)
    launch = validate_us_a0_formal_launch_bundle(
        _read_json(args.launch_bundle),
        preregistration_document=preregistration,
        execution_plan_document=execution_plan_document,
        gate_policy_document=gate_policy,
        status_document=status,
        pilot_gate_review_document=pilot_review,
    )
    profile = load_llm_profile(args.llm_config.expanduser().resolve(), args.llm_profile)
    runtime = validate_us_a0_formal_deepseek_runtime_policy(
        _read_json(args.runtime_policy),
        profile=profile,
        launch_artifacts=launch,
    )
    prepared = parse_us_a0_formal_orchestration_checkpoint(
        _read_json(args.prepared_checkpoint)
    )
    if prepared.state is not USAgentValueFormalOrchestrationState.PREPARED:
        raise SystemExit("FORMAL Agent generation requires a PREPARED checkpoint")
    if prepared.launch_bundle_id != launch.launch_bundle.launch_bundle_id:
        raise SystemExit("FORMAL PREPARED checkpoint/launch identity mismatch")
    if prepared.runtime_policy_id != runtime.runtime_policy_id:
        raise SystemExit("FORMAL PREPARED checkpoint/runtime identity mismatch")
    if prepared.pilot_gate_review_id != launch.pilot_gate_review_id:
        raise SystemExit("FORMAL PREPARED checkpoint/PILOT review identity mismatch")

    agent_specs = tuple(
        spec for spec in execution_plan.run_specs if spec.arm is USAgentValueArm.AGENT
    )
    if tuple(spec.run_spec_id for spec in agent_specs) != prepared.agent_run_spec_ids:
        raise SystemExit("FORMAL PREPARED checkpoint AGENT run-spec set differs from ExecutionPlan")

    output_root = args.output_root.expanduser().resolve()
    checkpoint_target = args.checkpoint_output.expanduser().resolve()
    call_store: SQLiteLLMCallStore | None = None
    provider: FormalRuntimeBoundDeepSeekAttemptProvider | None = None

    def get_call_store() -> SQLiteLLMCallStore:
        nonlocal call_store
        if call_store is None:
            call_store = SQLiteLLMCallStore(args.call_store.expanduser().resolve())
        return call_store

    def get_provider() -> FormalRuntimeBoundDeepSeekAttemptProvider:
        nonlocal provider
        if provider is None:
            configured = load_configured_llm(
                args.llm_config.expanduser().resolve(),
                profile_name=profile.name,
                secrets_path=(
                    None if args.secrets is None else args.secrets.expanduser().resolve()
                ),
            )
            provider = FormalRuntimeBoundDeepSeekAttemptProvider(
                configured,
                runtime_policy=runtime,
                call_store=get_call_store(),
            )
        return provider

    run_outputs = tuple(
        output_root / f"run_{spec.run_ordinal:02d}" / f"formal_agent_run_{spec.run_ordinal:02d}.json"
        for spec in agent_specs
    )
    if checkpoint_target.exists():
        completed = parse_us_a0_formal_orchestration_checkpoint(_read_json(checkpoint_target))
        if completed.state is not USAgentValueFormalOrchestrationState.AGENT_GENERATION_COMPLETE:
            raise SystemExit("existing FORMAL checkpoint output has wrong state")
        if completed.previous_checkpoint_id != prepared.checkpoint_id:
            raise SystemExit("existing FORMAL Agent checkpoint does not descend from PREPARED")
        runs = []
        for spec, path in zip(agent_specs, run_outputs, strict=True):
            if not path.exists():
                raise SystemExit("FORMAL Agent checkpoint exists but generation-run evidence is missing")
            run = build_us_a0_formal_agent_generation_run(
                protocol,
                spec,
                tuple(
                    parse_us_a0_formal_agent_slot(
                        _read_json(
                            path.parent / "slots" / f"slot_{slot_index:02d}" / "slot.json"
                        )
                    )
                    for slot_index in range(1, protocol.candidate_budget_per_run + 1)
                ),
            )
            if dict(_read_json(path)) != run.to_dict():
                raise SystemExit("existing FORMAL Agent run differs from immutable slot evidence")
            runs.append(run)
        if completed.agent_generation_run_ids != tuple(run.run_id for run in runs):
            raise SystemExit("existing FORMAL Agent checkpoint/run identities mismatch")
        print(
            json.dumps(
                {
                    "resumed": True,
                    "external_model_called": False,
                    "state": completed.state.value,
                    "checkpoint_id": completed.checkpoint_id,
                    "agent_generation_run_ids": list(completed.agent_generation_run_ids),
                },
                sort_keys=True,
                indent=2,
            )
        )
        return 0

    generated_runs = []
    any_external_call = False
    for run_index, spec in enumerate(agent_specs):
        run_dir = output_root / f"run_{spec.run_ordinal:02d}"
        run_output = run_outputs[run_index]
        if not run_output.exists():
            for later_path in run_outputs[run_index + 1 :]:
                if _run_has_any_evidence(later_path.parent):
                    raise SystemExit("FORMAL Agent run evidence contains a gap/reordered later run")

        slots: list[USAgentValueFormalAgentSlotEvidence] = []
        previous_progress: USAgentValueFormalAgentRunProgress | None = None
        for slot_index in range(1, protocol.candidate_budget_per_run + 1):
            slot_dir = run_dir / "slots" / f"slot_{slot_index:02d}"
            slot_path = slot_dir / "slot.json"
            progress_path = run_dir / "progress" / f"progress_{slot_index:02d}.json"
            if progress_path.exists() and not slot_path.exists():
                raise SystemExit("FORMAL slot progress exists but slot evidence is missing")

            if slot_path.exists():
                slot = parse_us_a0_formal_agent_slot(_read_json(slot_path))
            else:
                accepted = validate_us_a0_formal_slot_sequence(protocol, spec, tuple(slots))
                initial_path = slot_dir / "attempt_00.json"
                if initial_path.exists():
                    initial = parse_us_a0_formal_agent_attempt(_read_json(initial_path))
                else:
                    request_id = formal_agent_request_id(
                        spec.run_spec_id,
                        slot_index=slot_index,
                        attempt_index=0,
                    )
                    _require_no_orphaned_call(get_call_store(), request_id, initial_path)
                    initial = get_provider().generate_attempt(
                        protocol,
                        spec,
                        slot_index=slot_index,
                        attempt_index=0,
                        accepted_candidates=accepted,
                        repair_reason=None,
                    )
                    _write_once(initial_path, initial.to_dict())
                    any_external_call = True

                repair = None
                if initial.status is not CandidateValidationStatus.VALID_UNIQUE:
                    repair_path = slot_dir / "attempt_01.json"
                    if repair_path.exists():
                        repair = parse_us_a0_formal_agent_attempt(_read_json(repair_path))
                    else:
                        request_id = formal_agent_request_id(
                            spec.run_spec_id,
                            slot_index=slot_index,
                            attempt_index=1,
                        )
                        _require_no_orphaned_call(get_call_store(), request_id, repair_path)
                        repair = get_provider().generate_attempt(
                            protocol,
                            spec,
                            slot_index=slot_index,
                            attempt_index=1,
                            accepted_candidates=accepted,
                            repair_reason=(
                                initial.provider_parse_error
                                or initial.classification_reason
                                or "structural_conformance_failure"
                            ),
                        )
                        _write_once(repair_path, repair.to_dict())
                        any_external_call = True
                slot = USAgentValueFormalAgentSlotEvidence(
                    execution_plan_id=execution_plan.plan_id,
                    launch_bundle_id=launch.launch_bundle.launch_bundle_id,
                    runtime_policy_id=runtime.runtime_policy_id,
                    run_spec_id=spec.run_spec_id,
                    run_ordinal=spec.run_ordinal,
                    slot_index=slot_index,
                    initial=initial,
                    repair=repair,
                )
                _write_once(slot_path, slot.to_dict())

            candidate_slots = (*slots, slot)
            validate_us_a0_formal_slot_sequence(protocol, spec, candidate_slots)
            expected_progress = advance_us_a0_formal_agent_run_progress(
                previous=previous_progress,
                execution_plan=execution_plan,
                spec=spec,
                slot=slot,
            )
            if progress_path.exists():
                stored_progress = parse_us_a0_formal_agent_run_progress(
                    _read_json(progress_path)
                )
                if stored_progress != expected_progress:
                    raise SystemExit("FORMAL stored slot progress differs from immutable prefix")
                previous_progress = stored_progress
            else:
                _write_once(progress_path, expected_progress.to_dict())
                previous_progress = expected_progress
            slots.append(slot)

        generation_run = build_us_a0_formal_agent_generation_run(
            protocol,
            spec,
            tuple(slots),
        )
        if run_output.exists():
            if dict(_read_json(run_output)) != generation_run.to_dict():
                raise SystemExit("existing FORMAL Agent generation run differs from slot evidence")
        else:
            _write_once(run_output, generation_run.to_dict())
        generated_runs.append(generation_run)

    completed_checkpoint = advance_us_a0_formal_orchestration_checkpoint(
        prepared,
        state=USAgentValueFormalOrchestrationState.AGENT_GENERATION_COMPLETE,
        agent_generation_run_ids=tuple(run.run_id for run in generated_runs),
    )
    _write_once(checkpoint_target, completed_checkpoint.to_dict())
    print(
        json.dumps(
            {
                "phase": "FORMAL",
                "state": completed_checkpoint.state.value,
                "checkpoint_id": completed_checkpoint.checkpoint_id,
                "agent_generation_run_ids": [run.run_id for run in generated_runs],
                "accepted_candidate_counts": [
                    len(run.accepted_candidates) for run in generated_runs
                ],
                "external_model_called": any_external_call,
                "resumed_existing_evidence": not any_external_call,
                "candidate_budget_per_run": protocol.candidate_budget_per_run,
                "status_authority": False,
                "stage_exit_authority": False,
                "agent_value_gate_authority": False,
                "alpha_authority": False,
                "output_root": str(output_root),
                "checkpoint_output": str(checkpoint_target),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

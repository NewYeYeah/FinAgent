from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.agents.providers import (
    SQLiteLLMCallStore,
    load_configured_llm,
    load_llm_profile,
)
from finagent.research.us_agent_value_authority import require_us_a0_stage_authority
from finagent.research.us_agent_value_deepseek import (
    DEEPSEEK_V4_PRICING_POLICY_ID,
    US_A0_STRUCTURED_PROMPT_TEMPLATE_ID,
    configured_deepseek_structured_provider,
)
from finagent.research.us_agent_value_evaluation import validate_us_a0_preregistration_bundle
from finagent.research.us_agent_value_execution import (
    parse_candidate_generation_run,
    validate_us_a0_execution_plan,
)
from finagent.research.us_agent_value_gate_authority import (
    require_us_a0_pilot_formal_progression_authority,
)
from finagent.research.us_agent_value_launch import validate_us_a0_pilot_launch_bundle
from finagent.research.us_agent_value_orchestration import (
    USAgentValuePilotOrchestrationState,
    advance_us_a0_pilot_orchestration_checkpoint,
    parse_us_a0_pilot_orchestration_checkpoint,
)
from finagent.research.us_agent_value_protocol import USAgentValueArm, USAgentValuePhase
from finagent.research.us_agent_value_provider import (
    StructuredAgentSlotProvider,
    build_authorized_agent_generation_run,
)
from finagent.research.us_agent_value_runtime import (
    configured_runtime_bound_deepseek_provider,
    validate_us_a0_deepseek_runtime_policy,
)

_DEFAULT_A0_LLM_PROFILE = "deepseek_official_v4_flash"


def _read_json(path: Path) -> Mapping[str, object]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _read_status(path: Path) -> Mapping[str, object]:
    with path.expanduser().resolve().open("rb") as handle:
        return cast(Mapping[str, object], tomllib.load(handle))


def _write_once(path: Path, document: Mapping[str, object]) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
    except FileExistsError as exc:
        raise SystemExit(f"research evidence already exists and cannot be overwritten: {target}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate one preregistered US-A0 PILOT AGENT run through the shared FinAgent DeepSeek "
            "provider stack. PILOT generation requires frozen launch/runtime/checkpoint evidence. "
            "FORMAL generation is intentionally routed to the slot-resume-safe FORMAL orchestrator."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--gate-policy", type=Path, default=None)
    parser.add_argument("--launch-bundle", type=Path, default=None)
    parser.add_argument("--runtime-policy", type=Path, default=None)
    parser.add_argument("--orchestration-checkpoint", type=Path, default=None)
    parser.add_argument(
        "--pilot-gate-review",
        type=Path,
        default=None,
        help=(
            "Required when a FORMAL preregistration is supplied, solely to verify progression "
            "authority before this unsafe single-run path refuses and redirects to the FORMAL orchestrator."
        ),
    )
    parser.add_argument(
        "--checkpoint-output",
        type=Path,
        default=Path("reports/us_a0/pilot_launch/checkpoint_01_agent_generated.json"),
    )
    parser.add_argument("--run-ordinal", type=int, default=1)
    parser.add_argument("--llm-config", type=Path, default=Path("configs/llm.toml"))
    parser.add_argument(
        "--llm-profile",
        default=_DEFAULT_A0_LLM_PROFILE,
        help="US-A0 testing defaults to official DeepSeek V4-Flash.",
    )
    parser.add_argument("--secrets", type=Path, default=None)
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    parser.add_argument(
        "--call-store",
        type=Path,
        default=Path("data/us_a0/llm_calls.db"),
        help="Reuse the historical SQLite LLM telemetry store; raw hidden reasoning is not stored.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_a0/generation/us_a0_agent_run.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    preregistration = _read_json(args.preregistration)
    phase = USAgentValuePhase(str(preregistration.get("phase", "")).strip())
    validate_us_a0_preregistration_bundle(preregistration, phase)
    execution_plan_document = _read_json(args.execution_plan)
    protocol, execution_plan = validate_us_a0_execution_plan(
        execution_plan_document,
        preregistration,
    )

    status = _read_status(args.status)
    if phase is USAgentValuePhase.FORMAL:
        if args.pilot_gate_review is None:
            raise SystemExit(
                "FORMAL Agent generation requires --pilot-gate-review before any external provider path"
            )
        require_us_a0_pilot_formal_progression_authority(
            status,
            _read_json(args.pilot_gate_review),
        )
        raise SystemExit(
            "FORMAL Agent generation is disabled in prepare_us_a0_agent_run.py; use "
            "scripts/orchestrate_us_a0_formal_agent_generation.py for slot-level resume safety"
        )
    if args.pilot_gate_review is not None:
        raise SystemExit("PILOT Agent generation must not consume --pilot-gate-review")

    agent_specs = tuple(
        spec
        for spec in execution_plan.run_specs
        if spec.arm is USAgentValueArm.AGENT and spec.run_ordinal == args.run_ordinal
    )
    if len(agent_specs) != 1:
        raise SystemExit(
            f"ExecutionPlan must contain exactly one AGENT run with ordinal {args.run_ordinal}"
        )
    run_spec = agent_specs[0]

    profile = load_llm_profile(
        args.llm_config.expanduser().resolve(),
        args.llm_profile,
    )
    if profile.provider != run_spec.provider_id or profile.model != run_spec.model_id:
        raise SystemExit(
            "selected LLM profile does not match the preregistered AGENT run identity: "
            f"profile={profile.provider}/{profile.model}, "
            f"run={run_spec.provider_id}/{run_spec.model_id}"
        )
    if run_spec.prompt_template_id != US_A0_STRUCTURED_PROMPT_TEMPLATE_ID:
        raise SystemExit("AGENT run does not bind the canonical US-A0 structured prompt template")

    if any(
        value is None
        for value in (
            args.gate_policy,
            args.launch_bundle,
            args.runtime_policy,
            args.orchestration_checkpoint,
        )
    ):
        raise SystemExit(
            "PILOT AGENT generation requires --gate-policy, --launch-bundle, "
            "--runtime-policy and --orchestration-checkpoint"
        )
    assert args.gate_policy is not None
    assert args.launch_bundle is not None
    assert args.runtime_policy is not None
    assert args.orchestration_checkpoint is not None
    gate_policy_document = _read_json(args.gate_policy)
    launch_bundle_document = _read_json(args.launch_bundle)
    launch_artifacts = validate_us_a0_pilot_launch_bundle(
        launch_bundle_document,
        preregistration_document=preregistration,
        execution_plan_document=execution_plan_document,
        gate_policy_document=gate_policy_document,
    )
    if run_spec.run_spec_id not in launch_artifacts.launch_bundle.agent_run_spec_ids:
        raise SystemExit("PILOT AGENT run spec is not authorized by the frozen launch bundle")
    _, runtime_policy = validate_us_a0_deepseek_runtime_policy(
        _read_json(args.runtime_policy),
        profile=profile,
        preregistration_document=preregistration,
        execution_plan_document=execution_plan_document,
        gate_policy_document=gate_policy_document,
        launch_bundle_document=launch_bundle_document,
    )
    prepared_checkpoint = parse_us_a0_pilot_orchestration_checkpoint(
        _read_json(args.orchestration_checkpoint)
    )
    if prepared_checkpoint.state is not USAgentValuePilotOrchestrationState.PREPARED:
        raise SystemExit("PILOT Agent generation requires a PREPARED orchestration checkpoint")
    if prepared_checkpoint.launch_bundle_id != launch_artifacts.launch_bundle.launch_bundle_id:
        raise SystemExit("PILOT orchestration checkpoint/launch identity mismatch")
    if prepared_checkpoint.runtime_policy_id != runtime_policy.runtime_policy_id:
        raise SystemExit("PILOT orchestration checkpoint/runtime-policy identity mismatch")
    if prepared_checkpoint.agent_run_spec_id != run_spec.run_spec_id:
        raise SystemExit("PILOT orchestration checkpoint/AGENT run-spec identity mismatch")

    require_us_a0_stage_authority(status)

    target = args.output.expanduser().resolve()
    checkpoint_target = args.checkpoint_output.expanduser().resolve()

    if checkpoint_target.exists():
        completed_checkpoint = parse_us_a0_pilot_orchestration_checkpoint(
            _read_json(checkpoint_target)
        )
        if completed_checkpoint.state is not USAgentValuePilotOrchestrationState.AGENT_GENERATED:
            raise SystemExit("existing checkpoint output is not AGENT_GENERATED")
        if completed_checkpoint.previous_checkpoint_id != prepared_checkpoint.checkpoint_id:
            raise SystemExit("existing AGENT checkpoint does not descend from PREPARED checkpoint")
        if not target.exists():
            raise SystemExit("AGENT checkpoint exists but generation-run evidence is missing")
        run = parse_candidate_generation_run(_read_json(target), execution_plan)
        if completed_checkpoint.agent_generation_run_id != run.run_id:
            raise SystemExit("existing AGENT checkpoint/run evidence identity mismatch")
        print(
            json.dumps(
                {
                    "resumed": True,
                    "external_model_called": False,
                    "run_id": run.run_id,
                    "checkpoint_id": completed_checkpoint.checkpoint_id,
                    "state": completed_checkpoint.state.value,
                    "output": str(target),
                    "checkpoint_output": str(checkpoint_target),
                },
                sort_keys=True,
                indent=2,
            )
        )
        return 0

    if target.exists():
        generation_run = parse_candidate_generation_run(_read_json(target), execution_plan)
        if generation_run.spec.run_spec_id != run_spec.run_spec_id:
            raise SystemExit("existing AGENT generation run does not match requested run spec")
        external_model_called = False
    else:
        configured = load_configured_llm(
            args.llm_config.expanduser().resolve(),
            profile_name=profile.name,
            secrets_path=(None if args.secrets is None else args.secrets.expanduser().resolve()),
        )
        call_store = SQLiteLLMCallStore(args.call_store.expanduser().resolve())
        provider: StructuredAgentSlotProvider = configured_runtime_bound_deepseek_provider(
            configured,
            runtime_policy=runtime_policy,
            call_store=call_store,
        )
        generation_run = build_authorized_agent_generation_run(
            protocol,
            execution_plan,
            run_spec.run_spec_id,
            provider,
        )
        _write_once(target, generation_run.to_dict())
        external_model_called = True

    completed_checkpoint = advance_us_a0_pilot_orchestration_checkpoint(
        prepared_checkpoint,
        state=USAgentValuePilotOrchestrationState.AGENT_GENERATED,
        agent_generation_run_id=generation_run.run_id,
    )
    _write_once(checkpoint_target, completed_checkpoint.to_dict())
    print(
        json.dumps(
            {
                "run_id": generation_run.run_id,
                "run_spec_id": generation_run.spec.run_spec_id,
                "phase": generation_run.spec.phase.value,
                "run_ordinal": generation_run.spec.run_ordinal,
                "provider": generation_run.spec.provider_id,
                "model": generation_run.spec.model_id,
                "prompt_template_id": generation_run.spec.prompt_template_id,
                "runtime_policy_id": runtime_policy.runtime_policy_id,
                "max_output_tokens": runtime_policy.max_output_tokens,
                "pricing_policy_id": DEEPSEEK_V4_PRICING_POLICY_ID,
                "candidate_budget": generation_run.spec.candidate_budget,
                "accepted_candidate_count": len(generation_run.accepted_candidates),
                "invalid_slot_count": generation_run.invalid_slot_count,
                "duplicate_slot_count": generation_run.duplicate_slot_count,
                "repair_count": generation_run.repair_count,
                "usage": generation_run.usage.to_dict(),
                "external_model_called": external_model_called,
                "resumed": not external_model_called,
                "checkpoint_id": completed_checkpoint.checkpoint_id,
                "research_generation_evidence": True,
                "stage_exit_authority": False,
                "agent_value_gate_authority": False,
                "alpha_authority": False,
                "output": str(target),
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

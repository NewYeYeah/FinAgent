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
from finagent.research.us_agent_value_execution import validate_us_a0_execution_plan
from finagent.research.us_agent_value_launch import validate_us_a0_pilot_launch_bundle
from finagent.research.us_agent_value_protocol import USAgentValueArm, USAgentValuePhase
from finagent.research.us_agent_value_provider import build_authorized_agent_generation_run

_DEFAULT_A0_LLM_PROFILE = "deepseek_official_v4_flash"


def _read_json(path: Path) -> Mapping[str, object]:
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _read_status(path: Path) -> Mapping[str, object]:
    with path.expanduser().resolve().open("rb") as handle:
        return cast(Mapping[str, object], tomllib.load(handle))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate one preregistered US-A0 AGENT run through the shared FinAgent DeepSeek "
            "provider stack. PILOT generation additionally requires the exact pre-result launch "
            "bundle. The external model is not called unless docs/status.toml already authorizes "
            "current_stage=US-A0 with accepted US-B0 predecessor authority."
        )
    )
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument(
        "--gate-policy",
        type=Path,
        default=None,
        help="Required for PILOT so the exact pre-result launch bundle can be validated.",
    )
    parser.add_argument(
        "--launch-bundle",
        type=Path,
        default=None,
        help="Required for PILOT; binds the Agent call to the frozen launch/control evidence.",
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
    parser.add_argument("--overwrite", action="store_true")
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

    if phase is USAgentValuePhase.PILOT:
        if args.gate_policy is None or args.launch_bundle is None:
            raise SystemExit("PILOT AGENT generation requires --gate-policy and --launch-bundle")
        launch_artifacts = validate_us_a0_pilot_launch_bundle(
            _read_json(args.launch_bundle),
            preregistration_document=preregistration,
            execution_plan_document=execution_plan_document,
            gate_policy_document=_read_json(args.gate_policy),
        )
        if run_spec.run_spec_id not in launch_artifacts.launch_bundle.agent_run_spec_ids:
            raise SystemExit("PILOT AGENT run spec is not authorized by the frozen launch bundle")

    # Public model identity may be read before stage authority. Secrets/provider construction
    # intentionally happen only after the project-stage gate passes.
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

    status = _read_status(args.status)
    require_us_a0_stage_authority(status)

    configured = load_configured_llm(
        args.llm_config.expanduser().resolve(),
        profile_name=profile.name,
        secrets_path=(None if args.secrets is None else args.secrets.expanduser().resolve()),
    )
    call_store = SQLiteLLMCallStore(args.call_store.expanduser().resolve())
    provider = configured_deepseek_structured_provider(configured, call_store=call_store)
    generation_run = build_authorized_agent_generation_run(
        protocol,
        execution_plan,
        run_spec.run_spec_id,
        provider,
    )

    target = args.output.expanduser().resolve()
    if target.exists() and not args.overwrite:
        raise SystemExit(f"output already exists; pass --overwrite explicitly: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(generation_run.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "run_id": generation_run.run_id,
                "run_spec_id": generation_run.spec.run_spec_id,
                "phase": generation_run.spec.phase.value,
                "run_ordinal": generation_run.spec.run_ordinal,
                "provider": provider.provider_id,
                "model": provider.model_id,
                "prompt_template_id": provider.prompt_template_id,
                "pricing_policy_id": DEEPSEEK_V4_PRICING_POLICY_ID,
                "candidate_budget": generation_run.spec.candidate_budget,
                "accepted_candidate_count": len(generation_run.accepted_candidates),
                "invalid_slot_count": generation_run.invalid_slot_count,
                "duplicate_slot_count": generation_run.duplicate_slot_count,
                "repair_count": generation_run.repair_count,
                "usage": generation_run.usage.to_dict(),
                "research_generation_evidence": True,
                "stage_exit_authority": False,
                "agent_value_gate_authority": False,
                "alpha_authority": False,
                "output": str(target),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

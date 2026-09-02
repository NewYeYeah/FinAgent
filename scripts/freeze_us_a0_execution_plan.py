from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.agents.providers import load_llm_profile
from finagent.research.us_agent_value_deepseek import US_A0_STRUCTURED_PROMPT_TEMPLATE_ID
from finagent.research.us_agent_value_evaluation import validate_us_a0_preregistration_bundle
from finagent.research.us_agent_value_execution import build_us_a0_execution_plan
from finagent.research.us_agent_value_protocol import USAgentValuePhase

_DEFAULT_SEEDS: dict[USAgentValuePhase, tuple[int, ...]] = {
    USAgentValuePhase.PILOT: (1729,),
    USAgentValuePhase.FORMAL: (1729, 2718, 3141),
}


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the exact US-A0 independent-run plan before candidate generation/evaluation. "
            "The plan binds PROGRAMMATIC seeds and AGENT provider/model/prompt identities and has "
            "no stage-exit, Agent-value-gate or Alpha authority. By default provider/model identity "
            "is read from the shared public LLM profile without loading API secrets."
        )
    )
    parser.add_argument(
        "--preregistration",
        type=Path,
        required=True,
        help="Exact PILOT or FORMAL preregistration bundle frozen before results.",
    )
    parser.add_argument(
        "--llm-config",
        type=Path,
        default=Path("configs/llm.toml"),
        help="Shared public LLM routing config. Secrets are not read by this freezer.",
    )
    parser.add_argument(
        "--llm-profile",
        default=None,
        help="Optional profile override; otherwise [llm].default_profile is used.",
    )
    parser.add_argument(
        "--agent-provider",
        default=None,
        help="Optional explicit provider identity; when supplied it must match the LLM profile.",
    )
    parser.add_argument(
        "--agent-model",
        default=None,
        help="Optional explicit model identity; when supplied it must match the LLM profile.",
    )
    parser.add_argument(
        "--agent-prompt-template",
        default=US_A0_STRUCTURED_PROMPT_TEMPLATE_ID,
    )
    parser.add_argument(
        "--agent-generator-id",
        default="us_a0_structured_agent_generator_v1",
    )
    parser.add_argument(
        "--programmatic-seed",
        type=int,
        action="append",
        default=None,
        help=(
            "Repeat to freeze exact PROGRAMMATIC independent-run seeds. If omitted, use the "
            "pre-result defaults 1729 for PILOT and 1729/2718/3141 for FORMAL."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_a0/us_a0_execution_plan.json"),
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    preregistration_path = args.preregistration.expanduser().resolve()
    preregistration = _read_mapping(preregistration_path)
    phase = USAgentValuePhase(str(preregistration.get("phase", "")).strip())
    protocol = validate_us_a0_preregistration_bundle(preregistration, phase)
    seeds = (
        tuple(args.programmatic_seed)
        if args.programmatic_seed is not None
        else _DEFAULT_SEEDS[phase]
    )

    profile = load_llm_profile(
        args.llm_config.expanduser().resolve(),
        args.llm_profile,
    )
    if args.agent_provider is not None and args.agent_provider.strip() != profile.provider:
        raise SystemExit(
            "--agent-provider must match the selected shared LLM profile: "
            f"{args.agent_provider!r} != {profile.provider!r}"
        )
    if args.agent_model is not None and args.agent_model.strip() != profile.model:
        raise SystemExit(
            "--agent-model must match the selected shared LLM profile: "
            f"{args.agent_model!r} != {profile.model!r}"
        )

    plan = build_us_a0_execution_plan(
        protocol,
        preregistration_bundle_id=str(preregistration["bundle_id"]),
        programmatic_seeds=seeds,
        agent_provider_id=profile.provider,
        agent_model_id=profile.model,
        agent_prompt_template_id=args.agent_prompt_template,
        agent_generator_id=args.agent_generator_id,
    )

    target = args.output.expanduser().resolve()
    if target.exists() and not args.overwrite:
        raise SystemExit(f"output already exists; pass --overwrite explicitly: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(plan.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "plan_id": plan.plan_id,
                "phase": plan.phase.value,
                "protocol_id": plan.protocol_id,
                "preregistration_bundle_id": plan.preregistration_bundle_id,
                "run_spec_count": len(plan.run_specs),
                "run_spec_ids": [item.run_spec_id for item in plan.run_specs],
                "programmatic_seeds": list(seeds),
                "llm_profile": profile.name,
                "agent_provider": profile.provider,
                "agent_model": profile.model,
                "agent_prompt_template": args.agent_prompt_template,
                "secrets_loaded": False,
                "agent_value_gate_authority": False,
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

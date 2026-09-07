"""Guarded R4 campaign admission, freeze, verification and execution operator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from finagent.agents.r3_contracts import canonical_json
from finagent.agents.r4_provider_admission import ProviderAdmission, probe_provider
from finagent.application.r4_campaign import (
    R4CampaignFreeze,
    freeze_campaign,
    record_blocked_freeze,
    run_campaign,
    verify_campaign,
)
from finagent.application.r4_campaign_admission import (
    load_research_admission,
    prepare_research_admission,
)
from finagent.application.research_controller_host import R4ResearchAdmission

DEFAULT_CONFIG = Path("configs/llm.toml")


def _output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", type=Path, required=True)


def _config(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        required=required,
        default=None if required else DEFAULT_CONFIG,
    )


def _campaign_inputs(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    parser.add_argument("--research-admission", type=Path, required=required)
    parser.add_argument("--provider-admission", type=Path, required=required)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    probe = commands.add_parser("probe", help="perform one explicit non-research provider probe")
    _output(probe)
    _config(probe)

    admit = commands.add_parser("admit-source", help="bind the R4 development source")
    _output(admit)
    admit.add_argument("--source-config", type=Path)

    freeze = commands.add_parser("freeze", help="create a fresh accepted campaign freeze")
    _output(freeze)
    _config(freeze)
    _campaign_inputs(freeze)

    verify = commands.add_parser("verify", help="verify one exact accepted campaign freeze")
    _output(verify)
    _config(verify)
    _campaign_inputs(verify)
    verify.add_argument("--accepted-freeze-id")

    blocker = commands.add_parser(
        "record-blocker", help="record failed provider admission lineage without execution authority"
    )
    _output(blocker)
    _config(blocker)
    blocker.add_argument("--research-admission", type=Path)
    blocker.add_argument("--probe-directory", type=Path)

    run = commands.add_parser(
        "run",
        help="execute only an already reviewed ACCEPTED campaign freeze",
        description=(
            "Execute an already accepted R4 campaign. The operator must explicitly supply the "
            "research admission, accepted provider admission, exact reviewed freeze ID, campaign "
            "directory and provider config. This command never probes, freezes, retries, resets or "
            "changes protocol/research settings."
        ),
    )
    _output(run)
    _config(run, required=True)
    _campaign_inputs(run, required=True)
    run.add_argument("--accepted-freeze-id", required=True)
    return parser


def _load_campaign_inputs(args: argparse.Namespace) -> tuple[R4ResearchAdmission, ProviderAdmission]:
    admission = load_research_admission(args.research_admission)
    provider = ProviderAdmission(canonical_json(json.loads(args.provider_admission.read_text())))
    return admission, provider


def _run_summary(result: dict[str, Any], output: Path) -> dict[str, Any]:
    assessment = result["assessment"]
    return {
        "campaign_result_id": result["campaign_result_id"],
        "campaign_freeze_id": result["campaign_freeze_id"],
        "protocol_id": result["protocol_id"],
        "completed_runs": result["completed_runs"],
        "agent_value": assessment["agent_value"],
        "candidate_decision": assessment["candidate_decision"],
        "candidate_id": assessment["candidate_id"],
        "fixture_only": result["fixture_only"],
        "development_only": result["development_only"],
        "alpha_authority": result["alpha_authority"],
        "paper_authority": result["paper_authority"],
        "live_authority": result["live_authority"],
        "result_path": str(output / "campaign_result.json"),
    }


def _run_command(
    args: argparse.Namespace,
    *,
    verifier: Callable[..., R4CampaignFreeze] = verify_campaign,
    runner: Callable[..., dict[str, Any]] = run_campaign,
) -> dict[str, Any]:
    """Thin CLI boundary; injectable callables exist only for offline fixture tests."""
    admission, provider = _load_campaign_inputs(args)
    verifier(
        args.output,
        admission,
        provider,
        accepted_freeze_id=args.accepted_freeze_id,
        config=args.config,
    )
    result = runner(
        args.output,
        admission,
        provider,
        accepted_freeze_id=args.accepted_freeze_id,
        config=args.config,
    )
    print(canonical_json(_run_summary(result, args.output)))
    return result


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "probe":
        print(probe_provider(args.config, args.output).admission_id)
    elif args.command == "admit-source":
        if args.source_config is None:
            parser.error("--source-config required")
        admission = prepare_research_admission(
            json.loads(args.source_config.read_text()), args.output
        )
        print(admission.scope.manifest_id)
    elif args.command == "record-blocker":
        if args.research_admission is None or args.probe_directory is None:
            parser.error("--research-admission and --probe-directory required")
        frozen = record_blocked_freeze(
            load_research_admission(args.research_admission),
            args.probe_directory,
            args.output,
            config=args.config,
        )
        print(
            canonical_json(
                {
                    "campaign_freeze_id": frozen.freeze_id,
                    "protocol_id": frozen.protocol.protocol_id,
                    "status": frozen.to_dict()["status"],
                }
            )
        )
    elif args.command == "run":
        _run_command(args)
    else:
        if args.research_admission is None or args.provider_admission is None:
            parser.error("explicit --research-admission and --provider-admission required")
        admission, provider = _load_campaign_inputs(args)
        if args.command == "freeze":
            from finagent.agents.r4_provider_admission import provider_binding

            provider.verify(provider_binding(args.config))
            frozen = freeze_campaign(admission, provider, args.output, config=args.config)
        else:
            if not args.accepted_freeze_id:
                parser.error("--accepted-freeze-id required")
            frozen = verify_campaign(
                args.output,
                admission,
                provider,
                accepted_freeze_id=args.accepted_freeze_id,
                config=args.config,
            )
        print(
            canonical_json(
                {
                    "protocol_id": frozen.protocol.protocol_id,
                    "campaign_freeze_id": frozen.freeze_id,
                    "status": frozen.to_dict()["status"],
                    "campaign_executed": False,
                }
            )
        )


if __name__ == "__main__":
    main()

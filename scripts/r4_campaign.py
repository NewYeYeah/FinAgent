"""R4 operator admission/freeze/verify. Intentionally no real campaign run command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.agents.r3_contracts import canonical_json
from finagent.agents.r4_provider_admission import ProviderAdmission, probe_provider
from finagent.application.r4_campaign import freeze_campaign, record_blocked_freeze, verify_campaign
from finagent.application.r4_campaign_admission import (
    load_research_admission,
    prepare_research_admission,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("probe", "admit-source", "freeze", "verify", "record-blocker")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/llm.toml"))
    parser.add_argument("--source-config", type=Path)
    parser.add_argument("--research-admission", type=Path)
    parser.add_argument("--provider-admission", type=Path)
    parser.add_argument("--accepted-freeze-id")
    parser.add_argument("--probe-directory", type=Path)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
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
    else:
        if args.research_admission is None or args.provider_admission is None:
            parser.error("explicit --research-admission and --provider-admission required")
        admission = load_research_admission(args.research_admission)
        provider = ProviderAdmission(
            canonical_json(json.loads(args.provider_admission.read_text()))
        )
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

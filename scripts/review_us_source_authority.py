from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.data.provenance import load_dataset_authority_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate a US-S0 dataset source authority config without downloading bulk data."
        )
    )
    parser.add_argument("config", type=Path, help="TOML source-authority review config")
    parser.add_argument("--output", type=Path, help="Optional immutable JSON authority record")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    review = load_dataset_authority_config(args.config)
    bundle = review.bundle
    if args.output is not None:
        bundle.write_json(args.output)
    summary = {
        "schema_version": bundle.schema_version,
        "bundle_id": bundle.bundle_id,
        "candidate_id": bundle.provenance.candidate.candidate_id,
        "revision": bundle.provenance.revision.value,
        "authority_status": bundle.decision.status.value,
        "blocking_issues": list(bundle.decision.blocking_issues),
        "research_authority": bundle.decision.status.value == "accepted_for_research",
        "output": str(args.output) if args.output is not None else None,
    }
    print(json.dumps(summary, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

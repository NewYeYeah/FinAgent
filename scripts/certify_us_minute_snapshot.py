from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.data.provenance import load_dataset_authority_config
from finagent.data.us_minute import (
    DEFAULT_MINUTE_CLEANING_POLICY,
    admit_local_research_with_cleaning,
    certify_local_minute_research_snapshot,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Certify a local Hugging Face OHLCV-1m snapshot under the bounded FinAgent "
            "cleaning policy and create a local/non-redistributed research admission."
        )
    )
    parser.add_argument("root", type=Path, help="Hugging Face cache root or exact snapshot dir")
    parser.add_argument(
        "--authority-config",
        type=Path,
        default=Path("configs/us_source_authority/mito0o852_ohlcv_1m.toml"),
        help="Source authority review config",
    )
    parser.add_argument(
        "--sample-month",
        action="append",
        default=[],
        help="Month to certify (YYYY-MM); repeatable. Defaults to first/middle/last.",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    authority = load_dataset_authority_config(args.authority_config)
    revision = authority.bundle.provenance.revision.value
    certification = certify_local_minute_research_snapshot(
        args.root,
        expected_revision=revision,
        expected_coverage_start=authority.bundle.provenance.coverage_start,
        expected_coverage_end=authority.bundle.provenance.coverage_end,
        sample_months=tuple(args.sample_month) or None,
        cleaning_policy=DEFAULT_MINUTE_CLEANING_POLICY,
    )
    summary: dict[str, object] = {
        "source_candidate": authority.bundle.provenance.candidate.candidate_id,
        "source_revision": revision,
        "source_authority": authority.bundle.decision.status.value,
        "certification": certification.to_dict(),
        "local_research_admitted": False,
    }
    if certification.passed:
        admission = admit_local_research_with_cleaning(authority.bundle, certification)
        summary["local_research_admitted"] = True
        summary["admission"] = admission.to_dict()

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, sort_keys=True, indent=2))
    return 0 if certification.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

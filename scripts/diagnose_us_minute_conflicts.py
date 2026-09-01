from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.data.provenance import load_dataset_authority_config
from finagent.data.us_minute import diagnose_local_minute_conflicts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose conflicting duplicate (ticker,timestamp) groups in one local "
            "OHLCV-1m monthly partition without mutating the source snapshot."
        )
    )
    parser.add_argument("root", type=Path, help="Hugging Face cache root or exact snapshot dir")
    parser.add_argument("--month", required=True, help="Monthly partition to inspect (YYYY-MM)")
    parser.add_argument(
        "--authority-config",
        type=Path,
        default=Path("configs/us_source_authority/mito0o852_ohlcv_1m.toml"),
        help="Source authority review config",
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=20,
        help="Number of conflict-group examples to include in the JSON summary",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON summary path")
    parser.add_argument(
        "--rows-output",
        type=Path,
        help="Optional CSV path for all raw rows belonging to conflicting keys",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    authority = load_dataset_authority_config(args.authority_config)
    revision = authority.bundle.provenance.revision.value
    diagnostic = diagnose_local_minute_conflicts(
        args.root,
        expected_revision=revision,
        month=args.month,
        examples=args.examples,
        rows_output=args.rows_output,
    )
    payload: dict[str, object] = {
        "source_candidate": authority.bundle.provenance.candidate.candidate_id,
        "source_revision": revision,
        "source_authority": authority.bundle.decision.status.value,
        "diagnostic": diagnostic.to_dict(),
        "research_admission_unchanged": True,
        "recommended_terminal": (
            "UNRESOLVED_CONFLICTING_DUPLICATES"
            if diagnostic.unresolved
            else "NO_CONFLICTING_DUPLICATES_OBSERVED"
        ),
    }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

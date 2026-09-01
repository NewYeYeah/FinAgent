from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.data.us_universe_finalization_v2 import (
    USUniverseFinalizationPolicyV2,
    finalize_us_engineering_universe_v2,
)


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the final US-I0 20-30 name EngineeringUniverse from a deterministic "
            "candidate report, fresh read-only quote evidence and a fresh read-only MT5 "
            "inventory that records final Market Watch visibility/tradability."
        )
    )
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--quote-probe", type=Path, required=True)
    parser.add_argument(
        "--mt5-inventory-probe",
        type=Path,
        required=True,
        help=(
            "Fresh read-only MT5 inventory after manually making selected candidates visible. "
            "FinAgent does not call symbol_select."
        ),
    )
    parser.add_argument("--target-count", type=int, default=25)
    parser.add_argument("--minimum-count", type=int, default=20)
    parser.add_argument("--maximum-count", type=int, default=30)
    parser.add_argument("--maximum-current-spread-bps", type=float, default=50.0)
    parser.add_argument(
        "--maximum-quote-age-seconds",
        type=int,
        default=900,
        help="Maximum quote age at finalization time (default: 900 seconds).",
    )
    parser.add_argument(
        "--maximum-future-quote-skew-seconds",
        type=int,
        default=60,
        help="Maximum tolerated quote timestamp lead over local finalization time.",
    )
    parser.add_argument(
        "--attest-selected-exact-matches",
        action="store_true",
        help=(
            "Explicitly attest that every policy-selected exact RESEARCH=BROKER symbol "
            "represents the same security for bounded engineering integration only."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_instruments/us_i0_final_engineering_universe.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    policy = USUniverseFinalizationPolicyV2(
        target_count=args.target_count,
        minimum_count=args.minimum_count,
        maximum_count=args.maximum_count,
        maximum_current_spread_bps=args.maximum_current_spread_bps,
        maximum_quote_age_seconds=args.maximum_quote_age_seconds,
        maximum_future_quote_skew_seconds=args.maximum_future_quote_skew_seconds,
    )
    report = finalize_us_engineering_universe_v2(
        _read_mapping(args.candidate_report),
        _read_mapping(args.quote_probe),
        _read_mapping(args.mt5_inventory_probe),
        policy=policy,
        operator_attested=args.attest_selected_exact_matches,
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report_id": report.report_id,
                "policy_id": policy.policy_id,
                "accepted": report.accepted,
                "universe_id": report.universe_id,
                "accepted_mapping_count": report.accepted_mapping_count,
                "selected_symbols": list(report.selected_symbols),
                "excluded_by_quote_quality": sorted(
                    set(report.quote_evidence.stale_quote_symbols)
                    | set(report.quote_evidence.future_quote_symbols)
                ),
                "excluded_by_spread": list(report.excluded_by_spread),
                "quote_evidence_id": report.quote_evidence.assessment_id,
                "quote_evidence_passed": report.quote_evidence.passed,
                "blockers": list(report.blockers),
                "output": str(output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if report.accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.data.us_simulation_universe import (
    finalize_us_simulation_engineering_universe,
    validate_canonical_us_simulation_universe_policy,
)


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Finalize the no-account US-I0 simulation EngineeringUniverse from the "
            "deterministic candidate selection, immutable raw quote-probe v2 provenance, "
            "its delayed-reference assessment and a fresh read-only MT5 inventory. "
            "This command does not invoke or weaken the live/current v3 finalizer."
        )
    )
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--quote-probe", type=Path, required=True)
    parser.add_argument("--delayed-reference-report", type=Path, required=True)
    parser.add_argument("--simulation-universe-policy", type=Path, required=True)
    parser.add_argument(
        "--mt5-inventory-probe",
        type=Path,
        required=True,
        help=(
            "Fresh read-only MT5 inventory collected after manually exposing the "
            "candidate symbols. FinAgent does not call symbol_select."
        ),
    )
    parser.add_argument(
        "--attest-selected-exact-matches",
        action="store_true",
        help=(
            "Attest that every selected exact RESEARCH=BROKER symbol identifies the "
            "same security for bounded simulation engineering only."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "reports/us_instruments/us_i0_simulation_engineering_universe.json"
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    policy = validate_canonical_us_simulation_universe_policy(
        _read_mapping(args.simulation_universe_policy)
    )
    report = finalize_us_simulation_engineering_universe(
        _read_mapping(args.candidate_report),
        _read_mapping(args.quote_probe),
        _read_mapping(args.delayed_reference_report),
        _read_mapping(args.mt5_inventory_probe),
        policy=policy,
        operator_attested=args.attest_selected_exact_matches,
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict()
    output.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report_id": report.report_id,
                "schema_version": report.schema_version,
                "policy_id": policy.policy_id,
                "accepted_for_simulation_engineering": (
                    report.accepted_for_simulation_engineering
                ),
                "simulation_universe_id": report.simulation_universe_id,
                "simulation_accepted_mapping_count": (
                    report.simulation_accepted_mapping_count
                ),
                "selected_symbols": list(report.selected_symbols),
                "excluded_by_delayed_quality": list(
                    report.excluded_by_delayed_quality
                ),
                "excluded_by_reference_spread": list(
                    report.excluded_by_reference_spread
                ),
                "delayed_reference_report_id": report.delayed_reference_report_id,
                "inventory_probe_id": report.inventory_probe_id,
                "inventory_age_seconds": report.inventory_age_seconds,
                "live_market_data_authority": False,
                "live_executable_spread_authority": False,
                "execution_authority": False,
                "stage_exit_authority": False,
                "blockers": list(report.blockers),
                "output": str(output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if report.accepted_for_simulation_engineering else 2


if __name__ == "__main__":
    raise SystemExit(main())

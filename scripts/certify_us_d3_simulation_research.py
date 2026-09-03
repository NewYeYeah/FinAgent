from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from finagent.data.us_minute.simulation_certification import (
    build_us_simulation_d3_certification,
    validate_canonical_us_simulation_d3_certification_policy,
)


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate US-S0/US-D1/US-D2, the accepted no-account S2 simulation universe "
            "and U.S. MT5-D0 reconciliation into an explicit simulation-limited US-D3 "
            "certification. Continuous/all-day products are not part of this denominator."
        )
    )
    parser.add_argument("--source-certification", type=Path, required=True)
    parser.add_argument("--d1-smoke", type=Path, required=True)
    parser.add_argument("--d2-smoke", type=Path, required=True)
    parser.add_argument("--simulation-engineering-universe", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument(
        "--point-in-time-security-master-available",
        action="store_true",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_d3/us_d3_simulation_research_certification.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    policy = validate_canonical_us_simulation_d3_certification_policy(
        _read_mapping(args.policy)
    )
    report = build_us_simulation_d3_certification(
        source_document=_read_mapping(args.source_certification),
        d1_document=_read_mapping(args.d1_smoke),
        d2_document=_read_mapping(args.d2_smoke),
        simulation_universe_document=_read_mapping(args.simulation_engineering_universe),
        reconciliation_document=_read_mapping(args.reconciliation),
        point_in_time_security_master_available=(
            args.point_in_time_security_master_available
        ),
        policy=policy,
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
                "outcome": report.outcome.value,
                "certified": report.certified,
                "simulation_universe_report_id": report.simulation_universe.report_id,
                "simulation_universe_id": report.simulation_universe.simulation_universe_id,
                "reconciliation_report_id": report.reconciliation_report_id,
                "blockers": list(report.blockers),
                "limitations": list(report.limitations),
                "supports_us_b0_progression": report.certified,
                "all_day_preflight_in_certification_denominator": False,
                "live_market_data_authority": False,
                "live_executable_spread_authority": False,
                "execution_authority": False,
                "status_authority": False,
                "stage_exit_authority": False,
                "output": str(output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if report.certified else 2


if __name__ == "__main__":
    raise SystemExit(main())

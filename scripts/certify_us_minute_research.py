from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from finagent.data.us_minute.research_certification import (
    USMinuteCertificationPolicy,
    evaluate_us_minute_certification,
    load_us_minute_certification_inputs,
)


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate row-free US-S0/US-D1/US-D2/US-I0/reconciliation evidence "
            "into the provider-neutral US-D3 minute-data certification decision."
        )
    )
    parser.add_argument("--source-certification", type=Path, required=True)
    parser.add_argument("--d1-smoke", type=Path, required=True)
    parser.add_argument("--d2-smoke", type=Path)
    parser.add_argument("--engineering-universe", type=Path)
    parser.add_argument("--reconciliation", type=Path)
    parser.add_argument(
        "--point-in-time-security-master-available",
        action="store_true",
        help=(
            "Assert only when an accepted point-in-time security-master/lifecycle "
            "artifact is actually supplied by the governed environment."
        ),
    )
    parser.add_argument(
        "--minimum-universe-size",
        type=int,
        default=20,
    )
    parser.add_argument(
        "--maximum-universe-size",
        type=int,
        default=30,
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source = _read_mapping(args.source_certification)
    d1 = _read_mapping(args.d1_smoke)
    d2 = _read_mapping(args.d2_smoke) if args.d2_smoke else None
    universe = (
        _read_mapping(args.engineering_universe)
        if args.engineering_universe
        else None
    )
    reconciliation = (
        _read_mapping(args.reconciliation) if args.reconciliation else None
    )

    inputs = load_us_minute_certification_inputs(
        source_document=source,
        d1_document=d1,
        d2_document=d2,
        universe_document=universe,
        reconciliation_document=reconciliation,
        point_in_time_security_master_available=(
            args.point_in_time_security_master_available
        ),
    )
    policy = USMinuteCertificationPolicy(
        minimum_engineering_universe_size=args.minimum_universe_size,
        maximum_engineering_universe_size=args.maximum_universe_size,
    )
    report = evaluate_us_minute_certification(inputs, policy=policy)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.to_dict(), sort_keys=True, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "report_id": report.report_id,
                "outcome": report.outcome.value,
                "certified": report.certified,
                "blockers": list(report.blockers),
                "limitations": list(report.limitations),
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

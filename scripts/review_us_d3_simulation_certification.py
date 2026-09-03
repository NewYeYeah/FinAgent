from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from finagent.data.us_minute.simulation_certification import (
    USSimulationD3Review,
    USSimulationD3ReviewDecision,
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
            "Independently review a simulation-limited US-D3 certification after rebuilding "
            "it from exact source/D1/D2/S2/reconciliation evidence. The reviewer may accept "
            "a passing machine certification or conservatively reject it, never upgrade a failure."
        )
    )
    parser.add_argument("--source-certification", type=Path, required=True)
    parser.add_argument("--d1-smoke", type=Path, required=True)
    parser.add_argument("--d2-smoke", type=Path, required=True)
    parser.add_argument("--simulation-engineering-universe", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--certification", type=Path, required=True)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--decision", choices=[item.value for item in USSimulationD3ReviewDecision], required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument(
        "--point-in-time-security-master-available",
        action="store_true",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_d3/us_d3_simulation_research_review.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    policy = validate_canonical_us_simulation_d3_certification_policy(
        _read_mapping(args.policy)
    )
    rebuilt = build_us_simulation_d3_certification(
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
    stored = _read_mapping(args.certification)
    if stored != rebuilt.to_dict():
        raise RuntimeError(
            "stored simulation D3 certification differs from deterministic reconstruction"
        )
    review = USSimulationD3Review(
        certification=rebuilt,
        reviewer_id=args.reviewer_id,
        reviewed_at=datetime.now(UTC),
        decision=USSimulationD3ReviewDecision(args.decision),
        notes=args.notes,
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        existing = _read_mapping(output)
        if existing != review.to_dict():
            raise RuntimeError(
                "existing simulation D3 review differs; do not overwrite an independent review"
            )
    else:
        output.write_text(
            json.dumps(review.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "review_id": review.review_id,
                "certification_report_id": rebuilt.report_id,
                "decision": review.decision.value,
                "accepted": review.accepted,
                "supports_us_b0_progression": review.accepted,
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
    return 0 if review.accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())

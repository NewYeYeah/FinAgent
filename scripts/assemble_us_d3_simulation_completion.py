from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from finagent.data.us_minute.simulation_completion import (
    build_us_simulation_d3_completion_bundle,
)


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild the exact simulation US-D3 machine certification and independent review, "
            "then emit one content-addressed governance-readiness bundle. This command does not "
            "modify docs/status.toml and creates no live/PAPER/execution authority."
        )
    )
    parser.add_argument("--source-certification", type=Path, required=True)
    parser.add_argument("--d1-smoke", type=Path, required=True)
    parser.add_argument("--d2-smoke", type=Path, required=True)
    parser.add_argument("--simulation-engineering-universe", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--certification", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--code-fence-sha", required=True)
    parser.add_argument("--point-in-time-security-master-available", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_d3/us_d3_simulation_completion.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    bundle = build_us_simulation_d3_completion_bundle(
        source_document=_read_mapping(args.source_certification),
        d1_document=_read_mapping(args.d1_smoke),
        d2_document=_read_mapping(args.d2_smoke),
        simulation_universe_document=_read_mapping(args.simulation_engineering_universe),
        reconciliation_document=_read_mapping(args.reconciliation),
        policy_document=_read_mapping(args.policy),
        certification_document=_read_mapping(args.certification),
        review_document=_read_mapping(args.review),
        code_fence_sha=args.code_fence_sha,
        assembled_at=datetime.now(UTC),
        point_in_time_security_master_available=(
            args.point_in_time_security_master_available
        ),
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        existing = _read_mapping(output)
        if existing != bundle.to_dict():
            raise RuntimeError(
                "existing US-D3 completion bundle differs; do not overwrite reviewed closure evidence"
            )
    else:
        output.write_text(
            json.dumps(bundle.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "bundle_id": bundle.bundle_id,
                "governance_ready": True,
                "supports_us_b0_progression": True,
                "simulation_universe_id": bundle.simulation_universe_id,
                "certification_report_id": bundle.certification_report_id,
                "review_id": bundle.review_id,
                "status_authority": False,
                "stage_exit_authority": False,
                "output": str(output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

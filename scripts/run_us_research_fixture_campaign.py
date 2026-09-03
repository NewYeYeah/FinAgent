from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from finagent.research.us_fixture_campaign import run_us_research_fixture_campaign


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--generated-at must be timezone-aware ISO-8601")
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the deterministic B0/A0/R1 development fixture campaign. "
            "This command creates engineering-only evidence and never advances project, "
            "Agent Value, Alpha, execution, PAPER, or live-capital authority."
        )
    )
    parser.add_argument(
        "--generated-at",
        type=_parse_timestamp,
        default=None,
        help="Optional timezone-aware ISO-8601 timestamp for deterministic replay.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/development/us_research_fixture_campaign.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_us_research_fixture_campaign(generated_at=args.generated_at)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict()
    encoded = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if output.exists():
        existing = output.read_text(encoding="utf-8")
        if existing != encoded:
            raise RuntimeError(
                "existing fixture campaign report differs; use a new output path or the exact "
                "same --generated-at for deterministic replay"
            )
    else:
        output.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "campaign_id": report.campaign_id,
                "passed": report.passed,
                "scenario_terminals": {
                    item.scenario.value: item.r1.terminal.value for item in report.scenarios
                },
                "real_us_market_evidence_substituted": False,
                "status_authority": False,
                "stage_exit_authority": False,
                "agent_value_gate_authority": False,
                "alpha_authority": False,
                "output": str(output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

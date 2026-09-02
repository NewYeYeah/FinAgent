from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from finagent.data.us_candidate_quotes_v2 import (
    candidate_quote_probe_report_v2_from_document,
)
from finagent.data.us_delayed_reference_quotes import (
    build_us_delayed_reference_quote_report,
    us_delayed_reference_quote_report_from_document,
    validate_canonical_us_simulation_quote_timing_policy,
)


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Assess a persisted live/current US-I0 quote probe as a no-account "
            "MetaQuotes-Demo delayed reference. The raw v2 report remains unchanged "
            "and retains its original stale/current-quote semantics."
        )
    )
    parser.add_argument("--quote-probe", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    raw = candidate_quote_probe_report_v2_from_document(
        _read_mapping(args.quote_probe.expanduser().resolve())
    )
    policy = validate_canonical_us_simulation_quote_timing_policy(
        _read_mapping(args.policy.expanduser().resolve())
    )
    report = build_us_delayed_reference_quote_report(raw, policy)
    document = report.to_dict()

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        existing = us_delayed_reference_quote_report_from_document(_read_mapping(output))
        if existing.to_dict() != document:
            raise RuntimeError(
                "existing delayed-reference report differs; use a new output path for "
                "a new raw quote-probe identity"
            )
    else:
        output.write_text(
            json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "report_id": report.report_id,
                "raw_quote_probe_report_id": report.raw_quote_probe_report_id,
                "simulation_policy_id": report.policy.policy_id,
                "broker_server": report.broker_server,
                "broker_clock_passed": report.broker_clock_passed,
                "valid_quote_count": len(report.valid_symbols),
                "valid_quote_symbols": list(report.valid_symbols),
                "ready_for_simulation_reference": report.ready_for_simulation_reference,
                "blockers": list(report.blockers),
                "broker_account_required": False,
                "live_market_data_authority": False,
                "live_executable_spread_authority": False,
                "execution_authority": False,
                "order_authority": False,
                "live_capital_authority": False,
                "status_authority": False,
                "stage_exit_authority": False,
                "output": str(output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if report.ready_for_simulation_reference else 2


if __name__ == "__main__":
    raise SystemExit(main())

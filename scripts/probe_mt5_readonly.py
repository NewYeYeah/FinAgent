from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from finagent.brokers.mt5 import (
    RECOMMENDED_MT5_PACKAGE_VERSION,
    MT5P0AcceptancePolicy,
    MetaTrader5ReadOnlyClient,
    assess_mt5_p0,
    run_mt5_readonly_probe,
)


def _aware_datetime(value: str) -> datetime:
    rendered = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(rendered)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            "timestamps must be timezone-aware ISO-8601 values, e.g. 2026-01-01T00:00:00+00:00"
        )
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Probe the connected MetaTrader 5 terminal using the MT5-P0 read-only surface. "
            "No order/position/account mutation API is exposed by this script."
        )
    )
    parser.add_argument(
        "--expected-package-version",
        default=RECOMMENDED_MT5_PACKAGE_VERSION,
        help="Exact official MetaTrader5 Python package version expected by the probe",
    )
    parser.add_argument(
        "--symbol-group",
        default="",
        help="Optional MetaTrader5 symbols_get group filter; empty means full inventory",
    )
    parser.add_argument(
        "--history-symbol",
        action="append",
        default=[],
        help="Broker symbol to probe for M1/tick history; repeatable",
    )
    parser.add_argument("--bar-start", type=_aware_datetime)
    parser.add_argument("--bar-end", type=_aware_datetime)
    parser.add_argument("--tick-start", type=_aware_datetime)
    parser.add_argument("--tick-end", type=_aware_datetime)
    parser.add_argument(
        "--spread-symbol",
        action="append",
        default=[],
        help="Broker symbol for a current bid/ask spread sample; repeatable",
    )
    parser.add_argument(
        "--p0-representative-symbol",
        action="append",
        default=[],
        help=(
            "Exact visible/tradable broker symbol required by the MT5-P0 acceptance policy; "
            "repeatable. These symbols are automatically included in history and spread probes."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/mt5/mt5_p0_capability_probe.json"),
    )
    parser.add_argument(
        "--assessment-output",
        type=Path,
        help=(
            "Optional MT5-P0 assessment JSON path. When representative symbols are supplied, "
            "the default is <output-stem>_assessment.json."
        ),
    )
    return parser


def _unique_symbols(*groups: list[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            item.strip()
            for group in groups
            for item in group
            if item.strip()
        )
    )


def main() -> int:
    args = build_parser().parse_args()
    representative_symbols = _unique_symbols(args.p0_representative_symbol)
    history_symbols = _unique_symbols(args.history_symbol, args.p0_representative_symbol)
    spread_symbols = _unique_symbols(args.spread_symbol, args.p0_representative_symbol)

    if history_symbols and (args.bar_start is None or args.bar_end is None):
        raise SystemExit("history probing requires both --bar-start and --bar-end")
    if (args.tick_start is None) != (args.tick_end is None):
        raise SystemExit("--tick-start and --tick-end must be supplied together")
    if representative_symbols and (args.tick_start is None or args.tick_end is None):
        raise SystemExit(
            "--p0-representative-symbol requires --tick-start and --tick-end "
            "so tick-history evidence is explicit"
        )

    client = MetaTrader5ReadOnlyClient(
        expected_package_version=args.expected_package_version,
    )
    report = run_mt5_readonly_probe(
        client,
        symbol_group=args.symbol_group,
        history_symbols=history_symbols,
        bar_start=args.bar_start,
        bar_end=args.bar_end,
        tick_start=args.tick_start,
        tick_end=args.tick_end,
        spread_symbols=spread_symbols,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    assessment = None
    assessment_path = args.assessment_output
    if representative_symbols:
        policy = MT5P0AcceptancePolicy(
            representative_symbols=representative_symbols,
            expected_package_version=args.expected_package_version,
        )
        assessment = assess_mt5_p0(report, policy)
        if assessment_path is None:
            assessment_path = args.output.with_name(
                f"{args.output.stem}_assessment.json"
            )
        assessment_path.parent.mkdir(parents=True, exist_ok=True)
        assessment_path.write_text(
            json.dumps(
                {
                    "policy": policy.to_dict(),
                    "assessment": assessment.to_dict(),
                },
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    summary = {
        "probe_id": report.probe_id,
        "package_version": report.terminal.package_version,
        "terminal_version": report.terminal.terminal_version,
        "terminal_build": report.terminal.terminal_build,
        "connected": report.terminal.connected,
        "broker_server": report.terminal.broker_server,
        "symbol_count": len(report.symbols),
        "visible_symbol_count": report.visible_symbol_count,
        "tradable_symbol_count": report.tradable_symbol_count,
        "history": [item.to_dict() for item in report.history],
        "spread_samples": [item.to_dict() for item in report.spread_samples],
        "read_only": report.read_only,
        "mutation_authority": report.mutation_authority,
        "p0_assessment": assessment.to_dict() if assessment is not None else None,
        "output": str(args.output),
        "assessment_output": str(assessment_path) if assessment_path else None,
    }
    print(json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False))
    if assessment is not None and not assessment.accepted:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

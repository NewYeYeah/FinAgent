from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from finagent.brokers.mt5 import (
    MT5_FEED_REGIME_LANES,
    RECOMMENDED_MT5_PACKAGE_VERSION,
    MetaTrader5ReadOnlyClient,
    build_mt5_feed_regime_report,
    probe_mt5_capabilities,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture a read-only MT5 feed-regime fingerprint for explicitly selected symbols. "
            "The report is diagnostic only and cannot satisfy US-I0, MT5-D0, US-D3, PAPER, "
            "execution or live-market authority. The script never calls symbol_select()."
        )
    )
    parser.add_argument(
        "--feed-lane",
        required=True,
        choices=MT5_FEED_REGIME_LANES,
        help="Explicit evidence lane; it is never inferred from ticker, quote age or contract fields",
    )
    parser.add_argument(
        "--symbol",
        action="append",
        required=True,
        help="Exact already-exposed MT5 symbol to fingerprint; repeatable",
    )
    parser.add_argument(
        "--symbol-group",
        default="",
        help="Optional symbols_get group filter; empty means full read-only inventory",
    )
    parser.add_argument(
        "--expected-package-version",
        default=RECOMMENDED_MT5_PACKAGE_VERSION,
        help="Exact official MetaTrader5 Python package version expected by the probe",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/mt5/mt5_feed_regime.json"),
    )
    return parser


def _symbols(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in values if item.strip()))


def main() -> int:
    args = build_parser().parse_args()
    symbols = _symbols(args.symbol)
    if not symbols:
        raise SystemExit("at least one non-empty --symbol is required")

    observed_at = datetime.now(UTC)
    client = MetaTrader5ReadOnlyClient(
        expected_package_version=args.expected_package_version,
    )
    client.initialize()
    try:
        capability_report = probe_mt5_capabilities(
            client,
            symbol_group=args.symbol_group,
            probed_at=observed_at,
        )
        raw_inventory = client.symbols_get(args.symbol_group)
        if not isinstance(raw_inventory, (tuple, list)):
            try:
                raw_rows = tuple(raw_inventory)  # type: ignore[arg-type]
            except TypeError as exc:
                raise RuntimeError("MT5 symbols_get() result is not iterable") from exc
        else:
            raw_rows = tuple(raw_inventory)
        report = build_mt5_feed_regime_report(
            capability_report,
            raw_rows,
            symbols,
            feed_lane=args.feed_lane,
            generated_at=observed_at,
        )
    finally:
        client.shutdown()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    summary = {
        "report_id": report.report_id,
        "feed_lane": report.feed_lane,
        "broker_server": report.broker_server,
        "capability_probe_id": report.capability_probe_id,
        "requested_symbols": list(report.requested_symbols),
        "complete_for_diagnostic": report.complete_for_diagnostic,
        "evidence_count": len(report.evidence),
        "issues": [item.to_dict() for item in report.issues],
        "scope": "mt5_feed_regime_diagnostic_only",
        "output": str(args.output),
    }
    print(json.dumps(summary, sort_keys=True, indent=2, ensure_ascii=False))
    return 0 if report.complete_for_diagnostic else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import importlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finagent.brokers.mt5.clock import (
    MT5BrokerClockObservation,
    build_mt5_broker_clock_evidence,
)
from finagent.brokers.mt5.continuous_quote_smoke import (
    MT5ContinuousQuoteSmokePolicy,
    build_mt5_continuous_quote_smoke_report,
)

DEFAULT_SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY")


def _module() -> Any:
    try:
        return importlib.import_module("MetaTrader5")
    except ImportError as exc:
        raise SystemExit("MetaTrader5 package is required for this local Windows smoke") from exc


def _symbols(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(item.strip() for item in values if item.strip()))
    if not normalized:
        raise argparse.ArgumentTypeError("at least one symbol is required")
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a read-only MT5 current-quote smoke on continuously quoted instruments. "
            "This is engineering smoke only and cannot satisfy US-I0/US-D3 evidence gates."
        )
    )
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--reference-symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--minimum-symbol-count", type=int, default=3)
    parser.add_argument("--maximum-quote-age-seconds", type=int, default=60)
    parser.add_argument("--maximum-future-quote-skew-seconds", type=int, default=5)
    parser.add_argument("--expected-package-version", default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/mt5/mt5_continuous_quote_smoke.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    symbols = _symbols(args.symbols)
    references = _symbols(args.reference_symbols)
    mt5 = _module()
    if args.expected_package_version is not None:
        observed = str(getattr(mt5, "__version__", "")).strip()
        if observed != args.expected_package_version:
            raise SystemExit(
                f"MetaTrader5 package version mismatch: observed={observed!r} "
                f"expected={args.expected_package_version!r}"
            )
    if not mt5.initialize():
        raise SystemExit(f"mt5.initialize() failed: {mt5.last_error()}")

    try:
        account = mt5.account_info()
        if account is None:
            raise SystemExit(f"mt5.account_info() failed: {mt5.last_error()}")
        broker_server = str(account.server).strip()
        if not broker_server:
            raise SystemExit("MT5 account server is empty")

        clock_observations: list[MT5BrokerClockObservation] = []
        for symbol in references:
            tick = mt5.symbol_info_tick(symbol)
            retrieved = datetime.now(UTC)
            if tick is None:
                continue
            clock_observations.append(
                MT5BrokerClockObservation(
                    symbol=symbol,
                    raw_broker_time_msc=int(tick.time_msc),
                    retrieved_at_utc=retrieved,
                    bid=float(tick.bid),
                    ask=float(tick.ask),
                )
            )
        clock = build_mt5_broker_clock_evidence(
            broker_server,
            tuple(clock_observations),
        )

        inventory_rows: list[dict[str, object]] = []
        tick_rows: dict[str, dict[str, object] | None] = {}
        retrieved_at: dict[str, datetime] = {}
        for symbol in symbols:
            info = mt5.symbol_info(symbol)
            if info is not None:
                inventory_rows.append(
                    {
                        "name": symbol,
                        "visible": bool(info.visible),
                        "trade_mode": int(info.trade_mode),
                    }
                )
            tick = mt5.symbol_info_tick(symbol)
            retrieved_at[symbol] = datetime.now(UTC)
            tick_rows[symbol] = (
                None
                if tick is None
                else {
                    "time": int(tick.time),
                    "time_msc": int(tick.time_msc),
                    "bid": float(tick.bid),
                    "ask": float(tick.ask),
                }
            )

        report = build_mt5_continuous_quote_smoke_report(
            broker_server,
            symbols,
            inventory_rows,
            tick_rows,
            retrieved_at,
            clock,
            policy=MT5ContinuousQuoteSmokePolicy(
                minimum_symbol_count=args.minimum_symbol_count,
                maximum_quote_age_seconds=args.maximum_quote_age_seconds,
                maximum_future_quote_skew_seconds=args.maximum_future_quote_skew_seconds,
            ),
        )
    finally:
        mt5.shutdown()

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
                "passed": report.passed,
                "blockers": list(report.blockers),
                "clock_evidence_id": report.clock_evidence.evidence_id,
                "clock_offset_seconds": report.clock_evidence.inferred_offset_seconds,
                "passed_symbol_count": report.passed_symbol_count,
                "requested_symbols": list(report.requested_symbols),
                "stage_exit_authority": False,
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

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
from finagent.brokers.mt5.simulation_all_day_preflight import (
    MT5SimulationAllDayPreflightPolicy,
    build_mt5_simulation_all_day_preflight_report,
)

DEFAULT_SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY")


def _module() -> Any:
    try:
        return importlib.import_module("MetaTrader5")
    except ImportError as exc:
        raise SystemExit("MetaTrader5 package is required for this local Windows preflight") from exc


def _symbols(values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(item.strip() for item in values if item.strip()))
    if not normalized:
        raise argparse.ArgumentTypeError("at least one symbol is required")
    return normalized


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the no-target-broker-account MT5 simulation preflight on continuously or "
            "near-continuously quoted engineering products. The default EURUSD/GBPUSD/USDJPY "
            "fixture validates transport, broker clock and current quote health only; it has "
            "no U.S. research-universe or US-D3 authority."
        )
    )
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--expected-package-version", default="5.0.6147")
    parser.add_argument(
        "--expected-broker-server",
        default="MetaQuotes-Demo",
        help=(
            "Exact broker server identity to bind into this preflight policy. "
            "Evidence from another server is rejected instead of inherited."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/mt5/mt5_simulation_all_day_preflight.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    symbols = _symbols(args.symbols)
    policy = MT5SimulationAllDayPreflightPolicy(
        expected_broker_server=args.expected_broker_server,
    )
    if symbols != policy.required_symbols:
        raise SystemExit(
            "all-day simulation preflight v1 requires exact symbols: "
            + ", ".join(policy.required_symbols)
        )

    mt5 = _module()
    observed_package = str(getattr(mt5, "__version__", "")).strip()
    if observed_package != args.expected_package_version:
        raise SystemExit(
            "MetaTrader5 package version mismatch: "
            f"observed={observed_package!r} expected={args.expected_package_version!r}"
        )
    if not mt5.initialize():
        raise SystemExit(f"mt5.initialize() failed: {mt5.last_error()}")

    try:
        account = mt5.account_info()
        if account is None:
            raise SystemExit(f"mt5.account_info() failed: {mt5.last_error()}")
        broker_server = str(account.server).strip()
        if not broker_server:
            raise SystemExit("MT5 terminal server is empty")

        clock_observations: list[MT5BrokerClockObservation] = []
        for symbol in symbols:
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

        continuous = build_mt5_continuous_quote_smoke_report(
            broker_server,
            symbols,
            inventory_rows,
            tick_rows,
            retrieved_at,
            clock,
            policy=MT5ContinuousQuoteSmokePolicy(
                minimum_symbol_count=policy.minimum_passed_symbol_count,
                maximum_quote_age_seconds=60,
                maximum_future_quote_skew_seconds=5,
            ),
        )
        report = build_mt5_simulation_all_day_preflight_report(continuous, policy=policy)
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
                "continuous_smoke_report_id": report.continuous_smoke.report_id,
                "passed": report.passed,
                "blockers": list(report.blockers),
                "passed_symbols": list(report.passed_symbols),
                "broker_server": report.continuous_smoke.broker_server,
                "clock_evidence_id": report.continuous_smoke.clock_evidence.evidence_id,
                "clock_offset_seconds": (
                    report.continuous_smoke.clock_evidence.inferred_offset_seconds
                ),
                "product_scope": "continuous_or_near_continuous_engineering_fixture",
                "engineering_fixture_authority": report.passed,
                "us_research_universe_authority": False,
                "us_d3_certification_authority": False,
                "execution_authority": False,
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

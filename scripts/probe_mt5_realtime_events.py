from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from finagent.brokers.mt5 import (
    FX_ENGINEERING_FIXTURE,
    MT5_FEED_REGIME_LANES,
    RECOMMENDED_MT5_PACKAGE_VERSION,
    MetaTrader5ReadOnlyClient,
    build_mt5_broker_clock_evidence,
    probe_mt5_capabilities,
)
from finagent.brokers.mt5.clock import MT5BrokerClockObservation
from finagent.brokers.mt5.realtime_adapter import (
    MT5RealtimeAdapterPolicy,
    MT5RealtimeMarketAdapter,
)
from finagent.realtime.events import CanonicalRealtimeEvent


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError(
            "timestamps must be timezone-aware ISO-8601 values"
        )
    return parsed.astimezone(UTC)


def _field(record: object, name: str, default: object = None) -> object:
    if isinstance(record, Mapping):
        return record.get(name, default)
    if hasattr(record, name):
        return getattr(record, name)
    try:
        return record[name]  # type: ignore[index]
    except (KeyError, IndexError, TypeError, ValueError):
        return default


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        item = getattr(value, "item", None)
        if callable(item):
            return _integer(item(), field_name)
        raise TypeError(f"{field_name} must be integer-like")
    return int(value)


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        item = getattr(value, "item", None)
        if callable(item):
            return _number(item(), field_name)
        raise TypeError(f"{field_name} must be numeric")
    return float(value)


def _epoch_msc(record: object) -> int:
    time_msc = _field(record, "time_msc")
    if time_msc is not None:
        parsed = _integer(time_msc, "tick.time_msc")
        if parsed > 0:
            return parsed
    raw_time = _field(record, "time")
    if raw_time is None:
        raise ValueError("clock reference tick has no time_msc/time")
    parsed_time = _integer(raw_time, "tick.time")
    if parsed_time <= 0:
        raise ValueError("clock reference tick time must be positive")
    return parsed_time * 1000


def _rows(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray, Mapping)) or not isinstance(value, Iterable):
        raise TypeError("MT5 rates response must be an iterable of rows")
    return tuple(value)


def _unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in values if item.strip()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Map read-only MT5 polling observations into canonical FinAgent realtime events. "
            "This is D1 engineering validation only: no symbol_select, order_send, market-book "
            "subscription, PAPER, or live authority."
        )
    )
    parser.add_argument(
        "--expected-package-version",
        default=RECOMMENDED_MT5_PACKAGE_VERSION,
    )
    parser.add_argument(
        "--feed-lane",
        choices=MT5_FEED_REGIME_LANES,
        default=FX_ENGINEERING_FIXTURE,
        help="Explicit feed lane. It is never inferred from symbol names or quote age.",
    )
    parser.add_argument(
        "--clock-reference-symbol",
        action="append",
        default=[],
        help="Active symbol used to infer broker clock; repeat at least three times.",
    )
    parser.add_argument(
        "--symbol",
        action="append",
        default=[],
        help="Symbol to emit as QuoteEvent; repeatable.",
    )
    parser.add_argument("--symbol-group", default="")
    parser.add_argument(
        "--bar-symbol",
        action="append",
        default=[],
        help="Optional symbol for a completed historical M1 event window; repeatable.",
    )
    parser.add_argument("--bar-start", type=_aware_datetime)
    parser.add_argument("--bar-end", type=_aware_datetime)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/mt5/mt5_realtime_adapter_report.json"),
    )
    parser.add_argument(
        "--clock-output",
        type=Path,
        default=Path("reports/mt5/mt5_realtime_broker_clock.json"),
    )
    parser.add_argument(
        "--capability-output",
        type=Path,
        default=Path("reports/mt5/mt5_realtime_capability_probe.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    clock_symbols = _unique(args.clock_reference_symbol) or (
        "EURUSD",
        "GBPUSD",
        "USDJPY",
    )
    if len(clock_symbols) < 3:
        raise SystemExit("at least three unique --clock-reference-symbol values are required")
    symbols = _unique(args.symbol) or clock_symbols
    bar_symbols = _unique(args.bar_symbol)
    if bool(args.bar_start) != bool(args.bar_end):
        raise SystemExit("--bar-start and --bar-end must be supplied together")
    if bar_symbols and (args.bar_start is None or args.bar_end is None):
        raise SystemExit("--bar-symbol requires --bar-start and --bar-end")
    if (args.bar_start is not None or args.bar_end is not None) and not bar_symbols:
        raise SystemExit("--bar-start/--bar-end require at least one --bar-symbol")
    if args.bar_start is not None and args.bar_end is not None and args.bar_end <= args.bar_start:
        raise SystemExit("--bar-end must be later than --bar-start")

    client = MetaTrader5ReadOnlyClient(
        expected_package_version=args.expected_package_version,
    )
    client.initialize()
    try:
        capability = probe_mt5_capabilities(
            client,
            symbol_group=args.symbol_group,
            probed_at=datetime.now(UTC),
        )
        server = capability.terminal.broker_server
        if not server:
            raise RuntimeError("connected MT5 account does not expose broker_server")

        observations: list[MT5BrokerClockObservation] = []
        for symbol in clock_symbols:
            tick = client.symbol_info_tick(symbol)
            retrieved_at = datetime.now(UTC)
            observations.append(
                MT5BrokerClockObservation(
                    symbol=symbol,
                    raw_broker_time_msc=_epoch_msc(tick),
                    retrieved_at_utc=retrieved_at,
                    bid=_number(_field(tick, "bid"), f"{symbol}.bid"),
                    ask=_number(_field(tick, "ask"), f"{symbol}.ask"),
                )
            )
        clock = build_mt5_broker_clock_evidence(
            server,
            tuple(observations),
            generated_at=datetime.now(UTC),
        )
        if not clock.passed:
            raise RuntimeError(
                "broker clock evidence failed: " + ", ".join(clock.blockers)
            )

        adapter = MT5RealtimeMarketAdapter(
            MT5RealtimeAdapterPolicy(
                broker_server=server,
                feed_lane=args.feed_lane,
            ),
            clock,
        )
        events: list[CanonicalRealtimeEvent] = [
            adapter.connection_event(capability, observed_at=datetime.now(UTC))
        ]
        for symbol in symbols:
            tick = client.symbol_info_tick(symbol)
            events.append(
                adapter.quote_event(
                    symbol,
                    tick,
                    received_at=datetime.now(UTC),
                )
            )

        if bar_symbols:
            assert args.bar_start is not None and args.bar_end is not None
            if args.bar_end > datetime.now(UTC) - timedelta(minutes=2):
                raise SystemExit(
                    "bar probe requires --bar-end at least two minutes in the past so v1 can "
                    "mark every emitted M1 bar complete without current-bar inference"
                )
            for symbol in bar_symbols:
                rates = _rows(client.copy_rates_range(symbol, args.bar_start, args.bar_end))
                received_at = datetime.now(UTC)
                for rate in rates:
                    events.append(
                        adapter.bar_event(
                            symbol,
                            rate,
                            received_at=received_at,
                            complete=True,
                            interval_seconds=60,
                        )
                    )

        report = adapter.build_report(
            capability,
            tuple(events),
            generated_at=datetime.now(UTC),
        )
    finally:
        client.shutdown()

    for path, payload in (
        (args.capability_output, capability.to_dict()),
        (args.clock_output, clock.to_dict()),
        (args.output, report.to_dict()),
    ):
        path = path.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "report_id": report.report_id,
                "capability_probe_id": capability.probe_id,
                "clock_evidence_id": clock.evidence_id,
                "broker_server": server,
                "feed_lane": args.feed_lane,
                "event_count": len(report.events),
                "passed": report.passed,
                "implementation_ready_for_mt5_m1_acceptance": report.passed,
                "us_market_source_authority": False,
                "live_market_data_authority": False,
                "execution_authority": False,
                "paper_authority": False,
                "status_authority": False,
                "stage_exit_authority": False,
                "live_capital_authority": False,
                "output": str(args.output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

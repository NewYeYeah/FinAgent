from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from finagent.brokers.mt5 import RECOMMENDED_MT5_PACKAGE_VERSION, MetaTrader5ReadOnlyClient
from finagent.data.minute_store import (
    DuckDBExecutionPolicy,
    DuckDBParquetMinuteStore,
    fetch_plan_rows,
    manifest_from_huggingface_snapshot,
)
from finagent.data.minute_transform import (
    CalendarSessionizedMinuteStore,
    load_trading_calendar_evidence_json,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.data.us_minute.reconciliation import (
    MinuteReferenceReconciliationPolicy,
    MinuteReferenceReconciliationReport,
    ReferenceMinuteBar,
    reconcile_reference_symbol,
)
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval

SOURCE_REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"
INVENTORY_ID = "us-minute-inventory-c2cbf682b456f97eb613ed65"
CLEANING_ID = "us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244"
CALENDAR_ID = "trading-calendar-03a9c29f566d6634aedbbbdc"


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _row_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    asdict = getattr(value, "_asdict", None)
    if callable(asdict):
        mapped = asdict()
        if isinstance(mapped, Mapping):
            return cast(Mapping[str, object], mapped)
    names = getattr(getattr(value, "dtype", None), "names", None)
    if names:
        return {str(name): value[name] for name in names}
    raise TypeError(f"MT5 row is not mapping/namedtuple/structured-row like: {type(value)!r}")


def _number(value: object, default: float | None = None) -> float | None:
    if value is None:
        return default
    item = getattr(value, "item", None)
    scalar = item() if callable(item) else value
    if isinstance(scalar, (bool, int, float, str, bytes, bytearray)):
        return float(scalar)
    raise TypeError(f"numeric value has unsupported type {type(value)!r}")


def _integer(value: object) -> int:
    number = _number(value)
    if number is None:
        raise ValueError("integer value is missing")
    return int(number)


def _final_mappings(document: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    materialization_raw = document.get("materialization")
    materialization = (
        materialization_raw if isinstance(materialization_raw, Mapping) else document
    )
    mappings_raw = materialization.get("mappings")
    if not isinstance(mappings_raw, Sequence) or isinstance(
        mappings_raw,
        (str, bytes, bytearray),
    ):
        raise TypeError("engineering universe materialization must contain mappings[]")
    pairs: list[tuple[str, str]] = []
    for raw in mappings_raw:
        if not isinstance(raw, Mapping):
            raise TypeError("mapping row must be an object")
        if str(raw.get("status", "")).strip() != "accepted_for_engineering":
            continue
        research = raw.get("research")
        broker = raw.get("broker")
        if not isinstance(research, Mapping) or not isinstance(broker, Mapping):
            raise TypeError("mapping research/broker payload must be objects")
        research_symbol = str(research.get("source_symbol", "")).strip()
        broker_symbol = str(broker.get("broker_symbol", "")).strip()
        if research_symbol and broker_symbol:
            pairs.append((research_symbol, broker_symbol))
    if not pairs:
        raise ValueError("engineering universe contains no accepted mappings")
    return tuple(pairs)


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must be timezone-aware ISO-8601")
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare admitted research 1m bars with MT5 broker M1 reference bars. "
            "Timestamp/price disagreement is reported and never rewrites either source."
        )
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--engineering-universe", type=Path, required=True)
    parser.add_argument("--mt5-p0-probe", type=Path, required=True)
    parser.add_argument(
        "--start",
        type=_aware,
        default=_aware("2026-03-09T13:30:00+00:00"),
    )
    parser.add_argument(
        "--end",
        type=_aware,
        default=_aware("2026-03-09T20:00:00+00:00"),
    )
    parser.add_argument("--reference-symbol-count", type=int, default=4)
    parser.add_argument("--minimum-overlap-ratio", type=float, default=0.80)
    parser.add_argument("--maximum-abs-offset-minutes", type=int, default=360)
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--max-temp-directory-size", default="4GB")
    parser.add_argument(
        "--temp-directory",
        type=Path,
        default=Path("data/duckdb_temp/mt5_d0"),
    )
    parser.add_argument(
        "--expected-package-version",
        default=RECOMMENDED_MT5_PACKAGE_VERSION,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/mt5/mt5_d0_minute_reconciliation.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    p0_probe = _read_mapping(args.mt5_p0_probe)
    terminal = p0_probe.get("terminal")
    if not isinstance(terminal, Mapping):
        raise TypeError("MT5-P0 probe terminal must be an object")
    expected_server = str(terminal.get("broker_server", "")).strip()
    mt5_probe_id = str(p0_probe.get("probe_id", "")).strip()
    if not expected_server or not mt5_probe_id:
        raise ValueError("MT5-P0 probe is missing broker/probe identity")

    mappings = _final_mappings(_read_mapping(args.engineering_universe))
    mappings = mappings[: args.reference_symbol_count]
    if len(mappings) < args.reference_symbol_count:
        raise SystemExit(
            "final EngineeringUniverse has fewer mappings than required references"
        )

    policy = MinuteReferenceReconciliationPolicy(
        start=args.start,
        end=args.end,
        required_symbol_count=args.reference_symbol_count,
        minimum_rows_per_symbol=100,
        minimum_aligned_overlap_ratio=args.minimum_overlap_ratio,
        maximum_abs_offset_minutes=args.maximum_abs_offset_minutes,
    )
    calendar = load_trading_calendar_evidence_json(
        args.calendar,
        expected_calendar_id=CALENDAR_ID,
    )
    manifest = manifest_from_huggingface_snapshot(
        args.root,
        expected_revision=SOURCE_REVISION,
        expected_inventory_id=INVENTORY_ID,
        cleaning_identity=CLEANING_ID,
    )
    raw_store = DuckDBParquetMinuteStore(manifest)
    sessionized = CalendarSessionizedMinuteStore(raw_store, calendar)
    research_symbols = tuple(pair[0] for pair in mappings)
    query = MarketDataQuery(
        market_id="XNYS",
        assets=research_symbols,
        start=policy.start,
        end=policy.end,
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.CLOSE, MarketDataField.VOLUME),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.EVENT_TIME,
    )
    plan, _evidence = sessionized.plan(query)
    execution_policy = DuckDBExecutionPolicy(
        memory_limit=args.memory_limit,
        threads=args.threads,
        allow_temp_spill=True,
        max_temp_directory_size=args.max_temp_directory_size,
        preserve_insertion_order=False,
    )
    rows = fetch_plan_rows(
        plan,
        limit=100_000,
        policy=execution_policy,
        temp_directory=args.temp_directory,
    )
    research_by_symbol: dict[str, list[ReferenceMinuteBar]] = defaultdict(list)
    for row in rows:
        symbol = str(row["research_asset_id"])
        event_time = row["event_time"]
        if not isinstance(event_time, datetime):
            raise TypeError("sessionized event_time must materialize as datetime")
        research_by_symbol[symbol].append(
            ReferenceMinuteBar(
                timestamp=event_time,
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )

    client = MetaTrader5ReadOnlyClient(
        expected_package_version=args.expected_package_version
    )
    client.initialize()
    try:
        account = _row_mapping(client.account_info())
        observed_server = str(account.get("server", "")).strip()
        if observed_server != expected_server:
            raise RuntimeError(
                f"connected MT5 server mismatch: observed={observed_server!r}, "
                f"expected={expected_server!r}"
            )
        broker_start = policy.start - timedelta(
            minutes=policy.maximum_abs_offset_minutes
        )
        broker_end = policy.end + timedelta(minutes=policy.maximum_abs_offset_minutes)
        checks = []
        for research_symbol, broker_symbol in mappings:
            broker_raw = client.copy_rates_range(
                broker_symbol,
                broker_start,
                broker_end,
            )
            broker_bars: list[ReferenceMinuteBar] = []
            for raw in broker_raw:
                mapped = _row_mapping(raw)
                close = _number(mapped.get("close"))
                if close is None or close <= 0:
                    continue
                broker_bars.append(
                    ReferenceMinuteBar(
                        timestamp=datetime.fromtimestamp(
                            _integer(mapped.get("time")),
                            tz=UTC,
                        ),
                        close=close,
                        tick_volume=_number(mapped.get("tick_volume")),
                        real_volume=_number(mapped.get("real_volume")),
                    )
                )
            checks.append(
                reconcile_reference_symbol(
                    research_symbol,
                    broker_symbol,
                    tuple(research_by_symbol.get(research_symbol, ())),
                    tuple(broker_bars),
                    policy=policy,
                )
            )
    finally:
        client.shutdown()

    report = MinuteReferenceReconciliationReport(
        policy=policy,
        source_revision=manifest.source_revision,
        source_data_version=manifest.data_version,
        calendar_id=calendar.calendar_id,
        mt5_probe_id=mt5_probe_id,
        broker_server=expected_server,
        symbol_checks=tuple(checks),
        retrieved_at=datetime.now(UTC),
    )
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
                "symbol_checks": [
                    {
                        "research_symbol": item.research_symbol,
                        "broker_symbol": item.broker_symbol,
                        "best_offset_minutes": (
                            item.best_broker_to_research_offset_minutes
                        ),
                        "aligned_overlap_ratio": item.aligned_overlap_ratio,
                        "median_close_relative_difference": (
                            item.median_close_relative_difference
                        ),
                    }
                    for item in report.symbol_checks
                ],
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

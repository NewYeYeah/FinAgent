from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from finagent.brokers.mt5 import RECOMMENDED_MT5_PACKAGE_VERSION, MetaTrader5ReadOnlyClient
from finagent.brokers.mt5.clock import (
    MT5BrokerClockObservation,
    build_mt5_broker_clock_evidence,
)
from finagent.data.us_candidate_quotes_v2 import build_candidate_quote_probe_report_v2

DEFAULT_CLOCK_REFERENCE_SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY")


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _rows(value: object) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, bytearray, Mapping)) or not isinstance(
        value,
        Iterable,
    ):
        raise TypeError("MT5 symbol inventory must be an iterable of rows")
    return tuple(value)


def _row_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    asdict = getattr(value, "_asdict", None)
    if callable(asdict):
        mapped = asdict()
        if isinstance(mapped, Mapping):
            return cast(Mapping[str, object], mapped)
    raise TypeError(f"MT5 row is not mapping/namedtuple-like: {type(value)!r}")


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be integer-like")
    return int(value)


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be numeric")
    return float(value)


def _raw_time_msc(row: Mapping[str, object], field_name: str) -> int:
    raw_msc = row.get("time_msc")
    if raw_msc is not None:
        value = _integer(raw_msc, f"{field_name}.time_msc")
        if value > 0:
            return value
    seconds = _integer(row.get("time"), f"{field_name}.time")
    if seconds <= 0:
        raise ValueError(f"{field_name} timestamp must be positive")
    return seconds * 1000


def _requested_symbols(candidate: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(
        _text(item, "candidate.spread_probe_symbols[]")
        for item in _sequence(
            candidate.get("spread_probe_symbols"),
            "candidate.spread_probe_symbols",
        )
    )


def _clock_observation(
    symbol: str,
    tick: Mapping[str, object],
    retrieved_at: datetime,
) -> MT5BrokerClockObservation:
    return MT5BrokerClockObservation(
        symbol=symbol,
        raw_broker_time_msc=_raw_time_msc(tick, f"clock_tick[{symbol}]"),
        retrieved_at_utc=retrieved_at,
        bid=_number(tick.get("bid"), f"clock_tick[{symbol}].bid"),
        ask=_number(tick.get("ask"), f"clock_tick[{symbol}].ask"),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect broker-clock-normalized, row-free US-I0 quote evidence using only "
            "read-only MT5 surfaces. symbols_get supplies inventory/visibility and "
            "symbol_info_tick supplies current quote timestamps. No symbol_select/order "
            "or account mutation is used."
        )
    )
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--mt5-p0-probe", type=Path, required=True)
    parser.add_argument(
        "--expected-package-version",
        default=RECOMMENDED_MT5_PACKAGE_VERSION,
    )
    parser.add_argument(
        "--clock-reference-symbol",
        action="append",
        default=[],
        help=(
            "Active reference symbol used to infer the broker clock. Repeat at least "
            "three times to override the default EURUSD/GBPUSD/USDJPY references."
        ),
    )
    parser.add_argument(
        "--clock-output",
        type=Path,
        default=Path("reports/mt5/mt5_broker_clock_evidence.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_instruments/us_i0_candidate_quotes.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    candidate = _read_mapping(args.candidate_report)
    p0_probe = _read_mapping(args.mt5_p0_probe)
    requested = _requested_symbols(candidate)
    references = tuple(
        dict.fromkeys(args.clock_reference_symbol or DEFAULT_CLOCK_REFERENCE_SYMBOLS)
    )
    if len(references) < 3:
        raise SystemExit("broker clock inference requires at least three reference symbols")

    client = MetaTrader5ReadOnlyClient(
        expected_package_version=args.expected_package_version,
    )
    client.initialize()
    try:
        account = _row_mapping(client.account_info())
        expected_terminal = p0_probe.get("terminal")
        if not isinstance(expected_terminal, Mapping):
            raise TypeError("MT5-P0 probe terminal must be an object")
        expected_server = str(expected_terminal.get("broker_server", "")).strip()
        observed_server = str(account.get("server", "")).strip()
        if not expected_server or observed_server != expected_server:
            raise RuntimeError(
                "connected MT5 broker server does not match the accepted MT5-P0 probe: "
                f"observed={observed_server!r}, expected={expected_server!r}"
            )

        inventory_rows = tuple(_row_mapping(item) for item in _rows(client.symbols_get()))
        inventory_by_symbol = {
            _text(row.get("name", row.get("symbol")), "symbols_get[].name"): row
            for row in inventory_rows
        }

        clock_observations: list[MT5BrokerClockObservation] = []
        for symbol in references:
            try:
                tick = _row_mapping(client.symbol_info_tick(symbol))
                retrieved_at = datetime.now(UTC)
                clock_observations.append(
                    _clock_observation(symbol, tick, retrieved_at)
                )
            except (RuntimeError, TypeError, ValueError, OverflowError, OSError):
                continue

        clock_evidence = build_mt5_broker_clock_evidence(
            observed_server,
            tuple(clock_observations),
        )

        tick_rows: dict[str, Mapping[str, object] | None] = {}
        retrieved_at_by_symbol: dict[str, datetime] = {}
        for symbol in requested:
            inventory = inventory_by_symbol.get(symbol)
            if inventory is None:
                tick_rows[symbol] = None
                continue
            visible = inventory.get("visible") is True
            try:
                trade_mode = _integer(
                    inventory.get("trade_mode"),
                    f"symbols_get[{symbol}].trade_mode",
                )
            except (TypeError, ValueError):
                trade_mode = 0
            if not visible or trade_mode == 0:
                tick_rows[symbol] = None
                continue
            try:
                tick_rows[symbol] = _row_mapping(client.symbol_info_tick(symbol))
                retrieved_at_by_symbol[symbol] = datetime.now(UTC)
            except (RuntimeError, TypeError, ValueError, OverflowError, OSError):
                tick_rows[symbol] = None
    finally:
        client.shutdown()

    report = build_candidate_quote_probe_report_v2(
        candidate,
        p0_probe,
        inventory_rows,
        tick_rows,
        retrieved_at_by_symbol,
        clock_evidence,
    )

    clock_output = args.clock_output.expanduser().resolve()
    clock_output.parent.mkdir(parents=True, exist_ok=True)
    clock_output.write_text(
        json.dumps(clock_evidence.to_dict(), sort_keys=True, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
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
                "schema_version": report.schema_version,
                "ready_for_finalization": report.ready_for_finalization,
                "valid_quote_count": len(report.valid_quote_symbols),
                "missing_or_invalid_symbols": list(report.missing_or_invalid_symbols),
                "invalid_reason_counts": report.invalid_reason_counts,
                "broker_clock_evidence_id": clock_evidence.evidence_id,
                "broker_clock_passed": clock_evidence.passed,
                "broker_clock_offset_seconds": clock_evidence.inferred_offset_seconds,
                "broker_clock_maximum_abs_residual_seconds": (
                    clock_evidence.maximum_abs_residual_seconds
                ),
                "blockers": list(report.blockers),
                "clock_output": str(clock_output),
                "output": str(output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if report.ready_for_finalization else 2


if __name__ == "__main__":
    raise SystemExit(main())

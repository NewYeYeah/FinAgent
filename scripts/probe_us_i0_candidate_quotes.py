from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.brokers.mt5 import RECOMMENDED_MT5_PACKAGE_VERSION, MetaTrader5ReadOnlyClient
from finagent.data.us_universe_finalization import build_candidate_quote_probe_report


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
    raise TypeError(f"MT5 symbol row is not mapping/namedtuple-like: {type(value)!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect row-free current quote evidence for US-I0 candidates using only "
            "the read-only MT5 symbols_get surface. No symbol_select/order API is used."
        )
    )
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--mt5-p0-probe", type=Path, required=True)
    parser.add_argument(
        "--expected-package-version",
        default=RECOMMENDED_MT5_PACKAGE_VERSION,
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
        raw_symbols = client.symbols_get()
        rows = tuple(_row_mapping(item) for item in raw_symbols)
    finally:
        client.shutdown()

    report = build_candidate_quote_probe_report(candidate, p0_probe, rows)
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
                "ready_for_finalization": report.ready_for_finalization,
                "valid_quote_count": len(report.quotes),
                "missing_or_invalid_symbols": list(report.missing_or_invalid_symbols),
                "blockers": list(report.blockers),
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

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from finagent.brokers.mt5 import (
    RECOMMENDED_MT5_PACKAGE_VERSION,
    MetaTrader5MarketWatchClient,
)


def _report_id(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"mt5-market-watch-change-{hashlib.sha256(encoded).hexdigest()[:24]}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or add exact broker symbols to MT5 Market Watch. The command is "
            "add-only, uses an explicit per-run allowlist, and retains the funded-account "
            "trading lockout. It exposes no order, position, or symbol-removal operation."
        )
    )
    parser.add_argument(
        "--symbol",
        action="append",
        required=True,
        help="Exact broker symbol to inspect/add; repeatable and never normalized.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually add missing symbols. Without this flag the command is dry-run only.",
    )
    parser.add_argument(
        "--expected-package-version",
        default=RECOMMENDED_MT5_PACKAGE_VERSION,
    )
    parser.add_argument("--output", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    symbols = tuple(dict.fromkeys(symbol.strip() for symbol in args.symbol))
    if any(not symbol for symbol in symbols):
        raise SystemExit("--symbol values must be non-empty exact broker symbols")

    client = MetaTrader5MarketWatchClient(
        allowed_symbols=symbols,
        expected_package_version=args.expected_package_version,
    )
    changes: list[dict[str, object]] = []
    with client:
        for symbol in symbols:
            before = client.symbol_info(symbol)
            was_visible = bool(getattr(before, "visible", False))
            if args.apply:
                changes.append(client.ensure_visible(symbol).to_dict())
            else:
                changes.append(
                    {
                        "symbol": symbol,
                        "was_visible": was_visible,
                        "is_visible": was_visible,
                        "changed": False,
                    }
                )

    changed_count = sum(bool(item["changed"]) for item in changes)
    report = {
        "schema_version": "finagent.mt5-market-watch-change.v1",
        "mode": "apply" if args.apply else "dry_run",
        "add_only": True,
        "requested_symbols": list(symbols),
        "changes": changes,
        "changed_count": changed_count,
        "terminal_state_mutation": changed_count > 0,
        "order_send_authority": False,
        "order_check_authority": False,
        "position_query_authority": False,
        "execution_authority": False,
        "live_capital_authority": False,
        "stage_exit_authority": False,
    }
    report["report_id"] = _report_id(report)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()

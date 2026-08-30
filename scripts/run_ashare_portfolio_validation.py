#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.application import (
    PortfolioValidationOptions,
    load_toml_section,
    run_portfolio_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run reserve-safe A4 A-share execution-aware portfolio validation over "
            "a frozen A2.6 ResearchProgram. No reserve, promotion, PAPER or broker "
            "authority is granted."
        )
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("--a2p6-report", type=Path)
    parser.add_argument("--feature-store", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--frozen-report", type=Path)
    parser.add_argument("--assert-replay", action="store_true")
    parser.add_argument("--verify-content", action="store_true")
    args = parser.parse_args()
    if args.assert_replay and args.frozen_report is None:
        parser.error("--assert-replay requires --frozen-report")

    values = load_toml_section(args.config, "ashare_portfolio_validation")
    result = run_portfolio_validation(
        values,
        options=PortfolioValidationOptions(
            a2p6_report=args.a2p6_report,
            feature_store=args.feature_store,
            report=args.report,
            ledger=args.ledger,
            frozen_report=args.frozen_report,
            assert_replay=args.assert_replay,
            verify_content=args.verify_content,
        ),
    )
    print(json.dumps(result.payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

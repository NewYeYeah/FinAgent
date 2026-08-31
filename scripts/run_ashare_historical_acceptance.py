#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.runtime.ashare_historical_acceptance import AshareHistoricalAcceptanceConfig
from finagent.runtime.ashare_historical_acceptance_terminal import (
    run_ashare_historical_acceptance,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the A-C3 real A-share historical acceptance chain: certification → "
            "development research → A2.6 → A4 → V4 series → Historical Workbench → "
            "review bundle. A reviewed NO_ROBUST_FACTOR_FOUND → "
            "NO_ROBUST_FACTOR_FAMILY outcome is accepted as an explicit no-alpha "
            "terminal state rather than being converted into synthetic strategy/market "
            "evidence. This host-side command has no reserve, promotion, PAPER, broker "
            "or live-capital authority."
        )
    )
    parser.add_argument("config", type=Path)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="explicitly confirm the potentially long real historical research run",
    )
    args = parser.parse_args()

    config = AshareHistoricalAcceptanceConfig.read_toml(args.config)
    result = run_ashare_historical_acceptance(config, confirmed=args.confirm)
    print(json.dumps(result.payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result.accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())

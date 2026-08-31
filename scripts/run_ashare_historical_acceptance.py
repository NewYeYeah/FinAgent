#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.runtime.ashare_historical_acceptance import (
    AshareHistoricalAcceptanceConfig,
    AshareHistoricalAcceptanceRunner,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the A-C3 real A-share historical acceptance chain: certification → "
            "development research → A2.6 → A4 → V4 series → Historical Workbench → "
            "review bundle. This host-side command has no reserve, promotion, PAPER, "
            "broker or live-capital authority."
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
    runner = AshareHistoricalAcceptanceRunner(config, confirmed=args.confirm)
    result = runner.run()
    print(json.dumps(result.payload, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result.accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())

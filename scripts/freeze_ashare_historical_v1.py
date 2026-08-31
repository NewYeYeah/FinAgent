#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from finagent.runtime.ashare_historical_v1_freeze import HistoricalFreezeConfig
from finagent.runtime.ashare_historical_v1_freeze_lineage import (
    AshareHistoricalV1LineageFreezer,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze FinAgent A-share Historical v1.0 from accepted A-C3 and A-C4 "
            "evidence. The command writes release artifacts only; it does not run "
            "research, consume reserve data, promote a strategy or contact a broker."
        )
    )
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        default=Path("configs/acceptance/ashare_historical_v1_freeze.example.toml"),
    )
    parser.add_argument("--release-git-sha")
    args = parser.parse_args()

    config = HistoricalFreezeConfig.read_toml(args.config)
    if args.release_git_sha:
        config = replace(config, release_git_sha=args.release_git_sha)
    result = AshareHistoricalV1LineageFreezer(config).run()
    print(
        json.dumps(
            {
                "schema_version": "finagent.ashare-historical-v1-freeze-cli.v1",
                "freeze_id": result.payload.get("freeze_id"),
                "mode": config.mode,
                "contract_valid": result.contract_valid,
                "frozen": result.frozen,
                "json_report": str(result.json_path),
                "markdown_report": str(result.markdown_path),
                "package": str(result.package_path) if result.package_path else None,
                "package_sha256": result.package_sha256,
                "production_reserve_consumed": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    success = result.frozen if config.mode == "real_local_evidence" else result.contract_valid
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())

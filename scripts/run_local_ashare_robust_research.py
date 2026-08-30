#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.application import (
    RobustResearchOptions,
    load_toml_section,
    run_robust_research,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run A2.6 robust A-share expanding walk-forward research. "
            "The command never reads the 2025+ reserve, executes orders, promotes "
            "a model or starts PAPER/realtime operations."
        )
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--mode", choices=("deterministic", "agent"))
    parser.add_argument("--llm-profile")
    parser.add_argument("--frozen-report", type=Path)
    parser.add_argument("--assert-replay", action="store_true")
    parser.add_argument("--verify-content", action="store_true")
    args = parser.parse_args()
    if args.assert_replay and args.frozen_report is None:
        parser.error("--assert-replay requires --frozen-report")

    values = load_toml_section(args.config, "local_ashare_robust_research")
    result = run_robust_research(
        values,
        options=RobustResearchOptions(
            root=args.root,
            manifest=args.manifest,
            report=args.report,
            mode=args.mode,
            llm_profile=args.llm_profile,
            frozen_report=args.frozen_report,
            assert_replay=args.assert_replay,
            verify_content=args.verify_content,
        ),
    )
    print(json.dumps(result.payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.data import compare_provider_records, read_normalized_csv


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two normalized provider datasets on canonical symbol/session keys."
    )
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--left-provider", required=True)
    parser.add_argument("--right-provider", required=True)
    parser.add_argument("--close-abs-tolerance", type=float, default=1e-8)
    parser.add_argument("--close-rel-tolerance", type=float, default=1e-8)
    parser.add_argument("--volume-rel-tolerance", type=float, default=1e-6)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = compare_provider_records(
        args.left_provider,
        read_normalized_csv(args.left),
        args.right_provider,
        read_normalized_csv(args.right),
        close_abs_tolerance=args.close_abs_tolerance,
        close_rel_tolerance=args.close_rel_tolerance,
        volume_rel_tolerance=args.volume_rel_tolerance,
    )
    payload = json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

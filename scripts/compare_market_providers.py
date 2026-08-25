#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.data import compare_provider_records, read_normalized_csv


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two normalized FinAgent market datasets without reconciling them."
    )
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--left-provider", required=True)
    parser.add_argument("--right-provider", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = compare_provider_records(
        args.left_provider,
        read_normalized_csv(args.left),
        args.right_provider,
        read_normalized_csv(args.right),
    )
    payload = report.to_dict()
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

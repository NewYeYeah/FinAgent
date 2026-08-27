#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from finagent.data import (
    AshareBarFrequency,
    LocalAshareDatasetLayout,
    create_local_ashare_frozen_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze a local A-share vendor dataset into a verifiable manifest."
    )
    parser.add_argument("--root", type=Path, required=True, help="vendor A-share dataset root")
    parser.add_argument(
        "--frequency",
        action="append",
        default=[],
        choices=[item.value for item in AshareBarFrequency],
        help="frequency to include; default is 1d. Repeat for multiple frequencies.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="record file size/mtime only; default computes SHA-256 for every selected file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/manifests/local_ashare_frozen.json"),
    )
    args = parser.parse_args()

    frequencies = tuple(
        AshareBarFrequency(value) for value in (args.frequency or ["1d"])
    )
    layout = LocalAshareDatasetLayout(args.root)
    manifest = create_local_ashare_frozen_manifest(
        layout,
        frequencies=frequencies,
        content_hash=not args.fast,
    )
    manifest.write_json(args.output)
    print(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

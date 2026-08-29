#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from finagent.research.ashare_reserve import (
    ReserveEligibilitySealer,
    SQLiteReserveEligibilityStore,
)


def _git_identity(repo_root: Path) -> str:
    root = repo_root.resolve()
    sha = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=normal"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if dirty:
        raise PermissionError("A5 eligibility sealing requires a clean Git working tree")
    return sha


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create and persist the A5-1 ReserveEligibilitySeal for one exact frozen "
            "A2.6/A4 protocol. This command never opens or consumes reserve data."
        )
    )
    parser.add_argument("--a26-report", type=Path, required=True)
    parser.add_argument("--a26-replay", type=Path, required=True)
    parser.add_argument("--a4-report", type=Path, required=True)
    parser.add_argument("--a4-replay", type=Path, required=True)
    parser.add_argument("--a4-ledger", type=Path, required=True)
    parser.add_argument("--review-bundle", type=Path, required=True)
    parser.add_argument("--review-attestation", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--state-db",
        type=Path,
        default=Path(".finagent/a5/reserve_eligibility.sqlite"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    code_git_sha = _git_identity(args.repo_root)
    seal = ReserveEligibilitySealer().seal_from_paths(
        a26_report_path=args.a26_report,
        a26_replay_path=args.a26_replay,
        a4_report_path=args.a4_report,
        a4_replay_path=args.a4_replay,
        ledger_path=args.a4_ledger,
        review_bundle_path=args.review_bundle,
        review_attestation_path=args.review_attestation,
        code_git_sha=code_git_sha,
        created_at=datetime.now(tz=UTC),
    )
    SQLiteReserveEligibilityStore(args.state_db).register(seal)
    seal.write_json(args.output)
    print(seal.seal_id)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

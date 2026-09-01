#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class ReleaseTagSpec:
    release_id: str
    tag: str
    target: str


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
    )


def load_release_tags(root: Path) -> tuple[ReleaseTagSpec, ...]:
    status_path = root / "docs" / "status.toml"
    with status_path.open("rb") as handle:
        status = tomllib.load(handle)
    releases = status.get("release", {})
    if not isinstance(releases, dict):
        raise ValueError("docs/status.toml release table must be a mapping")
    specs: list[ReleaseTagSpec] = []
    for release_id, raw in releases.items():
        if not isinstance(raw, dict) or raw.get("status") != "accepted":
            continue
        tag = str(raw.get("tag", "")).strip()
        target = str(raw.get("tag_target", "")).strip().lower()
        if not TAG_RE.fullmatch(tag):
            raise ValueError(f"accepted release {release_id!r} has invalid tag {tag!r}")
        if not SHA_RE.fullmatch(target):
            raise ValueError(f"accepted release {release_id!r} has invalid tag_target {target!r}")
        specs.append(ReleaseTagSpec(str(release_id), tag, target))
    return tuple(specs)


def tag_commit(root: Path, tag: str) -> str | None:
    completed = _git(root, "rev-list", "-n", "1", tag, check=False)
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip().lower()
    return value or None


def sync_release_tags(root: Path, *, apply: bool, push: bool) -> tuple[str, ...]:
    messages: list[str] = []
    for spec in load_release_tags(root):
        _git(root, "cat-file", "-e", f"{spec.target}^{{commit}}")
        current = tag_commit(root, spec.tag)
        if current is not None:
            if current != spec.target:
                raise RuntimeError(
                    f"release tag {spec.tag!r} points to {current}, expected {spec.target}"
                )
            messages.append(f"verified {spec.tag} -> {spec.target}")
            continue
        if not apply:
            raise RuntimeError(f"missing accepted release tag {spec.tag!r}")
        _git(
            root,
            "tag",
            "-a",
            spec.tag,
            spec.target,
            "-m",
            f"FinAgent accepted release {spec.release_id}",
        )
        if push:
            _git(root, "push", "origin", f"refs/tags/{spec.tag}")
        messages.append(f"created {spec.tag} -> {spec.target}")
    return tuple(messages)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify or materialize accepted release tags")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()
    for message in sync_release_tags(
        args.root.resolve(),
        apply=args.apply,
        push=args.apply and not args.no_push,
    ):
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

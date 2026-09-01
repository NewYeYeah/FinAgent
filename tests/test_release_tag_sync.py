from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.sync_release_tags import load_release_tags, sync_release_tags


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


class ReleaseTagSyncTest(unittest.TestCase):
    def test_creates_and_verifies_expected_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp) / "repo"
            (root / "docs").mkdir(parents=True)
            _git(root, "init")
            _git(root, "config", "user.email", "release@example.invalid")
            _git(root, "config", "user.name", "Release Test")
            (root / "seed.txt").write_text("seed\n", encoding="utf-8")
            _git(root, "add", ".")
            _git(root, "commit", "-m", "seed")
            target = _git(root, "rev-parse", "HEAD")
            (root / "docs/status.toml").write_text(
                "\n".join(
                    [
                        '[release.demo]',
                        'status = "accepted"',
                        'tag = "demo-v1"',
                        f'tag_target = "{target}"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            specs = load_release_tags(root)
            self.assertEqual(len(specs), 1)
            self.assertEqual(specs[0].target, target)
            self.assertEqual(
                sync_release_tags(root, apply=True, push=False),
                (f"created demo-v1 -> {target}",),
            )
            self.assertEqual(_git(root, "rev-list", "-n", "1", "demo-v1"), target)
            self.assertEqual(
                sync_release_tags(root, apply=False, push=False),
                (f"verified demo-v1 -> {target}",),
            )


if __name__ == "__main__":
    unittest.main()

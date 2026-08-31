from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import finagent.runtime.historical_workbench_release_smoke as base
import finagent.runtime.historical_workbench_release_smoke_acceptance as acceptance
from finagent.runtime.historical_workbench_release_smoke import (
    HistoricalWorkbenchReleaseSmokeConfig,
)

ROOT = Path(__file__).resolve().parents[1]


def test_protected_worktree_guard_collects_unstaged_staged_and_untracked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_git(
        _root: Path,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del check
        prefix = args[:3]
        if prefix == ("diff", "--name-only", "--"):
            stdout = "workspace/package.json\n"
        elif args[:4] == ("diff", "--cached", "--name-only", "--"):
            stdout = "workspace/src/App.tsx\n"
        elif args[:4] == ("ls-files", "--others", "--exclude-standard", "--"):
            stdout = "workspace/src/local-only.ts\n"
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(base, "_git", fake_git)

    assert acceptance._protected_worktree_changes(ROOT) == (
        "workspace/package.json",
        "workspace/src/App.tsx",
        "workspace/src/local-only.ts",
    )


def test_real_release_fails_closed_on_dirty_protected_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = cast(
        HistoricalWorkbenchReleaseSmokeConfig,
        SimpleNamespace(mode="real_frozen_release", repository_root=ROOT),
    )
    monkeypatch.setattr(
        acceptance,
        "_protected_worktree_changes",
        lambda _root: ("workspace/package.json",),
    )

    with pytest.raises(
        ValueError,
        match=r"clean protected Workbench product paths.*workspace/package.json",
    ):
        acceptance.HistoricalWorkbenchReleaseSmoke(config).prepare()

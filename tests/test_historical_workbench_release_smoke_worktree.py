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


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _commit(root: Path, message: str) -> str:
    _git(root, "add", ".")
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _product_repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    (root / "workspace/src/workbench").mkdir(parents=True)
    (root / "workspace/src/test").mkdir(parents=True)
    (root / "workspace/src/App.tsx").write_text("export const app = 1;\n", encoding="utf-8")
    (root / "workspace/src/App.test.tsx").write_text("test('app', () => {});\n", encoding="utf-8")
    (root / "workspace/src/workbench/context.test.tsx").write_text(
        "test('context', () => {});\n",
        encoding="utf-8",
    )
    (root / "workspace/src/test/setup.ts").write_text("export {};\n", encoding="utf-8")
    _git(root, "init")
    _git(root, "config", "user.email", "hw1@example.invalid")
    _git(root, "config", "user.name", "HW1 Test")
    baseline = _commit(root, "baseline")
    return root, baseline


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


def test_test_only_workspace_sources_do_not_count_as_committed_product_drift(
    tmp_path: Path,
) -> None:
    root, baseline = _product_repo(tmp_path)
    (root / "workspace/src/App.test.tsx").write_text("test('app changed', () => {});\n", encoding="utf-8")
    (root / "workspace/src/workbench/context.test.tsx").write_text(
        "test('context changed', () => {});\n",
        encoding="utf-8",
    )
    (root / "workspace/src/test/setup.ts").write_text("export const setup = true;\n", encoding="utf-8")
    tests_only = _commit(root, "tests only")

    assert base._workbench_product_drift(
        root,
        freeze_sha=baseline,
        smoke_sha=tests_only,
    ) == ()

    (root / "workspace/src/App.tsx").write_text("export const app = 2;\n", encoding="utf-8")
    product_change = _commit(root, "product change")
    assert base._workbench_product_drift(
        root,
        freeze_sha=tests_only,
        smoke_sha=product_change,
    ) == ("workspace/src/App.tsx",)


def test_test_only_workspace_sources_do_not_dirty_real_product_guard(
    tmp_path: Path,
) -> None:
    root, _baseline = _product_repo(tmp_path)
    (root / "workspace/src/App.test.tsx").write_text("test('dirty test', () => {});\n", encoding="utf-8")
    (root / "workspace/src/test/setup.ts").write_text("export const dirty = true;\n", encoding="utf-8")

    assert acceptance._protected_worktree_changes(root) == ()

    (root / "workspace/src/App.tsx").write_text("export const app = 3;\n", encoding="utf-8")
    assert acceptance._protected_worktree_changes(root) == ("workspace/src/App.tsx",)


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

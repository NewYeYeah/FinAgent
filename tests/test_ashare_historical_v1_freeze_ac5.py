from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from finagent.data.local_ashare_freeze import FrozenLocalFile, LocalAshareFrozenManifest
from finagent.runtime.ashare_historical_acceptance import (
    AC3_ACCEPTANCE_SCHEMA,
    AC3_REQUIRED_COMMANDS,
)
from finagent.runtime.ashare_historical_v1_freeze import (
    AC5_FREEZE_SCHEMA,
    AshareHistoricalV1Freezer,
    HistoricalFreezeConfig,
    HistoricalFreezeMode,
    recompute_ac3_acceptance_id,
)
from finagent.runtime.initial_requirement_compliance import (
    run_initial_requirement_compliance_audit,
)

ROOT = Path(__file__).resolve().parents[1]
AC4_MANIFEST = ROOT / "configs/acceptance/ashare_initial_requirement_compliance_ac4.toml"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _artifact(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _fixture_file(tmp_path: Path, role: str, *, empty: bool = False) -> Path:
    path = tmp_path / f"{role}.fixture"
    path.write_bytes(b"" if empty else f"{role} fixture\n".encode())
    return path


def _write_dataset_manifest(tmp_path: Path) -> LocalAshareFrozenManifest:
    manifest = LocalAshareFrozenManifest(
        files=(
            FrozenLocalFile(
                relative_path="stock_daily.parquet",
                size=123,
                mtime_ns=0,
                sha256="a" * 64,
            ),
        ),
        frequencies=("1d",),
        created_at=datetime(2026, 8, 31, tzinfo=UTC),
        content_hashed=True,
    )
    manifest.write_json(tmp_path / "local_ashare_daily.json")
    return manifest


def _write_ac4(tmp_path: Path, git_sha: str) -> Path:
    report = tmp_path / "ac4.json"
    audit = run_initial_requirement_compliance_audit(
        AC4_MANIFEST,
        repository_root=ROOT,
        git_sha=git_sha,
    )
    audit.write_json(report)
    return report


def _write_ac3(
    tmp_path: Path,
    *,
    git_sha: str,
    data_version: str,
    no_alpha: bool,
) -> Path:
    certification = tmp_path / "certification.json"
    certification.write_text(
        json.dumps({"schema_version": "fixture.certification.v1"}) + "\n",
        encoding="utf-8",
    )
    review = tmp_path / "review.zip"
    with zipfile.ZipFile(review, "w") as archive:
        archive.writestr("README.txt", "contract fixture\n")

    identities: dict[str, object] = {
        "development_acceptance_id": "development-fixture",
        "program_result_id": "program-fixture",
        "portfolio_validation_id": "a4-fixture",
        "strategy_series_id": "strategy-fixture",
        "factor_series_id": "factor-fixture",
        "market_bar_series_id": None if no_alpha else "market-bars-fixture",
        "data_version": data_version,
    }
    checks = {
        "development_reserve_untouched": True,
        "robust_reserve_untouched": True,
        "a4_reserve_untouched": True,
        "fixture_contract": True,
    }
    artifacts: dict[str, object] = {
        "development": _artifact(_fixture_file(tmp_path, "development")),
        "robust": _artifact(_fixture_file(tmp_path, "robust")),
        "a4": _artifact(_fixture_file(tmp_path, "a4")),
        "a4_ledger": _artifact(_fixture_file(tmp_path, "a4-ledger", empty=no_alpha)),
        "factor_manifest": _artifact(_fixture_file(tmp_path, "factor-manifest")),
        "strategy_manifest": _artifact(_fixture_file(tmp_path, "strategy-manifest")),
        "review_bundle": _artifact(review),
        "command_store": _artifact(_fixture_file(tmp_path, "command-store")),
        "market_bar_manifest": None,
    }
    # The current no-alpha A-C3 payload does not place certification in artifacts;
    # A-C5 must recover it from the real application-service `output_path` instead.
    if not no_alpha:
        artifacts["certification"] = _artifact(certification)
        artifacts["market_bar_manifest"] = _artifact(
            _fixture_file(tmp_path, "market-bar-manifest")
        )

    command_runs: dict[str, object] = {}
    for command_id in AC3_REQUIRED_COMMANDS:
        command_runs[command_id] = {
            "ok": True,
            "command_run_id": f"{command_id}-fixture-run",
            "evidence_ids": [],
            "outputs": {},
        }
    certification_run = cast(
        dict[str, object],
        command_runs["data.certify_local_ashare"],
    )
    certification_run["command_run_id"] = "certify-fixture-run"
    certification_run["outputs"] = {"output_path": str(certification.resolve())}

    payload: dict[str, object] = {
        "schema_version": AC3_ACCEPTANCE_SCHEMA,
        "stage": "A-C3",
        "mode": "ci_contract_fixture",
        "contract_valid": True,
        "accepted": False,
        "real_dataset_attested": False,
        "git_sha": git_sha,
        "data": {
            "dataset_version": data_version,
            "content_hashed": True,
            "content_verified": False,
        },
        "identities": identities,
        "checks": checks,
        "command_runs": command_runs,
        "artifacts": artifacts,
    }
    if no_alpha:
        payload["terminal_state"] = "NO_ROBUST_FACTOR_FAMILY"
    payload["acceptance_id"] = recompute_ac3_acceptance_id(payload)
    report = tmp_path / ("ac3-no-alpha.json" if no_alpha else "ac3-populated.json")
    report.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _config(
    tmp_path: Path,
    *,
    ac3: Path,
    ac4: Path,
    dataset_manifest: Path,
    git_sha: str,
    suffix: str,
    mode: str = "ci_contract_fixture",
) -> HistoricalFreezeConfig:
    return HistoricalFreezeConfig(
        config_path=tmp_path / "unused.toml",
        repository_root=ROOT,
        ac3_report=ac3,
        ac4_report=ac4,
        ac4_manifest=AC4_MANIFEST,
        frozen_dataset_manifest=dataset_manifest,
        output_json=tmp_path / f"freeze-{suffix}.json",
        output_markdown=tmp_path / f"freeze-{suffix}.md",
        output_package=tmp_path / f"freeze-{suffix}.zip",
        environment_files=(
            ROOT / "pyproject.toml",
            ROOT / "workspace/package-lock.json",
        ),
        mode=cast(HistoricalFreezeMode, mode),
        release_git_sha=git_sha,
        require_clean_tracked_worktree=True,
    )


@pytest.mark.parametrize("no_alpha", [False, True])
def test_ac5_ci_contract_fixture_never_claims_real_freeze(
    tmp_path: Path,
    no_alpha: bool,
) -> None:
    git_sha = _git_sha()
    manifest = _write_dataset_manifest(tmp_path)
    ac4 = _write_ac4(tmp_path, git_sha)
    ac3 = _write_ac3(
        tmp_path,
        git_sha=git_sha,
        data_version=manifest.dataset_version,
        no_alpha=no_alpha,
    )
    config = _config(
        tmp_path,
        ac3=ac3,
        ac4=ac4,
        dataset_manifest=tmp_path / "local_ashare_daily.json",
        git_sha=git_sha,
        suffix="first",
    )

    result = AshareHistoricalV1Freezer(config).run()

    assert result.contract_valid is True
    assert result.frozen is False
    assert result.payload["schema_version"] == AC5_FREEZE_SCHEMA
    assert result.payload["production_reserve"] == {
        "historical_closure_consumed": False,
        "promotion_eligible": False,
        "paper_enabled_by_freeze": False,
        "live_capital_enabled_by_freeze": False,
    }
    ac3_summary = result.payload["ac3"]
    assert isinstance(ac3_summary, dict)
    assert ac3_summary["research_outcome"] == (
        "NO_ROBUST_FACTOR_FAMILY" if no_alpha else "POPULATED_STRATEGY"
    )
    assert ac3_summary["certification_command_run_id"] == "certify-fixture-run"
    assert ac3_summary["certification_evidence_ids"] == []
    assert ac3_summary["certification_artifact_sha256"]
    command_run_ids = ac3_summary["command_run_ids"]
    assert isinstance(command_run_ids, dict)
    assert set(command_run_ids) == set(AC3_REQUIRED_COMMANDS)
    assert result.package_path is not None and result.package_path.is_file()
    assert result.package_sha256 == _sha256(result.package_path)


def test_ac5_freeze_and_package_identity_are_deterministic(tmp_path: Path) -> None:
    git_sha = _git_sha()
    manifest = _write_dataset_manifest(tmp_path)
    ac4 = _write_ac4(tmp_path, git_sha)
    ac3 = _write_ac3(
        tmp_path,
        git_sha=git_sha,
        data_version=manifest.dataset_version,
        no_alpha=True,
    )
    first = AshareHistoricalV1Freezer(
        _config(
            tmp_path,
            ac3=ac3,
            ac4=ac4,
            dataset_manifest=tmp_path / "local_ashare_daily.json",
            git_sha=git_sha,
            suffix="one",
        )
    ).run()
    second = AshareHistoricalV1Freezer(
        _config(
            tmp_path,
            ac3=ac3,
            ac4=ac4,
            dataset_manifest=tmp_path / "local_ashare_daily.json",
            git_sha=git_sha,
            suffix="two",
        )
    ).run()

    assert first.payload == second.payload
    assert first.payload["freeze_id"] == second.payload["freeze_id"]
    assert first.package_sha256 == second.package_sha256


def test_ac5_real_mode_rejects_ci_ac3_evidence(tmp_path: Path) -> None:
    git_sha = _git_sha()
    manifest = _write_dataset_manifest(tmp_path)
    ac4 = _write_ac4(tmp_path, git_sha)
    ac3 = _write_ac3(
        tmp_path,
        git_sha=git_sha,
        data_version=manifest.dataset_version,
        no_alpha=True,
    )
    config = _config(
        tmp_path,
        ac3=ac3,
        ac4=ac4,
        dataset_manifest=tmp_path / "local_ashare_daily.json",
        git_sha=git_sha,
        suffix="real",
        mode="real_local_evidence",
    )

    with pytest.raises(ValueError, match="real_local_dataset"):
        AshareHistoricalV1Freezer(config).run()


def test_ac5_rejects_tampered_ac4_or_ac3_identity(tmp_path: Path) -> None:
    git_sha = _git_sha()
    manifest = _write_dataset_manifest(tmp_path)
    ac4 = _write_ac4(tmp_path, git_sha)
    ac3 = _write_ac3(
        tmp_path,
        git_sha=git_sha,
        data_version=manifest.dataset_version,
        no_alpha=False,
    )

    ac4_payload = json.loads(ac4.read_text(encoding="utf-8"))
    ac4_payload["summary"]["PASS"] += 1
    ac4.write_text(json.dumps(ac4_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly replay"):
        AshareHistoricalV1Freezer(
            _config(
                tmp_path,
                ac3=ac3,
                ac4=ac4,
                dataset_manifest=tmp_path / "local_ashare_daily.json",
                git_sha=git_sha,
                suffix="tampered-ac4",
            )
        ).run()

    ac4 = _write_ac4(tmp_path, git_sha)
    ac3_payload = json.loads(ac3.read_text(encoding="utf-8"))
    ac3_payload["acceptance_id"] = "ashare-historical-ac3-tampered"
    ac3.write_text(json.dumps(ac3_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="acceptance_id"):
        AshareHistoricalV1Freezer(
            _config(
                tmp_path,
                ac3=ac3,
                ac4=ac4,
                dataset_manifest=tmp_path / "local_ashare_daily.json",
                git_sha=git_sha,
                suffix="tampered-ac3",
            )
        ).run()


def test_ac5_rejects_missing_required_ac3_artifact_or_command_run(
    tmp_path: Path,
) -> None:
    git_sha = _git_sha()
    manifest = _write_dataset_manifest(tmp_path)
    ac4 = _write_ac4(tmp_path, git_sha)
    ac3 = _write_ac3(
        tmp_path,
        git_sha=git_sha,
        data_version=manifest.dataset_version,
        no_alpha=False,
    )
    config = _config(
        tmp_path,
        ac3=ac3,
        ac4=ac4,
        dataset_manifest=tmp_path / "local_ashare_daily.json",
        git_sha=git_sha,
        suffix="denominator",
    )

    payload = json.loads(ac3.read_text(encoding="utf-8"))
    del payload["artifacts"]["a4_ledger"]
    ac3.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="required release artifacts"):
        AshareHistoricalV1Freezer(config).run()

    ac3 = _write_ac3(
        tmp_path,
        git_sha=git_sha,
        data_version=manifest.dataset_version,
        no_alpha=False,
    )
    config = _config(
        tmp_path,
        ac3=ac3,
        ac4=ac4,
        dataset_manifest=tmp_path / "local_ashare_daily.json",
        git_sha=git_sha,
        suffix="command-denominator",
    )
    payload = json.loads(ac3.read_text(encoding="utf-8"))
    del payload["command_runs"]["research.run_a2p6"]
    ac3.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(TypeError, match="must be a mapping"):
        AshareHistoricalV1Freezer(config).run()

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

import finagent.runtime.historical_workbench_release_smoke as smoke_module
from finagent.runtime.historical_workbench_release_smoke import (
    HistoricalWorkbenchReleaseSmoke,
    HistoricalWorkbenchReleaseSmokeConfig,
    recompute_ac5_freeze_id,
)

ROOT = Path(__file__).resolve().parents[1]


def _git_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _descriptor(path: Path, role: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "path": str(path.resolve()),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }
    if role is not None:
        payload.update({"role": role, "logical_name": path.name})
    return payload


def _fake_app(*, validation_id: str, strategy_id: str, factor_id: str, program_result_id: str, config_count: int = 0) -> FastAPI:
    app = FastAPI()

    @app.get("/api/v3/workbench/status")
    def status() -> dict[str, object]:
        return {
            "read_only": True,
            "evidence_plane": True,
            "control_plane_enabled": False,
            "config_descriptor_count": config_count,
        }

    strategy_item = SimpleNamespace(
        series_id=strategy_id,
        portfolio_validation_id=validation_id,
        row_count=0,
        session_count=0,
        asset_count=0,
        start_date=None,
        end_date=None,
    )

    class Strategy:
        @staticmethod
        def by_portfolio(value: str):
            if value != validation_id:
                raise KeyError(value)
            return strategy_item

        @staticmethod
        def dimensions(_series: str) -> dict[str, object]:
            return {"assets": [], "folds": [], "session_count": 0}

        @staticmethod
        def market_bar_binding(_series: str):
            return None

    class Factors:
        @staticmethod
        def catalog() -> dict[str, object]:
            return {
                "items": [
                    {
                        "series_id": factor_id,
                        "program_result_id": program_result_id,
                        "factor_count": 5,
                    }
                ]
            }

    class PortfolioExecution:
        @staticmethod
        def catalog() -> dict[str, object]:
            return {"items": []}

    class WorkspaceV2:
        @staticmethod
        def portfolio_cockpit(value: str) -> dict[str, object]:
            assert value == validation_id
            return {"no_portfolio": True}

    class Linked:
        @staticmethod
        def status() -> dict[str, object]:
            return {
                "accepted": True,
                "browser_recomputation": False,
                "missing_evidence_policy": "explicit_unavailable_not_inferred",
            }

    app.state.strategy_explorer = Strategy()
    app.state.factor_tearsheet = Factors()
    app.state.portfolio_execution = PortfolioExecution()
    app.state.workspace_v2 = WorkspaceV2()
    app.state.linked_analytics_acceptance = Linked()
    return app


def _fixture(tmp_path: Path, *, real: bool = False) -> tuple[HistoricalWorkbenchReleaseSmokeConfig, dict[str, object]]:
    git_sha = _git_sha()
    validation_id = "hw1-validation"
    strategy_id = "hw1-strategy"
    factor_id = "hw1-factor-series"
    program_result_id = "hw1-program-result"

    evidence: dict[str, object] = {}
    for role, name in (
        ("robust", "robust.json"),
        ("a4", "a4.json"),
        ("factor_manifest", "factor-series.json"),
        ("strategy_manifest", "strategy-series.json"),
        ("command_store", "commands.sqlite"),
    ):
        path = tmp_path / name
        path.write_text(f"{role}\n", encoding="utf-8")
        evidence[role] = _descriptor(path)

    identities = {
        "development_acceptance_id": "hw1-development",
        "program_result_id": program_result_id,
        "portfolio_validation_id": validation_id,
        "strategy_series_id": strategy_id,
        "factor_series_id": factor_id,
        "market_bar_series_id": None,
        "data_version": "hw1-data",
    }
    ac3 = {
        "schema_version": "finagent.ashare-historical-acceptance.v1",
        "acceptance_id": "hw1-ac3-acceptance",
        "stage": "A-C3",
        "mode": "real_local_dataset" if real else "ci_contract_fixture",
        "contract_valid": True,
        "accepted": real,
        "real_dataset_attested": real,
        "identities": identities,
        "artifacts": evidence,
    }
    ac3_path = tmp_path / "ac3.json"
    ac3_path.write_text(json.dumps(ac3, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    freeze: dict[str, object] = {
        "schema_version": "finagent.ashare-historical-v1-freeze.v1",
        "release_name": "FinAgent A-share Historical v1.0",
        "release_git_sha": git_sha,
        "mode": "real_local_evidence" if real else "ci_contract_fixture",
        "ac3": {
            "acceptance_id": ac3["acceptance_id"],
            "research_outcome": "NO_ROBUST_FACTOR_FAMILY",
            "identities": identities,
        },
        "ac4_audit_id": "hw1-ac4",
        "deferred_capabilities": [],
        "artifacts": [_descriptor(ac3_path, "ac3_acceptance")],
        "reserve": {
            "historical_closure_consumed": False,
            "promotion_implied": False,
        },
        "stage": "A-C5",
        "contract_valid": True,
        "frozen": real,
        "production_reserve": {
            "historical_closure_consumed": False,
            "promotion_eligible": False,
            "paper_enabled_by_freeze": False,
            "live_capital_enabled_by_freeze": False,
        },
    }
    freeze["freeze_id"] = recompute_ac5_freeze_id(freeze)
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(
        json.dumps(freeze, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    package = tmp_path / "freeze.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "release/freeze/finagent_ashare_historical_v1_freeze.json",
            freeze_path.read_bytes(),
        )
        archive.writestr(
            "release/ac3/ashare_historical_acceptance_ac3.json",
            ac3_path.read_bytes(),
        )

    config = HistoricalWorkbenchReleaseSmokeConfig(
        config_path=tmp_path / "unused.toml",
        repository_root=ROOT,
        freeze_report=freeze_path,
        freeze_package=package,
        ac3_report=ac3_path,
        config_roots=(),
        frontend_dir=ROOT / "workspace/dist",
        output_json=tmp_path / "smoke.json",
        output_markdown=tmp_path / "smoke.md",
        mode="real_frozen_release" if real else "ci_contract_fixture",
        smoke_git_sha=git_sha,
        host="127.0.0.1",
        port=8765,
        build_frontend=False,
        run_browser=True,
    )
    return config, {
        "validation_id": validation_id,
        "strategy_id": strategy_id,
        "factor_id": factor_id,
        "program_result_id": program_result_id,
    }


def test_hw1_ci_contract_validates_no_alpha_projection_but_cannot_accept_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, ids = _fixture(tmp_path)
    monkeypatch.setattr(
        smoke_module,
        "create_workspace_app",
        lambda **_kwargs: _fake_app(
            validation_id=str(ids["validation_id"]),
            strategy_id=str(ids["strategy_id"]),
            factor_id=str(ids["factor_id"]),
            program_result_id=str(ids["program_result_id"]),
        ),
    )

    smoke = HistoricalWorkbenchReleaseSmoke(config)
    prepared = smoke.prepare()
    result = smoke.finalize(prepared, browser_status="passed")

    assert result.contract_valid is True
    assert result.accepted is False
    assert result.payload["research_outcome"] == "NO_ROBUST_FACTOR_FAMILY"
    checks = result.payload["checks"]
    assert isinstance(checks, dict) and all(checks.values())
    assert result.json_path.is_file()
    assert result.markdown_path.is_file()


def test_hw1_real_release_requires_actual_browser_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, ids = _fixture(tmp_path, real=True)
    monkeypatch.setattr(
        smoke_module,
        "create_workspace_app",
        lambda **_kwargs: _fake_app(
            validation_id=str(ids["validation_id"]),
            strategy_id=str(ids["strategy_id"]),
            factor_id=str(ids["factor_id"]),
            program_result_id=str(ids["program_result_id"]),
            config_count=1,
        ),
    )
    smoke = HistoricalWorkbenchReleaseSmoke(config)
    prepared = smoke.prepare()

    not_run = smoke.finalize(prepared, browser_status="not_run")
    passed = smoke.finalize(prepared, browser_status="passed")

    assert not_run.contract_valid is True
    assert not_run.accepted is False
    assert passed.accepted is True


def test_hw1_rejects_tampered_freeze_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, ids = _fixture(tmp_path)
    monkeypatch.setattr(
        smoke_module,
        "create_workspace_app",
        lambda **_kwargs: _fake_app(
            validation_id=str(ids["validation_id"]),
            strategy_id=str(ids["strategy_id"]),
            factor_id=str(ids["factor_id"]),
            program_result_id=str(ids["program_result_id"]),
        ),
    )
    with zipfile.ZipFile(config.freeze_package, "w") as archive:
        archive.writestr(
            "release/freeze/finagent_ashare_historical_v1_freeze.json",
            json.dumps({"tampered": True}),
        )
        archive.writestr(
            "release/ac3/ashare_historical_acceptance_ac3.json",
            config.ac3_report.read_bytes(),
        )

    with pytest.raises(ValueError, match="package freeze record differs"):
        HistoricalWorkbenchReleaseSmoke(config).prepare()


def test_hw1_product_drift_denominator_allows_only_additive_smoke_code() -> None:
    current = _git_sha()
    assert smoke_module._workbench_product_drift(
        ROOT,
        freeze_sha=current,
        smoke_sha=current,
    ) == ()

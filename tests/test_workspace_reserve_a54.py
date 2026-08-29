from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from finagent.research.ashare_reserve_lifecycle import ReserveConsumptionClaim
from finagent.research.ashare_reserve_runner import AshareReserveOneShotRunner
from finagent.visualization.workspace_api import create_workspace_app
from tests.test_ashare_reserve_runner_a5 import FakeEngine, _runner


def _app(tmp_path: Path, *, execute: bool = True):
    runner, terminal_store, seal, a26, a4 = _runner(tmp_path, FakeEngine())
    if execute:
        runner.run(
            seal=seal,
            a26_report=a26,
            a4_report=a4,
            runtime_code_git_sha="a5-runtime-sha",
            actor="human-operator",
        )
    app = create_workspace_app(
        report_paths=(tmp_path,),
        frontend_dir=None,
        git_sha="a5-runtime-sha",
        reserve_eligibility_path=runner.eligibility_store.path,
        reserve_consumption_path=runner.consumption_store.path,
        reserve_terminal_path=terminal_store.path,
    )
    return TestClient(app), runner, terminal_store, seal


def test_a54_projects_governance_reserve_detail_and_ledger_are_integrated(tmp_path: Path) -> None:
    client, runner, terminal_store, seal = _app(tmp_path)
    paths = (runner.eligibility_store.path, runner.consumption_store.path, terminal_store.path)
    before = {path: (path.stat().st_mtime_ns, path.stat().st_size) for path in paths}

    health = client.get("/api/v1/health").json()
    assert health["reserve_lifecycle"]["available"] == {
        "eligibility": True,
        "consumption": True,
        "terminal": True,
    }

    reserves = client.get("/api/v2/reserves")
    assert reserves.status_code == 200
    item = reserves.json()["items"][0]
    assert item["reserve_id"] == seal.reserve_id
    assert item["state"] == "CONSUMED"
    assert item["a5_status"] == "RESERVE_PASS"
    assert item["integrity"]["status"] == "PASS"
    assert item["integrity"]["fully_audited"] is True
    assert item["automatic_retry_allowed"] is False
    assert item["ledger"]["available"] is True
    assert item["ledger"]["row_count"] == 2
    assert {node["evidence_type"] for node in item["lineage"]["nodes"]} == {
        "ReserveEligibilitySeal",
        "ReserveConsumptionClaim",
        "ReserveTerminalEvidence",
        "ReserveConsumptionAudit",
    }

    detail = client.get(f"/api/v2/reserves/{seal.reserve_id}")
    assert detail.status_code == 200
    assert detail.json()["terminal"]["consumed_state_persistence"] == "DURABLE_PRE_ACCESS_V1"
    assert detail.json()["claim"]["state"] == "CONSUMED"

    ledger = client.get(f"/api/v2/reserves/{seal.reserve_id}/ledger")
    assert ledger.status_code == 200
    assert ledger.json()["row_count"] == 2
    assert ledger.json()["file_sha256"] == detail.json()["ledger"]["file_sha256"]

    projects = client.get("/api/v2/projects").json()["items"]
    project = next(value for value in projects if value["a4_validation_id"] == seal.portfolio_validation_id)
    assert project["reserve"]["status"] == "CONSUMED"
    assert project["reserve"]["frozen_report_status"] == "untouched"
    assert project["a5_status"] == "RESERVE_PASS"
    assert project["reserve_lifecycle"]["integrity"]["status"] == "PASS"

    governance = client.get(f"/api/v2/governance/{seal.portfolio_validation_id}")
    assert governance.status_code == 200
    assert governance.json()["reserve_status"] == "CONSUMED"
    assert governance.json()["reserve_lifecycle"]["a5_status"] == "RESERVE_PASS"

    assert client.post(f"/api/v2/reserves/{seal.reserve_id}").status_code == 405
    assert client.post(f"/api/v2/reserves/{seal.reserve_id}/ledger").status_code == 405
    after = {path: (path.stat().st_mtime_ns, path.stat().st_size) for path in paths}
    assert before == after


def test_a54_consumed_without_terminal_is_visible_but_never_retried(tmp_path: Path) -> None:
    client, runner, _, seal = _app(tmp_path, execute=False)
    claim = ReserveConsumptionClaim(
        execution_id=AshareReserveOneShotRunner.execution_id(seal),
        seal_id=seal.seal_id,
        reserve_id=seal.reserve_id,
        program_result_id=seal.program_result_id,
        portfolio_validation_id=seal.portfolio_validation_id,
        protocol_digest=seal.protocol_digest,
        runtime_code_git_sha="a5-runtime-sha",
        authorized_by="human-operator",
        claimed_at=datetime(2026, 8, 29, 4, 0, tzinfo=UTC),
    )
    runner.consumption_store.claim(claim)

    detail = client.get(f"/api/v2/reserves/{seal.reserve_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["state"] == "CONSUMED"
    assert payload["a5_status"] == "CONSUMED_INTERRUPTED"
    assert payload["terminal"] is None
    assert payload["automatic_retry_allowed"] is False
    assert payload["integrity"]["status"] == "INCOMPLETE"
    assert client.get(f"/api/v2/reserves/{seal.reserve_id}/ledger").status_code == 404


def test_a54_tampered_ledger_fails_closed(tmp_path: Path) -> None:
    client, _, terminal_store, seal = _app(tmp_path)
    with sqlite3.connect(terminal_store.path) as connection:
        connection.execute(
            "UPDATE reserve_terminal_artifacts SET ledger_bytes=?",
            (b'{}\n',),
        )

    assert client.get("/api/v2/reserves").status_code == 409
    assert client.get(f"/api/v2/reserves/{seal.reserve_id}").status_code == 409
    assert client.get("/api/v2/projects").status_code == 409

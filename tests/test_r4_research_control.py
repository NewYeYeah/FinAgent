from __future__ import annotations

from fastapi.testclient import TestClient

from finagent.agents.audit import SQLiteAgentAuditStore
from finagent.application.research_controller import ResearchSessionService
from finagent.visualization.workbench_control_api import create_control_app
from tests.r4_controller_fixture import ScriptedProvider, action, admission_fixture, fixture_policy
from tests.test_workbench_control_api_v32c import _await_terminal


def test_unadmitted_provider_explicitly_denied_and_no_mutating_get(tmp_path):
    with TestClient(
        create_control_app(
            config_paths=(),
            report_paths=(),
            store_path=tmp_path / "commands.sqlite",
            export_dir=tmp_path / "exports",
        )
    ) as client:
        status = client.get("/api/v3/control/research/status").json()
        assert status["provider_available"] is False
        assert client.get("/api/v3/control/research/runs").status_code == 405
        request = {"request_id": "human-request", "objective": "Investigate an admitted hypothesis"}
        response = client.post("/api/v3/control/research/runs", json=request)
        assert response.status_code == 503
        assert response.json()["state"] == "rejected"
        assert (
            client.post(
                "/api/v3/control/research/runs", json={**request, "objective": "   "}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v3/control/research/runs", json={**request, "evaluate_portfolio": True}
            ).status_code
            == 422
        )


def test_control_plane_starts_existing_runtime_once_and_binds_objective(tmp_path):
    admission, _ = admission_fixture(tmp_path / "inputs")
    provider = ScriptedProvider(
        [
            action(
                "finalize_candidate",
                recommendation="none",
                factor_set_id=None,
                allocator_proposal_id=None,
                experiment_ids=[],
                decision="No candidate: Control Plane engineering fixture.",
            )
        ]
    )
    audit = SQLiteAgentAuditStore(tmp_path / "audit.sqlite")
    service = ResearchSessionService(
        admission,
        tmp_path / "sessions",
        audit,
        lambda: provider,
        provider_id="scripted-offline",
        model_id="fixture",
        policy=fixture_policy(),
    )
    with TestClient(
        create_control_app(
            config_paths=(),
            report_paths=(),
            store_path=tmp_path / "commands.sqlite",
            export_dir=tmp_path / "exports",
            research_service=service,
        )
    ) as client:
        request = {
            "request_id": "human-objective-request",
            "objective": "Inspect bounded development evidence",
        }
        accepted = client.post("/api/v3/control/research/runs", json=request)
        assert accepted.status_code == 202
        payload = accepted.json()
        terminal = _await_terminal(client, payload["command_run_id"])
        assert terminal["run"]["state"] == "succeeded", terminal
        again = client.post("/api/v3/control/research/runs", json=request).json()
        assert again["command_run_id"] == payload["command_run_id"]
        assert len(provider.requests) == 1
        assert audit.get_run_context(payload["run_id"]).metadata["controller"] == "r4"
        assert request["objective"] in provider.requests[0].context_json
        assert (
            client.post(
                "/api/v3/control/research/runs",
                json={**request, "objective": "Change frozen request"},
            ).status_code
            == 409
        )

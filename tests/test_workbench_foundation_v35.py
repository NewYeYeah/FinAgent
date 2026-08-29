from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from finagent.visualization.workbench_api import create_workspace_app
from finagent.visualization.workbench_control_api import create_control_app
from finagent.visualization.workbench_control_catalog import (
    ConfigRegistry,
    default_command_catalog,
)
from finagent.visualization.workbench_streams import (
    CommandRunStreamProjection,
    WorkbenchSseEvent,
    WorkbenchStreamProjection,
    _stream_events,
)


_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_FORBIDDEN_AUTHORITY = {
    "production_reserve",
    "strategy_promotion",
    "paper_mutation",
    "broker_order",
    "live_capital",
    "arbitrary_shell",
    "arbitrary_python",
}


def _write_public_config(root: Path) -> tuple[Path, str]:
    config_root = root / "configs"
    config_root.mkdir(parents=True)
    (config_root / "local.toml").write_text(
        """
[local_ashare]
root = "D:/Data/A-Share"
basic_filename = "stock_basic_data.parquet"
daily_filename = "stock_daily.parquet"
sample_frequency = "1min"
sample_symbol = "000001.SZ"
sample_date = 2009-01-05
report_path = "reports/local_ashare_certification.json"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    snapshot = ConfigRegistry((config_root,)).snapshots("local_ashare")[0]
    return config_root, snapshot.snapshot_id


def _api_routes(app: FastAPI) -> tuple[APIRoute, ...]:
    return tuple(
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/")
    )


def _await_terminal(client: TestClient, command_run_id: str) -> dict[str, object]:
    for _ in range(200):
        response = client.get(f"/api/v3/control/runs/{command_run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["run"]["state"] in {"succeeded", "failed", "rejected"}:
            return payload
        time.sleep(0.01)
    raise AssertionError("CommandRun did not reach a terminal state")


def _sse_payload(text: str) -> dict[str, object]:
    line = next(value for value in text.splitlines() if value.startswith("data: "))
    payload = json.loads(line.removeprefix("data: "))
    assert isinstance(payload, dict)
    return payload


class _RequestStub:
    def __init__(
        self,
        *,
        headers: dict[str, str] | None = None,
        disconnected: bool = False,
    ) -> None:
        self.headers = headers or {}
        self._disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self._disconnected


async def _collect_stream(
    *,
    request: _RequestStub,
    projection: CommandRunStreamProjection,
    loader: Callable[[], CommandRunStreamProjection],
) -> list[str]:
    output: list[str] = []
    stream: AsyncIterator[str] = _stream_events(  # type: ignore[arg-type]
        request,
        initial=projection,
        loader=loader,
        event_builder=WorkbenchStreamProjection.event_for_command,
        poll_seconds=0.0,
        heartbeat_seconds=60.0,
    )
    async for frame in stream:
        output.append(frame)
    return output


def _planned_projection() -> CommandRunStreamProjection:
    return CommandRunStreamProjection(
        command_run_id="command-run-v35",
        command_id="config.validate",
        state="planned",
        config_snapshot_id="config-snapshot-v35",
        context={"project_id": "project-v35"},
        requested_by="acceptance-user",
        started_at=None,
        finished_at=None,
        updated_at="2026-08-30T00:00:00+08:00",
        result_status=None,
        evidence_ids=(),
        latest_event={
            "event_id": "command-event-v35",
            "sequence": 1,
            "event_type": "RUN_PLANNED",
            "state": "planned",
            "occurred_at": "2026-08-30T00:00:00+08:00",
        },
        terminal=False,
    )


def test_v35_two_plane_route_inventory_and_generic_authority_are_bounded(
    tmp_path: Path,
) -> None:
    config_root, _ = _write_public_config(tmp_path)
    command_store = tmp_path / "workbench" / "commands.sqlite"

    evidence_app = create_workspace_app(
        report_paths=(),
        config_paths=(config_root,),
        command_store_path=command_store,
        frontend_dir=None,
    )
    control_app = create_control_app(
        config_paths=(config_root,),
        report_paths=(tmp_path / "reports",),
        store_path=command_store,
        export_dir=tmp_path / "exports",
        requested_by="acceptance-user",
        max_workers=1,
    )

    evidence_routes = _api_routes(evidence_app)
    assert evidence_routes
    assert all(
        not (_MUTATION_METHODS & set(route.methods or ()))
        for route in evidence_routes
    )
    assert not any(route.path.startswith("/api/v3/control/") for route in evidence_routes)

    control_routes = _api_routes(control_app)
    post_routes = {
        route.path
        for route in control_routes
        if "POST" in set(route.methods or ())
    }
    assert post_routes == {"/api/v3/control/runs"}
    assert all(
        not ({"PUT", "PATCH", "DELETE"} & set(route.methods or ()))
        for route in control_routes
    )
    assert not any(
        token in route.path.lower()
        for route in control_routes
        for token in ("reserve", "promotion", "paper", "broker", "live")
    )

    catalog = default_command_catalog().to_dict()
    assert set(catalog["forbidden_authority"]) == _FORBIDDEN_AUTHORITY
    assert all(item["level"] in {"L0", "L1"} for item in catalog["items"])
    assert not any(
        token in str(item["command_id"]).lower()
        for item in catalog["items"]
        for token in ("reserve", "promote", "paper", "broker", "live")
    )

    with TestClient(control_app) as control:
        status = control.get("/api/v3/control/status")
        assert status.status_code == 200
        assert set(status.json()["forbidden_authority"]) == _FORBIDDEN_AUTHORITY
        assert status.json()["local_only"] is True
        assert status.json()["remote_binding_supported"] is False

        blocked_commands = (
            "reserve.execute",
            "strategy.promote",
            "paper.rebalance",
            "broker.submit_order",
            "live.deploy",
            "python.exec",
        )
        for index, command_id in enumerate(blocked_commands):
            response = control.post(
                "/api/v3/control/runs",
                json={
                    "request_id": f"blocked-v35-{index:02d}",
                    "command_id": command_id,
                    "context": {},
                    "confirmed": True,
                },
            )
            assert response.status_code == 422
            assert response.json()["run"]["state"] == "rejected"
            assert "allowlisted catalog" in response.json()["result"]["message"]

        records = control.get("/api/v3/control/runs?limit=100").json()["items"]
        assert len(records) == len(blocked_commands)
        assert all(item["run"]["state"] == "rejected" for item in records)

    assert not (tmp_path / "eligibility.sqlite").exists()
    assert not (tmp_path / "consumption.sqlite").exists()
    assert not (tmp_path / "terminal.sqlite").exists()


def test_v35_cross_plane_command_identity_is_durable_and_evidence_read_only(
    tmp_path: Path,
) -> None:
    config_root, snapshot_id = _write_public_config(tmp_path)
    command_store = tmp_path / "workbench" / "commands.sqlite"

    evidence_app = create_workspace_app(
        report_paths=(),
        config_paths=(config_root,),
        command_store_path=command_store,
        frontend_dir=None,
    )
    evidence = TestClient(evidence_app)
    initial_status = evidence.get("/api/v3/streams/status").json()
    assert initial_status["command_store_configured"] is True
    assert initial_status["command_store_available"] is False

    control_app = create_control_app(
        config_paths=(config_root,),
        report_paths=(tmp_path / "reports",),
        store_path=command_store,
        export_dir=tmp_path / "exports",
        requested_by="acceptance-user",
        max_workers=1,
    )
    with TestClient(control_app) as control:
        submitted = control.post(
            "/api/v3/control/runs",
            json={
                "request_id": "foundation-v35-config-validate",
                "command_id": "config.validate",
                "config_snapshot_id": snapshot_id,
                "context": {
                    "project_id": "project-v35",
                    "environment": "research",
                },
            },
        )
        assert submitted.status_code in {200, 202}
        run_id = submitted.json()["run"]["command_run_id"]
        terminal = _await_terminal(control, run_id)
        assert terminal["run"]["state"] == "succeeded"
        assert terminal["intent"]["config_snapshot_id"] == snapshot_id
        assert terminal["intent"]["context"] == {
            "environment": "research",
            "project_id": "project-v35",
        }

    assert command_store.is_file()
    before_mtime = command_store.stat().st_mtime_ns

    live_status = evidence.get("/api/v3/streams/status")
    assert live_status.status_code == 200
    assert live_status.json()["command_store_available"] is True

    projection = evidence.get(f"/api/v3/command-runs/{run_id}")
    assert projection.status_code == 200
    assert projection.json()["state"] == "succeeded"
    assert projection.json()["config_snapshot_id"] == snapshot_id

    reference = evidence.get(f"/api/v3/refs/command_run/{run_id}")
    assert reference.status_code == 200
    related = {(item["kind"], item["identity"]) for item in reference.json()["related"]}
    assert ("config_snapshot", snapshot_id) in related

    stream = evidence.get(f"/api/v3/streams/command-runs/{run_id}?once=true")
    assert stream.status_code == 200
    payload = _sse_payload(stream.text)
    assert payload["identity"] == run_id
    stream_projection = payload["projection"]
    assert isinstance(stream_projection, dict)
    assert stream_projection["state"] == "succeeded"
    assert stream_projection["terminal"] is True
    for forbidden in (
        "parameters",
        "outputs",
        "artifact_paths",
        "message",
        "shell",
        "python",
    ):
        assert forbidden not in json.dumps(stream_projection, sort_keys=True).lower()

    assert evidence.post(f"/api/v3/command-runs/{run_id}").status_code == 405
    assert evidence.post(f"/api/v3/refs/command_run/{run_id}").status_code == 405
    assert evidence.post(f"/api/v3/streams/command-runs/{run_id}").status_code == 405
    assert evidence.post("/api/v3/control/runs", json={}).status_code == 404
    assert command_store.stat().st_mtime_ns == before_mtime


def test_v35_sse_reconnect_disconnect_and_source_disappearance_are_bounded() -> None:
    projection = _planned_projection()
    event_builder: Callable[[CommandRunStreamProjection], WorkbenchSseEvent] = (
        WorkbenchStreamProjection.event_for_command
    )
    event_id = event_builder(projection).event_id

    def missing_source() -> CommandRunStreamProjection:
        raise FileNotFoundError("source disappeared")

    first = asyncio.run(
        _collect_stream(
            request=_RequestStub(),
            projection=projection,
            loader=missing_source,
        )
    )
    assert len(first) == 1
    assert f"id: {event_id}" in first[0]
    assert "event: command_run_snapshot" in first[0]

    replay_suppressed = asyncio.run(
        _collect_stream(
            request=_RequestStub(headers={"last-event-id": event_id}),
            projection=projection,
            loader=missing_source,
        )
    )
    assert replay_suppressed == []

    disconnected = asyncio.run(
        _collect_stream(
            request=_RequestStub(disconnected=True),
            projection=projection,
            loader=lambda: projection,
        )
    )
    assert disconnected == []

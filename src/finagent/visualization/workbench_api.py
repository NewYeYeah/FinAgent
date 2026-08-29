from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from finagent.application import (
    APPLICATION_SERVICE_BINDINGS,
    default_application_service_registry,
)

from .semantic import EvidenceContractError
from .workbench_control_catalog import ConfigRegistry, default_command_catalog
from .workbench_links import WorkbenchLinkProjection
from .workspace_api import create_workspace_app as create_evidence_app

WORKBENCH_API_VERSION = "finagent-workbench-api-v3.3"


def _attach_frontend(app: FastAPI, frontend_dir: str | Path | None) -> None:
    if frontend_dir is None:
        return
    static_root = Path(frontend_dir).expanduser()
    if not static_root.is_dir():
        return
    assets = static_root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="workspace-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def workbench_frontend(full_path: str, request: Request):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        requested = (static_root / full_path).resolve()
        try:
            requested.relative_to(static_root.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="not found") from exc
        if requested.is_file():
            return FileResponse(requested)
        index = static_root / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Workspace frontend has not been built",
                "request_path": request.url.path,
            },
        )


def create_workspace_app(
    *,
    report_paths: Sequence[str | Path] = ("reports",),
    config_paths: Sequence[str | Path] = ("configs",),
    agent_audit_path: str | Path | None = None,
    command_store_path: str | Path | None = None,
    frontend_dir: str | Path | None = "workspace/dist",
    git_sha: str = "",
    catalog_db_path: str | Path | None = None,
    reserve_eligibility_path: str | Path | None = None,
    reserve_consumption_path: str | Path | None = None,
    reserve_terminal_path: str | Path | None = None,
    cors_origins: Sequence[str] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ),
) -> FastAPI:
    """Compose the immutable Evidence Plane with V3 Workbench read models.

    V3-3 adds typed, fail-closed deep links across Agent, evidence, factors,
    ResearchPrograms, A4/A5, public ConfigSnapshots/ConfigDiffs and durable
    CommandRuns. The Evidence Plane remains GET-only. It opens the optional command
    store with SQLite read-only mode and never instantiates the mutable command store.
    """

    app = create_evidence_app(
        report_paths=report_paths,
        agent_audit_path=agent_audit_path,
        frontend_dir=None,
        git_sha=git_sha,
        catalog_db_path=catalog_db_path,
        reserve_eligibility_path=reserve_eligibility_path,
        reserve_consumption_path=reserve_consumption_path,
        reserve_terminal_path=reserve_terminal_path,
        cors_origins=cors_origins,
    )
    config_registry = ConfigRegistry(config_paths)
    command_catalog = default_command_catalog()
    service_registry = default_application_service_registry(config_registry)
    catalog_ready_bindings = {
        spec.command_id: spec.binding_ref
        for spec in command_catalog.specs
        if spec.gateway_readiness == "application_service_ready"
    }
    if catalog_ready_bindings != APPLICATION_SERVICE_BINDINGS:
        raise RuntimeError(
            "command catalog application-service bindings do not match "
            "the application service registry contract"
        )
    catalog_ready_commands = tuple(sorted(catalog_ready_bindings))
    if catalog_ready_commands != service_registry.command_ids():
        raise RuntimeError(
            "command catalog application_service_ready entries do not match "
            "registered application services"
        )

    links = WorkbenchLinkProjection(
        catalog=app.state.catalog,
        v2=app.state.workspace_v2,
        config_registry=config_registry,
        reserve_projection=app.state.reserve_projection,
        report_paths=report_paths,
        agent_audit_path=agent_audit_path,
        command_store_path=command_store_path,
    )

    app.state.config_registry = config_registry
    app.state.command_catalog = command_catalog
    app.state.application_service_ready_commands = catalog_ready_commands
    app.state.workbench_links = links
    app.state.command_store_path = (
        Path(command_store_path).expanduser() if command_store_path else None
    )
    app.state.control_plane_enabled = False

    @app.get("/api/v3/workbench/status")
    def get_v3_workbench_status() -> dict[str, object]:
        projection = config_registry.projection
        return {
            "schema_version": "finagent.workbench.status.v1",
            "version": WORKBENCH_API_VERSION,
            "read_only": True,
            "evidence_plane": True,
            "control_plane_enabled": False,
            "command_execution_enabled": False,
            "control_plane_separate": True,
            "deep_links": links.status(),
            "config_descriptor_count": len(projection.descriptors),
            "config_snapshot_count": len(projection.snapshots),
            "config_warning_count": len(projection.warnings),
            "command_spec_count": len(command_catalog.specs),
            "application_service_ready_command_count": len(catalog_ready_commands),
            "application_service_ready_commands": list(catalog_ready_commands),
        }

    @app.get("/api/v3/deep-links/status")
    def get_v3_deep_link_status() -> dict[str, object]:
        return links.status()

    @app.get("/api/v3/refs/{kind}/{identity}")
    def get_v3_reference(kind: str, identity: str) -> dict[str, object]:
        try:
            return links.resolve(kind, identity).to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Workbench reference not found") from exc
        except EvidenceContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (FileNotFoundError, sqlite3.Error) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/v3/artifacts/{artifact_id}")
    def get_v3_artifact(artifact_id: str) -> dict[str, object]:
        try:
            return links.artifacts.inspect(artifact_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="artifact not found") from exc

    @app.get("/api/v3/command-runs")
    def get_v3_command_runs(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, object]:
        try:
            return links.command_run_list(limit=limit)
        except (FileNotFoundError, sqlite3.Error) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/v3/command-runs/{command_run_id}")
    def get_v3_command_run(command_run_id: str) -> dict[str, object]:
        if not links.command_runs.configured:
            raise HTTPException(status_code=404, detail="command store is not configured")
        if not links.command_runs.available:
            raise HTTPException(status_code=503, detail="command store is unavailable")
        try:
            return links.command_runs.get(command_run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="command run not found") from exc
        except sqlite3.Error as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/v3/config")
    def get_v3_config_registry() -> dict[str, object]:
        return config_registry.projection.to_dict()

    @app.get("/api/v3/config/descriptors")
    def get_v3_config_descriptors() -> dict[str, object]:
        projection = config_registry.projection
        return {
            "schema_version": "finagent.workbench.config-descriptors.v1",
            "read_only": True,
            "items": [item.to_dict() for item in projection.descriptors],
            "warnings": list(projection.warnings),
        }

    @app.get("/api/v3/config/descriptors/{descriptor_id}")
    def get_v3_config_descriptor(descriptor_id: str) -> dict[str, object]:
        try:
            descriptor = config_registry.descriptor(descriptor_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="config descriptor not found",
            ) from exc
        return descriptor.to_dict()

    @app.get("/api/v3/config/snapshots")
    def get_v3_config_snapshots(descriptor_id: str | None = None) -> dict[str, object]:
        try:
            snapshots = config_registry.snapshots(descriptor_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="config descriptor not found",
            ) from exc
        return {
            "schema_version": "finagent.workbench.config-snapshots.v1",
            "read_only": True,
            "items": [item.to_dict() for item in snapshots],
        }

    @app.get("/api/v3/config/snapshots/{snapshot_id}")
    def get_v3_config_snapshot(snapshot_id: str) -> dict[str, object]:
        try:
            return config_registry.snapshot(snapshot_id).to_dict()
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="config snapshot not found",
            ) from exc

    @app.get("/api/v3/config/diff")
    def get_v3_config_diff(left: str, right: str) -> dict[str, object]:
        try:
            return config_registry.diff(left, right).to_dict()
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="config snapshot not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v3/commands")
    def get_v3_command_catalog() -> dict[str, object]:
        return command_catalog.to_dict()

    @app.get("/api/v3/commands/{command_id}")
    def get_v3_command(command_id: str) -> dict[str, object]:
        try:
            return command_catalog.get(command_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="command not found") from exc

    _attach_frontend(app, frontend_dir)
    return app


def create_app_from_environment() -> FastAPI:
    raw_reports = os.environ.get("FINAGENT_WORKSPACE_REPORTS", "reports")
    report_paths = tuple(value for value in raw_reports.split(os.pathsep) if value)
    raw_configs = os.environ.get("FINAGENT_WORKBENCH_CONFIGS", "configs")
    config_paths = tuple(value for value in raw_configs.split(os.pathsep) if value)
    agent_audit = os.environ.get("FINAGENT_WORKSPACE_AGENT_AUDIT") or None
    command_store = os.environ.get("FINAGENT_WORKSPACE_COMMAND_STORE") or None
    frontend = os.environ.get("FINAGENT_WORKSPACE_FRONTEND", "workspace/dist") or None
    git_sha = os.environ.get("FINAGENT_WORKSPACE_GIT_SHA", "")
    catalog_db = os.environ.get("FINAGENT_WORKSPACE_CATALOG_DB") or None
    reserve_eligibility = os.environ.get(
        "FINAGENT_WORKSPACE_RESERVE_ELIGIBILITY"
    ) or None
    reserve_consumption = os.environ.get(
        "FINAGENT_WORKSPACE_RESERVE_CONSUMPTION"
    ) or None
    reserve_terminal = os.environ.get("FINAGENT_WORKSPACE_RESERVE_TERMINAL") or None
    return create_workspace_app(
        report_paths=report_paths,
        config_paths=config_paths,
        agent_audit_path=agent_audit,
        command_store_path=command_store,
        frontend_dir=frontend,
        git_sha=git_sha,
        catalog_db_path=catalog_db,
        reserve_eligibility_path=reserve_eligibility,
        reserve_consumption_path=reserve_consumption,
        reserve_terminal_path=reserve_terminal,
    )

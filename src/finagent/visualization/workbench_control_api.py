from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from finagent.application import (
    APPLICATION_SERVICE_BINDINGS,
    ApplicationCommandInvocation,
    default_application_service_registry,
)
from finagent.application.command_store import SQLiteCommandStore

from .workbench_control_catalog import ConfigRegistry, default_command_catalog

CONTROL_API_VERSION = "finagent-workbench-control-api-v3.2"
_CONTROL_CONTEXT_KEYS = {
    "project_id",
    "thread_id",
    "run_id",
    "program_id",
    "factor_id",
    "portfolio_validation_id",
    "strategy_id",
    "reserve_id",
    "asset_id",
    "date_range",
    "session_date",
    "fold_id",
    "environment",
}
_SAFE_ID_PATTERN = r"^[A-Za-z0-9._:-]+$"
_SAFE_ID = re.compile(_SAFE_ID_PATTERN)


class ControlRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: Annotated[
        str,
        Field(min_length=8, max_length=128, pattern=_SAFE_ID_PATTERN),
    ]
    command_id: Annotated[
        str,
        Field(min_length=1, max_length=128, pattern=_SAFE_ID_PATTERN),
    ]
    config_snapshot_id: Annotated[str, Field(min_length=1, max_length=160)] | None = None
    context: dict[str, Annotated[str, Field(max_length=512)]] = Field(
        default_factory=dict
    )
    confirmed: bool = False
    validation_id: Annotated[
        str,
        Field(min_length=1, max_length=160, pattern=_SAFE_ID_PATTERN),
    ] | None = None


class ControlCommandRunner:
    """Background in-process runner over exact application-service identities."""

    def __init__(
        self,
        *,
        store: SQLiteCommandStore,
        config_registry: ConfigRegistry,
        report_paths: Sequence[str | Path],
        export_dir: str | Path,
        max_workers: int = 2,
    ) -> None:
        self._store = store
        self._configs = config_registry
        self._catalog = default_command_catalog()
        self._services = default_application_service_registry(config_registry)
        self._report_paths = tuple(
            str(Path(value).expanduser()) for value in report_paths
        )
        self._export_dir = Path(export_dir).expanduser()
        self._export_dir.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, min(int(max_workers), 4)),
            thread_name_prefix="finagent-control",
        )
        self._futures: set[Future[None]] = set()

    @property
    def service_ids(self) -> tuple[str, ...]:
        return self._services.command_ids()

    def submit(self, command_run_id: str) -> None:
        future = self._executor.submit(self._execute, command_run_id)
        self._futures.add(future)
        future.add_done_callback(self._futures.discard)

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _execute(self, command_run_id: str) -> None:
        try:
            record = self._store.mark_running(command_run_id)
            spec = self._catalog.get(record.run.command_id)
            service = self._services.get(record.run.command_id)
            if spec.gateway_readiness != "application_service_ready":
                raise RuntimeError("command readiness changed before execution")
            if APPLICATION_SERVICE_BINDINGS.get(spec.command_id) != spec.binding_ref:
                raise RuntimeError("command catalog/application binding drift detected")

            config_values: Mapping[str, object] = {}
            if record.intent.config_snapshot_id is not None:
                snapshot = self._configs.snapshot(record.intent.config_snapshot_id)
                if spec.command_id != "config.validate" and snapshot.redacted_fields:
                    raise RuntimeError(
                        "generic Control Plane cannot resolve host-bound secret references"
                    )
                config_values = snapshot.values

            parameters = dict(record.parameters)
            if spec.command_id == "review.export_bundle":
                validation_id = str(parameters["validation_id"])
                parameters = {
                    "validation_id": validation_id,
                    "reports": self._report_paths,
                    "output": str(
                        self._export_dir / f"finagent-review-{validation_id}.zip"
                    ),
                }
            invocation = ApplicationCommandInvocation(
                command_id=record.run.command_id,
                config_snapshot_id=record.intent.config_snapshot_id,
                config_values=config_values,
                parameters=parameters,
                context=record.intent.context,
                requested_by=record.intent.requested_by,
            )
            execution = service.execute(invocation)
            if execution.status == "succeeded":
                self._store.mark_succeeded(command_run_id, execution)
            else:
                self._store.mark_rejected(command_run_id, execution)
        except Exception as exc:  # noqa: BLE001 - failure must become durable audit
            message = f"{type(exc).__name__}: {exc}"
            try:
                self._store.mark_failed(command_run_id, message)
            except (KeyError, ValueError):
                return


def _normalize_context(context: Mapping[str, str]) -> dict[str, str]:
    unknown = set(context) - _CONTROL_CONTEXT_KEYS
    if unknown:
        raise ValueError(f"unsupported WorkbenchContext keys: {sorted(unknown)}")
    output: dict[str, str] = {}
    for raw_key, raw_value in sorted(context.items()):
        value = raw_value.strip()
        if value:
            output[raw_key] = value
    return output


def _safe_identifier(value: str, name: str) -> str:
    normalized = value.strip()
    if not _SAFE_ID.fullmatch(normalized):
        raise ValueError(f"{name} contains unsupported characters")
    return normalized


def _validate_request(
    request: ControlRunRequest,
    *,
    config_registry: ConfigRegistry,
) -> tuple[bool, str, dict[str, object], str | None, dict[str, str]]:
    catalog = default_command_catalog()
    services = default_application_service_registry(config_registry)
    command_id = request.command_id.strip()
    context = _normalize_context(request.context)
    parameters: dict[str, object] = {}
    snapshot_id = request.config_snapshot_id

    try:
        spec = catalog.get(command_id)
    except KeyError:
        return (
            False,
            "command_id is not in the allowlisted catalog",
            parameters,
            snapshot_id,
            context,
        )
    if spec.level not in {"L0", "L1"}:
        return (
            False,
            "generic Control Plane permits only L0/L1 commands",
            parameters,
            snapshot_id,
            context,
        )
    if spec.gateway_readiness != "application_service_ready":
        return (
            False,
            "command has no reviewed application-service binding",
            parameters,
            snapshot_id,
            context,
        )
    if command_id not in services.command_ids():
        return (
            False,
            "application service is not registered",
            parameters,
            snapshot_id,
            context,
        )
    if APPLICATION_SERVICE_BINDINGS.get(command_id) != spec.binding_ref:
        return (
            False,
            "catalog/application service binding mismatch",
            parameters,
            snapshot_id,
            context,
        )
    if spec.requires_confirmation and not request.confirmed:
        return (
            False,
            "command requires explicit confirmation",
            parameters,
            snapshot_id,
            context,
        )

    if spec.config_descriptor_ids:
        if snapshot_id is None:
            return (
                False,
                "command requires config_snapshot_id",
                parameters,
                snapshot_id,
                context,
            )
        try:
            snapshot = config_registry.snapshot(snapshot_id)
        except KeyError:
            return (
                False,
                "config snapshot not found",
                parameters,
                snapshot_id,
                context,
            )
        if snapshot.descriptor_id not in spec.config_descriptor_ids:
            return (
                False,
                "config snapshot descriptor is not permitted for this command",
                parameters,
                snapshot_id,
                context,
            )
    elif snapshot_id is not None:
        return (
            False,
            "command does not accept a config snapshot",
            parameters,
            snapshot_id,
            context,
        )

    if command_id == "review.export_bundle":
        validation_id = request.validation_id or context.get("portfolio_validation_id")
        if not validation_id:
            return (
                False,
                "review.export_bundle requires portfolio_validation_id context",
                parameters,
                snapshot_id,
                context,
            )
        try:
            parameters["validation_id"] = _safe_identifier(
                validation_id,
                "validation_id",
            )
        except ValueError as exc:
            return False, str(exc), parameters, snapshot_id, context
    elif request.validation_id is not None:
        return (
            False,
            "validation_id is not accepted by this command",
            parameters,
            snapshot_id,
            context,
        )

    return True, "", parameters, snapshot_id, context


def _control_catalog_projection(config_registry: ConfigRegistry) -> dict[str, object]:
    catalog = default_command_catalog()
    services = default_application_service_registry(config_registry)
    service_ids = set(services.command_ids())
    items: list[dict[str, object]] = []
    for spec in catalog.specs:
        executable = (
            spec.gateway_readiness == "application_service_ready"
            and spec.command_id in service_ids
            and APPLICATION_SERVICE_BINDINGS.get(spec.command_id) == spec.binding_ref
        )
        payload = spec.to_dict()
        payload["control_execution_enabled"] = executable
        payload["control_plane_enabled"] = True
        items.append(payload)
    return {
        "schema_version": "finagent.workbench.control-command-catalog.v1",
        "control_plane_enabled": True,
        "local_only": True,
        "items": items,
        "forbidden_authority": catalog.to_dict()["forbidden_authority"],
    }


def create_control_app(
    *,
    config_paths: Sequence[str | Path] = ("configs",),
    report_paths: Sequence[str | Path] = ("reports",),
    store_path: str | Path = ".finagent/workbench/commands.sqlite",
    export_dir: str | Path = ".finagent/workbench/exports",
    requested_by: str = "local-workbench-user",
    max_workers: int = 2,
    cors_origins: Sequence[str] = (
        "http://127.0.0.1:8765",
        "http://localhost:8765",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ),
) -> FastAPI:
    config_registry = ConfigRegistry(config_paths)
    store = SQLiteCommandStore(store_path)
    recovered = store.recover_incomplete()
    runner = ControlCommandRunner(
        store=store,
        config_registry=config_registry,
        report_paths=report_paths,
        export_dir=export_dir,
        max_workers=max_workers,
    )
    catalog = default_command_catalog()
    ready = tuple(
        sorted(
            spec.command_id
            for spec in catalog.specs
            if spec.gateway_readiness == "application_service_ready"
        )
    )
    if ready != runner.service_ids:
        raise RuntimeError(
            "application-service-ready catalog does not match registered "
            "Control Plane services"
        )

    actor = requested_by.strip()
    if not actor:
        raise ValueError("requested_by is required")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        runner.close()

    app = FastAPI(
        title="FinAgent Workbench Control Plane",
        version=CONTROL_API_VERSION,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Content-Type"],
    )
    app.state.control_plane_enabled = True
    app.state.command_store = store
    app.state.recovered_command_runs = recovered

    @app.get("/api/v3/control/status")
    def get_control_status() -> dict[str, object]:
        return {
            "schema_version": "finagent.workbench.control-status.v1",
            "version": CONTROL_API_VERSION,
            "control_plane_enabled": True,
            "local_only": True,
            "remote_binding_supported": False,
            "requested_by": actor,
            "application_service_ready": list(runner.service_ids),
            "recovered_incomplete_runs": list(recovered),
            "store": store.status(),
            "forbidden_authority": catalog.to_dict()["forbidden_authority"],
        }

    @app.get("/api/v3/control/commands")
    def get_control_commands() -> dict[str, object]:
        return _control_catalog_projection(config_registry)

    @app.get("/api/v3/control/runs")
    def get_control_runs(
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> dict[str, object]:
        return {
            "schema_version": "finagent.workbench.command-record-list.v1",
            "items": [record.to_dict() for record in store.list(limit=limit)],
        }

    @app.get("/api/v3/control/runs/{command_run_id}")
    def get_control_run(command_run_id: str) -> dict[str, object]:
        try:
            return store.get(command_run_id).to_dict()
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="command run not found",
            ) from exc

    @app.post("/api/v3/control/runs")
    def create_control_run(request: ControlRunRequest):
        request_key = _safe_identifier(request.request_id, "request_id")
        command_id = request.command_id.strip()
        try:
            accepted, reason, parameters, snapshot_id, context = _validate_request(
                request,
                config_registry=config_registry,
            )
        except ValueError as exc:
            accepted = False
            reason = str(exc)
            parameters = {}
            snapshot_id = request.config_snapshot_id
            context = {}
        try:
            record, created = store.create(
                request_key=request_key,
                command_id=command_id,
                config_snapshot_id=snapshot_id,
                context=context,
                parameters=parameters,
                requested_by=actor,
                accepted=accepted,
                rejection_message=reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if created and accepted:
            runner.submit(record.run.command_run_id)
        status_code = (
            202
            if accepted
            and record.run.state not in {"succeeded", "failed", "rejected"}
            else 200
        )
        if not accepted:
            status_code = 422
        return JSONResponse(
            status_code=status_code,
            content=record.to_dict(),
        )

    return app


def create_app_from_environment() -> FastAPI:
    config_paths = tuple(
        value
        for value in os.environ.get(
            "FINAGENT_CONTROL_CONFIGS",
            "configs",
        ).split(os.pathsep)
        if value
    )
    report_paths = tuple(
        value
        for value in os.environ.get(
            "FINAGENT_CONTROL_REPORTS",
            "reports",
        ).split(os.pathsep)
        if value
    )
    store_path = os.environ.get(
        "FINAGENT_CONTROL_STORE",
        ".finagent/workbench/commands.sqlite",
    )
    export_dir = os.environ.get(
        "FINAGENT_CONTROL_EXPORT_DIR",
        ".finagent/workbench/exports",
    )
    actor = os.environ.get("FINAGENT_CONTROL_ACTOR", "local-workbench-user")
    max_workers = int(os.environ.get("FINAGENT_CONTROL_WORKERS", "2"))
    return create_control_app(
        config_paths=config_paths,
        report_paths=report_paths,
        store_path=store_path,
        export_dir=export_dir,
        requested_by=actor,
        max_workers=max_workers,
    )

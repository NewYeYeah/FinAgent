from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal, Protocol

from finagent.data import (
    AshareBarFrequency,
    LocalAshareDatasetInspector,
    LocalAshareDatasetLayout,
)

ApplicationExecutionStatus = Literal["succeeded", "rejected"]

APPLICATION_SERVICE_BINDINGS: dict[str, str] = {
    "config.validate": (
        "finagent.application.control_services.ConfigValidationApplicationService"
    ),
    "data.certify_local_ashare": (
        "finagent.application.control_services.LocalAshareCertificationApplicationService"
    ),
    "review.export_bundle": (
        "finagent.application.control_services.ReviewBundleExportApplicationService"
    ),
}


@dataclass(frozen=True, slots=True)
class ApplicationCommandInvocation:
    """Typed in-process command input consumed by registered application services.

    This is deliberately not an executable-text contract. ``command_id`` is resolved
    through an allowlisted registry and parameters are data only.
    """

    command_id: str
    config_snapshot_id: str | None = None
    config_values: Mapping[str, object] = field(default_factory=dict)
    parameters: Mapping[str, object] = field(default_factory=dict)
    context: Mapping[str, str] = field(default_factory=dict)
    requested_by: str = "system"

    def __post_init__(self) -> None:
        command_id = self.command_id.strip()
        requested_by = self.requested_by.strip()
        if not command_id:
            raise ValueError("command_id is required")
        if not requested_by:
            raise ValueError("requested_by is required")
        object.__setattr__(self, "command_id", command_id)
        object.__setattr__(self, "requested_by", requested_by)
        if self.config_snapshot_id is not None:
            snapshot_id = self.config_snapshot_id.strip()
            if not snapshot_id:
                raise ValueError("config_snapshot_id cannot be empty")
            object.__setattr__(self, "config_snapshot_id", snapshot_id)


@dataclass(frozen=True, slots=True)
class ApplicationCommandExecution:
    command_id: str
    status: ApplicationExecutionStatus
    outputs: Mapping[str, object] = field(default_factory=dict)
    artifact_paths: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "command_id": self.command_id,
            "status": self.status,
            "outputs": dict(self.outputs),
            "artifact_paths": list(self.artifact_paths),
            "evidence_ids": list(self.evidence_ids),
            "message": self.message,
        }


class ApplicationCommandService(Protocol):
    command_id: str

    def execute(self, invocation: ApplicationCommandInvocation) -> ApplicationCommandExecution:
        ...


class ApplicationServiceRegistry:
    """Allowlisted in-process application-service registry.

    The registry owns no subprocess/shell facility. Unknown command identities fail
    closed instead of being interpreted as executable text.
    """

    def __init__(self, services: Sequence[ApplicationCommandService] = ()) -> None:
        self._services: dict[str, ApplicationCommandService] = {}
        for service in services:
            self.register(service)

    def register(self, service: ApplicationCommandService) -> None:
        command_id = service.command_id.strip()
        if not command_id:
            raise ValueError("application service command_id is required")
        if command_id in self._services:
            raise ValueError(f"application service already registered: {command_id}")
        self._services[command_id] = service

    def get(self, command_id: str) -> ApplicationCommandService:
        try:
            return self._services[command_id]
        except KeyError as exc:
            raise KeyError(f"application service is not registered: {command_id}") from exc

    def command_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._services))

    def execute(self, invocation: ApplicationCommandInvocation) -> ApplicationCommandExecution:
        return self.get(invocation.command_id).execute(invocation)


class ConfigValidationApplicationService:
    command_id = "config.validate"

    def __init__(self, config_registry: object) -> None:
        self._registry = config_registry

    def execute(self, invocation: ApplicationCommandInvocation) -> ApplicationCommandExecution:
        _assert_command(invocation, self.command_id)
        if invocation.config_snapshot_id is None:
            return ApplicationCommandExecution(
                command_id=self.command_id,
                status="rejected",
                message="config.validate requires config_snapshot_id",
            )

        snapshot = self._registry.snapshot(invocation.config_snapshot_id)
        descriptor = self._registry.descriptor(snapshot.descriptor_id)
        field_specs = {field.field_path: field for field in descriptor.fields}
        issues: list[str] = []

        for field in descriptor.fields:
            if field.required and field.field_path not in snapshot.values:
                issues.append(f"required field missing: {field.field_path}")

        for field_path in sorted(snapshot.values):
            field = field_specs.get(field_path)
            if field is None:
                issues.append(f"snapshot field absent from descriptor: {field_path}")
                continue
            if snapshot.domains.get(field_path) != field.domain:
                issues.append(f"domain mismatch: {field_path}")
            if snapshot.mutation_policies.get(field_path) != field.mutation_policy:
                issues.append(f"mutation policy mismatch: {field_path}")
            actual_type = _value_type(snapshot.values[field_path])
            if field.value_type not in {"mixed", actual_type}:
                issues.append(
                    f"value type mismatch: {field_path}: {actual_type} != {field.value_type}"
                )

        valid = not issues
        return ApplicationCommandExecution(
            command_id=self.command_id,
            status="succeeded" if valid else "rejected",
            outputs={
                "snapshot_id": snapshot.snapshot_id,
                "descriptor_id": descriptor.descriptor_id,
                "valid": valid,
                "issues": tuple(issues),
            },
            message="configuration snapshot is valid" if valid else "configuration snapshot is invalid",
        )


class LocalAshareCertificationApplicationService:
    command_id = "data.certify_local_ashare"

    def execute(self, invocation: ApplicationCommandInvocation) -> ApplicationCommandExecution:
        _assert_command(invocation, self.command_id)
        values = invocation.config_values
        root_raw = invocation.parameters.get("root", values.get("root"))
        if root_raw in {None, ""}:
            raise ValueError("local_ashare.root is required")
        root = Path(str(root_raw)).expanduser()
        layout = LocalAshareDatasetLayout(
            root=root,
            basic_filename=str(values.get("basic_filename", "stock_basic_data.parquet")),
            daily_filename=str(values.get("daily_filename", "stock_daily.parquet")),
        )
        frequency_raw = invocation.parameters.get(
            "frequency",
            values.get("sample_frequency", "1min"),
        )
        frequency = AshareBarFrequency(str(frequency_raw))
        symbol_raw = invocation.parameters.get(
            "sample_symbol",
            values.get("sample_symbol", ""),
        )
        symbol = str(symbol_raw).strip() or None
        sample_date_raw = invocation.parameters.get(
            "sample_date",
            values.get("sample_date"),
        )
        selected_date = _date_value(sample_date_raw)
        report = LocalAshareDatasetInspector(layout).inspect(
            intraday_symbol=symbol,
            intraday_date=selected_date,
            frequency=frequency,
        )
        output_raw = invocation.parameters.get(
            "output",
            values.get("report_path", "reports/local_ashare_certification.json"),
        )
        output = Path(str(output_raw)).expanduser()
        report.write_json(output)
        report_payload = report.to_dict()
        return ApplicationCommandExecution(
            command_id=self.command_id,
            status="succeeded" if report.passed else "rejected",
            outputs={
                "passed": bool(report.passed),
                "report": report_payload,
                "output_path": str(output),
            },
            artifact_paths=(str(output),),
            message=(
                "local A-share dataset certification passed"
                if report.passed
                else "local A-share dataset certification failed"
            ),
        )


class ReviewBundleExportApplicationService:
    command_id = "review.export_bundle"

    def execute(self, invocation: ApplicationCommandInvocation) -> ApplicationCommandExecution:
        _assert_command(invocation, self.command_id)
        validation_id = str(invocation.parameters.get("validation_id", "")).strip()
        if not validation_id:
            raise ValueError("review.export_bundle requires validation_id")
        raw_reports = invocation.parameters.get("reports", ("reports",))
        reports = _path_sequence(raw_reports)
        git_sha = str(invocation.parameters.get("git_sha", "")).strip()

        # Imported lazily so the application registry itself stays independent from
        # the Workbench presentation stack until this L0 export service is invoked.
        from finagent.visualization.workspace_api import WorkspaceEvidenceCatalog
        from finagent.visualization.workspace_v2 import WorkspaceV2Projection

        catalog = WorkspaceEvidenceCatalog(reports, git_sha=git_sha)
        projection = WorkspaceV2Projection(
            catalog.bundles(),
            report_paths=reports,
            git_sha=git_sha,
        )
        payload = projection.review_bundle(validation_id)
        output_raw = invocation.parameters.get(
            "output",
            f"finagent-review-{validation_id}.zip",
        )
        output = Path(str(output_raw)).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        return ApplicationCommandExecution(
            command_id=self.command_id,
            status="succeeded",
            outputs={
                "validation_id": validation_id,
                "output_path": str(output),
                "sha256": digest,
                "size_bytes": len(payload),
            },
            artifact_paths=(str(output),),
            evidence_ids=(validation_id,),
            message="human-review bundle exported",
        )


def default_application_service_registry(config_registry: object) -> ApplicationServiceRegistry:
    return ApplicationServiceRegistry(
        (
            ConfigValidationApplicationService(config_registry),
            LocalAshareCertificationApplicationService(),
            ReviewBundleExportApplicationService(),
        )
    )


def _assert_command(invocation: ApplicationCommandInvocation, expected: str) -> None:
    if invocation.command_id != expected:
        raise ValueError(
            f"application service {expected!r} cannot execute command {invocation.command_id!r}"
        )


def _date_value(value: object | None) -> date | None:
    if value in {None, ""}:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _path_sequence(value: object) -> tuple[str | Path, ...]:
    if isinstance(value, (str, Path)):
        return (value,)
    if not isinstance(value, Sequence):
        raise TypeError("reports must be a path or a sequence of paths")
    output = tuple(item for item in value if isinstance(item, (str, Path)))
    if len(output) != len(value):
        raise TypeError("reports must contain only paths")
    return output or ("reports",)


def _value_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__

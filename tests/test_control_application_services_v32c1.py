from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

import finagent.application.control_services as control_services
from finagent.application import (
    APPLICATION_SERVICE_BINDINGS,
    ApplicationCommandInvocation,
    ApplicationServiceRegistry,
    LocalAshareCertificationApplicationService,
    ReviewBundleExportApplicationService,
    default_application_service_registry,
)
from finagent.visualization.workbench_control_catalog import (
    ConfigRegistry,
    default_command_catalog,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_application_registry_matches_catalog_ready_commands(tmp_path: Path) -> None:
    _write(
        tmp_path / "local.toml",
        """
[local_ashare]
root = "D:/Data/A-Share"
basic_filename = "stock_basic_data.parquet"
daily_filename = "stock_daily.parquet"
sample_frequency = "1min"
report_path = "reports/local_ashare_certification.json"
""".strip(),
    )
    config_registry = ConfigRegistry((tmp_path,))
    services = default_application_service_registry(config_registry)
    catalog = default_command_catalog()
    ready_bindings = {
        spec.command_id: spec.binding_ref
        for spec in catalog.specs
        if spec.gateway_readiness == "application_service_ready"
    }
    assert ready_bindings == APPLICATION_SERVICE_BINDINGS
    assert services.command_ids() == tuple(sorted(ready_bindings))
    assert tuple(sorted(ready_bindings)) == (
        "config.validate",
        "data.certify_local_ashare",
        "review.export_bundle",
    )
    certification = catalog.get("data.certify_local_ashare")
    assert certification.config_descriptor_ids == ("local_ashare",)
    assert certification.binding_kind == "application_service"
    assert catalog.get("research.run_development").gateway_readiness == "adapter_required"
    assert catalog.get("research.run_a2p6").gateway_readiness == "adapter_required"
    assert catalog.get("portfolio.run_a4").gateway_readiness == "adapter_required"


def test_config_validation_service_accepts_projected_snapshot(tmp_path: Path) -> None:
    _write(
        tmp_path / "local.toml",
        """
[local_ashare]
root = "D:/Data/A-Share"
basic_filename = "stock_basic_data.parquet"
daily_filename = "stock_daily.parquet"
sample_frequency = "1min"
sample_symbol = "000001.SZ"
sample_date = 2009-01-05
report_path = "reports/local_ashare_certification.json"
""".strip(),
    )
    config_registry = ConfigRegistry((tmp_path,))
    snapshot = config_registry.snapshots("local_ashare")[0]
    execution = default_application_service_registry(config_registry).execute(
        ApplicationCommandInvocation(
            command_id="config.validate",
            config_snapshot_id=snapshot.snapshot_id,
            requested_by="test",
        )
    )
    assert execution.status == "succeeded"
    assert execution.outputs["valid"] is True
    assert execution.outputs["descriptor_id"] == "local_ashare"


def test_application_registry_fails_closed_for_unknown_command() -> None:
    registry = ApplicationServiceRegistry()
    with pytest.raises(KeyError, match="not registered"):
        registry.execute(
            ApplicationCommandInvocation(
                command_id="python -c 'print(1)'",
                requested_by="test",
            )
        )
    source = inspect.getsource(control_services)
    assert "subprocess" not in source
    assert "os.system" not in source


def test_local_ashare_certification_service_runs_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeReport:
        passed = True

        def write_json(self, path: Path) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.to_dict()), encoding="utf-8")

        def to_dict(self) -> dict[str, object]:
            return {"schema_version": "fake-cert.v1", "passed": True}

    class FakeInspector:
        def __init__(self, layout: object) -> None:
            observed["layout"] = layout

        def inspect(self, **kwargs: object) -> FakeReport:
            observed["inspect"] = kwargs
            return FakeReport()

    monkeypatch.setattr(control_services, "LocalAshareDatasetInspector", FakeInspector)
    output = tmp_path / "reports" / "certification.json"
    execution = LocalAshareCertificationApplicationService().execute(
        ApplicationCommandInvocation(
            command_id="data.certify_local_ashare",
            config_values={
                "root": str(tmp_path / "data"),
                "basic_filename": "basic.parquet",
                "daily_filename": "daily.parquet",
                "sample_frequency": "1min",
                "sample_symbol": "000001.SZ",
                "sample_date": "2009-01-05",
            },
            parameters={"output": output},
            requested_by="test",
        )
    )
    assert execution.status == "succeeded"
    assert execution.artifact_paths == (str(output),)
    assert output.is_file()
    assert execution.outputs["report"] == {
        "schema_version": "fake-cert.v1",
        "passed": True,
    }
    inspect_args = observed["inspect"]
    assert isinstance(inspect_args, dict)
    assert str(inspect_args["intraday_date"]) == "2009-01-05"


def test_review_bundle_export_service_runs_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from finagent.visualization import workspace_api, workspace_v2

    class FakeCatalog:
        def __init__(self, report_paths: object, *, git_sha: str = "") -> None:
            assert report_paths == ("reports",)
            assert git_sha == "git-a"

        def bundles(self) -> tuple[object, ...]:
            return ()

    class FakeProjection:
        def __init__(
            self,
            bundles: object,
            *,
            report_paths: object,
            git_sha: str = "",
        ) -> None:
            assert bundles == ()
            assert report_paths == ("reports",)
            assert git_sha == "git-a"

        def review_bundle(self, validation_id: str) -> bytes:
            assert validation_id == "a4-validation"
            return b"review-bundle-bytes"

    monkeypatch.setattr(workspace_api, "WorkspaceEvidenceCatalog", FakeCatalog)
    monkeypatch.setattr(workspace_v2, "WorkspaceV2Projection", FakeProjection)
    output = tmp_path / "review.zip"
    execution = ReviewBundleExportApplicationService().execute(
        ApplicationCommandInvocation(
            command_id="review.export_bundle",
            parameters={
                "validation_id": "a4-validation",
                "reports": ("reports",),
                "git_sha": "git-a",
                "output": output,
            },
            requested_by="test",
        )
    )
    payload = b"review-bundle-bytes"
    assert execution.status == "succeeded"
    assert output.read_bytes() == payload
    assert execution.outputs["sha256"] == hashlib.sha256(payload).hexdigest()
    assert execution.evidence_ids == ("a4-validation",)

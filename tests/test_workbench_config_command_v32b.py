from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from finagent.visualization.workbench_api import create_workspace_app
from finagent.visualization.workbench_control_catalog import (
    ConfigRegistry,
    default_command_catalog,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_config_registry_redacts_secrets_and_excludes_secret_files(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "market.toml",
        """
[market_data]
default_profile = "primary"
secrets_file = "C:/private/secrets.toml"

[market_data.profiles.primary]
provider = "hithink"
secret_id = "hithink-prod"
api_key = "must-not-leak"

[[market_data.extra_routes]]
name = "nested"
token = "nested-must-not-leak"
""".strip(),
    )
    _write(
        tmp_path / "secrets.toml",
        """
[api_keys]
hithink = "also-must-not-leak"
""".strip(),
    )

    registry = ConfigRegistry((tmp_path,))
    snapshots = registry.snapshots("market_data")
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.values["secrets_file"] == "<secret-file-reference>"
    assert snapshot.values["profiles.primary.secret_id"] == "hithink-prod"
    assert snapshot.values["profiles.primary.api_key"] == "<redacted>"
    extra_routes = snapshot.values["extra_routes"]
    assert isinstance(extra_routes, list)
    assert isinstance(extra_routes[0], dict)
    assert extra_routes[0]["token"] == "<redacted>"
    projection_text = str(registry.projection.to_dict())
    assert "must-not-leak" not in projection_text
    assert "nested-must-not-leak" not in projection_text
    assert "also-must-not-leak" not in projection_text
    assert any(
        "secret-like config excluded without parsing" in item
        for item in registry.projection.warnings
    )


def test_config_descriptor_required_is_derived_across_unique_snapshots(
    tmp_path: Path,
) -> None:
    first = _write(
        tmp_path / "first.toml",
        """
[local_ashare_research_smoke]
root = "D:/Data/A-Share"
min_assets = 100
optional_note = "first-only"
""".strip(),
    )
    _write(
        tmp_path / "second.toml",
        """
[local_ashare_research_smoke]
root = "E:/Data/A-Share"
min_assets = 120
""".strip(),
    )
    registry = ConfigRegistry((tmp_path, first))
    descriptor = registry.descriptor("local_ashare_research_smoke")
    fields = {item.field_path: item for item in descriptor.fields}
    assert fields["root"].required is True
    assert fields["min_assets"].required is True
    assert fields["optional_note"].required is False
    assert len(registry.snapshots("local_ashare_research_smoke")) == 2
    assert any(
        "duplicate config snapshot ignored" in item
        for item in registry.projection.warnings
    )


def test_config_diff_marks_protocol_identity_changes(tmp_path: Path) -> None:
    _write(
        tmp_path / "left.toml",
        """
[local_ashare_robust_research]
program_id = "program-a"
root = "D:/Data/A-Share"
universe_top_n = 150
""".strip(),
    )
    _write(
        tmp_path / "right.toml",
        """
[local_ashare_robust_research]
program_id = "program-a"
root = "E:/Data/A-Share"
universe_top_n = 180
""".strip(),
    )

    registry = ConfigRegistry((tmp_path,))
    snapshots = registry.snapshots("local_ashare_robust_research")
    assert len(snapshots) == 2
    diff = registry.diff(snapshots[0].snapshot_id, snapshots[1].snapshot_id)
    changes = {item.field_path: item for item in diff.changes}
    assert changes["root"].domain == "runtime"
    assert changes["root"].requires_new_identity is False
    assert changes["universe_top_n"].domain == "research_protocol"
    assert changes["universe_top_n"].mutation_policy == "new_identity_required"
    assert changes["universe_top_n"].requires_new_identity is True
    assert diff.requires_new_identity is True


def test_command_catalog_is_l0_l1_catalog_only() -> None:
    catalog = default_command_catalog()
    payload = catalog.to_dict()
    assert payload["control_plane_enabled"] is False
    assert payload["execution_enabled"] is False
    assert {item.level for item in catalog.specs} <= {"L0", "L1"}
    assert all(item.catalog_only for item in catalog.specs)
    assert all(not item.execution_enabled for item in catalog.specs)
    assert catalog.get("research.run_a2p6").gateway_readiness == "adapter_required"
    assert (
        catalog.get("review.export_bundle").binding_ref
        == "scripts/export_workspace_review_bundle.py"
    )
    assert "production_reserve" in payload["forbidden_authority"]
    assert "broker_order" in payload["forbidden_authority"]


def test_v32b_api_is_get_only_and_projects_catalogs(tmp_path: Path) -> None:
    _write(
        tmp_path / "config.toml",
        """
[ashare_portfolio_validation]
a2p6_report = "reports/a26.json"
risk_aversion = 3.0
broker_commission_rate = 0.0003
policy_min_net_sharpe = 0.5
""".strip(),
    )
    app = create_workspace_app(
        report_paths=(),
        config_paths=(tmp_path,),
        frontend_dir=None,
    )
    client = TestClient(app)

    status = client.get("/api/v3/workbench/status")
    assert status.status_code == 200
    assert status.json()["control_plane_enabled"] is False
    assert status.json()["command_execution_enabled"] is False

    registry = client.get("/api/v3/config")
    assert registry.status_code == 200
    assert registry.json()["read_only"] is True
    assert (
        registry.json()["descriptors"][0]["descriptor_id"]
        == "ashare_portfolio_validation"
    )

    commands = client.get("/api/v3/commands")
    assert commands.status_code == 200
    assert commands.json()["execution_enabled"] is False
    assert commands.json()["control_plane_enabled"] is False

    response = client.post(
        "/api/v3/commands",
        json={"command_id": "research.run_a2p6"},
    )
    assert response.status_code == 405
    assert client.put("/api/v3/config", json={}).status_code == 405
    assert client.delete("/api/v3/config").status_code == 405

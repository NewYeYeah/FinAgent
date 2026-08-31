from pathlib import Path

import pytest

from finagent.runtime.initial_requirement_compliance import (
    INITIAL_REQUIREMENT_COMPLIANCE_SCHEMA,
    InitialRequirementComplianceAudit,
    RequirementComplianceEntry,
    REQUIRED_REQUIREMENT_IDS,
    run_initial_requirement_compliance_audit,
)


MANIFEST = Path("configs/acceptance/ashare_initial_requirement_compliance_ac4.toml")
GIT_SHA = "0123456789abcdef0123456789abcdef01234567"


def test_ac4_manifest_is_complete_and_freeze_ready() -> None:
    audit = run_initial_requirement_compliance_audit(MANIFEST, git_sha=GIT_SHA)

    assert audit.audit_complete is True
    assert audit.historical_freeze_ready is True
    assert {entry.requirement_id for entry in audit.entries} == set(REQUIRED_REQUIREMENT_IDS)
    assert dict(audit.status_counts) == {
        "DEFERRED": 7,
        "N/A": 0,
        "PARTIAL": 0,
        "PASS": 15,
    }

    payload = audit.to_dict()
    assert payload["schema_version"] == INITIAL_REQUIREMENT_COMPLIANCE_SCHEMA
    assert payload["production_reserve_authority"] is False
    assert payload["reserve_accessed_by_audit"] is False
    assert payload["historical_freeze_ready"] is True
    assert set(payload["deferred_capabilities"]) == {
        "benchmark_evidence",
        "corporate_actions",
        "capacity_impact",
        "advanced_risk",
        "internal_paper",
        "realtime_gateway",
        "qmt",
    }


def test_ac4_audit_identity_and_rendering_are_deterministic(tmp_path: Path) -> None:
    first = run_initial_requirement_compliance_audit(MANIFEST, git_sha=GIT_SHA)
    second = run_initial_requirement_compliance_audit(MANIFEST, git_sha=GIT_SHA)

    assert first.audit_id == second.audit_id
    assert first.to_dict() == second.to_dict()
    assert first.to_markdown() == second.to_markdown()

    json_report = first.write_json(tmp_path / "audit.json")
    markdown_report = first.write_markdown(tmp_path / "audit.md")
    assert json_report.read_text(encoding="utf-8").endswith("\n")
    markdown = markdown_report.read_text(encoding="utf-8")
    assert "A-C4 Initial Requirement Compliance Audit" in markdown
    assert "`pit_data_adapter_research_dataset`" in markdown
    assert "`qmt`" in markdown
    assert "DEFERRED" in markdown


def test_ac4_pass_requires_implementation_and_evidence() -> None:
    with pytest.raises(ValueError, match="PASS requirements require"):
        RequirementComplianceEntry(
            requirement_id="invalid_pass",
            requirement="Invalid PASS",
            source_plans=("docs/development/current-development-plan-v4.0.md",),
            implementation_refs=(),
            test_evidence_refs=(),
            status="PASS",
            disposition="close",
            rationale="This intentionally violates the PASS evidence contract.",
        )


def test_ac4_frozen_requirement_denominator_cannot_drift() -> None:
    audit = run_initial_requirement_compliance_audit(MANIFEST, git_sha=GIT_SHA)
    with pytest.raises(ValueError, match="denominator differs"):
        InitialRequirementComplianceAudit(
            audit_name=audit.audit_name,
            git_sha=audit.git_sha,
            manifest_path=audit.manifest_path,
            manifest_sha256=audit.manifest_sha256,
            entries=audit.entries[:-1],
        )

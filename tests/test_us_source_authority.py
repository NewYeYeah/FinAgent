from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from finagent.data.provenance import (
    CorporateActionStatus,
    DatasetAuthorityBundle,
    DatasetAuthorityStatus,
    DatasetFileDescriptor,
    DatasetProvenanceRecord,
    DatasetRevision,
    DatasetRevisionKind,
    DatasetSourceCandidate,
    DatasetSourceKind,
    DatasetUsageRightsRecord,
    InventoryIdentityKind,
    OriginVerificationStatus,
    PriceAdjustmentStatus,
    SessionCoverageStatus,
    SymbolLifecycleStatus,
    TimestampMeaning,
    UsageRightsStatus,
    evaluate_dataset_authority,
    load_dataset_authority_config,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "us_source_authority" / "mito0o852_ohlcv_1m.toml"
NOW = datetime(2026, 9, 1, 3, 20, tzinfo=UTC)


def _accepted_provenance() -> DatasetProvenanceRecord:
    candidate = DatasetSourceCandidate(
        candidate_id="fixture-us-minute",
        source_kind=DatasetSourceKind.LOCAL_SNAPSHOT,
        locator="file:///fixture/us-minute",
        provider_name="fixture",
        market="us_equity",
        frequency="1m",
    )
    return DatasetProvenanceRecord(
        candidate=candidate,
        revision=DatasetRevision(
            kind=DatasetRevisionKind.CONTENT_HASH,
            value="a" * 64,
            immutable=True,
        ),
        upstream_origin="licensed fixture vendor",
        origin_status=OriginVerificationStatus.VERIFIED,
        schema_fields=("timestamp", "open", "high", "low", "close", "volume", "ticker"),
        partitioning="monthly parquet",
        coverage_start="2025-01",
        coverage_end="2025-12",
        timezone="UTC",
        timestamp_meaning=TimestampMeaning.BAR_START,
        session_coverage=SessionCoverageStatus.REGULAR_ONLY,
        price_adjustment=PriceAdjustmentStatus.RAW,
        corporate_actions=CorporateActionStatus.NOT_PROVIDED,
        symbol_lifecycle=SymbolLifecycleStatus.POINT_IN_TIME,
        inventory_complete=True,
        inventory_identity=InventoryIdentityKind.CONTENT_HASHES,
        files=(
            DatasetFileDescriptor(
                relative_path="2025-01.parquet",
                size_bytes=123,
                sha256="c" * 64,
            ),
        ),
        observed_at=NOW,
    )


def _accepted_rights() -> DatasetUsageRightsRecord:
    return DatasetUsageRightsRecord(
        status=UsageRightsStatus.VERIFIED_RESEARCH_USE,
        evidence_url="https://example.invalid/license",
        license_identifier="fixture-research-license",
        observed_at=NOW,
    )


def test_current_huggingface_candidate_is_reference_only() -> None:
    review = load_dataset_authority_config(CONFIG)
    bundle = review.bundle

    assert bundle.decision.status is DatasetAuthorityStatus.REFERENCE_ONLY
    assert bundle.provenance.revision.value == "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"
    assert "usage_rights:unresolved" in bundle.decision.blocking_issues
    assert "price_adjustment:unknown" in bundle.decision.blocking_issues
    assert "corporate_actions:unknown" in bundle.decision.blocking_issues
    with pytest.raises(PermissionError, match="reference_only"):
        bundle.require_research_authority()


def test_fully_resolved_source_can_be_accepted_for_research() -> None:
    provenance = _accepted_provenance()
    rights = _accepted_rights()
    decision = evaluate_dataset_authority(provenance, rights, decided_at=NOW)
    bundle = DatasetAuthorityBundle(provenance=provenance, usage_rights=rights, decision=decision)

    assert decision.status is DatasetAuthorityStatus.ACCEPTED_FOR_RESEARCH
    assert decision.blocking_issues == ()
    identity = bundle.require_research_authority()
    assert identity.revision == "a" * 64
    assert identity.authority_decision_id == decision.decision_id


def test_unknown_semantics_fail_closed_even_with_verified_rights() -> None:
    provenance = replace(
        _accepted_provenance(),
        session_coverage=SessionCoverageStatus.UNKNOWN,
        price_adjustment=PriceAdjustmentStatus.UNKNOWN,
    )
    decision = evaluate_dataset_authority(provenance, _accepted_rights(), decided_at=NOW)

    assert decision.status is DatasetAuthorityStatus.REFERENCE_ONLY
    assert decision.blocking_issues == (
        "session_coverage:unknown",
        "price_adjustment:unknown",
    )


def test_prohibited_usage_rights_reject_source() -> None:
    rights = replace(_accepted_rights(), status=UsageRightsStatus.PROHIBITED)
    decision = evaluate_dataset_authority(_accepted_provenance(), rights, decided_at=NOW)

    assert decision.status is DatasetAuthorityStatus.REJECTED
    assert "usage_rights:prohibited" in decision.blocking_issues


def test_revision_is_part_of_provenance_identity() -> None:
    original = _accepted_provenance()
    changed = replace(
        original,
        revision=DatasetRevision(
            kind=DatasetRevisionKind.CONTENT_HASH,
            value="b" * 64,
            immutable=True,
        ),
    )

    assert original.provenance_id != changed.provenance_id


def test_authority_bundle_round_trips_and_detects_identity(tmp_path: Path) -> None:
    provenance = _accepted_provenance()
    rights = _accepted_rights()
    decision = evaluate_dataset_authority(provenance, rights, decided_at=NOW)
    bundle = DatasetAuthorityBundle(provenance=provenance, usage_rights=rights, decision=decision)

    path = bundle.write_json(tmp_path / "authority.json")
    restored = DatasetAuthorityBundle.read_json(path)

    assert restored.bundle_id == bundle.bundle_id
    assert restored.source_identity() == bundle.source_identity()


def test_git_revision_requires_full_immutable_identity() -> None:
    with pytest.raises(ValueError, match="full 40-character"):
        DatasetRevision(kind=DatasetRevisionKind.GIT_COMMIT, value="7763284", immutable=True)

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import (
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
)


@dataclass(frozen=True, slots=True)
class DatasetAuthorityConfig:
    bundle: DatasetAuthorityBundle
    expected_status: DatasetAuthorityStatus
    required_blockers: tuple[str, ...]

    def verify_expectation(self) -> None:
        if self.bundle.decision.status is not self.expected_status:
            raise ValueError(
                f"authority status mismatch: expected {self.expected_status.value}, "
                f"got {self.bundle.decision.status.value}"
            )
        actual = set(self.bundle.decision.blocking_issues)
        missing = [blocker for blocker in self.required_blockers if blocker not in actual]
        if missing:
            raise ValueError("required authority blockers missing: " + ", ".join(missing))


def _parse_datetime(value: object) -> datetime:
    return datetime.fromisoformat(str(value).strip())


def load_dataset_authority_config(path: str | Path) -> DatasetAuthorityConfig:
    with Path(path).open("rb") as handle:
        raw: dict[str, Any] = tomllib.load(handle)

    candidate_raw = raw["candidate"]
    candidate = DatasetSourceCandidate(
        candidate_id=str(candidate_raw["candidate_id"]),
        source_kind=DatasetSourceKind(str(candidate_raw["source_kind"])),
        locator=str(candidate_raw["locator"]),
        provider_name=str(candidate_raw["provider_name"]),
        market=str(candidate_raw["market"]),
        frequency=str(candidate_raw["frequency"]),
    )

    revision_raw = raw["revision"]
    revision = DatasetRevision(
        kind=DatasetRevisionKind(str(revision_raw["kind"])),
        value=str(revision_raw["value"]),
        immutable=bool(revision_raw["immutable"]),
    )

    provenance_raw = raw["provenance"]
    files = tuple(
        DatasetFileDescriptor(
            relative_path=str(item["relative_path"]),
            size_bytes=int(item["size_bytes"]) if item.get("size_bytes") is not None else None,
            sha256=str(item.get("sha256") or ""),
            remote_oid=str(item.get("remote_oid") or ""),
        )
        for item in raw.get("files", [])
    )
    provenance = DatasetProvenanceRecord(
        candidate=candidate,
        revision=revision,
        upstream_origin=str(provenance_raw["upstream_origin"]),
        origin_status=OriginVerificationStatus(str(provenance_raw["origin_status"])),
        schema_fields=tuple(str(value) for value in provenance_raw["schema_fields"]),
        partitioning=str(provenance_raw["partitioning"]),
        coverage_start=str(provenance_raw["coverage_start"]),
        coverage_end=str(provenance_raw["coverage_end"]),
        timezone=str(provenance_raw["timezone"]),
        timestamp_meaning=TimestampMeaning(str(provenance_raw["timestamp_meaning"])),
        session_coverage=SessionCoverageStatus(str(provenance_raw["session_coverage"])),
        price_adjustment=PriceAdjustmentStatus(str(provenance_raw["price_adjustment"])),
        corporate_actions=CorporateActionStatus(str(provenance_raw["corporate_actions"])),
        symbol_lifecycle=SymbolLifecycleStatus(str(provenance_raw["symbol_lifecycle"])),
        inventory_complete=bool(provenance_raw["inventory_complete"]),
        inventory_identity=InventoryIdentityKind(str(provenance_raw["inventory_identity"])),
        files=files,
        observed_at=_parse_datetime(provenance_raw["observed_at"]),
        evidence_urls=tuple(str(value) for value in provenance_raw.get("evidence_urls", [])),
        notes=tuple(str(value) for value in provenance_raw.get("notes", [])),
    )

    rights_raw = raw["usage_rights"]
    rights = DatasetUsageRightsRecord(
        status=UsageRightsStatus(str(rights_raw["status"])),
        evidence_url=str(rights_raw["evidence_url"]),
        license_identifier=str(rights_raw.get("license_identifier") or ""),
        observed_at=_parse_datetime(rights_raw["observed_at"]),
        notes=tuple(str(value) for value in rights_raw.get("notes", [])),
    )

    decision_raw = raw.get("decision", {})
    decided_at = _parse_datetime(decision_raw.get("decided_at", provenance.observed_at.isoformat()))
    decision = evaluate_dataset_authority(provenance, rights, decided_at=decided_at)
    bundle = DatasetAuthorityBundle(provenance=provenance, usage_rights=rights, decision=decision)

    expectation_raw = raw["expectation"]
    config = DatasetAuthorityConfig(
        bundle=bundle,
        expected_status=DatasetAuthorityStatus(str(expectation_raw["authority_status"])),
        required_blockers=tuple(
            str(value) for value in expectation_raw.get("required_blockers", [])
        ),
    )
    config.verify_expectation()
    return config

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_OHLCV_FIELDS = frozenset(
    {"timestamp", "open", "high", "low", "close", "volume", "ticker"}
)


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _aware(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


class DatasetSourceKind(str, Enum):
    HUGGINGFACE_DATASET = "huggingface_dataset"
    PROVIDER_API = "provider_api"
    LOCAL_SNAPSHOT = "local_snapshot"


class DatasetRevisionKind(str, Enum):
    GIT_COMMIT = "git_commit"
    CONTENT_HASH = "content_hash"
    PROVIDER_SNAPSHOT = "provider_snapshot"


class OriginVerificationStatus(str, Enum):
    VERIFIED = "verified"
    DECLARED_BY_PUBLISHER = "declared_by_publisher"
    UNKNOWN = "unknown"


class UsageRightsStatus(str, Enum):
    VERIFIED_RESEARCH_USE = "verified_research_use"
    UNRESOLVED = "unresolved"
    RESTRICTED = "restricted"
    PROHIBITED = "prohibited"


class TimestampMeaning(str, Enum):
    BAR_START = "bar_start"
    BAR_END = "bar_end"
    UNKNOWN = "unknown"


class SessionCoverageStatus(str, Enum):
    REGULAR_ONLY = "regular_only"
    REGULAR_AND_EXTENDED = "regular_and_extended"
    UNKNOWN = "unknown"


class PriceAdjustmentStatus(str, Enum):
    RAW = "raw"
    ADJUSTED = "adjusted"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class CorporateActionStatus(str, Enum):
    SEPARATE_EVENTS = "separate_events"
    EMBEDDED_IN_PRICES = "embedded_in_prices"
    NOT_PROVIDED = "not_provided"
    UNKNOWN = "unknown"


class SymbolLifecycleStatus(str, Enum):
    POINT_IN_TIME = "point_in_time"
    HISTORICAL_SYMBOLS_WITHOUT_LIFECYCLE = "historical_symbols_without_lifecycle"
    CURRENT_ONLY = "current_only"
    UNKNOWN = "unknown"


class InventoryIdentityKind(str, Enum):
    IMMUTABLE_REPOSITORY_REVISION = "immutable_repository_revision"
    CONTENT_HASHES = "content_hashes"
    PROVIDER_BATCH_IDENTITY = "provider_batch_identity"
    NONE = "none"


class DatasetAuthorityStatus(str, Enum):
    ACCEPTED_FOR_RESEARCH = "accepted_for_research"
    REFERENCE_ONLY = "reference_only"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class DatasetSourceCandidate:
    candidate_id: str
    source_kind: DatasetSourceKind
    locator: str
    provider_name: str
    market: str
    frequency: str

    def __post_init__(self) -> None:
        candidate_id = self.candidate_id.strip().lower()
        locator = self.locator.strip()
        provider_name = self.provider_name.strip()
        market = self.market.strip().lower()
        frequency = self.frequency.strip().lower()
        if not all((candidate_id, locator, provider_name, market, frequency)):
            raise ValueError("dataset source candidate fields must be non-empty")
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "locator", locator)
        object.__setattr__(self, "provider_name", provider_name)
        object.__setattr__(self, "market", market)
        object.__setattr__(self, "frequency", frequency)

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "source_kind": self.source_kind.value,
            "locator": self.locator,
            "provider_name": self.provider_name,
            "market": self.market,
            "frequency": self.frequency,
        }


@dataclass(frozen=True, slots=True)
class DatasetRevision:
    kind: DatasetRevisionKind
    value: str
    immutable: bool

    def __post_init__(self) -> None:
        value = self.value.strip().lower()
        if not value:
            raise ValueError("dataset revision value must be non-empty")
        if self.kind is DatasetRevisionKind.GIT_COMMIT and not _GIT_SHA_RE.fullmatch(value):
            raise ValueError("git dataset revision must be a full 40-character lowercase SHA")
        if self.kind is DatasetRevisionKind.CONTENT_HASH and not _SHA256_RE.fullmatch(value):
            raise ValueError("content-hash dataset revision must be a 64-character SHA-256")
        object.__setattr__(self, "value", value)

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind.value, "value": self.value, "immutable": self.immutable}


@dataclass(frozen=True, slots=True)
class DatasetFileDescriptor:
    relative_path: str
    size_bytes: int | None = None
    sha256: str = ""
    remote_oid: str = ""

    def __post_init__(self) -> None:
        relative_path = self.relative_path.strip().replace("\\", "/")
        if not relative_path or relative_path.startswith("/") or ".." in Path(relative_path).parts:
            raise ValueError("dataset file descriptor requires a safe relative path")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("dataset file size cannot be negative")
        sha256 = self.sha256.strip().lower()
        if sha256 and not _SHA256_RE.fullmatch(sha256):
            raise ValueError("dataset file sha256 must be a 64-character lowercase digest")
        object.__setattr__(self, "relative_path", relative_path)
        object.__setattr__(self, "sha256", sha256)
        object.__setattr__(self, "remote_oid", self.remote_oid.strip())

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256 or None,
            "remote_oid": self.remote_oid or None,
        }


@dataclass(frozen=True, slots=True)
class DatasetProvenanceRecord:
    candidate: DatasetSourceCandidate
    revision: DatasetRevision
    upstream_origin: str
    origin_status: OriginVerificationStatus
    schema_fields: tuple[str, ...]
    partitioning: str
    coverage_start: str
    coverage_end: str
    timezone: str
    timestamp_meaning: TimestampMeaning
    session_coverage: SessionCoverageStatus
    price_adjustment: PriceAdjustmentStatus
    corporate_actions: CorporateActionStatus
    symbol_lifecycle: SymbolLifecycleStatus
    inventory_complete: bool
    inventory_identity: InventoryIdentityKind
    files: tuple[DatasetFileDescriptor, ...]
    observed_at: datetime
    evidence_urls: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        upstream_origin = self.upstream_origin.strip()
        partitioning = self.partitioning.strip()
        coverage_start = self.coverage_start.strip()
        coverage_end = self.coverage_end.strip()
        timezone = self.timezone.strip()
        schema_fields = tuple(dict.fromkeys(field.strip().lower() for field in self.schema_fields))
        if not all((upstream_origin, partitioning, coverage_start, coverage_end, timezone)):
            raise ValueError(
                "provenance origin/partition/coverage/timezone fields must be non-empty"
            )
        if any(not field for field in schema_fields):
            raise ValueError("schema fields cannot contain empty values")
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("dataset provenance contains duplicate file descriptors")
        if self.inventory_complete and not self.files:
            raise ValueError("complete inventory must contain file descriptors")
        if self.inventory_identity is InventoryIdentityKind.CONTENT_HASHES:
            if not self.files:
                raise ValueError("content-hash inventory identity requires at least one file")
            if any(not item.sha256 for item in self.files):
                raise ValueError("content-hash inventory identity requires SHA-256 for every file")
        object.__setattr__(self, "upstream_origin", upstream_origin)
        object.__setattr__(self, "partitioning", partitioning)
        object.__setattr__(self, "coverage_start", coverage_start)
        object.__setattr__(self, "coverage_end", coverage_end)
        object.__setattr__(self, "timezone", timezone)
        object.__setattr__(self, "schema_fields", schema_fields)
        object.__setattr__(self, "files", tuple(self.files))
        object.__setattr__(self, "observed_at", _aware(self.observed_at, field_name="observed_at"))
        object.__setattr__(
            self,
            "evidence_urls",
            tuple(url.strip() for url in self.evidence_urls if url.strip()),
        )
        object.__setattr__(
            self,
            "notes",
            tuple(str(note).strip() for note in self.notes if str(note).strip()),
        )

    @property
    def provenance_id(self) -> str:
        payload = self.to_dict(include_observed_at=False)
        return _canonical_hash(payload, prefix="dataset-provenance")

    def to_dict(self, *, include_observed_at: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "candidate": self.candidate.to_dict(),
            "revision": self.revision.to_dict(),
            "upstream_origin": self.upstream_origin,
            "origin_status": self.origin_status.value,
            "schema_fields": list(self.schema_fields),
            "partitioning": self.partitioning,
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "timezone": self.timezone,
            "timestamp_meaning": self.timestamp_meaning.value,
            "session_coverage": self.session_coverage.value,
            "price_adjustment": self.price_adjustment.value,
            "corporate_actions": self.corporate_actions.value,
            "symbol_lifecycle": self.symbol_lifecycle.value,
            "inventory_complete": self.inventory_complete,
            "inventory_identity": self.inventory_identity.value,
            "files": [item.to_dict() for item in self.files],
            "evidence_urls": list(self.evidence_urls),
            "notes": list(self.notes),
        }
        if include_observed_at:
            payload["observed_at"] = self.observed_at.isoformat()
            payload["provenance_id"] = self.provenance_id
        return payload


@dataclass(frozen=True, slots=True)
class DatasetUsageRightsRecord:
    status: UsageRightsStatus
    evidence_url: str
    license_identifier: str
    observed_at: datetime
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        evidence_url = self.evidence_url.strip()
        if not evidence_url:
            raise ValueError("usage-rights evidence_url must be non-empty")
        object.__setattr__(self, "evidence_url", evidence_url)
        object.__setattr__(self, "license_identifier", self.license_identifier.strip())
        object.__setattr__(self, "observed_at", _aware(self.observed_at, field_name="observed_at"))
        object.__setattr__(
            self,
            "notes",
            tuple(str(note).strip() for note in self.notes if str(note).strip()),
        )

    @property
    def usage_rights_id(self) -> str:
        return _canonical_hash(self.to_dict(include_observed_at=False), prefix="dataset-rights")

    def to_dict(self, *, include_observed_at: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status.value,
            "evidence_url": self.evidence_url,
            "license_identifier": self.license_identifier or None,
            "notes": list(self.notes),
        }
        if include_observed_at:
            payload["observed_at"] = self.observed_at.isoformat()
            payload["usage_rights_id"] = self.usage_rights_id
        return payload


@dataclass(frozen=True, slots=True)
class DatasetAuthorityDecision:
    status: DatasetAuthorityStatus
    provenance_id: str
    usage_rights_id: str
    blocking_issues: tuple[str, ...]
    rationale: str
    decided_at: datetime

    def __post_init__(self) -> None:
        if not self.provenance_id.strip() or not self.usage_rights_id.strip():
            raise ValueError("authority decision must bind provenance and usage-rights identities")
        blockers = tuple(
            dict.fromkeys(issue.strip() for issue in self.blocking_issues if issue.strip())
        )
        if self.status is DatasetAuthorityStatus.ACCEPTED_FOR_RESEARCH and blockers:
            raise ValueError("accepted research source cannot contain blocking issues")
        if self.status is not DatasetAuthorityStatus.ACCEPTED_FOR_RESEARCH and not blockers:
            raise ValueError("non-accepted source decision must state at least one blocking issue")
        rationale = self.rationale.strip()
        if not rationale:
            raise ValueError("authority decision rationale must be non-empty")
        object.__setattr__(self, "blocking_issues", blockers)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "decided_at", _aware(self.decided_at, field_name="decided_at"))

    @property
    def decision_id(self) -> str:
        return _canonical_hash(self.to_dict(include_decided_at=False), prefix="dataset-authority")

    def to_dict(self, *, include_decided_at: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status.value,
            "provenance_id": self.provenance_id,
            "usage_rights_id": self.usage_rights_id,
            "blocking_issues": list(self.blocking_issues),
            "rationale": self.rationale,
        }
        if include_decided_at:
            payload["decided_at"] = self.decided_at.isoformat()
            payload["decision_id"] = self.decision_id
        return payload


@dataclass(frozen=True, slots=True)
class DatasetSourceIdentity:
    candidate_id: str
    revision_kind: DatasetRevisionKind
    revision: str
    provenance_id: str
    authority_decision_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "revision_kind": self.revision_kind.value,
            "revision": self.revision,
            "provenance_id": self.provenance_id,
            "authority_decision_id": self.authority_decision_id,
        }


@dataclass(frozen=True, slots=True)
class DatasetAuthorityBundle:
    provenance: DatasetProvenanceRecord
    usage_rights: DatasetUsageRightsRecord
    decision: DatasetAuthorityDecision
    schema_version: str = "finagent.dataset-authority-bundle.v1"

    def __post_init__(self) -> None:
        if self.decision.provenance_id != self.provenance.provenance_id:
            raise ValueError("authority decision provenance identity mismatch")
        if self.decision.usage_rights_id != self.usage_rights.usage_rights_id:
            raise ValueError("authority decision usage-rights identity mismatch")

    @property
    def bundle_id(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "provenance_id": self.provenance.provenance_id,
            "usage_rights_id": self.usage_rights.usage_rights_id,
            "decision_id": self.decision.decision_id,
        }
        return _canonical_hash(payload, prefix="dataset-authority-bundle")

    def source_identity(self) -> DatasetSourceIdentity:
        return DatasetSourceIdentity(
            candidate_id=self.provenance.candidate.candidate_id,
            revision_kind=self.provenance.revision.kind,
            revision=self.provenance.revision.value,
            provenance_id=self.provenance.provenance_id,
            authority_decision_id=self.decision.decision_id,
        )

    def require_research_authority(self) -> DatasetSourceIdentity:
        if self.decision.status is not DatasetAuthorityStatus.ACCEPTED_FOR_RESEARCH:
            blockers = ", ".join(self.decision.blocking_issues)
            raise PermissionError(
                f"dataset source {self.provenance.candidate.candidate_id!r} is "
                f"{self.decision.status.value}, not accepted_for_research; blockers: {blockers}"
            )
        return self.source_identity()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "bundle_id": self.bundle_id,
            "source_identity": self.source_identity().to_dict(),
            "provenance": self.provenance.to_dict(),
            "usage_rights": self.usage_rights.to_dict(),
            "decision": self.decision.to_dict(),
        }

    def write_json(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return output

    @classmethod
    def read_json(cls, path: str | Path) -> DatasetAuthorityBundle:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema_version") != "finagent.dataset-authority-bundle.v1":
            raise ValueError("unsupported dataset authority bundle schema")
        bundle = _bundle_from_dict(payload)
        expected = str(payload.get("bundle_id", ""))
        if expected and expected != bundle.bundle_id:
            raise ValueError("dataset authority bundle identity mismatch")
        return bundle


def evaluate_dataset_authority(
    provenance: DatasetProvenanceRecord,
    usage_rights: DatasetUsageRightsRecord,
    *,
    decided_at: datetime | None = None,
) -> DatasetAuthorityDecision:
    blockers: list[str] = []

    if not provenance.revision.immutable:
        blockers.append("revision:not_immutable")
    if provenance.origin_status is OriginVerificationStatus.DECLARED_BY_PUBLISHER:
        blockers.append("upstream_origin:declared_only")
    elif provenance.origin_status is OriginVerificationStatus.UNKNOWN:
        blockers.append("upstream_origin:unknown")

    if usage_rights.status is not UsageRightsStatus.VERIFIED_RESEARCH_USE:
        blockers.append(f"usage_rights:{usage_rights.status.value}")

    missing_schema = sorted(_REQUIRED_OHLCV_FIELDS.difference(provenance.schema_fields))
    if missing_schema:
        blockers.append("schema:missing:" + ",".join(missing_schema))
    if provenance.timestamp_meaning is TimestampMeaning.UNKNOWN:
        blockers.append("timestamp_meaning:unknown")
    if provenance.session_coverage is SessionCoverageStatus.UNKNOWN:
        blockers.append("session_coverage:unknown")
    if provenance.price_adjustment is PriceAdjustmentStatus.UNKNOWN:
        blockers.append("price_adjustment:unknown")
    if provenance.corporate_actions is CorporateActionStatus.UNKNOWN:
        blockers.append("corporate_actions:unknown")
    if provenance.symbol_lifecycle is SymbolLifecycleStatus.UNKNOWN:
        blockers.append("symbol_lifecycle:unknown")
    if provenance.inventory_identity is InventoryIdentityKind.NONE:
        blockers.append("inventory_identity:none")
    if provenance.inventory_complete and not provenance.files:
        blockers.append("inventory:empty")

    if usage_rights.status is UsageRightsStatus.PROHIBITED:
        status = DatasetAuthorityStatus.REJECTED
        rationale = "Usage evidence explicitly prohibits the intended research use."
    elif blockers:
        status = DatasetAuthorityStatus.REFERENCE_ONLY
        rationale = (
            "Candidate remains diagnostic/reference metadata until every blocking source-authority "
            "dimension is resolved and re-reviewed."
        )
    else:
        status = DatasetAuthorityStatus.ACCEPTED_FOR_RESEARCH
        rationale = "All US-S0 source-authority requirements are explicitly resolved."

    return DatasetAuthorityDecision(
        status=status,
        provenance_id=provenance.provenance_id,
        usage_rights_id=usage_rights.usage_rights_id,
        blocking_issues=tuple(blockers),
        rationale=rationale,
        decided_at=decided_at or datetime.now(UTC),
    )


def _parse_datetime(value: object) -> datetime:
    text = str(value).strip().replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _bundle_from_dict(payload: dict[str, Any]) -> DatasetAuthorityBundle:
    prov = payload["provenance"]
    candidate_raw = prov["candidate"]
    revision_raw = prov["revision"]
    candidate = DatasetSourceCandidate(
        candidate_id=str(candidate_raw["candidate_id"]),
        source_kind=DatasetSourceKind(str(candidate_raw["source_kind"])),
        locator=str(candidate_raw["locator"]),
        provider_name=str(candidate_raw["provider_name"]),
        market=str(candidate_raw["market"]),
        frequency=str(candidate_raw["frequency"]),
    )
    revision = DatasetRevision(
        kind=DatasetRevisionKind(str(revision_raw["kind"])),
        value=str(revision_raw["value"]),
        immutable=bool(revision_raw["immutable"]),
    )
    files = tuple(
        DatasetFileDescriptor(
            relative_path=str(item["relative_path"]),
            size_bytes=int(item["size_bytes"]) if item.get("size_bytes") is not None else None,
            sha256=str(item.get("sha256") or ""),
            remote_oid=str(item.get("remote_oid") or ""),
        )
        for item in prov.get("files", [])
    )
    provenance = DatasetProvenanceRecord(
        candidate=candidate,
        revision=revision,
        upstream_origin=str(prov["upstream_origin"]),
        origin_status=OriginVerificationStatus(str(prov["origin_status"])),
        schema_fields=tuple(str(value) for value in prov["schema_fields"]),
        partitioning=str(prov["partitioning"]),
        coverage_start=str(prov["coverage_start"]),
        coverage_end=str(prov["coverage_end"]),
        timezone=str(prov["timezone"]),
        timestamp_meaning=TimestampMeaning(str(prov["timestamp_meaning"])),
        session_coverage=SessionCoverageStatus(str(prov["session_coverage"])),
        price_adjustment=PriceAdjustmentStatus(str(prov["price_adjustment"])),
        corporate_actions=CorporateActionStatus(str(prov["corporate_actions"])),
        symbol_lifecycle=SymbolLifecycleStatus(str(prov["symbol_lifecycle"])),
        inventory_complete=bool(prov["inventory_complete"]),
        inventory_identity=InventoryIdentityKind(str(prov["inventory_identity"])),
        files=files,
        observed_at=_parse_datetime(prov["observed_at"]),
        evidence_urls=tuple(str(value) for value in prov.get("evidence_urls", [])),
        notes=tuple(str(value) for value in prov.get("notes", [])),
    )
    rights_raw = payload["usage_rights"]
    usage_rights = DatasetUsageRightsRecord(
        status=UsageRightsStatus(str(rights_raw["status"])),
        evidence_url=str(rights_raw["evidence_url"]),
        license_identifier=str(rights_raw.get("license_identifier") or ""),
        observed_at=_parse_datetime(rights_raw["observed_at"]),
        notes=tuple(str(value) for value in rights_raw.get("notes", [])),
    )
    decision_raw = payload["decision"]
    decision = DatasetAuthorityDecision(
        status=DatasetAuthorityStatus(str(decision_raw["status"])),
        provenance_id=str(decision_raw["provenance_id"]),
        usage_rights_id=str(decision_raw["usage_rights_id"]),
        blocking_issues=tuple(str(value) for value in decision_raw["blocking_issues"]),
        rationale=str(decision_raw["rationale"]),
        decided_at=_parse_datetime(decision_raw["decided_at"]),
    )
    return DatasetAuthorityBundle(
        provenance=provenance, usage_rights=usage_rights, decision=decision
    )

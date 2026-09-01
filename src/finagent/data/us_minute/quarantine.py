from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from finagent.data.provenance import (
    DatasetAuthorityBundle,
    DatasetAuthorityStatus,
)

from .cleaning import (
    LocalMinuteResearchAdmission,
    LocalMinuteResearchCertification,
    MinuteDataCleaningPolicy,
    MinuteSampleQuality,
    certify_local_minute_research_snapshot,
)


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


CONFLICT_TOLERANT_BASE_POLICY = MinuteDataCleaningPolicy(
    max_invalid_ohlc_rate=1e-6,
    max_exact_duplicate_extra_row_rate=1e-4,
    invalid_ohlc_action="drop",
    exact_duplicate_action="collapse_full_row",
    reject_conflicting_duplicate_keys=False,
    reject_invalid_identity_rows=True,
    reject_negative_or_null_volume=True,
    schema_version="finagent.us-minute-cleaning-policy.v2",
)


@dataclass(frozen=True, slots=True)
class ConflictGroupQuarantinePolicy:
    """Bounded policy for ambiguous duplicate minute groups.

    A conflicting `(ticker, timestamp)` group has no source metadata that proves which
    row is authoritative. The only generic v1 action is therefore to remove the whole
    key group and preserve an explicit gap. The rate ceiling prevents quarantine from
    masking structural corruption.
    """

    max_conflicting_raw_row_rate: float = 5e-5
    action: str = "drop_entire_key_group"
    schema_version: str = "finagent.us-minute-conflict-quarantine-policy.v1"

    def __post_init__(self) -> None:
        if not 0 <= self.max_conflicting_raw_row_rate < 1:
            raise ValueError("max_conflicting_raw_row_rate must be in [0, 1)")
        if self.action != "drop_entire_key_group":
            raise ValueError("v1 conflict quarantine only supports drop_entire_key_group")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-minute-conflict-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "max_conflicting_raw_row_rate": self.max_conflicting_raw_row_rate,
            "action": self.action,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


DEFAULT_CONFLICT_QUARANTINE_POLICY = ConflictGroupQuarantinePolicy()


def conflicting_raw_row_count(sample: MinuteSampleQuality) -> int:
    return sample.conflicting_duplicate_key_count + sample.conflicting_duplicate_extra_row_count


def conflicting_raw_row_rate(sample: MinuteSampleQuality) -> float:
    return conflicting_raw_row_count(sample) / sample.row_count if sample.row_count else 1.0


@dataclass(frozen=True, slots=True)
class LocalMinuteQuarantineCertification:
    base: LocalMinuteResearchCertification
    quarantine_policy: ConflictGroupQuarantinePolicy
    certified_at: datetime
    schema_version: str = "finagent.us-minute-local-certification.v3"

    @property
    def passed(self) -> bool:
        return self.base.passed and all(
            conflicting_raw_row_rate(sample)
            <= self.quarantine_policy.max_conflicting_raw_row_rate
            for sample in self.base.sample_checks
        )

    @property
    def quarantined_conflicting_key_count(self) -> int:
        return sum(sample.conflicting_duplicate_key_count for sample in self.base.sample_checks)

    @property
    def quarantined_conflicting_raw_row_count(self) -> int:
        return sum(conflicting_raw_row_count(sample) for sample in self.base.sample_checks)

    @property
    def cleaning_identity(self) -> str:
        payload: dict[str, object] = {
            "base_cleaning_policy_id": self.base.cleaning_policy.policy_id,
            "conflict_quarantine_policy_id": self.quarantine_policy.policy_id,
        }
        return _canonical_hash(payload, prefix="us-minute-cleaning-stack")

    @property
    def certification_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "base_certification_id": self.base.certification_id,
            "quarantine_policy_id": self.quarantine_policy.policy_id,
            "sample_conflict_rates": [
                {
                    "month": sample.month,
                    "conflicting_raw_row_count": conflicting_raw_row_count(sample),
                    "conflicting_raw_row_rate": conflicting_raw_row_rate(sample),
                }
                for sample in self.base.sample_checks
            ],
        }
        return _canonical_hash(payload, prefix="us-minute-certification")

    def to_dict(self) -> dict[str, object]:
        base_payload = self.base.to_dict()
        sample_payloads: list[dict[str, object]] = []
        for sample in self.base.sample_checks:
            payload = sample.to_dict(self.base.cleaning_policy)
            payload["conflicting_raw_row_count"] = conflicting_raw_row_count(sample)
            payload["conflicting_raw_row_rate"] = conflicting_raw_row_rate(sample)
            payload["conflict_quarantine_passed"] = (
                conflicting_raw_row_rate(sample)
                <= self.quarantine_policy.max_conflicting_raw_row_rate
            )
            sample_payloads.append(payload)
        base_payload["sample_checks"] = sample_payloads
        return {
            "schema_version": self.schema_version,
            "certification_id": self.certification_id,
            "cleaning_identity": self.cleaning_identity,
            "passed": self.passed,
            "base_certification": base_payload,
            "conflict_quarantine_policy": self.quarantine_policy.to_dict(),
            "quarantined_conflicting_key_count": self.quarantined_conflicting_key_count,
            "quarantined_conflicting_raw_row_count": self.quarantined_conflicting_raw_row_count,
            "post_clean_conflicting_duplicate_key_count": 0 if self.passed else None,
            "certified_at": self.certified_at.astimezone(UTC).isoformat(),
        }


def certify_local_minute_snapshot_with_conflict_quarantine(
    root: str | Path,
    *,
    expected_revision: str,
    expected_coverage_start: str,
    expected_coverage_end: str,
    sample_months: tuple[str, ...] | None = None,
    quarantine_policy: ConflictGroupQuarantinePolicy = DEFAULT_CONFLICT_QUARANTINE_POLICY,
    certified_at: datetime | None = None,
) -> LocalMinuteQuarantineCertification:
    timestamp = certified_at or datetime.now(UTC)
    base = certify_local_minute_research_snapshot(
        root,
        expected_revision=expected_revision,
        expected_coverage_start=expected_coverage_start,
        expected_coverage_end=expected_coverage_end,
        sample_months=sample_months,
        cleaning_policy=CONFLICT_TOLERANT_BASE_POLICY,
        certified_at=timestamp,
    )
    return LocalMinuteQuarantineCertification(
        base=base,
        quarantine_policy=quarantine_policy,
        certified_at=timestamp,
    )


def quarantined_clean_month_select_sql(path: str | Path) -> str:
    """Canonical admitted read: clean rows plus whole-group conflict quarantine."""

    literal = "'" + Path(path).as_posix().replace("'", "''") + "'"
    return f"""
        WITH base AS (
            SELECT timestamp, open, high, low, close, volume, ticker
            FROM read_parquet({literal})
        ),
        conflicting_keys AS (
            SELECT ticker, timestamp
            FROM base
            GROUP BY ticker, timestamp
            HAVING COUNT(DISTINCT struct_pack(
                open := open,
                high := high,
                low := low,
                close := close,
                volume := volume
            )) > 1
        )
        SELECT DISTINCT
            b.timestamp, b.open, b.high, b.low, b.close, b.volume, b.ticker
        FROM base AS b
        WHERE b.timestamp IS NOT NULL
          AND b.ticker IS NOT NULL
          AND TRIM(b.ticker) <> ''
          AND b.open IS NOT NULL
          AND b.high IS NOT NULL
          AND b.low IS NOT NULL
          AND b.close IS NOT NULL
          AND b.open > 0
          AND b.high > 0
          AND b.low > 0
          AND b.close > 0
          AND b.high >= GREATEST(b.open, b.low, b.close)
          AND b.low <= LEAST(b.open, b.high, b.close)
          AND b.volume IS NOT NULL
          AND b.volume >= 0
          AND NOT EXISTS (
              SELECT 1
              FROM conflicting_keys AS c
              WHERE c.ticker IS NOT DISTINCT FROM b.ticker
                AND c.timestamp IS NOT DISTINCT FROM b.timestamp
          )
    """.strip()


def admit_local_research_with_conflict_quarantine(
    bundle: DatasetAuthorityBundle,
    certification: LocalMinuteQuarantineCertification,
    *,
    admitted_at: datetime | None = None,
) -> LocalMinuteResearchAdmission:
    if bundle.decision.status is DatasetAuthorityStatus.REJECTED:
        raise PermissionError("rejected dataset source cannot receive local research admission")
    if not certification.passed:
        raise PermissionError("local minute quarantine certification did not pass")
    if certification.base.revision != bundle.provenance.revision.value:
        raise ValueError("local snapshot revision does not match source authority revision")

    limitations = list(bundle.decision.blocking_issues)
    limitations.extend(
        [
            "scope:local_non_redistributed_research_only",
            "prices:intraday_raw_split_unadjusted",
            "corporate_actions:not_embedded_in_ohlcv",
            "symbol_lifecycle:no_point_in_time_security_master",
            "quality:certification_is_sampled_not_full_corpus_row_scan",
            "cleaning:drop_sparse_invalid_ohlc_rows",
            "cleaning:collapse_exact_duplicate_full_rows",
            "cleaning:quarantine_entire_conflicting_duplicate_key_group",
            f"cleaning_stack:{certification.cleaning_identity}",
        ]
    )
    if certification.base.extended_hours_observed:
        limitations.append("session:extended_hours_observed_in_certification_samples")
    if "session:outside_0400_2000_observed" in certification.base.warning_codes:
        limitations.append("session:outside_0400_2000_observed_diagnostic_only")

    return LocalMinuteResearchAdmission(
        source_identity=bundle.source_identity(),
        source_authority_status=bundle.decision.status,
        certification_id=certification.certification_id,
        inventory_id=certification.base.inventory_id,
        cleaning_policy_id=certification.cleaning_identity,
        scope="local_non_redistributed_research",
        limitations=tuple(dict.fromkeys(limitations)),
        admitted_at=admitted_at or datetime.now(UTC),
        schema_version="finagent.us-minute-local-research-admission.v3",
    )

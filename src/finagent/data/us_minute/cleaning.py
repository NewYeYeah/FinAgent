from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from finagent.data.provenance import (
    DatasetAuthorityBundle,
    DatasetAuthorityStatus,
    DatasetSourceIdentity,
)

from .local_snapshot import (
    HuggingFaceSnapshotLayout,
    LocalMinuteFile,
    LocalMinuteInventory,
    inventory_monthly_parquet,
)

_NEW_YORK = ZoneInfo("America/New_York")
_PREMARKET_OPEN = time(4, 0)
_REGULAR_OPEN = time(9, 30)
_REGULAR_CLOSE = time(16, 0)
_AFTER_HOURS_CLOSE = time(20, 0)


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class MinuteDataCleaningPolicy:
    """Identity-bound cleaning policy for local OHLCV-1m engineering research.

    Sparse, deterministic data defects may be quarantined instead of rejecting an
    otherwise useful multi-decade snapshot. Structural ambiguity remains fail-closed.
    """

    max_invalid_ohlc_rate: float = 1e-6
    max_exact_duplicate_extra_row_rate: float = 1e-4
    invalid_ohlc_action: str = "drop"
    exact_duplicate_action: str = "collapse_full_row"
    reject_conflicting_duplicate_keys: bool = True
    reject_invalid_identity_rows: bool = True
    reject_negative_or_null_volume: bool = True
    schema_version: str = "finagent.us-minute-cleaning-policy.v1"

    def __post_init__(self) -> None:
        for name, value in (
            ("max_invalid_ohlc_rate", self.max_invalid_ohlc_rate),
            ("max_exact_duplicate_extra_row_rate", self.max_exact_duplicate_extra_row_rate),
        ):
            if not 0 <= value < 1:
                raise ValueError(f"{name} must be in [0, 1)")
        if self.invalid_ohlc_action != "drop":
            raise ValueError("v1 cleaning policy only supports invalid_ohlc_action='drop'")
        if self.exact_duplicate_action != "collapse_full_row":
            raise ValueError(
                "v1 cleaning policy only supports exact_duplicate_action='collapse_full_row'"
            )

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-minute-cleaning-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "max_invalid_ohlc_rate": self.max_invalid_ohlc_rate,
            "max_exact_duplicate_extra_row_rate": self.max_exact_duplicate_extra_row_rate,
            "invalid_ohlc_action": self.invalid_ohlc_action,
            "exact_duplicate_action": self.exact_duplicate_action,
            "reject_conflicting_duplicate_keys": self.reject_conflicting_duplicate_keys,
            "reject_invalid_identity_rows": self.reject_invalid_identity_rows,
            "reject_negative_or_null_volume": self.reject_negative_or_null_volume,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


DEFAULT_MINUTE_CLEANING_POLICY = MinuteDataCleaningPolicy()


@dataclass(frozen=True, slots=True)
class MinuteSampleQuality:
    month: str
    row_count: int
    ticker_count: int
    min_timestamp: str
    max_timestamp: str
    duplicate_key_count: int
    exact_duplicate_key_count: int
    conflicting_duplicate_key_count: int
    exact_duplicate_extra_row_count: int
    conflicting_duplicate_extra_row_count: int
    invalid_identity_count: int
    invalid_ohlc_count: int
    negative_volume_count: int
    outside_regular_hours_count: int
    outside_0400_2000_count: int

    @property
    def invalid_ohlc_rate(self) -> float:
        return self.invalid_ohlc_count / self.row_count if self.row_count else 1.0

    @property
    def exact_duplicate_extra_row_rate(self) -> float:
        return self.exact_duplicate_extra_row_count / self.row_count if self.row_count else 1.0

    def passed(self, policy: MinuteDataCleaningPolicy) -> bool:
        if self.row_count <= 0 or self.ticker_count <= 0:
            return False
        if policy.reject_conflicting_duplicate_keys and self.conflicting_duplicate_key_count:
            return False
        if policy.reject_invalid_identity_rows and self.invalid_identity_count:
            return False
        if policy.reject_negative_or_null_volume and self.negative_volume_count:
            return False
        if self.invalid_ohlc_rate > policy.max_invalid_ohlc_rate:
            return False
        if self.exact_duplicate_extra_row_rate > policy.max_exact_duplicate_extra_row_rate:
            return False
        return True

    def warning_codes(self) -> tuple[str, ...]:
        warnings: list[str] = []
        if self.invalid_ohlc_count:
            warnings.append("quarantine:invalid_ohlc")
        if self.exact_duplicate_extra_row_count:
            warnings.append("collapse:exact_duplicate_rows")
        if self.outside_0400_2000_count:
            warnings.append("session:outside_0400_2000_observed")
        return tuple(warnings)

    def to_dict(self, policy: MinuteDataCleaningPolicy) -> dict[str, object]:
        return {
            "month": self.month,
            "row_count": self.row_count,
            "ticker_count": self.ticker_count,
            "min_timestamp": self.min_timestamp,
            "max_timestamp": self.max_timestamp,
            "duplicate_key_count": self.duplicate_key_count,
            "exact_duplicate_key_count": self.exact_duplicate_key_count,
            "conflicting_duplicate_key_count": self.conflicting_duplicate_key_count,
            "exact_duplicate_extra_row_count": self.exact_duplicate_extra_row_count,
            "conflicting_duplicate_extra_row_count": self.conflicting_duplicate_extra_row_count,
            "invalid_identity_count": self.invalid_identity_count,
            "invalid_ohlc_count": self.invalid_ohlc_count,
            "invalid_ohlc_rate": self.invalid_ohlc_rate,
            "negative_volume_count": self.negative_volume_count,
            "exact_duplicate_extra_row_rate": self.exact_duplicate_extra_row_rate,
            "outside_regular_hours_count": self.outside_regular_hours_count,
            "outside_0400_2000_count": self.outside_0400_2000_count,
            "warning_codes": list(self.warning_codes()),
            "passed": self.passed(policy),
        }


@dataclass(frozen=True, slots=True)
class LocalMinuteResearchCertification:
    revision: str
    inventory_id: str
    coverage_start: str
    coverage_end: str
    expected_coverage_start: str
    expected_coverage_end: str
    schema: tuple[tuple[str, str], ...]
    sample_checks: tuple[MinuteSampleQuality, ...]
    missing_months: tuple[str, ...]
    cleaning_policy: MinuteDataCleaningPolicy
    certified_at: datetime
    schema_version: str = "finagent.us-minute-local-certification.v2"

    @property
    def extended_hours_observed(self) -> bool:
        return any(item.outside_regular_hours_count > 0 for item in self.sample_checks)

    @property
    def warning_codes(self) -> tuple[str, ...]:
        values: list[str] = []
        for item in self.sample_checks:
            values.extend(item.warning_codes())
        return tuple(dict.fromkeys(values))

    @property
    def passed(self) -> bool:
        required_columns = {
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "ticker",
        }
        names = {name.lower() for name, _ in self.schema}
        timestamp_types = {
            kind.upper()
            for name, kind in self.schema
            if name.lower() == "timestamp"
        }
        timestamp_ok = any(
            "TIMESTAMP" in kind and ("TIME ZONE" in kind or "TIMESTAMPTZ" in kind)
            for kind in timestamp_types
        )
        return (
            not self.missing_months
            and self.coverage_start == self.expected_coverage_start
            and self.coverage_end == self.expected_coverage_end
            and required_columns.issubset(names)
            and timestamp_ok
            and bool(self.sample_checks)
            and all(item.passed(self.cleaning_policy) for item in self.sample_checks)
        )

    @property
    def certification_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "revision": self.revision,
            "inventory_id": self.inventory_id,
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "expected_coverage_start": self.expected_coverage_start,
            "expected_coverage_end": self.expected_coverage_end,
            "schema": [list(item) for item in self.schema],
            "sample_checks": [
                item.to_dict(self.cleaning_policy) for item in self.sample_checks
            ],
            "missing_months": list(self.missing_months),
            "cleaning_policy_id": self.cleaning_policy.policy_id,
        }
        return _canonical_hash(payload, prefix="us-minute-certification")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "certification_id": self.certification_id,
            "revision": self.revision,
            "inventory_id": self.inventory_id,
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "expected_coverage_start": self.expected_coverage_start,
            "expected_coverage_end": self.expected_coverage_end,
            "passed": self.passed,
            "extended_hours_observed": self.extended_hours_observed,
            "warning_codes": list(self.warning_codes),
            "missing_months": list(self.missing_months),
            "cleaning_policy": self.cleaning_policy.to_dict(),
            "schema": [{"name": name, "type": kind} for name, kind in self.schema],
            "sample_checks": [
                item.to_dict(self.cleaning_policy) for item in self.sample_checks
            ],
            "certified_at": self.certified_at.astimezone(UTC).isoformat(),
        }

    def write_json(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return output


@dataclass(frozen=True, slots=True)
class LocalMinuteResearchAdmission:
    source_identity: DatasetSourceIdentity
    source_authority_status: DatasetAuthorityStatus
    certification_id: str
    inventory_id: str
    cleaning_policy_id: str
    scope: str
    limitations: tuple[str, ...]
    admitted_at: datetime
    schema_version: str = "finagent.us-minute-local-research-admission.v2"

    @property
    def admission_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "source_identity": self.source_identity.to_dict(),
            "source_authority_status": self.source_authority_status.value,
            "certification_id": self.certification_id,
            "inventory_id": self.inventory_id,
            "cleaning_policy_id": self.cleaning_policy_id,
            "scope": self.scope,
            "limitations": list(self.limitations),
        }
        return _canonical_hash(payload, prefix="us-minute-local-admission")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "admission_id": self.admission_id,
            "source_identity": self.source_identity.to_dict(),
            "source_authority_status": self.source_authority_status.value,
            "certification_id": self.certification_id,
            "inventory_id": self.inventory_id,
            "cleaning_policy_id": self.cleaning_policy_id,
            "scope": self.scope,
            "limitations": list(self.limitations),
            "admitted_at": self.admitted_at.astimezone(UTC).isoformat(),
        }


def _duckdb() -> Any:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - optional dependency boundary
        raise RuntimeError(
            "local U.S. minute certification requires duckdb; install FinAgent "
            "with the development/local-parquet dependencies in the active Conda environment"
        ) from exc
    return duckdb


def _quote_path(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


def _sample_files(
    inventory: LocalMinuteInventory,
    requested: tuple[str, ...] | None,
) -> tuple[LocalMinuteFile, ...]:
    by_month = {item.month: item for item in inventory.files}
    if requested:
        missing = [month for month in requested if month not in by_month]
        if missing:
            raise ValueError("requested sample months not present: " + ", ".join(missing))
        return tuple(by_month[month] for month in dict.fromkeys(requested))
    indices = [0, len(inventory.files) // 2, len(inventory.files) - 1]
    return tuple(inventory.files[index] for index in dict.fromkeys(indices))


def _session_counts(connection: Any, path_literal: str) -> tuple[int, int]:
    minute_buckets = connection.execute(
        f"""
        SELECT
            CAST(FLOOR(epoch(timestamp) / 60) AS BIGINT) AS epoch_minute,
            COUNT(*) AS row_count
        FROM read_parquet({path_literal})
        WHERE timestamp IS NOT NULL
        GROUP BY 1
        """
    ).fetchall()
    outside_regular = 0
    outside_0400_2000 = 0
    for epoch_minute, row_count in minute_buckets:
        utc_dt = datetime.fromtimestamp(int(epoch_minute) * 60, tz=UTC)
        local_clock = utc_dt.astimezone(_NEW_YORK).time().replace(tzinfo=None)
        count = int(row_count)
        if local_clock < _REGULAR_OPEN or local_clock >= _REGULAR_CLOSE:
            outside_regular += count
        if local_clock < _PREMARKET_OPEN or local_clock >= _AFTER_HOURS_CLOSE:
            outside_0400_2000 += count
    return outside_regular, outside_0400_2000


def _quality_row(connection: Any, path_literal: str) -> tuple[Any, ...]:
    query = f"""
        WITH base AS (
            SELECT timestamp, open, high, low, close, volume, ticker
            FROM read_parquet({path_literal})
        ),
        duplicate_groups AS (
            SELECT
                ticker,
                timestamp,
                COUNT(*) AS group_rows,
                MIN(open) AS min_open,
                MAX(open) AS max_open,
                MIN(high) AS min_high,
                MAX(high) AS max_high,
                MIN(low) AS min_low,
                MAX(low) AS max_low,
                MIN(close) AS min_close,
                MAX(close) AS max_close,
                MIN(volume) AS min_volume,
                MAX(volume) AS max_volume
            FROM base
            GROUP BY ticker, timestamp
            HAVING COUNT(*) > 1
        ),
        duplicate_summary AS (
            SELECT
                COUNT(*) AS duplicate_key_count,
                COALESCE(SUM(
                    CASE WHEN
                        min_open IS NOT DISTINCT FROM max_open
                        AND min_high IS NOT DISTINCT FROM max_high
                        AND min_low IS NOT DISTINCT FROM max_low
                        AND min_close IS NOT DISTINCT FROM max_close
                        AND min_volume IS NOT DISTINCT FROM max_volume
                    THEN 1 ELSE 0 END
                ), 0) AS exact_duplicate_key_count,
                COALESCE(SUM(
                    CASE WHEN NOT (
                        min_open IS NOT DISTINCT FROM max_open
                        AND min_high IS NOT DISTINCT FROM max_high
                        AND min_low IS NOT DISTINCT FROM max_low
                        AND min_close IS NOT DISTINCT FROM max_close
                        AND min_volume IS NOT DISTINCT FROM max_volume
                    ) THEN 1 ELSE 0 END
                ), 0) AS conflicting_duplicate_key_count,
                COALESCE(SUM(
                    CASE WHEN
                        min_open IS NOT DISTINCT FROM max_open
                        AND min_high IS NOT DISTINCT FROM max_high
                        AND min_low IS NOT DISTINCT FROM max_low
                        AND min_close IS NOT DISTINCT FROM max_close
                        AND min_volume IS NOT DISTINCT FROM max_volume
                    THEN group_rows - 1 ELSE 0 END
                ), 0) AS exact_duplicate_extra_row_count,
                COALESCE(SUM(
                    CASE WHEN NOT (
                        min_open IS NOT DISTINCT FROM max_open
                        AND min_high IS NOT DISTINCT FROM max_high
                        AND min_low IS NOT DISTINCT FROM max_low
                        AND min_close IS NOT DISTINCT FROM max_close
                        AND min_volume IS NOT DISTINCT FROM max_volume
                    ) THEN group_rows - 1 ELSE 0 END
                ), 0) AS conflicting_duplicate_extra_row_count
            FROM duplicate_groups
        )
        SELECT
            COUNT(*) AS row_count,
            COUNT(DISTINCT ticker) AS ticker_count,
            MIN(epoch(timestamp)) AS min_epoch,
            MAX(epoch(timestamp)) AS max_epoch,
            (SELECT duplicate_key_count FROM duplicate_summary),
            (SELECT exact_duplicate_key_count FROM duplicate_summary),
            (SELECT conflicting_duplicate_key_count FROM duplicate_summary),
            (SELECT exact_duplicate_extra_row_count FROM duplicate_summary),
            (SELECT conflicting_duplicate_extra_row_count FROM duplicate_summary),
            SUM(CASE
                WHEN timestamp IS NULL OR ticker IS NULL OR TRIM(ticker) = ''
                THEN 1 ELSE 0
            END) AS invalid_identity_count,
            SUM(CASE
                WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                  OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
                  OR high < GREATEST(open, low, close)
                  OR low > LEAST(open, high, close)
                THEN 1 ELSE 0
            END) AS invalid_ohlc_count,
            SUM(CASE WHEN volume IS NULL OR volume < 0 THEN 1 ELSE 0 END)
                AS negative_volume_count
        FROM base
    """
    row = connection.execute(query).fetchone()
    assert row is not None
    return tuple(row)


def certify_local_minute_research_snapshot(
    root: str | Path,
    *,
    expected_revision: str,
    expected_coverage_start: str,
    expected_coverage_end: str,
    sample_months: tuple[str, ...] | None = None,
    cleaning_policy: MinuteDataCleaningPolicy = DEFAULT_MINUTE_CLEANING_POLICY,
    certified_at: datetime | None = None,
) -> LocalMinuteResearchCertification:
    layout = HuggingFaceSnapshotLayout.resolve(root, expected_revision=expected_revision)
    inventory = inventory_monthly_parquet(layout)
    duckdb = _duckdb()
    connection = duckdb.connect(database=":memory:")

    try:
        first_path = _quote_path(inventory.files[0].path)
        description = connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet({first_path})"
        ).fetchall()
        schema = tuple((str(row[0]), str(row[1])) for row in description)

        checks: list[MinuteSampleQuality] = []
        for item in _sample_files(inventory, sample_months):
            path_literal = _quote_path(item.path)
            row = _quality_row(connection, path_literal)
            outside_regular, outside_0400_2000 = _session_counts(connection, path_literal)
            min_timestamp = (
                datetime.fromtimestamp(float(row[2]), tz=UTC).isoformat()
                if row[2] is not None
                else ""
            )
            max_timestamp = (
                datetime.fromtimestamp(float(row[3]), tz=UTC).isoformat()
                if row[3] is not None
                else ""
            )
            checks.append(
                MinuteSampleQuality(
                    month=item.month,
                    row_count=int(row[0]),
                    ticker_count=int(row[1]),
                    min_timestamp=min_timestamp,
                    max_timestamp=max_timestamp,
                    duplicate_key_count=int(row[4] or 0),
                    exact_duplicate_key_count=int(row[5] or 0),
                    conflicting_duplicate_key_count=int(row[6] or 0),
                    exact_duplicate_extra_row_count=int(row[7] or 0),
                    conflicting_duplicate_extra_row_count=int(row[8] or 0),
                    invalid_identity_count=int(row[9] or 0),
                    invalid_ohlc_count=int(row[10] or 0),
                    negative_volume_count=int(row[11] or 0),
                    outside_regular_hours_count=outside_regular,
                    outside_0400_2000_count=outside_0400_2000,
                )
            )
    finally:
        connection.close()

    return LocalMinuteResearchCertification(
        revision=layout.revision,
        inventory_id=inventory.inventory_id,
        coverage_start=inventory.start_month,
        coverage_end=inventory.end_month,
        expected_coverage_start=expected_coverage_start,
        expected_coverage_end=expected_coverage_end,
        schema=schema,
        sample_checks=tuple(checks),
        missing_months=inventory.missing_months,
        cleaning_policy=cleaning_policy,
        certified_at=certified_at or datetime.now(UTC),
    )


def clean_month_select_sql(path: str | Path) -> str:
    """Build the canonical v1 clean read used after certification.

    Exact duplicate full rows collapse under DISTINCT. Sparse invalid OHLC rows are
    quarantined. Conflicting duplicate keys are not silently resolved; certification
    must reject them before this query is used as research input.
    """

    literal = _quote_path(Path(path))
    return f"""
        SELECT DISTINCT timestamp, open, high, low, close, volume, ticker
        FROM read_parquet({literal})
        WHERE timestamp IS NOT NULL
          AND ticker IS NOT NULL
          AND TRIM(ticker) <> ''
          AND open IS NOT NULL
          AND high IS NOT NULL
          AND low IS NOT NULL
          AND close IS NOT NULL
          AND open > 0
          AND high > 0
          AND low > 0
          AND close > 0
          AND high >= GREATEST(open, low, close)
          AND low <= LEAST(open, high, close)
          AND volume IS NOT NULL
          AND volume >= 0
    """.strip()


def admit_local_research_with_cleaning(
    bundle: DatasetAuthorityBundle,
    certification: LocalMinuteResearchCertification,
    *,
    admitted_at: datetime | None = None,
) -> LocalMinuteResearchAdmission:
    if bundle.decision.status is DatasetAuthorityStatus.REJECTED:
        raise PermissionError("rejected dataset source cannot receive local research admission")
    if not certification.passed:
        raise PermissionError("local minute research certification did not pass")
    if certification.revision != bundle.provenance.revision.value:
        raise ValueError("local snapshot revision does not match source authority revision")

    limitations = list(bundle.decision.blocking_issues)
    limitations.extend(
        [
            "scope:local_non_redistributed_research_only",
            "prices:intraday_raw_split_unadjusted",
            "corporate_actions:not_embedded_in_ohlcv",
            "symbol_lifecycle:no_point_in_time_security_master",
            "quality:certification_is_sampled_not_full_corpus_row_scan",
            f"cleaning_policy:{certification.cleaning_policy.policy_id}",
        ]
    )
    if certification.extended_hours_observed:
        limitations.append("session:extended_hours_observed_in_certification_samples")
    if "session:outside_0400_2000_observed" in certification.warning_codes:
        limitations.append("session:outside_0400_2000_observed_diagnostic_only")
    if "quarantine:invalid_ohlc" in certification.warning_codes:
        limitations.append("cleaning:drop_sparse_invalid_ohlc_rows")
    if "collapse:exact_duplicate_rows" in certification.warning_codes:
        limitations.append("cleaning:collapse_exact_duplicate_full_rows")

    return LocalMinuteResearchAdmission(
        source_identity=bundle.source_identity(),
        source_authority_status=bundle.decision.status,
        certification_id=certification.certification_id,
        inventory_id=certification.inventory_id,
        cleaning_policy_id=certification.cleaning_policy.policy_id,
        scope="local_non_redistributed_research",
        limitations=tuple(dict.fromkeys(limitations)),
        admitted_at=admitted_at or datetime.now(UTC),
    )

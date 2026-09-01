from __future__ import annotations

import hashlib
import json
import re
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

_MONTH_RE = re.compile(r"^ohlcv_(\d{4})-(\d{2})\.parquet$")
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


def _month_index(year: int, month: int) -> int:
    if not 1 <= month <= 12:
        raise ValueError("month must be in 1..12")
    return year * 12 + month - 1


def _month_label(index: int) -> str:
    year, zero_month = divmod(index, 12)
    return f"{year:04d}-{zero_month + 1:02d}"


@dataclass(frozen=True, slots=True)
class HuggingFaceSnapshotLayout:
    cache_root: Path
    revision: str
    snapshot_dir: Path
    data_dir: Path
    readme_path: Path

    @classmethod
    def resolve(
        cls,
        root: str | Path,
        *,
        expected_revision: str,
    ) -> HuggingFaceSnapshotLayout:
        cache_root = Path(root).expanduser().resolve()
        revision = expected_revision.strip().lower()
        if len(revision) != 40:
            raise ValueError("expected_revision must be a full 40-character commit SHA")

        if (cache_root / "data").is_dir():
            snapshot_dir = cache_root
        else:
            ref_path = cache_root / "refs" / "main"
            if ref_path.is_file():
                observed_ref = ref_path.read_text(encoding="utf-8").strip().lower()
                if observed_ref and observed_ref != revision:
                    raise ValueError(
                        f"Hugging Face cache refs/main points to {observed_ref}, expected {revision}"
                    )
            snapshot_dir = cache_root / "snapshots" / revision

        data_dir = snapshot_dir / "data"
        readme_path = snapshot_dir / "README.md"
        if not snapshot_dir.is_dir():
            raise FileNotFoundError(f"snapshot directory does not exist: {snapshot_dir}")
        if not data_dir.is_dir():
            raise FileNotFoundError(f"snapshot data directory does not exist: {data_dir}")
        if not readme_path.is_file():
            raise FileNotFoundError(f"snapshot README missing: {readme_path}")
        return cls(
            cache_root=cache_root,
            revision=revision,
            snapshot_dir=snapshot_dir,
            data_dir=data_dir,
            readme_path=readme_path,
        )


@dataclass(frozen=True, slots=True)
class LocalMinuteFile:
    month: str
    path: Path
    size_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "month": self.month,
            "relative_path": self.path.name,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class LocalMinuteInventory:
    revision: str
    files: tuple[LocalMinuteFile, ...]
    missing_months: tuple[str, ...]

    @property
    def start_month(self) -> str:
        return self.files[0].month

    @property
    def end_month(self) -> str:
        return self.files[-1].month

    @property
    def total_size_bytes(self) -> int:
        return sum(item.size_bytes for item in self.files)

    @property
    def inventory_id(self) -> str:
        payload: dict[str, object] = {
            "revision": self.revision,
            "files": [item.to_dict() for item in self.files],
            "missing_months": list(self.missing_months),
        }
        return _canonical_hash(payload, prefix="us-minute-inventory")

    def to_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "inventory_id": self.inventory_id,
            "file_count": len(self.files),
            "start_month": self.start_month,
            "end_month": self.end_month,
            "total_size_bytes": self.total_size_bytes,
            "missing_months": list(self.missing_months),
            "files": [item.to_dict() for item in self.files],
        }


def inventory_monthly_parquet(layout: HuggingFaceSnapshotLayout) -> LocalMinuteInventory:
    files: list[LocalMinuteFile] = []
    for path in sorted(layout.data_dir.glob("ohlcv_*.parquet")):
        match = _MONTH_RE.fullmatch(path.name)
        if match is None:
            continue
        year = int(match.group(1))
        month = int(match.group(2))
        _month_index(year, month)
        files.append(
            LocalMinuteFile(
                month=f"{year:04d}-{month:02d}",
                path=path,
                size_bytes=path.stat().st_size,
            )
        )
    if not files:
        raise FileNotFoundError(f"no ohlcv_YYYY-MM.parquet files under {layout.data_dir}")

    month_indices = [_month_index(*map(int, item.month.split("-"))) for item in files]
    if len(month_indices) != len(set(month_indices)):
        raise ValueError("duplicate monthly Parquet partitions detected")
    expected = set(range(min(month_indices), max(month_indices) + 1))
    missing = tuple(_month_label(index) for index in sorted(expected.difference(month_indices)))
    return LocalMinuteInventory(
        revision=layout.revision,
        files=tuple(files),
        missing_months=missing,
    )


@dataclass(frozen=True, slots=True)
class LocalMinuteSampleCheck:
    month: str
    row_count: int
    ticker_count: int
    min_timestamp: str
    max_timestamp: str
    duplicate_key_count: int
    invalid_ohlc_count: int
    negative_volume_count: int
    outside_regular_hours_count: int
    outside_0400_2000_count: int

    @property
    def passed(self) -> bool:
        return (
            self.row_count > 0
            and self.ticker_count > 0
            and self.duplicate_key_count == 0
            and self.invalid_ohlc_count == 0
            and self.negative_volume_count == 0
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "month": self.month,
            "row_count": self.row_count,
            "ticker_count": self.ticker_count,
            "min_timestamp": self.min_timestamp,
            "max_timestamp": self.max_timestamp,
            "duplicate_key_count": self.duplicate_key_count,
            "invalid_ohlc_count": self.invalid_ohlc_count,
            "negative_volume_count": self.negative_volume_count,
            "outside_regular_hours_count": self.outside_regular_hours_count,
            "outside_0400_2000_count": self.outside_0400_2000_count,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class LocalMinuteCertification:
    revision: str
    inventory_id: str
    coverage_start: str
    coverage_end: str
    expected_coverage_start: str
    expected_coverage_end: str
    schema: tuple[tuple[str, str], ...]
    sample_checks: tuple[LocalMinuteSampleCheck, ...]
    missing_months: tuple[str, ...]
    certified_at: datetime

    @property
    def extended_hours_observed(self) -> bool:
        return any(item.outside_regular_hours_count > 0 for item in self.sample_checks)

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
            and all(item.passed for item in self.sample_checks)
        )

    @property
    def certification_id(self) -> str:
        payload: dict[str, object] = {
            "revision": self.revision,
            "inventory_id": self.inventory_id,
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "expected_coverage_start": self.expected_coverage_start,
            "expected_coverage_end": self.expected_coverage_end,
            "schema": [list(item) for item in self.schema],
            "sample_checks": [item.to_dict() for item in self.sample_checks],
            "missing_months": list(self.missing_months),
        }
        return _canonical_hash(payload, prefix="us-minute-certification")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.us-minute-local-certification.v1",
            "certification_id": self.certification_id,
            "revision": self.revision,
            "inventory_id": self.inventory_id,
            "coverage_start": self.coverage_start,
            "coverage_end": self.coverage_end,
            "expected_coverage_start": self.expected_coverage_start,
            "expected_coverage_end": self.expected_coverage_end,
            "passed": self.passed,
            "extended_hours_observed": self.extended_hours_observed,
            "missing_months": list(self.missing_months),
            "schema": [{"name": name, "type": kind} for name, kind in self.schema],
            "sample_checks": [item.to_dict() for item in self.sample_checks],
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


def _duckdb() -> Any:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "local U.S. minute certification requires duckdb; install FinAgent "
            "with the dev or local-parquet extra"
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
    """Classify sampled rows by New York clock without DuckDB's optional pytz bridge.

    DuckDB reduces the data to one UTC-minute bucket plus its row count, so Python
    only receives at most ~45k rows per sampled month. Standard-library zoneinfo
    then supplies DST-correct local clock classification on every supported OS.
    """

    minute_buckets = connection.execute(
        f"""
        SELECT
            CAST(FLOOR(epoch(timestamp) / 60) AS BIGINT) AS epoch_minute,
            COUNT(*) AS row_count
        FROM read_parquet({path_literal})
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


def certify_local_minute_snapshot(
    root: str | Path,
    *,
    expected_revision: str,
    expected_coverage_start: str,
    expected_coverage_end: str,
    sample_months: tuple[str, ...] | None = None,
    certified_at: datetime | None = None,
) -> LocalMinuteCertification:
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

        checks: list[LocalMinuteSampleCheck] = []
        for item in _sample_files(inventory, sample_months):
            path_literal = _quote_path(item.path)
            query = f"""
                WITH base AS (
                    SELECT timestamp, open, high, low, close, volume, ticker
                    FROM read_parquet({path_literal})
                ),
                duplicate_keys AS (
                    SELECT COUNT(*) AS duplicate_key_count
                    FROM (
                        SELECT ticker, timestamp
                        FROM base
                        GROUP BY ticker, timestamp
                        HAVING COUNT(*) > 1
                    )
                )
                SELECT
                    COUNT(*) AS row_count,
                    COUNT(DISTINCT ticker) AS ticker_count,
                    MIN(epoch(timestamp)) AS min_epoch,
                    MAX(epoch(timestamp)) AS max_epoch,
                    (SELECT duplicate_key_count FROM duplicate_keys) AS duplicate_key_count,
                    SUM(
                        CASE
                            WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                              OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
                              OR high < GREATEST(open, low, close)
                              OR low > LEAST(open, high, close)
                            THEN 1 ELSE 0
                        END
                    ) AS invalid_ohlc_count,
                    SUM(CASE WHEN volume IS NULL OR volume < 0 THEN 1 ELSE 0 END)
                        AS negative_volume_count
                FROM base
            """
            row = connection.execute(query).fetchone()
            assert row is not None
            outside_regular, outside_0400_2000 = _session_counts(connection, path_literal)
            min_timestamp = datetime.fromtimestamp(float(row[2]), tz=UTC).isoformat()
            max_timestamp = datetime.fromtimestamp(float(row[3]), tz=UTC).isoformat()
            checks.append(
                LocalMinuteSampleCheck(
                    month=item.month,
                    row_count=int(row[0]),
                    ticker_count=int(row[1]),
                    min_timestamp=min_timestamp,
                    max_timestamp=max_timestamp,
                    duplicate_key_count=int(row[4]),
                    invalid_ohlc_count=int(row[5] or 0),
                    negative_volume_count=int(row[6] or 0),
                    outside_regular_hours_count=outside_regular,
                    outside_0400_2000_count=outside_0400_2000,
                )
            )
    finally:
        connection.close()

    return LocalMinuteCertification(
        revision=layout.revision,
        inventory_id=inventory.inventory_id,
        coverage_start=inventory.start_month,
        coverage_end=inventory.end_month,
        expected_coverage_start=expected_coverage_start,
        expected_coverage_end=expected_coverage_end,
        schema=schema,
        sample_checks=tuple(checks),
        missing_months=inventory.missing_months,
        certified_at=certified_at or datetime.now(UTC),
    )


@dataclass(frozen=True, slots=True)
class LocalResearchAdmission:
    source_identity: DatasetSourceIdentity
    source_authority_status: DatasetAuthorityStatus
    certification_id: str
    inventory_id: str
    scope: str
    limitations: tuple[str, ...]
    admitted_at: datetime

    @property
    def admission_id(self) -> str:
        payload: dict[str, object] = {
            "source_identity": self.source_identity.to_dict(),
            "source_authority_status": self.source_authority_status.value,
            "certification_id": self.certification_id,
            "inventory_id": self.inventory_id,
            "scope": self.scope,
            "limitations": list(self.limitations),
        }
        return _canonical_hash(payload, prefix="us-minute-local-admission")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.us-minute-local-research-admission.v1",
            "admission_id": self.admission_id,
            "source_identity": self.source_identity.to_dict(),
            "source_authority_status": self.source_authority_status.value,
            "certification_id": self.certification_id,
            "inventory_id": self.inventory_id,
            "scope": self.scope,
            "limitations": list(self.limitations),
            "admitted_at": self.admitted_at.astimezone(UTC).isoformat(),
        }


def admit_local_non_redistributed_research(
    bundle: DatasetAuthorityBundle,
    certification: LocalMinuteCertification,
    *,
    admitted_at: datetime | None = None,
) -> LocalResearchAdmission:
    if bundle.decision.status is DatasetAuthorityStatus.REJECTED:
        raise PermissionError("rejected dataset source cannot receive local research admission")
    if not certification.passed:
        raise PermissionError("local minute snapshot certification did not pass")
    if certification.revision != bundle.provenance.revision.value:
        raise ValueError("local snapshot revision does not match source authority revision")

    limitations = list(bundle.decision.blocking_issues)
    limitations.extend(
        [
            "scope:local_non_redistributed_research_only",
            "prices:intraday_raw_split_unadjusted",
            "corporate_actions:not_embedded_in_ohlcv",
            "symbol_lifecycle:no_point_in_time_security_master",
        ]
    )
    if certification.extended_hours_observed:
        limitations.append("session:extended_hours_observed_in_certification_samples")
    else:
        limitations.append("session:no_extended_hours_observed_in_certification_samples")
    return LocalResearchAdmission(
        source_identity=bundle.source_identity(),
        source_authority_status=bundle.decision.status,
        certification_id=certification.certification_id,
        inventory_id=certification.inventory_id,
        scope="local_non_redistributed_research",
        limitations=tuple(dict.fromkeys(limitations)),
        admitted_at=admitted_at or datetime.now(UTC),
    )

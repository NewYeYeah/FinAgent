from __future__ import annotations

import csv
import hashlib
import tomllib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .local_ashare import _normalize_ts_code


def _date(value: str, name: str, *, required: bool = True) -> date | None:
    text = str(value).strip()
    if not text:
        if required:
            raise ValueError(f"{name} is required")
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{name} must use YYYY-MM-DD") from exc


def _datetime(value: str, name: str, *, required: bool = True) -> datetime | None:
    text = str(value).strip()
    if not text:
        if required:
            raise ValueError(f"{name} is required")
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class AshareReferenceSource:
    source_id: str
    name: str
    url: str
    authority: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.name.strip() or not self.url.strip():
            raise ValueError("supplemental source id/name/url must be non-empty")


@dataclass(frozen=True, slots=True)
class AshareDelistingRecord:
    ts_code: str
    effective_date: date
    decision_date: date | None
    source_id: str
    source_url: str
    observed_at: datetime
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "ts_code", _normalize_ts_code(self.ts_code))
        if not self.source_id.strip() or not self.source_url.strip():
            raise ValueError("delisting source_id/source_url must be non-empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("delisting observed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class AshareStatusPeriod:
    ts_code: str
    start_date: date
    end_date: date | None
    status: str
    source_id: str
    source_url: str
    observed_at: datetime
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "ts_code", _normalize_ts_code(self.ts_code))
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("status period end_date cannot be before start_date")
        if not self.status.strip() or not self.source_id.strip() or not self.source_url.strip():
            raise ValueError("status/source_id/source_url must be non-empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("status observed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class AshareSuspensionPeriod:
    ts_code: str
    start_time: datetime
    end_time: datetime | None
    reason: str
    source_id: str
    source_url: str
    observed_at: datetime
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "ts_code", _normalize_ts_code(self.ts_code))
        if self.start_time.tzinfo is None or self.start_time.utcoffset() is None:
            raise ValueError("suspension start_time must be timezone-aware")
        if self.end_time is not None:
            if self.end_time.tzinfo is None or self.end_time.utcoffset() is None:
                raise ValueError("suspension end_time must be timezone-aware")
            if self.end_time < self.start_time:
                raise ValueError("suspension end_time cannot be before start_time")
        if not self.source_id.strip() or not self.source_url.strip():
            raise ValueError("suspension source_id/source_url must be non-empty")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("suspension observed_at must be timezone-aware")


class AshareSupplementalDataStore:
    """Versioned partial reference data kept separate from vendor market Parquet.

    The store deliberately makes no completeness claim. Records are suitable for
    filling explicitly sourced gaps (for example a known delisting effective date),
    but their presence never upgrades the universe to survivorship-certified.
    """

    FILENAMES = (
        "sources.toml",
        "delistings.csv",
        "st_periods.csv",
        "suspensions.csv",
    )

    def __init__(
        self,
        root: str | Path,
        *,
        sources: Mapping[str, AshareReferenceSource],
        delistings: tuple[AshareDelistingRecord, ...],
        st_periods: tuple[AshareStatusPeriod, ...],
        suspensions: tuple[AshareSuspensionPeriod, ...],
        coverage: str,
        notes: str,
        data_version: str,
    ) -> None:
        self.root = Path(root).expanduser()
        self.sources = MappingProxyType(dict(sources))
        self.delistings = delistings
        self.st_periods = st_periods
        self.suspensions = suspensions
        self.coverage = coverage.strip() or "partial"
        self.notes = notes.strip()
        self._data_version = data_version
        by_code: dict[str, AshareDelistingRecord] = {}
        for record in delistings:
            existing = by_code.get(record.ts_code)
            if existing is not None and existing.effective_date != record.effective_date:
                raise ValueError(
                    f"conflicting supplemental delisting dates for {record.ts_code}: "
                    f"{existing.effective_date} vs {record.effective_date}"
                )
            by_code[record.ts_code] = record
        self._delisting_by_code = MappingProxyType(by_code)

    @classmethod
    def from_directory(cls, root: str | Path) -> AshareSupplementalDataStore:
        root = Path(root).expanduser()
        if not root.is_dir():
            raise FileNotFoundError(root)
        metadata_path = root / "sources.toml"
        if not metadata_path.is_file():
            raise FileNotFoundError(metadata_path)
        with metadata_path.open("rb") as handle:
            payload = tomllib.load(handle)
        dataset = payload.get("dataset")
        if not isinstance(dataset, dict):
            raise TypeError("supplemental sources.toml must contain [dataset]")
        source_payload = payload.get("sources", {})
        if not isinstance(source_payload, dict):
            raise TypeError("supplemental sources.toml [sources] must be a table")
        sources: dict[str, AshareReferenceSource] = {}
        for source_id, values in source_payload.items():
            if not isinstance(values, dict):
                raise TypeError(f"supplemental source {source_id!r} must be a table")
            sources[str(source_id)] = AshareReferenceSource(
                source_id=str(source_id),
                name=str(values.get("name", "")),
                url=str(values.get("url", "")),
                authority=str(values.get("authority", "")),
                notes=str(values.get("notes", "")),
            )
        delistings = cls._read_delistings(root / "delistings.csv", sources)
        st_periods = cls._read_st_periods(root / "st_periods.csv", sources)
        suspensions = cls._read_suspensions(root / "suspensions.csv", sources)
        digest = hashlib.sha256()
        for filename in cls.FILENAMES:
            path = root / filename
            if path.is_file():
                digest.update(filename.encode())
                digest.update(path.read_bytes())
        return cls(
            root,
            sources=sources,
            delistings=delistings,
            st_periods=st_periods,
            suspensions=suspensions,
            coverage=str(dataset.get("coverage", "partial")),
            notes=str(dataset.get("notes", "")),
            data_version=f"ashare-supplement-{digest.hexdigest()[:24]}",
        )

    @property
    def data_version(self) -> str:
        return self._data_version

    @property
    def is_complete(self) -> bool:
        return self.coverage.lower() == "complete"

    def delisting(self, ts_code: str) -> AshareDelistingRecord | None:
        return self._delisting_by_code.get(_normalize_ts_code(ts_code))

    def to_manifest(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.ashare-supplement.v1",
            "data_version": self.data_version,
            "coverage": self.coverage,
            "notes": self.notes,
            "source_ids": sorted(self.sources),
            "records": {
                "delistings": len(self.delistings),
                "st_periods": len(self.st_periods),
                "suspensions": len(self.suspensions),
            },
        }

    @staticmethod
    def _rows(path: Path, required: tuple[str, ...]) -> list[dict[str, str]]:
        if not path.is_file():
            raise FileNotFoundError(path)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = set(required) - set(reader.fieldnames or ())
            if missing:
                raise ValueError(f"{path.name} missing columns: {sorted(missing)}")
            return [dict(row) for row in reader]

    @classmethod
    def _check_source(
        cls, source_id: str, source_url: str, sources: Mapping[str, AshareReferenceSource]
    ) -> None:
        if source_id not in sources:
            raise KeyError(f"supplemental source_id not registered: {source_id!r}")
        if not source_url.strip():
            raise ValueError("supplemental source_url must be non-empty")

    @classmethod
    def _read_delistings(
        cls, path: Path, sources: Mapping[str, AshareReferenceSource]
    ) -> tuple[AshareDelistingRecord, ...]:
        required = (
            "ts_code",
            "effective_date",
            "decision_date",
            "source_id",
            "source_url",
            "observed_at",
            "notes",
        )
        output: list[AshareDelistingRecord] = []
        for row in cls._rows(path, required):
            cls._check_source(row["source_id"], row["source_url"], sources)
            observed = _datetime(row["observed_at"], "observed_at")
            effective = _date(row["effective_date"], "effective_date")
            assert observed is not None and effective is not None
            output.append(
                AshareDelistingRecord(
                    ts_code=row["ts_code"],
                    effective_date=effective,
                    decision_date=_date(row["decision_date"], "decision_date", required=False),
                    source_id=row["source_id"],
                    source_url=row["source_url"],
                    observed_at=observed,
                    notes=row["notes"],
                )
            )
        return tuple(sorted(output, key=lambda item: (item.ts_code, item.effective_date)))

    @classmethod
    def _read_st_periods(
        cls, path: Path, sources: Mapping[str, AshareReferenceSource]
    ) -> tuple[AshareStatusPeriod, ...]:
        required = (
            "ts_code",
            "start_date",
            "end_date",
            "status",
            "source_id",
            "source_url",
            "observed_at",
            "notes",
        )
        output: list[AshareStatusPeriod] = []
        for row in cls._rows(path, required):
            cls._check_source(row["source_id"], row["source_url"], sources)
            observed = _datetime(row["observed_at"], "observed_at")
            start = _date(row["start_date"], "start_date")
            assert observed is not None and start is not None
            output.append(
                AshareStatusPeriod(
                    ts_code=row["ts_code"],
                    start_date=start,
                    end_date=_date(row["end_date"], "end_date", required=False),
                    status=row["status"],
                    source_id=row["source_id"],
                    source_url=row["source_url"],
                    observed_at=observed,
                    notes=row["notes"],
                )
            )
        return tuple(sorted(output, key=lambda item: (item.ts_code, item.start_date)))

    @classmethod
    def _read_suspensions(
        cls, path: Path, sources: Mapping[str, AshareReferenceSource]
    ) -> tuple[AshareSuspensionPeriod, ...]:
        required = (
            "ts_code",
            "start_time",
            "end_time",
            "reason",
            "source_id",
            "source_url",
            "observed_at",
            "notes",
        )
        output: list[AshareSuspensionPeriod] = []
        for row in cls._rows(path, required):
            cls._check_source(row["source_id"], row["source_url"], sources)
            observed = _datetime(row["observed_at"], "observed_at")
            start = _datetime(row["start_time"], "start_time")
            assert observed is not None and start is not None
            output.append(
                AshareSuspensionPeriod(
                    ts_code=row["ts_code"],
                    start_time=start,
                    end_time=_datetime(row["end_time"], "end_time", required=False),
                    reason=row["reason"],
                    source_id=row["source_id"],
                    source_url=row["source_url"],
                    observed_at=observed,
                    notes=row["notes"],
                )
            )
        return tuple(sorted(output, key=lambda item: (item.ts_code, item.start_time)))

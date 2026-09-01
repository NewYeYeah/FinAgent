from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from finagent.data.us_minute.local_snapshot import (
    HuggingFaceSnapshotLayout,
    inventory_monthly_parquet,
)
from finagent.domain._validation import require_non_empty

_MONTH_RE = re.compile(r"^ohlcv_(\d{4})-(\d{2})\.parquet$")


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class MinuteStorePartition:
    month: str
    path: Path
    size_bytes: int

    def __post_init__(self) -> None:
        match = _MONTH_RE.fullmatch(self.path.name)
        if match is None:
            raise ValueError("minute store partition must be named ohlcv_YYYY-MM.parquet")
        expected = f"{match.group(1)}-{match.group(2)}"
        if self.month != expected:
            raise ValueError("minute store partition month does not match filename")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be >= 0")

    def identity_dict(self) -> dict[str, object]:
        return {
            "month": self.month,
            "filename": self.path.name,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class MinuteStoreManifest:
    source_id: str
    source_revision: str
    cleaning_identity: str
    inventory_id: str
    partitions: tuple[MinuteStorePartition, ...]
    market_id: str = "XNYS"
    timezone: str = "America/New_York"
    schema_version: str = "finagent.minute-store-manifest.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "source_revision",
            "cleaning_identity",
            "inventory_id",
            "market_id",
            "timezone",
        ):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(str(getattr(self, field_name)), field_name),
            )
        if not self.partitions:
            raise ValueError("minute store manifest requires at least one partition")
        ordered = tuple(sorted(self.partitions, key=lambda item: item.month))
        months = tuple(item.month for item in ordered)
        if len(months) != len(set(months)):
            raise ValueError("minute store manifest cannot contain duplicate months")
        object.__setattr__(self, "partitions", ordered)

    @property
    def manifest_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "cleaning_identity": self.cleaning_identity,
            "inventory_id": self.inventory_id,
            "market_id": self.market_id,
            "timezone": self.timezone,
            "partitions": [item.identity_dict() for item in self.partitions],
        }
        return _canonical_hash(payload, prefix="minute-store-manifest")

    @property
    def data_version(self) -> str:
        return _canonical_hash(
            {
                "manifest_id": self.manifest_id,
                "source_revision": self.source_revision,
                "cleaning_identity": self.cleaning_identity,
            },
            prefix="minute-data-version",
        )

    @property
    def total_size_bytes(self) -> int:
        return sum(item.size_bytes for item in self.partitions)

    def partition_by_month(self) -> dict[str, MinuteStorePartition]:
        return {item.month: item for item in self.partitions}

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "data_version": self.data_version,
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "cleaning_identity": self.cleaning_identity,
            "inventory_id": self.inventory_id,
            "market_id": self.market_id,
            "timezone": self.timezone,
            "partition_count": len(self.partitions),
            "total_size_bytes": self.total_size_bytes,
            "partitions": [item.identity_dict() for item in self.partitions],
        }


def manifest_from_directory(
    data_dir: str | Path,
    *,
    source_id: str,
    source_revision: str,
    cleaning_identity: str,
    inventory_id: str,
    market_id: str = "XNYS",
) -> MinuteStoreManifest:
    directory = Path(data_dir).expanduser().resolve()
    if not directory.is_dir():
        raise FileNotFoundError(f"minute store data directory does not exist: {directory}")
    partitions: list[MinuteStorePartition] = []
    for path in sorted(directory.glob("ohlcv_*.parquet")):
        match = _MONTH_RE.fullmatch(path.name)
        if match is None:
            continue
        month = f"{match.group(1)}-{match.group(2)}"
        partitions.append(
            MinuteStorePartition(
                month=month,
                path=path,
                size_bytes=path.stat().st_size,
            )
        )
    if not partitions:
        raise FileNotFoundError(f"no ohlcv_YYYY-MM.parquet files under {directory}")
    return MinuteStoreManifest(
        source_id=source_id,
        source_revision=source_revision,
        cleaning_identity=cleaning_identity,
        inventory_id=inventory_id,
        partitions=tuple(partitions),
        market_id=market_id,
    )


def manifest_from_huggingface_snapshot(
    root: str | Path,
    *,
    expected_revision: str,
    expected_inventory_id: str,
    cleaning_identity: str,
    source_id: str = "hf-mito0o852-ohlcv-1m",
) -> MinuteStoreManifest:
    layout = HuggingFaceSnapshotLayout.resolve(root, expected_revision=expected_revision)
    inventory = inventory_monthly_parquet(layout)
    if inventory.inventory_id != expected_inventory_id:
        raise ValueError(
            "local minute inventory identity mismatch: "
            f"observed {inventory.inventory_id}, expected {expected_inventory_id}"
        )
    return MinuteStoreManifest(
        source_id=source_id,
        source_revision=expected_revision,
        cleaning_identity=cleaning_identity,
        inventory_id=inventory.inventory_id,
        partitions=tuple(
            MinuteStorePartition(
                month=item.month,
                path=item.path,
                size_bytes=item.size_bytes,
            )
            for item in inventory.files
        ),
        market_id="XNYS",
    )

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.market import PriceBar


class MarketRegion(str, Enum):
    A_SHARE = "a_share"
    US_EQUITY = "us_equity"


def _non_empty(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must be non-empty")
    return normalized


def numeric(value: object, name: str) -> float:
    """Convert provider scalar values while retaining a useful field-level error."""

    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{name} must be numeric")
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc


@dataclass(frozen=True, slots=True)
class MarketDataPullRequest:
    """Provider-neutral request for the first real-market ETF ingestion surface."""

    market: MarketRegion
    symbols: tuple[str, ...]
    start: date
    end: date
    asset_type: AssetType = AssetType.ETF
    adjustment: str = "raw"
    feed: str = ""
    venue_overrides: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        symbols = tuple(_non_empty(symbol, "symbol").upper() for symbol in self.symbols)
        if not symbols:
            raise ValueError("symbols cannot be empty")
        if len(set(symbols)) != len(symbols):
            raise ValueError("symbols cannot contain duplicates")
        if self.end < self.start:
            raise ValueError("end cannot be earlier than start")
        adjustment = _non_empty(self.adjustment, "adjustment").lower()
        if adjustment != "raw":
            raise ValueError(
                "M1 ingestion accepts only raw execution prices; adjusted research prices "
                "require the planned dual-price corporate-action bundle"
            )
        venues = {str(key).upper(): str(value).upper() for key, value in self.venue_overrides.items()}
        unknown = set(venues) - set(symbols)
        if unknown:
            raise ValueError(f"venue_overrides contain unknown symbols: {sorted(unknown)}")
        object.__setattr__(self, "symbols", symbols)
        object.__setattr__(self, "adjustment", adjustment)
        object.__setattr__(self, "feed", self.feed.strip().lower())
        object.__setattr__(self, "venue_overrides", MappingProxyType(venues))
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType({str(k): str(v) for k, v in self.metadata.items()}),
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "market": self.market.value,
            "symbols": list(self.symbols),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "asset_type": self.asset_type.value,
            "adjustment": self.adjustment,
            "feed": self.feed,
            "venue_overrides": dict(sorted(self.venue_overrides.items())),
            "metadata": dict(sorted(self.metadata.items())),
        }

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class NormalizedBarRecord:
    asset: AssetId
    bar: PriceBar
    source_symbol: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_symbol", _non_empty(self.source_symbol, "source_symbol"))

    @property
    def primary_key(self) -> tuple[str, datetime]:
        return (self.asset.key, self.bar.event_time)

    def csv_row(self) -> dict[str, object]:
        return {
            "source_symbol": self.source_symbol,
            "symbol": self.asset.symbol,
            "event_time": self.bar.event_time.isoformat(),
            "available_at": self.bar.available_at.isoformat(),
            "open": repr(self.bar.open),
            "high": repr(self.bar.high),
            "low": repr(self.bar.low),
            "close": repr(self.bar.close),
            "volume": repr(self.bar.volume),
            "venue": self.asset.venue,
            "currency": self.asset.currency,
            "asset_type": self.asset.asset_type.value,
        }


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: str
    message: str
    severity: str = "error"

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _non_empty(self.code, "issue code"))
        object.__setattr__(self, "message", _non_empty(self.message, "issue message"))
        if self.severity not in {"error", "warning"}:
            raise ValueError("severity must be 'error' or 'warning'")


@dataclass(frozen=True, slots=True)
class MarketDataQualityReport:
    rows: int
    assets: int
    start: datetime | None
    end: datetime | None
    issues: tuple[QualityIssue, ...] = ()

    @property
    def passed(self) -> bool:
        return self.rows > 0 and not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "rows": self.rows,
            "assets": self.assets,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "issues": [
                {"code": issue.code, "message": issue.message, "severity": issue.severity}
                for issue in self.issues
            ],
        }

    def raise_if_failed(self) -> None:
        if not self.passed:
            errors = "; ".join(
                f"{issue.code}: {issue.message}"
                for issue in self.issues
                if issue.severity == "error"
            )
            raise ValueError(f"market-data quality validation failed: {errors or 'empty dataset'}")


@dataclass(frozen=True, slots=True)
class MarketDataManifest:
    provider: str
    dataset: str
    data_version: str
    pulled_at: datetime
    request: Mapping[str, object]
    raw_file: str
    raw_sha256: str
    normalized_file: str
    normalized_sha256: str
    rows: int
    assets: int
    quality_passed: bool

    def __post_init__(self) -> None:
        if self.pulled_at.tzinfo is None or self.pulled_at.utcoffset() is None:
            raise ValueError("pulled_at must be timezone-aware")
        object.__setattr__(self, "provider", _non_empty(self.provider, "provider"))
        object.__setattr__(self, "dataset", _non_empty(self.dataset, "dataset"))
        object.__setattr__(self, "data_version", _non_empty(self.data_version, "data_version"))
        object.__setattr__(self, "request", MappingProxyType(dict(self.request)))

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "dataset": self.dataset,
            "data_version": self.data_version,
            "pulled_at": self.pulled_at.isoformat(),
            "request": dict(self.request),
            "raw_file": self.raw_file,
            "raw_sha256": self.raw_sha256,
            "normalized_file": self.normalized_file,
            "normalized_sha256": self.normalized_sha256,
            "rows": self.rows,
            "assets": self.assets,
            "quality_passed": self.quality_passed,
        }


@dataclass(frozen=True, slots=True)
class MaterializedMarketData:
    root: Path
    raw_path: Path
    normalized_path: Path
    quality_path: Path
    manifest_path: Path
    manifest: MarketDataManifest
    quality: MarketDataQualityReport


CSV_FIELDS = (
    "source_symbol",
    "symbol",
    "event_time",
    "available_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "venue",
    "currency",
    "asset_type",
)


def json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [json_safe(item) for item in value]
    item = getattr(value, "item", None)
    if callable(item):
        return json_safe(item())
    return str(value)


def frame_records(value: object) -> list[dict[str, object]]:
    """Convert a provider DataFrame-like value without importing pandas in core."""

    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, (list, tuple)):
        return [dict(row) for row in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        records = to_dict("records")
        return [dict(row) for row in records]
    raise TypeError("provider response must be a mapping, sequence of mappings, or DataFrame-like")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_raw_records(records: Iterable[Mapping[str, object]], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [json_safe(dict(row)) for row in records]
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def write_normalized_csv(records: Iterable[NormalizedBarRecord], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(records, key=lambda item: (item.asset.key, item.bar.event_time))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for record in ordered:
            writer.writerow(record.csv_row())
    return path


def read_normalized_csv(path: str | Path) -> tuple[NormalizedBarRecord, ...]:
    path = Path(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(CSV_FIELDS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"normalized CSV is missing columns: {sorted(missing)}")
        records: list[NormalizedBarRecord] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                asset = AssetId(
                    symbol=row["symbol"],
                    asset_type=AssetType(row["asset_type"].strip().lower()),
                    venue=row["venue"],
                    currency=row["currency"],
                )
                event_time = datetime.fromisoformat(row["event_time"])
                available_at = datetime.fromisoformat(row["available_at"])
                bar = PriceBar(
                    event_time=event_time,
                    available_at=available_at,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid normalized CSV row {row_number}: {exc}") from exc
            records.append(NormalizedBarRecord(asset, bar, row["source_symbol"]))
    return tuple(records)


def validate_records(
    records: Iterable[NormalizedBarRecord],
    *,
    expected_symbols: Sequence[str] = (),
    require_common_calendar: bool = True,
) -> MarketDataQualityReport:
    values = tuple(records)
    issues: list[QualityIssue] = []
    seen: set[tuple[str, datetime]] = set()
    calendars: dict[str, set[date]] = {}
    last_available: dict[str, datetime] = {}

    for record in values:
        key = record.primary_key
        if key in seen:
            issues.append(QualityIssue("DQ-01", f"duplicate bar {key[0]} {key[1].isoformat()}"))
        seen.add(key)
        asset_key = record.asset.key
        calendars.setdefault(asset_key, set()).add(record.bar.event_time.date())
        previous = last_available.get(asset_key)
        if previous is not None and record.bar.available_at <= previous:
            issues.append(
                QualityIssue(
                    "DQ-02",
                    f"non-increasing available_at for {asset_key}: "
                    f"{record.bar.available_at.isoformat()}",
                )
            )
        last_available[asset_key] = record.bar.available_at

    expected = {symbol.upper() for symbol in expected_symbols}
    observed = {record.source_symbol.upper() for record in values}
    missing = expected - observed
    if missing:
        issues.append(QualityIssue("DQ-06", f"missing requested symbols: {sorted(missing)}"))

    if require_common_calendar and calendars:
        union = set().union(*calendars.values())
        for asset_key, sessions in calendars.items():
            absent = union - sessions
            if absent:
                issues.append(
                    QualityIssue(
                        "DQ-10",
                        f"fixed-universe asset {asset_key} is missing {len(absent)} sessions; "
                        "use Level 2 tradability semantics for suspensions/delistings",
                    )
                )

    timestamps = [record.bar.available_at for record in values]
    return MarketDataQualityReport(
        rows=len(values),
        assets=len(calendars),
        start=min(timestamps) if timestamps else None,
        end=max(timestamps) if timestamps else None,
        issues=tuple(issues),
    )


def write_json(payload: Mapping[str, object], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe(payload), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def finalize_materialization(
    *,
    provider: str,
    dataset: str,
    request: MarketDataPullRequest,
    raw_records: Sequence[Mapping[str, object]],
    normalized_records: Sequence[NormalizedBarRecord],
    output_dir: str | Path,
    pulled_at: datetime,
    require_common_calendar: bool = True,
) -> MaterializedMarketData:
    root = Path(output_dir)
    raw_path = write_raw_records(raw_records, root / "raw_records.json")
    normalized_path = write_normalized_csv(normalized_records, root / "bars.csv")
    quality = validate_records(
        normalized_records,
        expected_symbols=request.symbols,
        require_common_calendar=require_common_calendar,
    )
    quality_path = write_json(quality.to_dict(), root / "quality_report.json")
    raw_digest = sha256_file(raw_path)
    normalized_digest = sha256_file(normalized_path)
    version_material = f"{provider}|{request.fingerprint}|{normalized_digest}".encode()
    data_version = f"{provider}-{hashlib.sha256(version_material).hexdigest()[:16]}"
    manifest = MarketDataManifest(
        provider=provider,
        dataset=dataset,
        data_version=data_version,
        pulled_at=pulled_at,
        request=request.canonical_payload(),
        raw_file=raw_path.name,
        raw_sha256=raw_digest,
        normalized_file=normalized_path.name,
        normalized_sha256=normalized_digest,
        rows=quality.rows,
        assets=quality.assets,
        quality_passed=quality.passed,
    )
    manifest_path = write_json(manifest.to_dict(), root / "manifest.json")
    quality.raise_if_failed()
    return MaterializedMarketData(
        root=root,
        raw_path=raw_path,
        normalized_path=normalized_path,
        quality_path=quality_path,
        manifest_path=manifest_path,
        manifest=manifest,
        quality=quality,
    )

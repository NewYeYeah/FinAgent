from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.market_bars import (
    BarInterval,
    BarTimestampConvention,
    LabelHorizonMode,
    LabelHorizonPolicy,
    MarketBarRow,
    MarketSessionSpec,
    SessionSegment,
)

from .local_ashare import SHANGHAI, AshareBarFrequency, LocalAshareDatasetLayout
from .local_ashare_research_adapter import LocalAshareParquetDataAdapter

MARKET_BAR_ROW_SCHEMA = "finagent.market-bar-row.v1"
MARKET_BAR_MANIFEST_SCHEMA = "finagent.market-bar-series.manifest.v1"
MARKET_BAR_QUERY_SCHEMA = "finagent.market-bar-series.query.v1"

_PARQUET_COLUMNS = (
    "sequence",
    "row_id",
    "asset",
    "session_date",
    "event_time",
    "available_at",
    "interval",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "session_id",
    "session_type",
    "source",
    "data_version",
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    )


def _digest(prefix: str, value: object, length: int = 64) -> str:
    raw = hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]
    return f"{prefix}-{raw}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _integer(value: object, default: int = 0) -> int:
    if value is None:
        return default
    return int(cast(Any, value))


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _safe_sibling(name: str, field: str) -> str:
    value = name.strip()
    if not value or Path(value).name != value or value in {".", ".."}:
        raise ValueError(f"{field} must be a sibling filename")
    return value


def _duckdb():
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - dependency guidance
        raise RuntimeError("MarketBarSeries Parquet support requires local-parquet") from exc
    return duckdb


def _row_payload(row: MarketBarRow) -> dict[str, object]:
    return {
        "schema_version": MARKET_BAR_ROW_SCHEMA,
        **row.to_dict(),
    }


def _row_id(row: MarketBarRow) -> str:
    return _digest("market-bar-row", _row_payload(row), 32)


def _series_identity_payload(
    *,
    linked_strategy_series_id: str,
    portfolio_validation_id: str,
    source_identity: str,
    data_version: str,
    interval: BarInterval,
    timestamp_convention: BarTimestampConvention,
    session_spec: MarketSessionSpec,
    label_horizon_policy: LabelHorizonPolicy,
    rows_digest: str,
) -> dict[str, object]:
    return {
        "schema_version": MARKET_BAR_MANIFEST_SCHEMA,
        "row_schema_version": MARKET_BAR_ROW_SCHEMA,
        "linked_strategy_series_id": linked_strategy_series_id,
        "portfolio_validation_id": portfolio_validation_id,
        "source_identity": source_identity,
        "data_version": data_version,
        "interval": interval.value,
        "timestamp_convention": timestamp_convention.value,
        "session_spec": session_spec.to_dict(),
        "label_horizon_policy": label_horizon_policy.to_dict(),
        "rows_digest": rows_digest,
    }


@dataclass(frozen=True, slots=True)
class MarketBarSeriesManifest:
    series_id: str
    linked_strategy_series_id: str
    portfolio_validation_id: str
    source_identity: str
    data_version: str
    interval: BarInterval
    timestamp_convention: BarTimestampConvention
    session_spec: MarketSessionSpec
    label_horizon_policy: LabelHorizonPolicy
    rows_digest: str
    data_file: str
    data_sha256: str
    row_count: int
    asset_count: int
    session_count: int
    start_date: str | None
    end_date: str | None
    columns: tuple[str, ...] = _PARQUET_COLUMNS
    authority: str = "authoritative"
    schema_version: str = MARKET_BAR_MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        required = (
            self.series_id,
            self.linked_strategy_series_id,
            self.portfolio_validation_id,
            self.source_identity,
            self.data_version,
            self.rows_digest,
            self.data_file,
            self.data_sha256,
        )
        if any(not value.strip() for value in required):
            raise ValueError("MarketBarSeries manifest identities are required")
        if self.authority != "authoritative":
            raise ValueError("MarketBarSeries manifest must be authoritative")
        if min(self.row_count, self.asset_count, self.session_count) < 0:
            raise ValueError("MarketBarSeries manifest counts cannot be negative")
        if self.columns != _PARQUET_COLUMNS:
            raise ValueError("MarketBarSeries manifest columns are not canonical")
        expected = _digest(
            "market-bar-series",
            _series_identity_payload(
                linked_strategy_series_id=self.linked_strategy_series_id,
                portfolio_validation_id=self.portfolio_validation_id,
                source_identity=self.source_identity,
                data_version=self.data_version,
                interval=self.interval,
                timestamp_convention=self.timestamp_convention,
                session_spec=self.session_spec,
                label_horizon_policy=self.label_horizon_policy,
                rows_digest=self.rows_digest,
            ),
            40,
        )
        if self.series_id != expected:
            raise ValueError("MarketBarSeries series_id differs from manifest content")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "authority": self.authority,
            "series_id": self.series_id,
            "linked_strategy_series_id": self.linked_strategy_series_id,
            "portfolio_validation_id": self.portfolio_validation_id,
            "source_identity": self.source_identity,
            "data_version": self.data_version,
            "interval": self.interval.value,
            "timestamp_convention": self.timestamp_convention.value,
            "session_spec": self.session_spec.to_dict(),
            "label_horizon_policy": self.label_horizon_policy.to_dict(),
            "rows_digest": self.rows_digest,
            "data_file": self.data_file,
            "data_sha256": self.data_sha256,
            "row_count": self.row_count,
            "asset_count": self.asset_count,
            "session_count": self.session_count,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "columns": list(self.columns),
            "ordering": "event_time, asset; sequence is deterministic 0-based order",
            "scope": (
                "historical market-bar evidence only; no alpha, portfolio, execution, "
                "PAPER, broker or live-capital authority"
            ),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> MarketBarSeriesManifest:
        if raw.get("schema_version") != MARKET_BAR_MANIFEST_SCHEMA:
            raise ValueError("unsupported MarketBarSeries manifest schema")
        session_raw = _mapping(raw.get("session_spec"))
        horizon_raw = _mapping(raw.get("label_horizon_policy"))
        return cls(
            series_id=_text(raw.get("series_id")),
            linked_strategy_series_id=_text(raw.get("linked_strategy_series_id")),
            portfolio_validation_id=_text(raw.get("portfolio_validation_id")),
            source_identity=_text(raw.get("source_identity")),
            data_version=_text(raw.get("data_version")),
            interval=BarInterval(_text(raw.get("interval"))),
            timestamp_convention=BarTimestampConvention(
                _text(raw.get("timestamp_convention"))
            ),
            session_spec=MarketSessionSpec.from_dict(dict(session_raw)),
            label_horizon_policy=LabelHorizonPolicy.from_dict(dict(horizon_raw)),
            rows_digest=_text(raw.get("rows_digest")),
            data_file=_safe_sibling(_text(raw.get("data_file")), "data_file"),
            data_sha256=_text(raw.get("data_sha256")),
            row_count=_integer(raw.get("row_count")),
            asset_count=_integer(raw.get("asset_count")),
            session_count=_integer(raw.get("session_count")),
            start_date=_text(raw.get("start_date")) or None,
            end_date=_text(raw.get("end_date")) or None,
            columns=tuple(str(value) for value in _sequence(raw.get("columns"))),
            authority=_text(raw.get("authority")),
        )

    @classmethod
    def read_json(cls, path: str | Path) -> MarketBarSeriesManifest:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("MarketBarSeries manifest root must be an object")
        return cls.from_dict(value)


def _create_parquet(path: Path, rows: Sequence[MarketBarRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".parquet", dir=str(path.parent)
    )
    os.close(fd)
    temp = Path(temp_name)
    temp.unlink(missing_ok=True)
    connection = _duckdb().connect()
    try:
        connection.execute(
            """
            CREATE TABLE market_bars (
                sequence BIGINT NOT NULL,
                row_id VARCHAR NOT NULL,
                asset VARCHAR NOT NULL,
                session_date DATE NOT NULL,
                event_time VARCHAR NOT NULL,
                available_at VARCHAR NOT NULL,
                interval VARCHAR NOT NULL,
                open DOUBLE NOT NULL,
                high DOUBLE NOT NULL,
                low DOUBLE NOT NULL,
                close DOUBLE NOT NULL,
                volume DOUBLE NOT NULL,
                session_id VARCHAR NOT NULL,
                session_type VARCHAR NOT NULL,
                source VARCHAR NOT NULL,
                data_version VARCHAR NOT NULL
            )
            """
        )
        values = [
            (
                index,
                _row_id(row),
                row.asset,
                row.session_date,
                row.event_time.isoformat(),
                row.available_at.isoformat(),
                row.interval.value,
                row.open,
                row.high,
                row.low,
                row.close,
                row.volume,
                row.session_id,
                row.session_type,
                row.source,
                row.data_version,
            )
            for index, row in enumerate(rows)
        ]
        if values:
            placeholders = ",".join("?" for _ in _PARQUET_COLUMNS)
            connection.executemany(
                f"INSERT INTO market_bars VALUES ({placeholders})",
                values,
            )
        target = str(temp).replace("'", "''")
        connection.execute(
            f"COPY market_bars TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    finally:
        connection.close()
    temp.replace(path)


def write_market_bar_series(
    *,
    linked_strategy_series_id: str,
    portfolio_validation_id: str,
    source_identity: str,
    data_version: str,
    interval: BarInterval,
    timestamp_convention: BarTimestampConvention,
    session_spec: MarketSessionSpec,
    label_horizon_policy: LabelHorizonPolicy,
    rows: Sequence[MarketBarRow],
    manifest_path: str | Path,
    data_path: str | Path,
) -> MarketBarSeriesManifest:
    manifest_target = Path(manifest_path).resolve()
    data_target = Path(data_path).resolve()
    if manifest_target.parent != data_target.parent:
        raise ValueError("MarketBarSeries manifest and Parquet must be sibling files")
    ordered = tuple(sorted(rows, key=lambda value: (value.event_time, value.asset)))
    if not ordered:
        raise ValueError("MarketBarSeries requires at least one bar")
    if any(row.interval is not interval for row in ordered):
        raise ValueError("MarketBarSeries rows must use the manifest interval")
    if any(row.data_version != data_version for row in ordered):
        raise ValueError("MarketBarSeries rows must use the manifest data_version")
    identities = [(row.asset, row.event_time) for row in ordered]
    if len(identities) != len(set(identities)):
        raise ValueError("MarketBarSeries asset/event_time identity is not unique")
    rows_digest = _digest(
        "market-bar-rows",
        [_row_payload(row) for row in ordered],
        64,
    )
    identity_payload = _series_identity_payload(
        linked_strategy_series_id=linked_strategy_series_id,
        portfolio_validation_id=portfolio_validation_id,
        source_identity=source_identity,
        data_version=data_version,
        interval=interval,
        timestamp_convention=timestamp_convention,
        session_spec=session_spec,
        label_horizon_policy=label_horizon_policy,
        rows_digest=rows_digest,
    )
    series_id = _digest("market-bar-series", identity_payload, 40)
    _create_parquet(data_target, ordered)
    dates = [row.session_date for row in ordered]
    manifest = MarketBarSeriesManifest(
        series_id=series_id,
        linked_strategy_series_id=linked_strategy_series_id,
        portfolio_validation_id=portfolio_validation_id,
        source_identity=source_identity,
        data_version=data_version,
        interval=interval,
        timestamp_convention=timestamp_convention,
        session_spec=session_spec,
        label_horizon_policy=label_horizon_policy,
        rows_digest=rows_digest,
        data_file=data_target.name,
        data_sha256=_sha256(data_target),
        row_count=len(ordered),
        asset_count=len({row.asset for row in ordered}),
        session_count=len({row.session_date for row in ordered}),
        start_date=min(dates).isoformat(),
        end_date=max(dates).isoformat(),
    )
    manifest_target.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return manifest


class MarketBarSeriesEvidence:
    """Verified bounded projection over immutable MarketBarSeries Parquet evidence."""

    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = Path(manifest_path).resolve()
        self.manifest = MarketBarSeriesManifest.read_json(self.manifest_path)
        self.data_path = self.manifest_path.parent / self.manifest.data_file
        if self.data_path.parent.resolve() != self.manifest_path.parent:
            raise ValueError("MarketBarSeries data file escaped its evidence root")
        if not self.data_path.is_file():
            raise FileNotFoundError(self.data_path)
        if _sha256(self.data_path) != self.manifest.data_sha256:
            raise ValueError("MarketBarSeries Parquet SHA-256 mismatch")
        self._validate_parquet()

    def _validate_parquet(self) -> None:
        connection = _duckdb().connect()
        try:
            columns = tuple(
                str(row[0])
                for row in connection.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?)",
                    (str(self.data_path),),
                ).fetchall()
            )
            if columns != self.manifest.columns:
                raise ValueError("MarketBarSeries Parquet columns differ from manifest")
            summary = connection.execute(
                """
                SELECT count(*), count(DISTINCT sequence), count(DISTINCT row_id),
                       min(sequence), max(sequence), count(DISTINCT asset),
                       count(DISTINCT session_date), count(DISTINCT interval),
                       min(interval), count(DISTINCT data_version), min(data_version)
                FROM read_parquet(?)
                """,
                (str(self.data_path),),
            ).fetchone()
            count = _integer(summary[0])
            if count != self.manifest.row_count:
                raise ValueError("MarketBarSeries Parquet row count differs from manifest")
            if _integer(summary[1]) != count or _integer(summary[2]) != count:
                raise ValueError("MarketBarSeries sequence/row identity is not unique")
            if count and (
                _integer(summary[3]) != 0 or _integer(summary[4]) != count - 1
            ):
                raise ValueError("MarketBarSeries sequence is not contiguous")
            if _integer(summary[5]) != self.manifest.asset_count:
                raise ValueError("MarketBarSeries asset count differs from manifest")
            if _integer(summary[6]) != self.manifest.session_count:
                raise ValueError("MarketBarSeries session count differs from manifest")
            if _integer(summary[7]) != 1 or _text(summary[8]) != self.manifest.interval.value:
                raise ValueError("MarketBarSeries interval differs from manifest")
            if _integer(summary[9]) != 1 or _text(summary[10]) != self.manifest.data_version:
                raise ValueError("MarketBarSeries data_version differs from manifest")
        finally:
            connection.close()

    def query(
        self,
        *,
        asset: str | None = None,
        start: date | None = None,
        end: date | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> dict[str, object]:
        if not 1 <= limit <= 5000:
            raise ValueError("limit must be in [1, 5000]")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if start is not None and end is not None and end < start:
            raise ValueError("end cannot be before start")
        where: list[str] = []
        parameters: list[object] = [str(self.data_path)]
        if asset:
            where.append("asset = ?")
            parameters.append(asset.strip())
        if start is not None:
            where.append("session_date >= ?")
            parameters.append(start)
        if end is not None:
            where.append("session_date <= ?")
            parameters.append(end)
        predicate = f" WHERE {' AND '.join(where)}" if where else ""
        connection = _duckdb().connect()
        try:
            total_row = connection.execute(
                f"SELECT count(*) FROM read_parquet(?) {predicate}",
                parameters,
            ).fetchone()
            total = _integer(total_row[0])
            values = connection.execute(
                f"SELECT * FROM read_parquet(?) {predicate} "
                "ORDER BY sequence LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            )
            names = [str(value[0]) for value in values.description]
            items: list[dict[str, object]] = []
            for raw in values.fetchall():
                row = dict(zip(names, raw, strict=True))
                row["session_date"] = cast(date, row["session_date"]).isoformat()
                row["event_time"] = str(row["event_time"])
                row["available_at"] = str(row["available_at"])
                items.append(row)
        finally:
            connection.close()
        return {
            "schema_version": MARKET_BAR_QUERY_SCHEMA,
            "read_only": True,
            "authority": "authoritative",
            "series_id": self.manifest.series_id,
            "linked_strategy_series_id": self.manifest.linked_strategy_series_id,
            "portfolio_validation_id": self.manifest.portfolio_validation_id,
            "interval": self.manifest.interval.value,
            "timestamp_convention": self.manifest.timestamp_convention.value,
            "session_spec": self.manifest.session_spec.to_dict(),
            "label_horizon_policy": self.manifest.label_horizon_policy.to_dict(),
            "filters": {
                "asset": asset,
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
                "limit": limit,
                "offset": offset,
            },
            "total": total,
            "items": items,
        }


def _asset_from_key(value: str) -> AssetId:
    parts = value.split(":")
    if len(parts) != 4:
        raise ValueError(f"invalid AssetId key: {value!r}")
    asset_type, venue, symbol, currency = parts
    return AssetId(
        symbol=symbol,
        asset_type=AssetType(asset_type),
        venue="" if venue == "-" else venue,
        currency=currency,
    )


def ashare_session_spec() -> MarketSessionSpec:
    return MarketSessionSpec(
        market_id="CN_A_SHARE",
        timezone="Asia/Shanghai",
        segments=(
            SessionSegment("morning", "09:30", "11:30", "regular"),
            SessionSegment("afternoon", "13:00", "15:00", "regular"),
        ),
    )


def _ashare_interval(frequency: AshareBarFrequency) -> BarInterval:
    return {
        AshareBarFrequency.DAILY: BarInterval.DAY_1,
        AshareBarFrequency.MINUTE_1: BarInterval.MINUTE_1,
        AshareBarFrequency.MINUTE_5: BarInterval.MINUTE_5,
        AshareBarFrequency.MINUTE_15: BarInterval.MINUTE_15,
        AshareBarFrequency.MINUTE_30: BarInterval.MINUTE_30,
        AshareBarFrequency.MINUTE_60: BarInterval.MINUTE_60,
    }[frequency]


def materialize_local_ashare_market_bar_rows(
    *,
    layout: LocalAshareDatasetLayout,
    asset_keys: Sequence[str],
    start: datetime,
    end: datetime,
    frequency: AshareBarFrequency = AshareBarFrequency.DAILY,
    data_version: str | None = None,
) -> tuple[
    tuple[MarketBarRow, ...],
    BarInterval,
    BarTimestampConvention,
    MarketSessionSpec,
    LabelHorizonPolicy,
    str,
]:
    """Project certified local A-share raw OHLC into generic A-C2 rows.

    This function deliberately materializes evidence rather than exposing the local
    Parquet root to the browser. Minute inputs are contract-smoke only at A-C2.
    """

    adapter = LocalAshareParquetDataAdapter(
        layout,
        frequency=frequency,
        data_version=data_version,
    )
    assets = tuple(_asset_from_key(value) for value in asset_keys)
    histories = adapter._query_records(assets, start, end)  # internal source projection
    interval = _ashare_interval(frequency)
    timestamp_convention = (
        BarTimestampConvention.SESSION_OPEN
        if frequency is AshareBarFrequency.DAILY
        else BarTimestampConvention.BAR_START
    )
    horizon = (
        LabelHorizonPolicy(LabelHorizonMode.TRADING_DAYS, 1, True)
        if frequency is AshareBarFrequency.DAILY
        else LabelHorizonPolicy(LabelHorizonMode.SAME_SESSION, 1, False)
    )
    rows: list[MarketBarRow] = []
    for asset in assets:
        for record in histories[asset]:
            session_date = record.bar.available_at.astimezone(SHANGHAI).date()
            rows.append(
                MarketBarRow(
                    asset=asset.key,
                    session_date=session_date,
                    event_time=record.bar.event_time,
                    available_at=record.bar.available_at,
                    interval=interval,
                    open=record.bar.open,
                    high=record.bar.high,
                    low=record.bar.low,
                    close=record.bar.close,
                    volume=record.bar.volume,
                    session_id=f"CN_A_SHARE:{session_date.isoformat()}",
                    session_type="regular",
                    source="local_ashare_parquet",
                    data_version=adapter.data_version,
                )
            )
    return (
        tuple(sorted(rows, key=lambda value: (value.event_time, value.asset))),
        interval,
        timestamp_convention,
        ashare_session_spec(),
        horizon,
        adapter.data_version,
    )

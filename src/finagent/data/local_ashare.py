from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.market import PriceBar
from finagent.domain.universe import UniverseSnapshot

SHANGHAI = ZoneInfo("Asia/Shanghai")


class AshareBarFrequency(str, Enum):
    DAILY = "1d"
    MINUTE_1 = "1min"
    MINUTE_5 = "5min"
    MINUTE_15 = "15min"
    MINUTE_30 = "30min"
    MINUTE_60 = "60min"

    @property
    def minutes(self) -> int | None:
        return {
            AshareBarFrequency.DAILY: None,
            AshareBarFrequency.MINUTE_1: 1,
            AshareBarFrequency.MINUTE_5: 5,
            AshareBarFrequency.MINUTE_15: 15,
            AshareBarFrequency.MINUTE_30: 30,
            AshareBarFrequency.MINUTE_60: 60,
        }[self]

    @property
    def directory_name(self) -> str:
        if self is AshareBarFrequency.DAILY:
            raise ValueError("daily data is stored in stock_daily.parquet, not a directory")
        return f"stock_{self.value}"


class AshareIntradayTimestampConvention(str, Enum):
    BAR_END_WITH_OPENING_AUCTION = "bar_end_with_opening_auction"


@dataclass(frozen=True, slots=True)
class LocalAshareDatasetLayout:
    root: Path
    basic_filename: str = "stock_basic_data.parquet"
    daily_filename: str = "stock_daily.parquet"

    def __post_init__(self) -> None:
        root = Path(self.root).expanduser()
        object.__setattr__(self, "root", root)
        if not self.basic_filename.strip() or not self.daily_filename.strip():
            raise ValueError("local A-share filenames must be non-empty")

    @property
    def basic_path(self) -> Path:
        return self.root / self.basic_filename

    @property
    def daily_path(self) -> Path:
        return self.root / self.daily_filename

    def intraday_directory(self, frequency: AshareBarFrequency) -> Path:
        return self.root / frequency.directory_name

    def intraday_path(self, frequency: AshareBarFrequency, ts_code: str) -> Path:
        normalized = _normalize_ts_code(ts_code)
        return self.intraday_directory(frequency) / f"{normalized}.parquet"

    def require(self, frequency: AshareBarFrequency) -> None:
        if not self.root.is_dir():
            raise FileNotFoundError(f"local A-share root does not exist: {self.root}")
        if not self.basic_path.is_file():
            raise FileNotFoundError(f"stock basic parquet does not exist: {self.basic_path}")
        if frequency is AshareBarFrequency.DAILY:
            if not self.daily_path.is_file():
                raise FileNotFoundError(f"daily parquet does not exist: {self.daily_path}")
        elif not self.intraday_directory(frequency).is_dir():
            raise FileNotFoundError(
                f"intraday directory does not exist: {self.intraday_directory(frequency)}"
            )

    def fast_fingerprint(self, frequency: AshareBarFrequency) -> str:
        """Metadata fingerprint for a large immutable local dataset.

        This avoids hashing multi-GB files on every adapter construction. The returned
        version is intentionally prefixed ``fast`` and must not be represented as a
        content SHA. A certification job may record full hashes separately.
        """

        self.require(frequency)
        digest = hashlib.sha256()
        candidates = [self.basic_path]
        if frequency is AshareBarFrequency.DAILY:
            candidates.append(self.daily_path)
        else:
            directory = self.intraday_directory(frequency)
            candidates.extend(sorted(directory.glob("*.parquet")))
        for path in candidates:
            stat = path.stat()
            relative = path.relative_to(self.root).as_posix()
            digest.update(f"{relative}|{stat.st_size}|{stat.st_mtime_ns}\n".encode())
        return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class AshareInstrumentRecord:
    asset: AssetId
    ts_code: str
    name: str
    area: str = ""
    industry: str = ""
    market: str = ""
    list_date: date | None = None
    delist_date: date | None = None
    actual_controller: str = ""
    controller_type: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "ts_code", _normalize_ts_code(self.ts_code))
        if self.asset.asset_type is not AssetType.EQUITY:
            raise ValueError("A-share security-master records must use equity assets")


class LocalAshareSecurityMaster:
    """Candidate PIT universe from the vendor basic file.

    The current source sample carries reliable ``ts_code`` and ``list_date`` but has
    incomplete ``list_status``/``delist_date`` fields. The provider therefore exposes
    a candidate listing-date universe and explicitly does not claim survivorship-free
    certification.
    """

    def __init__(
        self,
        records: Iterable[AshareInstrumentRecord],
        *,
        data_version: str,
        source_path: str | Path,
        limitations: Sequence[str] = (),
    ) -> None:
        values = tuple(records)
        if not values:
            raise ValueError("security-master records cannot be empty")
        by_asset: dict[AssetId, AshareInstrumentRecord] = {}
        by_code: dict[str, AshareInstrumentRecord] = {}
        for record in values:
            if record.asset in by_asset or record.ts_code in by_code:
                raise ValueError(f"duplicate security-master instrument: {record.ts_code}")
            by_asset[record.asset] = record
            by_code[record.ts_code] = record
        self._records = tuple(sorted(values, key=lambda item: item.ts_code))
        self._by_asset = MappingProxyType(by_asset)
        self._by_code = MappingProxyType(by_code)
        self._data_version = str(data_version).strip()
        if not self._data_version:
            raise ValueError("data_version must be non-empty")
        self._source_path = Path(source_path)
        self._limitations = tuple(str(item) for item in limitations)

    @classmethod
    def from_parquet(
        cls, path: str | Path, *, data_version: str | None = None
    ) -> LocalAshareSecurityMaster:
        path = Path(path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(path)
        duckdb = _duckdb()
        columns = _parquet_columns(path)
        required = {"ts_code", "name", "list_date"}
        missing = required - columns
        if missing:
            raise ValueError(f"stock basic parquet is missing columns: {sorted(missing)}")
        optional = (
            "area",
            "industry",
            "market",
            "delist_date",
            "act_name",
            "act_ent_type",
            "list_status",
        )
        select = ["ts_code", "name", "list_date"]
        select.extend(name if name in columns else f"NULL AS {name}" for name in optional)
        sql = (
            f"SELECT {', '.join(select)} "
            f"FROM read_parquet('{_sql_path(path)}') ORDER BY ts_code"
        )
        rows = duckdb.connect().execute(sql).fetchall()
        records: list[AshareInstrumentRecord] = []
        epoch_placeholders = 0
        delist_non_null = 0
        list_status_non_null = 0
        names = ("ts_code", "name", "list_date", *optional)
        for row in rows:
            values = dict(zip(names, row, strict=True))
            list_day = _coerce_date(values["list_date"])
            if list_day == date(1970, 1, 1):
                epoch_placeholders += 1
                list_day = None
            delist_day = _coerce_date(values["delist_date"])
            if delist_day is not None:
                delist_non_null += 1
            if values["list_status"] not in {None, ""}:
                list_status_non_null += 1
            ts_code = _normalize_ts_code(values["ts_code"])
            records.append(
                AshareInstrumentRecord(
                    asset=_asset_from_ts_code(ts_code),
                    ts_code=ts_code,
                    name=str(values["name"] or ""),
                    area=str(values["area"] or ""),
                    industry=str(values["industry"] or ""),
                    market=str(values["market"] or ""),
                    list_date=list_day,
                    delist_date=delist_day,
                    actual_controller=str(values["act_name"] or ""),
                    controller_type=str(values["act_ent_type"] or ""),
                )
            )
        limitations = [
            "candidate-only universe: vendor basic data is not certified as a complete PIT security master"
        ]
        if epoch_placeholders:
            limitations.append(
                f"{epoch_placeholders} list_date values used the 1970-01-01 placeholder"
            )
        if delist_non_null == 0:
            limitations.append("delist_date contains no observed values")
        if list_status_non_null == 0:
            limitations.append("list_status contains no observed values")
        version = data_version or f"local-basic-fast-{_file_fast_digest(path)[:16]}"
        return cls(
            records,
            data_version=version,
            source_path=path,
            limitations=limitations,
        )

    @property
    def data_version(self) -> str:
        return self._data_version

    @property
    def source_path(self) -> Path:
        return self._source_path

    @property
    def limitations(self) -> tuple[str, ...]:
        return self._limitations

    @property
    def survivorship_certified(self) -> bool:
        return False

    @property
    def records(self) -> tuple[AshareInstrumentRecord, ...]:
        return self._records

    @property
    def assets(self) -> tuple[AssetId, ...]:
        return tuple(record.asset for record in self._records)

    def record(self, asset: AssetId) -> AshareInstrumentRecord:
        try:
            return self._by_asset[asset]
        except KeyError as exc:
            raise KeyError(f"security master has no record for {asset.key}") from exc

    def eligibility(self, asset: AssetId, asof: datetime) -> tuple[bool, str]:
        asof = _aware(asof, "asof")
        local_day = asof.astimezone(SHANGHAI).date()
        record = self._by_asset.get(asset)
        if record is None:
            return False, "instrument absent from local security master"
        if record.list_date is None:
            return False, "listing date unavailable or placeholder"
        if local_day < record.list_date:
            return False, "not yet listed"
        if record.delist_date is not None and local_day > record.delist_date:
            return False, "delisted according to vendor basic data"
        return True, ""

    def snapshot(self, asof: datetime, assets: tuple[AssetId, ...]) -> UniverseSnapshot:
        asof = _aware(asof, "asof")
        eligible: dict[AssetId, bool] = {}
        reasons: dict[AssetId, str] = {}
        for asset in assets:
            flag, reason = self.eligibility(asset, asof)
            eligible[asset] = flag
            if reason:
                reasons[asset] = reason
        return UniverseSnapshot(
            asof=asof,
            eligible=eligible,
            reasons=reasons,
            data_version=self.data_version,
        )


@dataclass(frozen=True, slots=True)
class AshareBarRecord:
    asset: AssetId
    ts_code: str
    bar: PriceBar
    amount: float
    adj_factor: float
    fields: Mapping[str, float] = field(default_factory=dict)
    opening_auction: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "ts_code", _normalize_ts_code(self.ts_code))
        amount = float(self.amount)
        adj_factor = float(self.adj_factor)
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("amount must be finite and non-negative")
        if not math.isfinite(adj_factor) or adj_factor <= 0:
            raise ValueError("adj_factor must be finite and positive")
        normalized = {str(key): float(value) for key, value in self.fields.items()}
        if any(not math.isfinite(value) for value in normalized.values()):
            raise ValueError("A-share numeric sidecar fields must be finite")
        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "adj_factor", adj_factor)
        object.__setattr__(self, "fields", MappingProxyType(normalized))

    @property
    def research_close(self) -> float:
        return self.bar.close * self.adj_factor


def _duckdb():
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError(
            "local A-share Parquet support requires the 'local-parquet' extra: "
            "python -m pip install -e '.[local-parquet]'"
        ) from exc
    return duckdb


def _parquet_columns(path: Path) -> set[str]:
    sql = f"DESCRIBE SELECT * FROM read_parquet('{_sql_path(path)}')"
    rows = _duckdb().connect().execute(sql).fetchall()
    return {str(row[0]) for row in rows}


def _sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def _normalize_ts_code(value: object) -> str:
    text = str(value).strip().upper()
    if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", text):
        raise ValueError(f"invalid A-share ts_code: {value!r}")
    return text


def _asset_from_ts_code(ts_code: str) -> AssetId:
    normalized = _normalize_ts_code(ts_code)
    symbol, suffix = normalized.split(".", 1)
    venue = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[suffix]
    return AssetId(symbol, AssetType.EQUITY, venue=venue, currency="CNY")


def _ts_code_from_asset(asset: AssetId) -> str:
    if asset.asset_type is not AssetType.EQUITY or asset.currency != "CNY":
        raise ValueError(f"not an A-share equity asset: {asset.key}")
    suffix = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}.get(asset.venue)
    if suffix is None:
        raise ValueError(f"unsupported A-share venue: {asset.venue!r}")
    return f"{asset.symbol}.{suffix}"


def _coerce_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).date()


def _coerce_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is not None:
        result = result.astimezone(SHANGHAI).replace(tzinfo=None)
    return result


def _number(value: object, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def _file_fast_digest(path: Path) -> str:
    stat = path.stat()
    payload = f"{path.resolve().as_posix()}|{stat.st_size}|{stat.st_mtime_ns}".encode()
    return hashlib.sha256(payload).hexdigest()

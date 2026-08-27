from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from finagent.domain.assets import AssetId
from finagent.domain.execution import ExecutionQuote, ExecutionSnapshot
from finagent.domain.experiments import ArtifactRef, ArtifactType
from finagent.domain.market import MarketSnapshot, PriceBar
from finagent.domain.research import (
    DatasetRequest,
    FeatureWindow,
    ResearchDataset,
    ResearchSplit,
    TimeRange,
)

from .local_ashare import (
    SHANGHAI,
    AshareBarFrequency,
    AshareBarRecord,
    AshareIntradayTimestampConvention,
    LocalAshareDatasetLayout,
    LocalAshareSecurityMaster,
    _asset_from_ts_code,
    _aware,
    _coerce_date,
    _coerce_datetime,
    _duckdb,
    _number,
    _parquet_columns,
    _sql_path,
    _ts_code_from_asset,
)

_LAGGED = re.compile(
    r"^(log_return|simple_return|squared_log_return|log_volume_change)_(\d+)$"
)
_FORWARD = re.compile(r"^forward_(log_return|simple_return)_(\d+)$")


class LocalAshareParquetDataAdapter:
    """DuckDB-backed local A-share research/market adapter.

    Raw OHLC is retained for market/execution snapshots. Return features and labels
    use ``raw close * adj_factor`` so corporate actions do not create artificial alpha.
    Daily vendor units are normalized from lots/thousand-CNY to shares/CNY; intraday
    data is already shares/CNY. Only daily and the audited 1-minute convention are
    enabled by default.
    """

    DAILY_FIELD_SCALES = {
        "total_share": 10_000.0,
        "float_share": 10_000.0,
        "free_share": 10_000.0,
        "total_mv": 10_000.0,
        "circ_mv": 10_000.0,
    }

    DIRECT_FEATURES = (
        "open",
        "high",
        "low",
        "close",
        "research_close",
        "volume",
        "amount",
        "adj_factor",
        "pre_close",
        "up_limit",
        "down_limit",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "total_share",
        "float_share",
        "free_share",
        "total_mv",
        "circ_mv",
        "is_st",
        "listed_days",
    )

    def __init__(
        self,
        layout: LocalAshareDatasetLayout,
        *,
        frequency: AshareBarFrequency = AshareBarFrequency.DAILY,
        security_master: LocalAshareSecurityMaster | None = None,
        include_opening_auction: bool = False,
        allow_uncertified_frequency: bool = False,
        data_version: str | None = None,
    ) -> None:
        layout.require(frequency)
        if (
            frequency not in {AshareBarFrequency.DAILY, AshareBarFrequency.MINUTE_1}
            and not allow_uncertified_frequency
        ):
            raise ValueError(
                f"frequency {frequency.value!r} has not been timestamp-certified; "
                "set allow_uncertified_frequency=True only for diagnostic work"
            )
        self.layout = layout
        self.frequency = frequency
        self.security_master = security_master
        self.include_opening_auction = bool(include_opening_auction)
        self.timestamp_convention = (
            AshareIntradayTimestampConvention.BAR_END_WITH_OPENING_AUCTION
        )
        fingerprint = layout.fast_fingerprint(frequency)
        self._data_version = (
            data_version or f"local-ashare-{frequency.value}-fast-{fingerprint[:16]}"
        )
        self._available_columns = self._discover_columns()

    @property
    def data_version(self) -> str:
        return self._data_version

    @property
    def supported_features(self) -> tuple[str, ...]:
        direct = [name for name in self.DIRECT_FEATURES if self._supports_direct(name)]
        return tuple(direct) + (
            "log_return_N",
            "simple_return_N",
            "squared_log_return_N",
            "log_volume_change_N",
        )

    @property
    def supported_labels(self) -> tuple[str, ...]:
        return ("forward_log_return_N", "forward_simple_return_N")

    def _discover_columns(self) -> frozenset[str]:
        if self.frequency is AshareBarFrequency.DAILY:
            return frozenset(_parquet_columns(self.layout.daily_path))
        directory = self.layout.intraday_directory(self.frequency)
        first = next(iter(sorted(directory.glob("*.parquet"))), None)
        if first is None:
            raise ValueError(f"intraday directory contains no parquet files: {directory}")
        return frozenset(_parquet_columns(first))

    def _supports_direct(self, name: str) -> bool:
        if name in {
            "open",
            "high",
            "low",
            "close",
            "research_close",
            "volume",
            "amount",
            "adj_factor",
        }:
            return True
        return name in self._available_columns

    def _validate_features(self, features: Sequence[str]) -> None:
        for name in features:
            if self._supports_direct(name):
                continue
            if _LAGGED.fullmatch(name):
                continue
            raise KeyError(f"unsupported local A-share feature {name!r}")

    def _validate_labels(self, labels: Sequence[str]) -> None:
        for name in labels:
            if not _FORWARD.fullmatch(name):
                raise KeyError(f"unsupported local A-share label {name!r}")

    def _max_lag(self, features: Sequence[str]) -> int:
        values = [
            int(match.group(2))
            for name in features
            if (match := _LAGGED.fullmatch(name))
        ]
        return max(values, default=0)

    def _max_horizon(self, labels: Sequence[str]) -> int:
        values = [
            int(match.group(2))
            for name in labels
            if (match := _FORWARD.fullmatch(name))
        ]
        return max(values, default=0)

    def _query_records(
        self,
        universe: tuple[AssetId, ...],
        start: datetime,
        end: datetime,
        *,
        prior_rows: int = 0,
        future_rows: int = 0,
        extra_fields: Sequence[str] = (),
    ) -> dict[AssetId, tuple[AshareBarRecord, ...]]:
        if not universe:
            raise ValueError("universe cannot be empty")
        start = _aware(start, "start")
        end = _aware(end, "end")
        if end <= start:
            raise ValueError("end must be later than start")
        histories: dict[AssetId, list[AshareBarRecord]] = {
            asset: [] for asset in universe
        }
        if self.frequency is AshareBarFrequency.DAILY:
            rows, names = self._query_daily_batch(
                universe, start, end, prior_rows, future_rows, extra_fields
            )
            for row in rows:
                record = self._row_to_record(dict(zip(names, row, strict=True)))
                if record is not None and record.asset in histories:
                    histories[record.asset].append(record)
        else:
            for asset in universe:
                ts_code = _ts_code_from_asset(asset)
                rows, names = self._query_intraday(
                    ts_code, start, end, prior_rows, future_rows, extra_fields
                )
                for row in rows:
                    record = self._row_to_record(dict(zip(names, row, strict=True)))
                    if record is not None:
                        histories[asset].append(record)
        return {asset: tuple(values) for asset, values in histories.items()}

    def _select_columns(self, extra_fields: Sequence[str] = ()) -> tuple[str, ...]:
        base = (
            "ts_code",
            "open",
            "high",
            "low",
            "close",
            "vol",
            "amount",
            "adj_factor",
        )
        if self.frequency is AshareBarFrequency.DAILY:
            optional = tuple(
                name
                for name in extra_fields
                if name in self._available_columns
                and name
                not in {
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                    "adj_factor",
                    "research_close",
                }
            )
            return tuple(dict.fromkeys((*base, "trade_date", *optional)))
        return (*base, "trade_date", "trade_time")

    def _query_daily_batch(
        self,
        universe: tuple[AssetId, ...],
        start: datetime,
        end: datetime,
        prior_rows: int,
        future_rows: int,
        extra_fields: Sequence[str],
    ) -> tuple[list[tuple[Any, ...]], tuple[str, ...]]:
        names = self._select_columns(extra_fields)
        select = ", ".join(names)
        local_start = start.astimezone(SHANGHAI).date()
        local_end = end.astimezone(SHANGHAI).date()
        codes = tuple(_ts_code_from_asset(asset) for asset in universe)
        placeholders = ", ".join("?" for _ in codes)
        selected = ", ".join("o." + name for name in names)
        sql = f"""
        WITH ordered AS (
            SELECT {select},
                   row_number() OVER (
                       PARTITION BY ts_code ORDER BY CAST(trade_date AS TIMESTAMP)
                   ) AS rn
            FROM read_parquet('{_sql_path(self.layout.daily_path)}')
            WHERE ts_code IN ({placeholders})
        ), bounds AS (
            SELECT
                ts_code,
                min(CASE WHEN CAST(trade_date AS DATE) >= ?
                    AND CAST(trade_date AS DATE) <= ? THEN rn END) AS lo,
                max(CASE WHEN CAST(trade_date AS DATE) >= ?
                    AND CAST(trade_date AS DATE) <= ? THEN rn END) AS hi
            FROM ordered
            GROUP BY ts_code
        )
        SELECT {selected}
        FROM ordered o
        JOIN bounds b USING (ts_code)
        WHERE b.lo IS NOT NULL
          AND o.rn BETWEEN greatest(1, b.lo - ?) AND b.hi + ?
        ORDER BY o.ts_code, CAST(o.trade_date AS TIMESTAMP)
        """
        params = (
            *codes,
            local_start,
            local_end,
            local_start,
            local_end,
            prior_rows,
            future_rows,
        )
        return _duckdb().connect().execute(sql, params).fetchall(), names

    def _query_intraday(
        self,
        ts_code: str,
        start: datetime,
        end: datetime,
        prior_rows: int,
        future_rows: int,
        extra_fields: Sequence[str],
    ) -> tuple[list[tuple[Any, ...]], tuple[str, ...]]:
        path = self.layout.intraday_path(self.frequency, ts_code)
        if not path.is_file():
            return [], self._select_columns(extra_fields)
        names = self._select_columns(extra_fields)
        select = ", ".join(names)
        local_start = start.astimezone(SHANGHAI).replace(tzinfo=None)
        local_end = end.astimezone(SHANGHAI).replace(tzinfo=None)
        sql = f"""
        WITH ordered AS (
            SELECT {select},
                   row_number() OVER (ORDER BY CAST(trade_time AS TIMESTAMP)) AS rn
            FROM read_parquet('{_sql_path(path)}')
        ), bounds AS (
            SELECT
                min(CASE WHEN CAST(trade_time AS TIMESTAMP) >= ?
                    AND CAST(trade_time AS TIMESTAMP) < ? THEN rn END) AS lo,
                max(CASE WHEN CAST(trade_time AS TIMESTAMP) >= ?
                    AND CAST(trade_time AS TIMESTAMP) < ? THEN rn END) AS hi
            FROM ordered
        )
        SELECT {select}
        FROM ordered, bounds
        WHERE bounds.lo IS NOT NULL
          AND rn BETWEEN greatest(1, bounds.lo - ?) AND bounds.hi + ?
        ORDER BY CAST(trade_time AS TIMESTAMP)
        """
        params = (
            local_start,
            local_end,
            local_start,
            local_end,
            prior_rows,
            future_rows,
        )
        return _duckdb().connect().execute(sql, params).fetchall(), names

    def _row_to_record(self, row: Mapping[str, Any]) -> AshareBarRecord | None:
        ts_code = str(row["ts_code"])
        asset = _asset_from_ts_code(ts_code)
        if self.frequency is AshareBarFrequency.DAILY:
            day = _coerce_date(row["trade_date"])
            if day is None:
                raise ValueError("daily trade_date cannot be null")
            event_local = datetime.combine(day, datetime.min.time().replace(hour=9, minute=30))
            event_local = event_local.replace(tzinfo=SHANGHAI)
            available_local = datetime.combine(
                day, datetime.min.time().replace(hour=16)
            ).replace(tzinfo=SHANGHAI)
            volume = _number(row["vol"], "vol") * 100.0
            amount = _number(row["amount"], "amount") * 1000.0
            opening_auction = False
        else:
            available_naive = _coerce_datetime(row["trade_time"])
            available_local = available_naive.replace(tzinfo=SHANGHAI)
            opening_auction = (
                available_local.hour == 9 and available_local.minute == 30
            )
            if opening_auction and not self.include_opening_auction:
                return None
            minutes = self.frequency.minutes
            assert minutes is not None
            event_local = (
                available_local
                if opening_auction
                else available_local - timedelta(minutes=minutes)
            )
            volume = _number(row["vol"], "vol")
            amount = _number(row["amount"], "amount")
        optional: dict[str, float] = {}
        for name in self.DIRECT_FEATURES:
            if name in {
                "open",
                "high",
                "low",
                "close",
                "research_close",
                "volume",
                "amount",
                "adj_factor",
            }:
                continue
            value = row.get(name)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                optional[name] = number * self.DAILY_FIELD_SCALES.get(name, 1.0)
        return AshareBarRecord(
            asset=asset,
            ts_code=ts_code,
            bar=PriceBar(
                event_time=event_local.astimezone(datetime.now().astimezone().tzinfo)
                if False
                else event_local.astimezone(__import__("datetime").UTC),
                available_at=available_local.astimezone(__import__("datetime").UTC),
                open=_number(row["open"], "open"),
                high=_number(row["high"], "high"),
                low=_number(row["low"], "low"),
                close=_number(row["close"], "close"),
                volume=volume,
            ),
            amount=amount,
            adj_factor=_number(row["adj_factor"], "adj_factor"),
            fields=optional,
            opening_auction=opening_auction,
        )

    def _feature_value(
        self, history: tuple[AshareBarRecord, ...], index: int, name: str
    ) -> float:
        record = history[index]
        if name == "open":
            return record.bar.open
        if name == "high":
            return record.bar.high
        if name == "low":
            return record.bar.low
        if name == "close":
            return record.bar.close
        if name == "research_close":
            return record.research_close
        if name == "volume":
            return record.bar.volume
        if name == "amount":
            return record.amount
        if name == "adj_factor":
            return record.adj_factor
        if name in record.fields:
            return record.fields[name]
        match = _LAGGED.fullmatch(name)
        if not match:
            return float("nan")
        kind, lag_text = match.groups()
        lag = int(lag_text)
        previous_index = index - lag
        if lag <= 0:
            raise ValueError("feature lag must be >= 1")
        if previous_index < 0:
            return float("nan")
        previous = history[previous_index]
        if kind == "log_return":
            return math.log(record.research_close / previous.research_close)
        if kind == "simple_return":
            return record.research_close / previous.research_close - 1.0
        if kind == "squared_log_return":
            value = math.log(record.research_close / previous.research_close)
            return value * value
        if kind == "log_volume_change":
            if record.bar.volume <= 0 or previous.bar.volume <= 0:
                return float("nan")
            return math.log(record.bar.volume / previous.bar.volume)
        raise AssertionError(kind)

    def _label_value(
        self,
        history: tuple[AshareBarRecord, ...],
        index: int,
        name: str,
        split_range: TimeRange,
    ) -> float:
        match = _FORWARD.fullmatch(name)
        if not match:
            raise KeyError(f"unsupported label {name!r}")
        kind, horizon_text = match.groups()
        horizon = int(horizon_text)
        if horizon <= 0:
            raise ValueError("label horizon must be >= 1")
        future_index = index + horizon
        if future_index >= len(history):
            return float("nan")
        current = history[index]
        future = history[future_index]
        if not split_range.contains(future.bar.available_at):
            return float("nan")
        if kind == "log_return":
            return math.log(future.research_close / current.research_close)
        if kind == "simple_return":
            return future.research_close / current.research_close - 1.0
        raise AssertionError(kind)

    def calendar(
        self, start: datetime, end: datetime, universe: tuple[AssetId, ...]
    ) -> tuple[datetime, ...]:
        histories = self._query_records(universe, start, end)
        calendars = [
            {
                record.bar.available_at
                for record in history
                if start <= record.bar.available_at < end
            }
            for history in histories.values()
        ]
        return tuple(sorted(set.intersection(*calendars) if calendars else set()))

    def execution_calendar(
        self,
        start: datetime,
        end: datetime,
        universe: tuple[AssetId, ...],
        *,
        price_field: str = "open",
    ) -> tuple[datetime, ...]:
        if price_field not in {"open", "close"}:
            raise ValueError("price_field must be 'open' or 'close'")
        query_end = end
        if price_field == "open" and self.frequency.minutes is not None:
            query_end = end + timedelta(minutes=self.frequency.minutes)
        histories = self._query_records(universe, start, query_end)
        calendars = []
        for history in histories.values():
            calendars.append(
                {
                    record.bar.event_time
                    if price_field == "open"
                    else record.bar.available_at
                    for record in history
                    if start
                    <= (
                        record.bar.event_time
                        if price_field == "open"
                        else record.bar.available_at
                    )
                    < end
                }
            )
        return tuple(sorted(set.intersection(*calendars) if calendars else set()))

    def market_snapshot(
        self, asof: datetime, universe: tuple[AssetId, ...]
    ) -> MarketSnapshot:
        asof = _aware(asof, "asof")
        start = asof - (
            timedelta(days=730)
            if self.frequency is AshareBarFrequency.DAILY
            else timedelta(days=10)
        )
        histories = self._query_records(
            universe, start, asof + timedelta(microseconds=1)
        )
        selected: dict[AssetId, PriceBar] = {}
        for asset, history in histories.items():
            candidates = [record.bar for record in history if record.bar.available_at <= asof]
            if not candidates:
                raise KeyError(
                    f"no PIT-safe local A-share bar for {asset.key} at {asof.isoformat()}"
                )
            selected[asset] = candidates[-1]
        return MarketSnapshot(
            asof=asof,
            bars=selected,
            data_version=self.data_version,
            metadata={
                "adapter": self.__class__.__name__,
                "frequency": self.frequency.value,
            },
        )

    def execution_snapshot(
        self,
        asof: datetime,
        universe: tuple[AssetId, ...],
        *,
        price_field: str = "open",
    ) -> ExecutionSnapshot:
        if price_field not in {"open", "close"}:
            raise ValueError("price_field must be 'open' or 'close'")
        asof = _aware(asof, "asof")
        start = asof - (
            timedelta(days=730)
            if self.frequency is AshareBarFrequency.DAILY
            else timedelta(days=10)
        )
        query_end = asof + timedelta(microseconds=1)
        if price_field == "open" and self.frequency.minutes is not None:
            query_end += timedelta(minutes=self.frequency.minutes)
        histories = self._query_records(universe, start, query_end)
        quotes: dict[AssetId, ExecutionQuote] = {}
        for asset, history in histories.items():
            candidates: list[tuple[datetime, AshareBarRecord]] = []
            for record in history:
                visible = (
                    record.bar.event_time
                    if price_field == "open"
                    else record.bar.available_at
                )
                if visible <= asof:
                    candidates.append((visible, record))
            if not candidates:
                raise KeyError(f"no executable local A-share {price_field} for {asset.key}")
            visible, record = candidates[-1]
            quotes[asset] = ExecutionQuote(
                event_time=record.bar.event_time,
                available_at=visible,
                price=record.bar.open if price_field == "open" else record.bar.close,
                volume=record.bar.volume,
                price_field=price_field,
            )
        return ExecutionSnapshot(
            asof=asof,
            quotes=quotes,
            data_version=self.data_version,
            metadata={
                "adapter": self.__class__.__name__,
                "frequency": self.frequency.value,
            },
        )

    def feature_window(
        self,
        asof: datetime,
        universe: tuple[AssetId, ...],
        features: tuple[str, ...],
        lookback: int,
    ) -> FeatureWindow:
        self._validate_features(features)
        if lookback <= 0:
            raise ValueError("lookback must be >= 1")
        asof = _aware(asof, "asof")
        max_lag = self._max_lag(features)
        start = asof - (
            timedelta(days=3650)
            if self.frequency is AshareBarFrequency.DAILY
            else timedelta(days=60)
        )
        histories = self._query_records(
            universe,
            start,
            asof + timedelta(microseconds=1),
            prior_rows=lookback + max_lag,
            extra_fields=features,
        )
        all_times = sorted(
            {
                record.bar.available_at
                for history in histories.values()
                for record in history
                if record.bar.available_at <= asof
            }
        )
        times = tuple(all_times[-lookback:])
        if not times:
            raise ValueError("no observations available for requested feature window")
        values = np.full(
            (len(times), len(universe), len(features)), np.nan, dtype=float
        )
        time_index = {timestamp: index for index, timestamp in enumerate(times)}
        for asset_index, asset in enumerate(universe):
            history = histories[asset]
            for row_index, record in enumerate(history):
                output_row = time_index.get(record.bar.available_at)
                if output_row is None:
                    continue
                for feature_index, name in enumerate(features):
                    values[output_row, asset_index, feature_index] = self._feature_value(
                        history, row_index, name
                    )
        return FeatureWindow(
            asof=asof,
            timestamps=times,
            assets=universe,
            feature_names=features,
            values=values,
            data_version=self.data_version,
            metadata={
                "adapter": self.__class__.__name__,
                "frequency": self.frequency.value,
                "return_price": "raw_close_times_adj_factor",
                "share_count_unit": "shares",
                "market_cap_unit": "CNY",
                "rate_unit": "vendor_percent",
            },
        )

    def build_dataset(self, request: DatasetRequest) -> ResearchDataset:
        self._validate_features(request.features)
        self._validate_labels(request.labels)
        panels: dict[str, ResearchSplit] = {}
        max_lag = self._max_lag(request.features)
        max_horizon = self._max_horizon(request.labels)
        for split_name, split_range in request.splits.items():
            histories = self._query_records(
                request.universe,
                split_range.start,
                split_range.end,
                prior_rows=max_lag,
                future_rows=max_horizon,
                extra_fields=request.features,
            )
            timestamps = tuple(
                sorted(
                    {
                        record.bar.available_at
                        for history in histories.values()
                        for record in history
                        if split_range.contains(record.bar.available_at)
                    }
                )
            )
            if not timestamps:
                raise ValueError(f"split {split_name!r} contains no observations")
            feature_values = np.full(
                (len(timestamps), len(request.universe), len(request.features)),
                np.nan,
                dtype=float,
            )
            label_values = np.full(
                (len(timestamps), len(request.universe), len(request.labels)),
                np.nan,
                dtype=float,
            )
            eligibility = np.zeros(
                (len(timestamps), len(request.universe)), dtype=np.bool_
            )
            time_index = {
                timestamp: index for index, timestamp in enumerate(timestamps)
            }
            for asset_index, asset in enumerate(request.universe):
                history = histories[asset]
                for row_index, record in enumerate(history):
                    output_row = time_index.get(record.bar.available_at)
                    if output_row is None:
                        continue
                    for feature_index, name in enumerate(request.features):
                        feature_values[
                            output_row, asset_index, feature_index
                        ] = self._feature_value(history, row_index, name)
                    for label_index, name in enumerate(request.labels):
                        label_values[
                            output_row, asset_index, label_index
                        ] = self._label_value(
                            history, row_index, name, split_range
                        )
                    eligible = True
                    if self.security_master is not None:
                        eligible, _ = self.security_master.eligibility(
                            asset, record.bar.available_at
                        )
                    eligibility[output_row, asset_index] = eligible
            panels[split_name] = ResearchSplit(
                timestamps=timestamps,
                assets=request.universe,
                feature_names=request.features,
                label_names=request.labels,
                feature_values=feature_values,
                label_values=label_values,
                eligibility_mask=eligibility,
                metadata={
                    "split": split_name,
                    "data_version": self.data_version,
                    "frequency": self.frequency.value,
                    "return_price": "raw_close_times_adj_factor",
                    "universe_grade": (
                        "candidate_only"
                        if self.security_master is not None
                        and not self.security_master.survivorship_certified
                        else "static"
                    ),
                },
            )
        digest = self._dataset_digest(request, panels)
        artifact = ArtifactRef(
            artifact_id=request.dataset_id,
            artifact_type=ArtifactType.DATASET,
            version=self.data_version,
            digest=digest,
            uri=self.layout.root.resolve().as_uri(),
        )
        return ResearchDataset(
            artifact=artifact,
            universe=request.universe,
            features=request.features,
            labels=request.labels,
            splits=request.splits,
            point_in_time=True,
            metadata={
                **dict(request.metadata),
                "data_version": self.data_version,
                "frequency": self.frequency.value,
                "source": "local_ashare_parquet",
                "volume_unit": "shares",
                "amount_unit": "CNY",
                "return_price": "raw_close_times_adj_factor",
                "share_count_unit": "shares",
                "market_cap_unit": "CNY",
                "rate_unit": "vendor_percent",
            },
            panels=panels,
        )

    def _dataset_digest(
        self,
        request: DatasetRequest,
        panels: Mapping[str, ResearchSplit],
    ) -> str:
        digest = hashlib.sha256()
        manifest = {
            "data_version": self.data_version,
            "frequency": self.frequency.value,
            "dataset_id": request.dataset_id,
            "universe": [asset.key for asset in request.universe],
            "features": list(request.features),
            "labels": list(request.labels),
            "splits": {
                name: [window.start.isoformat(), window.end.isoformat()]
                for name, window in sorted(request.splits.items())
            },
            "include_opening_auction": self.include_opening_auction,
        }
        digest.update(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        )
        for split_name in sorted(panels):
            panel = panels[split_name]
            digest.update(split_name.encode())
            digest.update(
                "|".join(timestamp.isoformat() for timestamp in panel.timestamps).encode()
            )
            digest.update(panel.feature_values.tobytes(order="C"))
            digest.update(panel.label_values.tobytes(order="C"))
            digest.update(panel.eligibility_mask.tobytes(order="C"))
        return digest.hexdigest()

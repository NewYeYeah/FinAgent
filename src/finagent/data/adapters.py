from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np

from finagent.domain.assets import AssetId, AssetType
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

_LAGGED = re.compile(r"^(log_return|simple_return|squared_log_return|log_volume_change)_(\d+)$")
_FORWARD = re.compile(r"^forward_(log_return|simple_return)_(\d+)$")


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"timestamp must be timezone-aware: {value!r}")
    return parsed


class InMemoryPriceDataAdapter:
    """Point-in-time adapter over immutable ``PriceBar`` histories.

    The adapter uses ``PriceBar.available_at`` as the numerical panel clock. Feature
    values at time *t* are computed only from bars with ``available_at <= t``.
    Forward labels are materialized only for training/evaluation and are clipped at
    split boundaries, so a label never crosses from one split into another.
    """

    def __init__(
        self,
        bars: Mapping[AssetId, Iterable[PriceBar]],
        *,
        data_version: str = "memory-v1",
    ) -> None:
        if not data_version.strip():
            raise ValueError("data_version must be non-empty")
        normalized: dict[AssetId, tuple[PriceBar, ...]] = {}
        for asset, history in bars.items():
            seq = tuple(sorted(history, key=lambda bar: (bar.available_at, bar.event_time)))
            if not seq:
                raise ValueError(f"bar history cannot be empty for {asset.key}")
            times = [bar.available_at for bar in seq]
            if len(times) != len(set(times)):
                raise ValueError(f"duplicate available_at timestamps for {asset.key}")
            normalized[asset] = seq
        if not normalized:
            raise ValueError("bars cannot be empty")
        self._bars = normalized
        self._data_version = data_version.strip()

    @property
    def data_version(self) -> str:
        return self._data_version

    @property
    def supported_features(self) -> tuple[str, ...]:
        return (
            "close",
            "volume",
            "log_return_N",
            "simple_return_N",
            "squared_log_return_N",
            "log_volume_change_N",
        )

    @property
    def supported_labels(self) -> tuple[str, ...]:
        return ("forward_log_return_N", "forward_simple_return_N")

    def _validate_universe(self, universe: tuple[AssetId, ...]) -> None:
        missing = [asset.key for asset in universe if asset not in self._bars]
        if missing:
            raise KeyError(f"adapter has no history for: {', '.join(sorted(missing))}")

    def _feature_value(self, history: tuple[PriceBar, ...], index: int, name: str) -> float:
        bar = history[index]
        if name == "close":
            return bar.close
        if name == "volume":
            return bar.volume
        match = _LAGGED.fullmatch(name)
        if not match:
            raise KeyError(f"unsupported feature {name!r}")
        kind, lag_text = match.groups()
        lag = int(lag_text)
        if lag <= 0:
            raise ValueError("feature lag must be >= 1")
        previous_index = index - lag
        if previous_index < 0:
            return float("nan")
        previous = history[previous_index]
        if kind == "log_return":
            return math.log(bar.close / previous.close)
        if kind == "simple_return":
            return bar.close / previous.close - 1.0
        if kind == "squared_log_return":
            value = math.log(bar.close / previous.close)
            return value * value
        if kind == "log_volume_change":
            if bar.volume <= 0 or previous.volume <= 0:
                return float("nan")
            return math.log(bar.volume / previous.volume)
        raise AssertionError(kind)

    def _label_value(
        self,
        history: tuple[PriceBar, ...],
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
        # Strict split isolation: training labels may use future observations only
        # when the target observation itself belongs to the same split.
        if not split_range.contains(future.available_at):
            return float("nan")
        if kind == "log_return":
            return math.log(future.close / current.close)
        if kind == "simple_return":
            return future.close / current.close - 1.0
        raise AssertionError(kind)

    def _indices_by_time(self, asset: AssetId) -> dict[datetime, int]:
        return {bar.available_at: idx for idx, bar in enumerate(self._bars[asset])}

    def calendar(
        self,
        start: datetime,
        end: datetime,
        universe: tuple[AssetId, ...],
    ) -> tuple[datetime, ...]:
        self._validate_universe(universe)
        if end <= start:
            raise ValueError("end must be later than start")
        # The backtest clock uses the intersection so each asset has a newly available
        # observation at every rebalance point. Snapshot itself can still carry stale
        # latest-known bars if callers request arbitrary timestamps.
        calendars = []
        for asset in universe:
            calendars.append(
                {
                    bar.available_at
                    for bar in self._bars[asset]
                    if start <= bar.available_at < end
                }
            )
        common = set.intersection(*calendars) if calendars else set()
        return tuple(sorted(common))

    def execution_calendar(
        self,
        start: datetime,
        end: datetime,
        universe: tuple[AssetId, ...],
        *,
        price_field: str = "open",
    ) -> tuple[datetime, ...]:
        """Return common executable timestamps for field-level execution prices.

        ``open`` is considered executable at ``PriceBar.event_time`` while ``close``
        becomes executable only at ``PriceBar.available_at``.  No high/low execution
        mode is exposed because those fields do not have a deterministic intrabar
        availability time in the Phase 2 contract.
        """
        self._validate_universe(universe)
        if end <= start:
            raise ValueError("end must be later than start")
        if price_field not in {"open", "close"}:
            raise ValueError("price_field must be 'open' or 'close'")
        calendars = []
        for asset in universe:
            values = set()
            for bar in self._bars[asset]:
                ts = bar.event_time if price_field == "open" else bar.available_at
                if start <= ts < end:
                    values.add(ts)
            calendars.append(values)
        common = set.intersection(*calendars) if calendars else set()
        return tuple(sorted(common))

    def execution_snapshot(
        self,
        asof: datetime,
        universe: tuple[AssetId, ...],
        *,
        price_field: str = "open",
    ) -> ExecutionSnapshot:
        self._validate_universe(universe)
        if price_field not in {"open", "close"}:
            raise ValueError("price_field must be 'open' or 'close'")
        quotes: dict[AssetId, ExecutionQuote] = {}
        for asset in universe:
            candidates: list[tuple[datetime, PriceBar]] = []
            for bar in self._bars[asset]:
                available = bar.event_time if price_field == "open" else bar.available_at
                if available <= asof:
                    candidates.append((available, bar))
            if not candidates:
                raise KeyError(
                    f"no executable {price_field} available for {asset.key} at {asof.isoformat()}"
                )
            available, bar = max(candidates, key=lambda item: (item[0], item[1].event_time))
            price = bar.open if price_field == "open" else bar.close
            quotes[asset] = ExecutionQuote(
                event_time=bar.event_time,
                available_at=available,
                price=price,
                volume=bar.volume,
                price_field=price_field,
            )
        return ExecutionSnapshot(
            asof=asof,
            quotes=quotes,
            data_version=self.data_version,
            metadata={"adapter": self.__class__.__name__, "price_field": price_field},
        )

    def market_snapshot(
        self,
        asof: datetime,
        universe: tuple[AssetId, ...],
    ) -> MarketSnapshot:
        self._validate_universe(universe)
        selected: dict[AssetId, PriceBar] = {}
        for asset in universe:
            candidates = [bar for bar in self._bars[asset] if bar.available_at <= asof]
            if not candidates:
                raise KeyError(f"no PIT-safe bar available for {asset.key} at {asof.isoformat()}")
            selected[asset] = candidates[-1]
        return MarketSnapshot(
            asof=asof,
            bars=selected,
            data_version=self.data_version,
            metadata={"adapter": self.__class__.__name__},
        )

    def feature_window(
        self,
        asof: datetime,
        universe: tuple[AssetId, ...],
        features: tuple[str, ...],
        lookback: int,
    ) -> FeatureWindow:
        self._validate_universe(universe)
        if lookback <= 0:
            raise ValueError("lookback must be >= 1")
        if not features:
            raise ValueError("features cannot be empty")
        # Union clock allows partially missing assets; missing cells are NaN and model
        # implementations decide whether to drop/require complete observations.
        all_times = sorted(
            {
                bar.available_at
                for asset in universe
                for bar in self._bars[asset]
                if bar.available_at <= asof
            }
        )
        times = tuple(all_times[-lookback:])
        if not times:
            raise ValueError("no observations available for requested feature window")
        values = np.full((len(times), len(universe), len(features)), np.nan, dtype=float)
        time_index = {ts: idx for idx, ts in enumerate(times)}
        for asset_idx, asset in enumerate(universe):
            history = self._bars[asset]
            for bar_idx, bar in enumerate(history):
                row = time_index.get(bar.available_at)
                if row is None or bar.available_at > asof:
                    continue
                for feature_idx, feature_name in enumerate(features):
                    values[row, asset_idx, feature_idx] = self._feature_value(
                        history, bar_idx, feature_name
                    )
        return FeatureWindow(
            asof=asof,
            timestamps=times,
            assets=universe,
            feature_names=features,
            values=values,
            data_version=self.data_version,
            metadata={"adapter": self.__class__.__name__},
        )

    def build_dataset(self, request: DatasetRequest) -> ResearchDataset:
        self._validate_universe(request.universe)
        panels: dict[str, ResearchSplit] = {}
        for split_name, split_range in request.splits.items():
            timestamps = sorted(
                {
                    bar.available_at
                    for asset in request.universe
                    for bar in self._bars[asset]
                    if split_range.contains(bar.available_at)
                }
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
            time_index = {ts: idx for idx, ts in enumerate(timestamps)}
            for asset_idx, asset in enumerate(request.universe):
                history = self._bars[asset]
                for bar_idx, bar in enumerate(history):
                    row = time_index.get(bar.available_at)
                    if row is None:
                        continue
                    for feature_idx, feature_name in enumerate(request.features):
                        feature_values[row, asset_idx, feature_idx] = self._feature_value(
                            history, bar_idx, feature_name
                        )
                    for label_idx, label_name in enumerate(request.labels):
                        label_values[row, asset_idx, label_idx] = self._label_value(
                            history, bar_idx, label_name, split_range
                        )
            panels[split_name] = ResearchSplit(
                timestamps=tuple(timestamps),
                assets=request.universe,
                feature_names=request.features,
                label_names=request.labels,
                feature_values=feature_values,
                label_values=label_values,
                metadata={"split": split_name, "data_version": self.data_version},
            )

        digest = self._dataset_digest(request, panels)
        artifact = ArtifactRef(
            artifact_id=request.dataset_id,
            artifact_type=ArtifactType.DATASET,
            version=self.data_version,
            digest=digest,
            uri=f"memory://{request.dataset_id}",
        )
        return ResearchDataset(
            artifact=artifact,
            universe=request.universe,
            features=request.features,
            labels=request.labels,
            splits=request.splits,
            point_in_time=True,
            metadata={**dict(request.metadata), "data_version": self.data_version},
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
            "dataset_id": request.dataset_id,
            "universe": [asset.key for asset in request.universe],
            "features": list(request.features),
            "labels": list(request.labels),
            "splits": {
                name: [window.start.isoformat(), window.end.isoformat()]
                for name, window in sorted(request.splits.items())
            },
        }
        digest.update(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())
        for split_name in sorted(panels):
            panel = panels[split_name]
            digest.update(split_name.encode())
            digest.update("|".join(ts.isoformat() for ts in panel.timestamps).encode())
            # np.nan has a stable IEEE representation in arrays produced here.
            digest.update(panel.feature_values.tobytes(order="C"))
            digest.update(panel.label_values.tobytes(order="C"))
        return digest.hexdigest()


class CSVPriceDataAdapter(InMemoryPriceDataAdapter):
    """Load a normalized OHLCV CSV into the canonical PIT adapter.

    Required columns: ``symbol,event_time,available_at,open,high,low,close``.
    Optional columns: ``volume,venue,currency,asset_type``.
    """

    REQUIRED_COLUMNS = {
        "symbol",
        "event_time",
        "available_at",
        "open",
        "high",
        "low",
        "close",
    }

    def __init__(self, path: str | Path, *, data_version: str | None = None) -> None:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(path)
        grouped: dict[AssetId, list[PriceBar]] = defaultdict(list)
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = self.REQUIRED_COLUMNS - set(reader.fieldnames or ())
            if missing:
                raise ValueError(f"CSV missing required columns: {sorted(missing)}")
            for row in reader:
                asset_type_text = (row.get("asset_type") or "equity").strip().lower()
                try:
                    asset_type = AssetType(asset_type_text)
                except ValueError as exc:
                    raise ValueError(f"unsupported asset_type {asset_type_text!r}") from exc
                asset = AssetId(
                    symbol=row["symbol"],
                    asset_type=asset_type,
                    venue=row.get("venue") or "",
                    currency=row.get("currency") or "USD",
                )
                grouped[asset].append(
                    PriceBar(
                        event_time=_parse_iso(row["event_time"]),
                        available_at=_parse_iso(row["available_at"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume") or 0.0),
                    )
                )
        if data_version is None:
            file_hash = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            data_version = f"csv-{file_hash}"
        super().__init__(grouped, data_version=data_version)
        self.path = path


class SQLitePriceDataAdapter(InMemoryPriceDataAdapter):
    """Materialize a universe from ``SQLitePriceStore`` into the canonical adapter."""

    def __init__(self, store, universe: tuple[AssetId, ...], *, data_version: str | None = None) -> None:
        if data_version is None:
            data_version = f"sqlite-{store.content_digest[:16]}"
        super().__init__(store.load(universe), data_version=data_version)
        self.store = store

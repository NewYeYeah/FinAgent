from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import numpy as np

from finagent.domain.assets import AssetId
from finagent.domain.experiments import ArtifactRef, ArtifactType
from finagent.domain.research import DatasetRequest, ResearchDataset, ResearchSplit

from .local_ashare import AshareBarFrequency, AshareBarRecord
from .local_ashare_adapter import LocalAshareParquetDataAdapter as _BaseLocalAshareParquetDataAdapter

_FORWARD = re.compile(r"^forward_(log_return|simple_return)_(\d+)$")


def is_daily_nontrading_placeholder(row: Mapping[str, Any]) -> bool:
    """Return True for the audited vendor encoding of a suspended/no-trade daily row.

    The observed local dataset uses zero open/high/low and zero flow while carrying
    the previous close forward in ``close``. This predicate is intentionally strict:
    any other non-positive/OHLC-invalid pattern remains a data-quality error.
    """

    required = ("open", "high", "low", "close", "pre_close", "vol", "amount")
    if any(row.get(name) is None for name in required):
        return False
    try:
        open_, high, low, close, pre_close, volume, amount = (
            float(row[name]) for name in required
        )
    except (TypeError, ValueError):
        return False
    values = (open_, high, low, close, pre_close, volume, amount)
    if not all(math.isfinite(value) for value in values):
        return False
    return (
        open_ == 0.0
        and high == 0.0
        and low == 0.0
        and volume == 0.0
        and amount == 0.0
        and close > 0.0
        and pre_close > 0.0
        and math.isclose(close, pre_close, rel_tol=0.0, abs_tol=1e-9)
    )


class LocalAshareParquetDataAdapter(_BaseLocalAshareParquetDataAdapter):
    """Research adapter with explicit A-share suspension/session semantics.

    Daily no-trade placeholders are retained in the immutable vendor source but are
    not converted into ``PriceBar`` objects. Forward labels are measured on the
    common panel session clock: ``forward_*_h`` targets the h-th later panel session,
    and becomes NaN when the asset has no tradable bar on that target session.
    This prevents a one-session label from silently stretching across a suspension.
    """

    def bar_history(
        self,
        universe: tuple[AssetId, ...],
        start: datetime,
        end: datetime,
    ) -> Mapping[AssetId, tuple[AshareBarRecord, ...]]:
        """Return bounded PIT-safe raw bar records for evidence materialization.

        This is intentionally narrower than ``build_dataset`` and does not create
        features, labels, execution semantics or browser projections. A-C2 uses it
        as the public read boundary between a market adapter and MarketBarSeries.
        """

        histories = self._query_records(universe, start, end)
        return {
            asset: tuple(histories[asset])
            for asset in universe
        }

    def _select_columns(self, extra_fields: Sequence[str] = ()) -> tuple[str, ...]:
        names = super()._select_columns(extra_fields)
        if self.frequency is AshareBarFrequency.DAILY and "pre_close" in self._available_columns:
            return tuple(dict.fromkeys((*names, "pre_close")))
        return names

    def _row_to_record(self, row: Mapping[str, Any]) -> AshareBarRecord | None:
        if self.frequency is AshareBarFrequency.DAILY and is_daily_nontrading_placeholder(row):
            return None
        return super()._row_to_record(row)

    @staticmethod
    def _session_label(
        current: AshareBarRecord,
        target: AshareBarRecord | None,
        name: str,
    ) -> float:
        if target is None:
            return float("nan")
        match = _FORWARD.fullmatch(name)
        if match is None:
            raise KeyError(f"unsupported label {name!r}")
        kind = match.group(1)
        ratio = target.research_close / current.research_close
        if kind == "simple_return":
            return ratio - 1.0
        if kind == "log_return":
            return math.log(ratio)
        raise AssertionError(kind)

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
                (len(timestamps), len(request.universe)),
                dtype=np.bool_,
            )
            time_index = {timestamp: index for index, timestamp in enumerate(timestamps)}

            for asset_index, asset in enumerate(request.universe):
                history = histories[asset]
                record_by_time = {
                    record.bar.available_at: (row_index, record)
                    for row_index, record in enumerate(history)
                    if split_range.contains(record.bar.available_at)
                }
                for timestamp, (row_index, record) in record_by_time.items():
                    output_row = time_index[timestamp]
                    for feature_index, name in enumerate(request.features):
                        feature_values[output_row, asset_index, feature_index] = self._feature_value(
                            history,
                            row_index,
                            name,
                        )
                    for label_index, name in enumerate(request.labels):
                        match = _FORWARD.fullmatch(name)
                        if match is None:
                            raise KeyError(f"unsupported label {name!r}")
                        horizon = int(match.group(2))
                        target_row = output_row + horizon
                        target = None
                        if target_row < len(timestamps):
                            target_pair = record_by_time.get(timestamps[target_row])
                            if target_pair is not None:
                                target = target_pair[1]
                        label_values[output_row, asset_index, label_index] = self._session_label(
                            record,
                            target,
                            name,
                        )
                    eligible = True
                    if self.security_master is not None:
                        eligible, _ = self.security_master.eligibility(asset, record.bar.available_at)
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
                    "forward_label_clock": "common_panel_sessions",
                    "daily_nontrading_placeholder": "excluded_from_price_bars",
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
                "forward_label_clock": "common_panel_sessions",
                "daily_nontrading_placeholder": "excluded_from_price_bars",
            },
            panels=panels,
        )

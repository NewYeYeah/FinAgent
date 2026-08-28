from __future__ import annotations

from typing import Any

import numpy as np

from finagent.domain.experiments import ArtifactRef, ArtifactType
from finagent.domain.research import DatasetRequest, ResearchDataset, ResearchSplit

from .local_ashare_research_adapter import LocalAshareParquetDataAdapter


class LocalAshareInferenceDataAdapter(LocalAshareParquetDataAdapter):
    """Feature-only local A-share adapter that never reads forward-label rows.

    A2.6 keeps 2025+ untouched.  Reusing the research adapter for the final internal
    test split would ask DuckDB for ``future_rows=max_horizon`` even though those rows
    are not ultimately emitted.  This adapter deliberately sets ``future_rows=0`` and
    returns all-NaN label panels so universe construction and portfolio inference can
    use the canonical ``ResearchDataset`` contract without reading reserve evidence.

    The labels are structural placeholders only.  They must never be used for model
    fitting, Factor Quant, statistical validation, or performance attribution.
    """

    VERSION = "local-ashare-inference-adapter-v1"

    def build_dataset(self, request: DatasetRequest) -> ResearchDataset:
        self._validate_features(request.features)
        self._validate_labels(request.labels)
        panels: dict[str, ResearchSplit] = {}
        max_lag = self._max_lag(request.features)

        for split_name, split_range in request.splits.items():
            histories = self._query_records(
                request.universe,
                split_range.start,
                split_range.end,
                prior_rows=max_lag,
                future_rows=0,
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
                record_by_time: dict[Any, tuple[int, Any]] = {
                    record.bar.available_at: (row_index, record)
                    for row_index, record in enumerate(history)
                    if split_range.contains(record.bar.available_at)
                }
                for timestamp, (row_index, record) in record_by_time.items():
                    output_row = time_index[timestamp]
                    for feature_index, name in enumerate(request.features):
                        feature_values[output_row, asset_index, feature_index] = (
                            self._feature_value(history, row_index, name)
                        )
                    eligible = True
                    if self.security_master is not None:
                        eligible, _ = self.security_master.eligibility(
                            asset,
                            record.bar.available_at,
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
                    "labels": "structural_all_nan_not_observed",
                    "forward_rows_read": "0",
                    "reserve_access": "forbidden",
                    "adapter_version": self.VERSION,
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
                "adapter_version": self.VERSION,
                "inference_only": "true",
                "labels": "structural_all_nan_not_observed",
                "forward_rows_read": "0",
                "reserve_access": "forbidden",
            },
            panels=panels,
        )

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from types import MappingProxyType

import numpy as np

from finagent.data.local_ashare import (
    LocalAshareDatasetLayout,
    _duckdb,
    _sql_path,
)
from finagent.domain._validation import require_aware_datetime, require_non_empty
from finagent.domain.assets import AssetId
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.domain.universe import UniverseSnapshot


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class AshareCandidateUniverseConfig:
    selection_date: date
    top_n: int = 150
    min_universe_size: int = 50
    include_bse: bool = False
    min_listed_days: int = 250
    min_close: float = 1.0
    min_amount_cny: float = 10_000_000.0
    exclude_st: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.selection_date, date):
            raise TypeError("selection_date must be date")
        if isinstance(self.top_n, bool) or not isinstance(self.top_n, int) or self.top_n < 1:
            raise ValueError("top_n must be an integer >= 1")
        if (
            isinstance(self.min_universe_size, bool)
            or not isinstance(self.min_universe_size, int)
            or not 1 <= self.min_universe_size <= self.top_n
        ):
            raise ValueError("min_universe_size must be in [1, top_n]")
        if self.min_listed_days < 0 or self.min_close <= 0 or self.min_amount_cny < 0:
            raise ValueError("invalid candidate-universe thresholds")


@dataclass(frozen=True, slots=True)
class AshareCandidateUniverseSelection:
    data_version: str
    selection_date: date
    assets: tuple[AssetId, ...]
    ts_codes: tuple[str, ...]
    market_cap_cny: tuple[float, ...]
    amount_cny: tuple[float, ...]
    config: AshareCandidateUniverseConfig

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "data_version",
            require_non_empty(self.data_version, "data_version"),
        )
        if not self.assets or len(self.assets) != len(self.ts_codes):
            raise ValueError("candidate universe assets/codes must be non-empty and aligned")
        if len(set(self.assets)) != len(self.assets) or len(set(self.ts_codes)) != len(self.ts_codes):
            raise ValueError("candidate universe cannot contain duplicates")
        if len(self.market_cap_cny) != len(self.assets) or len(self.amount_cny) != len(self.assets):
            raise ValueError("candidate-universe diagnostics must align to assets")
        if not all(math.isfinite(value) and value >= 0 for value in self.market_cap_cny):
            raise ValueError("market caps must be finite and non-negative")
        if not all(math.isfinite(value) and value >= 0 for value in self.amount_cny):
            raise ValueError("amounts must be finite and non-negative")

    @property
    def selection_id(self) -> str:
        payload = {
            "data_version": self.data_version,
            "selection_date": self.selection_date.isoformat(),
            "ts_codes": list(self.ts_codes),
            "config": {
                "top_n": self.config.top_n,
                "min_universe_size": self.config.min_universe_size,
                "include_bse": self.config.include_bse,
                "min_listed_days": self.config.min_listed_days,
                "min_close": self.config.min_close,
                "min_amount_cny": self.config.min_amount_cny,
                "exclude_st": self.config.exclude_st,
            },
        }
        digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:24]
        return f"ashare-candidate-universe-{digest}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.ashare-candidate-universe.v1",
            "selection_id": self.selection_id,
            "data_version": self.data_version,
            "selection_date": self.selection_date.isoformat(),
            "size": len(self.assets),
            "ts_codes": list(self.ts_codes),
            "asset_keys": [asset.key for asset in self.assets],
            "scope": "fixed pre-development candidate universe; not survivorship-certified",
        }


class AshareCandidateUniverseSelector:
    """Choose a reproducible fixed A-share research universe before development starts."""

    REQUIRED_COLUMNS = frozenset(
        {"ts_code", "trade_date", "close", "amount", "circ_mv", "listed_days", "is_st"}
    )

    def __init__(
        self,
        layout: LocalAshareDatasetLayout,
        security_master,
        *,
        data_version: str,
    ) -> None:
        self.layout = layout
        self.security_master = security_master
        self.data_version = require_non_empty(data_version, "data_version")

    def select(self, config: AshareCandidateUniverseConfig) -> AshareCandidateUniverseSelection:
        pattern = r"^[0-9]{6}\.(SH|SZ|BJ)$" if config.include_bse else r"^[0-9]{6}\.(SH|SZ)$"
        st_clause = "AND coalesce(is_st, 1) = 0" if config.exclude_st else ""
        rows = _duckdb().connect().execute(
            f"""
            WITH ordered AS (
                SELECT ts_code, CAST(trade_date AS DATE) AS trade_date,
                       close, amount, circ_mv, listed_days, is_st,
                       row_number() OVER (
                           PARTITION BY ts_code ORDER BY CAST(trade_date AS DATE) DESC
                       ) AS rn
                FROM read_parquet('{_sql_path(self.layout.daily_path)}')
                WHERE CAST(trade_date AS DATE) <= ?
                  AND regexp_matches(CAST(ts_code AS VARCHAR), ?)
            )
            SELECT CAST(ts_code AS VARCHAR),
                   CAST(circ_mv AS DOUBLE) * 10000.0 AS market_cap_cny,
                   CAST(amount AS DOUBLE) * 1000.0 AS amount_cny
            FROM ordered
            WHERE rn = 1
              AND close >= ?
              AND amount * 1000.0 >= ?
              AND listed_days >= ?
              AND circ_mv IS NOT NULL
              {st_clause}
            ORDER BY market_cap_cny DESC, ts_code
            LIMIT ?
            """,
            (
                config.selection_date,
                pattern,
                config.min_close,
                config.min_amount_cny,
                config.min_listed_days,
                config.top_n,
            ),
        ).fetchall()
        by_code = {record.ts_code: record.asset for record in self.security_master.records}
        selected = [row for row in rows if str(row[0]) in by_code]
        if len(selected) < config.min_universe_size:
            raise ValueError(
                f"candidate universe contains only {len(selected)} canonical assets; "
                f"minimum is {config.min_universe_size}"
            )
        codes = tuple(str(row[0]) for row in selected)
        return AshareCandidateUniverseSelection(
            data_version=self.data_version,
            selection_date=config.selection_date,
            assets=tuple(by_code[code] for code in codes),
            ts_codes=codes,
            market_cap_cny=tuple(float(row[1]) for row in selected),
            amount_cny=tuple(float(row[2]) for row in selected),
            config=config,
        )


@dataclass(frozen=True, slots=True)
class AshareResearchUniversePolicyConfig:
    min_listed_days: int = 120
    exclude_st: bool = True
    min_close: float = 1.0
    min_median_amount_cny: float = 5_000_000.0
    liquidity_lookback: int = 20
    min_liquidity_observations: int = 10
    liquidity_warmup_calendar_days: int = 120

    def __post_init__(self) -> None:
        if self.min_listed_days < 0 or self.min_close <= 0 or self.min_median_amount_cny < 0:
            raise ValueError("invalid A-share research-universe thresholds")
        if self.liquidity_lookback < 1:
            raise ValueError("liquidity_lookback must be >= 1")
        if not 1 <= self.min_liquidity_observations <= self.liquidity_lookback:
            raise ValueError("min_liquidity_observations must be in [1, liquidity_lookback]")
        if self.liquidity_warmup_calendar_days < 1:
            raise ValueError("liquidity_warmup_calendar_days must be >= 1")

    @property
    def required_features(self) -> tuple[str, ...]:
        fields = ["close", "amount", "listed_days"]
        if self.exclude_st:
            fields.append("is_st")
        return tuple(fields)


@dataclass(frozen=True, slots=True)
class AshareUniverseSplitSummary:
    split_name: str
    timestamps: int
    assets: int
    warmup_timestamps: int
    first_session_eligible_assets: int
    eligible_cells: int
    average_eligible_assets: float
    minimum_eligible_assets: int
    maximum_eligible_assets: int
    rejected_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "split_name", require_non_empty(self.split_name, "split_name"))
        object.__setattr__(
            self,
            "rejected_counts",
            MappingProxyType({str(key): int(value) for key, value in self.rejected_counts.items()}),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "split_name": self.split_name,
            "timestamps": self.timestamps,
            "assets": self.assets,
            "warmup_timestamps": self.warmup_timestamps,
            "first_session_eligible_assets": self.first_session_eligible_assets,
            "eligible_cells": self.eligible_cells,
            "average_eligible_assets": self.average_eligible_assets,
            "minimum_eligible_assets": self.minimum_eligible_assets,
            "maximum_eligible_assets": self.maximum_eligible_assets,
            "rejected_counts": dict(self.rejected_counts),
        }


@dataclass(frozen=True, slots=True)
class AshareResearchUniverseReport:
    data_version: str
    candidate_selection_id: str
    config: AshareResearchUniversePolicyConfig
    splits: Mapping[str, AshareUniverseSplitSummary]

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_version", require_non_empty(self.data_version, "data_version"))
        object.__setattr__(
            self,
            "candidate_selection_id",
            require_non_empty(self.candidate_selection_id, "candidate_selection_id"),
        )
        if not self.splits:
            raise ValueError("A-share universe report requires split summaries")
        object.__setattr__(self, "splits", MappingProxyType(dict(self.splits)))

    @property
    def report_id(self) -> str:
        digest = hashlib.sha256(_canonical_json(self.to_dict(include_id=False)).encode()).hexdigest()[:24]
        return f"ashare-universe-policy-{digest}"

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.ashare-research-universe-policy.v1",
            "data_version": self.data_version,
            "candidate_selection_id": self.candidate_selection_id,
            "config": {
                "min_listed_days": self.config.min_listed_days,
                "exclude_st": self.config.exclude_st,
                "min_close": self.config.min_close,
                "min_median_amount_cny": self.config.min_median_amount_cny,
                "liquidity_lookback": self.config.liquidity_lookback,
                "min_liquidity_observations": self.config.min_liquidity_observations,
                "liquidity_warmup_calendar_days": (
                    self.config.liquidity_warmup_calendar_days
                ),
            },
            "splits": {key: value.to_dict() for key, value in self.splits.items()},
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


class AshareResearchUniverseProvider:
    def __init__(
        self,
        schedule: Mapping[datetime, frozenset[AssetId]],
        *,
        data_version: str,
    ) -> None:
        if not schedule:
            raise ValueError("A-share research universe schedule cannot be empty")
        normalized = {
            require_aware_datetime(timestamp, "timestamp"): frozenset(assets)
            for timestamp, assets in schedule.items()
        }
        self._schedule = MappingProxyType(normalized)
        self._data_version = require_non_empty(data_version, "data_version")

    @property
    def data_version(self) -> str:
        return self._data_version

    def snapshot(self, asof: datetime, assets: tuple[AssetId, ...]) -> UniverseSnapshot:
        asof = require_aware_datetime(asof, "asof")
        try:
            selected = self._schedule[asof]
        except KeyError as exc:
            raise KeyError(f"no A-share research universe snapshot at {asof.isoformat()}") from exc
        return UniverseSnapshot(
            asof=asof,
            eligible={asset: asset in selected for asset in assets},
            reasons={
                asset: "rejected by A-share research universe policy"
                for asset in assets
                if asset not in selected
            },
            data_version=self.data_version,
        )


class AshareResearchUniversePolicy:
    """Build a PIT research universe with split-independent rolling liquidity.

    Every requested split receives a hidden pre-split panel. The warm-up panel is
    used only to initialize trailing liquidity and is never returned as a research
    split or exposed as validation evidence. This prevents split boundaries from
    manufacturing zero-eligible sessions.
    """

    def __init__(self, config: AshareResearchUniversePolicyConfig) -> None:
        self.config = config

    def build(
        self,
        adapter,
        request: DatasetRequest,
        *,
        candidate_selection_id: str,
    ) -> tuple[AshareResearchUniverseProvider, AshareResearchUniverseReport]:
        missing = set(self.config.required_features) - set(adapter.supported_features)
        if missing:
            raise ValueError(f"local A-share adapter lacks universe-policy fields: {sorted(missing)}")

        policy_splits: dict[str, TimeRange] = {}
        warmup_names: dict[str, str] = {}
        for split_name, split_range in request.splits.items():
            warmup_name = f"__warmup__:{split_name}"
            if warmup_name in request.splits:
                raise ValueError(f"reserved universe-policy split name: {warmup_name!r}")
            warmup_names[split_name] = warmup_name
            policy_splits[warmup_name] = TimeRange(
                split_range.start - timedelta(days=self.config.liquidity_warmup_calendar_days),
                split_range.start,
            )
            policy_splits[split_name] = split_range

        policy_request = DatasetRequest(
            universe=request.universe,
            features=self.config.required_features,
            labels=request.labels,
            splits=policy_splits,
            dataset_id=f"{request.dataset_id}-universe-policy",
            metadata={
                **dict(request.metadata),
                "candidate_selection_id": candidate_selection_id,
                "purpose": "A-share PIT research universe policy with split warm-up",
            },
        )
        dataset = adapter.build_dataset(policy_request)
        schedule: dict[datetime, frozenset[AssetId]] = {}
        summaries: dict[str, AshareUniverseSplitSummary] = {}
        digest = hashlib.sha256()
        digest.update(adapter.data_version.encode())
        digest.update(candidate_selection_id.encode())
        digest.update(
            _canonical_json(
                {
                    "min_listed_days": self.config.min_listed_days,
                    "exclude_st": self.config.exclude_st,
                    "min_close": self.config.min_close,
                    "min_median_amount_cny": self.config.min_median_amount_cny,
                    "liquidity_lookback": self.config.liquidity_lookback,
                    "min_liquidity_observations": self.config.min_liquidity_observations,
                    "liquidity_warmup_calendar_days": (
                        self.config.liquidity_warmup_calendar_days
                    ),
                }
            ).encode()
        )

        for split_name in request.splits:
            panel = dataset.get_split(split_name)
            warmup = dataset.get_split(warmup_names[split_name])
            if warmup.assets != panel.assets or warmup.feature_names != panel.feature_names:
                raise ValueError("universe-policy warm-up panel is not aligned")

            base = np.asarray(panel.eligibility_mask, dtype=bool)
            close = panel.feature_panel("close")
            amount = panel.feature_panel("amount")
            warmup_amount = warmup.feature_panel("amount")
            listed_days = panel.feature_panel("listed_days")
            st = panel.feature_panel("is_st") if self.config.exclude_st else None

            listed_ok = np.isfinite(listed_days) & (listed_days >= self.config.min_listed_days)
            close_ok = np.isfinite(close) & (close >= self.config.min_close)
            st_ok = np.ones_like(base, dtype=bool)
            if st is not None:
                st_ok = np.isfinite(st) & (st <= 0.0)

            amount_history = np.concatenate((warmup_amount, amount), axis=0)
            offset = warmup.n_times
            liquidity_ok = np.zeros_like(base, dtype=bool)
            for row in range(panel.n_times):
                history_end = offset + row + 1
                history_start = max(0, history_end - self.config.liquidity_lookback)
                window = amount_history[history_start:history_end]
                for asset_index in range(panel.n_assets):
                    values = window[:, asset_index]
                    values = values[np.isfinite(values)]
                    if len(values) < self.config.min_liquidity_observations:
                        continue
                    liquidity_ok[row, asset_index] = (
                        float(np.median(values)) >= self.config.min_median_amount_cny
                    )

            final = base & listed_ok & close_ok & st_ok & liquidity_ok
            rejected = {
                "base_ineligible": int((~base).sum()),
                "listed_days": int((base & ~listed_ok).sum()),
                "price": int((base & ~close_ok).sum()),
                "st": int((base & ~st_ok).sum()),
                "liquidity": int((base & ~liquidity_ok).sum()),
            }
            counts = final.sum(axis=1)
            summaries[split_name] = AshareUniverseSplitSummary(
                split_name=split_name,
                timestamps=panel.n_times,
                assets=panel.n_assets,
                warmup_timestamps=warmup.n_times,
                first_session_eligible_assets=int(counts[0]),
                eligible_cells=int(final.sum()),
                average_eligible_assets=float(np.mean(counts)),
                minimum_eligible_assets=int(np.min(counts)),
                maximum_eligible_assets=int(np.max(counts)),
                rejected_counts=rejected,
            )
            for row, timestamp in enumerate(panel.timestamps):
                schedule[timestamp] = frozenset(
                    asset
                    for asset_index, asset in enumerate(panel.assets)
                    if final[row, asset_index]
                )
            digest.update(split_name.encode())
            digest.update(str(warmup.n_times).encode())
            digest.update("|".join(timestamp.isoformat() for timestamp in panel.timestamps).encode())
            digest.update(final.tobytes(order="C"))

        data_version = f"ashare-universe-policy-{digest.hexdigest()[:24]}"
        report = AshareResearchUniverseReport(
            data_version=data_version,
            candidate_selection_id=candidate_selection_id,
            config=self.config,
            splits=summaries,
        )
        return AshareResearchUniverseProvider(schedule, data_version=data_version), report

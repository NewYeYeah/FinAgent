from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from finagent.backtest import (
    STRATEGY_DECISION_MANIFEST_SCHEMA,
    StrategyDecisionSeriesManifest,
    StrategyDecisionSeriesProjection,
)
from finagent.data.market_bar_series import (
    MARKET_BAR_MANIFEST_SCHEMA,
    MarketBarSeriesEvidence,
    MarketBarSeriesManifest,
)


STRATEGY_EXPLORER_CATALOG_SCHEMA = "finagent.strategy-explorer.catalog.v1"
STRATEGY_EXPLORER_DIMENSIONS_SCHEMA = "finagent.strategy-explorer.dimensions.v1"


def _duckdb():
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - dependency guidance
        raise RuntimeError(
            "Strategy Decision Explorer requires the local-parquet extra"
        ) from exc
    return duckdb


def _candidate_json(paths: Sequence[str | Path]) -> tuple[Path, ...]:
    output: set[Path] = set()
    for raw in paths:
        root = Path(raw).expanduser()
        if root.is_file() and root.suffix.lower() == ".json":
            output.add(root.resolve())
        elif root.is_dir():
            output.update(
                value.resolve()
                for value in root.rglob("*.json")
                if value.is_file()
            )
    return tuple(sorted(output, key=lambda value: value.as_posix()))


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


@dataclass(frozen=True, slots=True)
class StrategyExplorerSeriesItem:
    series_id: str
    portfolio_validation_id: str
    source_program_result_id: str
    source_selection_id: str
    data_version: str
    selected_feature_digests: tuple[str, ...]
    alpha_model_ids: tuple[str, ...]
    row_count: int
    session_count: int
    asset_count: int
    start_date: str | None
    end_date: str | None
    market_bar_series_id: str | None = None
    market_bar_interval: str | None = None
    authority: str = "authoritative"

    @classmethod
    def from_manifest(
        cls,
        manifest: StrategyDecisionSeriesManifest,
    ) -> StrategyExplorerSeriesItem:
        return cls(
            series_id=manifest.series_id,
            portfolio_validation_id=manifest.portfolio_validation_id,
            source_program_result_id=manifest.source_program_result_id,
            source_selection_id=manifest.source_selection_id,
            data_version=manifest.data_version,
            selected_feature_digests=manifest.selected_feature_digests,
            alpha_model_ids=manifest.alpha_model_ids,
            row_count=manifest.row_count,
            session_count=manifest.row_session_count,
            asset_count=manifest.asset_count,
            start_date=manifest.start_date,
            end_date=manifest.end_date,
            authority=manifest.authority,
        )

    @property
    def ohlc_available(self) -> bool:
        return self.market_bar_series_id is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "series_id": self.series_id,
            "portfolio_validation_id": self.portfolio_validation_id,
            "source_program_result_id": self.source_program_result_id,
            "source_selection_id": self.source_selection_id,
            "data_version": self.data_version,
            "selected_feature_digests": list(self.selected_feature_digests),
            "alpha_model_ids": list(self.alpha_model_ids),
            "row_count": self.row_count,
            "session_count": self.session_count,
            "asset_count": self.asset_count,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "market_bar_series_id": self.market_bar_series_id,
            "market_bar_interval": self.market_bar_interval,
            "ohlc_available": self.ohlc_available,
            "authority": self.authority,
            "detail_url": f"/api/v4/strategy-series/{self.series_id}",
        }


class StrategyDecisionExplorerProjection:
    """Verified read-only index over StrategyDecisionSeries + optional MarketBarSeries.

    V4-0 decisions remain the strategy/execution authority. A-C2 may additionally bind
    an immutable MarketBarSeries only when strategy identity, A4 validation identity
    and data_version all match. OHLC is never reconstructed from close marks.
    """

    def __init__(self, report_paths: Sequence[str | Path]) -> None:
        self.report_paths = tuple(Path(value).expanduser() for value in report_paths)
        self._items: dict[str, StrategyExplorerSeriesItem] = {}
        self._projections: dict[str, StrategyDecisionSeriesProjection] = {}
        self._market_bars: dict[str, MarketBarSeriesEvidence] = {}
        self._warnings: list[str] = []
        self._notices: list[str] = []
        self._scan()

    def _scan(self) -> None:
        candidates = _candidate_json(self.report_paths)
        items: dict[str, StrategyExplorerSeriesItem] = {}
        projections: dict[str, StrategyDecisionSeriesProjection] = {}
        market_bars: dict[str, MarketBarSeriesEvidence] = {}
        warnings: list[str] = []
        notices: list[str] = []
        conflicts: set[str] = set()

        for path in candidates:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            payload = _mapping(raw)
            if payload.get("schema_version") != STRATEGY_DECISION_MANIFEST_SCHEMA:
                continue
            try:
                manifest = StrategyDecisionSeriesManifest.from_dict(payload)
                projection = StrategyDecisionSeriesProjection(path)
            except (
                OSError,
                RuntimeError,
                ValueError,
                TypeError,
                json.JSONDecodeError,
            ) as exc:
                warnings.append(f"{path}: {type(exc).__name__}: {exc}")
                continue
            series_id = manifest.series_id
            item = StrategyExplorerSeriesItem.from_manifest(manifest)
            if series_id in conflicts:
                continue
            if series_id in items:
                if items[series_id] == item:
                    notices.append(
                        f"{path}: equivalent StrategyDecisionSeries {series_id!r} ignored"
                    )
                    continue
                warnings.append(
                    f"{path}: conflicting manifests share series_id {series_id!r}; "
                    "the identity is omitted until the conflict is resolved"
                )
                items.pop(series_id, None)
                projections.pop(series_id, None)
                conflicts.add(series_id)
                continue
            items[series_id] = item
            projections[series_id] = projection

        market_conflicts: set[str] = set()
        for path in candidates:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            payload = _mapping(raw)
            if payload.get("schema_version") != MARKET_BAR_MANIFEST_SCHEMA:
                continue
            try:
                manifest = MarketBarSeriesManifest.from_dict(payload)
                evidence = MarketBarSeriesEvidence(path)
            except (
                OSError,
                RuntimeError,
                ValueError,
                TypeError,
                json.JSONDecodeError,
            ) as exc:
                warnings.append(f"{path}: {type(exc).__name__}: {exc}")
                continue
            strategy_id = manifest.linked_strategy_series_id
            if strategy_id not in items:
                notices.append(
                    f"{path}: MarketBarSeries {manifest.series_id!r} has no configured "
                    f"StrategyDecisionSeries {strategy_id!r}; binding omitted"
                )
                continue
            item = items[strategy_id]
            if manifest.portfolio_validation_id != item.portfolio_validation_id:
                warnings.append(
                    f"{path}: MarketBarSeries portfolio_validation_id does not match "
                    f"StrategyDecisionSeries {strategy_id!r}; binding omitted"
                )
                continue
            if manifest.data_version != item.data_version:
                warnings.append(
                    f"{path}: MarketBarSeries data_version does not match "
                    f"StrategyDecisionSeries {strategy_id!r}; binding omitted"
                )
                continue
            if strategy_id in market_conflicts:
                continue
            existing = market_bars.get(strategy_id)
            if existing is not None:
                if existing.manifest == manifest:
                    notices.append(
                        f"{path}: equivalent MarketBarSeries {manifest.series_id!r} ignored"
                    )
                    continue
                warnings.append(
                    f"{path}: multiple MarketBarSeries bind StrategyDecisionSeries "
                    f"{strategy_id!r}; OHLC is fail-closed until the conflict is resolved"
                )
                market_bars.pop(strategy_id, None)
                market_conflicts.add(strategy_id)
                continue
            market_bars[strategy_id] = evidence

        for strategy_id, evidence in market_bars.items():
            items[strategy_id] = replace(
                items[strategy_id],
                market_bar_series_id=evidence.manifest.series_id,
                market_bar_interval=evidence.manifest.interval.value,
            )

        self._items = items
        self._projections = projections
        self._market_bars = market_bars
        self._warnings = warnings
        self._notices = notices

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)

    @property
    def notices(self) -> tuple[str, ...]:
        return tuple(self._notices)

    def status(self) -> dict[str, object]:
        ohlc_available = bool(self._market_bars)
        return {
            "schema_version": "finagent.strategy-explorer.status.v1",
            "read_only": True,
            "authority": "authoritative_source_projection",
            "series_count": len(self._items),
            "market_bar_series_count": len(self._market_bars),
            "warning_count": len(self._warnings),
            "price_semantics": (
                "authoritative_market_bar_ohlc_when_bound_else_v4_close_only"
            ),
            "ohlc_available": ohlc_available,
            "ohlc_authority": (
                "MarketBarSeriesEvidence" if ohlc_available else "unavailable"
            ),
            "browser_recomputation": False,
        }

    def catalog(self) -> dict[str, object]:
        return {
            "schema_version": STRATEGY_EXPLORER_CATALOG_SCHEMA,
            "read_only": True,
            "items": [self._items[key].to_dict() for key in sorted(self._items)],
            "warnings": list(self._warnings),
            "notices": list(self._notices),
        }

    def item(self, series_id: str) -> StrategyExplorerSeriesItem:
        try:
            return self._items[series_id]
        except KeyError as exc:
            raise KeyError(series_id) from exc

    def projection(self, series_id: str) -> StrategyDecisionSeriesProjection:
        try:
            return self._projections[series_id]
        except KeyError as exc:
            raise KeyError(series_id) from exc

    def market_bar_projection(self, series_id: str) -> MarketBarSeriesEvidence:
        if series_id not in self._items:
            raise KeyError(series_id)
        try:
            return self._market_bars[series_id]
        except KeyError as exc:
            raise KeyError(f"MarketBarSeries unavailable for {series_id}") from exc

    def market_bar_binding(self, series_id: str) -> dict[str, object] | None:
        evidence = self._market_bars.get(series_id)
        if evidence is None:
            return None
        manifest = evidence.manifest
        return {
            "authority": "authoritative",
            "series_id": manifest.series_id,
            "interval": manifest.interval.value,
            "timestamp_convention": manifest.timestamp_convention.value,
            "source_identity": manifest.source_identity,
            "data_version": manifest.data_version,
            "row_count": manifest.row_count,
            "asset_count": manifest.asset_count,
            "session_count": manifest.session_count,
            "session_spec": manifest.session_spec.to_dict(),
            "label_horizon_policy": manifest.label_horizon_policy.to_dict(),
        }

    def by_portfolio(self, portfolio_validation_id: str) -> StrategyExplorerSeriesItem:
        matches = [
            item
            for item in self._items.values()
            if item.portfolio_validation_id == portfolio_validation_id
        ]
        if not matches:
            raise KeyError(portfolio_validation_id)
        if len(matches) != 1:
            raise ValueError(
                "portfolio validation resolves to multiple StrategyDecisionSeries identities"
            )
        return matches[0]

    def dimensions(self, series_id: str) -> dict[str, object]:
        projection = self.projection(series_id)
        duckdb = _duckdb()
        connection = duckdb.connect()
        try:
            assets = tuple(
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT asset FROM read_parquet(?) ORDER BY asset",
                    (str(projection.data_path),),
                ).fetchall()
            )
            folds = tuple(
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT fold_id FROM read_parquet(?) ORDER BY fold_id",
                    (str(projection.data_path),),
                ).fetchall()
            )
            bounds = connection.execute(
                "SELECT min(session_date), max(session_date), "
                "count(DISTINCT session_date) FROM read_parquet(?)",
                (str(projection.data_path),),
            ).fetchone()
        finally:
            connection.close()
        start = bounds[0] if bounds else None
        end = bounds[1] if bounds else None
        sessions = int(bounds[2]) if bounds else 0
        manifest = projection.manifest
        if len(assets) != manifest.asset_count:
            raise ValueError("V4-2 asset dimensions differ from V4-0 manifest")
        if sessions != manifest.row_session_count:
            raise ValueError("V4-2 session dimensions differ from V4-0 manifest")
        if start is not None and str(start) != str(manifest.start_date):
            raise ValueError("V4-2 start date differs from V4-0 manifest")
        if end is not None and str(end) != str(manifest.end_date):
            raise ValueError("V4-2 end date differs from V4-0 manifest")
        binding = self.market_bar_binding(series_id)
        return {
            "schema_version": STRATEGY_EXPLORER_DIMENSIONS_SCHEMA,
            "read_only": True,
            "authority": "authoritative",
            "series_id": manifest.series_id,
            "portfolio_validation_id": manifest.portfolio_validation_id,
            "assets": list(assets),
            "folds": list(folds),
            "start_date": str(start) if start is not None else None,
            "end_date": str(end) if end is not None else None,
            "session_count": sessions,
            "price_semantics": (
                "OHLC from bound MarketBarSeriesEvidence"
                if binding is not None
                else "close_price from authoritative A4 close marks"
            ),
            "ohlc_available": binding is not None,
            "market_bar_series_id": binding["series_id"] if binding else None,
            "market_bar_interval": binding["interval"] if binding else None,
        }

    def query(
        self,
        series_id: str,
        *,
        asset: str | None = None,
        start: date | None = None,
        end: date | None = None,
        fold_id: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> dict[str, object]:
        return self.projection(series_id).query(
            asset=asset,
            start=start,
            end=end,
            fold_id=fold_id,
            limit=limit,
            offset=offset,
        )

    def bars(
        self,
        series_id: str,
        *,
        asset: str | None = None,
        start: date | None = None,
        end: date | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> dict[str, object]:
        return self.market_bar_projection(series_id).query(
            asset=asset,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )

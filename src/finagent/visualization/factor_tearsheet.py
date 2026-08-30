from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform

from finagent.research import FactorSeriesManifest, FactorSeriesProjection
from finagent.research.factor_series import FACTOR_SERIES_MANIFEST_SCHEMA


FACTOR_TEAR_SHEET_CATALOG_SCHEMA = "finagent.factor-tear-sheet.catalog.v1"
FACTOR_TEAR_SHEET_DIMENSIONS_SCHEMA = "finagent.factor-tear-sheet.dimensions.v1"
FACTOR_TEAR_SHEET_SUMMARY_SCHEMA = "finagent.factor-tear-sheet.summary.v1"
FACTOR_TEAR_SHEET_CORRELATION_SCHEMA = "finagent.factor-tear-sheet.correlation.v1"
FACTOR_TEAR_SHEET_HEATMAP_SCHEMA = "finagent.factor-tear-sheet.heatmap.v1"
FACTOR_TEAR_SHEET_PROVENANCE_SCHEMA = "finagent.factor-tear-sheet.provenance.v1"


def _duckdb():
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - dependency guidance
        raise RuntimeError("Factor Tear Sheet requires the local-parquet extra") from exc
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


def _sequence(value: object) -> Sequence[Any]:
    return (
        value
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
        else ()
    )


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _number(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    result = float(value)  # type: ignore[arg-type]
    if not math.isfinite(result):
        raise ValueError("V4-3 numeric source value must be finite")
    return result


def _integer(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    return int(value)


@dataclass(frozen=True, slots=True)
class FactorTearSheetSeriesItem:
    series_id: str
    program_result_id: str
    program_id: str
    data_version: str
    candidate_feature_digests: tuple[str, ...]
    selected_feature_digests: tuple[str, ...]
    primary_label: str
    decay_labels: tuple[str, ...]
    row_count: int
    factor_count: int
    fold_count: int
    session_count: int
    start_date: str | None
    end_date: str | None
    authority: str = "authoritative"

    @classmethod
    def from_manifest(cls, manifest: FactorSeriesManifest) -> FactorTearSheetSeriesItem:
        return cls(
            series_id=manifest.series_id,
            program_result_id=manifest.program_result_id,
            program_id=manifest.program_id,
            data_version=manifest.data_version,
            candidate_feature_digests=manifest.candidate_feature_digests,
            selected_feature_digests=manifest.selected_feature_digests,
            primary_label=manifest.primary_label,
            decay_labels=manifest.decay_labels,
            row_count=manifest.row_count,
            factor_count=manifest.factor_count,
            fold_count=manifest.fold_count,
            session_count=manifest.session_count,
            start_date=manifest.start_date,
            end_date=manifest.end_date,
            authority=manifest.authority,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "series_id": self.series_id,
            "program_result_id": self.program_result_id,
            "program_id": self.program_id,
            "data_version": self.data_version,
            "candidate_feature_digests": list(self.candidate_feature_digests),
            "selected_feature_digests": list(self.selected_feature_digests),
            "primary_label": self.primary_label,
            "decay_labels": list(self.decay_labels),
            "row_count": self.row_count,
            "factor_count": self.factor_count,
            "fold_count": self.fold_count,
            "session_count": self.session_count,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "authority": self.authority,
            "detail_url": f"/api/v4/factor-series/{self.series_id}",
        }


class FactorTearSheetProjection:
    """Verified V4-3 read projection over immutable V4-1/A2.6 factor evidence.

    The projection never recreates factor statistics in React. V4-1 period rows are
    opened through FactorSeriesProjection, so source-report/manifest/Parquet identity
    is verified before a series becomes visible. Frozen A2.6 inference/gate/selection
    summaries remain authoritative source values. Year/fold means and correlation
    ordering are explicit deterministic presentation derivatives.
    """

    def __init__(self, report_paths: Sequence[str | Path]) -> None:
        self.report_paths = tuple(Path(value).expanduser() for value in report_paths)
        self._items: dict[str, FactorTearSheetSeriesItem] = {}
        self._projections: dict[str, FactorSeriesProjection] = {}
        self._reports: dict[str, Mapping[str, Any]] = {}
        self._warnings: list[str] = []
        self._notices: list[str] = []
        self._scan()

    def _scan(self) -> None:
        items: dict[str, FactorTearSheetSeriesItem] = {}
        projections: dict[str, FactorSeriesProjection] = {}
        reports: dict[str, Mapping[str, Any]] = {}
        warnings: list[str] = []
        notices: list[str] = []
        conflicts: set[str] = set()

        for path in _candidate_json(self.report_paths):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            payload = _mapping(raw)
            if payload.get("schema_version") != FACTOR_SERIES_MANIFEST_SCHEMA:
                continue
            try:
                manifest = FactorSeriesManifest.from_dict(payload)
                projection = FactorSeriesProjection(path)
                report_raw = json.loads(projection.report_path.read_text(encoding="utf-8"))
                if not isinstance(report_raw, Mapping):
                    raise ValueError("V4-3 source A2.6 report root must be an object")
                report = _mapping(report_raw)
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
            item = FactorTearSheetSeriesItem.from_manifest(manifest)
            if series_id in conflicts:
                continue
            if series_id in items:
                if items[series_id] == item:
                    notices.append(
                        f"{path}: equivalent FactorSeries {series_id!r} ignored"
                    )
                    continue
                warnings.append(
                    f"{path}: conflicting manifests share series_id {series_id!r}; "
                    "the identity is omitted until the conflict is resolved"
                )
                items.pop(series_id, None)
                projections.pop(series_id, None)
                reports.pop(series_id, None)
                conflicts.add(series_id)
                continue
            items[series_id] = item
            projections[series_id] = projection
            reports[series_id] = report

        self._items = items
        self._projections = projections
        self._reports = reports
        self._warnings = warnings
        self._notices = notices

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)

    @property
    def notices(self) -> tuple[str, ...]:
        return tuple(self._notices)

    def status(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.factor-tear-sheet.status.v1",
            "read_only": True,
            "authority": "verified_v4_1_and_frozen_a2p6_projection",
            "series_count": len(self._items),
            "warning_count": len(self._warnings),
            "browser_recomputation": False,
            "agent_chronology_available": False,
        }

    def catalog(self) -> dict[str, object]:
        return {
            "schema_version": FACTOR_TEAR_SHEET_CATALOG_SCHEMA,
            "read_only": True,
            "items": [self._items[key].to_dict() for key in sorted(self._items)],
            "warnings": list(self._warnings),
            "notices": list(self._notices),
        }

    def item(self, series_id: str) -> FactorTearSheetSeriesItem:
        try:
            return self._items[series_id]
        except KeyError as exc:
            raise KeyError(series_id) from exc

    def projection(self, series_id: str) -> FactorSeriesProjection:
        try:
            return self._projections[series_id]
        except KeyError as exc:
            raise KeyError(series_id) from exc

    def report(self, series_id: str) -> Mapping[str, Any]:
        try:
            return self._reports[series_id]
        except KeyError as exc:
            raise KeyError(series_id) from exc

    def by_program(self, program_id: str) -> FactorTearSheetSeriesItem:
        matches = [item for item in self._items.values() if item.program_id == program_id]
        if not matches:
            raise KeyError(program_id)
        if len(matches) != 1:
            raise ValueError("program resolves to multiple FactorSeries identities")
        return matches[0]

    def _source_maps(
        self, series_id: str
    ) -> tuple[
        Sequence[Any],
        Mapping[str, Mapping[str, Any]],
        Mapping[str, Mapping[str, Any]],
        Mapping[str, Mapping[str, Any]],
    ]:
        report = self.report(series_id)
        denominator = _sequence(report.get("candidate_denominator"))
        walk = _mapping(report.get("walk_forward_report"))
        gate = _mapping(report.get("gate_report"))
        selection = _mapping(report.get("frozen_selection"))
        candidates = {
            _text(_mapping(value).get("feature_digest")): _mapping(value)
            for value in _sequence(walk.get("candidates"))
        }
        gates = {
            _text(_mapping(value).get("feature_digest")): _mapping(value)
            for value in _sequence(gate.get("candidates"))
        }
        selected = {
            _text(_mapping(value).get("feature_digest")): _mapping(value)
            for value in _sequence(selection.get("components"))
        }
        return denominator, candidates, gates, selected

    def dimensions(self, series_id: str) -> dict[str, object]:
        projection = self.projection(series_id)
        report = self.report(series_id)
        duckdb = _duckdb()
        connection = duckdb.connect()
        try:
            factor_rows = connection.execute(
                "SELECT DISTINCT feature_id, feature_digest FROM read_parquet(?) "
                "ORDER BY feature_digest",
                (str(projection.data_path),),
            ).fetchall()
            folds = tuple(
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT fold_id FROM read_parquet(?) ORDER BY fold_id",
                    (str(projection.data_path),),
                ).fetchall()
            )
            labels = tuple(
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT label_name FROM read_parquet(?) "
                    "WHERE label_name <> '' ORDER BY label_name",
                    (str(projection.data_path),),
                ).fetchall()
            )
            quantiles = tuple(
                int(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT quantile FROM read_parquet(?) "
                    "WHERE quantile IS NOT NULL ORDER BY quantile",
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

        manifest = projection.manifest
        parquet_factors = {str(row[1]) for row in factor_rows}
        if parquet_factors != set(manifest.candidate_feature_digests):
            raise ValueError("V4-3 factor dimensions differ from V4-1 manifest")
        if len(folds) != manifest.fold_count:
            raise ValueError("V4-3 fold dimensions differ from V4-1 manifest")
        sessions = int(bounds[2]) if bounds else 0
        if sessions != manifest.session_count:
            raise ValueError("V4-3 session dimensions differ from V4-1 manifest")
        start = str(bounds[0]) if bounds and bounds[0] is not None else None
        end = str(bounds[1]) if bounds and bounds[1] is not None else None
        if start != manifest.start_date or end != manifest.end_date:
            raise ValueError("V4-3 date dimensions differ from V4-1 manifest")

        denominator = [_mapping(value) for value in _sequence(report.get("candidate_denominator"))]
        selected = set(manifest.selected_feature_digests)
        factors = [
            {
                "ordinal": index,
                "feature_id": _text(value.get("feature_id")),
                "feature_digest": _text(value.get("feature_digest")),
                "hypothesis": _text(value.get("hypothesis")),
                "generator_id": _text(value.get("generator_id")),
                "selected": _text(value.get("feature_digest")) in selected,
            }
            for index, value in enumerate(denominator)
        ]
        if {str(value["feature_digest"]) for value in factors} != parquet_factors:
            raise ValueError("V4-3 denominator metadata differs from V4-1 Parquet")

        return {
            "schema_version": FACTOR_TEAR_SHEET_DIMENSIONS_SCHEMA,
            "read_only": True,
            "authority": "authoritative_identity_dimensions",
            "series_id": manifest.series_id,
            "program_result_id": manifest.program_result_id,
            "program_id": manifest.program_id,
            "factors": factors,
            "folds": list(folds),
            "labels": list(labels),
            "primary_label": manifest.primary_label,
            "decay_labels": list(manifest.decay_labels),
            "quantiles": list(quantiles),
            "start_date": start,
            "end_date": end,
            "session_count": sessions,
            "rolling_window": manifest.rolling_window,
            "metric_authority": {
                "authoritative": [
                    "pearson_ic_raw",
                    "rank_ic_raw",
                    "pearson_ic",
                    "rank_ic",
                    "return",
                    "one_way_turnover",
                    "eligible_count",
                    "valid_factor_count",
                    "coverage",
                ],
                "derived": ["rolling_pearson_ic", "rolling_rank_ic", "nav"],
            },
        }

    def summary(
        self, series_id: str, *, feature_digest: str | None = None
    ) -> dict[str, object]:
        report = self.report(series_id)
        denominator, candidates, gates, selected = self._source_maps(series_id)
        selection = _mapping(report.get("frozen_selection"))
        items: list[dict[str, object]] = []
        for ordinal, raw in enumerate(denominator):
            provenance = _mapping(raw)
            digest = _text(provenance.get("feature_digest"))
            if feature_digest and digest != feature_digest:
                continue
            candidate = candidates.get(digest)
            gate = gates.get(digest)
            if candidate is None or gate is None:
                raise ValueError("V4-3 A2.6 candidate/gate identity is incomplete")
            component = selected.get(digest, {})
            hac = _mapping(candidate.get("hac"))
            bootstrap = _mapping(candidate.get("block_bootstrap"))
            folds = [_mapping(value) for value in _sequence(candidate.get("folds"))]
            items.append(
                {
                    "ordinal": ordinal,
                    "feature_id": _text(candidate.get("feature_id")),
                    "feature_digest": digest,
                    "hypothesis": _text(provenance.get("hypothesis")),
                    "generator_id": _text(provenance.get("generator_id")),
                    "input_fields": [str(value) for value in _sequence(provenance.get("input_fields"))],
                    "lookback": _integer(provenance.get("lookback")),
                    "selected": digest in selected,
                    "selection": {
                        "direction": _integer(component.get("direction")) if component else None,
                        "robust_score": _number(component.get("robust_score")) if component else None,
                        "weight": _number(component.get("weight")) if component else None,
                    },
                    "gate": {
                        "passed": gate.get("passed") is True,
                        "reason_codes": [str(value) for value in _sequence(gate.get("reason_codes"))],
                        "robust_score": _number(gate.get("robust_score")),
                    },
                    "metrics": {
                        "dominant_direction": _integer(candidate.get("dominant_direction")),
                        "direction_consistency": _number(candidate.get("direction_consistency")),
                        "pooled_rank_ic": _number(candidate.get("pooled_rank_ic")),
                        "pooled_rank_icir": _number(candidate.get("pooled_rank_icir")),
                        "mean_fold_rank_icir": _number(candidate.get("mean_fold_rank_icir")),
                        "worst_fold_rank_icir": _number(candidate.get("worst_fold_rank_icir")),
                        "positive_fold_ratio": _number(candidate.get("positive_fold_ratio")),
                        "mean_fold_long_short_sharpe": _number(candidate.get("mean_fold_long_short_sharpe")),
                        "worst_fold_long_short_sharpe": _number(candidate.get("worst_fold_long_short_sharpe")),
                        "coverage_mean": _number(candidate.get("coverage_mean")),
                        "coverage_min": _number(candidate.get("coverage_min")),
                        "quantile_monotonicity": _number(candidate.get("quantile_monotonicity")),
                        "mean_one_way_turnover": _number(candidate.get("mean_one_way_turnover")),
                        "horizon_sign_consistency": _number(candidate.get("horizon_sign_consistency")),
                    },
                    "hac": {
                        "tstat": _number(hac.get("tstat")),
                        "raw_pvalue": _number(hac.get("raw_pvalue"), 1.0),
                        "holm_adjusted_pvalue": _number(hac.get("holm_adjusted_pvalue"), 1.0),
                        "bh_qvalue": _number(hac.get("bh_qvalue"), 1.0),
                    },
                    "block_bootstrap": {
                        "pvalue": _number(bootstrap.get("pvalue"), 1.0),
                        "ci_lower": _number(bootstrap.get("ci_lower")),
                        "ci_upper": _number(bootstrap.get("ci_upper")),
                    },
                    "folds": [dict(value) for value in folds],
                }
            )
        if feature_digest and not items:
            raise KeyError(feature_digest)
        return {
            "schema_version": FACTOR_TEAR_SHEET_SUMMARY_SCHEMA,
            "read_only": True,
            "authority": "authoritative_frozen_a2p6_summary",
            "series_id": self.item(series_id).series_id,
            "program_result_id": self.item(series_id).program_result_id,
            "selection_status": _text(selection.get("status")),
            "gate_report_id": _text(_mapping(report.get("gate_report")).get("gate_report_id")),
            "selection_id": _text(selection.get("selection_id")),
            "items": items,
        }

    def correlations(self, series_id: str) -> dict[str, object]:
        report = self.report(series_id)
        manifest = self.projection(series_id).manifest
        walk = _mapping(report.get("walk_forward_report"))
        raw = _mapping(walk.get("factor_value_correlations"))
        factors = list(manifest.candidate_feature_digests)
        count = len(factors)
        matrix = np.eye(count, dtype=float)
        cells: list[dict[str, object]] = []
        for left_index, left in enumerate(factors):
            for right_index, right in enumerate(factors):
                if left_index == right_index:
                    value = 1.0
                else:
                    key = "|".join(sorted((left, right)))
                    value = _number(raw.get(key), 0.0)
                    if not -1.0 <= value <= 1.0:
                        raise ValueError("V4-3 factor correlation is outside [-1, 1]")
                matrix[left_index, right_index] = value
                cells.append({"left": left, "right": right, "value": value})
        if not np.allclose(matrix, matrix.T, rtol=0.0, atol=1e-12):
            raise ValueError("V4-3 factor correlation matrix is not symmetric")

        cluster_order = list(factors)
        if count > 1:
            distance = 1.0 - np.abs(matrix)
            np.fill_diagonal(distance, 0.0)
            condensed = squareform(distance, checks=False)
            tree = linkage(condensed, method="average", optimal_ordering=True)
            cluster_order = [factors[int(index)] for index in leaves_list(tree)]

        return {
            "schema_version": FACTOR_TEAR_SHEET_CORRELATION_SCHEMA,
            "read_only": True,
            "series_id": manifest.series_id,
            "factors": factors,
            "cells": cells,
            "correlation_authority": "authoritative_frozen_a2p6_summary",
            "cluster_order": cluster_order,
            "cluster_authority": "derived_presentation",
            "cluster_method": "average_linkage_on_1_minus_absolute_correlation",
        }

    def heatmap(
        self,
        series_id: str,
        *,
        feature_digest: str | None = None,
        label_name: str | None = None,
        metric: str = "rank_ic",
    ) -> dict[str, object]:
        if metric not in {"rank_ic", "pearson_ic"}:
            raise ValueError("V4-3 heatmap metric must be rank_ic or pearson_ic")
        projection = self.projection(series_id)
        manifest = projection.manifest
        label = (label_name or manifest.primary_label).strip()
        where = ["series_kind = 'ic'", "metric = ?", "label_name = ?"]
        parameters: list[object] = [str(projection.data_path), metric, label]
        if feature_digest:
            if feature_digest not in manifest.candidate_feature_digests:
                raise KeyError(feature_digest)
            where.append("feature_digest = ?")
            parameters.append(feature_digest)
        predicate = " AND ".join(where)
        duckdb = _duckdb()
        connection = duckdb.connect()
        try:
            rows = connection.execute(
                "SELECT feature_digest, fold_id, year(session_date) AS year, "
                "avg(value) AS mean_value, count(*) AS observations "
                f"FROM read_parquet(?) WHERE {predicate} "
                "GROUP BY feature_digest, fold_id, year(session_date) "
                "ORDER BY feature_digest, fold_id, year",
                parameters,
            ).fetchall()
        finally:
            connection.close()
        cells = [
            {
                "feature_digest": str(row[0]),
                "fold_id": str(row[1]),
                "year": int(row[2]),
                "value": float(row[3]),
                "observations": int(row[4]),
            }
            for row in rows
        ]
        return {
            "schema_version": FACTOR_TEAR_SHEET_HEATMAP_SCHEMA,
            "read_only": True,
            "authority": "derived_presentation",
            "source_authority": "authoritative_v4_1_period_rows",
            "aggregation": "arithmetic_mean_by_factor_fold_calendar_year",
            "series_id": manifest.series_id,
            "metric": metric,
            "label_name": label,
            "cells": cells,
        }

    def provenance(self, series_id: str) -> dict[str, object]:
        denominator, _candidates, gates, selected = self._source_maps(series_id)
        items = []
        for ordinal, raw in enumerate(denominator):
            value = _mapping(raw)
            digest = _text(value.get("feature_digest"))
            gate = gates.get(digest, {})
            items.append(
                {
                    "ordinal": ordinal,
                    "feature_id": _text(value.get("feature_id")),
                    "feature_digest": digest,
                    "hypothesis": _text(value.get("hypothesis")),
                    "generator_id": _text(value.get("generator_id")),
                    "input_fields": [str(item) for item in _sequence(value.get("input_fields"))],
                    "lookback": _integer(value.get("lookback")),
                    "gate_passed": gate.get("passed") is True,
                    "gate_reason_codes": [str(item) for item in _sequence(gate.get("reason_codes"))],
                    "selected": digest in selected,
                }
            )
        return {
            "schema_version": FACTOR_TEAR_SHEET_PROVENANCE_SCHEMA,
            "read_only": True,
            "authority": "authoritative_frozen_candidate_denominator",
            "ordering_semantics": "frozen_candidate_denominator_order_only",
            "agent_chronology_available": False,
            "chronology_note": (
                "A2.6 freezes candidate identity, hypothesis and generator_id but does not "
                "freeze an Agent generation timestamp/round timeline; V4-3 does not infer one"
            ),
            "series_id": self.item(series_id).series_id,
            "items": items,
        }

    def query(
        self,
        series_id: str,
        *,
        feature_digest: str | None = None,
        fold_id: str | None = None,
        series_kind: str | None = None,
        metric: str | None = None,
        label_name: str | None = None,
        quantile: int | None = None,
        start: date | None = None,
        end: date | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> dict[str, object]:
        return self.projection(series_id).query(
            feature_digest=feature_digest,
            fold_id=fold_id,
            series_kind=series_kind,
            metric=metric,
            label_name=label_name,
            quantile=quantile,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )

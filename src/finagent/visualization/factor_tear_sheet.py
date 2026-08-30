from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

from finagent.research.factor_series import (
    FACTOR_SERIES_MANIFEST_SCHEMA,
    FactorSeriesManifest,
    FactorSeriesProjection,
)


FACTOR_TEAR_SHEET_CATALOG_SCHEMA = "finagent.factor-tear-sheet.catalog.v1"
FACTOR_TEAR_SHEET_DIMENSIONS_SCHEMA = "finagent.factor-tear-sheet.dimensions.v1"
FACTOR_TEAR_SHEET_SUMMARY_SCHEMA = "finagent.factor-tear-sheet.summary.v1"


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
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return cast(Sequence[Any], value)
    return ()


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


@dataclass(frozen=True, slots=True)
class FactorTearSheetSeriesItem:
    series_id: str
    program_result_id: str
    program_id: str
    selection_id: str
    data_version: str
    candidate_feature_digests: tuple[str, ...]
    selected_feature_digests: tuple[str, ...]
    primary_label: str
    decay_labels: tuple[str, ...]
    quantiles: int
    row_count: int
    factor_count: int
    fold_count: int
    session_count: int
    start_date: str | None
    end_date: str | None
    source_report_content_digest: str
    authority: str = "authoritative"

    @classmethod
    def from_manifest(cls, manifest: FactorSeriesManifest) -> FactorTearSheetSeriesItem:
        return cls(
            series_id=manifest.series_id,
            program_result_id=manifest.program_result_id,
            program_id=manifest.program_id,
            selection_id=manifest.selection_id,
            data_version=manifest.data_version,
            candidate_feature_digests=manifest.candidate_feature_digests,
            selected_feature_digests=manifest.selected_feature_digests,
            primary_label=manifest.primary_label,
            decay_labels=manifest.decay_labels,
            quantiles=manifest.quantiles,
            row_count=manifest.row_count,
            factor_count=manifest.factor_count,
            fold_count=manifest.fold_count,
            session_count=manifest.session_count,
            start_date=manifest.start_date,
            end_date=manifest.end_date,
            source_report_content_digest=manifest.source_report_content_digest,
            authority=manifest.authority,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "series_id": self.series_id,
            "program_result_id": self.program_result_id,
            "program_id": self.program_id,
            "selection_id": self.selection_id,
            "data_version": self.data_version,
            "candidate_feature_digests": list(self.candidate_feature_digests),
            "selected_feature_digests": list(self.selected_feature_digests),
            "primary_label": self.primary_label,
            "decay_labels": list(self.decay_labels),
            "quantiles": self.quantiles,
            "row_count": self.row_count,
            "factor_count": self.factor_count,
            "fold_count": self.fold_count,
            "session_count": self.session_count,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "source_report_content_digest": self.source_report_content_digest,
            "authority": self.authority,
            "detail_url": f"/api/v4/factor-series/{self.series_id}",
        }


class FactorTearSheetProjection:
    """Verified V4-3A read model over immutable V4-1 FactorSeries evidence.

    The projection deliberately keeps two evidence classes visible. Period rows retain
    the authority stored by V4-1 (authoritative observations versus persisted derived
    rolling IC/NAV), while statistical summaries are copied from the physically bound
    frozen A2.6 source report. No IC, p-value, confidence interval, multiple-testing
    correction or NAV is recomputed by this projection or by the browser.
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
        semantic_keys: dict[str, tuple[object, ...]] = {}
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
                    raise ValueError("V4-3A source A2.6 report root must be an object")
                report = cast(Mapping[str, Any], report_raw)
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
            semantic_key = (
                item,
                manifest.rows_digest,
                manifest.quant_config_digest,
                manifest.source_report_content_digest,
            )
            if series_id in conflicts:
                continue
            if series_id in items:
                if semantic_keys[series_id] == semantic_key:
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
                semantic_keys.pop(series_id, None)
                conflicts.add(series_id)
                continue
            items[series_id] = item
            projections[series_id] = projection
            reports[series_id] = report
            semantic_keys[series_id] = semantic_key

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
            "series_count": len(self._items),
            "warning_count": len(self._warnings),
            "period_evidence": "v4_1_persisted_authority",
            "statistical_summary": "frozen_a2p6_authoritative",
            "browser_recomputation": False,
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

    def source_report(self, series_id: str) -> Mapping[str, Any]:
        try:
            return self._reports[series_id]
        except KeyError as exc:
            raise KeyError(series_id) from exc

    def by_program(self, program_id: str) -> FactorTearSheetSeriesItem:
        matches = [item for item in self._items.values() if item.program_id == program_id]
        if not matches:
            raise KeyError(program_id)
        if len(matches) != 1:
            raise ValueError(
                "program_id resolves to multiple FactorSeries identities; select a series explicitly"
            )
        return matches[0]

    def dimensions(self, series_id: str) -> dict[str, object]:
        projection = self.projection(series_id)
        manifest = projection.manifest
        duckdb = _duckdb()
        connection = duckdb.connect()
        try:
            factor_rows = connection.execute(
                "SELECT DISTINCT feature_digest, feature_id FROM read_parquet(?) "
                "ORDER BY feature_digest, feature_id",
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

        feature_ids: dict[str, str] = {}
        for digest_raw, feature_id_raw in factor_rows:
            digest = str(digest_raw)
            feature_id = str(feature_id_raw)
            existing = feature_ids.get(digest)
            if existing is not None and existing != feature_id:
                raise ValueError("V4-3A factor digest maps to multiple feature_id values")
            feature_ids[digest] = feature_id
        if set(feature_ids) != set(manifest.candidate_feature_digests):
            raise ValueError("V4-3A factor dimensions differ from V4-1 manifest")
        if len(folds) != manifest.fold_count:
            raise ValueError("V4-3A fold dimensions differ from V4-1 manifest")
        start = bounds[0] if bounds else None
        end = bounds[1] if bounds else None
        sessions = int(bounds[2]) if bounds else 0
        if sessions != manifest.session_count:
            raise ValueError("V4-3A session dimensions differ from V4-1 manifest")
        if start is not None and str(start) != str(manifest.start_date):
            raise ValueError("V4-3A start date differs from V4-1 manifest")
        if end is not None and str(end) != str(manifest.end_date):
            raise ValueError("V4-3A end date differs from V4-1 manifest")

        metric_authority = _mapping(manifest.to_dict().get("metric_authority"))
        return {
            "schema_version": FACTOR_TEAR_SHEET_DIMENSIONS_SCHEMA,
            "read_only": True,
            "series_id": manifest.series_id,
            "program_id": manifest.program_id,
            "program_result_id": manifest.program_result_id,
            "factors": [
                {
                    "feature_digest": digest,
                    "feature_id": feature_ids[digest],
                    "selected": digest in set(manifest.selected_feature_digests),
                }
                for digest in manifest.candidate_feature_digests
            ],
            "folds": list(folds),
            "labels": list(labels),
            "primary_label": manifest.primary_label,
            "decay_labels": list(manifest.decay_labels),
            "quantiles": list(quantiles),
            "start_date": str(start) if start is not None else None,
            "end_date": str(end) if end is not None else None,
            "session_count": sessions,
            "metric_authority": {
                "authoritative": list(_sequence(metric_authority.get("authoritative"))),
                "derived": list(_sequence(metric_authority.get("derived"))),
            },
        }

    def frozen_summary(self, series_id: str) -> dict[str, object]:
        manifest = self.projection(series_id).manifest
        report = self.source_report(series_id)
        walk = _mapping(report.get("walk_forward_report"))
        gate = _mapping(report.get("gate_report"))
        selection = _mapping(report.get("frozen_selection"))
        gate_by_digest = {
            _text(_mapping(value).get("feature_digest")): dict(_mapping(value))
            for value in _sequence(gate.get("candidates"))
        }
        selected_by_digest = {
            _text(_mapping(value).get("feature_digest")): dict(_mapping(value))
            for value in _sequence(selection.get("components"))
        }
        items: list[dict[str, object]] = []
        for raw in _sequence(walk.get("candidates")):
            candidate = dict(_mapping(raw))
            digest = _text(candidate.get("feature_digest"))
            feature_id = _text(candidate.get("feature_id"))
            folds = list(_sequence(candidate.pop("folds", ())))
            candidate.pop("feature_digest", None)
            candidate.pop("feature_id", None)
            items.append(
                {
                    "feature_id": feature_id,
                    "feature_digest": digest,
                    "selected": digest in set(manifest.selected_feature_digests),
                    "statistics": candidate,
                    "folds": folds,
                    "gate": gate_by_digest.get(digest),
                    "selection_component": selected_by_digest.get(digest),
                }
            )
        if {str(item["feature_digest"]) for item in items} != set(
            manifest.candidate_feature_digests
        ):
            raise ValueError("V4-3A frozen A2.6 candidate denominator differs from V4-1")
        correlations_raw = walk.get("factor_value_correlations", {})
        correlations = (
            dict(cast(Mapping[str, Any], correlations_raw))
            if isinstance(correlations_raw, Mapping)
            else {}
        )
        return {
            "schema_version": FACTOR_TEAR_SHEET_SUMMARY_SCHEMA,
            "read_only": True,
            "authority": "authoritative_frozen_a2p6_summary",
            "statistics_recomputed": False,
            "series_id": manifest.series_id,
            "program_id": manifest.program_id,
            "program_result_id": manifest.program_result_id,
            "items": items,
            "factor_value_correlations": correlations,
            "selection": dict(selection),
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

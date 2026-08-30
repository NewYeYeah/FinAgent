from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import numpy as np
from scipy.stats import rankdata

from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.domain.research import DatasetRequest
from finagent.models.alpha.primitives import winsorize_cross_section

from .factor_quant import FactorQuantConfig
from .panel_feature_materializer import PanelGeneratedFeatureMaterializer


FACTOR_SERIES_ROW_SCHEMA = "finagent.factor-series-row.v1"
FACTOR_SERIES_MANIFEST_SCHEMA = "finagent.factor-series.manifest.v1"
FACTOR_SERIES_QUERY_SCHEMA = "finagent.factor-series.query.v1"

_PARQUET_COLUMNS = (
    "sequence",
    "row_id",
    "feature_id",
    "feature_digest",
    "fold_id",
    "session_date",
    "train_direction",
    "series_kind",
    "metric",
    "authority",
    "label_name",
    "quantile",
    "value",
    "sample_count",
    "window_count",
)
_NULLABLE_COLUMNS = ("quantile",)
_SHANGHAI = ZoneInfo("Asia/Shanghai")

_KIND_ORDER = {
    "coverage": 0,
    "ic": 1,
    "quantile": 2,
    "long_short": 3,
    "turnover": 4,
}
_METRIC_ORDER = {
    "eligible_count": 0,
    "valid_factor_count": 1,
    "coverage": 2,
    "pearson_ic_raw": 3,
    "rank_ic_raw": 4,
    "pearson_ic": 5,
    "rank_ic": 6,
    "rolling_pearson_ic": 7,
    "rolling_rank_ic": 8,
    "return": 9,
    "nav": 10,
    "one_way_turnover": 11,
}
_ALLOWED_METRICS = {
    "coverage": frozenset({"eligible_count", "valid_factor_count", "coverage"}),
    "ic": frozenset(
        {
            "pearson_ic_raw",
            "rank_ic_raw",
            "pearson_ic",
            "rank_ic",
            "rolling_pearson_ic",
            "rolling_rank_ic",
        }
    ),
    "quantile": frozenset({"return", "nav"}),
    "long_short": frozenset({"return", "nav"}),
    "turnover": frozenset({"one_way_turnover"}),
}
_DERIVED_METRICS = frozenset({"rolling_pearson_ic", "rolling_rank_ic", "nav"})


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


def _mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value)
    return {}


def _sequence(value: object) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return cast(Sequence[Any], value)
    return ()


def _number(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    result = float(cast(Any, value))
    if not math.isfinite(result):
        raise ValueError("factor-series numeric values must be finite")
    return result


def _integer(value: object, default: int = 0) -> int:
    if value is None:
        return default
    return int(cast(Any, value))


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _safe_sibling(name: str, field: str) -> str:
    value = name.strip()
    if not value or Path(value).name != value or value in {".", ".."}:
        raise ValueError(f"{field} must be a sibling filename")
    return value


def _duckdb():
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - dependency guidance
        raise RuntimeError("FactorSeries Parquet support requires DuckDB") from exc
    return duckdb


def _safe_correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if left.size < 2 or right.size != left.size:
        return None
    if float(np.std(left)) <= 1e-15 or float(np.std(right)) <= 1e-15:
        return None
    value = float(np.corrcoef(left, right)[0, 1])
    return value if math.isfinite(value) else None


def _icir(values: Sequence[float]) -> float:
    array = np.asarray(tuple(values), dtype=float)
    if array.size < 2:
        return 0.0
    std = float(np.std(array, ddof=1))
    return float(np.mean(array) / std) if std > 1e-15 else 0.0


def _sharpe(values: Sequence[float], annualization: float) -> float:
    array = np.asarray(tuple(values), dtype=float)
    if array.size < 2:
        return 0.0
    std = float(np.std(array, ddof=1))
    return (
        float(np.mean(array) / std * math.sqrt(annualization))
        if std > 1e-15
        else 0.0
    )


def _monotonicity(values: Sequence[float]) -> float:
    array = np.asarray(tuple(values), dtype=float)
    if array.size < 2 or not np.isfinite(array).all():
        return 0.0
    if float(np.std(array)) <= 1e-15:
        return 0.0
    value = float(np.corrcoef(np.arange(array.size, dtype=float), array)[0, 1])
    return value if math.isfinite(value) else 0.0


def _close(name: str, actual: float, expected: float) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12):
        raise ValueError(
            f"V4-1 reconciliation failed for {name}: {actual!r} != {expected!r}"
        )


@dataclass(frozen=True, slots=True)
class FactorSeriesRow:
    sequence: int
    feature_id: str
    feature_digest: str
    fold_id: str
    session_date: date
    train_direction: int
    series_kind: str
    metric: str
    authority: str
    label_name: str
    quantile: int | None
    value: float
    sample_count: int
    window_count: int = 0

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("FactorSeries sequence must be >= 0")
        for name in ("feature_id", "feature_digest", "fold_id", "series_kind", "metric"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} must be non-empty")
            object.__setattr__(self, name, value)
        if self.train_direction not in {-1, 1}:
            raise ValueError("FactorSeries train_direction must be +/-1")
        if self.authority not in {"authoritative", "derived"}:
            raise ValueError("FactorSeries authority must be authoritative or derived")
        object.__setattr__(self, "label_name", self.label_name.strip())
        object.__setattr__(self, "value", _number(self.value))
        if self.sample_count < 0 or self.window_count < 0:
            raise ValueError("FactorSeries counts must be non-negative")
        metrics = _ALLOWED_METRICS.get(self.series_kind)
        if metrics is None or self.metric not in metrics:
            raise ValueError("invalid FactorSeries series_kind/metric combination")
        if self.series_kind == "coverage":
            if self.label_name or self.quantile is not None:
                raise ValueError("coverage rows cannot carry label_name or quantile")
        elif self.series_kind == "quantile":
            if not self.label_name or self.quantile is None or self.quantile < 1:
                raise ValueError("quantile rows require label_name and positive quantile")
        elif not self.label_name or self.quantile is not None:
            raise ValueError(
                f"{self.series_kind} rows require label_name and no quantile"
            )
        if self.metric.startswith("rolling_"):
            if self.authority != "derived" or self.window_count < 2:
                raise ValueError("rolling IC rows must be derived with window_count >= 2")
        elif self.window_count != 0:
            raise ValueError("non-rolling FactorSeries rows require window_count=0")
        expected_authority = "derived" if self.metric in _DERIVED_METRICS else "authoritative"
        if self.authority != expected_authority:
            raise ValueError(
                f"FactorSeries metric {self.metric!r} requires authority={expected_authority!r}"
            )

    @property
    def row_id(self) -> str:
        return _digest(
            "factor-series-row",
            {
                "feature_id": self.feature_id,
                "feature_digest": self.feature_digest,
                "fold_id": self.fold_id,
                "session_date": self.session_date.isoformat(),
                "train_direction": self.train_direction,
                "series_kind": self.series_kind,
                "metric": self.metric,
                "authority": self.authority,
                "label_name": self.label_name,
                "quantile": self.quantile,
                "value": self.value,
                "sample_count": self.sample_count,
                "window_count": self.window_count,
            },
            40,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": FACTOR_SERIES_ROW_SCHEMA,
            "sequence": self.sequence,
            "row_id": self.row_id,
            "feature_id": self.feature_id,
            "feature_digest": self.feature_digest,
            "fold_id": self.fold_id,
            "session_date": self.session_date.isoformat(),
            "train_direction": self.train_direction,
            "series_kind": self.series_kind,
            "metric": self.metric,
            "authority": self.authority,
            "label_name": self.label_name,
            "quantile": self.quantile,
            "value": self.value,
            "sample_count": self.sample_count,
            "window_count": self.window_count,
        }


class AshareFactorSeriesMaterializer:
    """Rebuild V4-1 period evidence from frozen A2.6 PIT factor panels."""

    VERSION = "ashare-factor-series-v1"

    def __init__(
        self,
        materializer: PanelGeneratedFeatureMaterializer,
        *,
        rolling_window: int = 20,
    ) -> None:
        if rolling_window < 2:
            raise ValueError("rolling_window must be >= 2")
        self.materializer = materializer
        self.rolling_window = int(rolling_window)

    @staticmethod
    def _row(
        *,
        artifact: GeneratedFeatureArtifact,
        fold_id: str,
        session_date: date,
        direction: int,
        series_kind: str,
        metric: str,
        value: float,
        sample_count: int,
        label_name: str = "",
        quantile: int | None = None,
        authority: str = "authoritative",
        window_count: int = 0,
    ) -> FactorSeriesRow:
        return FactorSeriesRow(
            sequence=0,
            feature_id=artifact.spec.feature_id,
            feature_digest=artifact.digest,
            fold_id=fold_id,
            session_date=session_date,
            train_direction=direction,
            series_kind=series_kind,
            metric=metric,
            authority=authority,
            label_name=label_name,
            quantile=quantile,
            value=value,
            sample_count=sample_count,
            window_count=window_count,
        )

    def _append_ic_rows(
        self,
        rows: list[FactorSeriesRow],
        rolling: dict[tuple[str, str], deque[float]],
        *,
        artifact: GeneratedFeatureArtifact,
        fold_id: str,
        session_date: date,
        direction: int,
        label_name: str,
        sample_count: int,
        raw_metric: str,
        oriented_metric: str,
        raw_value: float,
    ) -> None:
        oriented = direction * raw_value
        rows.append(
            self._row(
                artifact=artifact,
                fold_id=fold_id,
                session_date=session_date,
                direction=direction,
                series_kind="ic",
                metric=raw_metric,
                value=raw_value,
                sample_count=sample_count,
                label_name=label_name,
            )
        )
        rows.append(
            self._row(
                artifact=artifact,
                fold_id=fold_id,
                session_date=session_date,
                direction=direction,
                series_kind="ic",
                metric=oriented_metric,
                value=oriented,
                sample_count=sample_count,
                label_name=label_name,
            )
        )
        queue = rolling[(label_name, oriented_metric)]
        queue.append(oriented)
        if len(queue) == self.rolling_window:
            rows.append(
                self._row(
                    artifact=artifact,
                    fold_id=fold_id,
                    session_date=session_date,
                    direction=direction,
                    series_kind="ic",
                    metric=f"rolling_{oriented_metric}",
                    value=float(np.mean(tuple(queue))),
                    sample_count=sample_count,
                    label_name=label_name,
                    authority="derived",
                    window_count=self.rolling_window,
                )
            )

    def materialize_fold(
        self,
        *,
        artifact: GeneratedFeatureArtifact,
        request: DatasetRequest,
        split_name: str,
        fold_id: str,
        train_direction: int,
        config: FactorQuantConfig,
    ) -> tuple[FactorSeriesRow, ...]:
        if config.split_name != split_name:
            raise ValueError("FactorSeries config.split_name must match split_name")
        if train_direction not in {-1, 1}:
            raise ValueError("FactorSeries requires frozen train_direction +/-1")
        dataset = self.materializer.materialize(artifact, request)
        panel = dataset.get_split(split_name)
        factor = np.asarray(panel.feature_values[:, :, 0], dtype=float)
        eligibility = np.asarray(panel.eligibility_mask, dtype=bool)
        primary_labels = np.asarray(panel.label_panel(config.primary_label), dtype=float)
        rows: list[FactorSeriesRow] = []
        rolling: dict[tuple[str, str], deque[float]] = {
            (label, metric): deque(maxlen=self.rolling_window)
            for label in config.labels
            for metric in ("pearson_ic", "rank_ic")
        }
        quantile_nav = [1.0 for _ in range(config.quantiles)]
        long_short_nav = 1.0
        previous_weights = np.zeros(panel.n_assets, dtype=float)

        for index, timestamp in enumerate(panel.timestamps):
            session_date = timestamp.astimezone(_SHANGHAI).date()
            formation = eligibility[index] & np.isfinite(factor[index])
            eligible_count = int(eligibility[index].sum())
            valid_count = int(formation.sum())
            coverage = valid_count / eligible_count if eligible_count else 0.0
            for metric, value in (
                ("eligible_count", float(eligible_count)),
                ("valid_factor_count", float(valid_count)),
                ("coverage", float(coverage)),
            ):
                rows.append(
                    self._row(
                        artifact=artifact,
                        fold_id=fold_id,
                        session_date=session_date,
                        direction=train_direction,
                        series_kind="coverage",
                        metric=metric,
                        value=value,
                        sample_count=eligible_count,
                    )
                )

            for label_name in config.labels:
                labels = np.asarray(panel.label_panel(label_name)[index], dtype=float)
                realized = formation & np.isfinite(labels)
                sample_count = int(realized.sum())
                if sample_count < config.min_cross_section:
                    continue
                raw_factor = factor[index][realized]
                target = labels[realized]
                winsorized = np.asarray(
                    winsorize_cross_section(
                        raw_factor,
                        lower_quantile=config.winsor_lower_quantile,
                        upper_quantile=config.winsor_upper_quantile,
                    ),
                    dtype=float,
                )
                pearson = _safe_correlation(winsorized, target)
                rank_ic = _safe_correlation(
                    rankdata(raw_factor, method="average"),
                    rankdata(target, method="average"),
                )
                if pearson is not None:
                    self._append_ic_rows(
                        rows,
                        rolling,
                        artifact=artifact,
                        fold_id=fold_id,
                        session_date=session_date,
                        direction=train_direction,
                        label_name=label_name,
                        sample_count=sample_count,
                        raw_metric="pearson_ic_raw",
                        oriented_metric="pearson_ic",
                        raw_value=pearson,
                    )
                if rank_ic is not None:
                    self._append_ic_rows(
                        rows,
                        rolling,
                        artifact=artifact,
                        fold_id=fold_id,
                        session_date=session_date,
                        direction=train_direction,
                        label_name=label_name,
                        sample_count=sample_count,
                        raw_metric="rank_ic_raw",
                        oriented_metric="rank_ic",
                        raw_value=rank_ic,
                    )

            indices = np.flatnonzero(formation)
            if len(indices) < config.min_cross_section:
                continue
            ordered = indices[np.argsort(factor[index][indices], kind="mergesort")]
            raw_buckets = tuple(np.array_split(ordered, config.quantiles))
            if any(len(bucket) == 0 for bucket in raw_buckets):
                continue
            if not all(
                np.all(np.isfinite(primary_labels[index][bucket]))
                for bucket in raw_buckets
            ):
                continue
            oriented_buckets = (
                raw_buckets
                if train_direction == 1
                else tuple(reversed(raw_buckets))
            )
            bucket_returns = [
                float(np.mean(primary_labels[index][bucket]))
                for bucket in oriented_buckets
            ]
            for quantile_index, (bucket, period_return) in enumerate(
                zip(oriented_buckets, bucket_returns, strict=True),
                1,
            ):
                quantile_nav[quantile_index - 1] *= 1.0 + period_return
                if not math.isfinite(quantile_nav[quantile_index - 1]):
                    raise ValueError("FactorSeries quantile NAV became non-finite")
                rows.append(
                    self._row(
                        artifact=artifact,
                        fold_id=fold_id,
                        session_date=session_date,
                        direction=train_direction,
                        series_kind="quantile",
                        metric="return",
                        value=period_return,
                        sample_count=len(bucket),
                        label_name=config.primary_label,
                        quantile=quantile_index,
                    )
                )
                rows.append(
                    self._row(
                        artifact=artifact,
                        fold_id=fold_id,
                        session_date=session_date,
                        direction=train_direction,
                        series_kind="quantile",
                        metric="nav",
                        value=quantile_nav[quantile_index - 1],
                        sample_count=len(bucket),
                        label_name=config.primary_label,
                        quantile=quantile_index,
                        authority="derived",
                    )
                )

            spread = bucket_returns[-1] - bucket_returns[0]
            long_short_nav *= 1.0 + spread
            if not math.isfinite(long_short_nav):
                raise ValueError("FactorSeries long-short NAV became non-finite")
            active_count = len(oriented_buckets[0]) + len(oriented_buckets[-1])
            rows.append(
                self._row(
                    artifact=artifact,
                    fold_id=fold_id,
                    session_date=session_date,
                    direction=train_direction,
                    series_kind="long_short",
                    metric="return",
                    value=spread,
                    sample_count=active_count,
                    label_name=config.primary_label,
                )
            )
            rows.append(
                self._row(
                    artifact=artifact,
                    fold_id=fold_id,
                    session_date=session_date,
                    direction=train_direction,
                    series_kind="long_short",
                    metric="nav",
                    value=long_short_nav,
                    sample_count=active_count,
                    label_name=config.primary_label,
                    authority="derived",
                )
            )
            weights = np.zeros_like(previous_weights)
            weights[oriented_buckets[-1]] = 0.5 / len(oriented_buckets[-1])
            weights[oriented_buckets[0]] = -0.5 / len(oriented_buckets[0])
            turnover = float(0.5 * np.abs(weights - previous_weights).sum())
            previous_weights = weights
            rows.append(
                self._row(
                    artifact=artifact,
                    fold_id=fold_id,
                    session_date=session_date,
                    direction=train_direction,
                    series_kind="turnover",
                    metric="one_way_turnover",
                    value=turnover,
                    sample_count=active_count,
                    label_name=config.primary_label,
                )
            )
        return tuple(rows)


def _row_values(
    rows: Sequence[FactorSeriesRow],
    *,
    series_kind: str,
    metric: str,
    label_name: str = "",
    quantile: int | None = None,
) -> tuple[float, ...]:
    return tuple(
        row.value
        for row in rows
        if row.series_kind == series_kind
        and row.metric == metric
        and (not label_name or row.label_name == label_name)
        and row.quantile == quantile
    )


def reconcile_factor_series(
    rows: Sequence[FactorSeriesRow],
    source_report: Mapping[str, object],
) -> dict[str, int]:
    """Fail closed unless V4-1 period series reproduce frozen A2.6 diagnostics."""

    if source_report.get("schema_version") != "finagent.ashare-robust-research-program.v1":
        raise ValueError("FactorSeries reconciliation requires an A2.6 report")
    program = _mapping(source_report.get("program_spec"))
    primary_label = _text(program.get("primary_label"))
    decay_labels = tuple(str(value) for value in _sequence(program.get("decay_labels")))
    quant_config = _mapping(program.get("factor_quant_config"))
    annualization = _number(quant_config.get("annualization"), 252.0)
    report = _mapping(source_report.get("walk_forward_report"))
    candidate_reports = {
        _text(_mapping(value).get("feature_digest")): _mapping(value)
        for value in _sequence(report.get("candidates"))
    }
    by_feature_fold: dict[tuple[str, str], list[FactorSeriesRow]] = defaultdict(list)
    for row in rows:
        by_feature_fold[(row.feature_digest, row.fold_id)].append(row)
    fold_checks = 0
    candidate_checks = 0

    for feature_digest, candidate in candidate_reports.items():
        fold_diagnostics: list[dict[str, float]] = []
        combined_rank: list[float] = []
        directions: list[int] = []
        horizon_signs: list[float] = []
        for raw_fold in _sequence(candidate.get("folds")):
            fold = _mapping(raw_fold)
            fold_id = _text(fold.get("fold_id"))
            current = tuple(by_feature_fold[(feature_digest, fold_id)])
            if not current:
                raise ValueError(
                    f"V4-1 has no rows for factor {feature_digest!r} fold {fold_id!r}"
                )
            direction = _integer(fold.get("train_direction"))
            if {row.train_direction for row in current} != {direction}:
                raise ValueError("V4-1 row direction differs from frozen A2.6 fold direction")
            directions.append(direction)
            raw_rank = _row_values(
                current,
                series_kind="ic",
                metric="rank_ic_raw",
                label_name=primary_label,
            )
            raw_pearson = _row_values(
                current,
                series_kind="ic",
                metric="pearson_ic_raw",
                label_name=primary_label,
            )
            oriented_rank = _row_values(
                current,
                series_kind="ic",
                metric="rank_ic",
                label_name=primary_label,
            )
            if not raw_rank or not oriented_rank:
                raise ValueError("V4-1 primary RankIC series is empty")
            if min(len(raw_rank), len(raw_pearson)) != _integer(fold.get("periods")):
                raise ValueError("V4-1 IC period count differs from A2.6")
            _close(
                f"{feature_digest}:{fold_id}:test_raw_rank_ic",
                float(np.mean(raw_rank)),
                _number(fold.get("test_raw_rank_ic")),
            )
            _close(
                f"{feature_digest}:{fold_id}:test_raw_rank_icir",
                _icir(raw_rank),
                _number(fold.get("test_raw_rank_icir")),
            )
            _close(
                f"{feature_digest}:{fold_id}:test_rank_ic",
                float(np.mean(oriented_rank)),
                _number(fold.get("test_rank_ic")),
            )
            oriented_icir = _icir(oriented_rank)
            _close(
                f"{feature_digest}:{fold_id}:test_rank_icir",
                oriented_icir,
                _number(fold.get("test_rank_icir")),
            )
            long_short = _row_values(
                current,
                series_kind="long_short",
                metric="return",
                label_name=primary_label,
            )
            if not long_short:
                raise ValueError("V4-1 long-short return series is empty")
            long_short_sharpe = _sharpe(long_short, annualization)
            _close(
                f"{feature_digest}:{fold_id}:test_long_short_sharpe",
                long_short_sharpe,
                _number(fold.get("test_long_short_sharpe")),
            )
            _close(
                f"{feature_digest}:{fold_id}:test_raw_long_short_sharpe",
                direction * long_short_sharpe,
                _number(fold.get("test_raw_long_short_sharpe")),
            )
            turnover = _row_values(
                current,
                series_kind="turnover",
                metric="one_way_turnover",
                label_name=primary_label,
            )
            if not turnover:
                raise ValueError("V4-1 turnover series is empty")
            mean_turnover = float(np.mean(turnover))
            _close(
                f"{feature_digest}:{fold_id}:mean_one_way_turnover",
                mean_turnover,
                _number(fold.get("mean_one_way_turnover")),
            )
            eligible = _row_values(
                current,
                series_kind="coverage",
                metric="eligible_count",
            )
            valid = _row_values(
                current,
                series_kind="coverage",
                metric="valid_factor_count",
            )
            total_eligible = math.fsum(eligible)
            coverage = math.fsum(valid) / total_eligible if total_eligible else 0.0
            _close(
                f"{feature_digest}:{fold_id}:coverage",
                coverage,
                _number(fold.get("coverage")),
            )
            quantiles = sorted(
                {
                    row.quantile
                    for row in current
                    if row.series_kind == "quantile"
                    and row.metric == "return"
                    and row.quantile is not None
                }
            )
            if not quantiles:
                raise ValueError("V4-1 quantile return series is empty")
            quantile_means = [
                float(
                    np.mean(
                        _row_values(
                            current,
                            series_kind="quantile",
                            metric="return",
                            label_name=primary_label,
                            quantile=value,
                        )
                    )
                )
                for value in quantiles
            ]
            monotonicity = _monotonicity(quantile_means)
            _close(
                f"{feature_digest}:{fold_id}:quantile_monotonicity",
                monotonicity,
                _number(fold.get("quantile_monotonicity")),
            )
            primary_mean = float(np.mean(oriented_rank))
            for label_name in decay_labels:
                horizon = _row_values(
                    current,
                    series_kind="ic",
                    metric="rank_ic",
                    label_name=label_name,
                )
                if not horizon:
                    raise ValueError(
                        f"V4-1 decay RankIC series is empty for {label_name!r}"
                    )
                horizon_signs.append(
                    1.0 if float(np.mean(horizon)) * primary_mean >= 0 else 0.0
                )
            combined_rank.extend(oriented_rank)
            fold_diagnostics.append(
                {
                    "rank_icir": oriented_icir,
                    "long_short_sharpe": long_short_sharpe,
                    "coverage": coverage,
                    "monotonicity": monotonicity,
                    "turnover": mean_turnover,
                }
            )
            fold_checks += 1

        rank_icirs = np.asarray(
            [value["rank_icir"] for value in fold_diagnostics], dtype=float
        )
        sharpes = np.asarray(
            [value["long_short_sharpe"] for value in fold_diagnostics], dtype=float
        )
        coverages = np.asarray(
            [value["coverage"] for value in fold_diagnostics], dtype=float
        )
        _close(
            f"{feature_digest}:pooled_rank_ic",
            float(np.mean(combined_rank)),
            _number(candidate.get("pooled_rank_ic")),
        )
        _close(
            f"{feature_digest}:pooled_rank_icir",
            _icir(combined_rank),
            _number(candidate.get("pooled_rank_icir")),
        )
        _close(
            f"{feature_digest}:mean_fold_rank_icir",
            float(np.mean(rank_icirs)),
            _number(candidate.get("mean_fold_rank_icir")),
        )
        _close(
            f"{feature_digest}:worst_fold_rank_icir",
            float(np.min(rank_icirs)),
            _number(candidate.get("worst_fold_rank_icir")),
        )
        _close(
            f"{feature_digest}:positive_fold_ratio",
            float(np.mean(rank_icirs > 0)),
            _number(candidate.get("positive_fold_ratio")),
        )
        _close(
            f"{feature_digest}:mean_fold_long_short_sharpe",
            float(np.mean(sharpes)),
            _number(candidate.get("mean_fold_long_short_sharpe")),
        )
        _close(
            f"{feature_digest}:worst_fold_long_short_sharpe",
            float(np.min(sharpes)),
            _number(candidate.get("worst_fold_long_short_sharpe")),
        )
        _close(
            f"{feature_digest}:coverage_mean",
            float(np.mean(coverages)),
            _number(candidate.get("coverage_mean")),
        )
        _close(
            f"{feature_digest}:coverage_min",
            float(np.min(coverages)),
            _number(candidate.get("coverage_min")),
        )
        _close(
            f"{feature_digest}:quantile_monotonicity",
            float(np.mean([value["monotonicity"] for value in fold_diagnostics])),
            _number(candidate.get("quantile_monotonicity")),
        )
        _close(
            f"{feature_digest}:mean_one_way_turnover",
            float(np.mean([value["turnover"] for value in fold_diagnostics])),
            _number(candidate.get("mean_one_way_turnover")),
        )
        direction_total = sum(directions)
        dominant_direction = 1 if direction_total >= 0 else -1
        if dominant_direction != _integer(candidate.get("dominant_direction")):
            raise ValueError("V4-1 dominant direction differs from A2.6")
        _close(
            f"{feature_digest}:direction_consistency",
            max(directions.count(1), directions.count(-1)) / len(directions),
            _number(candidate.get("direction_consistency")),
        )
        _close(
            f"{feature_digest}:horizon_sign_consistency",
            float(np.mean(horizon_signs)) if horizon_signs else 1.0,
            _number(candidate.get("horizon_sign_consistency")),
        )
        candidate_checks += 1
    return {"fold_checks": fold_checks, "candidate_checks": candidate_checks}


def _row_sort_key(row: FactorSeriesRow) -> tuple[object, ...]:
    return (
        row.feature_digest,
        row.session_date,
        row.fold_id,
        _KIND_ORDER[row.series_kind],
        row.label_name,
        row.quantile if row.quantile is not None else -1,
        _METRIC_ORDER[row.metric],
        row.row_id,
    )


def order_factor_series_rows(rows: Sequence[FactorSeriesRow]) -> tuple[FactorSeriesRow, ...]:
    ordered = sorted(rows, key=_row_sort_key)
    output = tuple(replace(row, sequence=index) for index, row in enumerate(ordered))
    row_ids = [row.row_id for row in output]
    if len(row_ids) != len(set(row_ids)):
        raise ValueError("FactorSeries contains duplicate semantic row identities")
    return output


def _quant_config_payload(
    program: Mapping[str, Any], rolling_window: int
) -> dict[str, Any]:
    config = _mapping(program.get("factor_quant_config"))
    return {
        "primary_label": _text(program.get("primary_label")),
        "decay_labels": [str(value) for value in _sequence(program.get("decay_labels"))],
        "quantiles": _integer(config.get("quantiles")),
        "min_cross_section": _integer(config.get("min_cross_section")),
        "min_periods": _integer(config.get("min_periods")),
        "annualization": _number(config.get("annualization"), 252.0),
        "winsor_lower_quantile": _number(config.get("winsor_lower_quantile"), 0.01),
        "winsor_upper_quantile": _number(config.get("winsor_upper_quantile"), 0.99),
        "rolling_window": int(rolling_window),
    }


def _series_identity_payload(
    *,
    program_result_id: str,
    program_spec_id: str,
    walk_forward_report_id: str,
    gate_report_id: str,
    selection_id: str,
    plan_id: str,
    data_version: str,
    candidate_selection_id: str,
    universe_policy_version: str,
    candidate_feature_digests: Sequence[str],
    selected_feature_digests: Sequence[str],
    quant_config_digest: str,
    rows_digest: str,
) -> dict[str, object]:
    return {
        "program_result_id": program_result_id,
        "program_spec_id": program_spec_id,
        "walk_forward_report_id": walk_forward_report_id,
        "gate_report_id": gate_report_id,
        "selection_id": selection_id,
        "plan_id": plan_id,
        "data_version": data_version,
        "candidate_selection_id": candidate_selection_id,
        "universe_policy_version": universe_policy_version,
        "candidate_feature_digests": list(candidate_feature_digests),
        "selected_feature_digests": list(selected_feature_digests),
        "quant_config_digest": quant_config_digest,
        "rows_digest": rows_digest,
    }


@dataclass(frozen=True, slots=True)
class FactorSeriesManifest:
    series_id: str
    program_result_id: str
    program_id: str
    program_spec_id: str
    walk_forward_report_id: str
    gate_report_id: str
    selection_id: str
    plan_id: str
    data_version: str
    candidate_selection_id: str
    universe_policy_version: str
    candidate_feature_digests: tuple[str, ...]
    selected_feature_digests: tuple[str, ...]
    primary_label: str
    decay_labels: tuple[str, ...]
    quantiles: int
    min_cross_section: int
    min_periods: int
    annualization: float
    winsor_lower_quantile: float
    winsor_upper_quantile: float
    rolling_window: int
    quant_config_digest: str
    rows_digest: str
    source_report_content_digest: str
    source_report_file: str
    source_report_sha256: str
    data_file: str
    data_sha256: str
    row_count: int
    factor_count: int
    fold_count: int
    session_count: int
    start_date: str | None
    end_date: str | None
    columns: tuple[str, ...] = _PARQUET_COLUMNS
    nullable_columns: tuple[str, ...] = _NULLABLE_COLUMNS
    schema_version: str = FACTOR_SERIES_MANIFEST_SCHEMA
    authority: str = "authoritative"

    def __post_init__(self) -> None:
        required = (
            "series_id",
            "program_result_id",
            "program_id",
            "program_spec_id",
            "walk_forward_report_id",
            "gate_report_id",
            "selection_id",
            "plan_id",
            "data_version",
            "candidate_selection_id",
            "universe_policy_version",
            "quant_config_digest",
            "rows_digest",
            "source_report_content_digest",
            "source_report_sha256",
            "data_sha256",
        )
        for name in required:
            if not str(getattr(self, name)).strip():
                raise ValueError(f"FactorSeries manifest {name} must be non-empty")
        primary = self.primary_label.strip()
        if not primary:
            raise ValueError("FactorSeries manifest primary_label must be non-empty")
        object.__setattr__(self, "primary_label", primary)
        decay = tuple(value.strip() for value in self.decay_labels)
        if any(not value for value in decay) or len(set(decay)) != len(decay):
            raise ValueError("FactorSeries decay labels must be unique and non-empty")
        if primary in decay:
            raise ValueError("FactorSeries decay labels must exclude primary_label")
        object.__setattr__(self, "decay_labels", decay)
        object.__setattr__(
            self,
            "source_report_file",
            _safe_sibling(self.source_report_file, "source_report_file"),
        )
        object.__setattr__(self, "data_file", _safe_sibling(self.data_file, "data_file"))
        if self.authority != "authoritative":
            raise ValueError("FactorSeries package authority must remain authoritative")
        if not self.candidate_feature_digests:
            raise ValueError("FactorSeries requires a non-empty candidate denominator")
        if len(set(self.candidate_feature_digests)) != len(self.candidate_feature_digests):
            raise ValueError("FactorSeries candidate factor digests must be unique")
        if any(not value.strip() for value in self.candidate_feature_digests):
            raise ValueError("FactorSeries candidate factor digests must be non-empty")
        if len(set(self.selected_feature_digests)) != len(self.selected_feature_digests):
            raise ValueError("FactorSeries selected factor digests must be unique")
        if not set(self.selected_feature_digests).issubset(self.candidate_feature_digests):
            raise ValueError("selected FactorSeries factors must belong to denominator")
        if self.quantiles < 2 or self.min_cross_section < self.quantiles:
            raise ValueError("invalid FactorSeries quantile configuration")
        if self.min_periods < 2 or self.rolling_window < 2:
            raise ValueError("invalid FactorSeries period/window configuration")
        if not math.isfinite(self.annualization) or self.annualization <= 0:
            raise ValueError("FactorSeries annualization must be positive and finite")
        if not (
            0.0
            <= self.winsor_lower_quantile
            < self.winsor_upper_quantile
            <= 1.0
        ):
            raise ValueError("invalid FactorSeries winsorization quantiles")
        if self.row_count < 1 or self.factor_count < 1 or self.fold_count < 1:
            raise ValueError("FactorSeries manifest requires rows, factors and folds")
        if self.factor_count != len(self.candidate_feature_digests):
            raise ValueError("FactorSeries factor_count differs from candidate denominator")
        if self.session_count < 1:
            raise ValueError("FactorSeries manifest requires sessions")
        if self.start_date is None or self.end_date is None:
            raise ValueError("FactorSeries manifest requires a bounded date range")
        if date.fromisoformat(self.end_date) < date.fromisoformat(self.start_date):
            raise ValueError("FactorSeries manifest end_date precedes start_date")
        if self.columns != _PARQUET_COLUMNS or self.nullable_columns != _NULLABLE_COLUMNS:
            raise ValueError("FactorSeries manifest column contract differs from V4-1")
        expected_id = _digest(
            "factor-series",
            _series_identity_payload(
                program_result_id=self.program_result_id,
                program_spec_id=self.program_spec_id,
                walk_forward_report_id=self.walk_forward_report_id,
                gate_report_id=self.gate_report_id,
                selection_id=self.selection_id,
                plan_id=self.plan_id,
                data_version=self.data_version,
                candidate_selection_id=self.candidate_selection_id,
                universe_policy_version=self.universe_policy_version,
                candidate_feature_digests=self.candidate_feature_digests,
                selected_feature_digests=self.selected_feature_digests,
                quant_config_digest=self.quant_config_digest,
                rows_digest=self.rows_digest,
            ),
            40,
        )
        if self.series_id != expected_id:
            raise ValueError("FactorSeries series_id differs from manifest content")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "authority": self.authority,
            "series_id": self.series_id,
            "program_result_id": self.program_result_id,
            "program_id": self.program_id,
            "program_spec_id": self.program_spec_id,
            "walk_forward_report_id": self.walk_forward_report_id,
            "gate_report_id": self.gate_report_id,
            "selection_id": self.selection_id,
            "plan_id": self.plan_id,
            "data_version": self.data_version,
            "candidate_selection_id": self.candidate_selection_id,
            "universe_policy_version": self.universe_policy_version,
            "candidate_feature_digests": list(self.candidate_feature_digests),
            "selected_feature_digests": list(self.selected_feature_digests),
            "primary_label": self.primary_label,
            "decay_labels": list(self.decay_labels),
            "quantiles": self.quantiles,
            "min_cross_section": self.min_cross_section,
            "min_periods": self.min_periods,
            "annualization": self.annualization,
            "winsor_lower_quantile": self.winsor_lower_quantile,
            "winsor_upper_quantile": self.winsor_upper_quantile,
            "rolling_window": self.rolling_window,
            "quant_config_digest": self.quant_config_digest,
            "rows_digest": self.rows_digest,
            "source_report_content_digest": self.source_report_content_digest,
            "source_report_file": self.source_report_file,
            "source_report_sha256": self.source_report_sha256,
            "data_file": self.data_file,
            "data_sha256": self.data_sha256,
            "row_count": self.row_count,
            "factor_count": self.factor_count,
            "fold_count": self.fold_count,
            "session_count": self.session_count,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "columns": list(self.columns),
            "nullable_columns": list(self.nullable_columns),
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
            "orientation": (
                "test-period IC and quantile portfolios use the frozen train_direction "
                "from each A2.6 walk-forward fold; test data never selects direction"
            ),
            "rolling_definition": (
                "rolling IC is the arithmetic mean of the latest rolling_window valid "
                "oriented IC observations for the same factor/fold/horizon"
            ),
            "scope": (
                "internal A2.6 walk-forward factor-series evidence only; reserve remains "
                "untouched and no execution, promotion, PAPER, realtime or live authority"
            ),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> FactorSeriesManifest:
        if raw.get("schema_version") != FACTOR_SERIES_MANIFEST_SCHEMA:
            raise ValueError("unsupported FactorSeries manifest schema")
        return cls(
            series_id=_text(raw.get("series_id")),
            program_result_id=_text(raw.get("program_result_id")),
            program_id=_text(raw.get("program_id")),
            program_spec_id=_text(raw.get("program_spec_id")),
            walk_forward_report_id=_text(raw.get("walk_forward_report_id")),
            gate_report_id=_text(raw.get("gate_report_id")),
            selection_id=_text(raw.get("selection_id")),
            plan_id=_text(raw.get("plan_id")),
            data_version=_text(raw.get("data_version")),
            candidate_selection_id=_text(raw.get("candidate_selection_id")),
            universe_policy_version=_text(raw.get("universe_policy_version")),
            candidate_feature_digests=tuple(
                str(value) for value in _sequence(raw.get("candidate_feature_digests"))
            ),
            selected_feature_digests=tuple(
                str(value) for value in _sequence(raw.get("selected_feature_digests"))
            ),
            primary_label=_text(raw.get("primary_label")),
            decay_labels=tuple(str(value) for value in _sequence(raw.get("decay_labels"))),
            quantiles=_integer(raw.get("quantiles")),
            min_cross_section=_integer(raw.get("min_cross_section")),
            min_periods=_integer(raw.get("min_periods")),
            annualization=_number(raw.get("annualization"), 252.0),
            winsor_lower_quantile=_number(raw.get("winsor_lower_quantile"), 0.01),
            winsor_upper_quantile=_number(raw.get("winsor_upper_quantile"), 0.99),
            rolling_window=_integer(raw.get("rolling_window")),
            quant_config_digest=_text(raw.get("quant_config_digest")),
            rows_digest=_text(raw.get("rows_digest")),
            source_report_content_digest=_text(raw.get("source_report_content_digest")),
            source_report_file=_text(raw.get("source_report_file")),
            source_report_sha256=_text(raw.get("source_report_sha256")),
            data_file=_text(raw.get("data_file")),
            data_sha256=_text(raw.get("data_sha256")),
            row_count=_integer(raw.get("row_count")),
            factor_count=_integer(raw.get("factor_count")),
            fold_count=_integer(raw.get("fold_count")),
            session_count=_integer(raw.get("session_count")),
            start_date=_text(raw.get("start_date")) or None,
            end_date=_text(raw.get("end_date")) or None,
            columns=tuple(str(value) for value in _sequence(raw.get("columns"))),
            nullable_columns=tuple(
                str(value) for value in _sequence(raw.get("nullable_columns"))
            ),
            authority=_text(raw.get("authority")),
        )

    @classmethod
    def read_json(cls, path: str | Path) -> FactorSeriesManifest:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("FactorSeries manifest root must be an object")
        return cls.from_dict(cast(Mapping[str, object], value))


def _create_parquet(path: Path, rows: Sequence[FactorSeriesRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".parquet", dir=str(path.parent)
    )
    os.close(fd)
    temp = Path(temp_name)
    temp.unlink(missing_ok=True)
    duckdb = _duckdb()
    connection = duckdb.connect()
    try:
        connection.execute(
            """
            CREATE TABLE factor_series (
                sequence BIGINT NOT NULL,
                row_id VARCHAR NOT NULL,
                feature_id VARCHAR NOT NULL,
                feature_digest VARCHAR NOT NULL,
                fold_id VARCHAR NOT NULL,
                session_date DATE NOT NULL,
                train_direction INTEGER NOT NULL,
                series_kind VARCHAR NOT NULL,
                metric VARCHAR NOT NULL,
                authority VARCHAR NOT NULL,
                label_name VARCHAR NOT NULL,
                quantile INTEGER,
                value DOUBLE NOT NULL,
                sample_count BIGINT NOT NULL,
                window_count BIGINT NOT NULL
            )
            """
        )
        values = [
            (
                row.sequence,
                row.row_id,
                row.feature_id,
                row.feature_digest,
                row.fold_id,
                row.session_date,
                row.train_direction,
                row.series_kind,
                row.metric,
                row.authority,
                row.label_name,
                row.quantile,
                row.value,
                row.sample_count,
                row.window_count,
            )
            for row in rows
        ]
        if values:
            placeholders = ",".join("?" for _ in _PARQUET_COLUMNS)
            connection.executemany(
                f"INSERT INTO factor_series VALUES ({placeholders})", values
            )
        target = str(temp).replace("'", "''")
        connection.execute(
            f"COPY factor_series TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    finally:
        connection.close()
    temp.replace(path)


def write_factor_series(
    *,
    source_report: Mapping[str, object],
    rows: Sequence[FactorSeriesRow],
    source_report_path: str | Path,
    manifest_path: str | Path,
    data_path: str | Path,
    rolling_window: int,
) -> FactorSeriesManifest:
    source = Path(source_report_path).resolve()
    manifest_target = Path(manifest_path).resolve()
    data_target = Path(data_path).resolve()
    if len({source.parent, manifest_target.parent, data_target.parent}) != 1:
        raise ValueError("V4-1 source report, manifest and Parquet must be sibling files")
    if not source.is_file():
        raise FileNotFoundError(source)
    if source_report.get("schema_version") != "finagent.ashare-robust-research-program.v1":
        raise ValueError("FactorSeries requires an A2.6 robust research report")
    physical = json.loads(source.read_text(encoding="utf-8"))
    if _canonical_json(physical) != _canonical_json(source_report):
        raise ValueError("provided A2.6 report mapping differs from source report file")
    if _mapping(source_report.get("system_acceptance")).get("passed") is not True:
        raise ValueError("V4-1 requires a successful A2.6 system run")
    if _text(source_report.get("program_status")) != "frozen":
        raise ValueError("V4-1 requires a frozen A2.6 ResearchProgram")
    if _text(_mapping(source_report.get("reserve")).get("status")) != "untouched":
        raise ValueError("V4-1 refuses an A2.6 report whose reserve is not untouched")

    reconciliation = reconcile_factor_series(rows, source_report)
    ordered = order_factor_series_rows(rows)
    rows_digest = _digest(
        "factor-series-rows", [row.to_dict() for row in ordered], 64
    )
    program = _mapping(source_report.get("program_spec"))
    walk = _mapping(source_report.get("walk_forward_report"))
    gate = _mapping(source_report.get("gate_report"))
    selection = _mapping(source_report.get("frozen_selection"))
    plan = _mapping(program.get("walk_forward_plan"))
    denominator = tuple(
        _text(_mapping(value).get("feature_digest"))
        for value in _sequence(source_report.get("candidate_denominator"))
    )
    if not denominator or any(not value for value in denominator):
        raise ValueError("A2.6 candidate denominator is missing factor digests")
    selected = tuple(
        _text(_mapping(value).get("feature_digest"))
        for value in _sequence(selection.get("components"))
    )
    quant_payload = _quant_config_payload(program, rolling_window)
    quant_digest = _digest("factor-series-quant-config", quant_payload, 40)
    identity = _series_identity_payload(
        program_result_id=_text(source_report.get("program_result_id")),
        program_spec_id=_text(program.get("spec_id")),
        walk_forward_report_id=_text(walk.get("report_id")),
        gate_report_id=_text(gate.get("gate_report_id")),
        selection_id=_text(selection.get("selection_id")),
        plan_id=_text(plan.get("plan_id")),
        data_version=_text(source_report.get("data_version")),
        candidate_selection_id=_text(program.get("candidate_selection_id")),
        universe_policy_version=_text(program.get("universe_policy_version")),
        candidate_feature_digests=denominator,
        selected_feature_digests=selected,
        quant_config_digest=quant_digest,
        rows_digest=rows_digest,
    )
    series_id = _digest("factor-series", identity, 40)
    _create_parquet(data_target, ordered)
    dates = [row.session_date for row in ordered]
    decay_labels = tuple(str(value) for value in quant_payload["decay_labels"])
    manifest = FactorSeriesManifest(
        series_id=series_id,
        program_result_id=_text(source_report.get("program_result_id")),
        program_id=_text(program.get("program_id")),
        program_spec_id=_text(program.get("spec_id")),
        walk_forward_report_id=_text(walk.get("report_id")),
        gate_report_id=_text(gate.get("gate_report_id")),
        selection_id=_text(selection.get("selection_id")),
        plan_id=_text(plan.get("plan_id")),
        data_version=_text(source_report.get("data_version")),
        candidate_selection_id=_text(program.get("candidate_selection_id")),
        universe_policy_version=_text(program.get("universe_policy_version")),
        candidate_feature_digests=denominator,
        selected_feature_digests=selected,
        primary_label=str(quant_payload["primary_label"]),
        decay_labels=decay_labels,
        quantiles=int(quant_payload["quantiles"]),
        min_cross_section=int(quant_payload["min_cross_section"]),
        min_periods=int(quant_payload["min_periods"]),
        annualization=float(quant_payload["annualization"]),
        winsor_lower_quantile=float(quant_payload["winsor_lower_quantile"]),
        winsor_upper_quantile=float(quant_payload["winsor_upper_quantile"]),
        rolling_window=rolling_window,
        quant_config_digest=quant_digest,
        rows_digest=rows_digest,
        source_report_content_digest=_digest(
            "a2p6-report-content", source_report, 64
        ),
        source_report_file=source.name,
        source_report_sha256=_sha256(source),
        data_file=data_target.name,
        data_sha256=_sha256(data_target),
        row_count=len(ordered),
        factor_count=len(denominator),
        fold_count=len(_sequence(plan.get("folds"))),
        session_count=len({row.session_date for row in ordered}),
        start_date=min(dates).isoformat() if dates else None,
        end_date=max(dates).isoformat() if dates else None,
    )
    if reconciliation["candidate_checks"] != len(denominator):
        raise ValueError("V4-1 did not reconcile the complete A2.6 candidate denominator")
    manifest_target.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return manifest


class FactorSeriesProjection:
    """Verified bounded read projection over immutable V4-1 Parquet evidence."""

    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = Path(manifest_path).resolve()
        self.manifest = FactorSeriesManifest.read_json(self.manifest_path)
        root = self.manifest_path.parent
        self.report_path = root / self.manifest.source_report_file
        self.data_path = root / self.manifest.data_file
        for path in (self.report_path, self.data_path):
            if path.parent.resolve() != root:
                raise ValueError("V4-1 manifest sibling escaped its evidence root")
            if not path.is_file():
                raise FileNotFoundError(path)
        if _sha256(self.report_path) != self.manifest.source_report_sha256:
            raise ValueError("V4-1 source A2.6 report SHA-256 mismatch")
        if _sha256(self.data_path) != self.manifest.data_sha256:
            raise ValueError("V4-1 Parquet SHA-256 mismatch")
        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        if not isinstance(report, Mapping):
            raise ValueError("V4-1 source report root must be an object")
        report_map = cast(Mapping[str, object], report)
        self._verify_source_report(report_map)
        self._verify_parquet()

    def _verify_source_report(self, report: Mapping[str, object]) -> None:
        program = _mapping(report.get("program_spec"))
        walk = _mapping(report.get("walk_forward_report"))
        gate = _mapping(report.get("gate_report"))
        selection = _mapping(report.get("frozen_selection"))
        plan = _mapping(program.get("walk_forward_plan"))
        checks = {
            "program_result_id": report.get("program_result_id"),
            "program_id": program.get("program_id"),
            "program_spec_id": program.get("spec_id"),
            "walk_forward_report_id": walk.get("report_id"),
            "gate_report_id": gate.get("gate_report_id"),
            "selection_id": selection.get("selection_id"),
            "plan_id": plan.get("plan_id"),
            "data_version": report.get("data_version"),
            "candidate_selection_id": program.get("candidate_selection_id"),
            "universe_policy_version": program.get("universe_policy_version"),
        }
        for field, actual in checks.items():
            if _text(actual) != _text(getattr(self.manifest, field)):
                raise ValueError(f"V4-1 source report identity drift: {field}")
        denominator = tuple(
            _text(_mapping(value).get("feature_digest"))
            for value in _sequence(report.get("candidate_denominator"))
        )
        selected = tuple(
            _text(_mapping(value).get("feature_digest"))
            for value in _sequence(selection.get("components"))
        )
        if denominator != self.manifest.candidate_feature_digests:
            raise ValueError("V4-1 candidate denominator differs from source report")
        if selected != self.manifest.selected_feature_digests:
            raise ValueError("V4-1 selected factor identities differ from source report")
        if _digest("a2p6-report-content", report, 64) != self.manifest.source_report_content_digest:
            raise ValueError("V4-1 source report content digest mismatch")
        expected = _quant_config_payload(program, self.manifest.rolling_window)
        if _digest("factor-series-quant-config", expected, 40) != self.manifest.quant_config_digest:
            raise ValueError("V4-1 quant configuration digest differs from source report")
        expected_fields: dict[str, object] = {
            "primary_label": str(expected["primary_label"]),
            "decay_labels": tuple(str(value) for value in expected["decay_labels"]),
            "quantiles": int(expected["quantiles"]),
            "min_cross_section": int(expected["min_cross_section"]),
            "min_periods": int(expected["min_periods"]),
            "annualization": float(expected["annualization"]),
            "winsor_lower_quantile": float(expected["winsor_lower_quantile"]),
            "winsor_upper_quantile": float(expected["winsor_upper_quantile"]),
            "rolling_window": int(expected["rolling_window"]),
        }
        for field, expected_value in expected_fields.items():
            actual = getattr(self.manifest, field)
            if actual != expected_value:
                raise ValueError(f"V4-1 manifest quant metadata drift: {field}")

    def _verify_parquet(self) -> None:
        duckdb = _duckdb()
        connection = duckdb.connect()
        try:
            columns = tuple(
                str(row[0])
                for row in connection.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?)", (str(self.data_path),)
                ).fetchall()
            )
            if columns != self.manifest.columns:
                raise ValueError("V4-1 Parquet columns differ from manifest")
            raw_rows = connection.execute(
                "SELECT * FROM read_parquet(?) ORDER BY sequence",
                (str(self.data_path),),
            ).fetchall()
        finally:
            connection.close()
        if len(raw_rows) != self.manifest.row_count:
            raise ValueError("V4-1 Parquet row count differs from manifest")
        rows: list[FactorSeriesRow] = []
        for expected_sequence, raw in enumerate(raw_rows):
            row = FactorSeriesRow(
                sequence=int(raw[0]),
                feature_id=str(raw[2]),
                feature_digest=str(raw[3]),
                fold_id=str(raw[4]),
                session_date=date.fromisoformat(str(raw[5])),
                train_direction=int(raw[6]),
                series_kind=str(raw[7]),
                metric=str(raw[8]),
                authority=str(raw[9]),
                label_name=str(raw[10]),
                quantile=int(raw[11]) if raw[11] is not None else None,
                value=float(raw[12]),
                sample_count=int(raw[13]),
                window_count=int(raw[14]),
            )
            if row.sequence != expected_sequence:
                raise ValueError("V4-1 Parquet sequence is not contiguous")
            if str(raw[1]) != row.row_id:
                raise ValueError("V4-1 Parquet row_id differs from row content")
            rows.append(row)
        if len({row.row_id for row in rows}) != len(rows):
            raise ValueError("V4-1 Parquet contains duplicate row identities")
        digest = _digest("factor-series-rows", [row.to_dict() for row in rows], 64)
        if digest != self.manifest.rows_digest:
            raise ValueError("V4-1 Parquet rows_digest differs from manifest")
        factors = {row.feature_digest for row in rows}
        folds = {row.fold_id for row in rows}
        sessions = {row.session_date for row in rows}
        if factors != set(self.manifest.candidate_feature_digests):
            raise ValueError("V4-1 Parquet factor denominator differs from manifest")
        if len(folds) != self.manifest.fold_count:
            raise ValueError("V4-1 Parquet fold count differs from manifest")
        if len(sessions) != self.manifest.session_count:
            raise ValueError("V4-1 Parquet session count differs from manifest")
        if min(sessions).isoformat() != self.manifest.start_date:
            raise ValueError("V4-1 Parquet start_date differs from manifest")
        if max(sessions).isoformat() != self.manifest.end_date:
            raise ValueError("V4-1 Parquet end_date differs from manifest")

    def query(
        self,
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
        if not 1 <= limit <= 5000:
            raise ValueError("limit must be in [1, 5000]")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if start is not None and end is not None and end < start:
            raise ValueError("end cannot be before start")
        if series_kind is not None and series_kind not in _KIND_ORDER:
            raise ValueError("unknown FactorSeries series_kind")
        if metric is not None and metric not in _METRIC_ORDER:
            raise ValueError("unknown FactorSeries metric")
        if quantile is not None and quantile < 1:
            raise ValueError("quantile must be >= 1")
        where: list[str] = []
        parameters: list[object] = [str(self.data_path)]
        for field, value in (
            ("feature_digest", feature_digest),
            ("fold_id", fold_id),
            ("series_kind", series_kind),
            ("metric", metric),
            ("label_name", label_name),
        ):
            if value:
                where.append(f"{field} = ?")
                parameters.append(value.strip())
        if quantile is not None:
            where.append("quantile = ?")
            parameters.append(quantile)
        if start is not None:
            where.append("session_date >= ?")
            parameters.append(start)
        if end is not None:
            where.append("session_date <= ?")
            parameters.append(end)
        predicate = f" WHERE {' AND '.join(where)}" if where else ""
        duckdb = _duckdb()
        connection = duckdb.connect()
        try:
            total_row = connection.execute(
                f"SELECT count(*) FROM read_parquet(?) {predicate}", parameters
            ).fetchone()
            if total_row is None:
                raise RuntimeError("V4-1 count query returned no row")
            total = int(total_row[0])
            cursor = connection.execute(
                f"SELECT * FROM read_parquet(?) {predicate} "
                "ORDER BY sequence LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            )
            names = [str(value[0]) for value in cursor.description]
            items = []
            for raw in cursor.fetchall():
                item = dict(zip(names, raw, strict=True))
                item["session_date"] = str(item["session_date"])
                items.append(item)
        finally:
            connection.close()
        return {
            "schema_version": FACTOR_SERIES_QUERY_SCHEMA,
            "read_only": True,
            "authority": "mixed_persisted_metrics",
            "series_id": self.manifest.series_id,
            "program_result_id": self.manifest.program_result_id,
            "total": total,
            "offset": offset,
            "limit": limit,
            "items": items,
        }

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from scipy.stats import norm


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _finite(value: float, field_name: str) -> float:
    rendered = float(value)
    if not math.isfinite(rendered):
        raise ValueError(f"{field_name} must be finite")
    return rendered


@dataclass(frozen=True, slots=True)
class USR1PeriodMetricPoint:
    event_time: datetime
    session_id: str
    rank_ic: float
    long_short_return_bps: float
    one_way_turnover: float
    coverage: float
    quantile_monotonicity: float
    schema_version: str = "finagent.us-r1-period-metric-point.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_time", _aware(self.event_time, "event_time"))
        session = self.session_id.strip()
        if not session:
            raise ValueError("session_id must be non-empty")
        object.__setattr__(self, "session_id", session)
        for field_name in ("rank_ic", "long_short_return_bps", "quantile_monotonicity"):
            object.__setattr__(self, field_name, _finite(getattr(self, field_name), field_name))
        turnover = _finite(self.one_way_turnover, "one_way_turnover")
        coverage = _finite(self.coverage, "coverage")
        if turnover < 0:
            raise ValueError("one_way_turnover must be non-negative")
        if not 0.0 <= coverage <= 1.0:
            raise ValueError("coverage must be in [0,1]")
        object.__setattr__(self, "one_way_turnover", turnover)
        object.__setattr__(self, "coverage", coverage)


@dataclass(frozen=True, slots=True)
class USR1FoldSeries:
    fold_id: str
    points: tuple[USR1PeriodMetricPoint, ...]
    schema_version: str = "finagent.us-r1-fold-series.v1"

    def __post_init__(self) -> None:
        fold = self.fold_id.strip()
        if not fold:
            raise ValueError("fold_id must be non-empty")
        object.__setattr__(self, "fold_id", fold)
        if len(self.points) < 2:
            raise ValueError("US-R1 fold series requires at least two periods")
        previous: datetime | None = None
        for point in self.points:
            if previous is not None and point.event_time <= previous:
                raise ValueError("US-R1 fold points must be strictly ordered")
            previous = point.event_time


@dataclass(frozen=True, slots=True)
class USR1FoldSummary:
    fold_id: str
    periods: int
    sessions: int
    mean_rank_ic: float
    rank_icir: float
    mean_long_short_return_bps: float
    mean_one_way_turnover: float
    coverage_mean: float
    coverage_min: float
    quantile_monotonicity_mean: float
    schema_version: str = "finagent.us-r1-fold-summary.v1"

    def __post_init__(self) -> None:
        if self.periods < 2 or self.sessions < 1:
            raise ValueError("US-R1 fold summary requires periods and sessions")
        for field_name in (
            "mean_rank_ic",
            "rank_icir",
            "mean_long_short_return_bps",
            "mean_one_way_turnover",
            "coverage_mean",
            "coverage_min",
            "quantile_monotonicity_mean",
        ):
            _finite(getattr(self, field_name), field_name)
        if self.mean_one_way_turnover < 0:
            raise ValueError("mean_one_way_turnover must be non-negative")
        if not 0.0 <= self.coverage_mean <= 1.0 or not 0.0 <= self.coverage_min <= 1.0:
            raise ValueError("coverage metrics must be in [0,1]")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "fold_id": self.fold_id,
            "periods": self.periods,
            "sessions": self.sessions,
            "mean_rank_ic": self.mean_rank_ic,
            "rank_icir": self.rank_icir,
            "mean_long_short_return_bps": self.mean_long_short_return_bps,
            "mean_one_way_turnover": self.mean_one_way_turnover,
            "coverage_mean": self.coverage_mean,
            "coverage_min": self.coverage_min,
            "quantile_monotonicity_mean": self.quantile_monotonicity_mean,
        }


def rank_icir(values: Sequence[float]) -> float:
    array = np.asarray(tuple(float(value) for value in values), dtype=float)
    if array.size < 2:
        return 0.0
    deviation = float(np.std(array, ddof=1))
    return float(np.mean(array) / deviation) if deviation > 1e-15 else 0.0


def summarize_us_r1_fold(series: USR1FoldSeries, *, direction: int) -> USR1FoldSummary:
    if direction not in {-1, 1}:
        raise ValueError("US-R1 candidate direction must be -1 or 1")
    rank_ic = tuple(direction * point.rank_ic for point in series.points)
    long_short = tuple(direction * point.long_short_return_bps for point in series.points)
    turnovers = tuple(point.one_way_turnover for point in series.points)
    coverages = tuple(point.coverage for point in series.points)
    monotonicity = tuple(direction * point.quantile_monotonicity for point in series.points)
    return USR1FoldSummary(
        fold_id=series.fold_id,
        periods=len(series.points),
        sessions=len({point.session_id for point in series.points}),
        mean_rank_ic=float(np.mean(rank_ic)),
        rank_icir=rank_icir(rank_ic),
        mean_long_short_return_bps=float(np.mean(long_short)),
        mean_one_way_turnover=float(np.mean(turnovers)),
        coverage_mean=float(np.mean(coverages)),
        coverage_min=float(np.min(coverages)),
        quantile_monotonicity_mean=float(np.mean(monotonicity)),
    )


def newey_west_mean_test(values: Sequence[float], *, lags: int) -> tuple[float, float]:
    """Dependence-aware mean test using the same Bartlett HAC convention as A-share robust research."""

    array = np.asarray(tuple(float(value) for value in values), dtype=float)
    if array.size < 2:
        return 0.0, 1.0
    if not np.isfinite(array).all():
        raise ValueError("Newey-West inputs must be finite")
    centered = array - float(np.mean(array))
    count = array.size
    effective_lags = min(max(0, int(lags)), count - 1)
    long_run_variance = float(np.dot(centered, centered) / count)
    for lag in range(1, effective_lags + 1):
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / count)
        weight = 1.0 - lag / (effective_lags + 1.0)
        long_run_variance += 2.0 * weight * covariance
    long_run_variance = max(long_run_variance, 0.0)
    standard_error = math.sqrt(long_run_variance / count) if long_run_variance > 1e-30 else 0.0
    if standard_error <= 1e-15:
        return 0.0, 1.0
    statistic = float(np.mean(array) / standard_error)
    pvalue = float(2.0 * norm.sf(abs(statistic)))
    return statistic, min(max(pvalue, 0.0), 1.0)


def session_block_bootstrap_mean_test(
    points: Sequence[USR1PeriodMetricPoint],
    *,
    direction: int,
    samples: int,
    block_sessions: int,
    seed: int,
) -> tuple[float, float, float]:
    """Bootstrap the session-mean RankIC series; intraday bars are never treated as IID draws."""

    if direction not in {-1, 1}:
        raise ValueError("US-R1 candidate direction must be -1 or 1")
    if samples < 100:
        raise ValueError("bootstrap samples must be >= 100")
    if block_sessions < 1:
        raise ValueError("bootstrap block_sessions must be positive")
    by_session: dict[str, list[float]] = defaultdict(list)
    session_order: list[str] = []
    for point in points:
        if point.session_id not in by_session:
            session_order.append(point.session_id)
        by_session[point.session_id].append(direction * point.rank_ic)
    session_means = np.asarray(
        [float(np.mean(by_session[session_id])) for session_id in session_order],
        dtype=float,
    )
    if session_means.size < 2:
        value = float(session_means[0]) if session_means.size else 0.0
        return 1.0, value, value
    count = session_means.size
    block = min(block_sessions, count)
    blocks_needed = int(math.ceil(count / block))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, count, size=(samples, blocks_needed), endpoint=False)
    offsets = np.arange(block, dtype=int)
    indices = (starts[:, :, None] + offsets[None, None, :]) % count
    indices = indices.reshape(samples, -1)[:, :count]
    sample_means = np.mean(session_means[indices], axis=1)
    centered = session_means - float(np.mean(session_means))
    null_means = np.mean(centered[indices], axis=1)
    observed = abs(float(np.mean(session_means)))
    pvalue = float((1 + np.count_nonzero(np.abs(null_means) >= observed)) / (samples + 1))
    lower, upper = np.quantile(sample_means, (0.025, 0.975))
    return pvalue, float(lower), float(upper)

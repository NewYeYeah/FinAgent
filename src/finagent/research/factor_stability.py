from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

import numpy as np
from scipy.stats import norm, rankdata

from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.domain._validation import require_non_empty
from finagent.domain.research import DatasetRequest, ResearchSplit
from finagent.models.alpha.primitives import winsorize_cross_section

from .factor_quant import FactorQuantAnalyzer


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


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
    standard_deviation = float(np.std(array, ddof=1))
    return float(np.mean(array) / standard_deviation) if standard_deviation > 1e-15 else 0.0


def _newey_west_mean_test(values: Sequence[float], lags: int) -> tuple[float, float]:
    array = np.asarray(tuple(values), dtype=float)
    if array.size < 2:
        return 0.0, 1.0
    centered = array - float(np.mean(array))
    n = array.size
    effective_lags = min(max(0, int(lags)), n - 1)
    long_run_variance = float(np.dot(centered, centered) / n)
    for lag in range(1, effective_lags + 1):
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / n)
        weight = 1.0 - lag / (effective_lags + 1.0)
        long_run_variance += 2.0 * weight * covariance
    long_run_variance = max(long_run_variance, 0.0)
    standard_error = math.sqrt(long_run_variance / n) if long_run_variance > 1e-30 else 0.0
    if standard_error <= 1e-15:
        return 0.0, 1.0
    statistic = float(np.mean(array) / standard_error)
    pvalue = float(2.0 * norm.sf(abs(statistic)))
    return statistic, min(max(pvalue, 0.0), 1.0)


def _circular_block_bootstrap(
    values: Sequence[float],
    *,
    samples: int,
    block_length: int,
    seed: int,
) -> tuple[float, float, float]:
    array = np.asarray(tuple(values), dtype=float)
    if array.size < 2:
        value = float(array[0]) if array.size else 0.0
        return 1.0, value, value
    n = array.size
    block = min(max(1, int(block_length)), n)
    blocks_needed = int(math.ceil(n / block))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(samples, blocks_needed), endpoint=False)
    offsets = np.arange(block, dtype=int)
    indices = (starts[:, :, None] + offsets[None, None, :]) % n
    indices = indices.reshape(samples, -1)[:, :n]
    sample_means = np.mean(array[indices], axis=1)
    centered = array - float(np.mean(array))
    null_means = np.mean(centered[indices], axis=1)
    observed = abs(float(np.mean(array)))
    pvalue = float((1 + np.count_nonzero(np.abs(null_means) >= observed)) / (samples + 1))
    lower, upper = np.quantile(sample_means, (0.025, 0.975))
    return pvalue, float(lower), float(upper)


def adjust_family_pvalues(raw: Mapping[str, float]) -> dict[str, tuple[float, float]]:
    """Return ``digest -> (Holm adjusted p, Benjamini-Hochberg q)``."""

    items = sorted((str(key), float(value)) for key, value in raw.items())
    if not items:
        return {}
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for _, value in items):
        raise ValueError("raw p-values must be finite and in [0, 1]")
    ordered = sorted(items, key=lambda item: (item[1], item[0]))
    count = len(ordered)

    holm: dict[str, float] = {}
    running = 0.0
    for rank, (key, pvalue) in enumerate(ordered):
        adjusted = min(1.0, (count - rank) * pvalue)
        running = max(running, adjusted)
        holm[key] = running

    bh: dict[str, float] = {}
    running_q = 1.0
    for reverse_index in range(count - 1, -1, -1):
        key, pvalue = ordered[reverse_index]
        rank = reverse_index + 1
        running_q = min(running_q, count * pvalue / rank)
        bh[key] = min(1.0, running_q)
    return {key: (holm[key], bh[key]) for key, _ in items}


@dataclass(frozen=True, slots=True)
class FactorStabilityConfig:
    rolling_window: int = 63
    rolling_step: int = 21
    min_rolling_periods: int = 20
    hac_lags: int = 5
    bootstrap_samples: int = 500
    bootstrap_block_length: int = 20
    bootstrap_seed: int = 20_260_827

    def __post_init__(self) -> None:
        integer_fields = (
            ("rolling_window", self.rolling_window, 2),
            ("rolling_step", self.rolling_step, 1),
            ("min_rolling_periods", self.min_rolling_periods, 2),
            ("hac_lags", self.hac_lags, 0),
            ("bootstrap_samples", self.bootstrap_samples, 100),
            ("bootstrap_block_length", self.bootstrap_block_length, 1),
        )
        for name, value, minimum in integer_fields:
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if self.min_rolling_periods > self.rolling_window:
            raise ValueError("min_rolling_periods cannot exceed rolling_window")

    def to_dict(self) -> dict[str, object]:
        return {
            "rolling_window": self.rolling_window,
            "rolling_step": self.rolling_step,
            "min_rolling_periods": self.min_rolling_periods,
            "hac_lags": self.hac_lags,
            "bootstrap_samples": self.bootstrap_samples,
            "bootstrap_block_length": self.bootstrap_block_length,
            "bootstrap_seed": self.bootstrap_seed,
        }


@dataclass(frozen=True, slots=True)
class FactorRollingICPoint:
    start: datetime
    end: datetime
    rank_ic: float
    rank_icir: float
    periods: int

    def __post_init__(self) -> None:
        if self.end < self.start or self.periods < 2:
            raise ValueError("invalid rolling IC interval")
        if not math.isfinite(self.rank_ic) or not math.isfinite(self.rank_icir):
            raise ValueError("rolling IC metrics must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "rank_ic": self.rank_ic,
            "rank_icir": self.rank_icir,
            "periods": self.periods,
        }


@dataclass(frozen=True, slots=True)
class FactorSubperiodStability:
    period: str
    start: datetime
    end: datetime
    rank_ic: float
    rank_icir: float
    periods: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "period", require_non_empty(self.period, "period"))
        if self.end < self.start or self.periods < 1:
            raise ValueError("invalid factor subperiod")
        if not math.isfinite(self.rank_ic) or not math.isfinite(self.rank_icir):
            raise ValueError("subperiod metrics must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "period": self.period,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "rank_ic": self.rank_ic,
            "rank_icir": self.rank_icir,
            "periods": self.periods,
        }


@dataclass(frozen=True, slots=True)
class FactorCandidateStabilityReport:
    feature_id: str
    feature_digest: str
    primary_label: str
    periods: int
    dominant_direction: int
    positive_rank_ic_ratio: float
    sign_consistency_ratio: float
    hac_lags: int
    hac_tstat: float
    hac_pvalue: float
    bootstrap_pvalue: float
    bootstrap_ci_lower: float
    bootstrap_ci_upper: float
    quantile_monotonicity: float
    turnover_std: float
    coverage_mean: float
    coverage_min: float
    horizon_sign_consistency: float
    horizon_rank_ic: Mapping[str, float]
    rolling_rank_ic: tuple[FactorRollingICPoint, ...]
    subperiods: tuple[FactorSubperiodStability, ...]

    def __post_init__(self) -> None:
        for name in ("feature_id", "feature_digest", "primary_label"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if self.periods < 2 or self.dominant_direction not in {-1, 1} or self.hac_lags < 0:
            raise ValueError("invalid factor stability identity")
        bounded = (
            self.positive_rank_ic_ratio,
            self.sign_consistency_ratio,
            self.hac_pvalue,
            self.bootstrap_pvalue,
            self.coverage_mean,
            self.coverage_min,
            self.horizon_sign_consistency,
        )
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in bounded):
            raise ValueError("bounded stability metrics must be finite and in [0, 1]")
        numeric = (
            self.hac_tstat,
            self.bootstrap_ci_lower,
            self.bootstrap_ci_upper,
            self.quantile_monotonicity,
            self.turnover_std,
        )
        if any(not math.isfinite(value) for value in numeric):
            raise ValueError("stability metrics must be finite")
        if self.bootstrap_ci_upper < self.bootstrap_ci_lower or self.turnover_std < 0:
            raise ValueError("invalid bootstrap interval or turnover stability")
        horizons = {str(key): float(value) for key, value in self.horizon_rank_ic.items()}
        if self.primary_label not in horizons or any(not math.isfinite(value) for value in horizons.values()):
            raise ValueError("horizon_rank_ic must include finite primary-label evidence")
        object.__setattr__(self, "horizon_rank_ic", MappingProxyType(horizons))

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "feature_digest": self.feature_digest,
            "primary_label": self.primary_label,
            "periods": self.periods,
            "dominant_direction": self.dominant_direction,
            "positive_rank_ic_ratio": self.positive_rank_ic_ratio,
            "sign_consistency_ratio": self.sign_consistency_ratio,
            "hac": {
                "lags": self.hac_lags,
                "tstat": self.hac_tstat,
                "pvalue": self.hac_pvalue,
            },
            "block_bootstrap": {
                "pvalue": self.bootstrap_pvalue,
                "ci_lower": self.bootstrap_ci_lower,
                "ci_upper": self.bootstrap_ci_upper,
            },
            "quantile_monotonicity": self.quantile_monotonicity,
            "turnover_std": self.turnover_std,
            "coverage_mean": self.coverage_mean,
            "coverage_min": self.coverage_min,
            "horizon_sign_consistency": self.horizon_sign_consistency,
            "horizon_rank_ic": dict(self.horizon_rank_ic),
            "rolling_rank_ic": [value.to_dict() for value in self.rolling_rank_ic],
            "subperiods": [value.to_dict() for value in self.subperiods],
        }


@dataclass(frozen=True, slots=True)
class FactorMultiplicityDiagnostics:
    feature_digest: str
    raw_hac_pvalue: float
    holm_adjusted_pvalue: float
    bh_qvalue: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "feature_digest",
            require_non_empty(self.feature_digest, "feature_digest"),
        )
        values = (self.raw_hac_pvalue, self.holm_adjusted_pvalue, self.bh_qvalue)
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values):
            raise ValueError("multiplicity diagnostics must be in [0, 1]")

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_digest": self.feature_digest,
            "raw_hac_pvalue": self.raw_hac_pvalue,
            "holm_adjusted_pvalue": self.holm_adjusted_pvalue,
            "bh_qvalue": self.bh_qvalue,
        }


@dataclass(frozen=True, slots=True)
class FactorFamilyStabilityReport:
    data_version: str
    split_name: str
    primary_label: str
    candidates: tuple[FactorCandidateStabilityReport, ...]
    multiplicity: Mapping[str, FactorMultiplicityDiagnostics]
    config: FactorStabilityConfig

    def __post_init__(self) -> None:
        for name in ("data_version", "split_name", "primary_label"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if not self.candidates:
            raise ValueError("factor stability report requires candidates")
        digests = {candidate.feature_digest for candidate in self.candidates}
        if len(digests) != len(self.candidates):
            raise ValueError("factor stability report contains duplicate candidates")
        values = dict(self.multiplicity)
        if set(values) != digests:
            raise ValueError("factor stability multiplicity denominator differs from candidates")
        object.__setattr__(self, "multiplicity", MappingProxyType(values))

    @property
    def report_id(self) -> str:
        encoded = _canonical_json(self.to_dict(include_id=False)).encode()
        return f"factor-stability-{hashlib.sha256(encoded).hexdigest()[:24]}"

    def candidate(self, digest: str) -> FactorCandidateStabilityReport:
        for candidate in self.candidates:
            if candidate.feature_digest == digest:
                return candidate
        raise KeyError(digest)

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.factor-stability-report.v1",
            "data_version": self.data_version,
            "split_name": self.split_name,
            "primary_label": self.primary_label,
            "config": self.config.to_dict(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "multiplicity": {
                key: value.to_dict() for key, value in self.multiplicity.items()
            },
            "scope": f"{self.split_name}_factor_stability_diagnostics",
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


class FactorStabilityAnalyzer:
    """Compute time stability and dependence-aware inference for factor panels."""

    VERSION = "factor-stability-v1"

    def __init__(
        self,
        factor_analyzer: FactorQuantAnalyzer,
        *,
        config: FactorStabilityConfig = FactorStabilityConfig(),
    ) -> None:
        self.factor_analyzer = factor_analyzer
        self.config = config

    def _ic_series(
        self,
        panel: ResearchSplit,
        label_name: str,
    ) -> tuple[tuple[datetime, ...], np.ndarray, np.ndarray]:
        factor = panel.feature_values[:, :, 0]
        labels = panel.label_panel(label_name)
        eligibility = np.asarray(panel.eligibility_mask, dtype=bool)
        timestamps: list[datetime] = []
        pearson_values: list[float] = []
        rank_values: list[float] = []
        quant_config = self.factor_analyzer.config
        for row, timestamp in enumerate(panel.timestamps):
            mask = eligibility[row] & np.isfinite(factor[row]) & np.isfinite(labels[row])
            if int(mask.sum()) < quant_config.min_cross_section:
                continue
            raw_factor = factor[row][mask]
            target = labels[row][mask]
            winsorized = winsorize_cross_section(
                raw_factor,
                lower_quantile=quant_config.winsor_lower_quantile,
                upper_quantile=quant_config.winsor_upper_quantile,
            )
            pearson = _safe_correlation(np.asarray(winsorized, dtype=float), target)
            rank_ic = _safe_correlation(
                rankdata(raw_factor, method="average"),
                rankdata(target, method="average"),
            )
            if pearson is None or rank_ic is None:
                continue
            timestamps.append(timestamp)
            pearson_values.append(pearson)
            rank_values.append(rank_ic)
        if len(rank_values) < quant_config.min_periods:
            raise ValueError(
                f"factor has only {len(rank_values)} usable stability periods for {label_name!r}; "
                f"minimum is {quant_config.min_periods}"
            )
        return (
            tuple(timestamps),
            np.asarray(pearson_values, dtype=float),
            np.asarray(rank_values, dtype=float),
        )

    def _rolling_points(
        self,
        timestamps: tuple[datetime, ...],
        rank_values: np.ndarray,
    ) -> tuple[FactorRollingICPoint, ...]:
        window = min(self.config.rolling_window, len(rank_values))
        if window < self.config.min_rolling_periods:
            return ()
        endpoints = list(range(window, len(rank_values) + 1, self.config.rolling_step))
        if endpoints[-1] != len(rank_values):
            endpoints.append(len(rank_values))
        points = []
        for endpoint in endpoints:
            start = endpoint - window
            values = rank_values[start:endpoint]
            points.append(
                FactorRollingICPoint(
                    start=timestamps[start],
                    end=timestamps[endpoint - 1],
                    rank_ic=float(np.mean(values)),
                    rank_icir=_icir(values),
                    periods=len(values),
                )
            )
        return tuple(points)

    @staticmethod
    def _subperiods(
        timestamps: tuple[datetime, ...],
        rank_values: np.ndarray,
    ) -> tuple[FactorSubperiodStability, ...]:
        grouped: dict[int, list[int]] = {}
        for index, timestamp in enumerate(timestamps):
            grouped.setdefault(timestamp.year, []).append(index)
        output = []
        for year in sorted(grouped):
            indices = grouped[year]
            values = rank_values[indices]
            output.append(
                FactorSubperiodStability(
                    period=str(year),
                    start=timestamps[indices[0]],
                    end=timestamps[indices[-1]],
                    rank_ic=float(np.mean(values)),
                    rank_icir=_icir(values),
                    periods=len(values),
                )
            )
        return tuple(output)

    def _quantile_series(
        self,
        panel: ResearchSplit,
    ) -> tuple[tuple[float, ...], np.ndarray, np.ndarray]:
        config = self.factor_analyzer.config
        factor = panel.feature_values[:, :, 0]
        labels = panel.label_panel(config.primary_label)
        eligibility = np.asarray(panel.eligibility_mask, dtype=bool)
        quantile_returns: list[list[float]] = [[] for _ in range(config.quantiles)]
        spreads: list[float] = []
        turnovers: list[float] = []
        previous_weights = np.zeros(panel.n_assets, dtype=float)
        for row in range(panel.n_times):
            mask = eligibility[row] & np.isfinite(factor[row])
            indices = np.flatnonzero(mask)
            if len(indices) < config.min_cross_section:
                continue
            ordered = indices[np.argsort(factor[row][indices], kind="mergesort")]
            buckets = np.array_split(ordered, config.quantiles)
            if any(len(bucket) == 0 for bucket in buckets):
                continue
            if any(not np.all(np.isfinite(labels[row][bucket])) for bucket in buckets):
                continue
            bucket_values = [float(np.mean(labels[row][bucket])) for bucket in buckets]
            for target, value in zip(quantile_returns, bucket_values, strict=True):
                target.append(value)
            spreads.append(bucket_values[-1] - bucket_values[0])
            weights = np.zeros_like(previous_weights)
            weights[buckets[-1]] = 0.5 / len(buckets[-1])
            weights[buckets[0]] = -0.5 / len(buckets[0])
            turnovers.append(float(0.5 * np.abs(weights - previous_weights).sum()))
            previous_weights = weights
        means = tuple(float(np.mean(values)) for values in quantile_returns)
        return means, np.asarray(spreads, dtype=float), np.asarray(turnovers, dtype=float)

    def analyze_panel(
        self,
        *,
        feature_id: str,
        feature_digest: str,
        panel: ResearchSplit,
    ) -> FactorCandidateStabilityReport:
        quant_config = self.factor_analyzer.config
        horizon_rank_ic: dict[str, float] = {}
        primary_timestamps: tuple[datetime, ...] | None = None
        primary_rank: np.ndarray | None = None
        for label_name in quant_config.labels:
            timestamps, _, rank_values = self._ic_series(panel, label_name)
            horizon_rank_ic[label_name] = float(np.mean(rank_values))
            if label_name == quant_config.primary_label:
                primary_timestamps = timestamps
                primary_rank = rank_values
        assert primary_timestamps is not None and primary_rank is not None

        mean_rank = float(np.mean(primary_rank))
        dominant_direction = 1 if mean_rank >= 0 else -1
        positive_ratio = float(np.mean(primary_rank > 0))
        sign_consistency = float(np.mean(primary_rank * dominant_direction > 0))
        hac_tstat, hac_pvalue = _newey_west_mean_test(primary_rank, self.config.hac_lags)
        feature_seed = int(hashlib.sha256(feature_digest.encode()).hexdigest()[:8], 16)
        bootstrap_pvalue, ci_lower, ci_upper = _circular_block_bootstrap(
            primary_rank,
            samples=self.config.bootstrap_samples,
            block_length=self.config.bootstrap_block_length,
            seed=self.config.bootstrap_seed ^ feature_seed,
        )

        quantile_means, _, turnovers = self._quantile_series(panel)
        monotonicity = _safe_correlation(
            np.arange(len(quantile_means), dtype=float),
            rankdata(np.asarray(quantile_means), method="average"),
        )
        if monotonicity is None:
            monotonicity = 0.0
        eligibility = np.asarray(panel.eligibility_mask, dtype=bool)
        factor = panel.feature_values[:, :, 0]
        row_coverage = []
        for row in range(panel.n_times):
            eligible = int(eligibility[row].sum())
            if eligible:
                row_coverage.append(
                    float((eligibility[row] & np.isfinite(factor[row])).sum() / eligible)
                )
        horizon_values = np.asarray(tuple(horizon_rank_ic.values()), dtype=float)
        horizon_consistency = (
            float(np.mean(horizon_values * dominant_direction > 0))
            if horizon_values.size
            else 0.0
        )
        return FactorCandidateStabilityReport(
            feature_id=feature_id,
            feature_digest=feature_digest,
            primary_label=quant_config.primary_label,
            periods=len(primary_rank),
            dominant_direction=dominant_direction,
            positive_rank_ic_ratio=positive_ratio,
            sign_consistency_ratio=sign_consistency,
            hac_lags=min(self.config.hac_lags, len(primary_rank) - 1),
            hac_tstat=hac_tstat,
            hac_pvalue=hac_pvalue,
            bootstrap_pvalue=bootstrap_pvalue,
            bootstrap_ci_lower=ci_lower,
            bootstrap_ci_upper=ci_upper,
            quantile_monotonicity=float(monotonicity),
            turnover_std=float(np.std(turnovers, ddof=1)) if len(turnovers) > 1 else 0.0,
            coverage_mean=float(np.mean(row_coverage)) if row_coverage else 0.0,
            coverage_min=float(np.min(row_coverage)) if row_coverage else 0.0,
            horizon_sign_consistency=horizon_consistency,
            horizon_rank_ic=horizon_rank_ic,
            rolling_rank_ic=self._rolling_points(primary_timestamps, primary_rank),
            subperiods=self._subperiods(primary_timestamps, primary_rank),
        )

    def analyze(
        self,
        candidates: Sequence[GeneratedFeatureArtifact],
        *,
        request: DatasetRequest,
    ) -> FactorFamilyStabilityReport:
        artifacts = tuple(candidates)
        if not artifacts or len({artifact.digest for artifact in artifacts}) != len(artifacts):
            raise ValueError("factor stability analysis requires unique candidates")
        reports = []
        for artifact in artifacts:
            dataset = self.factor_analyzer.materializer.materialize(artifact, request)
            reports.append(
                self.analyze_panel(
                    feature_id=artifact.spec.feature_id,
                    feature_digest=artifact.digest,
                    panel=dataset.get_split(self.factor_analyzer.config.split_name),
                )
            )
        adjusted = adjust_family_pvalues(
            {report.feature_digest: report.hac_pvalue for report in reports}
        )
        multiplicity = {
            report.feature_digest: FactorMultiplicityDiagnostics(
                feature_digest=report.feature_digest,
                raw_hac_pvalue=report.hac_pvalue,
                holm_adjusted_pvalue=adjusted[report.feature_digest][0],
                bh_qvalue=adjusted[report.feature_digest][1],
            )
            for report in reports
        }
        return FactorFamilyStabilityReport(
            data_version=self.factor_analyzer.adapter.data_version,
            split_name=self.factor_analyzer.config.split_name,
            primary_label=self.factor_analyzer.config.primary_label,
            candidates=tuple(reports),
            multiplicity=multiplicity,
            config=self.config,
        )

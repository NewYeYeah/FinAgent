from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType

import numpy as np
from scipy.stats import norm, rankdata

from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.domain._validation import require_non_empty
from finagent.domain.research import DatasetRequest, ResearchDataset, TimeRange

from .factor_quant import (
    FactorQuantAnalyzer,
    FactorQuantCandidateReport,
    FactorQuantConfig,
)
from .factor_stability import adjust_family_pvalues


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(prefix: str, payload: object, length: int = 24) -> str:
    value = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:length]
    return f"{prefix}-{value}"


def _icir(values: Sequence[float]) -> float:
    array = np.asarray(tuple(values), dtype=float)
    if array.size < 2:
        return 0.0
    standard_deviation = float(np.std(array, ddof=1))
    return (
        float(np.mean(array) / standard_deviation)
        if standard_deviation > 1e-15
        else 0.0
    )


def _safe_correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if left.size < 2 or right.size != left.size:
        return None
    if float(np.std(left)) <= 1e-15 or float(np.std(right)) <= 1e-15:
        return None
    value = float(np.corrcoef(left, right)[0, 1])
    return value if math.isfinite(value) else None


def _monotonicity(values: Sequence[float]) -> float:
    array = np.asarray(tuple(values), dtype=float)
    if array.size < 2 or not np.isfinite(array).all():
        return 0.0
    if float(np.std(array)) <= 1e-15:
        return 0.0
    value = float(np.corrcoef(np.arange(array.size, dtype=float), array)[0, 1])
    return value if math.isfinite(value) else 0.0


def _newey_west_mean_test(values: Sequence[float], lags: int) -> tuple[float, float]:
    array = np.asarray(tuple(values), dtype=float)
    if array.size < 2:
        return 0.0, 1.0
    centered = array - float(np.mean(array))
    count = array.size
    effective_lags = min(max(0, int(lags)), count - 1)
    long_run_variance = float(np.dot(centered, centered) / count)
    for lag in range(1, effective_lags + 1):
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / count)
        weight = 1.0 - lag / (effective_lags + 1.0)
        long_run_variance += 2.0 * weight * covariance
    long_run_variance = max(long_run_variance, 0.0)
    standard_error = (
        math.sqrt(long_run_variance / count)
        if long_run_variance > 1e-30
        else 0.0
    )
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
    count = array.size
    block = min(max(1, int(block_length)), count)
    blocks_needed = int(math.ceil(count / block))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, count, size=(samples, blocks_needed), endpoint=False)
    offsets = np.arange(block, dtype=int)
    indices = (starts[:, :, None] + offsets[None, None, :]) % count
    indices = indices.reshape(samples, -1)[:, :count]
    sample_means = np.mean(array[indices], axis=1)
    centered = array - float(np.mean(array))
    null_means = np.mean(centered[indices], axis=1)
    observed = abs(float(np.mean(array)))
    pvalue = float(
        (1 + np.count_nonzero(np.abs(null_means) >= observed)) / (samples + 1)
    )
    lower, upper = np.quantile(sample_means, (0.025, 0.975))
    return pvalue, float(lower), float(upper)


@dataclass(frozen=True, slots=True)
class AshareWalkForwardFold:
    fold_id: str
    train_split: str
    test_split: str
    train: TimeRange
    test: TimeRange

    def __post_init__(self) -> None:
        for name in ("fold_id", "train_split", "test_split"):
            object.__setattr__(
                self,
                name,
                require_non_empty(getattr(self, name), name),
            )
        if self.train_split == self.test_split:
            raise ValueError("walk-forward train/test split names must differ")
        if self.train.end > self.test.start:
            raise ValueError("walk-forward training must end before test begins")

    def to_dict(self) -> dict[str, object]:
        return {
            "fold_id": self.fold_id,
            "train_split": self.train_split,
            "test_split": self.test_split,
            "train": [self.train.start.isoformat(), self.train.end.isoformat()],
            "test": [self.test.start.isoformat(), self.test.end.isoformat()],
        }


@dataclass(frozen=True, slots=True)
class AshareExpandingWalkForwardPlan:
    folds: tuple[AshareWalkForwardFold, ...]
    reserve: TimeRange

    def __post_init__(self) -> None:
        if not self.folds:
            raise ValueError("walk-forward plan requires folds")
        if len({fold.fold_id for fold in self.folds}) != len(self.folds):
            raise ValueError("walk-forward fold ids must be unique")
        starts = {fold.train.start for fold in self.folds}
        if len(starts) != 1:
            raise ValueError("expanding walk-forward folds must share a training start")
        previous_test_end = None
        previous_train_end = None
        for fold in self.folds:
            if previous_test_end is not None and fold.test.start < previous_test_end:
                raise ValueError("walk-forward test windows must not overlap")
            if previous_train_end is not None and fold.train.end <= previous_train_end:
                raise ValueError("walk-forward training windows must expand")
            previous_test_end = fold.test.end
            previous_train_end = fold.train.end
        if self.folds[-1].test.end > self.reserve.start:
            raise ValueError("walk-forward tests must end before untouched reserve")
        if self.reserve.end <= self.reserve.start:
            raise ValueError("reserve range is invalid")

    @property
    def plan_id(self) -> str:
        return _digest("ashare-walk-forward-plan", self.to_dict(include_id=False))

    @property
    def split_ranges(self) -> Mapping[str, TimeRange]:
        values: dict[str, TimeRange] = {}
        for fold in self.folds:
            values[fold.train_split] = fold.train
            values[fold.test_split] = fold.test
        return MappingProxyType(values)

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.ashare-expanding-walk-forward-plan.v1",
            "folds": [fold.to_dict() for fold in self.folds],
            "reserve": [self.reserve.start.isoformat(), self.reserve.end.isoformat()],
            "reserve_status": "untouched",
        }
        if include_id:
            payload["plan_id"] = self.plan_id
        return payload


@dataclass(frozen=True, slots=True)
class AshareResearchProgramSpec:
    program_id: str
    data_version: str
    candidate_selection_id: str
    universe_policy_version: str
    plan: AshareExpandingWalkForwardPlan
    approved_input_fields: tuple[str, ...]
    primary_label: str
    decay_labels: tuple[str, ...]
    factor_quant_config: Mapping[str, object]
    gate_config: Mapping[str, object]
    selector_config: Mapping[str, object]
    generation_config: Mapping[str, object]
    reserve_id: str

    def __post_init__(self) -> None:
        for name in (
            "program_id",
            "data_version",
            "candidate_selection_id",
            "universe_policy_version",
            "primary_label",
            "reserve_id",
        ):
            object.__setattr__(
                self,
                name,
                require_non_empty(getattr(self, name), name),
            )
        fields = tuple(
            require_non_empty(value, "approved input field")
            for value in self.approved_input_fields
        )
        if not fields or len(set(fields)) != len(fields):
            raise ValueError("approved_input_fields must be unique and non-empty")
        decay = tuple(require_non_empty(value, "decay label") for value in self.decay_labels)
        if self.primary_label in decay or len(set(decay)) != len(decay):
            raise ValueError("decay labels must be unique and exclude primary label")
        object.__setattr__(self, "approved_input_fields", fields)
        object.__setattr__(self, "decay_labels", decay)
        for name in (
            "factor_quant_config",
            "gate_config",
            "selector_config",
            "generation_config",
        ):
            object.__setattr__(
                self,
                name,
                MappingProxyType(dict(getattr(self, name))),
            )

    @property
    def spec_id(self) -> str:
        return _digest("ashare-research-program-spec", self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.ashare-research-program-spec.v1",
            "program_id": self.program_id,
            "data_version": self.data_version,
            "candidate_selection_id": self.candidate_selection_id,
            "universe_policy_version": self.universe_policy_version,
            "walk_forward_plan": self.plan.to_dict(),
            "approved_input_fields": list(self.approved_input_fields),
            "primary_label": self.primary_label,
            "decay_labels": list(self.decay_labels),
            "factor_quant_config": dict(self.factor_quant_config),
            "gate_config": dict(self.gate_config),
            "selector_config": dict(self.selector_config),
            "generation_config": dict(self.generation_config),
            "reserve_id": self.reserve_id,
            "scope": "internal development/walk-forward only; reserve is untouched",
        }
        if include_id:
            payload["spec_id"] = self.spec_id
        return payload


class SQLiteAshareResearchProgramSpecStore:
    """Immutable A2.6 program-spec registry."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ashare_research_program_specs (
                    program_id TEXT PRIMARY KEY,
                    spec_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def register(self, spec: AshareResearchProgramSpec) -> None:
        payload = _canonical_json(spec.to_dict())
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT spec_id, payload_json FROM ashare_research_program_specs "
                "WHERE program_id=?",
                (spec.program_id,),
            ).fetchone()
            if existing is not None:
                if str(existing[0]) != spec.spec_id or str(existing[1]) != payload:
                    raise ValueError(
                        f"A-share research program {spec.program_id!r} is immutable"
                    )
                return
            connection.execute(
                "INSERT INTO ashare_research_program_specs VALUES (?, ?, ?)",
                (spec.program_id, spec.spec_id, payload),
            )

    def payload(self, program_id: str) -> Mapping[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM ashare_research_program_specs WHERE program_id=?",
                (program_id,),
            ).fetchone()
        if row is None:
            raise KeyError(program_id)
        value = json.loads(str(row[0]))
        if not isinstance(value, Mapping):
            raise TypeError("stored A-share research program spec is invalid")
        return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class AshareProgramReservationPlan:
    program_id: str
    family_id: str
    spec_id: str
    alpha: float
    variants: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("program_id", "family_id", "spec_id"):
            object.__setattr__(
                self,
                name,
                require_non_empty(getattr(self, name), name),
            )
        if not 0.0 < self.alpha < 1.0:
            raise ValueError("family alpha must be in (0, 1)")
        if not self.variants or len(set(self.variants)) != len(self.variants):
            raise ValueError("program reservation variants must be unique and non-empty")

    def fingerprint(self, task_id: str) -> str:
        return _digest(
            "ashare-program-plan",
            {
                "task_id": require_non_empty(task_id, "task_id"),
                "program_id": self.program_id,
                "family_id": self.family_id,
                "spec_id": self.spec_id,
                "alpha": self.alpha,
                "variants": list(self.variants),
            },
            64,
        )


@dataclass(frozen=True, slots=True)
class AshareWalkForwardFoldCandidate:
    fold_id: str
    train_direction: int
    train_rank_ic: float
    train_rank_icir: float
    test_raw_rank_ic: float
    test_raw_rank_icir: float
    test_rank_ic: float
    test_rank_icir: float
    test_raw_long_short_sharpe: float
    test_long_short_sharpe: float
    coverage: float
    quantile_monotonicity: float
    mean_one_way_turnover: float
    periods: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fold_id",
            require_non_empty(self.fold_id, "fold_id"),
        )
        if self.train_direction not in {-1, 1} or self.periods < 2:
            raise ValueError("invalid walk-forward fold candidate identity")
        numeric = (
            self.train_rank_ic,
            self.train_rank_icir,
            self.test_raw_rank_ic,
            self.test_raw_rank_icir,
            self.test_rank_ic,
            self.test_rank_icir,
            self.test_raw_long_short_sharpe,
            self.test_long_short_sharpe,
            self.coverage,
            self.quantile_monotonicity,
            self.mean_one_way_turnover,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("walk-forward fold metrics must be finite")
        if not 0.0 <= self.coverage <= 1.0:
            raise ValueError("fold coverage must be in [0, 1]")

    def to_dict(self) -> dict[str, object]:
        return {
            "fold_id": self.fold_id,
            "train_direction": self.train_direction,
            "train_rank_ic": self.train_rank_ic,
            "train_rank_icir": self.train_rank_icir,
            "test_raw_rank_ic": self.test_raw_rank_ic,
            "test_raw_rank_icir": self.test_raw_rank_icir,
            "test_rank_ic": self.test_rank_ic,
            "test_rank_icir": self.test_rank_icir,
            "test_raw_long_short_sharpe": self.test_raw_long_short_sharpe,
            "test_long_short_sharpe": self.test_long_short_sharpe,
            "coverage": self.coverage,
            "quantile_monotonicity": self.quantile_monotonicity,
            "mean_one_way_turnover": self.mean_one_way_turnover,
            "periods": self.periods,
        }


@dataclass(frozen=True, slots=True)
class AshareWalkForwardCandidateReport:
    feature_id: str
    feature_digest: str
    folds: tuple[AshareWalkForwardFoldCandidate, ...]
    dominant_direction: int
    direction_consistency: float
    pooled_rank_ic: float
    pooled_rank_icir: float
    mean_fold_rank_icir: float
    worst_fold_rank_icir: float
    positive_fold_ratio: float
    mean_fold_long_short_sharpe: float
    worst_fold_long_short_sharpe: float
    coverage_mean: float
    coverage_min: float
    quantile_monotonicity: float
    mean_one_way_turnover: float
    horizon_sign_consistency: float
    hac_tstat: float
    raw_hac_pvalue: float
    bootstrap_pvalue: float
    bootstrap_ci_lower: float
    bootstrap_ci_upper: float
    holm_adjusted_pvalue: float = 1.0
    bh_qvalue: float = 1.0

    def __post_init__(self) -> None:
        for name in ("feature_id", "feature_digest"):
            object.__setattr__(
                self,
                name,
                require_non_empty(getattr(self, name), name),
            )
        if not self.folds or self.dominant_direction not in {-1, 1}:
            raise ValueError("walk-forward candidate requires folds and direction")
        bounded = (
            self.direction_consistency,
            self.positive_fold_ratio,
            self.coverage_mean,
            self.coverage_min,
            self.horizon_sign_consistency,
            self.raw_hac_pvalue,
            self.bootstrap_pvalue,
            self.holm_adjusted_pvalue,
            self.bh_qvalue,
        )
        if any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in bounded
        ):
            raise ValueError("bounded robust metrics must be finite and in [0, 1]")
        numeric = (
            self.pooled_rank_ic,
            self.pooled_rank_icir,
            self.mean_fold_rank_icir,
            self.worst_fold_rank_icir,
            self.mean_fold_long_short_sharpe,
            self.worst_fold_long_short_sharpe,
            self.quantile_monotonicity,
            self.mean_one_way_turnover,
            self.hac_tstat,
            self.bootstrap_ci_lower,
            self.bootstrap_ci_upper,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("robust candidate metrics must be finite")
        if self.bootstrap_ci_upper < self.bootstrap_ci_lower:
            raise ValueError("invalid bootstrap confidence interval")

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "feature_digest": self.feature_digest,
            "folds": [fold.to_dict() for fold in self.folds],
            "dominant_direction": self.dominant_direction,
            "direction_consistency": self.direction_consistency,
            "pooled_rank_ic": self.pooled_rank_ic,
            "pooled_rank_icir": self.pooled_rank_icir,
            "mean_fold_rank_icir": self.mean_fold_rank_icir,
            "worst_fold_rank_icir": self.worst_fold_rank_icir,
            "positive_fold_ratio": self.positive_fold_ratio,
            "mean_fold_long_short_sharpe": self.mean_fold_long_short_sharpe,
            "worst_fold_long_short_sharpe": self.worst_fold_long_short_sharpe,
            "coverage_mean": self.coverage_mean,
            "coverage_min": self.coverage_min,
            "quantile_monotonicity": self.quantile_monotonicity,
            "mean_one_way_turnover": self.mean_one_way_turnover,
            "horizon_sign_consistency": self.horizon_sign_consistency,
            "hac": {
                "tstat": self.hac_tstat,
                "raw_pvalue": self.raw_hac_pvalue,
                "holm_adjusted_pvalue": self.holm_adjusted_pvalue,
                "bh_qvalue": self.bh_qvalue,
            },
            "block_bootstrap": {
                "pvalue": self.bootstrap_pvalue,
                "ci_lower": self.bootstrap_ci_lower,
                "ci_upper": self.bootstrap_ci_upper,
            },
        }


@dataclass(frozen=True, slots=True)
class AshareWalkForwardFamilyReport:
    program_spec_id: str
    data_version: str
    primary_label: str
    plan_id: str
    candidates: tuple[AshareWalkForwardCandidateReport, ...]
    factor_value_correlations: Mapping[str, float]

    def __post_init__(self) -> None:
        for name in (
            "program_spec_id",
            "data_version",
            "primary_label",
            "plan_id",
        ):
            object.__setattr__(
                self,
                name,
                require_non_empty(getattr(self, name), name),
            )
        if not self.candidates:
            raise ValueError("walk-forward family report requires candidates")
        digests = {candidate.feature_digest for candidate in self.candidates}
        if len(digests) != len(self.candidates):
            raise ValueError("walk-forward family report contains duplicate candidates")
        correlations = {
            str(key): float(value)
            for key, value in self.factor_value_correlations.items()
        }
        if any(
            not math.isfinite(value) or not -1.0 <= value <= 1.0
            for value in correlations.values()
        ):
            raise ValueError("factor correlations must be finite and in [-1, 1]")
        object.__setattr__(
            self,
            "factor_value_correlations",
            MappingProxyType(correlations),
        )

    @property
    def report_id(self) -> str:
        return _digest("ashare-walk-forward-report", self.to_dict(include_id=False))

    def candidate(self, digest: str) -> AshareWalkForwardCandidateReport:
        for candidate in self.candidates:
            if candidate.feature_digest == digest:
                return candidate
        raise KeyError(digest)

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.ashare-walk-forward-factor-report.v1",
            "program_spec_id": self.program_spec_id,
            "data_version": self.data_version,
            "primary_label": self.primary_label,
            "plan_id": self.plan_id,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "factor_value_correlations": dict(self.factor_value_correlations),
            "scope": "internal_walk_forward_development_only",
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


class AshareWalkForwardFactorAnalyzer:
    """Evaluate one immutable candidate family on expanding internal test folds."""

    VERSION = "ashare-walk-forward-factor-analyzer-v1"

    def __init__(
        self,
        *,
        adapter,
        materializer,
        program_spec: AshareResearchProgramSpec,
        requests: Mapping[str, DatasetRequest],
        factor_quant_config: FactorQuantConfig,
        hac_lags: int = 5,
        bootstrap_samples: int = 500,
        bootstrap_block_length: int = 20,
        bootstrap_seed: int = 20_260_828,
    ) -> None:
        self.adapter = adapter
        self.materializer = materializer
        self.program_spec = program_spec
        self.requests = MappingProxyType(dict(requests))
        self.factor_quant_config = factor_quant_config
        self.hac_lags = int(hac_lags)
        self.bootstrap_samples = int(bootstrap_samples)
        self.bootstrap_block_length = int(bootstrap_block_length)
        self.bootstrap_seed = int(bootstrap_seed)
        if self.bootstrap_samples < 100:
            raise ValueError("bootstrap_samples must be >= 100")
        required = set(program_spec.plan.split_ranges)
        if set(self.requests) != required:
            raise ValueError("walk-forward requests must exactly match plan split names")
        self._dataset_cache: dict[tuple[str, str], ResearchDataset] = {}

    def _analyzer(self, split_name: str) -> FactorQuantAnalyzer:
        return FactorQuantAnalyzer(
            self.adapter,
            config=replace(self.factor_quant_config, split_name=split_name),
            materializer=self.materializer,
        )

    def _dataset(
        self,
        artifact: GeneratedFeatureArtifact,
        split_name: str,
    ) -> ResearchDataset:
        key = (artifact.digest, split_name)
        if key not in self._dataset_cache:
            self._dataset_cache[key] = self.materializer.materialize(
                artifact,
                self.requests[split_name],
            )
        return self._dataset_cache[key]

    def _candidate_report(
        self,
        artifact: GeneratedFeatureArtifact,
        split_name: str,
    ) -> FactorQuantCandidateReport:
        analyzer = self._analyzer(split_name)
        return analyzer._candidate_report(
            artifact,
            self._dataset(artifact, split_name),
        )

    def _rank_ic_series(
        self,
        artifact: GeneratedFeatureArtifact,
        split_name: str,
        direction: int,
    ) -> np.ndarray:
        analyzer = self._analyzer(split_name)
        panel = self._dataset(artifact, split_name).get_split(split_name)
        factor = panel.feature_values[:, :, 0]
        labels = panel.label_panel(analyzer.config.primary_label)
        eligibility = np.asarray(panel.eligibility_mask, dtype=bool)
        output: list[float] = []
        for row in range(panel.n_times):
            mask = (
                eligibility[row]
                & np.isfinite(factor[row])
                & np.isfinite(labels[row])
            )
            if int(mask.sum()) < analyzer.config.min_cross_section:
                continue
            value = _safe_correlation(
                rankdata(factor[row][mask], method="average"),
                rankdata(labels[row][mask], method="average"),
            )
            if value is not None:
                output.append(direction * value)
        if len(output) < analyzer.config.min_periods:
            raise ValueError(
                f"factor has only {len(output)} internal OOS IC periods for "
                f"{split_name!r}"
            )
        return np.asarray(output, dtype=float)

    @staticmethod
    def _direction(candidate: FactorQuantCandidateReport) -> int:
        metric = candidate.primary.rank_ic
        if abs(metric) <= 1e-15:
            metric = candidate.primary.pearson_ic
        return 1 if metric >= 0 else -1

    @staticmethod
    def _oriented_monotonicity(
        candidate: FactorQuantCandidateReport,
        direction: int,
    ) -> float:
        values = candidate.quantile_diagnostics.quantile_mean_returns
        oriented = values if direction == 1 else tuple(reversed(values))
        return _monotonicity(oriented)

    def _candidate(
        self,
        artifact: GeneratedFeatureArtifact,
    ) -> AshareWalkForwardCandidateReport:
        fold_values: list[AshareWalkForwardFoldCandidate] = []
        rank_series: list[np.ndarray] = []
        directions: list[int] = []
        horizon_signs: list[float] = []

        for fold in self.program_spec.plan.folds:
            train = self._candidate_report(artifact, fold.train_split)
            test = self._candidate_report(artifact, fold.test_split)
            direction = self._direction(train)
            directions.append(direction)
            rank_series.append(
                self._rank_ic_series(artifact, fold.test_split, direction)
            )
            primary_sign = direction * test.primary.rank_ic
            for label_name, horizon in test.horizon_diagnostics.items():
                if label_name == test.primary_label:
                    continue
                horizon_signs.append(
                    1.0 if direction * horizon.rank_ic * primary_sign >= 0 else 0.0
                )
            quantile = test.quantile_diagnostics
            fold_values.append(
                AshareWalkForwardFoldCandidate(
                    fold_id=fold.fold_id,
                    train_direction=direction,
                    train_rank_ic=train.primary.rank_ic,
                    train_rank_icir=train.primary.rank_icir,
                    test_raw_rank_ic=test.primary.rank_ic,
                    test_raw_rank_icir=test.primary.rank_icir,
                    test_rank_ic=direction * test.primary.rank_ic,
                    test_rank_icir=direction * test.primary.rank_icir,
                    test_raw_long_short_sharpe=quantile.long_short_sharpe,
                    test_long_short_sharpe=direction * quantile.long_short_sharpe,
                    coverage=test.coverage,
                    quantile_monotonicity=self._oriented_monotonicity(
                        test,
                        direction,
                    ),
                    mean_one_way_turnover=quantile.mean_one_way_turnover,
                    periods=test.primary.periods,
                )
            )

        combined = np.concatenate(rank_series)
        direction_total = sum(directions)
        dominant_direction = 1 if direction_total >= 0 else -1
        direction_consistency = max(
            directions.count(1),
            directions.count(-1),
        ) / len(directions)
        fold_rank_icirs = np.asarray(
            [fold.test_rank_icir for fold in fold_values],
            dtype=float,
        )
        fold_sharpes = np.asarray(
            [fold.test_long_short_sharpe for fold in fold_values],
            dtype=float,
        )
        hac_tstat, hac_pvalue = _newey_west_mean_test(combined, self.hac_lags)
        seed_material = (
            f"{self.bootstrap_seed}:{self.program_spec.spec_id}:{artifact.digest}"
        )
        seed = int(hashlib.sha256(seed_material.encode()).hexdigest()[:16], 16)
        bootstrap_pvalue, ci_lower, ci_upper = _circular_block_bootstrap(
            combined,
            samples=self.bootstrap_samples,
            block_length=self.bootstrap_block_length,
            seed=seed,
        )
        return AshareWalkForwardCandidateReport(
            feature_id=artifact.spec.feature_id,
            feature_digest=artifact.digest,
            folds=tuple(fold_values),
            dominant_direction=dominant_direction,
            direction_consistency=float(direction_consistency),
            pooled_rank_ic=float(np.mean(combined)),
            pooled_rank_icir=_icir(combined),
            mean_fold_rank_icir=float(np.mean(fold_rank_icirs)),
            worst_fold_rank_icir=float(np.min(fold_rank_icirs)),
            positive_fold_ratio=float(np.mean(fold_rank_icirs > 0)),
            mean_fold_long_short_sharpe=float(np.mean(fold_sharpes)),
            worst_fold_long_short_sharpe=float(np.min(fold_sharpes)),
            coverage_mean=float(np.mean([fold.coverage for fold in fold_values])),
            coverage_min=float(np.min([fold.coverage for fold in fold_values])),
            quantile_monotonicity=float(
                np.mean([fold.quantile_monotonicity for fold in fold_values])
            ),
            mean_one_way_turnover=float(
                np.mean([fold.mean_one_way_turnover for fold in fold_values])
            ),
            horizon_sign_consistency=(
                float(np.mean(horizon_signs)) if horizon_signs else 1.0
            ),
            hac_tstat=hac_tstat,
            raw_hac_pvalue=hac_pvalue,
            bootstrap_pvalue=bootstrap_pvalue,
            bootstrap_ci_lower=ci_lower,
            bootstrap_ci_upper=ci_upper,
        )

    def _correlations(
        self,
        artifacts: Sequence[GeneratedFeatureArtifact],
    ) -> Mapping[str, float]:
        output: dict[str, float] = {}
        ordered = sorted(artifacts, key=lambda item: item.digest)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                values: list[float] = []
                for fold in self.program_spec.plan.folds:
                    analyzer = self._analyzer(fold.test_split)
                    value = analyzer._factor_value_correlation(
                        self._dataset(left, fold.test_split),
                        self._dataset(right, fold.test_split),
                        fold.test_split,
                        analyzer.config.min_cross_section,
                    )
                    values.append(value)
                output[f"{left.digest}|{right.digest}"] = float(np.mean(values))
        return MappingProxyType(output)

    def analyze(
        self,
        candidates: Sequence[GeneratedFeatureArtifact],
    ) -> AshareWalkForwardFamilyReport:
        artifacts = tuple(candidates)
        if not artifacts or len({artifact.digest for artifact in artifacts}) != len(
            artifacts
        ):
            raise ValueError("walk-forward analysis requires unique candidates")
        reports = [self._candidate(artifact) for artifact in artifacts]
        adjusted = adjust_family_pvalues(
            {candidate.feature_digest: candidate.raw_hac_pvalue for candidate in reports}
        )
        reports = [
            replace(
                candidate,
                holm_adjusted_pvalue=adjusted[candidate.feature_digest][0],
                bh_qvalue=adjusted[candidate.feature_digest][1],
            )
            for candidate in reports
        ]
        return AshareWalkForwardFamilyReport(
            program_spec_id=self.program_spec.spec_id,
            data_version=self.adapter.data_version,
            primary_label=self.factor_quant_config.primary_label,
            plan_id=self.program_spec.plan.plan_id,
            candidates=tuple(reports),
            factor_value_correlations=self._correlations(artifacts),
        )


@dataclass(frozen=True, slots=True)
class AshareRobustCandidateGateConfig:
    min_positive_fold_ratio: float = 0.75
    min_direction_consistency: float = 0.75
    min_pooled_rank_icir: float = 0.0
    min_mean_fold_rank_icir: float = 0.0
    min_worst_fold_rank_icir: float = -0.05
    min_mean_fold_long_short_sharpe: float = 0.0
    min_coverage: float = 0.90
    min_quantile_monotonicity: float = 0.25
    min_horizon_sign_consistency: float = 0.50
    max_hac_pvalue: float = 0.10
    max_bh_qvalue: float = 0.20
    max_mean_one_way_turnover: float = 1.0
    turnover_penalty: float = 0.5

    def __post_init__(self) -> None:
        bounded = (
            self.min_positive_fold_ratio,
            self.min_direction_consistency,
            self.min_coverage,
            self.min_quantile_monotonicity,
            self.min_horizon_sign_consistency,
            self.max_hac_pvalue,
            self.max_bh_qvalue,
        )
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in bounded):
            raise ValueError("bounded robust gate values must be in [0, 1]")
        if self.max_mean_one_way_turnover < 0 or self.turnover_penalty < 0:
            raise ValueError("turnover gate values must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "min_positive_fold_ratio": self.min_positive_fold_ratio,
            "min_direction_consistency": self.min_direction_consistency,
            "min_pooled_rank_icir": self.min_pooled_rank_icir,
            "min_mean_fold_rank_icir": self.min_mean_fold_rank_icir,
            "min_worst_fold_rank_icir": self.min_worst_fold_rank_icir,
            "min_mean_fold_long_short_sharpe": self.min_mean_fold_long_short_sharpe,
            "min_coverage": self.min_coverage,
            "min_quantile_monotonicity": self.min_quantile_monotonicity,
            "min_horizon_sign_consistency": self.min_horizon_sign_consistency,
            "max_hac_pvalue": self.max_hac_pvalue,
            "max_bh_qvalue": self.max_bh_qvalue,
            "max_mean_one_way_turnover": self.max_mean_one_way_turnover,
            "turnover_penalty": self.turnover_penalty,
        }


@dataclass(frozen=True, slots=True)
class AshareRobustCandidateGateEvaluation:
    feature_id: str
    feature_digest: str
    passed: bool
    reason_codes: tuple[str, ...]
    robust_score: float

    def __post_init__(self) -> None:
        for name in ("feature_id", "feature_digest"):
            object.__setattr__(
                self,
                name,
                require_non_empty(getattr(self, name), name),
            )
        if not math.isfinite(self.robust_score) or self.robust_score < 0:
            raise ValueError("robust_score must be finite and non-negative")
        if self.passed and self.reason_codes:
            raise ValueError("passed robust candidate cannot contain rejection reasons")
        if not self.passed and not self.reason_codes:
            raise ValueError("rejected robust candidate requires reasons")

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "feature_digest": self.feature_digest,
            "passed": self.passed,
            "reason_codes": list(self.reason_codes),
            "robust_score": self.robust_score,
        }


@dataclass(frozen=True, slots=True)
class AshareRobustCandidateGateReport:
    walk_forward_report_id: str
    config: AshareRobustCandidateGateConfig
    candidates: tuple[AshareRobustCandidateGateEvaluation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "walk_forward_report_id",
            require_non_empty(
                self.walk_forward_report_id,
                "walk_forward_report_id",
            ),
        )
        if not self.candidates:
            raise ValueError("robust gate report requires candidates")
        if len({candidate.feature_digest for candidate in self.candidates}) != len(
            self.candidates
        ):
            raise ValueError("robust gate report contains duplicate candidates")

    @property
    def gate_report_id(self) -> str:
        return _digest("ashare-robust-gate-report", self.to_dict(include_id=False))

    def candidate(self, digest: str) -> AshareRobustCandidateGateEvaluation:
        for candidate in self.candidates:
            if candidate.feature_digest == digest:
                return candidate
        raise KeyError(digest)

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.ashare-robust-candidate-gate.v1",
            "walk_forward_report_id": self.walk_forward_report_id,
            "config": self.config.to_dict(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "scope": "preregistered_internal_walk_forward_rejection_gate",
        }
        if include_id:
            payload["gate_report_id"] = self.gate_report_id
        return payload


class AshareRobustCandidateGate:
    def __init__(
        self,
        config: AshareRobustCandidateGateConfig = AshareRobustCandidateGateConfig(),
    ) -> None:
        self.config = config

    def _evaluate(
        self,
        candidate: AshareWalkForwardCandidateReport,
    ) -> AshareRobustCandidateGateEvaluation:
        config = self.config
        reasons: list[str] = []
        checks = (
            (
                candidate.positive_fold_ratio >= config.min_positive_fold_ratio,
                "POSITIVE_FOLD_RATIO_BELOW_THRESHOLD",
            ),
            (
                candidate.direction_consistency >= config.min_direction_consistency,
                "TRAIN_DIRECTION_UNSTABLE",
            ),
            (
                candidate.pooled_rank_icir >= config.min_pooled_rank_icir,
                "POOLED_RANK_ICIR_BELOW_THRESHOLD",
            ),
            (
                candidate.mean_fold_rank_icir >= config.min_mean_fold_rank_icir,
                "MEAN_FOLD_RANK_ICIR_BELOW_THRESHOLD",
            ),
            (
                candidate.worst_fold_rank_icir >= config.min_worst_fold_rank_icir,
                "WORST_FOLD_RANK_ICIR_BELOW_THRESHOLD",
            ),
            (
                candidate.mean_fold_long_short_sharpe
                >= config.min_mean_fold_long_short_sharpe,
                "MEAN_FOLD_LONG_SHORT_SHARPE_BELOW_THRESHOLD",
            ),
            (
                candidate.coverage_min >= config.min_coverage,
                "COVERAGE_BELOW_THRESHOLD",
            ),
            (
                candidate.quantile_monotonicity
                >= config.min_quantile_monotonicity,
                "QUANTILE_MONOTONICITY_BELOW_THRESHOLD",
            ),
            (
                candidate.horizon_sign_consistency
                >= config.min_horizon_sign_consistency,
                "HORIZON_SIGN_INCONSISTENT",
            ),
            (
                candidate.raw_hac_pvalue <= config.max_hac_pvalue,
                "HAC_NOT_SIGNIFICANT",
            ),
            (
                candidate.bh_qvalue <= config.max_bh_qvalue,
                "BH_QVALUE_ABOVE_THRESHOLD",
            ),
            (
                candidate.mean_one_way_turnover
                <= config.max_mean_one_way_turnover,
                "TURNOVER_ABOVE_THRESHOLD",
            ),
        )
        reasons.extend(code for passed, code in checks if not passed)
        passed = not reasons
        if not passed:
            score = 0.0
        else:
            score = (
                max(candidate.pooled_rank_icir, 1e-12)
                * candidate.positive_fold_ratio
                * candidate.direction_consistency
                * (0.5 + 0.5 * max(0.0, candidate.quantile_monotonicity))
                * math.sqrt(max(candidate.coverage_mean, 1e-12))
                * (1.0 - 0.5 * candidate.bh_qvalue)
                / (
                    1.0
                    + config.turnover_penalty
                    * candidate.mean_one_way_turnover
                )
            )
        return AshareRobustCandidateGateEvaluation(
            feature_id=candidate.feature_id,
            feature_digest=candidate.feature_digest,
            passed=passed,
            reason_codes=tuple(reasons),
            robust_score=float(score),
        )

    def evaluate(
        self,
        report: AshareWalkForwardFamilyReport,
    ) -> AshareRobustCandidateGateReport:
        return AshareRobustCandidateGateReport(
            walk_forward_report_id=report.report_id,
            config=self.config,
            candidates=tuple(self._evaluate(candidate) for candidate in report.candidates),
        )


@dataclass(frozen=True, slots=True)
class AshareRobustSelectorConfig:
    max_factors: int = 3
    max_abs_factor_correlation: float = 0.85
    quality_power: float = 1.0

    def __post_init__(self) -> None:
        if self.max_factors < 1:
            raise ValueError("max_factors must be >= 1")
        if not 0.0 <= self.max_abs_factor_correlation <= 1.0:
            raise ValueError("max_abs_factor_correlation must be in [0, 1]")
        if self.quality_power <= 0:
            raise ValueError("quality_power must be > 0")

    def to_dict(self) -> dict[str, object]:
        return {
            "max_factors": self.max_factors,
            "max_abs_factor_correlation": self.max_abs_factor_correlation,
            "quality_power": self.quality_power,
        }


@dataclass(frozen=True, slots=True)
class AshareRobustFactorComponent:
    feature_id: str
    feature_digest: str
    direction: int
    robust_score: float
    weight: float

    def __post_init__(self) -> None:
        for name in ("feature_id", "feature_digest"):
            object.__setattr__(
                self,
                name,
                require_non_empty(getattr(self, name), name),
            )
        if self.direction not in {-1, 1}:
            raise ValueError("robust factor direction must be -1 or 1")
        if (
            not math.isfinite(self.robust_score)
            or not math.isfinite(self.weight)
            or self.robust_score < 0
            or self.weight < 0
        ):
            raise ValueError("robust component metrics must be finite and non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "feature_digest": self.feature_digest,
            "direction": self.direction,
            "robust_score": self.robust_score,
            "weight": self.weight,
        }


@dataclass(frozen=True, slots=True)
class AshareRobustFactorSelection:
    walk_forward_report_id: str
    gate_report_id: str
    status: str
    config: AshareRobustSelectorConfig
    components: tuple[AshareRobustFactorComponent, ...]

    def __post_init__(self) -> None:
        for name in ("walk_forward_report_id", "gate_report_id", "status"):
            object.__setattr__(
                self,
                name,
                require_non_empty(getattr(self, name), name),
            )
        if self.status not in {
            "ROBUST_FACTOR_FAMILY_FROZEN",
            "NO_ROBUST_FACTOR_FOUND",
        }:
            raise ValueError("invalid robust factor selection status")
        if self.status == "NO_ROBUST_FACTOR_FOUND" and self.components:
            raise ValueError("no-alpha selection cannot contain components")
        if self.status == "ROBUST_FACTOR_FAMILY_FROZEN":
            if not self.components:
                raise ValueError("frozen robust family requires components")
            if abs(sum(component.weight for component in self.components) - 1.0) > 1e-9:
                raise ValueError("robust factor weights must sum to one")

    @property
    def selection_id(self) -> str:
        return _digest("ashare-robust-factor-selection", self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.ashare-robust-factor-selection.v1",
            "walk_forward_report_id": self.walk_forward_report_id,
            "gate_report_id": self.gate_report_id,
            "status": self.status,
            "config": self.config.to_dict(),
            "components": [component.to_dict() for component in self.components],
            "selection_semantics": (
                "internal walk-forward evidence only; empty selection is valid"
            ),
        }
        if include_id:
            payload["selection_id"] = self.selection_id
        return payload


class AshareRobustFactorSelector:
    def __init__(
        self,
        config: AshareRobustSelectorConfig = AshareRobustSelectorConfig(),
    ) -> None:
        self.config = config

    @staticmethod
    def _correlation(
        report: AshareWalkForwardFamilyReport,
        left: str,
        right: str,
    ) -> float:
        if left == right:
            return 1.0
        return float(
            report.factor_value_correlations.get(
                "|".join(sorted((left, right))),
                0.0,
            )
        )

    def select(
        self,
        report: AshareWalkForwardFamilyReport,
        gate: AshareRobustCandidateGateReport,
    ) -> AshareRobustFactorSelection:
        if gate.walk_forward_report_id != report.report_id:
            raise ValueError("robust gate does not belong to walk-forward report")
        ranked = sorted(
            (
                (evaluation.robust_score, report.candidate(evaluation.feature_digest))
                for evaluation in gate.candidates
                if evaluation.passed
            ),
            key=lambda item: (-item[0], item[1].feature_digest),
        )
        if not ranked:
            return AshareRobustFactorSelection(
                walk_forward_report_id=report.report_id,
                gate_report_id=gate.gate_report_id,
                status="NO_ROBUST_FACTOR_FOUND",
                config=self.config,
                components=(),
            )
        selected: list[tuple[float, AshareWalkForwardCandidateReport]] = []
        for score, candidate in ranked:
            if len(selected) >= self.config.max_factors:
                break
            if any(
                abs(
                    self._correlation(
                        report,
                        candidate.feature_digest,
                        chosen.feature_digest,
                    )
                )
                > self.config.max_abs_factor_correlation
                for _, chosen in selected
            ):
                continue
            selected.append((score, candidate))
        if not selected:
            return AshareRobustFactorSelection(
                walk_forward_report_id=report.report_id,
                gate_report_id=gate.gate_report_id,
                status="NO_ROBUST_FACTOR_FOUND",
                config=self.config,
                components=(),
            )
        masses = np.asarray(
            [
                max(score, 1e-12) ** self.config.quality_power
                for score, _ in selected
            ],
            dtype=float,
        )
        masses /= float(masses.sum())
        return AshareRobustFactorSelection(
            walk_forward_report_id=report.report_id,
            gate_report_id=gate.gate_report_id,
            status="ROBUST_FACTOR_FAMILY_FROZEN",
            config=self.config,
            components=tuple(
                AshareRobustFactorComponent(
                    feature_id=candidate.feature_id,
                    feature_digest=candidate.feature_digest,
                    direction=candidate.dominant_direction,
                    robust_score=float(score),
                    weight=float(masses[index]),
                )
                for index, (score, candidate) in enumerate(selected)
            ),
        )


@dataclass(frozen=True, slots=True)
class AshareRobustResearchProgramResult:
    mode: str
    program_spec: AshareResearchProgramSpec
    candidates: tuple[GeneratedFeatureArtifact, ...]
    walk_forward_report: AshareWalkForwardFamilyReport
    gate_report: AshareRobustCandidateGateReport
    frozen_selection: AshareRobustFactorSelection
    program_status: str
    discovery: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"deterministic", "agent", "replay"}:
            raise ValueError("invalid robust research mode")
        digests = {candidate.digest for candidate in self.candidates}
        if not digests or digests != {
            candidate.feature_digest
            for candidate in self.walk_forward_report.candidates
        }:
            raise ValueError("walk-forward denominator differs from candidates")
        if digests != {
            candidate.feature_digest for candidate in self.gate_report.candidates
        }:
            raise ValueError("gate denominator differs from candidates")
        if not {
            component.feature_digest for component in self.frozen_selection.components
        }.issubset(digests):
            raise ValueError("robust selection references candidate outside denominator")
        object.__setattr__(
            self,
            "program_status",
            require_non_empty(self.program_status, "program_status"),
        )
        object.__setattr__(
            self,
            "discovery",
            MappingProxyType(dict(self.discovery))
            if self.discovery is not None
            else None,
        )

    @property
    def result_id(self) -> str:
        return _digest(
            "ashare-robust-program-result",
            self.to_dict(include_id=False, include_mode=False),
        )

    @property
    def research_status(self) -> str:
        return self.frozen_selection.status

    def to_dict(
        self,
        *,
        include_id: bool = True,
        include_mode: bool = True,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.ashare-robust-research-program.v1",
            "scope": (
                "A2.6 internal expanding walk-forward factor research only; "
                "no reserve consumption, execution, promotion, PAPER or realtime claim"
            ),
            "system_acceptance": {"passed": True, "status": "PASS"},
            "research_outcome": {
                "status": self.research_status,
                "robust_factor_count": len(self.frozen_selection.components),
                "promotion_eligible": False,
                "reason_codes": (
                    ["NO_CANDIDATE_PASSED_PREREGISTERED_GATE"]
                    if not self.frozen_selection.components
                    else ["A_SHARE_EXECUTION_NOT_CERTIFIED"]
                ),
            },
            "program_spec": self.program_spec.to_dict(),
            "program_status": self.program_status,
            "data_version": self.program_spec.data_version,
            "candidate_denominator": [
                {
                    "feature_id": artifact.spec.feature_id,
                    "feature_digest": artifact.digest,
                    "hypothesis": artifact.spec.hypothesis,
                    "input_fields": list(artifact.spec.input_fields),
                    "lookback": artifact.spec.lookback,
                    "generator_id": artifact.generator_id,
                }
                for artifact in self.candidates
            ],
            "walk_forward_report": self.walk_forward_report.to_dict(),
            "gate_report": self.gate_report.to_dict(),
            "frozen_selection": self.frozen_selection.to_dict(),
            "reserve": {
                "reserve_id": self.program_spec.reserve_id,
                "start": self.program_spec.plan.reserve.start.isoformat(),
                "end": self.program_spec.plan.reserve.end.isoformat(),
                "status": "untouched",
            },
            "discovery": (
                dict(self.discovery) if self.discovery is not None else None
            ),
        }
        if include_mode:
            payload["mode"] = self.mode
        if include_id:
            payload["program_result_id"] = self.result_id
        return payload

    def write_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                self.to_dict(),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return target

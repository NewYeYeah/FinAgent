from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Sequence

import numpy as np
from numpy.typing import NDArray
from scipy.stats import kurtosis, skew

from finagent.domain.experiment_family import CorrectionMethod

FloatArray = NDArray[np.float64]
_STD_NORMAL = NormalDist()
_EULER_GAMMA = 0.5772156649015329


def _as_finite_vector(values: Sequence[float], name: str) -> FloatArray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"{name} must be a non-empty one-dimensional sequence")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain only finite values")
    return array


def _as_return_matrix(values: object) -> FloatArray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 2 or min(array.shape) < 2:
        raise ValueError("returns must have shape (time, strategy) with both dimensions >= 2")
    if not np.isfinite(array).all():
        raise ValueError("returns must contain only finite values")
    return array


@dataclass(frozen=True, slots=True)
class MultipleTestingResult:
    method: CorrectionMethod
    alpha: float
    raw_pvalues: tuple[float, ...]
    adjusted_pvalues: tuple[float, ...]
    rejected: tuple[bool, ...]


@dataclass(frozen=True, slots=True)
class DeflatedSharpeResult:
    observed_sharpe: float
    benchmark_sharpe: float
    deflated_probability: float
    sample_size: int
    n_trials: int
    skewness: float
    kurtosis: float


@dataclass(frozen=True, slots=True)
class PBOResult:
    probability_of_backtest_overfitting: float
    logits: tuple[float, ...]
    combinations_evaluated: int
    blocks: int


@dataclass(frozen=True, slots=True)
class RealityCheckResult:
    observed_statistic: float
    pvalue: float
    bootstrap_samples: int
    block_size: int


def adjust_pvalues(
    pvalues: Sequence[float],
    *,
    method: CorrectionMethod | str = CorrectionMethod.HOLM,
    alpha: float = 0.05,
) -> MultipleTestingResult:
    """Adjust a family of p-values using a pre-declared multiplicity procedure."""

    p = _as_finite_vector(pvalues, "pvalues")
    if np.any((p < 0.0) | (p > 1.0)):
        raise ValueError("pvalues must be in [0, 1]")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be strictly between 0 and 1")
    method = CorrectionMethod(method)
    m = p.size

    if method is CorrectionMethod.BONFERRONI:
        adjusted = np.minimum(1.0, p * m)
    elif method is CorrectionMethod.HOLM:
        order = np.argsort(p)
        ranked = p[order]
        adjusted_ranked = np.maximum.accumulate((m - np.arange(m)) * ranked)
        adjusted_ranked = np.minimum(1.0, adjusted_ranked)
        adjusted = np.empty_like(adjusted_ranked)
        adjusted[order] = adjusted_ranked
    elif method is CorrectionMethod.BENJAMINI_HOCHBERG:
        order = np.argsort(p)
        ranked = p[order]
        adjusted_ranked = ranked * m / np.arange(1, m + 1)
        adjusted_ranked = np.minimum.accumulate(adjusted_ranked[::-1])[::-1]
        adjusted_ranked = np.minimum(1.0, adjusted_ranked)
        adjusted = np.empty_like(adjusted_ranked)
        adjusted[order] = adjusted_ranked
    else:  # pragma: no cover - enum exhaustiveness
        raise ValueError(method)

    rejected = adjusted <= alpha
    return MultipleTestingResult(
        method=method,
        alpha=float(alpha),
        raw_pvalues=tuple(float(x) for x in p),
        adjusted_pvalues=tuple(float(x) for x in adjusted),
        rejected=tuple(bool(x) for x in rejected),
    )


def sharpe_ratio(returns: Sequence[float]) -> float:
    values = _as_finite_vector(returns, "returns")
    if values.size < 2:
        raise ValueError("at least two return observations are required")
    std = float(np.std(values, ddof=1))
    if std == 0.0:
        return math.inf if float(np.mean(values)) > 0.0 else 0.0
    return float(np.mean(values) / std)


def expected_maximum_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """Approximate E[max Sharpe] under a zero-mean independent-trial null."""

    if isinstance(n_trials, bool) or n_trials < 1:
        raise ValueError("n_trials must be an integer >= 1")
    if not math.isfinite(sharpe_variance) or sharpe_variance < 0.0:
        raise ValueError("sharpe_variance must be finite and >= 0")
    if n_trials == 1 or sharpe_variance == 0.0:
        return 0.0
    first = _STD_NORMAL.inv_cdf(1.0 - 1.0 / n_trials)
    second = _STD_NORMAL.inv_cdf(1.0 - 1.0 / (n_trials * math.e))
    return math.sqrt(sharpe_variance) * ((1.0 - _EULER_GAMMA) * first + _EULER_GAMMA * second)


def deflated_sharpe_ratio(
    returns: Sequence[float],
    *,
    n_trials: int,
    trial_sharpes: Sequence[float] | None = None,
    benchmark_sharpe: float | None = None,
) -> DeflatedSharpeResult:
    """Compute the Bailey/López de Prado deflated Sharpe probability.

    Sharpe ratios here are per-observation (not annualized).  If a benchmark is not
    supplied, the expected maximum null Sharpe is estimated from the variance of the
    declared trial Sharpes.  The number of trials must reflect the whole experiment
    family, not only the final selected strategy.
    """

    values = _as_finite_vector(returns, "returns")
    if values.size < 3:
        raise ValueError("deflated Sharpe requires at least three observations")
    if isinstance(n_trials, bool) or n_trials < 1:
        raise ValueError("n_trials must be an integer >= 1")
    observed = sharpe_ratio(values)
    if not math.isfinite(observed):
        observed = float(np.sign(np.mean(values)) * 1e12)

    if benchmark_sharpe is None:
        if trial_sharpes is None:
            variance = 0.0
        else:
            trial_values = _as_finite_vector(trial_sharpes, "trial_sharpes")
            variance = float(np.var(trial_values, ddof=1)) if trial_values.size > 1 else 0.0
        benchmark = expected_maximum_sharpe(n_trials, variance)
    else:
        if not math.isfinite(benchmark_sharpe):
            raise ValueError("benchmark_sharpe must be finite")
        benchmark = float(benchmark_sharpe)

    sample_skew = float(skew(values, bias=False))
    sample_kurtosis = float(kurtosis(values, fisher=False, bias=False))
    denominator_sq = (
        1.0
        - sample_skew * observed
        + ((sample_kurtosis - 1.0) / 4.0) * observed * observed
    )
    denominator_sq = max(denominator_sq, np.finfo(float).eps)
    z = (observed - benchmark) * math.sqrt(values.size - 1) / math.sqrt(denominator_sq)
    probability = _STD_NORMAL.cdf(z)
    return DeflatedSharpeResult(
        observed_sharpe=float(observed),
        benchmark_sharpe=float(benchmark),
        deflated_probability=float(probability),
        sample_size=int(values.size),
        n_trials=int(n_trials),
        skewness=sample_skew,
        kurtosis=sample_kurtosis,
    )


def _strategy_metric(block: FloatArray) -> FloatArray:
    means = np.mean(block, axis=0)
    stds = np.std(block, axis=0, ddof=1)
    return np.divide(means, stds, out=np.zeros_like(means), where=stds > 0)


def probability_of_backtest_overfitting(
    returns: object,
    *,
    blocks: int = 8,
    max_combinations: int = 10_000,
) -> PBOResult:
    """Estimate PBO using combinatorially symmetric cross-validation (CSCV).

    The input matrix has one column per fully specified strategy/trial.  Rows are split
    into contiguous blocks; for each half-block combination the best in-sample strategy
    is ranked out-of-sample.  PBO is the fraction with an OOS rank below the median.
    """

    matrix = _as_return_matrix(returns)
    if blocks < 4 or blocks % 2:
        raise ValueError("blocks must be an even integer >= 4")
    if blocks > matrix.shape[0]:
        raise ValueError("blocks cannot exceed the number of return observations")
    if max_combinations <= 0:
        raise ValueError("max_combinations must be >= 1")

    block_indices = tuple(
        np.asarray(index, dtype=int)
        for index in np.array_split(np.arange(matrix.shape[0]), blocks)
    )
    combos = list(itertools.combinations(range(blocks), blocks // 2))
    # Symmetric pairs are duplicates.  Keep one canonical representative.
    combos = [combo for combo in combos if 0 in combo]
    if len(combos) > max_combinations:
        positions = np.linspace(0, len(combos) - 1, max_combinations, dtype=int)
        combos = [combos[i] for i in positions]

    logits: list[float] = []
    all_blocks = set(range(blocks))
    n_strategies = matrix.shape[1]
    for combo in combos:
        is_rows = np.concatenate([block_indices[i] for i in combo])
        oos_blocks = sorted(all_blocks - set(combo))
        oos_rows = np.concatenate([block_indices[i] for i in oos_blocks])
        is_metric = _strategy_metric(matrix[is_rows])
        best = int(np.argmax(is_metric))
        oos_metric = _strategy_metric(matrix[oos_rows])
        # Percentile in (0, 1): 1 is best, values below 0.5 indicate poor OOS rank.
        less = int(np.sum(oos_metric < oos_metric[best]))
        equal = int(np.sum(oos_metric == oos_metric[best]))
        rank_fraction = (less + 0.5 * equal) / n_strategies
        eps = 0.5 / n_strategies
        omega = min(1.0 - eps, max(eps, rank_fraction))
        logits.append(float(math.log(omega / (1.0 - omega))))

    pbo = float(np.mean(np.asarray(logits) <= 0.0))
    return PBOResult(
        probability_of_backtest_overfitting=pbo,
        logits=tuple(logits),
        combinations_evaluated=len(logits),
        blocks=blocks,
    )


def _circular_block_indices(
    n: int,
    *,
    block_size: int,
    rng: np.random.Generator,
) -> NDArray[np.int64]:
    starts = rng.integers(0, n, size=math.ceil(n / block_size))
    pieces = [((start + np.arange(block_size)) % n) for start in starts]
    return np.concatenate(pieces)[:n].astype(np.int64, copy=False)


def whites_reality_check(
    returns: object,
    *,
    bootstrap_samples: int = 1000,
    block_size: int | None = None,
    seed: int = 0,
) -> RealityCheckResult:
    """White-style reality check for the best mean return in a strategy family.

    A circular moving-block bootstrap is applied to column-wise demeaned returns, so
    temporal dependence and contemporaneous dependence across trials are retained.
    """

    matrix = _as_return_matrix(returns)
    n = matrix.shape[0]
    if bootstrap_samples <= 0:
        raise ValueError("bootstrap_samples must be >= 1")
    if block_size is None:
        block_size = max(1, int(round(n ** (1.0 / 3.0))))
    if block_size <= 0 or block_size > n:
        raise ValueError("block_size must be in [1, n_observations]")

    scale = math.sqrt(n)
    observed = float(np.max(scale * np.mean(matrix, axis=0)))
    centered = matrix - np.mean(matrix, axis=0, keepdims=True)
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(bootstrap_samples):
        idx = _circular_block_indices(n, block_size=block_size, rng=rng)
        statistic = float(np.max(scale * np.mean(centered[idx], axis=0)))
        if statistic >= observed:
            exceed += 1
    pvalue = (exceed + 1.0) / (bootstrap_samples + 1.0)
    return RealityCheckResult(
        observed_statistic=observed,
        pvalue=float(pvalue),
        bootstrap_samples=int(bootstrap_samples),
        block_size=int(block_size),
    )


@dataclass(frozen=True, slots=True)
class FamilyValidationReport:
    selected_index: int
    multiple_testing: MultipleTestingResult
    deflated_sharpe: DeflatedSharpeResult
    pbo: PBOResult
    reality_check: RealityCheckResult
    passed: bool


def validate_experiment_family(
    returns: object,
    pvalues: Sequence[float],
    *,
    selected_index: int,
    correction_method: CorrectionMethod | str = CorrectionMethod.HOLM,
    alpha: float = 0.05,
    dsr_probability_threshold: float = 0.95,
    pbo_threshold: float = 0.5,
    pbo_blocks: int = 8,
    bootstrap_samples: int = 1000,
    bootstrap_block_size: int | None = None,
    seed: int = 0,
) -> FamilyValidationReport:
    """Apply the Phase 2.5 family-level validation gate to one selected trial.

    Passing requires the selected hypothesis to survive the declared p-value correction,
    reach the deflated-Sharpe probability threshold, remain below the PBO threshold, and
    pass the family-level White reality check.  The function intentionally exposes all
    components instead of collapsing them into an opaque score.
    """

    matrix = _as_return_matrix(returns)
    if selected_index < 0 or selected_index >= matrix.shape[1]:
        raise IndexError("selected_index is outside the strategy columns")
    p = _as_finite_vector(pvalues, "pvalues")
    if p.size != matrix.shape[1]:
        raise ValueError("pvalues must have one entry per strategy column")
    if not 0.0 < dsr_probability_threshold < 1.0:
        raise ValueError("dsr_probability_threshold must be in (0, 1)")
    if not 0.0 <= pbo_threshold <= 1.0:
        raise ValueError("pbo_threshold must be in [0, 1]")

    multiple = adjust_pvalues(p, method=correction_method, alpha=alpha)
    trial_sharpes = tuple(sharpe_ratio(matrix[:, idx]) for idx in range(matrix.shape[1]))
    dsr = deflated_sharpe_ratio(
        matrix[:, selected_index],
        n_trials=matrix.shape[1],
        trial_sharpes=trial_sharpes,
    )
    pbo = probability_of_backtest_overfitting(matrix, blocks=pbo_blocks)
    reality = whites_reality_check(
        matrix,
        bootstrap_samples=bootstrap_samples,
        block_size=bootstrap_block_size,
        seed=seed,
    )
    passed = (
        multiple.rejected[selected_index]
        and dsr.deflated_probability >= dsr_probability_threshold
        and pbo.probability_of_backtest_overfitting <= pbo_threshold
        and reality.pvalue <= alpha
    )
    return FamilyValidationReport(
        selected_index=int(selected_index),
        multiple_testing=multiple,
        deflated_sharpe=dsr,
        pbo=pbo,
        reality_check=reality,
        passed=bool(passed),
    )

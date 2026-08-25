from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

import numpy as np


class SignalPrimitive(str, Enum):
    MOMENTUM = "momentum"
    SHORT_TERM_REVERSAL = "short_term_reversal"
    VOLATILITY = "volatility"
    ZSCORE = "zscore"
    WINSORIZE = "winsorize"
    NEUTRALIZE = "neutralize"
    VOLATILITY_SCALE = "volatility_scale"


def _array(values: Sequence[float], *, name: str) -> np.ndarray:
    result = np.asarray(values, dtype=float)
    if result.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    return result


def momentum(prices: Sequence[float], lookback: int, *, skip: int = 0) -> float:
    """Simple trailing price momentum using only the supplied historical window."""
    values = _array(prices, name="prices")
    if lookback < 1 or skip < 0:
        raise ValueError("lookback must be >= 1 and skip must be >= 0")
    end = len(values) - 1 - skip
    start = end - lookback
    if start < 0 or end < 0:
        raise ValueError("insufficient price history for requested momentum")
    if not np.isfinite(values[start]) or not np.isfinite(values[end]) or values[start] <= 0:
        return float("nan")
    return float(values[end] / values[start] - 1.0)


def short_term_reversal(returns: Sequence[float], lookback: int = 5) -> float:
    """Negative cumulative recent return, a canonical short-horizon reversal signal."""
    values = _array(returns, name="returns")
    if lookback < 1 or len(values) < lookback:
        raise ValueError("insufficient return history for requested reversal")
    tail = values[-lookback:]
    if not np.all(np.isfinite(tail)):
        return float("nan")
    return -float(np.prod(1.0 + tail) - 1.0)


def rolling_volatility(
    returns: Sequence[float],
    lookback: int = 20,
    *,
    annualization: int = 252,
) -> float:
    values = _array(returns, name="returns")
    if lookback < 2 or len(values) < lookback:
        raise ValueError("rolling volatility requires at least two observations")
    tail = values[-lookback:]
    if not np.all(np.isfinite(tail)):
        return float("nan")
    return float(np.std(tail, ddof=1) * np.sqrt(annualization))


def winsorize_cross_section(
    values: Sequence[float],
    *,
    lower_quantile: float = 0.01,
    upper_quantile: float = 0.99,
    eligible: Sequence[bool] | None = None,
) -> np.ndarray:
    array = _array(values, name="values").copy()
    if not 0.0 <= lower_quantile < upper_quantile <= 1.0:
        raise ValueError("invalid winsorization quantiles")
    mask = np.isfinite(array)
    if eligible is not None:
        eligible_array = np.asarray(eligible, dtype=bool)
        if eligible_array.shape != array.shape:
            raise ValueError("eligible mask shape mismatch")
        mask &= eligible_array
    chosen = array[mask]
    if chosen.size == 0:
        return array
    lower, upper = np.quantile(chosen, [lower_quantile, upper_quantile])
    array[mask] = np.clip(array[mask], lower, upper)
    return array


def cross_sectional_zscore(
    values: Sequence[float],
    *,
    eligible: Sequence[bool] | None = None,
) -> np.ndarray:
    array = _array(values, name="values")
    result = np.full_like(array, np.nan, dtype=float)
    mask = np.isfinite(array)
    if eligible is not None:
        eligible_array = np.asarray(eligible, dtype=bool)
        if eligible_array.shape != array.shape:
            raise ValueError("eligible mask shape mismatch")
        mask &= eligible_array
    chosen = array[mask]
    if chosen.size < 2:
        return result
    std = float(np.std(chosen, ddof=1))
    if std <= 1e-15:
        result[mask] = 0.0
    else:
        result[mask] = (chosen - float(np.mean(chosen))) / std
    return result


def neutralize_linear(
    signal: Sequence[float],
    exposures: Sequence[Sequence[float]],
    *,
    eligible: Sequence[bool] | None = None,
    add_intercept: bool = True,
) -> np.ndarray:
    """Cross-sectional OLS residualization for beta/group/style neutralization."""
    y = _array(signal, name="signal")
    x = np.asarray(exposures, dtype=float)
    if x.ndim == 1:
        x = x[:, None]
    if x.ndim != 2 or x.shape[0] != y.shape[0]:
        raise ValueError("exposures must have shape (asset, factor)")
    mask = np.isfinite(y) & np.all(np.isfinite(x), axis=1)
    if eligible is not None:
        eligible_array = np.asarray(eligible, dtype=bool)
        if eligible_array.shape != y.shape:
            raise ValueError("eligible mask shape mismatch")
        mask &= eligible_array
    result = np.full_like(y, np.nan, dtype=float)
    if int(mask.sum()) <= x.shape[1] + int(add_intercept):
        return result
    design = x[mask]
    if add_intercept:
        design = np.column_stack((np.ones(len(design)), design))
    beta, *_ = np.linalg.lstsq(design, y[mask], rcond=None)
    result[mask] = y[mask] - design @ beta
    return result


def volatility_scale(
    signal: Sequence[float],
    volatility: Sequence[float],
    *,
    floor: float = 1e-4,
) -> np.ndarray:
    signal_array = _array(signal, name="signal")
    vol = _array(volatility, name="volatility")
    if signal_array.shape != vol.shape:
        raise ValueError("signal and volatility must be aligned")
    if floor <= 0:
        raise ValueError("floor must be > 0")
    result = np.full_like(signal_array, np.nan, dtype=float)
    mask = np.isfinite(signal_array) & np.isfinite(vol) & (vol >= 0)
    result[mask] = signal_array[mask] / np.maximum(vol[mask], floor)
    return result


@dataclass(frozen=True, slots=True)
class CanonicalSignalSpec:
    """Small typed vocabulary for deterministic research-template construction."""

    primitive: SignalPrimitive
    lookback: int = 20
    skip: int = 0

    def __post_init__(self) -> None:
        if self.lookback < 1 or self.skip < 0:
            raise ValueError("invalid signal lookback/skip")

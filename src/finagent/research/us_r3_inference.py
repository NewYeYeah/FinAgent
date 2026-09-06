"""R3 design and descriptive inference; independence is a separate admission."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from statistics import NormalDist


@dataclass(frozen=True)
class EvidenceDesign:
    effect_bps: float = 5.0
    planning_daily_sigma_bps: float = 50.0
    planning_ar1: float = 0.2
    family_size: int = 72
    family_alpha: float = 0.05
    power: float = 0.8
    hac_lags: int = 5
    bootstrap_block: int = 5
    bootstrap_draws: int = 999
    seed: int = 20260906

    def __post_init__(self) -> None:
        if not all(
            math.isfinite(x)
            for x in (
                self.effect_bps,
                self.planning_daily_sigma_bps,
                self.planning_ar1,
                self.family_alpha,
                self.power,
            )
        ):
            raise ValueError("finite design parameters required")
        if (
            self.effect_bps <= 0
            or self.planning_daily_sigma_bps <= 0
            or not 0 <= self.planning_ar1 < 1
        ):
            raise ValueError("invalid effect/variance/dependence")
        if (
            type(self.family_size) is not int
            or self.family_size < 1
            or not 0 < self.family_alpha < 0.5
            or not 0.5 < self.power < 1
        ):
            raise ValueError("invalid multiplicity/power")
        if any(
            type(x) is not int or x < 1
            for x in (self.hac_lags, self.bootstrap_block, self.bootstrap_draws)
        ):
            raise ValueError("positive integer inference settings required")

    def to_dict(self) -> dict[str, object]:
        z = NormalDist().inv_cdf(1 - self.family_alpha / self.family_size)
        effective = math.ceil(
            (
                (z + NormalDist().inv_cdf(self.power))
                * self.planning_daily_sigma_bps
                / self.effect_bps
            )
            ** 2
        )
        return {
            **asdict(self),
            "minimum_effective_sessions": effective,
            "planning_calendar_sessions": math.ceil(
                effective * (1 + self.planning_ar1) / (1 - self.planning_ar1)
            ),
            "endpoint": "paired daily net return vs cash and eligible equal-weight; primary 5bp gross-traded-notional cost",
            "approximation": "one-sided normal design with specified sigma and AR(1); not a guarantee of power",
            "stopping": "one fixed sample endpoint; no optional peeking or extension based on outcome",
        }


def describe_returns(
    values: Sequence[float | None], design: EvidenceDesign, *, paired: bool = False
) -> dict[str, object]:
    """Whole calendar denominator, Bartlett HAC and circular block uncertainty."""
    import numpy as np

    if any(v is not None and (not math.isfinite(v) or (not paired and v <= -1)) for v in values):
        raise ValueError("finite solvent daily returns required")
    if len(values) < 2 or any(v is None for v in values):
        return {"available": False, "reason": "INCOMPLETE_OR_SHORT_SAMPLE", "sessions": len(values)}
    x = np.asarray(values, dtype=float)
    n = len(x)
    mean = float(x.mean())
    centered = x - mean
    variance = float(np.dot(centered, centered) / n)
    lags = min(design.hac_lags, n - 1)
    long_run = variance + 2 * sum(
        (1 - lag / (lags + 1)) * float(np.dot(centered[lag:], centered[:-lag])) / n
        for lag in range(1, lags + 1)
    )
    se = math.sqrt(max(0, long_run) / n)
    effective = min(float(n), n * variance / long_run) if long_run > 0 and variance > 0 else None
    z = NormalDist().inv_cdf(1 - design.family_alpha / design.family_size)
    rng = np.random.default_rng(design.seed)
    draws = []
    for _ in range(design.bootstrap_draws):
        starts = rng.integers(0, n, size=math.ceil(n / design.bootstrap_block))
        indices = ((starts[:, None] + np.arange(design.bootstrap_block)) % n).reshape(-1)[:n]
        draws.append(float(x[indices].mean()))
    q = design.family_alpha / design.family_size
    nav = np.cumprod(1 + x)
    peaks = np.maximum.accumulate(np.r_[1.0, nav])[1:]
    return {
        "available": True,
        "sessions": n,
        "mean_bps": mean * 10000,
        "compounded_return": float(nav[-1] - 1) if not paired else None,
        "max_drawdown": float(np.max(1 - nav / peaks)) if not paired else None,
        "hac_standard_error_bps": se * 10000,
        "effective_sessions_diagnostic": effective,
        "one_sided_bonferroni_p": min(
            1.0, design.family_size * 0.5 * math.erfc(mean / se / math.sqrt(2))
        )
        if se > 0
        else None,
        "hac_family_lower_mean_bps": (mean - z * se) * 10000 if se > 0 else None,
        "block_bootstrap_mean_interval_bps": [
            float(np.quantile(draws, q)) * 10000,
            float(np.quantile(draws, 1 - q)) * 10000,
        ],
        "bootstrap_tail_resolution_warning": q < 1 / (design.bootstrap_draws + 1),
        "scope": "descriptive exposed-data inference; not independently confirmed Alpha",
    }


def purged_splits(days: Sequence[str]) -> dict[str, list[str]]:
    if len(days) < 12 or list(days) != sorted(set(days)):
        raise ValueError("at least twelve unique chronological sessions required")
    a, b = len(days) // 3, 2 * len(days) // 3
    return {
        "development": list(days[: a - 1]),
        "purge": [days[a - 1], days[b - 1]],
        "validation": list(days[a : b - 1]),
        "outer_exploratory": list(days[b:]),
    }


def confirmation_terminal(
    *,
    admitted: bool,
    independent_review_id: str | None,
    effective_sessions: float | None,
    minimum_sessions: int,
    statistical_pass: bool,
    economic_pass: bool,
) -> str:
    if (
        not admitted
        or not independent_review_id
        or effective_sessions is None
        or effective_sessions < minimum_sessions
    ):
        return "INSUFFICIENT_INDEPENDENT_EVIDENCE"
    return "CONFIRMED_POSITIVE" if statistical_pass and economic_pass else "CONFIRMED_NEGATIVE"

from __future__ import annotations

import numpy as np

from finagent.research.validation import (
    probability_of_backtest_overfitting,
    whites_reality_check,
)


def test_pbo_is_zero_for_one_uniformly_dominant_strategy() -> None:
    base = np.linspace(-0.01, 0.01, 160)
    returns = np.column_stack(
        [
            base + 0.01,
            base,
            -base - 0.005,
            np.sin(np.arange(base.size)) * 0.005,
        ]
    )
    result = probability_of_backtest_overfitting(returns, blocks=8)
    assert result.combinations_evaluated > 0
    assert result.probability_of_backtest_overfitting == 0.0


def test_reality_check_rejects_null_for_deterministic_positive_edge() -> None:
    n = 120
    returns = np.column_stack(
        [
            np.full(n, 0.01),
            np.zeros(n),
            np.full(n, -0.005),
        ]
    )
    result = whites_reality_check(
        returns,
        bootstrap_samples=199,
        block_size=5,
        seed=7,
    )
    assert result.observed_statistic > 0.0
    assert result.pvalue == 1.0 / 200.0

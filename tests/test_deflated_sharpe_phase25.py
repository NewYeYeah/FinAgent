from __future__ import annotations

import numpy as np

from finagent.research.validation import deflated_sharpe_ratio, expected_maximum_sharpe


def test_expected_maximum_sharpe_increases_with_trials() -> None:
    assert expected_maximum_sharpe(1, 0.1) == 0.0
    assert expected_maximum_sharpe(100, 0.1) > expected_maximum_sharpe(5, 0.1) > 0.0


def test_deflated_sharpe_penalizes_large_trial_family() -> None:
    rng = np.random.default_rng(17)
    returns = rng.normal(0.002, 0.01, 400)
    small = deflated_sharpe_ratio(
        returns,
        n_trials=2,
        trial_sharpes=(0.05, 0.10),
    )
    large = deflated_sharpe_ratio(
        returns,
        n_trials=100,
        trial_sharpes=tuple(np.linspace(-0.2, 0.2, 100)),
    )
    assert 0.0 <= small.deflated_probability <= 1.0
    assert 0.0 <= large.deflated_probability <= 1.0
    assert large.benchmark_sharpe > small.benchmark_sharpe
    assert large.deflated_probability < small.deflated_probability

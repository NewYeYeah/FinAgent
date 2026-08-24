from __future__ import annotations

import numpy as np

from finagent.research.validation import validate_experiment_family


def test_family_validation_exposes_all_anti_overfitting_components() -> None:
    rng = np.random.default_rng(42)
    n = 320
    strong = rng.normal(0.004, 0.008, n)
    weak1 = rng.normal(0.0, 0.01, n)
    weak2 = rng.normal(-0.0005, 0.01, n)
    returns = np.column_stack([strong, weak1, weak2])
    report = validate_experiment_family(
        returns,
        pvalues=(0.001, 0.4, 0.8),
        selected_index=0,
        pbo_blocks=8,
        bootstrap_samples=199,
        seed=123,
    )
    assert report.multiple_testing.rejected[0]
    assert report.deflated_sharpe.deflated_probability > 0.95
    assert 0.0 <= report.pbo.probability_of_backtest_overfitting <= 1.0
    assert 0.0 <= report.reality_check.pvalue <= 1.0

from dataclasses import replace

import pytest

from finagent.research.us_r3_inference import (
    EvidenceDesign,
    confirmation_terminal,
    describe_returns,
    purged_splits,
)


def test_power_penalizes_multiplicity_and_dependence():
    base = EvidenceDesign()
    assert base.to_dict()["minimum_effective_sessions"] > 1000
    assert (
        base.to_dict()["planning_calendar_sessions"] > base.to_dict()["minimum_effective_sessions"]
    )
    assert (
        replace(base, family_size=1).to_dict()["minimum_effective_sessions"]
        < base.to_dict()["minimum_effective_sessions"]
    )
    with pytest.raises(ValueError):
        replace(base, planning_ar1=1.0)


def test_hac_and_bootstrap_are_deterministic_and_missing_days_invalidate():
    values = [0.01, -0.005, 0.003, -0.002] * 15
    policy = EvidenceDesign(bootstrap_draws=99)
    result = describe_returns(values, policy)
    assert result == describe_returns(values, policy)
    assert 0 < result["effective_sessions_diagnostic"] <= len(values)
    assert result["bootstrap_tail_resolution_warning"]
    assert not describe_returns(values + [None], policy)["available"]
    assert describe_returns([0.0] * 20, policy)["one_sided_bonferroni_p"] is None
    pair = describe_returns([-1.2, 1.3] * 10, policy, paired=True)
    assert pair["compounded_return"] is None


def test_purged_calendar_split_and_no_false_confirmation():
    days = [f"2025-01-{i:02}" for i in range(1, 25)]
    splits = purged_splits(days)
    assert sorted(d for v in splits.values() for d in v) == days
    assert not set(splits["development"]) & set(splits["outer_exploratory"])
    assert (
        confirmation_terminal(
            admitted=False,
            independent_review_id="name",
            effective_sessions=99999,
            minimum_sessions=10,
            statistical_pass=True,
            economic_pass=True,
        )
        == "INSUFFICIENT_INDEPENDENT_EVIDENCE"
    )


def test_hac_matches_direct_intercept_only_bartlett_formula():
    values = [0.001, 0.002, -0.003, 0.004, -0.002, 0.003]
    design = EvidenceDesign(hac_lags=2, bootstrap_draws=10)
    n = len(values)
    mean = sum(values) / n
    x = [v - mean for v in values]
    variance = sum(v * v for v in x) / n
    long_run = variance + 2 * sum(
        (1 - lag / 3) * sum(x[t] * x[t - lag] for t in range(lag, n)) / n for lag in (1, 2)
    )
    assert describe_returns(values, design)["hac_standard_error_bps"] == pytest.approx(
        (long_run / n) ** 0.5 * 10000
    )

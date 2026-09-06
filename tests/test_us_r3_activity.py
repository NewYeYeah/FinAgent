from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from finagent.research.us_a1_factor_panel_materialization import FactorPanelAsset
from finagent.research.us_baselines import USBaselineBar
from finagent.research.us_r3_activity import ACTIVITY_ARMS, ActivityHistory, activity_targets
from finagent.research.us_r3_economics import EconomicPolicy


def panel(volume=100.0, slots=26):
    clock = datetime(2024, 12, 1, 14, 30, tzinfo=UTC)
    return tuple(
        FactorPanelAsset(
            name,
            tuple(
                USBaselineBar(
                    event_time=clock + timedelta(minutes=15 * i),
                    available_at=clock + timedelta(minutes=15 * (i + 1)),
                    session_id="fixture",
                    open=100.0,
                    high=102.0,
                    low=98.0,
                    close=close,
                    volume=volume,
                    is_complete=True,
                )
                for i in range(slots)
            ),
        )
        for name, close in (("A", 99), ("B", 100), ("C", 101))
    )


def test_exact_previous_twenty_median_excludes_current_and_is_bounded():
    state = ActivityHistory()
    for i in range(20):
        result = state.process(date(2024, 12, 1) + timedelta(days=i), panel(i + 1))
        assert result["A"] == [None] * 26
    result = state.process(date(2024, 12, 21), panel(210))
    assert result["A"] == [20.0] * 26
    assert len(state.history) == 20
    with pytest.raises(ValueError, match="chronological"):
        state.process(date(2024, 12, 21), panel())


def test_missing_slot_and_half_day_are_not_skipped_or_filled():
    state = ActivityHistory()
    for i in range(20):
        state.process(date(2024, 12, 1) + timedelta(days=i), panel(slots=14 if i == 19 else 26))
    result = state.process(date(2024, 12, 21), panel(200))
    assert result["A"][:14] == [2.0] * 14
    assert result["A"][14:] == [None] * 12
    state.process(date(2024, 12, 22), ())
    assert state.process(date(2024, 12, 23), panel())["A"] == [None] * 26


def test_later_slots_cannot_change_earlier_context_and_current_gaps_remain_unavailable():
    states = [ActivityHistory(), ActivityHistory()]
    for state in states:
        for i in range(20):
            state.process(date(2024, 12, 1) + timedelta(days=i), panel())
    current = panel(200)
    changed = tuple(
        replace(
            a,
            bars=a.bars[:5]
            + tuple(replace(b, volume=999999, is_complete=False) for b in a.bars[5:]),
        )
        for a in current
    )
    results = [
        state.process(date(2024, 12, 21), assets)
        for state, assets in zip(states, (current, changed), strict=True)
    ]
    assert results[0]["A"][:5] == results[1]["A"][:5]
    assert results[1]["A"][5:] == [None] * 21


def test_zero_history_denominator_and_incomplete_history_do_not_generate_ratios():
    state = ActivityHistory()
    for i in range(20):
        state.process(date(2024, 12, 1) + timedelta(days=i), panel(0))
    assert state.process(date(2024, 12, 21), panel())["A"] == [None] * 26


def test_one_mechanism_mask_ablation_and_identical_trigger_control():
    assets = panel()
    policy = EconomicPolicy(minimum_breadth=3, selection_count=1)
    ratios = {a.asset_id: [2.0] * 26 for a in assets}
    result = activity_targets(assets, ratios, policy)
    assert result[ACTIVITY_ARMS[0]] == [{"A": 1.0}] * 26
    assert result[ACTIVITY_ARMS[2]] == [{"A": 1 / 3, "B": 1 / 3, "C": 1 / 3}] * 26
    ratios["A"] = [1.99] * 26
    low = activity_targets(assets, ratios, policy)
    assert low[ACTIVITY_ARMS[0]] == [{}] * 26
    assert low[ACTIVITY_ARMS[1]] == [{"A": 1.0}] * 26
    assert low[ACTIVITY_ARMS[2]] == [{}] * 26
    ratios["C"] = [None] * 26
    assert activity_targets(assets, ratios, policy)[ACTIVITY_ARMS[1]] == [{}] * 26

from __future__ import annotations

from dataclasses import replace

import pytest

from finagent.research.us_r3_economics import (
    EconomicPolicy,
    positive_weights,
    simulate_session,
    summarize_sessions,
)


def test_hand_calculated_delayed_trade_charges_both_legs() -> None:
    policy = EconomicPolicy(holding_bars=2, minimum_breadth=1, selection_count=1)
    # Signal at 100, delayed buy at 110, exit at 121. 0.5 initial notional.
    prices = [{"A": v} for v in (100, 110, 115, 121, 123, 125)]
    targets = [{"A": 1.0}, {}, {}, {}, {}, {}]
    result = simulate_session(prices, targets, policy, cost_bps=1.0)
    assert result["resolved"]
    assert result["net_return"] == pytest.approx(0.05 - 1.05 / 10000)
    assert result["gross_traded_notional"] == pytest.approx(1.05)
    assert result["ledger"][0]["net_trades"] == {}
    assert result["ledger"][-1]["shares"] == {}


def test_overlapping_sleeves_net_replacements_and_never_borrow_cash() -> None:
    policy = EconomicPolicy(holding_bars=4, minimum_breadth=1, selection_count=1)
    prices = [{"A": 100.0}] * 20
    result = simulate_session(prices, [{"A": 1.0}] * 20, policy, cost_bps=5.0)
    assert max(row["active_sleeves"] for row in result["ledger"]) == 4
    assert all(row["cash"] >= -1e-12 for row in result["ledger"])
    assert result["net_return"] == pytest.approx(-result["cost"])
    assert result["ledger"][-2]["shares"] == {}
    assert result["ledger"][-1]["net_trades"] == {}
    # Replacing an equal sleeve at the same price trades no notional.
    assert result["ledger"][6]["gross_traded_notional"] == pytest.approx(0)
    assert result["gross_traded_notional"] < 2.01


def test_missing_exit_cannot_be_dropped_or_counted_as_cash() -> None:
    policy = EconomicPolicy(holding_bars=2, minimum_breadth=1, selection_count=1)
    prices = [{"A": 100.0}, {"A": 100.0}, {"A": 100.0}, {"A": None}, {"A": 100.0}, {"A": 100.0}]
    result = simulate_session(prices, [{"A": 1.0}, {}, {}, {}, {}, {}], policy, cost_bps=0.0)
    assert not result["resolved"]
    assert result["reason"] == "MISSING_EXIT_REFERENCE"
    summary = summarize_sessions([result])
    assert summary["scheduled_sessions"] == 1
    assert summary["compounded_return"] is None


def test_missing_entry_cancels_whole_basket_without_future_reallocation() -> None:
    policy = EconomicPolicy(holding_bars=2, minimum_breadth=2, selection_count=2)
    prices = [{"A": 100.0, "B": 100.0} for _ in range(6)]
    prices[1]["B"] = None
    result = simulate_session(
        prices, [{"A": 0.5, "B": 0.5}, {}, {}, {}, {}, {}], policy, cost_bps=0.0
    )
    assert result["canceled_entries"] == 1
    assert result["net_return"] == 0
    assert result["entries"] == 0


def test_missing_intermediate_mark_is_explicit_without_fake_price() -> None:
    policy = EconomicPolicy(holding_bars=2, minimum_breadth=1, selection_count=1)
    prices = [{"A": 100.0} for _ in range(6)]
    prices[2]["A"] = None
    result = simulate_session(prices, [{"A": 1.0}, {}, {}, {}, {}, {}], policy, cost_bps=0.0)
    assert result["resolved"]
    assert result["missing_mark_bars"] == 1
    assert result["ledger"][2]["equity"] is None
    assert result["ledger"][2]["missing_held_marks"] == ["A"]


def test_future_prices_cannot_change_past_trades() -> None:
    policy = EconomicPolicy(holding_bars=2, minimum_breadth=1, selection_count=1)
    first = [{"A": 100.0} for _ in range(10)]
    second = first[:5] + [{"A": 1000.0} for _ in range(5)]
    targets = [{"A": 1.0}] * 10
    a, b = [simulate_session(p, targets, policy, cost_bps=1.0) for p in (first, second)]
    assert a["ledger"][:5] == b["ledger"][:5]


def test_cash_is_allowed_and_ties_are_deterministic() -> None:
    policy = EconomicPolicy(minimum_breadth=3, selection_count=1)
    assert positive_weights({"A": -1, "B": 0, "C": -2}, policy) == {}
    assert positive_weights({"C": 1, "B": 1, "A": 1}, policy) == {"A": 1.0}
    assert positive_weights({"A": 1, "B": 2, "C": None}, policy) == {}
    assert positive_weights({"A": 0, "B": 0, "C": 0}, policy, equal_weight=True) == {
        "A": 1 / 3,
        "B": 1 / 3,
        "C": 1 / 3,
    }


def test_compounding_includes_cash_sessions_and_no_trade_break_even_is_unavailable() -> None:
    policy = EconomicPolicy(minimum_breadth=1, selection_count=1)
    cash = simulate_session([{"A": 100.0}] * 10, [{}] * 10, policy, cost_bps=0.0)
    assert summarize_sessions([cash, cash])["linear_break_even_cost_bps"] is None
    assert summarize_sessions([cash, cash])["compounded_return"] == 0
    assert summarize_sessions([])["compounded_return"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"delay_bars": 0},
        {"holding_bars": True},
        {"cost_bps": (0.0, float("nan"))},
        {"cost_bps": (1.0,)},
        {"minimum_breadth": 1, "selection_count": 2},
    ],
)
def test_invalid_policy_is_rejected(changes) -> None:
    with pytest.raises(ValueError):
        replace(EconomicPolicy(), **changes)


def test_pending_exit_fills_at_observation_time_and_retains_capital() -> None:
    policy = EconomicPolicy(
        holding_bars=2, minimum_breadth=1, selection_count=1, execution_profile="pending_exit_5m"
    )
    prices = [{"A": 100.0} for _ in range(30)]
    # Decision at reference 2, entry at 5, scheduled exit at 11 (30m later);
    # absent until reference 15.
    for i in range(11, 15):
        prices[i] = {"A": None}
    prices[15] = {"A": 120.0}
    targets = [{"A": 1.0} for _ in range(10)]
    result = simulate_session(prices, targets, policy, cost_bps=0.0)
    assert result["resolved"]
    assert result["suppressed_entries_pending_exit"] == 2
    assert result["max_exit_delay_minutes"] == 20
    ledger = result["ledger"]
    assert ledger[4]["net_trades"] == {}
    assert ledger[5]["net_trades"] == {"A": 0.005}
    assert ledger[11]["cash"] == 0
    assert ledger[11]["equity"] is None
    assert ledger[11]["shares"] == {"A": 0.01}
    assert ledger[15]["cash"] == pytest.approx(1.2)
    assert ledger[15]["delayed_exit_fills"][0]["actual_reference_index"] == 15
    changed = prices[:15] + [{"A": 1.0} for _ in range(15)]
    other = simulate_session(changed, targets, policy, cost_bps=0.0)
    assert other["ledger"][:15] == ledger[:15]


def test_pending_exit_cutoff_never_uses_closing_auction_or_next_day() -> None:
    policy = EconomicPolicy(
        holding_bars=2, minimum_breadth=1, selection_count=1, execution_profile="pending_exit_5m"
    )
    prices = [{"A": 100.0} for _ in range(18)]
    for i in range(11, 17):
        prices[i] = {"A": None}
    result = simulate_session(prices, [{"A": 1.0}] + [{}] * 5, policy, cost_bps=1.0)
    assert not result["resolved"]
    assert result["bar_index"] == 16
    assert result["reason"] == "EXIT_REFERENCE_UNAVAILABLE_AT_CUTOFF"
    assert result["ledger"][-1]["shares"]["A"] > 0
    assert summarize_sessions([result])["compounded_return"] is None


def test_dense_references_preserve_original_economics_when_no_exit_is_missing() -> None:
    sparse = [{"A": 100.0 + i} for i in range(15)]
    targets = [{"A": 1.0}] * 15
    policy = EconomicPolicy(holding_bars=2, minimum_breadth=1, selection_count=1)
    original = simulate_session(sparse, targets, policy, cost_bps=5.0)
    dense = simulate_session(
        [p for p in sparse for _ in range(3)],
        targets,
        replace(policy, execution_profile="pending_exit_5m"),
        cost_bps=5.0,
    )
    assert dense["net_return"] == original["net_return"]
    assert dense["gross_traded_notional"] == original["gross_traded_notional"]
    assert dense["deferred_exit_fills"] == 0


def test_pending_exit_sells_available_legs_and_charges_actual_delayed_price() -> None:
    policy = EconomicPolicy(
        holding_bars=2, minimum_breadth=2, selection_count=2, execution_profile="pending_exit_5m"
    )
    prices = [{"A": 100.0, "B": 100.0} for _ in range(18)]
    prices[11] = {"A": 110.0, "B": None}
    prices[12] = {"A": 110.0, "B": 120.0}
    result = simulate_session(prices, [{"A": 0.5, "B": 0.5}] + [{}] * 5, policy, cost_bps=5.0)
    assert result["resolved"]
    assert result["ledger"][11]["shares"] == {"B": 0.0025}
    assert result["ledger"][11]["net_trades"] == {"A": -0.0025}
    assert result["ledger"][12]["net_trades"] == {"B": -0.0025}
    assert result["net_return"] == pytest.approx(0.075 - 1.075 * 0.0005)
    assert result["deferred_exit_fills"] == 1
    assert result["max_exit_delay_minutes"] == 5


@pytest.mark.parametrize("signal_count", [14, 26])
def test_opening_once_clock_cash_fees_and_calendar_exit(signal_count) -> None:
    policy = EconomicPolicy(
        minimum_breadth=1, selection_count=1, execution_profile="pending_exit_5m"
    )
    prices = [{"A": 100.0} for _ in range(signal_count * 3)]
    prices[14] = {"A": 110.0}  # entry at open + 75m
    prices[-4] = {"A": 121.0}  # scheduled exit at close - 15m
    result = simulate_session(
        prices, [{"A": 1.0}] * signal_count, policy, cost_bps=5.0, schedule="opening_60m_once"
    )
    quantity = 1 / (110 * 1.0005)
    assert result["entries"] == 1
    assert result["net_return"] == pytest.approx(quantity * 121 * 0.9995 - 1)
    assert result["gross_traded_notional"] == pytest.approx(quantity * (110 + 121))
    ledger = result["ledger"]
    assert all(row["net_trades"] == {} for row in ledger[:14])
    assert ledger[14]["decision_bar_index"] == 3
    assert ledger[14]["shares"]["A"] == pytest.approx(quantity)
    assert all(row["shares"] == ledger[14]["shares"] for row in ledger[15:-4])
    assert ledger[-4]["shares"] == {}
    assert all(row["cash"] >= -1e-12 for row in ledger)


def test_opening_once_missing_entry_cancels_for_entire_day() -> None:
    policy = EconomicPolicy(
        minimum_breadth=1, selection_count=1, execution_profile="pending_exit_5m"
    )
    prices = [{"A": 100.0} for _ in range(78)]
    prices[14] = {"A": None}
    result = simulate_session(
        prices, [{"A": 1.0}] * 26, policy, cost_bps=5.0, schedule="opening_60m_once"
    )
    assert result["canceled_entries"] == 1
    assert result["entries"] == 0
    assert result["net_return"] == 0


def test_opening_once_ignores_later_signals_and_retries_only_exit() -> None:
    policy = EconomicPolicy(
        minimum_breadth=1, selection_count=1, execution_profile="pending_exit_5m"
    )
    prices = [{"A": 100.0} for _ in range(78)]
    prices[74] = {"A": None}
    prices[75] = {"A": 105.0}
    targets = [{"A": 1.0}] * 26
    first = simulate_session(prices, targets, policy, cost_bps=0.0, schedule="opening_60m_once")
    second = simulate_session(
        prices, targets[:4] + [{}] * 22, policy, cost_bps=0.0, schedule="opening_60m_once"
    )
    assert first == second
    assert first["entries"] == 1
    assert first["net_return"] == pytest.approx(0.05)
    assert first["max_exit_delay_minutes"] == 5


def test_first_activity_attempt_is_once_and_has_fixed_holding_period():
    policy = EconomicPolicy(
        minimum_breadth=1, selection_count=1, execution_profile="pending_exit_5m"
    )
    prices = [{"A": 100.0}] * 78
    targets = [{}] * 6 + [{"A": 1.0}] * 20
    result = simulate_session(prices, targets, policy, cost_bps=0.0, schedule="first_activity_once")
    assert result["entries"] == 1
    assert result["ledger"][22]["shares"] == {}
    assert result["ledger"][23]["shares"] == {"A": 0.01}
    assert result["ledger"][35]["shares"] == {}
    missing = list(prices)
    missing[23] = {"A": None}
    canceled = simulate_session(
        missing, targets, policy, cost_bps=0.0, schedule="first_activity_once"
    )
    assert canceled["entries"] == 0
    assert canceled["canceled_entries"] == 1

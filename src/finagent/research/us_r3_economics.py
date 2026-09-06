"""Broker-neutral, long-only sleeve accounting for exploratory R3 research.

Orders are determined from earlier signals and priced at delayed bar-close
references plus explicit scenario costs. These are hypothetical fills, not
historically observed executable quotes. No labels enter the decision path.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True)
class EconomicPolicy:
    holding_bars: int = 4
    delay_bars: int = 1
    minimum_breadth: int = 20
    selection_count: int = 5
    cost_bps: tuple[float, ...] = (0.0, 1.0, 5.0, 10.0)
    execution_profile: str = "strict_15m"

    def __post_init__(self) -> None:
        if self.execution_profile not in ("strict_15m", "pending_exit_5m"):
            raise ValueError("unsupported execution profile")
        for name in ("holding_bars", "delay_bars", "minimum_breadth", "selection_count"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 64:
                raise ValueError(f"{name} must be an integer in 1..64")
        if self.selection_count > self.minimum_breadth:
            raise ValueError("selection_count must not exceed minimum_breadth")
        if (
            not self.cost_bps
            or len(self.cost_bps) > 16
            or tuple(sorted(set(self.cost_bps))) != self.cost_bps
            or self.cost_bps[0] != 0.0
            or any(
                type(c) not in (int, float) or not math.isfinite(c) or not 0 <= c <= 1000
                for c in self.cost_bps
            )
        ):
            raise ValueError(
                "cost grid must be unique, sorted, finite, start at zero, and <=1000bp"
            )


def positive_weights(
    scores: Mapping[str, float | None],
    policy: EconomicPolicy,
    *,
    equal_weight: bool = False,
) -> dict[str, float]:
    valid = [(value, asset) for asset, value in scores.items() if value is not None]
    if any(not math.isfinite(value) for value, _ in valid):
        raise ValueError("nonfinite signal")
    if len(valid) < policy.minimum_breadth:
        return {}
    eligible = [
        asset
        for value, asset in sorted(valid, key=lambda pair: (-pair[0], pair[1]))
        if equal_weight or value > 0
    ]
    selected = eligible if equal_weight else eligible[: policy.selection_count]
    return {asset: 1.0 / len(selected) for asset in selected}


def _ending_cash(
    available: float,
    budget: float,
    legs: tuple[tuple[float, float], ...],
    rate: float,
) -> float:
    return (
        available - budget - rate * math.fsum(abs(budget * weight - sold) for weight, sold in legs)
    )


def simulate_session(
    prices: Sequence[Mapping[str, float | None]],
    targets: Sequence[Mapping[str, float]],
    policy: EconomicPolicy,
    *,
    cost_bps: float,
    schedule: str = "rolling_sleeves",
) -> dict[str, object]:
    """Self-financing cash/share ledger starting with one unit of daily NAV.

    Four 60-minute sleeves can overlap at a 15-minute decision clock. Each new
    sleeve has at most 1/holding_bars of opening NAV. Cash bounds include fees;
    due exits and new entries are netted by shares before charging traded
    notional. Final scheduled exit is the penultimate close reference (15m
    before session close), so no closing-auction fill is presumed.

    A missing entry reference cancels the entire basket, without reallocating
    it. Missing held marks remain explicit. The optional pending_exit_5m profile
    accepts three execution references per signal bar, retries due shares at
    their next observed price, and suspends new entries while exits are pending.
    Retry stops five minutes before close. Unfilled exits invalidate the day.

    opening_60m_once uses only the signal available 60m after session open,
    delays entry by the policy clock, allocates available opening NAV once,
    and holds fixed shares to close-minus-15m. A canceled entry is never retried.
    """
    if schedule not in ("rolling_sleeves", "opening_60m_once", "first_activity_once"):
        raise ValueError("unsupported allocation schedule")
    steps = 3 if policy.execution_profile == "pending_exit_5m" else 1
    if len(prices) != len(targets) * steps or not 3 <= len(targets) <= 64:
        raise ValueError("aligned bounded session arrays required")
    if cost_bps not in policy.cost_bps:
        raise ValueError("cost scenario is outside the frozen grid")
    for frame in prices:
        if any(
            value is not None and (not math.isfinite(value) or value <= 0)
            for value in frame.values()
        ):
            raise ValueError("prices must be positive finite or explicitly unavailable")
    for target in targets:
        if any(not math.isfinite(w) or w <= 0 for w in target.values()):
            raise ValueError("weights must be positive finite")
        if target and not math.isclose(math.fsum(target.values()), 1.0, abs_tol=1e-12):
            raise ValueError("entry basket weights must sum to one")
    rate = cost_bps / 10_000.0
    cash = 1.0
    # (scheduled exit index, per-asset shares)
    sleeves: list[tuple[int, dict[str, float]]] = []
    ledger: list[dict[str, object]] = []
    cost_total = traded_total = 0.0
    canceled = missing_marks = entries = 0
    last_exit = len(prices) - 1 - steps
    cutoff = len(prices) - 2
    deferred_fills = suppressed_entries = max_exit_delay = 0
    attempted_once = False
    for index, marks in enumerate(prices):
        due = [(expiry, shares) for expiry, shares in sleeves if expiry <= index]
        sells: dict[str, float] = {}
        remaining = [(expiry, shares) for expiry, shares in sleeves if expiry > index]
        delayed_fills: list[dict[str, object]] = []
        for expiry, shares in due:
            pending: dict[str, float] = {}
            for asset, quantity in shares.items():
                if marks.get(asset) is None:
                    pending[asset] = quantity
                else:
                    sells[asset] = sells.get(asset, 0.0) + quantity
                    if index > expiry:
                        delay = (index - expiry) * (15 // steps)
                        max_exit_delay = max(max_exit_delay, delay)
                        deferred_fills += 1
                        delayed_fills.append(
                            {
                                "asset": asset,
                                "shares": quantity,
                                "scheduled_reference_index": expiry,
                                "actual_reference_index": index,
                                "delay_minutes": delay,
                            }
                        )
            if pending:
                remaining.append((expiry, pending))
        pending_exits = [
            {"asset": asset, "shares": qty, "scheduled_reference_index": expiry}
            for expiry, shares in remaining
            if expiry <= index
            for asset, qty in sorted(shares.items())
        ]
        if pending_exits and steps == 1:
            return {
                "resolved": False,
                "reason": "MISSING_EXIT_REFERENCE",
                "bar_index": index,
                "net_return": None,
                "ledger": ledger,
                "canceled_entries": canceled,
            }
        sell_value = math.fsum(qty * float(marks[asset]) for asset, qty in sells.items())  # type: ignore[arg-type]
        sleeves = remaining
        signal_index = (index + 1) // steps - 1 - policy.delay_bars
        scheduled_exit = (
            last_exit if schedule == "opening_60m_once" else index + policy.holding_bars * steps
        )
        entry_allowed = (
            signal_index == 3 and index < last_exit
            if schedule == "opening_60m_once"
            else scheduled_exit <= last_exit
        )
        if schedule == "first_activity_once":
            entry_allowed = signal_index >= 3 and not attempted_once and scheduled_exit <= last_exit
        target = (
            targets[signal_index]
            if (index + 1) % steps == 0 and signal_index >= 0 and entry_allowed
            else {}
        )
        if target and pending_exits:
            suppressed_entries += 1
            target = {}
        if target and schedule == "first_activity_once":
            attempted_once = True
        if target and any(marks.get(asset) is None for asset in target):
            canceled += 1
            target = {}
        # Solve the monotone cash constraint using the actual NET trade costs.
        # Reserving independent round-trip fees here would repeatedly shrink an
        # unchanged replacement basket even when it requires zero external trade.
        legs = tuple(
            (target.get(asset, 0.0), sells.get(asset, 0.0) * cast(float, marks[asset]))
            for asset in sorted(set(sells) | set(target))
        )
        allocation = 1.0 if schedule != "rolling_sleeves" else 1.0 / policy.holding_bars
        budget = allocation if target else 0.0
        if target and _ending_cash(cash + sell_value, budget, legs, rate) < 0:
            lower, upper = 0.0, budget
            for _ in range(60):
                middle = (lower + upper) / 2
                if _ending_cash(cash + sell_value, middle, legs, rate) >= 0:
                    lower = middle
                else:
                    upper = middle
            budget = lower
        buys = (
            {
                asset: budget * weight / float(marks[asset])  # type: ignore[arg-type]
                for asset, weight in target.items()
            }
            if budget > 1e-12
            else {}
        )
        if buys:
            sleeves.append((scheduled_exit, buys))
            entries += 1
        assets = sorted(set(sells) | set(buys))
        trades = {asset: buys.get(asset, 0.0) - sells.get(asset, 0.0) for asset in assets}
        notional = math.fsum(
            abs(qty) * float(marks[asset])  # type: ignore[arg-type]
            for asset, qty in trades.items()
        )
        cost = rate * notional
        cash -= (
            math.fsum(
                qty * float(marks[asset])  # type: ignore[arg-type]
                for asset, qty in trades.items()
            )
            + cost
        )
        if cash < -1e-10:
            raise ArithmeticError("self-financing cash constraint violated")
        cost_total += cost
        traded_total += notional
        held: dict[str, float] = {}
        for _, shares in sleeves:
            for asset, quantity in shares.items():
                held[asset] = held.get(asset, 0.0) + quantity
        missing = sorted(asset for asset in held if marks.get(asset) is None)
        missing_marks += bool(missing)
        equity = (
            None
            if missing
            else cash + math.fsum(qty * cast(float, marks[asset]) for asset, qty in held.items())
        )
        ledger.append(
            {
                "bar_index": index,
                "decision_bar_index": signal_index if (index + 1) % steps == 0 else None,
                "reference_minutes": 15 // steps,
                "shares": held,
                "net_trades": trades,
                "cash": cash,
                "equity": equity,
                "gross_traded_notional": notional,
                "cost": cost,
                "missing_held_marks": missing,
                "active_sleeves": len(sleeves),
                "pending_exits": pending_exits,
                "delayed_exit_fills": delayed_fills,
            }
        )
        if index == cutoff and sleeves:
            return {
                "resolved": False,
                "reason": "EXIT_REFERENCE_UNAVAILABLE_AT_CUTOFF",
                "bar_index": index,
                "net_return": None,
                "ledger": ledger,
                "canceled_entries": canceled,
                "pending_exits": pending_exits,
            }
    if sleeves:
        raise ArithmeticError("session must end flat")
    return {
        "resolved": True,
        "net_return": cash - 1.0,
        "trading_pnl_before_cost": cash - 1.0 + cost_total,
        "cost": cost_total,
        "gross_traded_notional": traded_total,
        "entries": entries,
        "canceled_entries": canceled,
        "missing_mark_bars": missing_marks,
        "deferred_exit_fills": deferred_fills,
        "max_exit_delay_minutes": max_exit_delay,
        "suppressed_entries_pending_exit": suppressed_entries,
        "ledger": ledger,
    }


def summarize_sessions(sessions: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """No significance/Alpha claim; unresolved days invalidate full-period NAV."""
    resolved = [row for row in sessions if row["resolved"] is True]
    returns = [float(row["net_return"]) for row in resolved]  # type: ignore[arg-type]
    costs = math.fsum(float(row["cost"]) for row in resolved)  # type: ignore[arg-type]
    traded = math.fsum(float(row["gross_traded_notional"]) for row in resolved)  # type: ignore[arg-type]
    complete = bool(sessions) and len(resolved) == len(sessions)
    nav = peak = 1.0
    drawdown = 0.0
    for value in returns:
        nav *= 1.0 + value
        peak = max(peak, nav)
        drawdown = max(drawdown, 1.0 - nav / peak)
    return {
        "scheduled_sessions": len(sessions),
        "resolved_sessions": len(resolved),
        "unresolved_sessions": len(sessions) - len(resolved),
        "full_period_evaluable": complete,
        "active_sessions": sum(cast(int, row["entries"]) > 0 for row in resolved),
        "cash_only_sessions": sum(cast(int, row["entries"]) == 0 for row in resolved),
        "total_entry_baskets": sum(cast(int, row["entries"]) for row in resolved),
        "compounded_return": nav - 1.0 if complete else None,
        "daily_close_max_drawdown": drawdown if complete else None,
        "resolved_session_mean_net_bps": math.fsum(returns) / len(returns) * 10000
        if returns
        else None,
        "resolved_session_cost_sum": costs,
        "resolved_session_gross_traded_sum": traded,
        "linear_break_even_cost_bps": math.fsum(returns) / traded * 10000
        if complete and traded > 0 and costs == 0
        else None,
        "break_even_scope": "zero_cost_path_linear_diagnostic_not_execution_estimate",
        "canceled_entries": sum(int(row["canceled_entries"]) for row in resolved),  # type: ignore[call-overload]
        "missing_mark_bars": sum(int(row["missing_mark_bars"]) for row in resolved),  # type: ignore[call-overload]
        "deferred_exit_fills": sum(int(row.get("deferred_exit_fills", 0)) for row in resolved),  # type: ignore[call-overload]
        "max_exit_delay_minutes": max(
            (cast(int, row.get("max_exit_delay_minutes", 0)) for row in resolved), default=0
        ),
        "suppressed_entries_pending_exit": sum(
            cast(int, row.get("suppressed_entries_pending_exit", 0)) for row in resolved
        ),
        "inference": "descriptive_exposed_development_data_only",
    }

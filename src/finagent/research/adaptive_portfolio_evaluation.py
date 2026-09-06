"""Session mechanics and descriptive metrics, reusing FactorGraph and R3 economics."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from itertools import pairwise
from typing import Any, cast

from finagent.domain.trading import TradeActivity
from finagent.research.factor_library_evaluation import _rank_ic
from finagent.research.factor_performance import (
    FactorDecisionIC,
    FactorPerformanceObservation,
    fixed_exposure_targets,
    normalize_factor_signal,
)
from finagent.research.market_state import MarketStateRow, utc_text
from finagent.research.us_a1_factor_materialization import CompiledFactorBatch
from finagent.research.us_a1_factor_panel_materialization import (
    FactorPanelAsset,
    materialize_compiled_factor_panel,
)
from finagent.research.us_baselines import _canonical_hash
from finagent.research.us_r3_economics import EconomicPolicy, simulate_session, summarize_sessions

SignalFrame = dict[str, dict[str, float]]


def materialize_session_signals(
    compiled: CompiledFactorBatch, assets: tuple[FactorPanelAsset, ...], policy: EconomicPolicy
) -> tuple[SignalFrame, ...]:
    panel = materialize_compiled_factor_panel(
        compiled, assets, minimum_cross_section=policy.minimum_breadth
    )
    series = {(r.candidate_id, r.asset_id): r.values for r in panel.candidates}
    ids = sorted(r.candidate_id for r in compiled.roots)
    frames = []
    for i in range(len(assets[0].bars)):
        frame = {
            factor: {
                a.asset_id: series[factor, a.asset_id][i]
                for a in assets
                if series[factor, a.asset_id][i] is not None
            }
            for factor in ids
        }
        # Coverage is frozen before looking at outcomes or weights, including
        # factors that subsequently receive zero allocation.
        common = set.intersection(*(set(row) for row in frame.values()))
        frames.append(
            {
                f: normalize_factor_signal({a: row[a] for a in sorted(common)})
                for f, row in frame.items()
            }
        )
    return tuple(frames)


def session_prices(assets: tuple[FactorPanelAsset, ...]) -> list[dict[str, float | None]]:
    return [
        {a.asset_id: a.bars[i].close if a.bars[i].is_complete else None for a in assets}
        for i in range(len(assets[0].bars))
    ]


def run_session_economics(
    assets: tuple[FactorPanelAsset, ...],
    targets: Sequence[Mapping[str, float]],
    policy: EconomicPolicy,
    cost: float,
) -> dict[str, object]:
    if not any(b.is_complete for a in assets for b in a.bars):
        return {"resolved": False, "reason": "NO_COMPLETE_OHLCV_SESSION", "net_return": None}
    return cast(
        dict[str, object],
        simulate_session(
            session_prices(assets), targets, policy, cost_bps=cost, schedule="rolling_sleeves"
        ),
    )


def observe_completed_session(
    assets: tuple[FactorPanelAsset, ...],
    signals: tuple[SignalFrame, ...],
    states: tuple[MarketStateRow, ...],
    policy: EconomicPolicy,
    *,
    source_id: str,
    evaluation_id: str,
    as_of: datetime,
) -> tuple[FactorPerformanceObservation, ...]:
    bars = assets[0].bars
    if as_of < bars[-1].available_at:
        raise ValueError("session performance cannot be released before completion")
    if len(signals) != len(bars) or len(states) != len(bars):
        raise ValueError("performance arrays must align with the session")
    result = []
    for factor in sorted(signals[0]):
        decisions = []
        for i, (bar, state) in enumerate(zip(bars, states, strict=True)):
            entry, exit_index = i + policy.delay_bars, i + policy.delay_bars + policy.holding_bars
            outcomes = {}
            maturity = None
            # Exactly the simulator's final allowed exit reference. Overlapping
            # intraday labels are descriptive and never cross a session boundary.
            if exit_index <= len(bars) - 2:
                maturity = bars[exit_index].available_at
                for asset in assets:
                    holding = asset.bars[entry : exit_index + 1]
                    if all(b.is_complete for b in holding):
                        outcomes[asset.asset_id] = holding[-1].close / holding[0].close - 1
            ic = _rank_ic(signals[i][factor], outcomes, policy.minimum_breadth)
            if state.available_at != bar.available_at or state.session_id != bar.session_id:
                raise ValueError("performance must retain state at the exact decision")
            decisions.append(
                FactorDecisionIC(
                    bar.available_at, maturity, ic, state.probabilities, state.model_id
                )
            )
        net = run_session_economics(
            assets,
            [fixed_exposure_targets(frame[factor], policy) for frame in signals],
            policy,
            5.0,
        )
        usable = [d.rank_ic for d in decisions if d.rank_ic is not None]
        result.append(
            FactorPerformanceObservation(
                factor,
                bars[0].available_at,
                bars[-1].available_at,
                bars[0].session_id,
                math.fsum(usable) / len(usable) if usable else None,
                cast(float | None, net["net_return"]),
                tuple(decisions),
                source_id,
                evaluation_id,
                sum(len(frame[factor]) < policy.minimum_breadth for frame in signals),
            )
        )
    return tuple(result)


def session_identity(assets: tuple[FactorPanelAsset, ...]) -> str:
    return str(
        _canonical_hash(
            [
                {
                    "asset_id": a.asset_id,
                    "bars": [
                        {
                            "event_time": utc_text(b.event_time),
                            "available_at": utc_text(b.available_at),
                            "session_id": b.session_id,
                            "ohlcv": (b.open, b.high, b.low, b.close, b.volume),
                            "complete": b.is_complete,
                        }
                        for b in a.bars
                    ],
                }
                for a in sorted(assets, key=lambda a: a.asset_id)
            ],
            prefix="adaptive-session",
        )
    )


def weight_series_metrics(series: Sequence[dict[str, Any]]) -> dict[str, Any]:
    vectors = [list(row["weights"].values()) for row in series]
    turnovers = [TradeActivity.from_weights(a, b).one_way_turnover for a, b in pairwise(vectors)]
    mean_turnover = math.fsum(turnovers) / len(turnovers) if turnovers else 0.0
    return {
        "decision_count": len(series),
        "fallback_count": sum(r["fallback_reason"] is not None for r in series),
        "mean_factor_weight_concentration": math.fsum(math.fsum(w * w for w in v) for v in vectors)
        / len(vectors)
        if vectors
        else None,
        "factor_weight_turnover_total": math.fsum(turnovers),
        "mean_factor_weight_turnover": mean_turnover,
        "factor_weight_stability": 1 - mean_turnover,
        "weight_turnover_definition": "half_L1_between_consecutive_decisions; includes_session_boundary; excludes_initialization",
        "unavailable_signal_frames": sum(r["data_fallback_reason"] is not None for r in series),
        "unavailable_market_state_frames": sum(not r["market_state_available"] for r in series),
    }


def conditional_nav_metrics(
    economics: Sequence[dict[str, object]],
    session_states: Sequence[tuple[MarketStateRow, ...]],
    component_count: int,
) -> dict[str, Any]:
    pairs: list[list[tuple[float, float]]] = [[] for _ in range(component_count)]
    unavailable = 0
    for day, states in zip(economics, session_states, strict=True):
        if day["resolved"] is not True:
            unavailable += len(states) - 1
            continue
        ledger = cast(list[dict[str, Any]], day["ledger"])
        for i in range(1, len(ledger)):
            before, after = ledger[i - 1]["equity"], ledger[i]["equity"]
            p = states[i - 1].probabilities  # known at the BEGINNING of this NAV interval
            if p is None or before is None or after is None or before <= 0:
                unavailable += 1
                continue
            change = after / before - 1
            for k in range(component_count):
                pairs[k].append((change, p[k]))
    return {
        "definition": "15m_NAV_change_conditioned_on_state_known_at_interval_start; resolved_sessions_only; descriptive_not_state_strategy",
        "unavailable_intervals": unavailable,
        "states": {
            str(k): {
                "observation_weight": (mass := math.fsum(p for _, p in values)),
                "mean_nav_change_bps": math.fsum(r * p for r, p in values) / mass * 10000
                if mass
                else None,
            }
            for k, values in enumerate(pairs)
        },
    }


def strategy_summary(
    economics: Sequence[dict[str, object]],
    states: Sequence[tuple[MarketStateRow, ...]],
    series: Sequence[dict[str, Any]],
    component_count: int,
) -> dict[str, Any]:
    summary = summarize_sessions(economics)
    traded = cast(float, summary["resolved_session_gross_traded_sum"])
    return {
        **summary,
        **weight_series_metrics(series),
        "turnover": TradeActivity.from_traded_notional(traded, 1.0).one_way_turnover,
        "gross_traded_notional": traded,
        "cost": summary["resolved_session_cost_sum"],
        "turnover_scope": "resolved_session_sum; each_session_starts_at_unit_NAV; half_gross_traded_notional",
        "by_market_state": conditional_nav_metrics(economics, states, component_count),
    }

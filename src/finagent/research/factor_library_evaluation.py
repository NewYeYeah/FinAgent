"""Development-only FactorGraph diagnostics by causal MarketState.

IC/coverage/decay use soft probability weights. Economics is a separate,
explicit fixed argmax entry-gate diagnostic; every state and every cost is kept.
It reuses R3 cash/share accounting, not a new allocator or confirmation gate.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from finagent.domain.research import TimeRange
from finagent.research.factor_library import FactorRegistration
from finagent.research.market_state import build_market_features, utc_text
from finagent.research.market_state_gmm import MarketStateModel, project_market_state
from finagent.research.us_a1_factor_materialization import compile_factor_graph_batch
from finagent.research.us_a1_factor_panel_materialization import (
    FactorPanelAsset,
    materialize_compiled_factor_panel,
)
from finagent.research.us_baseline_evaluation import _average_ranks, _correlation
from finagent.research.us_baselines import _canonical_hash
from finagent.research.us_r3_economic_campaign import file_digest
from finagent.research.us_r3_economics import (
    EconomicPolicy,
    positive_weights,
    simulate_session,
    summarize_sessions,
)


def evaluation_implementation_id() -> str:
    root = Path(__file__).parent
    names = (
        "factor_library_evaluation.py",
        "us_a1_factor_materialization.py",
        "us_a1_factor_panel_materialization.py",
        "us_a1_factor_validation.py",
        "us_a1_factor_graph.py",
        "us_baseline_evaluation.py",
        "us_r3_economics.py",
    )
    return str(
        _canonical_hash(
            {name: file_digest(root / name) for name in names},
            prefix="factor-evaluation-implementation",
        )
    )


@dataclass(frozen=True)
class FactorEvaluationConfig:
    economics: EconomicPolicy
    decay_bars: tuple[int, ...] = (1, 4)

    def __post_init__(self) -> None:
        if self.economics.execution_profile != "strict_15m":
            raise ValueError("FactorLibrary v1 uses explicit complete 15m close references")
        if not self.decay_bars or tuple(sorted(set(self.decay_bars))) != self.decay_bars:
            raise ValueError("decay horizons must be unique and sorted")
        if any(type(h) is not int or not 1 <= h <= 16 for h in self.decay_bars):
            raise ValueError("decay horizons must be integers in 1..16")
        if 5.0 not in self.economics.cost_bps:
            raise ValueError("preserve the primary 5bp development cost scenario")


def _rank_ic(left: dict[str, float], right: dict[str, float], minimum: int) -> float | None:
    common = sorted(left.keys() & right.keys())
    if len(common) < minimum:
        return None
    return _correlation(  # type: ignore[no-any-return]
        _average_ranks({a: left[a] for a in common}),
        _average_ranks({a: right[a] for a in common}),
    )


def _weighted(values: Sequence[tuple[float | None, float]]) -> float | None:
    valid = [(value, weight) for value, weight in values if value is not None and weight > 0]
    mass = math.fsum(weight for _, weight in valid)
    return math.fsum(value * weight for value, weight in valid) / mass if mass else None


def _outcomes(assets: tuple[FactorPanelAsset, ...], index: int, horizon: int) -> dict[str, float]:
    result = {}
    for asset in assets:
        holding = asset.bars[index : index + horizon + 1]
        if len(holding) == horizon + 1 and all(b.is_complete for b in holding):
            result[asset.asset_id] = holding[-1].close / holding[0].close - 1
    return result


def evaluate_factor_library(
    factors: tuple[FactorRegistration, ...],
    sessions: tuple[tuple[FactorPanelAsset, ...], ...],
    model: MarketStateModel,
    window: TimeRange,
    config: FactorEvaluationConfig,
    *,
    as_of: datetime,
) -> tuple[dict[str, Any], ...]:
    """Evaluate complete calendar-aligned sessions strictly after the fitted history.

    The application reader supplies the accepted calendar denominator, including
    padded missing sessions. No labels or factors are used to fit the state model.
    """
    if window.start < model.fit_window.end or window.start < model.available_at:
        raise ValueError("evaluation window overlaps model training/availability")
    if as_of < window.end:
        raise ValueError("evaluation outcomes not available at requested as_of")
    ids = tuple(f.factor_id for f in factors)
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("nonempty unique factors required")
    if not sessions or len(sessions) > 252:
        raise ValueError("bounded nonempty evaluation sessions required")
    compiled = compile_factor_graph_batch(
        tuple(f.graph for f in factors), admit_panel_operators=True
    )
    records: dict[str, list[dict[str, Any]]] = {identity: [] for identity in ids}
    arms = ("global", *(f"state_{i}" for i in range(model.config.n_components)))
    economics: dict[str, dict[str, dict[str, list[dict[str, object]]]]] = {
        identity: {arm: {str(cost): [] for cost in config.economics.cost_bps} for arm in arms}
        for identity in ids
    }
    session_digests = []
    previous_end: datetime | None = None
    universe: tuple[str, ...] | None = None
    for assets in sessions:
        if not assets or not assets[0].bars:
            raise ValueError("aligned nonempty session required")
        bars = assets[0].bars
        if len({bar.session_id for bar in bars}) != 1:
            raise ValueError("one calendar session per materialization required")
        current_universe = tuple(sorted(a.asset_id for a in assets))
        if universe is not None and universe != current_universe:
            raise ValueError("evaluation universe must remain fixed")
        universe = current_universe
        if bars[0].event_time < window.start or bars[-1].available_at > window.end:
            raise ValueError("session/label horizon outside evaluation window")
        if previous_end is not None and bars[0].event_time < previous_end:
            raise ValueError("evaluation sessions overlap or recur")
        previous_end = bars[-1].available_at
        panel = materialize_compiled_factor_panel(
            compiled,
            assets,
            minimum_cross_section=config.economics.minimum_breadth,
        )
        features = build_market_features(assets, model.source, model.features)
        states = project_market_state(model, features, as_of=as_of)
        session_digests.append(
            _canonical_hash(
                [
                    {
                        "asset": a.asset_id,
                        "bars": [
                            {
                                **asdict(b),
                                "event_time": utc_text(b.event_time),
                                "available_at": utc_text(b.available_at),
                            }
                            for b in a.bars
                        ],
                    }
                    for a in sorted(assets, key=lambda a: a.asset_id)
                ],
                prefix="factor-session",
            )
        )
        series = {(row.candidate_id, row.asset_id): row.values for row in panel.candidates}
        scores = {
            identity: [
                {
                    a.asset_id: float(series[identity, a.asset_id][i])
                    for a in assets
                    if series[identity, a.asset_id][i] is not None
                }
                for i in range(len(bars))
            ]
            for identity in ids
        }
        prices = [
            {a.asset_id: a.bars[i].close if a.bars[i].is_complete else None for a in assets}
            for i in range(len(bars))
        ]
        for identity in ids:
            targets = [positive_weights(score, config.economics) for score in scores[identity]]
            previous: Mapping[str, float] = {}
            for i, (bar, state) in enumerate(zip(bars, states, strict=True)):
                turnover = math.fsum(
                    abs(targets[i].get(a, 0) - previous.get(a, 0))
                    for a in targets[i].keys() | previous.keys()
                )
                previous = targets[i]
                records[identity].append(
                    {
                        "event_time": utc_text(bar.event_time),
                        "available_at": utc_text(bar.available_at),
                        "state_probabilities": state.probabilities,
                        "state_unavailable_reason": state.unavailable_reason,
                        "coverage": len(scores[identity][i]) / len(assets),
                        "turnover": turnover,
                        "decay": {
                            str(h * 15): _rank_ic(
                                scores[identity][i],
                                _outcomes(assets, i, h),
                                config.economics.minimum_breadth,
                            )
                            for h in config.decay_bars
                        },
                        "similarity": {
                            other: _rank_ic(
                                scores[identity][i],
                                scores[other][i],
                                config.economics.minimum_breadth,
                            )
                            for other in ids
                            if other != identity
                        },
                    }
                )
            for arm in arms:
                gated = (
                    targets
                    if arm == "global"
                    else [
                        target if state.state == int(arm.removeprefix("state_")) else {}
                        for target, state in zip(targets, states, strict=True)
                    ]
                )
                for cost in config.economics.cost_bps:
                    economics[identity][arm][str(cost)].append(
                        simulate_session(prices, gated, config.economics, cost_bps=cost)
                        if any(b.is_complete for a in assets for b in a.bars)
                        else {
                            "resolved": False,
                            "reason": "NO_COMPLETE_OHLCV_SESSION",
                            "net_return": None,
                        }
                    )
    reports = []
    for identity in ids:
        frames = records[identity]
        summaries = {}
        for arm in arms:
            weights = [
                1.0
                if arm == "global"
                else (
                    r["state_probabilities"][int(arm.removeprefix("state_"))]
                    if r["state_probabilities"] is not None
                    else 0.0
                )
                for r in frames
            ]

            summaries[arm] = {
                "observation_weight": math.fsum(weights),
                "coverage": _weighted(
                    [(r["coverage"], w) for r, w in zip(frames, weights, strict=True)]
                ),
                "turnover": _weighted(
                    [(r["turnover"], w) for r, w in zip(frames, weights, strict=True)]
                ),
                "decay_rank_ic": {
                    str(h * 15): _weighted(
                        [(r["decay"][str(h * 15)], w) for r, w in zip(frames, weights, strict=True)]
                    )
                    for h in config.decay_bars
                },
                "decay_observation_weight": {
                    str(h * 15): math.fsum(
                        w
                        for r, w in zip(frames, weights, strict=True)
                        if r["decay"][str(h * 15)] is not None
                    )
                    for h in config.decay_bars
                },
                "rank_similarity": {
                    other: _weighted(
                        [(r["similarity"][other], w) for r, w in zip(frames, weights, strict=True)]
                    )
                    for other in ids
                    if other != identity
                },
                "economic_scenarios": {
                    cost: summarize_sessions(rows)
                    for cost, rows in economics[identity][arm].items()
                },
            }
        report: dict[str, Any] = {
            "version": "finagent.factor-evaluation.v1",
            "factor_id": identity,
            "model_id": model.model_id,
            "source_id": model.source.identity,
            "source": asdict(model.source),
            "implementation_id": evaluation_implementation_id(),
            "window": {"start": utc_text(window.start), "end": utc_text(window.end)},
            "available_at": utc_text(window.end),
            "config": asdict(config),
            "compiled_batch_id": compiled.batch_id,
            "session_content_ids": session_digests,
            "global": summaries["global"],
            "by_market_state": {k: v for k, v in summaries.items() if k != "global"},
            "frames": frames,
            "state_available_frames": sum(r["state_probabilities"] is not None for r in frames),
            "state_unavailable_frames": sum(r["state_probabilities"] is None for r in frames),
            "conditioning": "soft_probability_weighted_IC_coverage_decay_similarity",
            "turnover_definition": "mean_L1_change_in_positive_selection_targets; session_start_cash; excludes_forced_exit",
            "economic_conditioning": "fixed_argmax_state_entry_gate; full_sessions_including_cash; exits_never_gated",
            "outcome_definition": "same_session_complete_15m_close_simple_return; horizon_minutes; outcomes_not_features",
            "cost_scope": "hypothetical_broker_neutral_cost_per_traded_notional; not_measured_executable_quotes",
            "inference": "descriptive_development_only_overlapping_outcomes_no_significance",
            "alpha_authority": False,
            "paper_authority": False,
            "live_authority": False,
        }
        report["evaluation_id"] = _canonical_hash(report, prefix="factor-evaluation")
        reports.append(report)
    return tuple(reports)

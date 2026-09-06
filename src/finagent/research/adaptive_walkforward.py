"""Sequential fold-local deterministic allocation on the existing research clock."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import pairwise
from typing import Any

from finagent.domain._validation import require_aware_datetime, require_non_empty
from finagent.domain.research import TimeRange
from finagent.research.adaptive_inputs import DevelopmentPanelSource
from finagent.research.adaptive_portfolio_evaluation import (
    materialize_session_signals,
    observe_completed_session,
    run_session_economics,
    session_identity,
    strategy_summary,
)
from finagent.research.factor_allocators import AllocatorType, DeterministicFactorAllocator
from finagent.research.factor_library import FactorRegistration
from finagent.research.factor_performance import (
    NORMALIZATION,
    SUPPORT_RULE,
    FactorPerformanceHistory,
    QualityConfig,
    combine_factor_signals,
    fixed_exposure_targets,
)
from finagent.research.market_state import (
    MarketFeatureConfig,
    MarketFeatures,
    MarketStateRow,
    build_market_features,
    utc_text,
)
from finagent.research.market_state_gmm import GMMConfig, fit_market_state, project_market_state
from finagent.research.ridge_meta_allocator import RidgeConfig, fit_ridge_meta
from finagent.research.us_a1_factor_materialization import compile_factor_graph_batch
from finagent.research.us_baselines import _canonical_hash
from finagent.research.us_r3_economics import EconomicPolicy


@dataclass(frozen=True)
class WalkForwardFold:
    name: str
    train: TimeRange
    state_fit_end: datetime
    evaluation: TimeRange

    def __post_init__(self) -> None:
        require_non_empty(self.name, "fold name")
        require_aware_datetime(self.state_fit_end, "state fit cutoff")
        if not self.train.start < self.state_fit_end < self.train.end <= self.evaluation.start:
            raise ValueError(
                "fold requires train.start < state_fit_end < train.end <= evaluation.start"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "train": {"start": utc_text(self.train.start), "end": utc_text(self.train.end)},
            "state_fit_end": utc_text(self.state_fit_end),
            "evaluation": {
                "start": utc_text(self.evaluation.start),
                "end": utc_text(self.evaluation.end),
            },
            "window_semantics": "start_inclusive_end_exclusive",
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> WalkForwardFold:
        return cls(
            row["name"],
            TimeRange(*(datetime.fromisoformat(row["train"][k]) for k in ("start", "end"))),
            datetime.fromisoformat(row["state_fit_end"]),
            TimeRange(*(datetime.fromisoformat(row["evaluation"][k]) for k in ("start", "end"))),
        )


def validate_walkforward(
    factors: tuple[FactorRegistration, ...],
    folds: tuple[WalkForwardFold, ...],
    economics: EconomicPolicy,
) -> None:
    if not 2 <= len(folds) <= 12 or len({f.name for f in folds}) != len(folds):
        raise ValueError("walk-forward requires 2..12 uniquely named folds")
    if any(
        a.evaluation.end > b.evaluation.start or a.train.start > b.train.start
        for a, b in pairwise(folds)
    ):
        raise ValueError(
            "folds must progress chronologically with nonoverlapping evaluation windows"
        )
    if not 2 <= len(factors) <= 20 or len({f.factor_id for f in factors}) != len(factors):
        raise ValueError("a fixed unique pool of 2..20 factors is required")
    if any(f.created_at > folds[0].train.start for f in factors):
        raise ValueError("factor definitions must be frozen before first TRAIN")
    if (
        economics.execution_profile != "strict_15m"
        or economics.holding_bars != 4
        or economics.delay_bars != 1
    ):
        raise ValueError("this slice freezes strict_15m, one-bar delay and four-bar holding")
    if economics.cost_bps != (0.0, 1.0, 5.0, 10.0):
        raise ValueError("all arms require the same frozen 0/1/5/10bp grid")


def evaluate_walkforward_fold(
    source: DevelopmentPanelSource,
    factors: tuple[FactorRegistration, ...],
    fold: WalkForwardFold,
    features: MarketFeatureConfig,
    gmm: GMMConfig,
    quality: QualityConfig,
    ridge: RidgeConfig,
    economics: EconomicPolicy,
) -> dict[str, Any]:
    """Fit anew, then evaluate one session at a time; never precompute fold PnL/IC.

    A frozen prefix of TRAIN fits GMM. Remaining TRAIN sessions can therefore
    carry states that really existed at their decisions; no fitted-state backfill.
    Prefix performance can seed non-state quality, but has unavailable states.
    """
    ids = tuple(sorted(f.factor_id for f in factors))
    compiled = compile_factor_graph_batch(
        tuple(f.graph for f in factors), admit_panel_operators=True
    )
    train = source.read(fold.train)
    prefix = tuple(s for s in train if s[0].bars[-1].available_at <= fold.state_fit_end)
    if (
        not prefix
        or len(prefix) == len(train)
        or any(
            s[0].bars[0].event_time < fold.state_fit_end < s[0].bars[-1].available_at for s in train
        )
    ):
        raise ValueError(
            "state fit prefix and calibration must contain complete separate TRAIN sessions"
        )
    train_features = MarketFeatures(
        source.identity,
        features,
        tuple(
            row
            for session in prefix
            for row in build_market_features(session, source.identity, features).rows
        ),
    )
    state_model = fit_market_state(
        train_features, TimeRange(fold.train.start, fold.state_fit_end), config=gmm
    )
    context_id = str(
        _canonical_hash(
            {
                "fold": fold.to_dict(),
                "batch_id": compiled.batch_id,
                "economics": asdict(economics),
                "normalization": NORMALIZATION,
                "support_rule": SUPPORT_RULE,
            },
            prefix="adaptive-fold-context",
        )
    )
    history = FactorPerformanceHistory()
    train_content = []
    for session in train:
        close = session[0].bars[-1].available_at
        states = project_market_state(
            state_model, build_market_features(session, source.identity, features), as_of=close
        )
        signals = materialize_session_signals(compiled, session, economics)
        content_id = session_identity(session)
        train_content.append(content_id)
        observations = observe_completed_session(
            session,
            signals,
            states,
            economics,
            source_id=source.identity.identity,
            evaluation_id=context_id + ":" + content_id,
            as_of=close,
        )
        history = history.append(observations, as_of=close)
    initial_history_id = history.identity
    ridge_model = fit_ridge_meta(ids, history, fold.train, quality, ridge)
    allocators = {
        kind.value: DeterministicFactorAllocator(
            kind, quality, ridge_model if kind is AllocatorType.RIDGE_META else None
        )
        for kind in AllocatorType
    }
    series: dict[str, list[dict[str, Any]]] = {arm: [] for arm in allocators}
    economic_rows: dict[str, dict[str, list[dict[str, object]]]] = {
        arm: {str(cost): [] for cost in economics.cost_bps} for arm in allocators
    }
    session_states: list[tuple[MarketStateRow, ...]] = []
    evaluation_content, session_ids = [], []
    # The bounded adapter may read OHLCV panels in one batch. Only this current
    # session is materialized/evaluated; no future-fold or future-session metrics
    # exist in the allocator input, and current-session releases are appended last.
    evaluation = source.read(fold.evaluation)
    for session in evaluation:
        bars = session[0].bars
        session_id, open_at, close = bars[0].session_id, bars[0].event_time, bars[-1].available_at
        past = history.available(as_of=open_at).trailing(quality.lookback_sessions)
        signals = materialize_session_signals(compiled, session, economics)
        states = project_market_state(
            state_model, build_market_features(session, source.identity, features), as_of=close
        )
        session_states.append(states)
        session_ids.append(session_id)
        targets: dict[str, list[dict[str, float]]] = {arm: [] for arm in allocators}
        for bar, frame, state in zip(bars, signals, states, strict=True):
            signal_id = str(_canonical_hash(frame, prefix="normalized-factor-frame"))
            for arm, allocator in allocators.items():
                snapshot = allocator.allocate(
                    ids,
                    past,
                    as_of=bar.available_at,
                    session_id=session_id,
                    session_open=open_at,
                    market_state=state,
                )
                combined = combine_factor_signals(frame, dict(snapshot.weights))
                target = fixed_exposure_targets(combined, economics)
                targets[arm].append(target)
                series[arm].append(
                    {
                        **snapshot.to_dict(),
                        "normalized_signal_id": signal_id,
                        "target": target,
                        "common_asset_count": len(combined),
                        "data_fallback_reason": "INSUFFICIENT_COMMON_FACTOR_SUPPORT"
                        if len(combined) < economics.minimum_breadth
                        else None,
                        "market_state_available": state.probabilities is not None,
                    }
                )
        for arm in allocators:
            for cost in economics.cost_bps:
                economic_rows[arm][str(cost)].append(
                    run_session_economics(session, targets[arm], economics, cost)
                )
        content_id = session_identity(session)
        evaluation_content.append(content_id)
        observations = observe_completed_session(
            session,
            signals,
            states,
            economics,
            source_id=source.identity.identity,
            evaluation_id=context_id + ":" + content_id,
            as_of=close,
        )
        history = history.append(observations, as_of=close)
    releases = tuple(r for r in history.observations if r.session_id in session_ids)
    availability = {
        "released_factor_sessions": len(releases),
        "unavailable_session_rank_ic": sum(r.rank_ic is None for r in releases),
        "unavailable_standalone_5bp_return": sum(
            r.standalone_5bp_net_return is None for r in releases
        ),
        "outside_allowed_holding_horizon_decisions": sum(
            d.outcome_available_at is None for r in releases for d in r.decisions
        ),
        "unavailable_within_horizon_decision_ic": sum(
            d.outcome_available_at is not None and d.rank_ic is None
            for r in releases
            for d in r.decisions
        ),
    }
    return {
        "fold": fold.to_dict(),
        "source_id": source.identity.identity,
        "factor_ids": ids,
        "normalization": NORMALIZATION,
        "support_rule": SUPPORT_RULE,
        "state_model": state_model.to_dict(),
        "ridge_model": {**ridge_model.to_dict(), "model_id": ridge_model.model_id},
        "initial_history_id": initial_history_id,
        "train_session_content_ids": train_content,
        "evaluation_session_content_ids": evaluation_content,
        "performance_history": [r.to_dict() for r in history.observations],
        "market_states": [[s.to_dict() for s in day] for day in session_states],
        "arms": {
            arm: {
                "allocator": allocator.to_dict(),
                "factor_weight_series": series[arm],
                "cost_scenarios": {
                    cost: {
                        **strategy_summary(
                            rows, session_states, series[arm], state_model.config.n_components
                        ),
                        "performance_availability": availability,
                        "sessions": [
                            {
                                "session_id": session_id,
                                **{k: v for k, v in row.items() if k != "ledger"},
                            }
                            for session_id, row in zip(session_ids, rows, strict=True)
                        ],
                    }
                    for cost, rows in economic_rows[arm].items()
                },
            }
            for arm, allocator in allocators.items()
        },
        "execution_policy": asdict(economics),
        "schedule": "rolling_sleeves",
        "gross_exposure_rule": "same_unit_NAV_sleeve_budget_for_all_arms; no_timing",
        "purge_embargo": "complete_sessions; delayed_labels_and_held_positions_mature_within_session; release_at_close; train_releases_before_evaluation_open",
        "inference": "development_descriptive_only_no_significance_gate",
        "alpha_authority": False,
        "paper_authority": False,
        "live_authority": False,
    }


def summarize_folds(folds: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for arm in folds[0]["arms"]:
        result[arm] = {}
        for cost in folds[0]["arms"][arm]["cost_scenarios"]:
            values = [
                (
                    fold["fold"]["name"],
                    fold["arms"][arm]["cost_scenarios"][cost]["compounded_return"],
                )
                for fold in folds
            ]
            usable = [(name, value) for name, value in values if value is not None]
            complete = len(usable) == len(folds)
            result[arm][cost] = {
                "fold_count": len(folds),
                "evaluable_fold_count": len(usable),
                "mean_fold_compounded_return": math.fsum(v for _, v in usable) / len(usable)
                if complete
                else None,
                "worst_fold": min(usable, key=lambda x: x[1])[0] if complete else None,
                "worst_fold_compounded_return": min(v for _, v in usable) if complete else None,
                "interpretation": "arithmetic_fold_comparison; independent_fold_initial_NAV; not_stitched_investable_NAV",
            }
    return result

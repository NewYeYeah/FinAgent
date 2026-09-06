"""Causal, immutable session releases of factor performance; no second ledger.

Each session release retains its decision-level IC/state pairs. A session's net
return is stored once, never copied onto each bar or attributed to a later state.
All rows enter allocator history only when that complete session has finished.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from typing import Any, cast

from finagent.domain._validation import require_aware_datetime, require_non_empty
from finagent.research.market_state import utc_text
from finagent.research.us_baseline_evaluation import _average_ranks
from finagent.research.us_baselines import _canonical_hash
from finagent.research.us_r3_economics import EconomicPolicy, positive_weights

NORMALIZATION = "same_bar_average_rank; 2*(rank-1)/(N-1)-1; missing_excluded; N>=2"
SUPPORT_RULE = "intersection_of_all_frozen_factors_before_ranking; independent_of_allocator_weights"


def normalize_factor_signal(raw: Mapping[str, float | None]) -> dict[str, float]:
    valid = {asset: value for asset, value in raw.items() if value is not None}
    if any(not math.isfinite(value) for value in valid.values()):
        raise ValueError("factor signals must be finite or explicitly missing")
    if len(valid) < 2:
        return {}
    ranks = _average_ranks(valid)
    return {asset: 2 * (ranks[asset] - 1) / (len(valid) - 1) - 1 for asset in sorted(valid)}


def combine_factor_signals(
    signals: Mapping[str, Mapping[str, float]], weights: Mapping[str, float]
) -> dict[str, float]:
    if not signals or signals.keys() != weights.keys():
        raise ValueError("signals and factor weights must have identical nonempty factor IDs")
    if any(not math.isfinite(w) or w < 0 for w in weights.values()) or not math.isclose(
        math.fsum(weights.values()), 1.0, abs_tol=1e-12
    ):
        raise ValueError("factor weights must be nonnegative and sum to one")
    common = set.intersection(*(set(row) for row in signals.values()))
    return {
        asset: math.fsum(weights[f] * signals[f][asset] for f in sorted(weights))
        for asset in sorted(common)
    }


def fixed_exposure_targets(scores: Mapping[str, float], policy: EconomicPolicy) -> dict[str, float]:
    if any(not math.isfinite(v) or abs(v) > 1 + 1e-12 for v in scores.values()):
        raise ValueError("expected centered normalized combined scores")
    # A fixed positive offset preserves ordering and selects exactly top K even
    # for tied/negative scores. Allocators cannot create cash timing via sign.
    return cast(
        dict[str, float],
        positive_weights({asset: score + 2 for asset, score in scores.items()}, policy),
    )


@dataclass(frozen=True)
class FactorDecisionIC:
    decision_time: datetime
    outcome_available_at: datetime | None
    rank_ic: float | None
    state_probabilities: tuple[float, ...] | None = None
    market_state_model_id: str | None = None

    def __post_init__(self) -> None:
        require_aware_datetime(self.decision_time, "decision_time")
        if self.outcome_available_at is not None:
            require_aware_datetime(self.outcome_available_at, "outcome_available_at")
            if self.outcome_available_at <= self.decision_time:
                raise ValueError("IC outcome must follow its decision")
        if self.rank_ic is not None and (
            self.outcome_available_at is None
            or not math.isfinite(self.rank_ic)
            or abs(self.rank_ic) > 1 + 1e-12
        ):
            raise ValueError("invalid IC/outcome availability")
        if self.state_probabilities is not None and (
            not self.market_state_model_id
            or not self.state_probabilities
            or any(not math.isfinite(p) or p < 0 or p > 1 for p in self.state_probabilities)
            or not math.isclose(math.fsum(self.state_probabilities), 1, abs_tol=1e-12)
        ):
            raise ValueError("invalid historical decision-state probabilities")

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_time": utc_text(self.decision_time),
            "outcome_available_at": utc_text(self.outcome_available_at)
            if self.outcome_available_at
            else None,
            "rank_ic": self.rank_ic,
            "state_probabilities": self.state_probabilities,
            "market_state_model_id": self.market_state_model_id,
        }


@dataclass(frozen=True)
class FactorPerformanceObservation:
    factor_id: str
    decision_time: datetime  # first covered formation; decisions below retain exact clocks
    outcome_available_at: datetime  # full-session release, including standalone economics
    session_id: str
    rank_ic: float | None
    standalone_5bp_net_return: float | None
    decisions: tuple[FactorDecisionIC, ...]
    source_id: str
    evaluation_id: str
    missing_signal_frames: int = 0

    def __post_init__(self) -> None:
        for name in ("factor_id", "session_id", "source_id", "evaluation_id"):
            require_non_empty(getattr(self, name), name)
        require_aware_datetime(self.decision_time, "decision_time")
        require_aware_datetime(self.outcome_available_at, "outcome_available_at")
        if self.outcome_available_at <= self.decision_time:
            raise ValueError("session outcome must follow its first decision")
        if not self.decisions or self.decisions[0].decision_time != self.decision_time:
            raise ValueError("session release must bind its actual decisions")
        if any(
            a.decision_time >= b.decision_time for a, b in zip(self.decisions, self.decisions[1:])
        ):
            raise ValueError("decision history must be strictly chronological")
        if any(
            d.decision_time > self.outcome_available_at
            or (
                d.outcome_available_at is not None
                and d.outcome_available_at > self.outcome_available_at
            )
            for d in self.decisions
        ):
            raise ValueError("session release precedes covered decisions/outcomes")
        usable = [d.rank_ic for d in self.decisions if d.rank_ic is not None]
        expected = math.fsum(usable) / len(usable) if usable else None
        if self.rank_ic != expected:
            raise ValueError("session IC must aggregate the retained decision ICs")
        if self.standalone_5bp_net_return is not None and (
            not math.isfinite(self.standalone_5bp_net_return) or self.standalone_5bp_net_return < -1
        ):
            raise ValueError("invalid standalone return")
        if not 0 <= self.missing_signal_frames <= len(self.decisions):
            raise ValueError("invalid missing-signal count")

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "decision_time": utc_text(self.decision_time),
            "outcome_available_at": utc_text(self.outcome_available_at),
            "session_id": self.session_id,
            "rank_ic": self.rank_ic,
            "standalone_5bp_net_return": self.standalone_5bp_net_return,
            "decisions": [d.to_dict() for d in self.decisions],
            "source_id": self.source_id,
            "evaluation_id": self.evaluation_id,
            "missing_signal_frames": self.missing_signal_frames,
            "release_clock": "completed_session_only",
        }


@dataclass(frozen=True)
class FactorPerformanceHistory:
    observations: tuple[FactorPerformanceObservation, ...] = ()

    def __post_init__(self) -> None:
        keys = [(r.outcome_available_at, r.session_id, r.factor_id) for r in self.observations]
        if keys != sorted(keys) or len(
            {(r.factor_id, r.session_id) for r in self.observations}
        ) != len(keys):
            raise ValueError("performance history must be ordered and unique by factor/session")
        if len({r.source_id for r in self.observations}) > 1:
            raise ValueError("performance history cannot mix source identities")
        session_clocks: dict[str, tuple[datetime, datetime]] = {}
        for row in self.observations:
            clock = (row.decision_time, row.outcome_available_at)
            if session_clocks.setdefault(row.session_id, clock) != clock:
                raise ValueError("factor session clocks disagree")

    def available(self, *, as_of: datetime) -> FactorPerformanceHistory:
        require_aware_datetime(as_of, "history as_of")
        if self.cutoff is None or self.cutoff <= as_of:
            return self
        return FactorPerformanceHistory(
            tuple(r for r in self.observations if r.outcome_available_at <= as_of)
        )

    def append(
        self, observations: tuple[FactorPerformanceObservation, ...], *, as_of: datetime
    ) -> FactorPerformanceHistory:
        require_aware_datetime(as_of, "history append as_of")
        if any(r.outcome_available_at > as_of for r in observations):
            raise ValueError("cannot append performance before session outcome is available")
        return FactorPerformanceHistory(self.observations + observations)

    def trailing(self, sessions: int) -> FactorPerformanceHistory:
        if sessions < 1:
            raise ValueError("positive session lookback required")
        ordered = list(dict.fromkeys(r.session_id for r in self.observations))
        if len(ordered) <= sessions:
            return self
        ordered = ordered[-sessions:]
        return FactorPerformanceHistory(
            tuple(r for r in self.observations if r.session_id in ordered)
        )

    @cached_property
    def cutoff(self) -> datetime | None:
        return max((r.outcome_available_at for r in self.observations), default=None)

    @cached_property
    def identity(self) -> str:
        return str(
            _canonical_hash(
                [r.to_dict() for r in self.observations], prefix="factor-performance-history"
            )
        )


@dataclass(frozen=True)
class QualityConfig:
    lookback_sessions: int = 20
    minimum_observations: int = 5

    def __post_init__(self) -> None:
        if any(
            type(v) is not int for v in (self.lookback_sessions, self.minimum_observations)
        ) or not (2 <= self.minimum_observations <= self.lookback_sessions <= 252):
            raise ValueError("require 2 <= minimum observations <= session lookback <= 252")


def performance_features(
    factor_id: str, history: FactorPerformanceHistory, config: QualityConfig
) -> tuple[float, float] | None:
    rows = [
        r
        for r in history.trailing(config.lookback_sessions).observations
        if r.factor_id == factor_id
    ]
    ic = [r.rank_ic for r in rows if r.rank_ic is not None]
    net = [r.standalone_5bp_net_return for r in rows if r.standalone_5bp_net_return is not None]
    if min(len(ic), len(net)) < config.minimum_observations:
        return None
    return math.fsum(ic) / len(ic), 10000 * math.fsum(net) / len(net)

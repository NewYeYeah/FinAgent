"""Five small deterministic factor-weight baselines, with explicit causal inputs."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from finagent.domain._validation import require_aware_datetime
from finagent.research.factor_performance import (
    FactorPerformanceHistory,
    QualityConfig,
    performance_features,
)
from finagent.research.market_state import MarketStateRow, utc_text
from finagent.research.ridge_meta_allocator import RidgeMetaModel
from finagent.research.us_baselines import _canonical_hash


class AllocatorType(StrEnum):
    EQUAL_WEIGHT = "equal_weight"
    ROLLING_IC = "rolling_ic"
    ROLLING_NET_RETURN = "rolling_net_return"
    REGIME_CONDITIONAL = "regime_conditional"
    RIDGE_META = "ridge_meta"


@dataclass(frozen=True)
class FactorWeightSnapshot:
    allocator_id: str
    allocator_type: AllocatorType
    config_json: str
    as_of: datetime
    session_id: str
    session_open: datetime
    weights: tuple[tuple[str, float], ...]
    history_cutoff: datetime | None
    history_id: str
    market_state_model_id: str | None
    state_probabilities: tuple[float, ...] | None
    fallback_reason: str | None
    state_weights: tuple[tuple[float, ...], ...] = ()
    quality: tuple[float | None, ...] = ()

    def __post_init__(self) -> None:
        require_aware_datetime(self.as_of, "allocator as_of")
        require_aware_datetime(self.session_open, "session_open")
        if self.as_of <= self.session_open:
            raise ValueError("decision must follow session open")
        if self.history_cutoff is not None:
            require_aware_datetime(self.history_cutoff, "history cutoff")
            if self.history_cutoff > self.session_open:
                raise ValueError("allocator history must precede the current session")
        ids = tuple(f for f, _ in self.weights)
        if not ids or tuple(sorted(set(ids))) != ids:
            raise ValueError("factor weights require canonical unique IDs")
        if any(not math.isfinite(w) or w < 0 for _, w in self.weights) or not math.isclose(
            math.fsum(w for _, w in self.weights), 1, abs_tol=1e-12
        ):
            raise ValueError("factor weights must be nonnegative and sum to one")

    def to_dict(self) -> dict[str, Any]:
        return {
            "allocator_id": self.allocator_id,
            "allocator_type": self.allocator_type.value,
            "config": json.loads(self.config_json),
            "as_of": utc_text(self.as_of),
            "session_id": self.session_id,
            "session_open": utc_text(self.session_open),
            "factor_ids": [f for f, _ in self.weights],
            "weights": dict(self.weights),
            "history_cutoff": utc_text(self.history_cutoff) if self.history_cutoff else None,
            "history_id": self.history_id,
            "market_state_model_id": self.market_state_model_id,
            "state_probabilities": self.state_probabilities,
            "fallback_reason": self.fallback_reason,
            "state_weights": self.state_weights,
            "quality": self.quality,
        }


class FactorAllocator(Protocol):
    def allocate(
        self,
        factor_ids: tuple[str, ...],
        history: FactorPerformanceHistory,
        *,
        as_of: datetime,
        session_id: str,
        session_open: datetime,
        market_state: MarketStateRow | None = None,
    ) -> FactorWeightSnapshot: ...


def _positive_or_equal(values: tuple[float | None, ...]) -> tuple[tuple[float, ...], bool]:
    quality = tuple(max(v, 0) if v is not None else 0.0 for v in values)
    mass = math.fsum(quality)
    return (
        (tuple(v / mass for v in quality), False)
        if mass > 0
        else ((1 / len(values),) * len(values), True)
    )


@dataclass(frozen=True)
class DeterministicFactorAllocator:
    kind: AllocatorType
    config: QualityConfig
    ridge_model: RidgeMetaModel | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AllocatorType):
            raise TypeError("explicit allocator type required")
        if (self.kind is AllocatorType.RIDGE_META) != (self.ridge_model is not None):
            raise ValueError("only Ridge allocators require a fitted train model")
        if self.ridge_model is not None and self.config != self.ridge_model.quality_config:
            raise ValueError("Ridge feature/history configuration mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "finagent.factor-allocator.v1",
            "allocator_type": self.kind.value,
            **asdict(self.config),
            "quality_transform": "max(mean_or_prediction,0); normalize",
            "fallback": "EqualWeight; never_cash",
            "history_clock": "previous_completed_sessions",
            "regime_metric": "decision_RankIC_weighted_by_then_available_state_probability",
            "ridge_model_id": self.ridge_model.model_id if self.ridge_model else None,
            "ridge_config": asdict(self.ridge_model.config) if self.ridge_model else None,
        }

    @property
    def allocator_id(self) -> str:
        return str(_canonical_hash(self.to_dict(), prefix="factor-allocator"))

    def allocate(
        self,
        factor_ids: tuple[str, ...],
        history: FactorPerformanceHistory,
        *,
        as_of: datetime,
        session_id: str,
        session_open: datetime,
        market_state: MarketStateRow | None = None,
    ) -> FactorWeightSnapshot:
        if not factor_ids or tuple(sorted(set(factor_ids))) != factor_ids:
            raise ValueError("allocator requires sorted unique factor IDs")
        require_aware_datetime(as_of, "allocator as_of")
        if session_open >= as_of:
            raise ValueError("session open must precede decision")
        available = (
            FactorPerformanceHistory()
            if self.kind is AllocatorType.EQUAL_WEIGHT
            else history.available(as_of=session_open).trailing(self.config.lookback_sessions)
        )
        if any(r.factor_id not in factor_ids for r in available.observations):
            raise ValueError("history contains a factor outside the frozen pool")
        values: tuple[float | None, ...] = ()
        weights = (1 / len(factor_ids),) * len(factor_ids)
        reason = None
        probabilities = None
        model_id = None
        state_weights: tuple[tuple[float, ...], ...] = ()
        if self.kind in (AllocatorType.ROLLING_IC, AllocatorType.ROLLING_NET_RETURN):
            metric = (
                "rank_ic" if self.kind is AllocatorType.ROLLING_IC else "standalone_5bp_net_return"
            )
            qualities = []
            for factor in factor_ids:
                observations = [
                    getattr(r, metric)
                    for r in available.observations
                    if r.factor_id == factor and getattr(r, metric) is not None
                ]
                qualities.append(
                    math.fsum(observations) / len(observations)
                    if len(observations) >= self.config.minimum_observations
                    else None
                )
            values = tuple(qualities)
            weights, fallback = _positive_or_equal(values)
            reason = "INSUFFICIENT_OR_NONPOSITIVE_QUALITY" if fallback else None
        elif self.kind is AllocatorType.REGIME_CONDITIONAL:
            if market_state is not None and (
                market_state.available_at != as_of or market_state.session_id != session_id
            ):
                raise ValueError("current state must match this decision/session")
            if market_state is None or market_state.probabilities is None:
                reason = "CURRENT_MARKET_STATE_UNAVAILABLE"
            else:
                probabilities, model_id = market_state.probabilities, market_state.model_id
                components, failed = [], []
                for state in range(len(probabilities)):
                    qualities = []
                    for factor in factor_ids:
                        pairs = []
                        observed_sessions = set()
                        for row in available.observations:
                            if row.factor_id != factor:
                                continue
                            for decision in row.decisions:
                                p = decision.state_probabilities
                                if p is None or decision.rank_ic is None:
                                    continue
                                if decision.market_state_model_id != model_id or len(p) != len(
                                    probabilities
                                ):
                                    raise ValueError(
                                        "historical states belong to a different fold model"
                                    )
                                if p[state] > 0:
                                    pairs.append((decision.rank_ic, p[state]))
                                    observed_sessions.add(row.session_id)
                        mass = math.fsum(p for _, p in pairs)
                        qualities.append(
                            math.fsum(ic * p for ic, p in pairs) / mass
                            if mass > 1e-12
                            and len(observed_sessions) >= self.config.minimum_observations
                            else None
                        )
                    component, fallback = _positive_or_equal(tuple(qualities))
                    components.append(component)
                    if fallback and probabilities[state] > 0:
                        failed.append(str(state))
                state_weights = tuple(components)
                weights = tuple(
                    math.fsum(p * w[j] for p, w in zip(probabilities, components, strict=True))
                    for j in range(len(factor_ids))
                )
                reason = "STATE_COMPONENT_EQUAL_FALLBACK:" + ",".join(failed) if failed else None
        elif self.kind is AllocatorType.RIDGE_META:
            model = self.ridge_model
            assert model is not None
            if model.factor_ids != factor_ids or model.available_at > session_open:
                raise ValueError("Ridge model pool/availability mismatch")
            if available.observations and model.source_id != available.observations[0].source_id:
                raise ValueError("Ridge model source mismatch")
            if model.fallback_reason:
                reason = model.fallback_reason
            else:
                values = tuple(
                    model.predict(features)
                    if (features := performance_features(factor, available, self.config))
                    is not None
                    else None
                    for factor in factor_ids
                )
                weights, fallback = _positive_or_equal(values)
                reason = "INSUFFICIENT_OR_NONPOSITIVE_RIDGE_PREDICTION" if fallback else None
        return FactorWeightSnapshot(
            self.allocator_id,
            self.kind,
            json.dumps(self.to_dict(), sort_keys=True),
            as_of,
            session_id,
            session_open,
            tuple(zip(factor_ids, weights, strict=True)),
            available.cutoff,
            available.identity,
            model_id,
            probabilities,
            reason,
            state_weights,
            values,
        )

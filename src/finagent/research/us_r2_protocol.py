from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from finagent.research.us_r1_protocol import canonical_us_r1_research_protocol


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _non_empty(value: str, field_name: str) -> str:
    rendered = str(value).strip()
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


class USR2Terminal(StrEnum):
    ROBUST_FACTOR_FAMILY = "ROBUST_FACTOR_FAMILY"
    NO_ROBUST_FACTOR_FAMILY = "NO_ROBUST_FACTOR_FAMILY"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"
    INSUFFICIENT_MULTI_REGIME_DATA = "INSUFFICIENT_MULTI_REGIME_DATA"


class USRegimeFeatureSource(StrEnum):
    MARKET_ANCHOR_RETURN = "MARKET_ANCHOR_RETURN"
    MARKET_ANCHOR_REALIZED_VOLATILITY = "MARKET_ANCHOR_REALIZED_VOLATILITY"
    CROSS_SECTIONAL_DISPERSION = "CROSS_SECTIONAL_DISPERSION"
    CROSS_SECTIONAL_BREADTH = "CROSS_SECTIONAL_BREADTH"


@dataclass(frozen=True, slots=True)
class USRegimeFeatureSpec:
    name: str
    source: USRegimeFeatureSource
    lookback_sessions: int
    availability_lag_sessions: int = 1
    anchor_asset: str | None = None
    schema_version: str = "finagent.us-r2-regime-feature-spec.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _non_empty(self.name, "name"))
        if self.lookback_sessions < 1:
            raise ValueError("regime feature lookback_sessions must be >= 1")
        if self.availability_lag_sessions < 1:
            raise ValueError("regime features must be lagged by at least one completed session")
        needs_anchor = self.source in {
            USRegimeFeatureSource.MARKET_ANCHOR_RETURN,
            USRegimeFeatureSource.MARKET_ANCHOR_REALIZED_VOLATILITY,
        }
        if needs_anchor:
            object.__setattr__(
                self,
                "anchor_asset",
                _non_empty(self.anchor_asset or "", "anchor_asset"),
            )
        elif self.anchor_asset is not None:
            raise ValueError("cross-sectional regime features cannot bind an anchor asset")

    @property
    def feature_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-regime-feature")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "name": self.name,
            "source": self.source.value,
            "lookback_sessions": self.lookback_sessions,
            "availability_lag_sessions": self.availability_lag_sessions,
            "anchor_asset": self.anchor_asset,
            "candidate_performance_input": False,
            "future_label_input": False,
        }
        if include_id:
            payload["feature_id"] = self.feature_id
        return payload


@dataclass(frozen=True, slots=True)
class USRegimeDefinitionPolicy:
    features: tuple[USRegimeFeatureSpec, ...]
    minimum_distinct_regimes: int = 2
    classification_clock: str = "PRIOR_SESSION_CLOSE"
    threshold_fit_scope: str = "TRAIN_ONLY"
    schema_version: str = "finagent.us-r2-regime-definition-policy.v1"

    def __post_init__(self) -> None:
        if not self.features:
            raise ValueError("regime definition policy requires ex-ante observable features")
        feature_ids = tuple(item.feature_id for item in self.features)
        names = tuple(item.name for item in self.features)
        if len(feature_ids) != len(set(feature_ids)) or len(names) != len(set(names)):
            raise ValueError("regime definition features must be structurally unique")
        if self.minimum_distinct_regimes < 2:
            raise ValueError("multi-regime policy requires at least two distinct regimes")
        if self.classification_clock != "PRIOR_SESSION_CLOSE":
            raise ValueError("US-R2 v1 regime classification is prior-session-close only")
        if self.threshold_fit_scope != "TRAIN_ONLY":
            raise ValueError("US-R2 regime thresholds must be fit on training evidence only")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-regime-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "features": [item.to_dict() for item in self.features],
            "minimum_distinct_regimes": self.minimum_distinct_regimes,
            "classification_clock": self.classification_clock,
            "threshold_fit_scope": self.threshold_fit_scope,
            "candidate_performance_inputs_allowed": False,
            "candidate_rank_ic_inputs_allowed": False,
            "candidate_pvalue_inputs_allowed": False,
            "future_label_inputs_allowed": False,
            "evaluation_fold_fit_allowed": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


@dataclass(frozen=True, slots=True)
class USMultiRegimeFold:
    fold_id: str
    train_start: date
    train_end: date
    evaluation_start: date
    evaluation_end: date
    expected_regimes: tuple[str, ...]
    schema_version: str = "finagent.us-r2-multi-regime-fold.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "fold_id", _non_empty(self.fold_id, "fold_id"))
        if not self.train_start < self.train_end <= self.evaluation_start < self.evaluation_end:
            raise ValueError(
                "fold windows require train_start < train_end <= evaluation_start < evaluation_end"
            )
        regimes = tuple(
            sorted(dict.fromkeys(_non_empty(item, "expected_regimes[]") for item in self.expected_regimes))
        )
        if not regimes:
            raise ValueError("each US-R2 fold must declare at least one expected regime")
        object.__setattr__(self, "expected_regimes", regimes)

    @property
    def fold_spec_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-fold")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "fold_id": self.fold_id,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "evaluation_start": self.evaluation_start.isoformat(),
            "evaluation_end": self.evaluation_end.isoformat(),
            "expected_regimes": list(self.expected_regimes),
            "window_semantics": "start_inclusive_end_exclusive",
        }
        if include_id:
            payload["fold_spec_id"] = self.fold_spec_id
        return payload


@dataclass(frozen=True, slots=True)
class USMultiRegimeWalkForwardProtocol:
    corpus_id: str
    candidate_denominator_id: str
    r1_protocol_id: str
    regime_policy: USRegimeDefinitionPolicy
    folds: tuple[USMultiRegimeFold, ...]
    schema_version: str = "finagent.us-r2-multi-regime-walk-forward-protocol.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "corpus_id", _non_empty(self.corpus_id, "corpus_id"))
        object.__setattr__(
            self,
            "candidate_denominator_id",
            _non_empty(self.candidate_denominator_id, "candidate_denominator_id"),
        )
        object.__setattr__(self, "r1_protocol_id", _non_empty(self.r1_protocol_id, "r1_protocol_id"))
        r1 = canonical_us_r1_research_protocol()
        if self.r1_protocol_id != r1.protocol_id:
            raise ValueError("US-R2 first replication must preserve the accepted US-R1 protocol")
        if len(self.folds) < 2:
            raise ValueError("US-R2 multi-regime walk-forward requires at least two folds")
        fold_ids = tuple(item.fold_id for item in self.folds)
        if len(fold_ids) != len(set(fold_ids)):
            raise ValueError("US-R2 fold IDs must be unique")
        ordered = tuple(sorted(self.folds, key=lambda item: item.evaluation_start))
        for left, right in zip(ordered, ordered[1:], strict=False):
            if right.evaluation_start < left.evaluation_end:
                raise ValueError("US-R2 evaluation windows cannot overlap")
        observed_regimes = {regime for fold in self.folds for regime in fold.expected_regimes}
        if len(observed_regimes) < self.regime_policy.minimum_distinct_regimes:
            raise ValueError("frozen folds do not cover the policy minimum distinct regimes")

    @property
    def protocol_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-walk-forward")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        r1 = canonical_us_r1_research_protocol()
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "corpus_id": self.corpus_id,
            "candidate_denominator_id": self.candidate_denominator_id,
            "candidate_denominator_preserved": True,
            "performance_filter_applied": False,
            "r1_protocol_id": self.r1_protocol_id,
            "regime_policy": self.regime_policy.to_dict(),
            "fold_count": len(self.folds),
            "folds": [item.to_dict() for item in self.folds],
            "inherited_research_semantics": {
                "primary_interval": r1.primary_interval.value,
                "robustness_intervals": [item.value for item in r1.robustness_intervals],
                "label_name": r1.label_name,
                "label_horizon_trading_minutes": r1.label_horizon_trading_minutes,
                "decay_horizon_trading_minutes": list(r1.decay_horizon_trading_minutes),
                "purge_trading_minutes": r1.purge_trading_minutes,
                "embargo_trading_minutes": r1.embargo_trading_minutes,
                "hac_lags": {
                    "5m": r1.hac_lags_5m,
                    "15m": r1.hac_lags_15m,
                    "30m": r1.hac_lags_30m,
                },
                "bootstrap_samples": r1.bootstrap_samples,
                "bootstrap_block_sessions": r1.bootstrap_block_sessions,
                "multiplicity_methods": list(r1.multiplicity_methods),
                "same_session_only": r1.same_session_only,
                "intraday_flat": r1.intraday_flat,
            },
            "candidate_performance_used_to_define_regimes": False,
            "new_agent_candidates_admitted": False,
            "research_scope": "denominator_preserving_multi_regime_engineering_replication",
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "supports_us_x0_progression": False,
        }
        if include_id:
            payload["protocol_id"] = self.protocol_id
        return payload

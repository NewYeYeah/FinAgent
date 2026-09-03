from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from finagent.domain.market_bars import BarInterval
from finagent.research.us_r1_protocol import canonical_us_r1_research_protocol
from finagent.research.us_r1_walkforward import canonical_us_r1_walk_forward


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class USR1StatisticalEvaluationPolicy:
    research_protocol_id: str
    walk_forward_protocol_id: str
    direction_source_fold_ordinal: int = 1
    direction_signal_interval: BarInterval = BarInterval.MINUTE_15
    direction_label_horizon_trading_minutes: int = 60
    direction_statistic: str = "mean_cross_sectional_rank_ic"
    direction_zero_tie_break: int = 1
    direction_frozen_across_oos_folds: bool = True
    minimum_cross_section: int = 10
    minimum_train_periods: int = 20
    minimum_oos_periods_per_fold: int = 20
    quantile_count: int = 5
    quantile_assignment: str = "stable_equal_count_sorted_by_feature_then_asset"
    long_short_semantics: str = "equal_weight_top_quantile_minus_bottom_quantile"
    turnover_semantics: str = "half_l1_long_short_weight_change_reset_at_session_boundary"
    boundary_label_policy: str = "skip_only_when_all_available_features_target_crosses_session"
    partial_label_policy: str = "omit_entire_formation_cross_section"
    schema_version: str = "finagent.us-r1-statistical-evaluation-policy.v1"

    def __post_init__(self) -> None:
        protocol = canonical_us_r1_research_protocol()
        walk_forward = canonical_us_r1_walk_forward()
        if self.research_protocol_id != protocol.protocol_id:
            raise ValueError("US-R1 evaluation policy/research protocol identity mismatch")
        if self.walk_forward_protocol_id != walk_forward.protocol_id:
            raise ValueError("US-R1 evaluation policy/walk-forward identity mismatch")
        if self.direction_source_fold_ordinal != 1:
            raise ValueError("US-R1 v1 direction must be frozen from fold-1 TRAIN only")
        if self.direction_signal_interval is not BarInterval.MINUTE_15:
            raise ValueError("US-R1 v1 direction source must use 15m TRAIN observations")
        if self.direction_label_horizon_trading_minutes != 60:
            raise ValueError("US-R1 v1 direction source must use the 60m primary label")
        if self.direction_statistic != "mean_cross_sectional_rank_ic":
            raise ValueError("US-R1 v1 direction statistic is frozen to mean cross-sectional RankIC")
        if self.direction_zero_tie_break != 1 or not self.direction_frozen_across_oos_folds:
            raise ValueError("US-R1 v1 freezes one positive-tie direction across every OOS fold")
        if self.minimum_cross_section < 10:
            raise ValueError("US-R1 v1 minimum cross-section must be at least 10 assets")
        if self.minimum_train_periods < 20 or self.minimum_oos_periods_per_fold < 20:
            raise ValueError("US-R1 v1 train/OOS period minima must be at least 20")
        if self.quantile_count != 5:
            raise ValueError("US-R1 v1 quantile diagnostics use exactly five quantiles")
        if self.quantile_assignment != "stable_equal_count_sorted_by_feature_then_asset":
            raise ValueError("US-R1 v1 quantile assignment semantics are frozen")
        if self.long_short_semantics != "equal_weight_top_quantile_minus_bottom_quantile":
            raise ValueError("US-R1 v1 long-short semantics are frozen")
        if self.turnover_semantics != (
            "half_l1_long_short_weight_change_reset_at_session_boundary"
        ):
            raise ValueError("US-R1 v1 turnover semantics are frozen")
        if self.boundary_label_policy != (
            "skip_only_when_all_available_features_target_crosses_session"
        ):
            raise ValueError("US-R1 v1 boundary-label semantics are frozen")
        if self.partial_label_policy != "omit_entire_formation_cross_section":
            raise ValueError("US-R1 v1 partial-label semantics require symmetric complete cases")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-r1-statistical-evaluation-policy",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "research_protocol_id": self.research_protocol_id,
            "walk_forward_protocol_id": self.walk_forward_protocol_id,
            "direction_source_fold_ordinal": self.direction_source_fold_ordinal,
            "direction_signal_interval": self.direction_signal_interval.value,
            "direction_label_horizon_trading_minutes": (
                self.direction_label_horizon_trading_minutes
            ),
            "direction_statistic": self.direction_statistic,
            "direction_zero_tie_break": self.direction_zero_tie_break,
            "direction_frozen_across_oos_folds": self.direction_frozen_across_oos_folds,
            "minimum_cross_section": self.minimum_cross_section,
            "minimum_train_periods": self.minimum_train_periods,
            "minimum_oos_periods_per_fold": self.minimum_oos_periods_per_fold,
            "quantile_count": self.quantile_count,
            "quantile_assignment": self.quantile_assignment,
            "long_short_semantics": self.long_short_semantics,
            "turnover_semantics": self.turnover_semantics,
            "boundary_label_policy": self.boundary_label_policy,
            "partial_label_policy": self.partial_label_policy,
            "selection_semantics": (
                "direction_only_from_fold_01_train_never_from_oos_no_candidate_selection"
            ),
            "status_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


def canonical_us_r1_statistical_evaluation_policy() -> USR1StatisticalEvaluationPolicy:
    return USR1StatisticalEvaluationPolicy(
        research_protocol_id=canonical_us_r1_research_protocol().protocol_id,
        walk_forward_protocol_id=canonical_us_r1_walk_forward().protocol_id,
    )


def validate_us_r1_statistical_evaluation_policy(
    document: dict[str, object],
) -> USR1StatisticalEvaluationPolicy:
    expected = canonical_us_r1_statistical_evaluation_policy()
    if document != expected.to_dict():
        raise ValueError("US-R1 statistical evaluation policy differs from canonical preregistration")
    return expected

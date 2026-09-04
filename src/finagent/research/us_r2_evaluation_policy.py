from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from finagent.research.us_r1_evaluation_policy import (
    canonical_us_r1_statistical_evaluation_policy,
)
from finagent.research.us_r1_gate import canonical_us_r1_alpha_gate_policy
from finagent.research.us_r1_protocol import canonical_us_r1_research_protocol
from finagent.research.us_r2_frozen_protocol import (
    FROZEN_CANDIDATE_DENOMINATOR_ID,
    FROZEN_REGIME_LABELS,
    canonical_us_r2_frozen_protocol,
)


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
class USR2StatisticalEvaluationPolicy:
    frozen_protocol_id: str
    r1_statistical_policy_id: str
    r1_alpha_gate_policy_id: str
    candidate_denominator_id: str = FROZEN_CANDIDATE_DENOMINATOR_ID
    direction_source_fold_id: str = "us-r2-fold-01"
    direction_statistic: str = "mean_cross_sectional_rank_ic"
    direction_zero_tie_break: int = 1
    direction_frozen_across_evaluation_folds: bool = True
    minimum_cross_section: int = 10
    minimum_train_periods: int = 20
    minimum_oos_periods_per_fold_regime: int = 20
    minimum_oos_sessions_per_fold_regime: int = 20
    quantile_count: int = 5
    primary_robustness_cell: str = "fold_x_regime"
    required_fold_count: int = 5
    required_regimes: tuple[str, ...] = FROZEN_REGIME_LABELS
    required_primary_cell_count: int = 20
    regime_primary_threshold_mapping: str = (
        "apply_unchanged_r1_fold_thresholds_to_each_fold_x_regime_primary_cell"
    )
    pooled_inference_semantics: str = (
        "direction_normalized_oos_period_series_across_all_admitted_fold_regime_cells"
    )
    frequency_robustness_semantics: str = (
        "within_each_regime_pool_folds_and_apply_unchanged_r1_5m_15m_30m_sign_consistency_threshold"
    )
    decay_robustness_semantics: str = (
        "within_each_regime_pool_folds_and_apply_unchanged_r1_30m_60m_120m_sign_consistency_threshold"
    )
    schema_version: str = "finagent.us-r2-statistical-evaluation-policy.v1"

    def __post_init__(self) -> None:
        frozen = canonical_us_r2_frozen_protocol()
        r1_stats = canonical_us_r1_statistical_evaluation_policy()
        r1_gate = canonical_us_r1_alpha_gate_policy()
        if self.frozen_protocol_id != frozen.freeze_id:
            raise ValueError("US-R2 evaluation policy must bind the canonical frozen R2 protocol")
        if self.r1_statistical_policy_id != r1_stats.policy_id:
            raise ValueError("US-R2 evaluation policy must inherit the accepted R1 statistics policy")
        if self.r1_alpha_gate_policy_id != r1_gate.policy_id:
            raise ValueError("US-R2 evaluation policy must inherit the accepted R1 Alpha Gate")
        if self.candidate_denominator_id != FROZEN_CANDIDATE_DENOMINATOR_ID:
            raise ValueError("US-R2 evaluation policy must preserve the frozen R1 denominator")
        if self.direction_source_fold_id != frozen.direction_source_fold_id:
            raise ValueError("US-R2 direction source must remain fold-01 TRAIN")
        if self.direction_statistic != frozen.direction_statistic:
            raise ValueError("US-R2 direction statistic differs from the frozen protocol")
        if self.direction_zero_tie_break != r1_stats.direction_zero_tie_break:
            raise ValueError("US-R2 direction zero tie-break must remain the R1 positive tie")
        if not self.direction_frozen_across_evaluation_folds:
            raise ValueError("US-R2 candidate direction must remain frozen across OOS")
        if self.minimum_cross_section != r1_stats.minimum_cross_section:
            raise ValueError("US-R2 minimum cross-section must inherit R1 unchanged")
        if self.minimum_train_periods != r1_stats.minimum_train_periods:
            raise ValueError("US-R2 TRAIN period minimum must inherit R1 unchanged")
        if self.minimum_oos_periods_per_fold_regime != r1_stats.minimum_oos_periods_per_fold:
            raise ValueError("US-R2 fold-regime period minimum must inherit the R1 OOS minimum")
        if self.minimum_oos_sessions_per_fold_regime != r1_stats.minimum_oos_periods_per_fold:
            raise ValueError("US-R2 fold-regime session minimum is frozen at the reviewed 20-session gate")
        if self.quantile_count != r1_stats.quantile_count:
            raise ValueError("US-R2 quantile count must inherit R1 unchanged")
        if self.primary_robustness_cell != "fold_x_regime":
            raise ValueError("US-R2 primary robustness cells must be fold x regime")
        if self.required_fold_count != len(frozen.walk_forward_protocol.folds):
            raise ValueError("US-R2 evaluation policy must retain all five frozen folds")
        regimes = tuple(sorted(self.required_regimes))
        if regimes != FROZEN_REGIME_LABELS:
            raise ValueError("US-R2 evaluation policy must retain all four frozen regimes")
        object.__setattr__(self, "required_regimes", regimes)
        if self.required_primary_cell_count != self.required_fold_count * len(regimes):
            raise ValueError("US-R2 primary robustness cell count must be 5 x 4 = 20")
        if self.regime_primary_threshold_mapping != (
            "apply_unchanged_r1_fold_thresholds_to_each_fold_x_regime_primary_cell"
        ):
            raise ValueError("US-R2 may not weaken R1 primary thresholds for regimes")
        if self.pooled_inference_semantics != (
            "direction_normalized_oos_period_series_across_all_admitted_fold_regime_cells"
        ):
            raise ValueError("US-R2 pooled inference semantics differ from preregistration")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-statistical-evaluation-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        r1_stats = canonical_us_r1_statistical_evaluation_policy()
        r1_gate = canonical_us_r1_alpha_gate_policy()
        r1_protocol = canonical_us_r1_research_protocol()
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "frozen_protocol_id": self.frozen_protocol_id,
            "r1_statistical_policy_id": self.r1_statistical_policy_id,
            "r1_alpha_gate_policy_id": self.r1_alpha_gate_policy_id,
            "candidate_denominator_id": self.candidate_denominator_id,
            "direction_source_fold_id": self.direction_source_fold_id,
            "direction_source_role": "TRAIN",
            "direction_signal_interval": "15m",
            "direction_label_horizon_trading_minutes": 60,
            "direction_statistic": self.direction_statistic,
            "direction_zero_tie_break": self.direction_zero_tie_break,
            "direction_frozen_across_evaluation_folds": self.direction_frozen_across_evaluation_folds,
            "minimum_cross_section": self.minimum_cross_section,
            "minimum_train_periods": self.minimum_train_periods,
            "minimum_oos_periods_per_fold_regime": self.minimum_oos_periods_per_fold_regime,
            "minimum_oos_sessions_per_fold_regime": self.minimum_oos_sessions_per_fold_regime,
            "quantile_count": self.quantile_count,
            "quantile_assignment": r1_stats.quantile_assignment,
            "long_short_semantics": r1_stats.long_short_semantics,
            "turnover_semantics": r1_stats.turnover_semantics,
            "boundary_label_policy": r1_stats.boundary_label_policy,
            "partial_label_policy": r1_stats.partial_label_policy,
            "primary_robustness_cell": self.primary_robustness_cell,
            "required_fold_count": self.required_fold_count,
            "required_regimes": list(self.required_regimes),
            "required_primary_cell_count": self.required_primary_cell_count,
            "regime_primary_threshold_mapping": self.regime_primary_threshold_mapping,
            "pooled_inference_semantics": self.pooled_inference_semantics,
            "frequency_robustness_semantics": self.frequency_robustness_semantics,
            "decay_robustness_semantics": self.decay_robustness_semantics,
            "inherited_primary_gate_thresholds": {
                "min_primary_mean_rank_ic": r1_gate.min_primary_mean_rank_ic,
                "min_worst_primary_cell_rank_ic": r1_gate.min_worst_fold_rank_ic,
                "min_mean_primary_cell_rank_icir": r1_gate.min_mean_fold_rank_icir,
                "min_worst_primary_cell_rank_icir": r1_gate.min_worst_fold_rank_icir,
                "min_positive_primary_cell_ratio": r1_gate.min_positive_fold_ratio,
                "min_coverage": r1_gate.min_coverage,
                "min_quantile_monotonicity": r1_gate.min_quantile_monotonicity,
                "min_mean_long_short_return_bps": r1_gate.min_mean_long_short_return_bps,
                "max_mean_one_way_turnover": r1_gate.max_mean_one_way_turnover,
                "min_return_per_turnover_bps": r1_gate.min_return_per_turnover_bps,
            },
            "inherited_inference_thresholds": {
                "hac_lags_15m": r1_protocol.hac_lags_15m,
                "max_raw_hac_pvalue": r1_gate.max_raw_hac_pvalue,
                "max_holm_adjusted_pvalue": r1_gate.max_holm_adjusted_pvalue,
                "max_bh_qvalue": r1_gate.max_bh_qvalue,
                "bootstrap_samples": r1_protocol.bootstrap_samples,
                "bootstrap_block_sessions": r1_protocol.bootstrap_block_sessions,
                "bootstrap_seed": r1_protocol.bootstrap_seed,
                "max_session_bootstrap_pvalue": r1_gate.max_session_bootstrap_pvalue,
                "min_session_bootstrap_ci_lower": r1_gate.min_session_bootstrap_ci_lower,
            },
            "inherited_robustness_thresholds": {
                "min_frequency_sign_consistency_per_regime": r1_gate.min_frequency_sign_consistency,
                "min_decay_sign_consistency_per_regime": r1_gate.min_decay_sign_consistency,
            },
            "multiplicity_methods": list(r1_protocol.multiplicity_methods),
            "multiplicity_denominator": "all_37_frozen_r1_candidates",
            "performance_filter_applied": False,
            "new_agent_candidates_admitted": False,
            "result_dependent_regime_definition_allowed": False,
            "result_dependent_threshold_change_allowed": False,
            "survivorship_safe_market_claim": False,
            "point_in_time_security_master_available": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


def canonical_us_r2_statistical_evaluation_policy() -> USR2StatisticalEvaluationPolicy:
    return USR2StatisticalEvaluationPolicy(
        frozen_protocol_id=canonical_us_r2_frozen_protocol().freeze_id,
        r1_statistical_policy_id=canonical_us_r1_statistical_evaluation_policy().policy_id,
        r1_alpha_gate_policy_id=canonical_us_r1_alpha_gate_policy().policy_id,
    )


def validate_us_r2_statistical_evaluation_policy(
    document: dict[str, object],
) -> USR2StatisticalEvaluationPolicy:
    expected = canonical_us_r2_statistical_evaluation_policy()
    if document != expected.to_dict():
        raise ValueError("US-R2 statistical evaluation policy differs from canonical preregistration")
    return expected

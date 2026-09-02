from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum

from finagent.domain.market_bars import BarInterval
from finagent.research.us_agent_value_experiment import AgentValueExperiment
from finagent.research.us_agent_value_gate import (
    USAgentValueGateDecision,
    USAgentValueGateReview,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValueCandidateSpec,
    USAgentValuePhase,
)
from finagent.research.us_baselines import USBaselineProtocol


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


class USR1Terminal(StrEnum):
    ROBUST_FACTOR_FAMILY = "ROBUST_FACTOR_FAMILY"
    NO_ROBUST_FACTOR_FAMILY = "NO_ROBUST_FACTOR_FAMILY"
    SYSTEM_FAILURE = "SYSTEM_FAILURE"


class USR1AgentScope(StrEnum):
    RETAINED = "RETAINED"
    CONTRACTED = "CONTRACTED"


@dataclass(frozen=True, slots=True)
class USR1ResearchProtocol:
    baseline_protocol_id: str
    primary_interval: BarInterval = BarInterval.MINUTE_15
    robustness_intervals: tuple[BarInterval, ...] = (
        BarInterval.MINUTE_5,
        BarInterval.MINUTE_30,
    )
    label_name: str = "us_same_session_60m_simple_return_raw"
    label_horizon_trading_minutes: int = 60
    decay_horizon_trading_minutes: tuple[int, ...] = (30, 120)
    purge_trading_minutes: int = 60
    embargo_trading_minutes: int = 60
    hac_lags_5m: int = 12
    hac_lags_15m: int = 4
    hac_lags_30m: int = 2
    bootstrap_samples: int = 2000
    bootstrap_block_sessions: int = 5
    bootstrap_seed: int = 20_260_902
    multiplicity_methods: tuple[str, ...] = ("HOLM", "BH")
    candidate_admission_rule: str = (
        "latest_completed_a0_phase_all_valid_unique_structural_candidates_deduplicated_no_performance_filter"
    )
    research_scope: str = "engineering_universe_bounded_not_marketwide_survivorship_safe_claim"
    same_session_only: bool = True
    intraday_flat: bool = True
    schema_version: str = "finagent.us-r1-research-protocol.v1"

    def __post_init__(self) -> None:
        baseline = USBaselineProtocol()
        if self.baseline_protocol_id != baseline.protocol_id:
            raise ValueError("US-R1 protocol must bind the canonical US-B0/A0 research protocol")
        if self.primary_interval is not BarInterval.MINUTE_15:
            raise ValueError("US-R1 v1 primary interval must be 15m")
        if self.robustness_intervals != (BarInterval.MINUTE_5, BarInterval.MINUTE_30):
            raise ValueError("US-R1 v1 robustness intervals must be exactly 5m and 30m")
        if self.label_name != baseline.label_name or self.label_horizon_trading_minutes != 60:
            raise ValueError("US-R1 v1 must preserve the same-session 60m RAW label")
        if self.decay_horizon_trading_minutes != (30, 120):
            raise ValueError("US-R1 v1 decay horizons must be 30m and 120m around the 60m primary")
        if self.purge_trading_minutes < self.label_horizon_trading_minutes:
            raise ValueError("US-R1 purge must cover the full overlapping label horizon")
        if self.embargo_trading_minutes < self.label_horizon_trading_minutes:
            raise ValueError("US-R1 embargo must cover the full overlapping label horizon")
        if (self.hac_lags_5m, self.hac_lags_15m, self.hac_lags_30m) != (12, 4, 2):
            raise ValueError("US-R1 HAC lags must cover one full 60m overlapping horizon")
        if self.bootstrap_samples < 1000:
            raise ValueError("US-R1 deployment inference requires at least 1000 bootstrap samples")
        if self.bootstrap_block_sessions < 2:
            raise ValueError("US-R1 session bootstrap requires multi-session blocks")
        if self.multiplicity_methods != ("HOLM", "BH"):
            raise ValueError("US-R1 v1 multiplicity methods must be HOLM and BH")
        if not self.same_session_only or not self.intraday_flat:
            raise ValueError("US-R1 v1 is same-session and intraday-flat")

    @property
    def protocol_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-protocol")

    def hac_lags(self, interval: BarInterval) -> int:
        if interval is BarInterval.MINUTE_5:
            return self.hac_lags_5m
        if interval is BarInterval.MINUTE_15:
            return self.hac_lags_15m
        if interval is BarInterval.MINUTE_30:
            return self.hac_lags_30m
        raise ValueError("US-R1 HAC lag requested for unsupported interval")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "baseline_protocol_id": self.baseline_protocol_id,
            "primary_interval": self.primary_interval.value,
            "robustness_intervals": [item.value for item in self.robustness_intervals],
            "label_name": self.label_name,
            "label_horizon_trading_minutes": self.label_horizon_trading_minutes,
            "decay_horizon_trading_minutes": list(self.decay_horizon_trading_minutes),
            "purge_trading_minutes": self.purge_trading_minutes,
            "embargo_trading_minutes": self.embargo_trading_minutes,
            "hac_lags": {
                "5m": self.hac_lags_5m,
                "15m": self.hac_lags_15m,
                "30m": self.hac_lags_30m,
            },
            "session_block_bootstrap": {
                "samples": self.bootstrap_samples,
                "block_sessions": self.bootstrap_block_sessions,
                "seed": self.bootstrap_seed,
                "unit": "session",
            },
            "multiplicity_methods": list(self.multiplicity_methods),
            "candidate_admission_rule": self.candidate_admission_rule,
            "research_scope": self.research_scope,
            "same_session_only": self.same_session_only,
            "intraday_flat": self.intraday_flat,
            "annualization_semantics": (
                "presentation_only_frequency_aware_never_used_as_statistical_sample_size"
            ),
            "status_authority": False,
            "stage_exit_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["protocol_id"] = self.protocol_id
        return payload


def canonical_us_r1_research_protocol() -> USR1ResearchProtocol:
    return USR1ResearchProtocol(baseline_protocol_id=USBaselineProtocol().protocol_id)


@dataclass(frozen=True, slots=True)
class USR1CandidateProvenance:
    candidate: USAgentValueCandidateSpec
    source_arms: tuple[USAgentValueArm, ...]
    source_run_ids: tuple[str, ...]
    schema_version: str = "finagent.us-r1-candidate-provenance.v1"

    def __post_init__(self) -> None:
        if not self.source_arms or not self.source_run_ids:
            raise ValueError("US-R1 candidate provenance requires source arms and run IDs")
        if len(self.source_run_ids) != len(set(self.source_run_ids)):
            raise ValueError("US-R1 candidate provenance run IDs must be unique")
        if any(not value.strip() for value in self.source_run_ids):
            raise ValueError("US-R1 candidate provenance run IDs must be non-empty")
        ordered_arms = tuple(dict.fromkeys(self.source_arms))
        object.__setattr__(self, "source_arms", ordered_arms)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate": self.candidate.to_dict(),
            "candidate_id": self.candidate.candidate_id,
            "source_arms": [item.value for item in self.source_arms],
            "source_run_ids": list(self.source_run_ids),
            "admission_semantics": "structural_union_no_a0_performance_filter",
        }


@dataclass(frozen=True, slots=True)
class USR1CandidateDenominator:
    protocol_id: str
    a0_phase: USAgentValuePhase
    a0_experiment_id: str
    a0_gate_review_id: str
    a0_gate_decision: USAgentValueGateDecision
    agent_scope: USR1AgentScope
    candidates: tuple[USR1CandidateProvenance, ...]
    schema_version: str = "finagent.us-r1-candidate-denominator.v1"

    def __post_init__(self) -> None:
        protocol = canonical_us_r1_research_protocol()
        if self.protocol_id != protocol.protocol_id:
            raise ValueError("US-R1 candidate denominator/protocol identity mismatch")
        for field_name in ("a0_experiment_id", "a0_gate_review_id"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if not self.candidates:
            raise ValueError("US-R1 candidate denominator cannot be empty")
        candidate_ids = tuple(item.candidate.candidate_id for item in self.candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("US-R1 candidate denominator contains duplicate structural candidates")
        if self.a0_phase is USAgentValuePhase.PILOT:
            if self.a0_gate_decision not in {
                USAgentValueGateDecision.PILOT_DO_NOT_PROCEED_TO_FORMAL,
                USAgentValueGateDecision.INCONCLUSIVE,
            }:
                raise ValueError("US-R1 cannot treat PILOT_PROCEED_TO_FORMAL as terminal A0 evidence")
        else:
            if self.a0_gate_decision not in {
                USAgentValueGateDecision.FORMAL_INCREMENTAL_VALUE_SUPPORTED,
                USAgentValueGateDecision.FORMAL_NO_INCREMENTAL_VALUE,
                USAgentValueGateDecision.INCONCLUSIVE,
            }:
                raise ValueError("US-R1 FORMAL predecessor has invalid Agent Value Gate decision")

    @property
    def denominator_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-denominator")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "a0_phase": self.a0_phase.value,
            "a0_experiment_id": self.a0_experiment_id,
            "a0_gate_review_id": self.a0_gate_review_id,
            "a0_gate_decision": self.a0_gate_decision.value,
            "agent_scope": self.agent_scope.value,
            "candidate_count": len(self.candidates),
            "candidate_ids": [item.candidate.candidate_id for item in self.candidates],
            "candidates": [item.to_dict() for item in self.candidates],
            "multiplicity_denominator": "all_admitted_unique_structural_candidates",
            "performance_filter_applied": False,
            "status_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["denominator_id"] = self.denominator_id
        return payload


def _terminal_a0_review(
    experiment: AgentValueExperiment,
    review: USAgentValueGateReview,
) -> tuple[USAgentValuePhase, USAgentValueGateDecision, USR1AgentScope]:
    if review.assessment.experiment_id != experiment.experiment_id:
        raise ValueError("US-R1 A0 review/experiment identity mismatch")
    if review.assessment.phase is not experiment.protocol.phase:
        raise ValueError("US-R1 A0 review/experiment phase mismatch")
    phase = review.assessment.phase
    decision = review.decision
    if phase is USAgentValuePhase.PILOT:
        if decision is USAgentValueGateDecision.PILOT_PROCEED_TO_FORMAL:
            raise ValueError("US-R1 cannot start from a PILOT review that requires FORMAL continuation")
        if decision not in {
            USAgentValueGateDecision.PILOT_DO_NOT_PROCEED_TO_FORMAL,
            USAgentValueGateDecision.INCONCLUSIVE,
        }:
            raise ValueError("US-R1 PILOT terminal review decision is invalid")
        return phase, decision, USR1AgentScope.CONTRACTED
    if decision not in {
        USAgentValueGateDecision.FORMAL_INCREMENTAL_VALUE_SUPPORTED,
        USAgentValueGateDecision.FORMAL_NO_INCREMENTAL_VALUE,
        USAgentValueGateDecision.INCONCLUSIVE,
    }:
        raise ValueError("US-R1 FORMAL terminal review decision is invalid")
    scope = (
        USR1AgentScope.RETAINED
        if decision is USAgentValueGateDecision.FORMAL_INCREMENTAL_VALUE_SUPPORTED
        else USR1AgentScope.CONTRACTED
    )
    return phase, decision, scope


def build_us_r1_candidate_denominator(
    experiment: AgentValueExperiment,
    review: USAgentValueGateReview,
) -> USR1CandidateDenominator:
    phase, decision, agent_scope = _terminal_a0_review(experiment, review)
    provenance: dict[str, tuple[USAgentValueCandidateSpec, list[USAgentValueArm], list[str]]] = {}
    order: list[str] = []
    for arm_result in experiment.arm_results:
        for run in arm_result.generation_runs:
            for candidate in run.accepted_candidates:
                candidate_id = candidate.candidate_id
                if candidate_id not in provenance:
                    provenance[candidate_id] = (candidate, [], [])
                    order.append(candidate_id)
                stored_candidate, arms, run_ids = provenance[candidate_id]
                if stored_candidate != candidate:
                    raise ValueError("US-R1 structural candidate identity collision")
                if arm_result.arm not in arms:
                    arms.append(arm_result.arm)
                if run.run_id not in run_ids:
                    run_ids.append(run.run_id)
    candidates = tuple(
        USR1CandidateProvenance(
            candidate=provenance[candidate_id][0],
            source_arms=tuple(provenance[candidate_id][1]),
            source_run_ids=tuple(provenance[candidate_id][2]),
        )
        for candidate_id in order
    )
    return USR1CandidateDenominator(
        protocol_id=canonical_us_r1_research_protocol().protocol_id,
        a0_phase=phase,
        a0_experiment_id=experiment.experiment_id,
        a0_gate_review_id=review.review_id,
        a0_gate_decision=decision,
        agent_scope=agent_scope,
        candidates=candidates,
    )

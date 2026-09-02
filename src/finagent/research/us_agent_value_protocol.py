from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from finagent.research.us_baseline_walkforward import canonical_us_b0_pilot_walk_forward
from finagent.research.us_baselines import (
    USBaselineFeatureKind,
    USBaselineFeatureSpec,
    USBaselineProtocol,
    canonical_us_baseline_denominator,
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


class USAgentValueArm(StrEnum):
    MANUAL = "MANUAL"
    PROGRAMMATIC = "PROGRAMMATIC"
    AGENT = "AGENT"


class USAgentValuePhase(StrEnum):
    PILOT = "PILOT"
    FORMAL = "FORMAL"


_FIXED_INPUT_FIELDS: dict[USBaselineFeatureKind, tuple[str, ...]] = {
    USBaselineFeatureKind.REVERSAL: ("close",),
    USBaselineFeatureKind.MOMENTUM: ("close",),
    USBaselineFeatureKind.RANGE_MEAN: ("high", "low", "close"),
    USBaselineFeatureKind.RETURN_VOLATILITY: ("close",),
    USBaselineFeatureKind.VOLUME_SURPRISE: ("volume",),
    USBaselineFeatureKind.CLOSE_LOCATION: ("high", "low", "close"),
}


def _allowed_windows(kind: USBaselineFeatureKind) -> tuple[int, ...]:
    if kind is USBaselineFeatureKind.CLOSE_LOCATION:
        return (1,)
    if kind is USBaselineFeatureKind.RANGE_MEAN:
        return tuple(range(1, 14))
    return tuple(range(2, 14))


@dataclass(frozen=True, slots=True)
class USAgentValuePrimitiveRule:
    kind: USBaselineFeatureKind
    allowed_window_bars: tuple[int, ...]
    input_fields: tuple[str, ...]
    schema_version: str = "finagent.us-agent-value-primitive-rule.v1"

    def __post_init__(self) -> None:
        expected_windows = _allowed_windows(self.kind)
        expected_fields = _FIXED_INPUT_FIELDS[self.kind]
        if self.allowed_window_bars != expected_windows:
            raise ValueError("US-A0 primitive rule window domain drift")
        if self.input_fields != expected_fields:
            raise ValueError("US-A0 primitive rule input-field drift")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind.value,
            "allowed_window_bars": list(self.allowed_window_bars),
            "input_fields": list(self.input_fields),
        }


@dataclass(frozen=True, slots=True)
class USAgentValuePrimitiveVocabulary:
    rules: tuple[USAgentValuePrimitiveRule, ...]
    signal_interval: str = "15m"
    label_name: str = "us_same_session_60m_simple_return_raw"
    price_basis: str = "RAW"
    availability_policy: str = "available_at"
    same_session_only: bool = True
    require_complete_bars: bool = True
    schema_version: str = "finagent.us-agent-value-primitive-vocabulary.v1"

    def __post_init__(self) -> None:
        expected_kinds = tuple(USBaselineFeatureKind)
        if tuple(rule.kind for rule in self.rules) != expected_kinds:
            raise ValueError("US-A0 vocabulary must contain each frozen feature kind exactly once")
        if self.signal_interval != "15m":
            raise ValueError("US-A0 v1 shares the US-B0 15m signal clock")
        if self.label_name != "us_same_session_60m_simple_return_raw":
            raise ValueError("US-A0 v1 shares the US-B0 same-session 60m RAW label")
        if self.price_basis != "RAW" or self.availability_policy != "available_at":
            raise ValueError("US-A0 v1 must preserve RAW/available_at research semantics")
        if not self.same_session_only or not self.require_complete_bars:
            raise ValueError("US-A0 v1 requires same-session complete-bar features")

    @property
    def vocabulary_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-vocabulary",
        )

    @property
    def candidate_space_size(self) -> int:
        return sum(len(rule.allowed_window_bars) for rule in self.rules)

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "signal_interval": self.signal_interval,
            "label_name": self.label_name,
            "price_basis": self.price_basis,
            "availability_policy": self.availability_policy,
            "same_session_only": self.same_session_only,
            "require_complete_bars": self.require_complete_bars,
            "rules": [rule.to_dict() for rule in self.rules],
            "candidate_space_size": self.candidate_space_size,
            "scope": "bounded_shared_candidate_grammar_not_executable_code",
        }
        if include_id:
            payload["vocabulary_id"] = self.vocabulary_id
        return payload

    def candidate(
        self,
        kind: USBaselineFeatureKind,
        window_bars: int,
    ) -> USAgentValueCandidateSpec:
        rule = next((item for item in self.rules if item.kind is kind), None)
        if rule is None or window_bars not in rule.allowed_window_bars:
            raise ValueError(f"candidate outside frozen US-A0 vocabulary: {kind.value}/{window_bars}")
        return USAgentValueCandidateSpec(
            vocabulary_id=self.vocabulary_id,
            kind=kind,
            window_bars=window_bars,
            input_fields=rule.input_fields,
        )

    def all_candidates(self) -> tuple[USAgentValueCandidateSpec, ...]:
        return tuple(
            self.candidate(rule.kind, window)
            for rule in self.rules
            for window in rule.allowed_window_bars
        )


@dataclass(frozen=True, slots=True)
class USAgentValueCandidateSpec:
    vocabulary_id: str
    kind: USBaselineFeatureKind
    window_bars: int
    input_fields: tuple[str, ...]
    schema_version: str = "finagent.us-agent-value-candidate-spec.v1"

    def __post_init__(self) -> None:
        if not self.vocabulary_id.strip():
            raise ValueError("candidate vocabulary_id must be non-empty")
        if self.window_bars not in _allowed_windows(self.kind):
            raise ValueError("candidate window is outside the frozen primitive domain")
        if self.input_fields != _FIXED_INPUT_FIELDS[self.kind]:
            raise ValueError("candidate inputs must be derived from the frozen primitive kind")

    @property
    def candidate_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-candidate",
        )

    @property
    def structural_key(self) -> str:
        return f"{self.kind.value}:{self.window_bars}"

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "vocabulary_id": self.vocabulary_id,
            "kind": self.kind.value,
            "window_bars": self.window_bars,
            "input_fields": list(self.input_fields),
            "structural_key": self.structural_key,
        }
        if include_id:
            payload["candidate_id"] = self.candidate_id
        return payload

    def compile_feature_spec(self) -> USBaselineFeatureSpec:
        baseline_protocol = USBaselineProtocol()
        feature_id = f"a0_{self.kind.value}_{self.window_bars}bars_{self.candidate_id[-8:]}"
        if self.kind is USBaselineFeatureKind.REVERSAL:
            hypothesis = "Completed intraday returns may partially reverse over the frozen lookback."
            description = f"Negative simple close return across {self.window_bars - 1} adjacent 15m intervals."
        elif self.kind is USBaselineFeatureKind.MOMENTUM:
            hypothesis = "Completed intraday returns may continue over the frozen lookback."
            description = f"Simple close return across {self.window_bars - 1} adjacent 15m intervals."
        elif self.kind is USBaselineFeatureKind.RANGE_MEAN:
            hypothesis = "Recent normalized intraday range may contain cross-sectional information."
            description = f"Mean normalized high-low range across {self.window_bars} completed 15m bars."
        elif self.kind is USBaselineFeatureKind.RETURN_VOLATILITY:
            hypothesis = "Recent intraday return dispersion may contain cross-sectional information."
            description = (
                f"Population volatility of {self.window_bars - 1} adjacent completed 15m log returns."
            )
        elif self.kind is USBaselineFeatureKind.VOLUME_SURPRISE:
            hypothesis = "Current volume relative to recent same-session volume may be informative."
            description = (
                "Current completed 15m volume divided by the mean of the prior "
                f"{self.window_bars - 1} completed bars minus one."
            )
        else:
            hypothesis = "The close location within the completed bar may capture directional pressure."
            description = "Current completed 15m close location inside its high-low range, centered at zero."
        return USBaselineFeatureSpec(
            feature_id=feature_id,
            kind=self.kind,
            window_bars=self.window_bars,
            input_fields=self.input_fields,
            hypothesis=hypothesis,
            description=description,
            protocol_id=baseline_protocol.protocol_id,
        )


def canonical_us_a0_primitive_vocabulary() -> USAgentValuePrimitiveVocabulary:
    return USAgentValuePrimitiveVocabulary(
        rules=tuple(
            USAgentValuePrimitiveRule(
                kind=kind,
                allowed_window_bars=_allowed_windows(kind),
                input_fields=_FIXED_INPUT_FIELDS[kind],
            )
            for kind in USBaselineFeatureKind
        )
    )


def _core_manual_candidates(
    vocabulary: USAgentValuePrimitiveVocabulary,
) -> tuple[USAgentValueCandidateSpec, ...]:
    baseline = canonical_us_baseline_denominator()
    candidates: list[USAgentValueCandidateSpec] = []
    for feature in baseline.candidates:
        candidate = vocabulary.candidate(feature.kind, feature.window_bars)
        if candidate.input_fields != feature.input_fields:
            raise ValueError(f"US-B0/A0 primitive input mismatch for {feature.feature_id}")
        candidates.append(candidate)
    return tuple(candidates)


def canonical_us_a0_manual_candidates() -> tuple[USAgentValueCandidateSpec, ...]:
    """Freeze 32 MANUAL formulas before any US-A0 result inspection.

    The first eight structurally reproduce the US-B0 manual denominator. The remaining
    formulas are a pre-result coverage grid over the same grammar, not performance-selected
    extensions. PILOT consumes the first 16; FORMAL consumes all 32.
    """

    vocabulary = canonical_us_a0_primitive_vocabulary()
    core = _core_manual_candidates(vocabulary)
    pilot_extensions = (
        vocabulary.candidate(USBaselineFeatureKind.MOMENTUM, 2),
        vocabulary.candidate(USBaselineFeatureKind.MOMENTUM, 3),
        vocabulary.candidate(USBaselineFeatureKind.REVERSAL, 5),
        vocabulary.candidate(USBaselineFeatureKind.REVERSAL, 9),
        vocabulary.candidate(USBaselineFeatureKind.RANGE_MEAN, 1),
        vocabulary.candidate(USBaselineFeatureKind.RANGE_MEAN, 8),
        vocabulary.candidate(USBaselineFeatureKind.RETURN_VOLATILITY, 9),
        vocabulary.candidate(USBaselineFeatureKind.VOLUME_SURPRISE, 5),
    )
    formal_extensions = (
        vocabulary.candidate(USBaselineFeatureKind.REVERSAL, 4),
        vocabulary.candidate(USBaselineFeatureKind.REVERSAL, 6),
        vocabulary.candidate(USBaselineFeatureKind.REVERSAL, 7),
        vocabulary.candidate(USBaselineFeatureKind.REVERSAL, 8),
        vocabulary.candidate(USBaselineFeatureKind.MOMENTUM, 4),
        vocabulary.candidate(USBaselineFeatureKind.MOMENTUM, 6),
        vocabulary.candidate(USBaselineFeatureKind.MOMENTUM, 7),
        vocabulary.candidate(USBaselineFeatureKind.MOMENTUM, 8),
        vocabulary.candidate(USBaselineFeatureKind.RANGE_MEAN, 2),
        vocabulary.candidate(USBaselineFeatureKind.RANGE_MEAN, 6),
        vocabulary.candidate(USBaselineFeatureKind.RANGE_MEAN, 9),
        vocabulary.candidate(USBaselineFeatureKind.RETURN_VOLATILITY, 2),
        vocabulary.candidate(USBaselineFeatureKind.RETURN_VOLATILITY, 3),
        vocabulary.candidate(USBaselineFeatureKind.RETURN_VOLATILITY, 7),
        vocabulary.candidate(USBaselineFeatureKind.VOLUME_SURPRISE, 3),
        vocabulary.candidate(USBaselineFeatureKind.VOLUME_SURPRISE, 7),
    )
    result = core + pilot_extensions + formal_extensions
    ids = tuple(item.candidate_id for item in result)
    if len(result) != 32 or len(ids) != len(set(ids)):
        raise RuntimeError("canonical US-A0 MANUAL candidate grid must contain 32 unique formulas")
    return result


@dataclass(frozen=True, slots=True)
class USAgentValueExperimentProtocol:
    phase: USAgentValuePhase
    vocabulary_id: str
    us_b0_walk_forward_protocol_id: str
    candidate_budget_per_run: int
    manual_candidate_ids: tuple[str, ...]
    manual_core_candidate_ids: tuple[str, ...]
    arms: tuple[USAgentValueArm, ...] = (
        USAgentValueArm.MANUAL,
        USAgentValueArm.PROGRAMMATIC,
        USAgentValueArm.AGENT,
    )
    manual_min_independent_runs: int = 1
    programmatic_min_independent_runs: int = 1
    agent_min_independent_runs: int = 1
    maximum_repairs_per_slot: int = 1
    replacements_allowed: bool = False
    invalid_and_duplicate_consume_slot: bool = True
    budget_unit: str = "per_independent_run"
    schema_version: str = "finagent.us-agent-value-experiment-protocol.v1"

    def __post_init__(self) -> None:
        expected_budget = 16 if self.phase is USAgentValuePhase.PILOT else 32
        if self.candidate_budget_per_run != expected_budget:
            raise ValueError("US-A0 candidate budget must match the frozen phase budget")
        if self.arms != (
            USAgentValueArm.MANUAL,
            USAgentValueArm.PROGRAMMATIC,
            USAgentValueArm.AGENT,
        ):
            raise ValueError("US-A0 v1 arms must be exactly MANUAL/PROGRAMMATIC/AGENT")
        if len(self.manual_candidate_ids) != self.candidate_budget_per_run:
            raise ValueError("MANUAL arm must fill the same frozen per-run candidate budget")
        if len(set(self.manual_candidate_ids)) != len(self.manual_candidate_ids):
            raise ValueError("MANUAL candidate identities must be unique")
        if len(self.manual_core_candidate_ids) != 8:
            raise ValueError("US-A0 must retain the eight US-B0 structural MANUAL candidates")
        if not set(self.manual_core_candidate_ids).issubset(self.manual_candidate_ids):
            raise ValueError("US-B0 core MANUAL candidates must remain inside the A0 MANUAL arm")
        if self.maximum_repairs_per_slot != 1:
            raise ValueError("US-A0 v1 permits at most one repair within a consumed slot")
        if self.replacements_allowed:
            raise ValueError("US-A0 v1 forbids replacement slots after invalid/duplicate proposals")
        if not self.invalid_and_duplicate_consume_slot:
            raise ValueError("invalid and duplicate proposals must consume the shared trial budget")
        if self.budget_unit != "per_independent_run":
            raise ValueError("US-A0 compares equal per-run trial budgets")
        expected_repeats = 1 if self.phase is USAgentValuePhase.PILOT else 3
        if self.manual_min_independent_runs != 1:
            raise ValueError("MANUAL is one frozen deterministic run")
        if self.programmatic_min_independent_runs != expected_repeats:
            raise ValueError("PROGRAMMATIC independent-run count drift")
        if self.agent_min_independent_runs != expected_repeats:
            raise ValueError("AGENT independent-run count drift")

    @property
    def protocol_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-agent-value-experiment-protocol",
        )

    def minimum_runs(self, arm: USAgentValueArm) -> int:
        if arm is USAgentValueArm.MANUAL:
            return self.manual_min_independent_runs
        if arm is USAgentValueArm.PROGRAMMATIC:
            return self.programmatic_min_independent_runs
        return self.agent_min_independent_runs

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "phase": self.phase.value,
            "vocabulary_id": self.vocabulary_id,
            "us_b0_walk_forward_protocol_id": self.us_b0_walk_forward_protocol_id,
            "candidate_budget_per_run": self.candidate_budget_per_run,
            "budget_unit": self.budget_unit,
            "arms": [item.value for item in self.arms],
            "manual_candidate_ids": list(self.manual_candidate_ids),
            "manual_core_candidate_ids": list(self.manual_core_candidate_ids),
            "manual_min_independent_runs": self.manual_min_independent_runs,
            "programmatic_min_independent_runs": self.programmatic_min_independent_runs,
            "agent_min_independent_runs": self.agent_min_independent_runs,
            "maximum_repairs_per_slot": self.maximum_repairs_per_slot,
            "replacements_allowed": self.replacements_allowed,
            "invalid_and_duplicate_consume_slot": self.invalid_and_duplicate_consume_slot,
            "proposal_storage": "structured_formula_fields_and_short_hypothesis_only_no_chain_of_thought",
            "programmatic_seed_policy": "required_and_recorded_per_independent_run",
            "agent_identity_policy": "provider_model_prompt_template_required_per_run",
            "predecessor_requirement": "accepted_US-B0_split_bound_evidence_before_formal_A0_execution",
            "status_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["protocol_id"] = self.protocol_id
        return payload


def canonical_us_a0_experiment_protocol(
    phase: USAgentValuePhase = USAgentValuePhase.PILOT,
) -> USAgentValueExperimentProtocol:
    vocabulary = canonical_us_a0_primitive_vocabulary()
    manual = canonical_us_a0_manual_candidates()
    core_ids = tuple(item.candidate_id for item in manual[:8])
    budget = 16 if phase is USAgentValuePhase.PILOT else 32
    minimum_repeats = 1 if phase is USAgentValuePhase.PILOT else 3
    return USAgentValueExperimentProtocol(
        phase=phase,
        vocabulary_id=vocabulary.vocabulary_id,
        us_b0_walk_forward_protocol_id=canonical_us_b0_pilot_walk_forward().protocol_id,
        candidate_budget_per_run=budget,
        manual_candidate_ids=tuple(item.candidate_id for item in manual[:budget]),
        manual_core_candidate_ids=core_ids,
        manual_min_independent_runs=1,
        programmatic_min_independent_runs=minimum_repeats,
        agent_min_independent_runs=minimum_repeats,
    )

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from finagent.agents.domain import AgentTask
from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.agents.observability import AgentTracer
from finagent.domain._validation import require_non_empty

from .agent_market import MarketFeatureCandidateGenerator
from .ashare_robust_program import (
    AshareRobustCandidateGate,
    AshareRobustCandidateGateReport,
    AshareRobustFactorSelection,
    AshareRobustFactorSelector,
    AshareWalkForwardFactorAnalyzer,
    AshareWalkForwardFamilyReport,
)
from .factor_discovery import AgentFactorDiscoveryConfig


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class AshareRobustFeedbackFold:
    fold_id: str
    train_direction: int
    test_rank_icir: float
    test_long_short_sharpe: float
    coverage: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fold_id",
            require_non_empty(self.fold_id, "fold_id"),
        )
        if self.train_direction not in {-1, 1}:
            raise ValueError("feedback fold direction must be -1 or 1")

    def to_dict(self) -> dict[str, object]:
        return {
            "fold_id": self.fold_id,
            "train_direction": self.train_direction,
            "test_rank_icir": self.test_rank_icir,
            "test_long_short_sharpe": self.test_long_short_sharpe,
            "coverage": self.coverage,
        }


@dataclass(frozen=True, slots=True)
class AshareRobustFeedbackCandidate:
    feature_id: str
    feature_digest: str
    folds: tuple[AshareRobustFeedbackFold, ...]
    pooled_rank_icir: float
    mean_fold_rank_icir: float
    worst_fold_rank_icir: float
    positive_fold_ratio: float
    direction_consistency: float
    mean_fold_long_short_sharpe: float
    quantile_monotonicity: float
    mean_one_way_turnover: float
    coverage_min: float
    horizon_sign_consistency: float
    hac_pvalue: float
    bh_qvalue: float
    gate_passed: bool
    gate_reason_codes: tuple[str, ...]
    robust_score: float

    def __post_init__(self) -> None:
        for name in ("feature_id", "feature_digest"):
            object.__setattr__(
                self,
                name,
                require_non_empty(getattr(self, name), name),
            )
        if not self.folds:
            raise ValueError("robust feedback candidate requires folds")
        if self.gate_passed and self.gate_reason_codes:
            raise ValueError("passed feedback candidate cannot contain rejection reasons")
        if not self.gate_passed and not self.gate_reason_codes:
            raise ValueError("rejected feedback candidate requires reasons")

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "feature_digest": self.feature_digest,
            "folds": [fold.to_dict() for fold in self.folds],
            "pooled_rank_icir": self.pooled_rank_icir,
            "mean_fold_rank_icir": self.mean_fold_rank_icir,
            "worst_fold_rank_icir": self.worst_fold_rank_icir,
            "positive_fold_ratio": self.positive_fold_ratio,
            "direction_consistency": self.direction_consistency,
            "mean_fold_long_short_sharpe": self.mean_fold_long_short_sharpe,
            "quantile_monotonicity": self.quantile_monotonicity,
            "mean_one_way_turnover": self.mean_one_way_turnover,
            "coverage_min": self.coverage_min,
            "horizon_sign_consistency": self.horizon_sign_consistency,
            "hac_pvalue": self.hac_pvalue,
            "bh_qvalue": self.bh_qvalue,
            "gate_passed": self.gate_passed,
            "gate_reason_codes": list(self.gate_reason_codes),
            "robust_score": self.robust_score,
        }


@dataclass(frozen=True, slots=True)
class AshareRobustAgentFeedbackV3:
    program_spec_id: str
    walk_forward_report_id: str
    gate_report_id: str
    candidates: tuple[AshareRobustFeedbackCandidate, ...]
    selection_id: str
    selected_feature_digests: tuple[str, ...]
    selected_weights: tuple[float, ...]
    selection_status: str

    def __post_init__(self) -> None:
        for name in (
            "program_spec_id",
            "walk_forward_report_id",
            "gate_report_id",
            "selection_id",
            "selection_status",
        ):
            object.__setattr__(
                self,
                name,
                require_non_empty(getattr(self, name), name),
            )
        if not self.candidates:
            raise ValueError("robust feedback requires candidates")
        candidate_digests = {candidate.feature_digest for candidate in self.candidates}
        if len(candidate_digests) != len(self.candidates):
            raise ValueError("robust feedback contains duplicate candidates")
        if len(self.selected_feature_digests) != len(self.selected_weights):
            raise ValueError("selected factor digests and weights differ in length")
        if not set(self.selected_feature_digests).issubset(candidate_digests):
            raise ValueError("robust feedback selection is outside candidate denominator")
        if self.selected_weights and abs(sum(self.selected_weights) - 1.0) > 1e-9:
            raise ValueError("selected robust weights must sum to one")

    @property
    def feedback_id(self) -> str:
        digest = hashlib.sha256(self.to_json().encode()).hexdigest()[:24]
        return f"ashare-robust-feedback-v3-{digest}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.ashare-robust-agent-feedback.v3",
            "program_spec_id": self.program_spec_id,
            "walk_forward_report_id": self.walk_forward_report_id,
            "gate_report_id": self.gate_report_id,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "selection": {
                "selection_id": self.selection_id,
                "status": self.selection_status,
                "feature_digests": list(self.selected_feature_digests),
                "weights": list(self.selected_weights),
            },
            "scope": (
                "2018-2024 internal development/walk-forward evidence only; "
                "excludes 2025+ reserve, execution, promotion, PAPER and live evidence"
            ),
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_reports(
        cls,
        walk_forward: AshareWalkForwardFamilyReport,
        gate: AshareRobustCandidateGateReport,
        selection: AshareRobustFactorSelection,
    ) -> AshareRobustAgentFeedbackV3:
        if gate.walk_forward_report_id != walk_forward.report_id:
            raise ValueError("gate report does not belong to walk-forward report")
        if selection.walk_forward_report_id != walk_forward.report_id:
            raise ValueError("selection does not belong to walk-forward report")
        if selection.gate_report_id != gate.gate_report_id:
            raise ValueError("selection does not belong to gate report")
        candidates = []
        for item in walk_forward.candidates:
            evaluation = gate.candidate(item.feature_digest)
            candidates.append(
                AshareRobustFeedbackCandidate(
                    feature_id=item.feature_id,
                    feature_digest=item.feature_digest,
                    folds=tuple(
                        AshareRobustFeedbackFold(
                            fold_id=fold.fold_id,
                            train_direction=fold.train_direction,
                            test_rank_icir=fold.test_rank_icir,
                            test_long_short_sharpe=fold.test_long_short_sharpe,
                            coverage=fold.coverage,
                        )
                        for fold in item.folds
                    ),
                    pooled_rank_icir=item.pooled_rank_icir,
                    mean_fold_rank_icir=item.mean_fold_rank_icir,
                    worst_fold_rank_icir=item.worst_fold_rank_icir,
                    positive_fold_ratio=item.positive_fold_ratio,
                    direction_consistency=item.direction_consistency,
                    mean_fold_long_short_sharpe=item.mean_fold_long_short_sharpe,
                    quantile_monotonicity=item.quantile_monotonicity,
                    mean_one_way_turnover=item.mean_one_way_turnover,
                    coverage_min=item.coverage_min,
                    horizon_sign_consistency=item.horizon_sign_consistency,
                    hac_pvalue=item.raw_hac_pvalue,
                    bh_qvalue=item.bh_qvalue,
                    gate_passed=evaluation.passed,
                    gate_reason_codes=evaluation.reason_codes,
                    robust_score=evaluation.robust_score,
                )
            )
        return cls(
            program_spec_id=walk_forward.program_spec_id,
            walk_forward_report_id=walk_forward.report_id,
            gate_report_id=gate.gate_report_id,
            candidates=tuple(candidates),
            selection_id=selection.selection_id,
            selected_feature_digests=tuple(
                component.feature_digest for component in selection.components
            ),
            selected_weights=tuple(component.weight for component in selection.components),
            selection_status=selection.status,
        )


class AshareRobustFeedbackAwareMarketFeatureCandidateGenerator:
    """Inject only internal walk-forward development evidence into the next round."""

    def __init__(self, base: MarketFeatureCandidateGenerator) -> None:
        self.base = base

    def generate(
        self,
        *,
        task: AgentTask,
        count: int,
        approved_input_fields: Sequence[str],
        smoke_inputs: Mapping[str, Sequence[int | float | None]],
        round_index: int,
        feedback: AshareRobustAgentFeedbackV3 | None = None,
    ):
        if round_index < 1:
            raise ValueError("round_index must be >= 1")
        objective = task.objective
        metadata = {
            **dict(task.metadata),
            "ashare_robust_discovery_round": str(round_index),
        }
        if feedback is not None:
            objective = (
                f"{task.objective}\n\n"
                "INTERNAL DEVELOPMENT-ONLY WALK-FORWARD FEEDBACK V3:\n"
                f"{feedback.to_json()}\n\n"
                "Propose new economically interpretable A-share factors using only "
                "approved PIT market inputs. Prefer stable sign and direction across "
                "expanding test folds, positive worst-fold behavior, monotonic quantiles, "
                "adequate coverage, low turnover and mechanisms distinct from rejected or "
                "correlated candidates. Treat gate rejection as evidence about robustness, "
                "not as permission to inspect or infer the 2025+ reserve. Never request "
                "reserve, execution, promotion, PAPER or live evidence."
            )
            metadata["ashare_robust_feedback_id"] = feedback.feedback_id
            metadata["ashare_walk_forward_report_id"] = feedback.walk_forward_report_id
            metadata["ashare_robust_gate_report_id"] = feedback.gate_report_id
        child = AgentTask(
            task_id=f"{task.task_id}:robust-round:{round_index:02d}",
            objective=objective,
            created_at=task.created_at,
            metadata=metadata,
        )
        return self.base.generate(
            task=child,
            count=count,
            approved_input_fields=approved_input_fields,
            smoke_inputs=smoke_inputs,
        )


@dataclass(frozen=True, slots=True)
class AgentAshareRobustDiscoveryRound:
    round_index: int
    candidates: tuple[GeneratedFeatureArtifact, ...]
    cumulative_report: AshareWalkForwardFamilyReport
    gate_report: AshareRobustCandidateGateReport
    selection: AshareRobustFactorSelection
    feedback: AshareRobustAgentFeedbackV3

    def __post_init__(self) -> None:
        if self.round_index < 1 or not self.candidates:
            raise ValueError("robust discovery round requires candidates")
        if self.gate_report.walk_forward_report_id != self.cumulative_report.report_id:
            raise ValueError("round gate does not belong to cumulative report")
        if self.selection.walk_forward_report_id != self.cumulative_report.report_id:
            raise ValueError("round selection does not belong to cumulative report")
        if self.feedback.walk_forward_report_id != self.cumulative_report.report_id:
            raise ValueError("round feedback does not belong to cumulative report")


@dataclass(frozen=True, slots=True)
class AgentAshareRobustDiscoveryResult:
    task_id: str
    program_spec_id: str
    rounds: tuple[AgentAshareRobustDiscoveryRound, ...]
    candidates: tuple[GeneratedFeatureArtifact, ...]
    final_report: AshareWalkForwardFamilyReport
    final_gate_report: AshareRobustCandidateGateReport
    final_selection: AshareRobustFactorSelection
    final_feedback: AshareRobustAgentFeedbackV3

    def __post_init__(self) -> None:
        for name in ("task_id", "program_spec_id"):
            object.__setattr__(
                self,
                name,
                require_non_empty(getattr(self, name), name),
            )
        if not self.rounds or not self.candidates:
            raise ValueError("robust discovery result requires rounds and candidates")
        digests = {candidate.digest for candidate in self.candidates}
        if digests != {
            candidate.feature_digest for candidate in self.final_report.candidates
        }:
            raise ValueError("robust discovery denominator drifted")
        if self.final_report.program_spec_id != self.program_spec_id:
            raise ValueError("robust discovery program spec drifted")

    @property
    def discovery_id(self) -> str:
        payload = {
            "task_id": self.task_id,
            "program_spec_id": self.program_spec_id,
            "round_report_ids": [
                item.cumulative_report.report_id for item in self.rounds
            ],
            "candidate_digests": [candidate.digest for candidate in self.candidates],
            "final_selection_id": self.final_selection.selection_id,
        }
        digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:24]
        return f"ashare-robust-discovery-{digest}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.ashare-robust-agent-discovery.v3",
            "discovery_id": self.discovery_id,
            "task_id": self.task_id,
            "program_spec_id": self.program_spec_id,
            "rounds": [
                {
                    "round_index": item.round_index,
                    "new_candidate_digests": [
                        candidate.digest for candidate in item.candidates
                    ],
                    "cumulative_candidate_digests": [
                        candidate.feature_digest
                        for candidate in item.cumulative_report.candidates
                    ],
                    "walk_forward_report_id": item.cumulative_report.report_id,
                    "gate_report_id": item.gate_report.gate_report_id,
                    "selection_id": item.selection.selection_id,
                    "selection_status": item.selection.status,
                    "feedback_id": item.feedback.feedback_id,
                }
                for item in self.rounds
            ],
            "candidate_digests": [candidate.digest for candidate in self.candidates],
            "final_walk_forward_report_id": self.final_report.report_id,
            "final_gate_report_id": self.final_gate_report.gate_report_id,
            "final_selection_id": self.final_selection.selection_id,
            "final_feedback_id": self.final_feedback.feedback_id,
            "scope": (
                "adaptive internal development/walk-forward discovery; "
                "2025+ reserve remains untouched"
            ),
        }


class AgentAshareRobustDiscoveryLoop:
    VERSION = "ashare-robust-agent-discovery-v3"

    def __init__(
        self,
        *,
        generator: AshareRobustFeedbackAwareMarketFeatureCandidateGenerator,
        analyzer: AshareWalkForwardFactorAnalyzer,
        gate: AshareRobustCandidateGate,
        selector: AshareRobustFactorSelector,
        config: AgentFactorDiscoveryConfig,
        tracer: AgentTracer | None = None,
    ) -> None:
        self.generator = generator
        self.analyzer = analyzer
        self.gate = gate
        self.selector = selector
        self.config = config
        self.tracer = tracer or AgentTracer()

    def run(
        self,
        *,
        task: AgentTask,
        approved_input_fields: Sequence[str],
        smoke_inputs: Mapping[str, Sequence[int | float | None]],
    ) -> AgentAshareRobustDiscoveryResult:
        approved = tuple(str(value) for value in approved_input_fields)
        if not approved or len(set(approved)) != len(approved):
            raise ValueError("approved_input_fields must be unique and non-empty")
        if set(smoke_inputs) != set(approved):
            raise ValueError("smoke_inputs must exactly match approved_input_fields")

        feedback: AshareRobustAgentFeedbackV3 | None = None
        all_candidates: list[GeneratedFeatureArtifact] = []
        rounds: list[AgentAshareRobustDiscoveryRound] = []
        seen_digests: set[str] = set()
        seen_ids: set[str] = set()

        with self.tracer.span(
            "finagent.ashare.robust_discovery",
            "AGENT",
            {
                "finagent.task_id": task.task_id,
                "finagent.program_spec_id": self.analyzer.program_spec.spec_id,
                "finagent.rounds": self.config.rounds,
                "finagent.candidates_per_round": self.config.candidates_per_round,
            },
        ) as root_span:
            for round_index in range(1, self.config.rounds + 1):
                with self.tracer.span(
                    f"finagent.ashare.robust_round.{round_index}",
                    "AGENT",
                    {
                        "finagent.round_index": round_index,
                        "finagent.prior_candidate_count": len(all_candidates),
                    },
                ) as round_span:
                    generated = tuple(
                        self.generator.generate(
                            task=task,
                            count=self.config.candidates_per_round,
                            approved_input_fields=approved,
                            smoke_inputs=smoke_inputs,
                            round_index=round_index,
                            feedback=feedback,
                        )
                    )
                    if len(generated) != self.config.candidates_per_round:
                        raise RuntimeError(
                            "robust candidate generator returned unexpected count"
                        )
                    for artifact in generated:
                        if (
                            artifact.digest in seen_digests
                            or artifact.spec.feature_id in seen_ids
                        ):
                            raise ValueError(
                                "robust discovery generated a duplicate candidate"
                            )
                        seen_digests.add(artifact.digest)
                        seen_ids.add(artifact.spec.feature_id)
                    all_candidates.extend(generated)
                    if len(all_candidates) > self.config.max_total_candidates:
                        raise RuntimeError(
                            "robust discovery exceeded max_total_candidates"
                        )
                    report = self.analyzer.analyze(tuple(all_candidates))
                    gate_report = self.gate.evaluate(report)
                    selection = self.selector.select(report, gate_report)
                    feedback = AshareRobustAgentFeedbackV3.from_reports(
                        report,
                        gate_report,
                        selection,
                    )
                    self.tracer.event(
                        "ashare_robust_feedback_created",
                        {
                            "feedback_id": feedback.feedback_id,
                            "walk_forward_report_id": report.report_id,
                            "gate_report_id": gate_report.gate_report_id,
                            "selection_status": selection.status,
                            "scope": "internal_development_only",
                        },
                    )
                    rounds.append(
                        AgentAshareRobustDiscoveryRound(
                            round_index=round_index,
                            candidates=generated,
                            cumulative_report=report,
                            gate_report=gate_report,
                            selection=selection,
                            feedback=feedback,
                        )
                    )
                    round_span.set_attributes(
                        {
                            "finagent.new_candidate_count": len(generated),
                            "finagent.cumulative_candidate_count": len(all_candidates),
                            "finagent.robust_selection_status": selection.status,
                            "finagent.robust_factor_count": len(selection.components),
                        }
                    )

            assert feedback is not None
            final = rounds[-1]
            result = AgentAshareRobustDiscoveryResult(
                task_id=task.task_id,
                program_spec_id=self.analyzer.program_spec.spec_id,
                rounds=tuple(rounds),
                candidates=tuple(all_candidates),
                final_report=final.cumulative_report,
                final_gate_report=final.gate_report,
                final_selection=final.selection,
                final_feedback=final.feedback,
            )
            root_span.set_attributes(
                {
                    "finagent.discovery_id": result.discovery_id,
                    "finagent.candidate_denominator": len(result.candidates),
                    "finagent.final_selection_status": result.final_selection.status,
                }
            )
            return result

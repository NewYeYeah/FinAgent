from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from finagent.agents.domain import AgentTask
from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.agents.observability import AgentTracer
from finagent.domain._validation import require_non_empty
from finagent.domain.research import DatasetRequest

from .factor_discovery import AgentFactorDiscoveryConfig
from .factor_feedback_v2 import (
    FactorQuantAgentFeedbackV2,
    FactorQuantFeedbackAwareMarketFeatureCandidateGenerator,
)
from .factor_quant import (
    FactorEnsembleSelection,
    FactorEnsembleSelector,
    FactorQuantAnalyzer,
    FactorQuantFamilyReport,
)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class AgentFactorQuantDiscoveryRound:
    round_index: int
    candidates: tuple[GeneratedFeatureArtifact, ...]
    cumulative_report: FactorQuantFamilyReport
    selection: FactorEnsembleSelection
    feedback: FactorQuantAgentFeedbackV2

    def __post_init__(self) -> None:
        if self.round_index < 1 or not self.candidates:
            raise ValueError("factor quant discovery round requires candidates")
        if self.selection.report_id != self.cumulative_report.report_id:
            raise ValueError("round selection does not belong to cumulative factor report")
        if self.feedback.report_id != self.cumulative_report.report_id:
            raise ValueError("round feedback does not belong to cumulative factor report")


@dataclass(frozen=True, slots=True)
class AgentFactorQuantDiscoveryResult:
    task_id: str
    development_data_id: str
    rounds: tuple[AgentFactorQuantDiscoveryRound, ...]
    candidates: tuple[GeneratedFeatureArtifact, ...]
    final_report: FactorQuantFamilyReport
    final_selection: FactorEnsembleSelection
    final_feedback: FactorQuantAgentFeedbackV2

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", require_non_empty(self.task_id, "task_id"))
        object.__setattr__(
            self,
            "development_data_id",
            require_non_empty(self.development_data_id, "development_data_id"),
        )
        if not self.rounds or not self.candidates:
            raise ValueError("factor quant discovery result requires rounds and candidates")
        if self.final_report.report_id != self.final_selection.report_id:
            raise ValueError("final factor selection does not belong to final report")
        if self.final_feedback.report_id != self.final_report.report_id:
            raise ValueError("final factor feedback does not belong to final report")
        if self.final_feedback.development_data_id != self.development_data_id:
            raise ValueError("factor quant discovery development identity drifted")
        report_digests = {item.feature_digest for item in self.final_report.candidates}
        candidate_digests = {item.digest for item in self.candidates}
        if report_digests != candidate_digests:
            raise ValueError("final Factor Quant denominator differs from discovery candidates")

    @property
    def discovery_id(self) -> str:
        payload = {
            "task_id": self.task_id,
            "development_data_id": self.development_data_id,
            "round_report_ids": [item.cumulative_report.report_id for item in self.rounds],
            "candidate_digests": [artifact.digest for artifact in self.candidates],
            "final_selection": self.final_selection.to_dict(),
        }
        digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:24]
        return f"factor-quant-discovery-{digest}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.agent-factor-quant-discovery.v2",
            "discovery_id": self.discovery_id,
            "task_id": self.task_id,
            "development_data_id": self.development_data_id,
            "rounds": [
                {
                    "round_index": item.round_index,
                    "new_candidate_digests": [artifact.digest for artifact in item.candidates],
                    "cumulative_report_id": item.cumulative_report.report_id,
                    "cumulative_candidate_digests": [
                        candidate.feature_digest for candidate in item.cumulative_report.candidates
                    ],
                    "selection": item.selection.to_dict(),
                    "feedback_id": item.feedback.feedback_id,
                }
                for item in self.rounds
            ],
            "candidate_digests": [artifact.digest for artifact in self.candidates],
            "final_report": self.final_report.to_dict(),
            "final_selection": self.final_selection.to_dict(),
            "final_feedback_id": self.final_feedback.feedback_id,
            "scope": (
                "adaptive development-only Factor Quant v2 discovery; the complete generated "
                "candidate denominator still requires independent governed validation"
            ),
        }

    def write_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path


class AgentFactorQuantDiscoveryLoop:
    """Cumulative adaptive discovery driven by development-only Factor Quant v2 evidence."""

    VERSION = "agent-factor-quant-discovery-v2.1"

    def __init__(
        self,
        *,
        generator: FactorQuantFeedbackAwareMarketFeatureCandidateGenerator,
        analyzer: FactorQuantAnalyzer,
        selector: FactorEnsembleSelector | None = None,
        config: AgentFactorDiscoveryConfig | None = None,
        tracer: AgentTracer | None = None,
    ) -> None:
        self.generator = generator
        self.analyzer = analyzer
        self.selector = selector or FactorEnsembleSelector()
        self.config = config or AgentFactorDiscoveryConfig()
        self.tracer = tracer or AgentTracer()

    def _preflight(
        self,
        request: DatasetRequest,
        approved_input_fields: Sequence[str],
        smoke_inputs: Mapping[str, Sequence[int | float | None]],
    ) -> None:
        quant = self.analyzer.config
        if quant.split_name not in request.splits:
            raise KeyError(f"development request has no split {quant.split_name!r}")
        missing_labels = set(quant.labels) - set(request.labels)
        if missing_labels:
            raise ValueError(
                f"development request is missing Factor Quant labels: {sorted(missing_labels)}"
            )
        approved = tuple(str(value) for value in approved_input_fields)
        if not approved or len(set(approved)) != len(approved):
            raise ValueError("approved_input_fields must be non-empty and unique")
        missing_features = set(approved) - set(request.features)
        if missing_features:
            raise ValueError(
                "development request must declare every Agent-approved input field: "
                f"{sorted(missing_features)}"
            )
        if set(smoke_inputs) != set(approved):
            raise ValueError("smoke_inputs must exactly match approved_input_fields")

    def run(
        self,
        *,
        task: AgentTask,
        request: DatasetRequest,
        approved_input_fields: Sequence[str],
        smoke_inputs: Mapping[str, Sequence[int | float | None]],
    ) -> AgentFactorQuantDiscoveryResult:
        self._preflight(request, approved_input_fields, smoke_inputs)
        feedback: FactorQuantAgentFeedbackV2 | None = None
        rounds: list[AgentFactorQuantDiscoveryRound] = []
        all_candidates: list[GeneratedFeatureArtifact] = []
        seen_digests: set[str] = set()
        seen_ids: set[str] = set()

        with self.tracer.span(
            "finagent.factor_quant.discovery",
            "AGENT",
            {
                "finagent.task_id": task.task_id,
                "finagent.rounds": self.config.rounds,
                "finagent.candidates_per_round": self.config.candidates_per_round,
                "finagent.max_total_candidates": self.config.max_total_candidates,
                "finagent.development_split": self.analyzer.config.split_name,
            },
        ) as discovery_span:
            for round_index in range(1, self.config.rounds + 1):
                with self.tracer.span(
                    f"finagent.factor_quant.round.{round_index}",
                    "AGENT",
                    {
                        "finagent.round_index": round_index,
                        "finagent.prior_candidate_count": len(all_candidates),
                        "finagent.has_feedback": feedback is not None,
                    },
                ) as round_span:
                    with self.tracer.span(
                        "finagent.factor_quant.generate_candidates",
                        "AGENT",
                        {"finagent.requested_candidates": self.config.candidates_per_round},
                    ):
                        generated = tuple(
                            self.generator.generate(
                                task=task,
                                count=self.config.candidates_per_round,
                                approved_input_fields=approved_input_fields,
                                smoke_inputs=smoke_inputs,
                                round_index=round_index,
                                feedback=feedback,
                            )
                        )
                    if len(generated) != self.config.candidates_per_round:
                        raise RuntimeError(
                            "candidate generator returned an unexpected candidate count"
                        )
                    for artifact in generated:
                        if artifact.digest in seen_digests or artifact.spec.feature_id in seen_ids:
                            raise ValueError(
                                "factor quant discovery generated a duplicate across rounds"
                            )
                        seen_digests.add(artifact.digest)
                        seen_ids.add(artifact.spec.feature_id)
                    all_candidates.extend(generated)
                    if len(all_candidates) > self.config.max_total_candidates:
                        raise RuntimeError("factor quant discovery exceeded max_total_candidates")

                    with self.tracer.span(
                        "finagent.factor_quant.analyze",
                        "EVALUATOR",
                        {"finagent.cumulative_candidates": len(all_candidates)},
                    ) as analyzer_span:
                        report = self.analyzer.analyze(tuple(all_candidates), request=request)
                        analyzer_span.set_attributes(
                            {
                                "finagent.factor_quant_report_id": report.report_id,
                                "finagent.factor_quant_candidate_count": len(report.candidates),
                            }
                        )
                    with self.tracer.span(
                        "finagent.factor_quant.select",
                        "EVALUATOR",
                        {"finagent.factor_quant_report_id": report.report_id},
                    ) as selection_span:
                        selection = self.selector.select(report)
                        selection_span.set_attributes(
                            {
                                "finagent.selected_factor_count": len(selection.components),
                                "finagent.selected_feature_digests": list(
                                    selection.feature_digests
                                ),
                            }
                        )
                    feedback = FactorQuantAgentFeedbackV2.from_report(
                        report,
                        request=request,
                        selection=selection,
                    )
                    self.tracer.event(
                        "development_feedback_created",
                        {
                            "feedback_id": feedback.feedback_id,
                            "report_id": feedback.report_id,
                            "candidate_count": len(feedback.candidates),
                            "scope": "development_only",
                        },
                    )
                    rounds.append(
                        AgentFactorQuantDiscoveryRound(
                            round_index=round_index,
                            candidates=generated,
                            cumulative_report=report,
                            selection=selection,
                            feedback=feedback,
                        )
                    )
                    round_span.set_attributes(
                        {
                            "finagent.new_candidate_count": len(generated),
                            "finagent.cumulative_candidate_count": len(all_candidates),
                            "finagent.feedback_id": feedback.feedback_id,
                        }
                    )

            assert feedback is not None
            final_round = rounds[-1]
            development_ids = {item.feedback.development_data_id for item in rounds}
            if len(development_ids) != 1:
                raise RuntimeError(
                    "factor quant discovery rounds changed development data identity"
                )
            result = AgentFactorQuantDiscoveryResult(
                task_id=task.task_id,
                development_data_id=next(iter(development_ids)),
                rounds=tuple(rounds),
                candidates=tuple(all_candidates),
                final_report=final_round.cumulative_report,
                final_selection=final_round.selection,
                final_feedback=final_round.feedback,
            )
            discovery_span.set_attributes(
                {
                    "finagent.discovery_id": result.discovery_id,
                    "finagent.candidate_denominator": len(result.candidates),
                    "finagent.final_report_id": result.final_report.report_id,
                }
            )
            return result

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

import numpy as np

from finagent.agents.domain import AgentTask
from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.domain._validation import require_non_empty
from finagent.domain.research import DatasetRequest

from .agent_market import MarketFeatureCandidateGenerator
from .generated_feature_eval import (
    GeneratedFeatureEvaluationConfig,
    GeneratedFeatureMaterializer,
    GeneratedFeatureResearchTrace,
    evaluate_generated_feature_dataset,
)


_FEEDBACK_METRICS = (
    "mean_ic",
    "icir",
    "annualized_icir",
    "mean_net_return",
    "net_sharpe",
    "mean_one_way_turnover",
    "mean_gross_traded_weight",
    "coverage",
    "evaluated_periods",
    "ic_periods",
)


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _development_data_id(request: DatasetRequest, data_version: str) -> str:
    payload = {
        "data_version": require_non_empty(data_version, "data_version"),
        "universe": [asset.key for asset in request.universe],
        "labels": list(request.labels),
        "splits": {
            name: [window.start.isoformat(), window.end.isoformat()]
            for name, window in sorted(request.splits.items())
        },
    }
    return f"factor-dev-{hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:24]}"


def _aligned_return_correlation(
    left: GeneratedFeatureResearchTrace,
    right: GeneratedFeatureResearchTrace,
) -> float:
    left_map = dict(zip(left.timestamps, left.net_returns))
    right_map = dict(zip(right.timestamps, right.net_returns))
    common = sorted(set(left_map) & set(right_map))
    if len(common) < 2:
        return 0.0
    x = np.asarray([left_map[ts] for ts in common], dtype=float)
    y = np.asarray([right_map[ts] for ts in common], dtype=float)
    if float(np.std(x)) <= 1e-15 or float(np.std(y)) <= 1e-15:
        return 0.0
    return float(np.corrcoef(x, y)[0, 1])


@dataclass(frozen=True, slots=True)
class FactorCandidateDiagnostics:
    feature_id: str
    feature_digest: str
    hypothesis: str
    description: str
    lookback: int
    input_fields: tuple[str, ...]
    metrics: Mapping[str, float]
    pvalue: float

    def __post_init__(self) -> None:
        for name in ("feature_id", "feature_digest", "hypothesis", "description"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if self.lookback < 1:
            raise ValueError("lookback must be >= 1")
        if not self.input_fields or len(set(self.input_fields)) != len(self.input_fields):
            raise ValueError("input_fields must be non-empty and unique")
        metrics = {str(key): float(value) for key, value in self.metrics.items()}
        if not metrics or any(not math.isfinite(value) for value in metrics.values()):
            raise ValueError("factor diagnostic metrics must be non-empty and finite")
        pvalue = float(self.pvalue)
        if not 0.0 <= pvalue <= 1.0:
            raise ValueError("pvalue must be in [0, 1]")
        object.__setattr__(self, "metrics", MappingProxyType(metrics))
        object.__setattr__(self, "pvalue", pvalue)

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "feature_digest": self.feature_digest,
            "hypothesis": self.hypothesis,
            "description": self.description,
            "lookback": self.lookback,
            "input_fields": list(self.input_fields),
            "metrics": dict(self.metrics),
            "pvalue": self.pvalue,
        }


@dataclass(frozen=True, slots=True)
class FactorFamilyDiagnostics:
    round_index: int
    development_data_id: str
    data_version: str
    split_name: str
    selection_metric: str
    candidates: tuple[FactorCandidateDiagnostics, ...]
    net_return_correlations: Mapping[str, float]
    best_feature_digest: str

    def __post_init__(self) -> None:
        if self.round_index < 1:
            raise ValueError("round_index must be >= 1")
        for name in ("development_data_id", "data_version", "split_name", "selection_metric", "best_feature_digest"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if not self.candidates:
            raise ValueError("factor family diagnostics require candidates")
        digests = {candidate.feature_digest for candidate in self.candidates}
        if len(digests) != len(self.candidates):
            raise ValueError("factor family diagnostics contain duplicate candidates")
        if self.best_feature_digest not in digests:
            raise ValueError("best_feature_digest is not a candidate")
        correlations = {str(key): float(value) for key, value in self.net_return_correlations.items()}
        if any(not math.isfinite(value) or not -1.0 <= value <= 1.0 for value in correlations.values()):
            raise ValueError("return correlations must be finite and in [-1, 1]")
        object.__setattr__(self, "net_return_correlations", MappingProxyType(correlations))

    @property
    def analysis_id(self) -> str:
        payload = self.to_dict(include_id=False)
        return f"factor-analysis-{hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:24]}"

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.factor-family-diagnostics.v1",
            "round_index": self.round_index,
            "development_data_id": self.development_data_id,
            "data_version": self.data_version,
            "split_name": self.split_name,
            "selection_metric": self.selection_metric,
            "best_feature_digest": self.best_feature_digest,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "net_return_correlations": dict(self.net_return_correlations),
            "scope": "development_only_factor_diagnostics",
        }
        if include_id:
            payload["analysis_id"] = self.analysis_id
        return payload


@dataclass(frozen=True, slots=True)
class FactorAgentFeedback:
    analysis_id: str
    round_index: int
    development_data_id: str
    selection_metric: str
    best_feature_digest: str
    candidates: tuple[FactorCandidateDiagnostics, ...]
    net_return_correlations: Mapping[str, float]

    def __post_init__(self) -> None:
        for name in ("analysis_id", "development_data_id", "selection_metric", "best_feature_digest"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if self.round_index < 1 or not self.candidates:
            raise ValueError("feedback requires a positive round and candidates")
        correlations = {str(key): float(value) for key, value in self.net_return_correlations.items()}
        object.__setattr__(self, "net_return_correlations", MappingProxyType(correlations))

    @property
    def feedback_id(self) -> str:
        return f"factor-feedback-{hashlib.sha256(self.to_json().encode()).hexdigest()[:24]}"

    def to_dict(self) -> dict[str, object]:
        candidate_payload = []
        for candidate in self.candidates:
            metrics = {
                name: float(candidate.metrics[name])
                for name in _FEEDBACK_METRICS
                if name in candidate.metrics
            }
            candidate_payload.append(
                {
                    "feature_id": candidate.feature_id,
                    "feature_digest": candidate.feature_digest,
                    "hypothesis": candidate.hypothesis,
                    "description": candidate.description,
                    "lookback": candidate.lookback,
                    "input_fields": list(candidate.input_fields),
                    "metrics": metrics,
                    "pvalue": candidate.pvalue,
                }
            )
        return {
            "schema_version": "finagent.factor-agent-feedback.v1",
            "analysis_id": self.analysis_id,
            "round_index": self.round_index,
            "development_data_id": self.development_data_id,
            "selection_metric": self.selection_metric,
            "best_feature_digest": self.best_feature_digest,
            "candidates": candidate_payload,
            "net_return_correlations": dict(self.net_return_correlations),
            "scope": "development_only; no outer-test, holdout, promotion or paper evidence",
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_diagnostics(cls, diagnostics: FactorFamilyDiagnostics) -> FactorAgentFeedback:
        return cls(
            analysis_id=diagnostics.analysis_id,
            round_index=diagnostics.round_index,
            development_data_id=diagnostics.development_data_id,
            selection_metric=diagnostics.selection_metric,
            best_feature_digest=diagnostics.best_feature_digest,
            candidates=diagnostics.candidates,
            net_return_correlations=diagnostics.net_return_correlations,
        )


class FactorDevelopmentAnalyzer:
    """Deterministic factor lab used only during adaptive Agent discovery.

    The analyzer evaluates generated features on one explicitly declared development
    split. It reports factor-level IC, ICIR, net returns, turnover, coverage and
    redundancy diagnostics. It does not run or expose outer-test/holdout evidence.
    """

    def __init__(
        self,
        adapter,
        *,
        config: GeneratedFeatureEvaluationConfig | None = None,
        materializer: GeneratedFeatureMaterializer | None = None,
        selection_metric: str = "net_sharpe",
    ) -> None:
        self.adapter = adapter
        self.config = config or GeneratedFeatureEvaluationConfig(split_name="development")
        self.materializer = materializer or GeneratedFeatureMaterializer(adapter)
        self.selection_metric = require_non_empty(selection_metric, "selection_metric")

    def analyze(
        self,
        candidates: Sequence[GeneratedFeatureArtifact],
        *,
        request: DatasetRequest,
        round_index: int,
    ) -> FactorFamilyDiagnostics:
        artifacts = tuple(candidates)
        if not artifacts:
            raise ValueError("factor development analysis requires candidates")
        if len({artifact.digest for artifact in artifacts}) != len(artifacts):
            raise ValueError("factor development analysis received duplicate feature digests")
        if self.config.split_name not in request.splits:
            raise KeyError(f"development request has no split {self.config.split_name!r}")

        traces: dict[str, GeneratedFeatureResearchTrace] = {}
        diagnostics: list[FactorCandidateDiagnostics] = []
        for artifact in artifacts:
            dataset = self.materializer.materialize(artifact, request)
            trace = evaluate_generated_feature_dataset(
                dataset,
                feature_digest=artifact.digest,
                config=self.config,
            )
            if self.selection_metric not in trace.metrics:
                raise KeyError(f"selection metric {self.selection_metric!r} is absent from factor trace")
            traces[artifact.digest] = trace
            diagnostics.append(
                FactorCandidateDiagnostics(
                    feature_id=artifact.spec.feature_id,
                    feature_digest=artifact.digest,
                    hypothesis=artifact.spec.hypothesis,
                    description=artifact.spec.description,
                    lookback=artifact.spec.lookback,
                    input_fields=artifact.spec.input_fields,
                    metrics=trace.metrics,
                    pvalue=trace.pvalue,
                )
            )

        correlations: dict[str, float] = {}
        ordered = sorted(traces)
        for left_index, left_digest in enumerate(ordered):
            for right_digest in ordered[left_index + 1 :]:
                key = f"{left_digest}|{right_digest}"
                correlations[key] = _aligned_return_correlation(
                    traces[left_digest], traces[right_digest]
                )

        best = min(
            diagnostics,
            key=lambda item: (
                -float(item.metrics[self.selection_metric]),
                item.pvalue,
                item.feature_digest,
            ),
        )
        return FactorFamilyDiagnostics(
            round_index=round_index,
            development_data_id=_development_data_id(request, self.adapter.data_version),
            data_version=self.adapter.data_version,
            split_name=self.config.split_name,
            selection_metric=self.selection_metric,
            candidates=tuple(diagnostics),
            net_return_correlations=correlations,
            best_feature_digest=best.feature_digest,
        )


class FeedbackAwareMarketFeatureCandidateGenerator:
    """Feed deterministic development diagnostics back into any bounded generator."""

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
        feedback: FactorAgentFeedback | None = None,
    ) -> tuple[GeneratedFeatureArtifact, ...]:
        if round_index < 1:
            raise ValueError("round_index must be >= 1")
        objective = task.objective
        metadata = {**dict(task.metadata), "factor_discovery_round": str(round_index)}
        if feedback is not None:
            objective = (
                f"{task.objective}\n\n"
                "DEVELOPMENT-ONLY QUANTITATIVE FACTOR FEEDBACK:\n"
                f"{feedback.to_json()}\n\n"
                "Use this evidence to propose new economically interpretable factor hypotheses. "
                "Improve the trade-off among IC stability, net Sharpe, turnover and coverage; "
                "avoid reproducing prior feature ids/digests or trivially renaming prior formulas. "
                "The feedback contains no outer-test or sealed-holdout evidence."
            )
            metadata["factor_feedback_id"] = feedback.feedback_id
            metadata["factor_feedback_analysis_id"] = feedback.analysis_id
        child = AgentTask(
            task_id=f"{task.task_id}:discovery-round:{round_index:02d}",
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
class AgentFactorDiscoveryConfig:
    rounds: int = 2
    candidates_per_round: int = 4
    max_total_candidates: int = 8

    def __post_init__(self) -> None:
        for name in ("rounds", "candidates_per_round", "max_total_candidates"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be an integer >= 1")
        if self.rounds * self.candidates_per_round > self.max_total_candidates:
            raise ValueError("rounds * candidates_per_round exceeds max_total_candidates")


@dataclass(frozen=True, slots=True)
class AgentFactorDiscoveryRound:
    round_index: int
    candidates: tuple[GeneratedFeatureArtifact, ...]
    diagnostics: FactorFamilyDiagnostics
    feedback: FactorAgentFeedback


@dataclass(frozen=True, slots=True)
class AgentFactorDiscoveryResult:
    task_id: str
    development_data_id: str
    rounds: tuple[AgentFactorDiscoveryRound, ...]
    candidates: tuple[GeneratedFeatureArtifact, ...]
    final_feedback: FactorAgentFeedback

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", require_non_empty(self.task_id, "task_id"))
        object.__setattr__(
            self,
            "development_data_id",
            require_non_empty(self.development_data_id, "development_data_id"),
        )
        if not self.rounds or not self.candidates:
            raise ValueError("factor discovery result requires rounds and candidates")

    @property
    def discovery_id(self) -> str:
        payload = {
            "task_id": self.task_id,
            "development_data_id": self.development_data_id,
            "round_analysis_ids": [item.diagnostics.analysis_id for item in self.rounds],
            "candidate_digests": [artifact.digest for artifact in self.candidates],
        }
        return f"factor-discovery-{hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:24]}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.agent-factor-discovery.v1",
            "discovery_id": self.discovery_id,
            "task_id": self.task_id,
            "development_data_id": self.development_data_id,
            "rounds": [
                {
                    "round_index": item.round_index,
                    "candidate_digests": [artifact.digest for artifact in item.candidates],
                    "diagnostics": item.diagnostics.to_dict(),
                    "feedback": item.feedback.to_dict(),
                }
                for item in self.rounds
            ],
            "candidate_digests": [artifact.digest for artifact in self.candidates],
            "final_feedback_id": self.final_feedback.feedback_id,
            "scope": "adaptive development-only factor discovery; candidates require separate governed validation",
        }

    def write_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        return path


class AgentFactorDiscoveryLoop:
    """Iteratively couple an Agent candidate generator with deterministic factor analysis."""

    def __init__(
        self,
        *,
        generator: FeedbackAwareMarketFeatureCandidateGenerator,
        analyzer: FactorDevelopmentAnalyzer,
        config: AgentFactorDiscoveryConfig | None = None,
    ) -> None:
        self.generator = generator
        self.analyzer = analyzer
        self.config = config or AgentFactorDiscoveryConfig()

    def run(
        self,
        *,
        task: AgentTask,
        request: DatasetRequest,
        approved_input_fields: Sequence[str],
        smoke_inputs: Mapping[str, Sequence[int | float | None]],
    ) -> AgentFactorDiscoveryResult:
        feedback: FactorAgentFeedback | None = None
        rounds: list[AgentFactorDiscoveryRound] = []
        all_candidates: list[GeneratedFeatureArtifact] = []
        seen_digests: set[str] = set()
        seen_ids: set[str] = set()

        for round_index in range(1, self.config.rounds + 1):
            candidates = self.generator.generate(
                task=task,
                count=self.config.candidates_per_round,
                approved_input_fields=approved_input_fields,
                smoke_inputs=smoke_inputs,
                round_index=round_index,
                feedback=feedback,
            )
            if len(candidates) != self.config.candidates_per_round:
                raise RuntimeError("candidate generator returned an unexpected candidate count")
            for artifact in candidates:
                if artifact.digest in seen_digests or artifact.spec.feature_id in seen_ids:
                    raise ValueError("factor discovery generated a duplicate candidate across rounds")
                seen_digests.add(artifact.digest)
                seen_ids.add(artifact.spec.feature_id)
            diagnostics = self.analyzer.analyze(
                candidates,
                request=request,
                round_index=round_index,
            )
            feedback = FactorAgentFeedback.from_diagnostics(diagnostics)
            rounds.append(AgentFactorDiscoveryRound(round_index, candidates, diagnostics, feedback))
            all_candidates.extend(candidates)

        assert feedback is not None
        development_ids = {item.diagnostics.development_data_id for item in rounds}
        if len(development_ids) != 1:
            raise RuntimeError("factor discovery rounds do not share one development data identity")
        return AgentFactorDiscoveryResult(
            task_id=task.task_id,
            development_data_id=next(iter(development_ids)),
            rounds=tuple(rounds),
            candidates=tuple(all_candidates),
            final_feedback=feedback,
        )

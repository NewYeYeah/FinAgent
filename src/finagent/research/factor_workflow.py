from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from finagent.agents.domain import AgentTask
from finagent.domain._validation import require_aware_datetime, require_non_empty
from finagent.domain.assets import AssetId
from finagent.domain.experiments import ArtifactRef
from finagent.domain.research import DatasetRequest

from .agent_market import AgentMarketResearchResult
from .factor_discovery import AgentFactorDiscoveryLoop, AgentFactorDiscoveryResult
from .factor_quant_discovery import AgentFactorQuantDiscoveryLoop, AgentFactorQuantDiscoveryResult
from .governed_agent_market import GovernedAgentMarketResearchRunner


DiscoveryLoop = AgentFactorDiscoveryLoop | AgentFactorQuantDiscoveryLoop
DiscoveryResult = AgentFactorDiscoveryResult | AgentFactorQuantDiscoveryResult


@dataclass(frozen=True, slots=True)
class AgentFactorResearchWorkflowResult:
    """Identity-preserving bridge from adaptive discovery to formal market validation."""

    task_id: str
    program_id: str
    family_id: str
    validation_task_id: str
    development_end: datetime
    validation_start: datetime
    validation_end: datetime
    discovery: DiscoveryResult
    validation: AgentMarketResearchResult

    def __post_init__(self) -> None:
        for name in ("task_id", "program_id", "family_id", "validation_task_id"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        for name in ("development_end", "validation_start", "validation_end"):
            object.__setattr__(
                self,
                name,
                require_aware_datetime(getattr(self, name), name),
            )
        if self.development_end > self.validation_start:
            raise ValueError("development evidence overlaps the formal validation window")
        if self.validation_end <= self.validation_start:
            raise ValueError("validation_end must be later than validation_start")
        if self.validation.task_id != self.validation_task_id:
            raise ValueError("validation result task identity differs from workflow identity")
        if self.validation.program_id != self.program_id:
            raise ValueError("validation result ResearchProgram identity differs from workflow")
        if self.validation.family_id != self.family_id:
            raise ValueError("validation result ExperimentFamily identity differs from workflow")
        discovery_digests = {artifact.digest for artifact in self.discovery.candidates}
        validation_digests = {candidate.feature_digest for candidate in self.validation.candidates}
        if discovery_digests != validation_digests:
            raise ValueError("formal validation denominator differs from the complete discovery search")

    @property
    def workflow_id(self) -> str:
        payload = {
            "task_id": self.task_id,
            "program_id": self.program_id,
            "family_id": self.family_id,
            "validation_task_id": self.validation_task_id,
            "development_data_id": self.discovery.development_data_id,
            "discovery_id": self.discovery.discovery_id,
            "validation_study_id": self.validation.study_id,
            "development_end": self.development_end.isoformat(),
            "validation_start": self.validation_start.isoformat(),
            "validation_end": self.validation_end.isoformat(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return f"agent-factor-workflow-{hashlib.sha256(encoded).hexdigest()[:24]}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.agent-factor-research-workflow.v1",
            "workflow_id": self.workflow_id,
            "task_id": self.task_id,
            "program_id": self.program_id,
            "family_id": self.family_id,
            "validation_task_id": self.validation_task_id,
            "development_data_id": self.discovery.development_data_id,
            "discovery_id": self.discovery.discovery_id,
            "validation_study_id": self.validation.study_id,
            "development_end": self.development_end.isoformat(),
            "validation_start": self.validation_start.isoformat(),
            "validation_end": self.validation_end.isoformat(),
            "candidate_digests": [artifact.digest for artifact in self.discovery.candidates],
            "validation_aggregate_portfolio_metrics": dict(
                self.validation.aggregate_portfolio_metrics
            ),
            "scope": (
                "adaptive development-only factor discovery followed by independent "
                "governed nested market validation of the complete search denominator"
            ),
        }


class AgentFactorResearchWorkflow:
    """Join adaptive factor discovery with the existing formal market-research pipeline.

    Both the legacy FactorDevelopmentAnalyzer loop and the Factor Quant v2 cumulative
    discovery loop are accepted. Adaptive feedback remains restricted to the explicitly
    declared development split. Every generated candidate is passed into one formal
    ``ExperimentFamily`` on the non-overlapping validation window.
    """

    VERSION = "agent-factor-workflow-v1.1"

    def __init__(
        self,
        *,
        discovery_loop: DiscoveryLoop,
        validation_runner: GovernedAgentMarketResearchRunner,
        development_split: str = "development",
    ) -> None:
        self.discovery_loop = discovery_loop
        self.validation_runner = validation_runner
        self.development_split = require_non_empty(development_split, "development_split")

    @staticmethod
    def _analyzer_label(analyzer) -> str:
        config = analyzer.config
        value = getattr(config, "label_name", None)
        if value is None:
            value = getattr(config, "primary_label", None)
        if value is None:
            raise TypeError("factor discovery analyzer exposes no label contract")
        return require_non_empty(str(value), "analyzer_label")

    def _preflight(
        self,
        *,
        development_request: DatasetRequest,
        validation_universe: tuple[AssetId, ...],
        approved_input_fields: Sequence[str],
        smoke_inputs: Mapping[str, Sequence[int | float | None]],
        validation_start: datetime,
        validation_end: datetime,
    ) -> datetime:
        validation_start = require_aware_datetime(validation_start, "validation_start")
        validation_end = require_aware_datetime(validation_end, "validation_end")
        if validation_end <= validation_start:
            raise ValueError("validation_end must be later than validation_start")
        if self.development_split not in development_request.splits:
            raise KeyError(f"development request has no split {self.development_split!r}")
        if tuple(development_request.universe) != tuple(validation_universe):
            raise ValueError("development and formal validation universes must match")
        if not validation_universe or len(set(validation_universe)) != len(validation_universe):
            raise ValueError("validation universe must be non-empty and unique")

        approved = tuple(str(value) for value in approved_input_fields)
        if not approved or len(set(approved)) != len(approved):
            raise ValueError("approved_input_fields must be non-empty and unique")
        missing_declared = set(approved) - set(development_request.features)
        if missing_declared:
            raise ValueError(
                "development DatasetRequest must declare every Agent-approved input field: "
                f"{sorted(missing_declared)}"
            )
        if set(smoke_inputs) != set(approved):
            raise ValueError("smoke_inputs must exactly match approved_input_fields")

        validation_label = self.validation_runner.config.label_name
        if validation_label not in development_request.labels:
            raise ValueError(
                "development DatasetRequest must use the same forward label as formal validation"
            )
        analyzer = self.discovery_loop.analyzer
        analyzer_label = self._analyzer_label(analyzer)
        if analyzer_label != validation_label:
            raise ValueError("factor discovery and formal validation label contracts differ")
        if analyzer.config.split_name != self.development_split:
            raise ValueError("factor discovery analyzer split does not match workflow development_split")

        discovery_version = analyzer.adapter.data_version
        validation_version = self.validation_runner.adapter.data_version
        if discovery_version != validation_version:
            raise ValueError("factor discovery and formal validation data versions differ")

        development_end = development_request.splits[self.development_split].end
        if development_end > validation_start:
            raise ValueError(
                "adaptive factor development must end no later than formal validation_start"
            )
        return development_end

    def run(
        self,
        *,
        task: AgentTask,
        development_request: DatasetRequest,
        approved_input_fields: Sequence[str],
        smoke_inputs: Mapping[str, Sequence[int | float | None]],
        validation_universe: tuple[AssetId, ...],
        validation_start: datetime,
        validation_end: datetime,
        program_id: str,
        family_id: str,
        dataset_artifact: ArtifactRef | None = None,
    ) -> AgentFactorResearchWorkflowResult:
        program_id = require_non_empty(program_id, "program_id")
        family_id = require_non_empty(family_id, "family_id")
        development_end = self._preflight(
            development_request=development_request,
            validation_universe=validation_universe,
            approved_input_fields=approved_input_fields,
            smoke_inputs=smoke_inputs,
            validation_start=validation_start,
            validation_end=validation_end,
        )

        discovery = self.discovery_loop.run(
            task=task,
            request=development_request,
            approved_input_fields=approved_input_fields,
            smoke_inputs=smoke_inputs,
        )
        candidates = discovery.candidates
        if len(candidates) > self.validation_runner.config.max_candidates:
            raise ValueError(
                "complete adaptive discovery search exceeds formal validation candidate budget"
            )
        if len({artifact.digest for artifact in candidates}) != len(candidates):
            raise RuntimeError("adaptive discovery result contains duplicate feature digests")

        validation_task = AgentTask(
            task_id=f"{task.task_id}:formal-validation:{discovery.discovery_id[-12:]}",
            objective=task.objective,
            created_at=task.created_at,
            metadata={
                **dict(task.metadata),
                "agent_factor_workflow_version": self.VERSION,
                "factor_discovery_id": discovery.discovery_id,
                "development_data_id": discovery.development_data_id,
                "development_end": development_end.isoformat(),
                "validation_start": validation_start.isoformat(),
                "validation_end": validation_end.isoformat(),
                "adaptive_candidate_count": str(len(candidates)),
            },
        )
        validation = self.validation_runner.run(
            task=validation_task,
            candidates=candidates,
            universe=validation_universe,
            start=validation_start,
            end=validation_end,
            program_id=program_id,
            family_id=family_id,
            dataset_artifact=dataset_artifact,
            require_existing_family=False,
        )
        return AgentFactorResearchWorkflowResult(
            task_id=task.task_id,
            program_id=program_id,
            family_id=family_id,
            validation_task_id=validation_task.task_id,
            development_end=development_end,
            validation_start=validation_start,
            validation_end=validation_end,
            discovery=discovery,
            validation=validation,
        )

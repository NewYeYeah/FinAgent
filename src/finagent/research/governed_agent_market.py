from __future__ import annotations

from datetime import datetime
from typing import Sequence

from finagent.agents.domain import AgentTask
from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.data.ingestion.provider import ProviderCapabilities, ResearchDataRequirement
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiments import ArtifactRef, ArtifactType

from .agent_family import AgentMarketExperimentFamilyBridge
from .agent_market import AgentMarketResearchConfig, AgentMarketResearchResult, AgentMarketResearchRunner
from .programs import SQLiteResearchProgramStore
from .registry import SQLiteResearchRegistry


class GovernedAgentMarketResearchRunner:
    """Mandatory governance wrapper for promotion-oriented Agent market research.

    The existing ``AgentMarketResearchRunner`` remains the deterministic numerical
    engine. This wrapper owns the pre-evaluation governance sequence so candidate
    evidence is never computed before the ResearchProgram budget and the formal
    ExperimentFamily denominator are durable and frozen.
    """

    VERSION = "governed-agent-market-v1"

    def __init__(
        self,
        *,
        adapter,
        capabilities: ProviderCapabilities,
        requirement: ResearchDataRequirement,
        program_store: SQLiteResearchProgramStore,
        research_registry: SQLiteResearchRegistry,
        config: AgentMarketResearchConfig | None = None,
    ) -> None:
        self.config = config or AgentMarketResearchConfig()
        self.capabilities = capabilities
        self.adapter = adapter
        self.program_store = program_store
        self.research_registry = research_registry
        self.family_bridge = AgentMarketExperimentFamilyBridge(research_registry)
        self.engine = AgentMarketResearchRunner(
            adapter=adapter,
            capabilities=capabilities,
            requirement=requirement,
            program_store=program_store,
            config=self.config,
        )

    def _preflight(
        self,
        *,
        candidates: Sequence[GeneratedFeatureArtifact],
        universe: tuple[AssetId, ...],
        start: datetime,
        end: datetime,
    ) -> tuple[GeneratedFeatureArtifact, ...]:
        candidates = tuple(candidates)
        if not candidates or len(candidates) > self.config.max_candidates:
            raise ValueError("candidate family is empty or exceeds configured budget")
        if len({artifact.digest for artifact in candidates}) != len(candidates):
            raise ValueError("candidate family contains duplicate feature digests")
        if len({artifact.spec.feature_id for artifact in candidates}) != len(candidates):
            raise ValueError("candidate family contains duplicate feature ids")
        if len(universe) < 2 or len(set(universe)) != len(universe):
            raise ValueError("agent market research requires at least two unique assets")
        if any(asset.asset_type is not AssetType.ETF for asset in universe):
            raise ValueError("FinAgent 1.2 agent market research is ETF-first")
        if len({asset.currency for asset in universe}) != 1:
            raise ValueError("FinAgent 1.2 requires a single base currency")
        if end <= start:
            raise ValueError("end must be later than start")
        return candidates

    def run(
        self,
        *,
        task: AgentTask,
        candidates: Sequence[GeneratedFeatureArtifact],
        universe: tuple[AssetId, ...],
        start: datetime,
        end: datetime,
        program_id: str,
        family_id: str,
        dataset_artifact: ArtifactRef | None = None,
        require_existing_family: bool = False,
    ) -> AgentMarketResearchResult:
        candidates = self._preflight(
            candidates=candidates,
            universe=universe,
            start=start,
            end=end,
        )
        if dataset_artifact is None:
            dataset_artifact = self.family_bridge.market_dataset_artifact(
                provider=self.capabilities.provider,
                data_version=self.adapter.data_version,
            )
        if dataset_artifact.artifact_type is not ArtifactType.DATASET:
            raise ValueError("dataset_artifact must be an ArtifactType.DATASET reference")

        prepared = self.family_bridge.prepare(
            program_store=self.program_store,
            task=task,
            program_id=program_id,
            family_id=family_id,
            candidates=candidates,
            dataset=dataset_artifact,
            universe=universe,
            primary_metric=self.config.selection_metric,
            alpha=self.config.family_alpha,
            provider=self.capabilities.provider,
            require_existing=require_existing_family,
        )
        if prepared.registration.status.value not in {"frozen", "closed"}:
            raise RuntimeError("formal Agent experiment family is not frozen before evaluation")

        result = self.engine.run(
            task=task,
            candidates=candidates,
            universe=universe,
            start=start,
            end=end,
            program_id=program_id,
            family_id=family_id,
        )
        if result.program_id != prepared.registration.program_id:
            raise RuntimeError("numerical result ResearchProgram identity drifted after preparation")
        if result.family_id != prepared.registration.family_id:
            raise RuntimeError("numerical result ExperimentFamily identity drifted after preparation")
        result_digests = {candidate.feature_digest for candidate in result.candidates}
        if result_digests != set(prepared.registration.candidate_experiments):
            raise RuntimeError("numerical result candidate denominator drifted after family freeze")
        return result

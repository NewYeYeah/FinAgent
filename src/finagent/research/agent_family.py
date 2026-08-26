from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence

from finagent.agents.domain import AgentTask
from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.domain.assets import AssetId
from finagent.domain.experiment_family import (
    CorrectionMethod,
    ExperimentFamily,
    ExperimentFamilyStatus,
)
from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentSpec

from .programs import ProgramReservation, SQLiteResearchProgramStore
from .registry import SQLiteResearchRegistry


@dataclass(frozen=True, slots=True)
class AgentMarketProgramPlan:
    """Public immutable budget identity for one generated-feature candidate family.

    Its fingerprint intentionally matches the 1.2 `AgentMarketResearchRunner` plan
    identity so pre-registration can reserve budget before numerical family evaluation
    while the runner's later reservation remains idempotent.
    """

    program_id: str
    family_id: str
    alpha: float
    variants: tuple[str, ...]

    def fingerprint(self, task_id: str) -> str:
        payload = {
            "task_id": task_id,
            "program_id": self.program_id,
            "family_id": self.family_id,
            "alpha": self.alpha,
            "candidate_digests": [str(value) for value in self.variants],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class AgentMarketFamilyRegistration:
    family_id: str
    program_id: str
    dataset: ArtifactRef
    candidate_experiments: Mapping[str, str]
    status: ExperimentFamilyStatus

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_experiments",
            MappingProxyType({str(k): str(v) for k, v in self.candidate_experiments.items()}),
        )


@dataclass(frozen=True, slots=True)
class AgentMarketFamilyPreparation:
    reservation: ProgramReservation
    registration: AgentMarketFamilyRegistration


class AgentMarketExperimentFamilyBridge:
    """Bind an Agent-generated candidate denominator to the formal experiment registry.

    The bridge is deliberately evaluated *before* candidate numerical evidence. It
    creates one immutable `ExperimentSpec` per generated feature and freezes the formal
    `ExperimentFamily`, making the multiplicity denominator durable instead of relying
    only on an in-memory tuple of candidate digests.

    A frozen family can later be verified on replay/cross-provider paths without
    changing the original experiment dataset identity.
    """

    VERSION = "agent-market-family-v1"

    def __init__(self, registry: SQLiteResearchRegistry) -> None:
        self.registry = registry

    @staticmethod
    def experiment_id(family_id: str, candidate_digest: str) -> str:
        return f"{family_id}:candidate:{candidate_digest[:20]}"

    @staticmethod
    def market_dataset_artifact(
        *,
        provider: str,
        data_version: str,
        normalized_digest: str | None = None,
        uri: str = "",
    ) -> ArtifactRef:
        provider = provider.strip().lower()
        data_version = data_version.strip()
        if not provider or not data_version:
            raise ValueError("provider and data_version are required")
        digest = (normalized_digest or data_version).strip().lower()
        if not digest:
            raise ValueError("normalized dataset digest must be non-empty")
        return ArtifactRef(
            artifact_id=f"agent-market-dataset:{provider}",
            artifact_type=ArtifactType.DATASET,
            version=data_version,
            digest=digest,
            uri=uri,
        )

    @classmethod
    def program_plan(
        cls,
        *,
        program_id: str,
        family_id: str,
        alpha: float,
        candidates: Sequence[GeneratedFeatureArtifact],
    ) -> AgentMarketProgramPlan:
        return AgentMarketProgramPlan(
            program_id=program_id,
            family_id=family_id,
            alpha=float(alpha),
            variants=tuple(artifact.digest for artifact in candidates),
        )

    @staticmethod
    def _validate_candidates(candidates: Sequence[GeneratedFeatureArtifact]) -> tuple[GeneratedFeatureArtifact, ...]:
        candidates = tuple(candidates)
        if not candidates:
            raise ValueError("agent market candidate family cannot be empty")
        digests = [artifact.digest for artifact in candidates]
        if len(set(digests)) != len(digests):
            raise ValueError("agent market candidate family contains duplicate digests")
        feature_ids = [artifact.spec.feature_id for artifact in candidates]
        if len(set(feature_ids)) != len(feature_ids):
            raise ValueError("agent market candidate family contains duplicate feature ids")
        return candidates

    @classmethod
    def _spec(
        cls,
        *,
        task: AgentTask,
        program_id: str,
        family_id: str,
        artifact: GeneratedFeatureArtifact,
        dataset: ArtifactRef,
        universe: tuple[AssetId, ...],
        provider: str,
    ) -> ExperimentSpec:
        return ExperimentSpec(
            experiment_id=cls.experiment_id(family_id, artifact.digest),
            hypothesis=artifact.spec.hypothesis,
            dataset=dataset,
            code=artifact.code_artifact_ref(),
            universe=universe,
            parameters={
                "feature_id": artifact.spec.feature_id,
                "feature_digest": artifact.digest,
                "lookback": artifact.spec.lookback,
                "input_fields": "|".join(artifact.spec.input_fields),
            },
            seed=0,
            metadata={
                "agent_market_family_version": cls.VERSION,
                "task_id": task.task_id,
                "program_id": program_id,
                "family_id": family_id,
                "provider": provider.strip().lower(),
                "generated_feature_digest": artifact.digest,
                "generated_feature_id": artifact.spec.feature_id,
            },
        )

    def _registration_from_existing(
        self,
        *,
        family: ExperimentFamily,
        program_id: str,
        dataset: ArtifactRef,
        candidates: tuple[GeneratedFeatureArtifact, ...],
        universe: tuple[AssetId, ...],
    ) -> AgentMarketFamilyRegistration:
        if family.status not in {ExperimentFamilyStatus.FROZEN, ExperimentFamilyStatus.CLOSED}:
            raise PermissionError("existing Agent market experiment family must already be frozen")
        if family.metadata.get("program_id", "") != program_id:
            raise ValueError("existing experiment family belongs to a different ResearchProgram")
        expected_ids = {
            self.experiment_id(family.family_id, artifact.digest): artifact
            for artifact in candidates
        }
        actual_members = self.registry.family_members(family.family_id)
        actual_ids = {member.experiment_id for member in actual_members}
        if actual_ids != set(expected_ids):
            raise ValueError("frozen experiment-family membership does not match candidate family")

        mapping: dict[str, str] = {}
        for experiment_id, artifact in expected_ids.items():
            spec = self.registry.get_experiment(experiment_id)
            if spec.metadata.get("generated_feature_digest") != artifact.digest:
                raise ValueError("frozen experiment candidate digest does not match generated feature")
            if spec.code.digest != artifact.code_artifact_ref().digest:
                raise ValueError("frozen experiment code digest does not match generated feature")
            if tuple(spec.universe) != tuple(universe):
                raise ValueError("frozen experiment universe does not match requested universe")
            if spec.metadata.get("task_id") != family.metadata.get("task_id"):
                raise ValueError("frozen experiment task identity does not match family")
            mapping[artifact.digest] = experiment_id

        # The dataset argument may be a second provider during external validation.
        # Existing ExperimentSpecs intentionally retain the original primary dataset.
        primary_dataset = self.registry.get_experiment(next(iter(actual_ids))).dataset
        return AgentMarketFamilyRegistration(
            family_id=family.family_id,
            program_id=program_id,
            dataset=primary_dataset,
            candidate_experiments=mapping,
            status=family.status,
        )

    def ensure_frozen_family(
        self,
        *,
        task: AgentTask,
        program_id: str,
        family_id: str,
        candidates: Sequence[GeneratedFeatureArtifact],
        dataset: ArtifactRef,
        universe: tuple[AssetId, ...],
        primary_metric: str,
        alpha: float,
        provider: str,
        require_existing: bool = False,
    ) -> AgentMarketFamilyRegistration:
        candidates = self._validate_candidates(candidates)
        if not universe or len(set(universe)) != len(universe):
            raise ValueError("Agent market experiment family requires a unique non-empty universe")
        try:
            existing = self.registry.get_family(family_id)
        except KeyError:
            existing = None

        if existing is not None:
            if existing.research_question != task.objective:
                raise ValueError("existing experiment family research question does not match task")
            if existing.primary_metric != primary_metric:
                raise ValueError("existing experiment family primary metric does not match protocol")
            if abs(existing.alpha - float(alpha)) > 1e-15:
                raise ValueError("existing experiment family alpha does not match protocol")
            return self._registration_from_existing(
                family=existing,
                program_id=program_id,
                dataset=dataset,
                candidates=candidates,
                universe=universe,
            )
        if require_existing:
            raise KeyError(
                f"frozen experiment family {family_id!r} must already exist for replay/validation"
            )

        self.registry.register_artifact(dataset)
        family = ExperimentFamily(
            family_id=family_id,
            research_question=task.objective,
            primary_metric=primary_metric,
            created_at=task.created_at,
            alpha=float(alpha),
            correction_method=CorrectionMethod.HOLM,
            metadata={
                "agent_market_family_version": self.VERSION,
                "task_id": task.task_id,
                "program_id": program_id,
                "provider": provider.strip().lower(),
                "dataset_digest": dataset.digest,
                "candidate_count": str(len(candidates)),
            },
        )
        self.registry.register_family(family)
        mapping: dict[str, str] = {}
        for artifact in candidates:
            code = artifact.code_artifact_ref()
            factor = artifact.factor_artifact_ref()
            self.registry.register_artifact(code)
            self.registry.register_artifact(factor)
            spec = self._spec(
                task=task,
                program_id=program_id,
                family_id=family_id,
                artifact=artifact,
                dataset=dataset,
                universe=universe,
                provider=provider,
            )
            self.registry.register_experiment(spec)
            self.registry.add_experiment_to_family(
                family_id,
                spec.experiment_id,
                added_at=task.created_at,
            )
            mapping[artifact.digest] = spec.experiment_id

        frozen = self.registry.transition_family(family_id, ExperimentFamilyStatus.FROZEN)
        return AgentMarketFamilyRegistration(
            family_id=family_id,
            program_id=program_id,
            dataset=dataset,
            candidate_experiments=mapping,
            status=frozen.status,
        )

    def prepare(
        self,
        *,
        program_store: SQLiteResearchProgramStore,
        task: AgentTask,
        program_id: str,
        family_id: str,
        candidates: Sequence[GeneratedFeatureArtifact],
        dataset: ArtifactRef,
        universe: tuple[AssetId, ...],
        primary_metric: str,
        alpha: float,
        provider: str,
        require_existing: bool = False,
    ) -> AgentMarketFamilyPreparation:
        candidates = self._validate_candidates(candidates)
        plan = self.program_plan(
            program_id=program_id,
            family_id=family_id,
            alpha=alpha,
            candidates=candidates,
        )
        reservation = program_store.reserve_plan(plan, task_id=task.task_id)
        registration = self.ensure_frozen_family(
            task=task,
            program_id=program_id,
            family_id=family_id,
            candidates=candidates,
            dataset=dataset,
            universe=universe,
            primary_metric=primary_metric,
            alpha=alpha,
            provider=provider,
            require_existing=require_existing,
        )
        return AgentMarketFamilyPreparation(reservation, registration)

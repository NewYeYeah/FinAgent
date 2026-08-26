from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Callable, Mapping, Protocol

from finagent.domain._validation import require_aware_datetime, require_non_empty, require_finite
from finagent.domain.experiment_family import ExperimentFamilyStatus
from finagent.domain.experiments import ExperimentResult
from finagent.memory import (
    AtomicScopedEvidenceWriter,
    EvidenceVisibility,
    FailureCategory,
    FailureStage,
    MemoryNode,
    MemoryNodeType,
    SQLiteMemoryVisibilityStore,
    SQLiteResearchMemoryStore,
)

from .agent_family_validation import SQLiteAgentFamilyValidationStore
from .final_strategy import FinalStrategySpec, SQLiteFinalStrategyStore
from .programs import ResearchProgramStatus, SQLiteResearchProgramStore
from .registry import SQLiteResearchRegistry


@dataclass(frozen=True, slots=True)
class SealedHoldoutBackendResult:
    metrics: Mapping[str, float]
    backend_version: str
    notes: str = ""

    def __post_init__(self) -> None:
        normalized = {
            str(key): require_finite(value, f"metrics[{key}]") for key, value in self.metrics.items()
        }
        if not normalized:
            raise ValueError("sealed holdout backend must return at least one metric")
        object.__setattr__(self, "metrics", MappingProxyType(normalized))
        object.__setattr__(
            self, "backend_version", require_non_empty(self.backend_version, "backend_version")
        )
        object.__setattr__(self, "notes", self.notes.strip())


class SealedHoldoutBackend(Protocol):
    def evaluate(
        self,
        *,
        strategy: FinalStrategySpec,
        holdout_id: str,
    ) -> SealedHoldoutBackendResult: ...


class FunctionSealedHoldoutBackend:
    """Small adapter for a deterministic holdout resolver/evaluator function."""

    def __init__(
        self,
        fn: Callable[[FinalStrategySpec, str], Mapping[str, float]],
        *,
        version: str,
    ) -> None:
        self.fn = fn
        self.version = require_non_empty(version, "version")

    def evaluate(
        self,
        *,
        strategy: FinalStrategySpec,
        holdout_id: str,
    ) -> SealedHoldoutBackendResult:
        return SealedHoldoutBackendResult(
            metrics=self.fn(strategy, holdout_id),
            backend_version=self.version,
        )


@dataclass(frozen=True, slots=True)
class SealedHoldoutReport:
    program_id: str
    family_id: str
    strategy_id: str
    family_validation_report_id: str
    selected_experiment_id: str
    holdout_id: str
    run_id: str
    evidence_key: str
    evaluated_at: datetime
    backend_version: str
    metrics: Mapping[str, float]

    def __post_init__(self) -> None:
        for name in (
            "program_id",
            "family_id",
            "strategy_id",
            "family_validation_report_id",
            "selected_experiment_id",
            "holdout_id",
            "run_id",
            "evidence_key",
            "backend_version",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        object.__setattr__(self, "evaluated_at", require_aware_datetime(self.evaluated_at, "evaluated_at"))
        object.__setattr__(
            self,
            "metrics",
            MappingProxyType(
                {
                    str(key): require_finite(value, f"metrics[{key}]")
                    for key, value in self.metrics.items()
                }
            ),
        )

    @property
    def report_id(self) -> str:
        payload = {
            "program_id": self.program_id,
            "family_id": self.family_id,
            "strategy_id": self.strategy_id,
            "family_validation_report_id": self.family_validation_report_id,
            "selected_experiment_id": self.selected_experiment_id,
            "holdout_id": self.holdout_id,
            "run_id": self.run_id,
            "evidence_key": self.evidence_key,
            "backend_version": self.backend_version,
            "metrics": dict(self.metrics),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return f"sealed-holdout-report-{hashlib.sha256(encoded).hexdigest()[:24]}"


class SealedHoldoutEvaluator:
    """Consume one holdout only after every research degree of freedom is frozen."""

    def __init__(
        self,
        *,
        program_store: SQLiteResearchProgramStore,
        research_registry: SQLiteResearchRegistry,
        strategy_store: SQLiteFinalStrategyStore,
        family_validation_store: SQLiteAgentFamilyValidationStore,
        memory_store: SQLiteResearchMemoryStore,
        visibility_store: SQLiteMemoryVisibilityStore,
        backend: SealedHoldoutBackend,
    ) -> None:
        self.program_store = program_store
        self.research_registry = research_registry
        self.strategy_store = strategy_store
        self.family_validation_store = family_validation_store
        self.memory_store = memory_store
        self.visibility_store = visibility_store
        self.writer = AtomicScopedEvidenceWriter(memory_store, visibility_store)
        self.backend = backend

    @staticmethod
    def _run_id(strategy: FinalStrategySpec, holdout_id: str) -> str:
        digest = hashlib.sha256(
            f"{strategy.program_id}|{strategy.strategy_id}|{holdout_id}".encode()
        ).hexdigest()
        return f"sealed-holdout-{digest[:24]}"

    def _ensure_strategy_source(self, strategy: FinalStrategySpec) -> MemoryNode:
        node = MemoryNode(
            MemoryNodeType.ARTIFACT,
            strategy.strategy_id,
            f"final strategy {strategy.strategy_id}",
            strategy.created_at,
            {
                "artifact_kind": "final_strategy",
                "program_id": strategy.program_id,
                "family_id": strategy.family_id,
                "selected_experiment_id": strategy.selected_experiment_id,
                "selected_feature_digest": strategy.selected_feature_digest,
                "family_validation_report_id": strategy.family_validation_report_id,
                "research_protocol_digest": strategy.research_protocol_digest,
            },
        )
        self.memory_store.register_node(node)
        try:
            self.visibility_store.bind(
                node.key,
                EvidenceVisibility.VALIDATION,
                program_id=strategy.program_id,
                recorded_at=strategy.created_at,
            )
        except ValueError:
            scope = self.visibility_store.get(node.key)
            if (
                scope is None
                or scope.visibility is not EvidenceVisibility.VALIDATION
                or scope.program_id != strategy.program_id
            ):
                raise
        return node

    def _validate_preconditions(self, strategy: FinalStrategySpec) -> None:
        program = self.program_store.get(strategy.program_id)
        if program.status is not ResearchProgramStatus.FROZEN:
            raise PermissionError("sealed holdout evaluation requires a FROZEN ResearchProgram")
        family = self.research_registry.get_family(strategy.family_id)
        if family.status not in {ExperimentFamilyStatus.FROZEN, ExperimentFamilyStatus.CLOSED}:
            raise PermissionError("sealed holdout evaluation requires a frozen formal family")
        if family.metadata.get("program_id", "") != strategy.program_id:
            raise ValueError("final strategy family does not belong to the ResearchProgram")

        stored_strategy = self.strategy_store.for_family(strategy.program_id, strategy.family_id)
        if stored_strategy.get("strategy_id") != strategy.strategy_id:
            raise ValueError("provided final strategy is not the immutable stored strategy")
        validation = self.family_validation_store.get(strategy.family_validation_report_id)
        if validation.get("family_id") != strategy.family_id or not bool(validation.get("passed")):
            raise PermissionError("final strategy does not reference a passing formal family report")
        eligible = validation.get("eligible_experiment_ids", [])
        if strategy.selected_experiment_id not in eligible:
            raise PermissionError("selected final experiment is not statistically eligible")

        experiment = self.research_registry.get_experiment(strategy.selected_experiment_id)
        if experiment.dataset != strategy.primary_dataset:
            raise ValueError("final strategy primary dataset drifted from the formal ExperimentSpec")
        if tuple(experiment.universe) != strategy.universe:
            raise ValueError("final strategy universe drifted from the formal ExperimentSpec")
        if experiment.metadata.get("generated_feature_digest", "") != strategy.selected_feature_digest:
            raise ValueError("final strategy feature digest drifted from the formal ExperimentSpec")

    def evaluate(
        self,
        strategy: FinalStrategySpec,
        *,
        actor: str,
        accessed_at: datetime,
    ) -> SealedHoldoutReport:
        actor = require_non_empty(actor, "actor")
        accessed_at = require_aware_datetime(accessed_at, "accessed_at")
        self._validate_preconditions(strategy)
        source = self._ensure_strategy_source(strategy)

        access = self.program_store.consume_sealed_holdout(
            strategy.program_id,
            actor=actor,
            accessed_at=accessed_at,
        )
        holdout_id = access["holdout_id"]
        run_id = self._run_id(strategy, holdout_id)
        try:
            backend_result = self.backend.evaluate(strategy=strategy, holdout_id=holdout_id)
        except Exception as exc:
            failure_digest = hashlib.sha256(f"{run_id}|{type(exc).__name__}".encode()).hexdigest()
            self.writer.register_failure(
                failure_id=f"sealed-holdout-failure-{failure_digest[:24]}",
                category=FailureCategory.OPERATIONAL,
                stage=FailureStage.VALIDATION,
                summary=f"sealed holdout backend failed: {type(exc).__name__}",
                observed_at=accessed_at,
                visibility=EvidenceVisibility.SEALED_HOLDOUT,
                program_id=strategy.program_id,
                related_node_keys=(source.key,),
                metadata={
                    "strategy_id": strategy.strategy_id,
                    "holdout_id": holdout_id,
                    "exception_type": type(exc).__name__,
                },
            )
            raise

        result = ExperimentResult(
            run_id=run_id,
            metrics=backend_result.metrics,
            passed=True,
            notes=(
                "sealed holdout evaluation completed; passed=True means the computation "
                "completed, not that the strategy is approved for promotion"
            ),
        )
        written = self.writer.register_result_from_source(
            source_key=source.key,
            result=result,
            created_at=accessed_at,
            visibility=EvidenceVisibility.SEALED_HOLDOUT,
            program_id=strategy.program_id,
            extra_metadata={
                "strategy_id": strategy.strategy_id,
                "family_id": strategy.family_id,
                "family_validation_report_id": strategy.family_validation_report_id,
                "selected_experiment_id": strategy.selected_experiment_id,
                "holdout_id": holdout_id,
                "backend_version": backend_result.backend_version,
            },
        )
        return SealedHoldoutReport(
            program_id=strategy.program_id,
            family_id=strategy.family_id,
            strategy_id=strategy.strategy_id,
            family_validation_report_id=strategy.family_validation_report_id,
            selected_experiment_id=strategy.selected_experiment_id,
            holdout_id=holdout_id,
            run_id=run_id,
            evidence_key=written.node.key,
            evaluated_at=accessed_at,
            backend_version=backend_result.backend_version,
            metrics=backend_result.metrics,
        )

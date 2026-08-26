from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from finagent.domain._validation import require_aware_datetime, require_non_empty
from finagent.domain.experiments import ArtifactRef, ArtifactType
from finagent.domain.model_registry import ModelStage, RegisteredModel

from .agent_family_validation import AgentFamilyStatisticalReport
from .final_strategy import FinalStrategySpec
from .holdout_evaluation import HoldoutEvaluationReport, HoldoutEvaluationStatus
from .market_validation import AgentMarketValidationReport
from .programs import ResearchProgramStatus, SQLiteResearchProgramStore
from .registry import SQLiteResearchRegistry


class ResearchPromotionStatus(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ResearchPromotionDecision:
    program_id: str
    family_id: str
    family_validation_report_id: str
    final_strategy_id: str
    selected_experiment_id: str
    selected_feature_digest: str
    holdout_evaluation_id: str
    holdout_dataset_digest: str
    status: ResearchPromotionStatus
    reasons: tuple[str, ...]
    decided_at: datetime
    provider_validation_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "program_id",
            "family_id",
            "family_validation_report_id",
            "final_strategy_id",
            "selected_experiment_id",
            "selected_feature_digest",
            "holdout_evaluation_id",
            "holdout_dataset_digest",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        object.__setattr__(self, "reasons", tuple(str(reason).strip() for reason in self.reasons if str(reason).strip()))
        object.__setattr__(self, "provider_validation_id", self.provider_validation_id.strip())
        object.__setattr__(self, "decided_at", require_aware_datetime(self.decided_at, "decided_at"))
        if self.status is ResearchPromotionStatus.APPROVED and self.reasons:
            raise ValueError("approved research promotion cannot carry rejection reasons")
        if self.status is ResearchPromotionStatus.REJECTED and not self.reasons:
            raise ValueError("rejected research promotion requires at least one reason")

    @property
    def passed(self) -> bool:
        return self.status is ResearchPromotionStatus.APPROVED

    @property
    def promotion_id(self) -> str:
        payload = {
            "program_id": self.program_id,
            "family_id": self.family_id,
            "family_validation_report_id": self.family_validation_report_id,
            "final_strategy_id": self.final_strategy_id,
            "selected_experiment_id": self.selected_experiment_id,
            "selected_feature_digest": self.selected_feature_digest,
            "holdout_evaluation_id": self.holdout_evaluation_id,
            "holdout_dataset_digest": self.holdout_dataset_digest,
            "status": self.status.value,
            "reasons": list(self.reasons),
            "provider_validation_id": self.provider_validation_id,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return f"research-promotion-{hashlib.sha256(encoded).hexdigest()[:24]}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.research-promotion.v1",
            "promotion_id": self.promotion_id,
            "program_id": self.program_id,
            "family_id": self.family_id,
            "family_validation_report_id": self.family_validation_report_id,
            "final_strategy_id": self.final_strategy_id,
            "selected_experiment_id": self.selected_experiment_id,
            "selected_feature_digest": self.selected_feature_digest,
            "holdout_evaluation_id": self.holdout_evaluation_id,
            "holdout_dataset_digest": self.holdout_dataset_digest,
            "status": self.status.value,
            "passed": self.passed,
            "reasons": list(self.reasons),
            "provider_validation_id": self.provider_validation_id,
            "decided_at": self.decided_at.isoformat(),
        }


class ResearchPromotionGate:
    """Deterministically join development, frozen-strategy and final-OOS evidence.

    The gate deliberately introduces no new performance thresholds. Numerical
    acceptance belongs to the preregistered holdout policy. This layer checks that
    the evidence chain is internally consistent and that every mandatory stage has
    already reached its terminal state.
    """

    def __init__(self, *, program_store: SQLiteResearchProgramStore) -> None:
        self.program_store = program_store

    def evaluate(
        self,
        *,
        family_report: AgentFamilyStatisticalReport,
        strategy: FinalStrategySpec,
        holdout_report: HoldoutEvaluationReport,
        decided_at: datetime,
        provider_validation: AgentMarketValidationReport | None = None,
    ) -> ResearchPromotionDecision:
        if strategy.family_id != family_report.family_id:
            raise ValueError("FinalStrategySpec family does not match statistical report")
        if strategy.family_validation_report_id != family_report.report_id:
            raise ValueError("FinalStrategySpec statistical report identity mismatch")
        if strategy.selected_experiment_id not in family_report.experiment_order:
            raise ValueError("selected experiment is outside the formal ExperimentFamily")
        if strategy.selected_feature_digest.strip() == "":
            raise ValueError("FinalStrategySpec selected feature digest is empty")
        if holdout_report.program_id != strategy.program_id:
            raise ValueError("holdout report belongs to a different ResearchProgram")
        if holdout_report.final_strategy_id != strategy.strategy_id:
            raise ValueError("holdout report does not evaluate the frozen final strategy")

        lifecycle = self.program_store.lifecycle_snapshot(strategy.program_id)
        if lifecycle.status is not ResearchProgramStatus.CLOSED:
            raise PermissionError("research promotion requires a CLOSED ResearchProgram")
        if not lifecycle.holdout_consumed:
            raise PermissionError("research promotion requires consumed sealed holdout evidence")

        reasons: list[str] = []
        if not family_report.passed:
            reasons.append("formal ExperimentFamily statistical validation did not pass")
        if strategy.selected_experiment_id not in family_report.eligible_experiment_ids:
            reasons.append("frozen final strategy was not statistically eligible on development evidence")
        if holdout_report.status is not HoldoutEvaluationStatus.PASSED:
            reasons.append(f"sealed holdout status is {holdout_report.status.value}")
        if provider_validation is not None and not provider_validation.passed:
            reasons.append("provider validation report did not pass")

        status = ResearchPromotionStatus.REJECTED if reasons else ResearchPromotionStatus.APPROVED
        return ResearchPromotionDecision(
            program_id=strategy.program_id,
            family_id=strategy.family_id,
            family_validation_report_id=family_report.report_id,
            final_strategy_id=strategy.strategy_id,
            selected_experiment_id=strategy.selected_experiment_id,
            selected_feature_digest=strategy.selected_feature_digest,
            holdout_evaluation_id=holdout_report.evaluation_id,
            holdout_dataset_digest=holdout_report.dataset_digest,
            status=status,
            reasons=tuple(reasons),
            provider_validation_id=(provider_validation.validation_id if provider_validation else ""),
            decided_at=decided_at,
        )


class SQLiteResearchPromotionStore:
    """Append-only one-decision-per-program promotion audit store."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS research_promotions (
                    promotion_id TEXT PRIMARY KEY,
                    program_id TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def register(self, decision: ResearchPromotionDecision) -> None:
        encoded = json.dumps(
            decision.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        with sqlite3.connect(self.path) as con:
            existing = con.execute(
                "SELECT promotion_id, payload_json FROM research_promotions WHERE program_id=?",
                (decision.program_id,),
            ).fetchone()
            if existing is not None:
                if existing[0] != decision.promotion_id or existing[1] != encoded:
                    raise ValueError("ResearchProgram already has a different promotion decision")
                return
            con.execute(
                "INSERT INTO research_promotions VALUES (?, ?, ?)",
                (decision.promotion_id, decision.program_id, encoded),
            )

    def get_for_program(self, program_id: str) -> ResearchPromotionDecision:
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT payload_json FROM research_promotions WHERE program_id=?",
                (program_id,),
            ).fetchone()
        if row is None:
            raise KeyError(program_id)
        payload = json.loads(row[0])
        return ResearchPromotionDecision(
            program_id=payload["program_id"],
            family_id=payload["family_id"],
            family_validation_report_id=payload["family_validation_report_id"],
            final_strategy_id=payload["final_strategy_id"],
            selected_experiment_id=payload["selected_experiment_id"],
            selected_feature_digest=payload["selected_feature_digest"],
            holdout_evaluation_id=payload["holdout_evaluation_id"],
            holdout_dataset_digest=payload["holdout_dataset_digest"],
            status=ResearchPromotionStatus(payload["status"]),
            reasons=tuple(payload["reasons"]),
            provider_validation_id=payload.get("provider_validation_id", ""),
            decided_at=datetime.fromisoformat(payload["decided_at"]),
        )

    def snapshot(self, program_id: str) -> Mapping[str, object]:
        return MappingProxyType(self.get_for_program(program_id).to_dict())


@dataclass(frozen=True, slots=True)
class ResearchPromotionResult:
    decision: ResearchPromotionDecision
    model: RegisteredModel | None


class ResearchPromotionService:
    """Persist a terminal research decision and materialize an approved VALIDATED model."""

    VERSION = "research-promotion-service-v1"

    def __init__(
        self,
        *,
        gate: ResearchPromotionGate,
        promotion_store: SQLiteResearchPromotionStore,
        registry: SQLiteResearchRegistry,
    ) -> None:
        self.gate = gate
        self.promotion_store = promotion_store
        self.registry = registry

    @staticmethod
    def _model_artifact(strategy: FinalStrategySpec) -> ArtifactRef:
        payload = {
            "strategy_id": strategy.strategy_id,
            "selected_experiment_id": strategy.selected_experiment_id,
            "selected_feature_digest": strategy.selected_feature_digest,
            "research_protocol_digest": strategy.research_protocol_digest,
            "primary_dataset_digest": strategy.primary_dataset.digest,
            "universe": sorted(asset.key for asset in strategy.universe),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        return ArtifactRef(
            artifact_id=f"research-model:{strategy.strategy_id}",
            artifact_type=ArtifactType.MODEL,
            version="1.2.2",
            digest=digest,
        )

    @staticmethod
    def _model_id(strategy: FinalStrategySpec) -> str:
        return f"validated-{strategy.strategy_id}"

    def _ensure_validated_model(
        self,
        *,
        decision: ResearchPromotionDecision,
        strategy: FinalStrategySpec,
        holdout_report: HoldoutEvaluationReport,
    ) -> RegisteredModel:
        artifact = self._model_artifact(strategy)
        model_id = self._model_id(strategy)
        try:
            current = self.registry.get_model(model_id)
        except KeyError:
            candidate = RegisteredModel(
                model_id=model_id,
                family="generated-feature-strategy",
                artifact=artifact,
                stage=ModelStage.CANDIDATE,
                created_at=decision.decided_at,
                metrics=holdout_report.metrics,
                metadata={
                    "promotion_id": decision.promotion_id,
                    "program_id": decision.program_id,
                    "family_id": decision.family_id,
                    "final_strategy_id": decision.final_strategy_id,
                    "holdout_evaluation_id": decision.holdout_evaluation_id,
                },
            )
            self.registry.register_model(candidate)
            current = candidate
        else:
            if current.artifact != artifact:
                raise ValueError("research promotion model_id is bound to a different artifact")
            if current.family != "generated-feature-strategy":
                raise ValueError("research promotion model family identity drifted")

        if current.stage is ModelStage.CANDIDATE:
            return self.registry.promote_model(
                current.model_id,
                ModelStage.VALIDATED,
                changed_at=decision.decided_at,
                reason=f"research promotion {decision.promotion_id} approved",
                actor="research-promotion-gate",
            )
        return current

    def promote(
        self,
        *,
        family_report: AgentFamilyStatisticalReport,
        strategy: FinalStrategySpec,
        holdout_report: HoldoutEvaluationReport,
        decided_at: datetime,
        provider_validation: AgentMarketValidationReport | None = None,
    ) -> ResearchPromotionResult:
        try:
            existing = self.promotion_store.get_for_program(strategy.program_id)
        except KeyError:
            existing = None

        if existing is None:
            decision = self.gate.evaluate(
                family_report=family_report,
                strategy=strategy,
                holdout_report=holdout_report,
                provider_validation=provider_validation,
                decided_at=decided_at,
            )
            self.promotion_store.register(decision)
        else:
            expected_provider_id = provider_validation.validation_id if provider_validation else ""
            if (
                existing.family_validation_report_id != family_report.report_id
                or existing.final_strategy_id != strategy.strategy_id
                or existing.holdout_evaluation_id != holdout_report.evaluation_id
                or existing.provider_validation_id != expected_provider_id
            ):
                raise ValueError("existing promotion decision belongs to different frozen evidence")
            decision = existing

        if not decision.passed:
            return ResearchPromotionResult(decision=decision, model=None)
        model = self._ensure_validated_model(
            decision=decision,
            strategy=strategy,
            holdout_report=holdout_report,
        )
        return ResearchPromotionResult(decision=decision, model=model)

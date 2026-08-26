from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from finagent.domain._validation import require_aware_datetime, require_non_empty
from finagent.domain.assets import AssetId
from finagent.domain.experiment_family import ExperimentFamilyStatus
from finagent.domain.experiments import ArtifactRef, ArtifactType

from .agent_family_validation import AgentFamilyStatisticalReport
from .agent_market import AgentMarketResearchConfig
from .programs import ProgramLifecycleEvent, ResearchProgramStatus, SQLiteResearchProgramStore
from .registry import SQLiteResearchRegistry


FINAL_STRATEGY_SELECTION_RULE = (
    "eligible_max_dsr_probability_then_adjusted_pvalue_then_experiment_id:v1"
)


def _artifact_payload(artifact: ArtifactRef) -> dict[str, str]:
    return {
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type.value,
        "version": artifact.version,
        "digest": artifact.digest,
        "uri": artifact.uri,
    }


def _asset_payload(asset: AssetId) -> dict[str, str]:
    return {
        "symbol": asset.symbol,
        "asset_type": asset.asset_type.value,
        "venue": asset.venue,
        "currency": asset.currency,
    }


def _canonical_protocol(config: AgentMarketResearchConfig) -> str:
    payload = {
        "schema_version": "finagent.final-strategy-protocol.v1",
        "agent_market": {
            "max_candidates": config.max_candidates,
            "family_alpha": config.family_alpha,
            "selection_metric": config.selection_metric,
            "label_name": config.label_name,
            "transaction_cost_bps": config.transaction_cost_bps,
            "min_cross_section": config.min_cross_section,
            "min_periods": config.min_periods,
            "require_statistical_acceptance": config.require_statistical_acceptance,
        },
        "market": asdict(config.market),
        "implementation": {
            "alpha_model": "GeneratedFeatureAlphaModel",
            "risk_model": "GARCH11RiskModel",
            "portfolio_optimizer": "MeanVarianceOptimizer",
            "risk_gate": "StaticRiskGate",
            "execution_engine": "TimedEventDrivenBacktestEngine",
            "execution_price_field": "open",
            "annualization_factor": 252.0,
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True, slots=True)
class FinalStrategySpec:
    program_id: str
    family_id: str
    family_validation_report_id: str
    selected_experiment_id: str
    selected_feature_digest: str
    primary_dataset: ArtifactRef
    universe: tuple[AssetId, ...]
    research_protocol_json: str
    research_protocol_digest: str
    selection_rule: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "program_id",
            "family_id",
            "family_validation_report_id",
            "selected_experiment_id",
            "selected_feature_digest",
            "research_protocol_json",
            "research_protocol_digest",
            "selection_rule",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if self.primary_dataset.artifact_type is not ArtifactType.DATASET:
            raise ValueError("primary_dataset must be an ArtifactType.DATASET")
        if not self.universe or len(set(self.universe)) != len(self.universe):
            raise ValueError("final strategy universe must be non-empty and unique")
        created_at = require_aware_datetime(self.created_at, "created_at")
        protocol_digest = hashlib.sha256(self.research_protocol_json.encode()).hexdigest()
        if protocol_digest != self.research_protocol_digest:
            raise ValueError("research_protocol_digest does not match research_protocol_json")
        object.__setattr__(self, "created_at", created_at)

    def identity_payload(self) -> dict[str, object]:
        return {
            "program_id": self.program_id,
            "family_id": self.family_id,
            "family_validation_report_id": self.family_validation_report_id,
            "selected_experiment_id": self.selected_experiment_id,
            "selected_feature_digest": self.selected_feature_digest,
            "primary_dataset": _artifact_payload(self.primary_dataset),
            "universe": [_asset_payload(asset) for asset in self.universe],
            "research_protocol_digest": self.research_protocol_digest,
            "selection_rule": self.selection_rule,
        }

    @property
    def strategy_id(self) -> str:
        encoded = json.dumps(
            self.identity_payload(), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        return f"final-strategy-{hashlib.sha256(encoded).hexdigest()[:24]}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.final-strategy.v1",
            "strategy_id": self.strategy_id,
            **self.identity_payload(),
            "research_protocol_json": self.research_protocol_json,
            "created_at": self.created_at.isoformat(),
        }


class FinalStrategySelector:
    """Select one immutable winner from statistically eligible development evidence."""

    def __init__(self, registry: SQLiteResearchRegistry) -> None:
        self.registry = registry

    def select(
        self,
        *,
        program_id: str,
        report: AgentFamilyStatisticalReport,
        config: AgentMarketResearchConfig,
        created_at: datetime,
    ) -> FinalStrategySpec:
        family = self.registry.get_family(report.family_id)
        if family.status is not ExperimentFamilyStatus.FROZEN:
            raise ValueError("final strategy selection requires a FROZEN ExperimentFamily")
        if family.metadata.get("program_id", "") != program_id:
            raise ValueError("ExperimentFamily does not belong to the requested ResearchProgram")
        members = self.registry.family_members(report.family_id)
        experiment_order = tuple(member.experiment_id for member in members)
        if report.experiment_order != experiment_order:
            raise ValueError("statistical report denominator does not match formal family membership")
        if family.metadata.get("dataset_digest", "") != report.dataset_digest:
            raise ValueError("statistical report dataset does not match formal family dataset")

        eligible = [candidate for candidate in report.candidates if candidate.passed]
        if not eligible:
            raise PermissionError("no statistically eligible candidate can be frozen as final strategy")
        eligible.sort(
            key=lambda item: (
                -item.deflated_sharpe.deflated_probability,
                item.adjusted_pvalue,
                item.experiment_id,
            )
        )
        selected = eligible[0]
        if selected.experiment_id not in experiment_order:
            raise ValueError("eligible candidate is not a formal family member")
        experiment = self.registry.get_experiment(selected.experiment_id)
        feature_digest = str(experiment.metadata.get("generated_feature_digest", "")).strip()
        if not feature_digest:
            raise ValueError("selected ExperimentSpec is not a generated-feature candidate")
        if experiment.dataset.digest != report.dataset_digest:
            raise ValueError("selected ExperimentSpec dataset does not match statistical report")

        protocol_json = _canonical_protocol(config)
        return FinalStrategySpec(
            program_id=program_id,
            family_id=report.family_id,
            family_validation_report_id=report.report_id,
            selected_experiment_id=selected.experiment_id,
            selected_feature_digest=feature_digest,
            primary_dataset=experiment.dataset,
            universe=experiment.universe,
            research_protocol_json=protocol_json,
            research_protocol_digest=hashlib.sha256(protocol_json.encode()).hexdigest(),
            selection_rule=FINAL_STRATEGY_SELECTION_RULE,
            created_at=created_at,
        )


class SQLiteFinalStrategyStore:
    """Immutable one-final-strategy-per-(program,family) registry."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS final_strategies (
                    strategy_id TEXT PRIMARY KEY,
                    program_id TEXT NOT NULL,
                    family_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(program_id, family_id)
                );
                """
            )

    def register(self, spec: FinalStrategySpec) -> None:
        encoded = json.dumps(
            spec.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        with sqlite3.connect(self.path) as con:
            existing_family = con.execute(
                "SELECT strategy_id, payload_json FROM final_strategies "
                "WHERE program_id=? AND family_id=?",
                (spec.program_id, spec.family_id),
            ).fetchone()
            if existing_family is not None:
                if existing_family[0] != spec.strategy_id or existing_family[1] != encoded:
                    raise ValueError(
                        "a different final strategy is already frozen for this program/family"
                    )
                return
            con.execute(
                "INSERT INTO final_strategies VALUES (?, ?, ?, ?)",
                (spec.strategy_id, spec.program_id, spec.family_id, encoded),
            )

    def get_payload(self, strategy_id: str) -> Mapping[str, object]:
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT payload_json FROM final_strategies WHERE strategy_id=?",
                (strategy_id,),
            ).fetchone()
        if row is None:
            raise KeyError(strategy_id)
        return MappingProxyType(json.loads(row[0]))

    def for_family(self, program_id: str, family_id: str) -> Mapping[str, object]:
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT payload_json FROM final_strategies WHERE program_id=? AND family_id=?",
                (program_id, family_id),
            ).fetchone()
        if row is None:
            raise KeyError((program_id, family_id))
        return MappingProxyType(json.loads(row[0]))


@dataclass(frozen=True, slots=True)
class FinalStrategyFreezeResult:
    strategy: FinalStrategySpec
    lifecycle_event: ProgramLifecycleEvent


class FinalStrategyFreezer:
    """Persist the final strategy first, then freeze the ResearchProgram search space."""

    def __init__(
        self,
        *,
        selector: FinalStrategySelector,
        strategy_store: SQLiteFinalStrategyStore,
        program_store: SQLiteResearchProgramStore,
    ) -> None:
        self.selector = selector
        self.strategy_store = strategy_store
        self.program_store = program_store

    def freeze(
        self,
        *,
        program_id: str,
        report: AgentFamilyStatisticalReport,
        config: AgentMarketResearchConfig,
        actor: str,
        frozen_at: datetime,
    ) -> FinalStrategyFreezeResult:
        actor = require_non_empty(actor, "actor")
        program = self.program_store.get(program_id)
        if program.status not in {ResearchProgramStatus.OPEN, ResearchProgramStatus.FROZEN}:
            raise PermissionError("final strategy cannot be frozen for a CLOSED ResearchProgram")
        strategy = self.selector.select(
            program_id=program_id,
            report=report,
            config=config,
            created_at=frozen_at,
        )
        self.strategy_store.register(strategy)
        lifecycle_event = self.program_store.freeze_program(
            program_id,
            actor=actor,
            reason=f"final strategy {strategy.strategy_id} frozen before sealed holdout access",
            occurred_at=frozen_at,
        )
        if self.program_store.get(program_id).status is not ResearchProgramStatus.FROZEN:
            raise RuntimeError("ResearchProgram did not reach FROZEN after final strategy persistence")
        return FinalStrategyFreezeResult(strategy, lifecycle_event)

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

import numpy as np

from finagent.domain._validation import require_aware_datetime, require_non_empty
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiments import ArtifactRef, ArtifactType

from .agent_family_validation import AgentFamilyDevelopmentEvidence, AgentFamilyStatisticalReport
from .final_strategy import FinalStrategySpec
from .programs import ResearchProgramStatus, SQLiteResearchProgramStore
from .registry import SQLiteResearchRegistry


def _artifact_payload(artifact: ArtifactRef) -> dict[str, str]:
    return {
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type.value,
        "version": artifact.version,
        "digest": artifact.digest,
        "uri": artifact.uri,
    }


def _artifact_from_payload(payload: Mapping[str, object]) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=str(payload["artifact_id"]),
        artifact_type=ArtifactType(str(payload["artifact_type"])),
        version=str(payload["version"]),
        digest=str(payload["digest"]),
        uri=str(payload.get("uri", "")),
    )


def _asset_payload(asset: AssetId) -> dict[str, str]:
    return {
        "symbol": asset.symbol,
        "asset_type": asset.asset_type.value,
        "venue": asset.venue,
        "currency": asset.currency,
    }


def _asset_from_payload(payload: Mapping[str, object]) -> AssetId:
    return AssetId(
        symbol=str(payload["symbol"]),
        asset_type=AssetType(str(payload["asset_type"])),
        venue=str(payload.get("venue", "")),
        currency=str(payload.get("currency", "USD")),
    )


def development_evidence_digest(evidence: AgentFamilyDevelopmentEvidence) -> str:
    """Hash the exact development time series used before final-strategy freeze."""

    payload = {
        "schema_version": "finagent.development-evidence-seal.v1",
        "family_id": evidence.family_id,
        "experiment_order": list(evidence.experiment_order),
        "timestamps": list(evidence.timestamps),
        "trial_returns": {
            experiment_id: list(evidence.trial_returns[experiment_id])
            for experiment_id in evidence.experiment_order
        },
        "pvalues": {
            experiment_id: evidence.pvalues[experiment_id]
            for experiment_id in evidence.experiment_order
        },
        "dataset_digest": evidence.dataset_digest,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _development_bounds(evidence: AgentFamilyDevelopmentEvidence) -> tuple[datetime, datetime]:
    timestamps = tuple(datetime.fromisoformat(value) for value in evidence.timestamps)
    if any(value.tzinfo is None or value.utcoffset() is None for value in timestamps):
        raise ValueError("development evidence timestamps must be timezone-aware")
    if any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise ValueError("development evidence timestamps must be strictly increasing")
    return timestamps[0], timestamps[-1]


@dataclass(frozen=True, slots=True)
class SealedHoldoutSpec:
    """Pre-registered final OOS data/time identity.

    Registration is required before any ResearchProgram family budget is spent. The
    holdout interval is therefore not allowed to move after development results are
    observed. ``training_*`` freezes the final pre-holdout calibration window; the
    one-shot evaluator may not silently expand or shift either split.
    """

    holdout_id: str
    program_id: str
    dataset: ArtifactRef
    universe: tuple[AssetId, ...]
    provider: str
    data_version: str
    training_start: datetime
    training_end: datetime
    holdout_start: datetime
    holdout_end: datetime
    created_at: datetime

    def __post_init__(self) -> None:
        for name in ("holdout_id", "program_id", "provider", "data_version"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if self.dataset.artifact_type is not ArtifactType.DATASET:
            raise ValueError("sealed holdout dataset must be an ArtifactType.DATASET")
        if len(self.universe) < 2 or len(set(self.universe)) != len(self.universe):
            raise ValueError("sealed holdout universe must contain at least two unique assets")
        if len({asset.currency for asset in self.universe}) != 1:
            raise ValueError("sealed holdout universe must use one base currency")
        training_start = require_aware_datetime(self.training_start, "training_start")
        training_end = require_aware_datetime(self.training_end, "training_end")
        holdout_start = require_aware_datetime(self.holdout_start, "holdout_start")
        holdout_end = require_aware_datetime(self.holdout_end, "holdout_end")
        created_at = require_aware_datetime(self.created_at, "created_at")
        if not training_start < training_end <= holdout_start < holdout_end:
            raise ValueError(
                "sealed holdout windows must satisfy training_start < training_end "
                "<= holdout_start < holdout_end"
            )
        object.__setattr__(self, "training_start", training_start)
        object.__setattr__(self, "training_end", training_end)
        object.__setattr__(self, "holdout_start", holdout_start)
        object.__setattr__(self, "holdout_end", holdout_end)
        object.__setattr__(self, "created_at", created_at)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.sealed-holdout-spec.v1",
            "holdout_id": self.holdout_id,
            "program_id": self.program_id,
            "dataset": _artifact_payload(self.dataset),
            "universe": [_asset_payload(asset) for asset in self.universe],
            "provider": self.provider,
            "data_version": self.data_version,
            "training_start": self.training_start.isoformat(),
            "training_end": self.training_end.isoformat(),
            "holdout_start": self.holdout_start.isoformat(),
            "holdout_end": self.holdout_end.isoformat(),
            "created_at": self.created_at.isoformat(),
        }

    @property
    def spec_digest(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


class SQLiteSealedHoldoutStore:
    """Immutable pre-research registry for final OOS specifications."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS sealed_holdouts (
                    holdout_id TEXT PRIMARY KEY,
                    program_id TEXT NOT NULL UNIQUE,
                    spec_digest TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def register_before_research(
        self,
        spec: SealedHoldoutSpec,
        *,
        program_store: SQLiteResearchProgramStore,
    ) -> None:
        program = program_store.get(spec.program_id)
        if program.sealed_holdout_id != spec.holdout_id:
            raise ValueError("ResearchProgram.sealed_holdout_id does not match SealedHoldoutSpec")
        if program.status is not ResearchProgramStatus.OPEN:
            raise PermissionError("sealed holdout must be registered while ResearchProgram is OPEN")
        budget = program_store.budget_snapshot(spec.program_id)
        if budget.family_count or budget.experiment_count or budget.alpha_spent > 1e-15:
            raise PermissionError("sealed holdout must be registered before any research budget is spent")

        encoded = json.dumps(
            spec.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        with sqlite3.connect(self.path) as con:
            existing = con.execute(
                "SELECT program_id, spec_digest, payload_json FROM sealed_holdouts "
                "WHERE holdout_id=?",
                (spec.holdout_id,),
            ).fetchone()
            candidate = (spec.program_id, spec.spec_digest, encoded)
            if existing is not None:
                if tuple(existing) != candidate:
                    raise ValueError("sealed holdout identity is immutable")
                return
            program_row = con.execute(
                "SELECT holdout_id FROM sealed_holdouts WHERE program_id=?",
                (spec.program_id,),
            ).fetchone()
            if program_row is not None:
                raise ValueError("ResearchProgram already has a different sealed holdout")
            con.execute(
                "INSERT INTO sealed_holdouts VALUES (?, ?, ?, ?)",
                (spec.holdout_id, spec.program_id, spec.spec_digest, encoded),
            )

    def get(self, holdout_id: str) -> SealedHoldoutSpec:
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT payload_json FROM sealed_holdouts WHERE holdout_id=?",
                (holdout_id,),
            ).fetchone()
        if row is None:
            raise KeyError(holdout_id)
        payload = json.loads(row[0])
        return SealedHoldoutSpec(
            holdout_id=payload["holdout_id"],
            program_id=payload["program_id"],
            dataset=_artifact_from_payload(payload["dataset"]),
            universe=tuple(_asset_from_payload(item) for item in payload["universe"]),
            provider=payload["provider"],
            data_version=payload["data_version"],
            training_start=datetime.fromisoformat(payload["training_start"]),
            training_end=datetime.fromisoformat(payload["training_end"]),
            holdout_start=datetime.fromisoformat(payload["holdout_start"]),
            holdout_end=datetime.fromisoformat(payload["holdout_end"]),
            created_at=datetime.fromisoformat(payload["created_at"]),
        )


@dataclass(frozen=True, slots=True)
class HoldoutEligibilitySeal:
    """Immutable bridge from development evidence to one frozen final OOS run."""

    program_id: str
    family_id: str
    family_validation_report_id: str
    final_strategy_id: str
    selected_experiment_id: str
    selected_feature_digest: str
    holdout_id: str
    holdout_spec_digest: str
    development_evidence_digest: str
    development_start: datetime
    development_end: datetime
    created_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "program_id",
            "family_id",
            "family_validation_report_id",
            "final_strategy_id",
            "selected_experiment_id",
            "selected_feature_digest",
            "holdout_id",
            "holdout_spec_digest",
            "development_evidence_digest",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        development_start = require_aware_datetime(self.development_start, "development_start")
        development_end = require_aware_datetime(self.development_end, "development_end")
        created_at = require_aware_datetime(self.created_at, "created_at")
        if development_end < development_start:
            raise ValueError("development_end cannot precede development_start")
        object.__setattr__(self, "development_start", development_start)
        object.__setattr__(self, "development_end", development_end)
        object.__setattr__(self, "created_at", created_at)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.holdout-eligibility-seal.v1",
            "program_id": self.program_id,
            "family_id": self.family_id,
            "family_validation_report_id": self.family_validation_report_id,
            "final_strategy_id": self.final_strategy_id,
            "selected_experiment_id": self.selected_experiment_id,
            "selected_feature_digest": self.selected_feature_digest,
            "holdout_id": self.holdout_id,
            "holdout_spec_digest": self.holdout_spec_digest,
            "development_evidence_digest": self.development_evidence_digest,
            "development_start": self.development_start.isoformat(),
            "development_end": self.development_end.isoformat(),
            "created_at": self.created_at.isoformat(),
        }

    @property
    def seal_id(self) -> str:
        encoded = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        return f"holdout-eligibility-{hashlib.sha256(encoded).hexdigest()[:24]}"


class HoldoutEligibilitySealer:
    """Bind development evidence, statistical gate, final strategy and holdout identity."""

    def __init__(
        self,
        *,
        registry: SQLiteResearchRegistry,
        program_store: SQLiteResearchProgramStore,
        holdout_store: SQLiteSealedHoldoutStore,
    ) -> None:
        self.registry = registry
        self.program_store = program_store
        self.holdout_store = holdout_store

    def seal(
        self,
        *,
        strategy: FinalStrategySpec,
        report: AgentFamilyStatisticalReport,
        evidence: AgentFamilyDevelopmentEvidence,
        created_at: datetime,
    ) -> HoldoutEligibilitySeal:
        program = self.program_store.get(strategy.program_id)
        if program.status is not ResearchProgramStatus.FROZEN:
            raise PermissionError("holdout eligibility requires a FROZEN ResearchProgram")
        if not program.sealed_holdout_id:
            raise ValueError("ResearchProgram has no sealed_holdout_id")
        holdout = self.holdout_store.get(program.sealed_holdout_id)
        if holdout.program_id != strategy.program_id:
            raise ValueError("SealedHoldoutSpec belongs to a different ResearchProgram")
        if tuple(holdout.universe) != tuple(strategy.universe):
            raise ValueError("sealed holdout universe does not match FinalStrategySpec")

        family = self.registry.get_family(strategy.family_id)
        if family.metadata.get("program_id", "") != strategy.program_id:
            raise ValueError("FinalStrategySpec family does not belong to ResearchProgram")
        members = self.registry.family_members(strategy.family_id)
        experiment_order = tuple(member.experiment_id for member in members)
        if evidence.family_id != strategy.family_id or report.family_id != strategy.family_id:
            raise ValueError("development evidence/report family does not match FinalStrategySpec")
        if evidence.experiment_order != experiment_order or report.experiment_order != experiment_order:
            raise ValueError("development evidence/report denominator drifted from formal family")
        if report.observation_count != len(evidence.timestamps):
            raise ValueError("statistical report observation count does not match development evidence")
        if not (
            evidence.dataset_digest
            == report.dataset_digest
            == strategy.primary_dataset.digest
        ):
            raise ValueError("development dataset identity drifted before holdout sealing")
        ordered_pvalues = tuple(float(evidence.pvalues[item]) for item in experiment_order)
        if not np.array_equal(
            np.asarray(report.multiple_testing.raw_pvalues, dtype=float),
            np.asarray(ordered_pvalues, dtype=float),
        ):
            raise ValueError("statistical report p-values do not match development evidence")
        if strategy.family_validation_report_id != report.report_id:
            raise ValueError("FinalStrategySpec points to a different statistical report")
        eligible = {item.experiment_id: item for item in report.candidates if item.passed}
        if strategy.selected_experiment_id not in eligible:
            raise PermissionError("final strategy is not statistically eligible for holdout access")
        selected_spec = self.registry.get_experiment(strategy.selected_experiment_id)
        formal_feature_digest = str(
            selected_spec.metadata.get("generated_feature_digest", "")
        ).strip()
        if formal_feature_digest != strategy.selected_feature_digest:
            raise ValueError("FinalStrategySpec feature digest drifted from formal ExperimentSpec")

        development_start, development_end = _development_bounds(evidence)
        if development_start < holdout.training_start:
            raise ValueError("development evidence starts before pre-registered training window")
        if development_end >= holdout.holdout_start:
            raise PermissionError("development evidence overlaps the sealed holdout interval")
        if holdout.training_end > holdout.holdout_start:
            raise ValueError("sealed holdout training window overlaps final OOS window")

        return HoldoutEligibilitySeal(
            program_id=strategy.program_id,
            family_id=strategy.family_id,
            family_validation_report_id=report.report_id,
            final_strategy_id=strategy.strategy_id,
            selected_experiment_id=strategy.selected_experiment_id,
            selected_feature_digest=strategy.selected_feature_digest,
            holdout_id=holdout.holdout_id,
            holdout_spec_digest=holdout.spec_digest,
            development_evidence_digest=development_evidence_digest(evidence),
            development_start=development_start,
            development_end=development_end,
            created_at=created_at,
        )


class SQLiteHoldoutEligibilityStore:
    """Append-only pre-access seal store; one final seal per ResearchProgram."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS holdout_eligibility_seals (
                    seal_id TEXT PRIMARY KEY,
                    program_id TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def register(self, seal: HoldoutEligibilitySeal) -> None:
        encoded = json.dumps(
            seal.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        with sqlite3.connect(self.path) as con:
            existing_program = con.execute(
                "SELECT seal_id, payload_json FROM holdout_eligibility_seals WHERE program_id=?",
                (seal.program_id,),
            ).fetchone()
            if existing_program is not None:
                if existing_program[0] != seal.seal_id or existing_program[1] != encoded:
                    raise ValueError("ResearchProgram already has a different holdout eligibility seal")
                return
            con.execute(
                "INSERT INTO holdout_eligibility_seals VALUES (?, ?, ?)",
                (seal.seal_id, seal.program_id, encoded),
            )

    def get_for_program(self, program_id: str) -> Mapping[str, object]:
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT payload_json FROM holdout_eligibility_seals WHERE program_id=?",
                (program_id,),
            ).fetchone()
        if row is None:
            raise KeyError(program_id)
        return MappingProxyType(json.loads(row[0]))

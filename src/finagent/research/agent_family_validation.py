from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np

from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.domain.assets import AssetId
from finagent.domain.experiment_family import ExperimentFamilyStatus
from finagent.domain.experiments import ArtifactRef

from .agent_market import AgentMarketResearchConfig, one_sided_mean_pvalue
from .generated_feature_eval import (
    GeneratedFeatureEvaluationConfig,
    GeneratedFeatureNestedWalkForwardStudy,
)
from .registry import SQLiteResearchRegistry
from .validation import (
    DeflatedSharpeResult,
    MultipleTestingResult,
    PBOResult,
    RealityCheckResult,
    adjust_pvalues,
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_ratio,
    whites_reality_check,
)


@dataclass(frozen=True, slots=True)
class AgentFamilyDevelopmentEvidence:
    """Aligned development-only return evidence for one formal ExperimentFamily."""

    family_id: str
    experiment_order: tuple[str, ...]
    timestamps: tuple[str, ...]
    trial_returns: Mapping[str, tuple[float, ...]]
    pvalues: Mapping[str, float]
    dataset_digest: str

    def __post_init__(self) -> None:
        expected = set(self.experiment_order)
        if not self.family_id.strip() or not self.experiment_order:
            raise ValueError("family_id and experiment_order are required")
        if len(expected) != len(self.experiment_order):
            raise ValueError("experiment_order cannot contain duplicates")
        if set(self.trial_returns) != expected or set(self.pvalues) != expected:
            raise ValueError("development evidence must contain exactly experiment_order members")
        if not self.timestamps or len(set(self.timestamps)) != len(self.timestamps):
            raise ValueError("development timestamps must be non-empty and non-overlapping")
        n = len(self.timestamps)
        normalized_returns: dict[str, tuple[float, ...]] = {}
        for experiment_id in self.experiment_order:
            values = tuple(float(value) for value in self.trial_returns[experiment_id])
            if len(values) != n or not np.isfinite(np.asarray(values, dtype=float)).all():
                raise ValueError("all development return series must align and be finite")
            normalized_returns[experiment_id] = values
        normalized_pvalues = {key: float(value) for key, value in self.pvalues.items()}
        if any(not 0.0 <= value <= 1.0 for value in normalized_pvalues.values()):
            raise ValueError("development pvalues must be in [0, 1]")
        if not self.dataset_digest.strip():
            raise ValueError("dataset_digest is required")
        object.__setattr__(self, "trial_returns", MappingProxyType(normalized_returns))
        object.__setattr__(self, "pvalues", MappingProxyType(normalized_pvalues))


class AgentFamilyDevelopmentEvidenceBuilder:
    """Recompute all formal candidates on aligned development outer folds.

    This deterministic builder is deliberately separate from Agent-facing research
    output. Non-selected candidate outer evidence is needed for family-level
    anti-overfitting statistics, but it must not become adaptive Agent feedback.
    """

    VERSION = "agent-family-development-evidence-v1"

    def __init__(
        self,
        *,
        registry: SQLiteResearchRegistry,
        adapter,
        config: AgentMarketResearchConfig | None = None,
    ) -> None:
        self.registry = registry
        self.adapter = adapter
        self.config = config or AgentMarketResearchConfig()

    def build(
        self,
        family_id: str,
        *,
        candidates: Sequence[GeneratedFeatureArtifact],
        universe: tuple[AssetId, ...],
        start,
        end,
        dataset_artifact: ArtifactRef,
    ) -> AgentFamilyDevelopmentEvidence:
        family = self.registry.get_family(family_id)
        if family.status is not ExperimentFamilyStatus.FROZEN:
            raise ValueError("Agent experiment family must be FROZEN before development validation")
        members = self.registry.family_members(family_id)
        experiment_order = tuple(member.experiment_id for member in members)
        if not experiment_order:
            raise ValueError("Agent experiment family has no registered members")

        by_digest = {artifact.digest: artifact for artifact in candidates}
        if len(by_digest) != len(tuple(candidates)):
            raise ValueError("candidate artifacts contain duplicate digests")
        artifacts_by_experiment: dict[str, GeneratedFeatureArtifact] = {}
        for experiment_id in experiment_order:
            spec = self.registry.get_experiment(experiment_id)
            digest = str(spec.metadata.get("generated_feature_digest", "")).strip()
            if not digest or digest not in by_digest:
                raise ValueError("candidate artifacts do not match formal ExperimentFamily membership")
            artifact = by_digest[digest]
            if spec.code.digest != artifact.code_artifact_ref().digest:
                raise ValueError("candidate code digest does not match formal ExperimentSpec")
            if spec.dataset != dataset_artifact:
                raise ValueError("development dataset does not match the formal primary ExperimentSpec")
            if tuple(spec.universe) != tuple(universe):
                raise ValueError("development universe does not match the formal ExperimentSpec")
            artifacts_by_experiment[experiment_id] = artifact
        if set(by_digest) != {artifact.digest for artifact in artifacts_by_experiment.values()}:
            raise ValueError("candidate artifacts contain members outside the frozen ExperimentFamily")

        evaluation_config = GeneratedFeatureEvaluationConfig(
            label_name=self.config.label_name,
            split_name="test",
            transaction_cost_bps=self.config.transaction_cost_bps,
            min_cross_section=self.config.min_cross_section,
            min_periods=self.config.min_periods,
        )
        splitter = self.config.market.splitter()
        returns: dict[str, tuple[float, ...]] = {}
        pvalues: dict[str, float] = {}
        canonical_timestamps: tuple[str, ...] | None = None

        for experiment_id in experiment_order:
            artifact = artifacts_by_experiment[experiment_id]
            study = GeneratedFeatureNestedWalkForwardStudy(
                adapter=self.adapter,
                splitter=splitter,
                config=evaluation_config,
            ).run(
                artifact,
                universe=universe,
                start=start,
                end=end,
                dataset_id_prefix=f"agent-family-validation-{family_id}-{artifact.spec.feature_id}",
            )
            timestamps = tuple(
                timestamp.isoformat()
                for fold in study.folds
                for timestamp in fold.outer_test.timestamps
            )
            values = tuple(
                float(value)
                for fold in study.folds
                for value in fold.outer_test.net_returns
            )
            if not timestamps or len(timestamps) != len(values):
                raise ValueError("candidate produced empty or misaligned development evidence")
            if len(set(timestamps)) != len(timestamps):
                raise ValueError(
                    "promotion-grade development folds overlap; duplicate timestamps are forbidden"
                )
            if canonical_timestamps is None:
                canonical_timestamps = timestamps
            elif timestamps != canonical_timestamps:
                raise ValueError("formal family candidates do not share identical development timestamps")
            returns[experiment_id] = values
            pvalues[experiment_id] = one_sided_mean_pvalue(values)

        assert canonical_timestamps is not None
        return AgentFamilyDevelopmentEvidence(
            family_id=family_id,
            experiment_order=experiment_order,
            timestamps=canonical_timestamps,
            trial_returns=returns,
            pvalues=pvalues,
            dataset_digest=dataset_artifact.digest,
        )


@dataclass(frozen=True, slots=True)
class AgentCandidateStatisticalValidation:
    experiment_id: str
    raw_pvalue: float
    adjusted_pvalue: float
    multiplicity_rejected: bool
    deflated_sharpe: DeflatedSharpeResult
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "raw_pvalue": self.raw_pvalue,
            "adjusted_pvalue": self.adjusted_pvalue,
            "multiplicity_rejected": self.multiplicity_rejected,
            "deflated_sharpe": {
                "observed_sharpe": self.deflated_sharpe.observed_sharpe,
                "benchmark_sharpe": self.deflated_sharpe.benchmark_sharpe,
                "deflated_probability": self.deflated_sharpe.deflated_probability,
                "sample_size": self.deflated_sharpe.sample_size,
                "n_trials": self.deflated_sharpe.n_trials,
                "skewness": self.deflated_sharpe.skewness,
                "kurtosis": self.deflated_sharpe.kurtosis,
            },
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class AgentFamilyStatisticalReport:
    family_id: str
    experiment_order: tuple[str, ...]
    observation_count: int
    dataset_digest: str
    multiple_testing: MultipleTestingResult
    pbo: PBOResult
    reality_check: RealityCheckResult
    candidates: tuple[AgentCandidateStatisticalValidation, ...]
    dsr_probability_threshold: float
    pbo_threshold: float
    validator_version: str = "formal-agent-family-validation-v1"

    @property
    def eligible_experiment_ids(self) -> tuple[str, ...]:
        return tuple(item.experiment_id for item in self.candidates if item.passed)

    @property
    def passed(self) -> bool:
        return bool(self.eligible_experiment_ids)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.agent-family-statistical-report.v1",
            "validator_version": self.validator_version,
            "family_id": self.family_id,
            "experiment_order": list(self.experiment_order),
            "observation_count": self.observation_count,
            "dataset_digest": self.dataset_digest,
            "multiple_testing": {
                "method": self.multiple_testing.method.value,
                "alpha": self.multiple_testing.alpha,
                "raw_pvalues": list(self.multiple_testing.raw_pvalues),
                "adjusted_pvalues": list(self.multiple_testing.adjusted_pvalues),
                "rejected": list(self.multiple_testing.rejected),
            },
            "pbo": {
                "probability_of_backtest_overfitting": self.pbo.probability_of_backtest_overfitting,
                "combinations_evaluated": self.pbo.combinations_evaluated,
                "blocks": self.pbo.blocks,
            },
            "reality_check": {
                "observed_statistic": self.reality_check.observed_statistic,
                "pvalue": self.reality_check.pvalue,
                "bootstrap_samples": self.reality_check.bootstrap_samples,
                "block_size": self.reality_check.block_size,
            },
            "candidates": [item.to_dict() for item in self.candidates],
            "eligible_experiment_ids": list(self.eligible_experiment_ids),
            "dsr_probability_threshold": self.dsr_probability_threshold,
            "pbo_threshold": self.pbo_threshold,
            "passed": self.passed,
        }

    @property
    def report_id(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        return f"agent-family-validation-{hashlib.sha256(encoded).hexdigest()[:20]}"


class FormalAgentExperimentFamilyValidator:
    """Compute promotion statistics without choosing a final strategy winner."""

    def __init__(self, registry: SQLiteResearchRegistry) -> None:
        self.registry = registry

    def validate(
        self,
        evidence: AgentFamilyDevelopmentEvidence,
        *,
        dsr_probability_threshold: float = 0.95,
        pbo_threshold: float = 0.5,
        pbo_blocks: int = 8,
        bootstrap_samples: int = 1000,
        bootstrap_block_size: int | None = None,
        seed: int = 0,
    ) -> AgentFamilyStatisticalReport:
        family = self.registry.get_family(evidence.family_id)
        if family.status is not ExperimentFamilyStatus.FROZEN:
            raise ValueError("experiment family must be FROZEN before statistical validation")
        members = self.registry.family_members(evidence.family_id)
        experiment_order = tuple(member.experiment_id for member in members)
        if evidence.experiment_order != experiment_order:
            raise ValueError("development evidence order does not match formal family membership")
        expected = set(experiment_order)
        if set(evidence.trial_returns) != expected or set(evidence.pvalues) != expected:
            raise ValueError("development evidence denominator does not match formal family membership")
        if not 0.0 < dsr_probability_threshold < 1.0:
            raise ValueError("dsr_probability_threshold must be in (0, 1)")
        if not 0.0 <= pbo_threshold <= 1.0:
            raise ValueError("pbo_threshold must be in [0, 1]")

        matrix = np.column_stack(
            [np.asarray(evidence.trial_returns[item], dtype=float) for item in experiment_order]
        )
        ordered_pvalues = tuple(float(evidence.pvalues[item]) for item in experiment_order)
        multiple = adjust_pvalues(
            ordered_pvalues,
            method=family.correction_method,
            alpha=family.alpha,
        )
        trial_sharpes = tuple(sharpe_ratio(matrix[:, index]) for index in range(matrix.shape[1]))
        pbo = probability_of_backtest_overfitting(matrix, blocks=pbo_blocks)
        reality = whites_reality_check(
            matrix,
            bootstrap_samples=bootstrap_samples,
            block_size=bootstrap_block_size,
            seed=seed,
        )
        common_pass = (
            pbo.probability_of_backtest_overfitting <= pbo_threshold
            and reality.pvalue <= family.alpha
        )
        candidate_reports: list[AgentCandidateStatisticalValidation] = []
        for index, experiment_id in enumerate(experiment_order):
            dsr = deflated_sharpe_ratio(
                matrix[:, index],
                n_trials=len(experiment_order),
                trial_sharpes=trial_sharpes,
            )
            passed = (
                multiple.rejected[index]
                and dsr.deflated_probability >= dsr_probability_threshold
                and common_pass
            )
            candidate_reports.append(
                AgentCandidateStatisticalValidation(
                    experiment_id=experiment_id,
                    raw_pvalue=multiple.raw_pvalues[index],
                    adjusted_pvalue=multiple.adjusted_pvalues[index],
                    multiplicity_rejected=multiple.rejected[index],
                    deflated_sharpe=dsr,
                    passed=passed,
                )
            )
        return AgentFamilyStatisticalReport(
            family_id=evidence.family_id,
            experiment_order=experiment_order,
            observation_count=len(evidence.timestamps),
            dataset_digest=evidence.dataset_digest,
            multiple_testing=multiple,
            pbo=pbo,
            reality_check=reality,
            candidates=tuple(candidate_reports),
            dsr_probability_threshold=float(dsr_probability_threshold),
            pbo_threshold=float(pbo_threshold),
        )


class SQLiteAgentFamilyValidationStore:
    """Append-only store for deterministic formal-family statistical reports."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_family_validation (
                    report_id TEXT PRIMARY KEY,
                    family_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def register(self, report: AgentFamilyStatisticalReport) -> None:
        encoded = json.dumps(
            report.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        with sqlite3.connect(self.path) as con:
            existing = con.execute(
                "SELECT family_id, payload_json FROM agent_family_validation WHERE report_id=?",
                (report.report_id,),
            ).fetchone()
            candidate = (report.family_id, encoded)
            if existing is not None:
                if tuple(existing) != candidate:
                    raise ValueError("formal family validation report identity is immutable")
                return
            con.execute(
                "INSERT INTO agent_family_validation VALUES (?, ?, ?)",
                (report.report_id, report.family_id, encoded),
            )

    def get(self, report_id: str) -> Mapping[str, object]:
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT payload_json FROM agent_family_validation WHERE report_id=?",
                (report_id,),
            ).fetchone()
        if row is None:
            raise KeyError(report_id)
        return MappingProxyType(json.loads(row[0]))

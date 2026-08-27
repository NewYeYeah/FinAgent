from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import numpy as np

from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.domain._validation import require_non_empty
from finagent.domain.research import DatasetRequest, ResearchSplit
from finagent.models.alpha.primitives import cross_sectional_zscore, winsorize_cross_section

from .ashare_universe import (
    AshareCandidateUniverseSelection,
    AshareResearchUniverseReport,
)
from .factor_feedback_v2 import factor_ensemble_selection_id
from .factor_quant import (
    FactorEnsembleSelection,
    FactorEnsembleSelector,
    FactorQuantAnalyzer,
    FactorQuantCandidateReport,
    FactorQuantFamilyReport,
)
from .factor_stability import (
    FactorCandidateStabilityReport,
    FactorFamilyStabilityReport,
    FactorStabilityAnalyzer,
    FactorStabilityConfig,
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
class AshareFrozenFactorComponent:
    feature_id: str
    feature_digest: str
    weight: float
    direction: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature_id", require_non_empty(self.feature_id, "feature_id"))
        object.__setattr__(
            self,
            "feature_digest",
            require_non_empty(self.feature_digest, "feature_digest"),
        )
        if not math.isfinite(self.weight) or self.weight < 0:
            raise ValueError("factor ensemble weight must be finite and non-negative")
        if self.direction not in {-1, 1}:
            raise ValueError("factor direction must be -1 or 1")

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "feature_digest": self.feature_digest,
            "weight": self.weight,
            "direction": self.direction,
        }


@dataclass(frozen=True, slots=True)
class AshareFrozenFactorEnsemble:
    development_report_id: str
    selection_id: str
    primary_label: str
    quality_metric: str
    components: tuple[AshareFrozenFactorComponent, ...]

    def __post_init__(self) -> None:
        for name in (
            "development_report_id",
            "selection_id",
            "primary_label",
            "quality_metric",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if not self.components:
            raise ValueError("frozen A-share factor ensemble requires components")
        if len({component.feature_digest for component in self.components}) != len(self.components):
            raise ValueError("frozen A-share factor ensemble contains duplicate components")
        if abs(sum(component.weight for component in self.components) - 1.0) > 1e-9:
            raise ValueError("frozen A-share factor ensemble weights must sum to one")

    @property
    def ensemble_id(self) -> str:
        digest = hashlib.sha256(_canonical_json(self.to_dict(include_id=False)).encode()).hexdigest()[:24]
        return f"ashare-frozen-factor-ensemble-{digest}"

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.ashare-frozen-factor-ensemble.v1",
            "development_report_id": self.development_report_id,
            "selection_id": self.selection_id,
            "primary_label": self.primary_label,
            "quality_metric": self.quality_metric,
            "components": [component.to_dict() for component in self.components],
        }
        if include_id:
            payload["ensemble_id"] = self.ensemble_id
        return payload

    @classmethod
    def from_development(
        cls,
        report: FactorQuantFamilyReport,
        selection: FactorEnsembleSelection,
    ) -> AshareFrozenFactorEnsemble:
        if selection.report_id != report.report_id:
            raise ValueError("factor selection does not belong to development report")
        components: list[AshareFrozenFactorComponent] = []
        for selected in selection.components:
            candidate = report.candidate(selected.feature_digest)
            directional_metric = candidate.primary.rank_ic
            if abs(directional_metric) <= 1e-15:
                directional_metric = candidate.primary.pearson_ic
            direction = 1 if directional_metric >= 0 else -1
            components.append(
                AshareFrozenFactorComponent(
                    feature_id=selected.feature_id,
                    feature_digest=selected.feature_digest,
                    weight=selected.weight,
                    direction=direction,
                )
            )
        return cls(
            development_report_id=report.report_id,
            selection_id=factor_ensemble_selection_id(selection),
            primary_label=report.primary_label,
            quality_metric=selection.quality_metric,
            components=tuple(components),
        )


@dataclass(frozen=True, slots=True)
class AshareFactorValidationComparison:
    best_single_feature_digest: str
    best_single_direction: int
    best_single_raw_rank_icir: float
    best_single_rank_icir: float
    ensemble_rank_icir: float
    ensemble_minus_best_single_rank_icir: float
    absolute_rank_icir_magnitude_delta: float
    best_single_raw_long_short_sharpe: float
    best_single_long_short_sharpe: float
    ensemble_long_short_sharpe: float
    ensemble_minus_best_single_long_short_sharpe: float
    absolute_long_short_sharpe_magnitude_delta: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "best_single_feature_digest",
            require_non_empty(self.best_single_feature_digest, "best_single_feature_digest"),
        )
        if self.best_single_direction not in {-1, 1}:
            raise ValueError("best_single_direction must be -1 or 1")
        values = (
            self.best_single_raw_rank_icir,
            self.best_single_rank_icir,
            self.ensemble_rank_icir,
            self.ensemble_minus_best_single_rank_icir,
            self.absolute_rank_icir_magnitude_delta,
            self.best_single_raw_long_short_sharpe,
            self.best_single_long_short_sharpe,
            self.ensemble_long_short_sharpe,
            self.ensemble_minus_best_single_long_short_sharpe,
            self.absolute_long_short_sharpe_magnitude_delta,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("validation comparison metrics must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "best_single_feature_digest": self.best_single_feature_digest,
            "best_single_direction": self.best_single_direction,
            "best_single_raw_rank_icir": self.best_single_raw_rank_icir,
            "best_single_rank_icir": self.best_single_rank_icir,
            "ensemble_rank_icir": self.ensemble_rank_icir,
            "ensemble_minus_best_single_rank_icir": self.ensemble_minus_best_single_rank_icir,
            "absolute_rank_icir_magnitude_delta": self.absolute_rank_icir_magnitude_delta,
            "best_single_raw_long_short_sharpe": self.best_single_raw_long_short_sharpe,
            "best_single_long_short_sharpe": self.best_single_long_short_sharpe,
            "ensemble_long_short_sharpe": self.ensemble_long_short_sharpe,
            "ensemble_minus_best_single_long_short_sharpe": self.ensemble_minus_best_single_long_short_sharpe,
            "absolute_long_short_sharpe_magnitude_delta": self.absolute_long_short_sharpe_magnitude_delta,
            "comparison_semantics": "development-frozen direction; signed deltas",
        }


@dataclass(frozen=True, slots=True)
class AshareResearchVerdictPolicy:
    min_validation_rank_icir: float = 0.0
    min_validation_long_short_sharpe: float = 0.0
    max_hac_pvalue: float = 0.05
    max_bootstrap_pvalue: float = 0.05

    def __post_init__(self) -> None:
        values = (
            self.min_validation_rank_icir,
            self.min_validation_long_short_sharpe,
            self.max_hac_pvalue,
            self.max_bootstrap_pvalue,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("research verdict policy must be finite")
        if not 0.0 <= self.max_hac_pvalue <= 1.0:
            raise ValueError("max_hac_pvalue must be in [0, 1]")
        if not 0.0 <= self.max_bootstrap_pvalue <= 1.0:
            raise ValueError("max_bootstrap_pvalue must be in [0, 1]")

    def to_dict(self) -> dict[str, object]:
        return {
            "min_validation_rank_icir": self.min_validation_rank_icir,
            "min_validation_long_short_sharpe": self.min_validation_long_short_sharpe,
            "max_hac_pvalue": self.max_hac_pvalue,
            "max_bootstrap_pvalue": self.max_bootstrap_pvalue,
        }


@dataclass(frozen=True, slots=True)
class AshareResearchOutcome:
    status: str
    ensemble_validation_passed: bool
    promotion_eligible: bool
    reason_codes: tuple[str, ...]
    policy: AshareResearchVerdictPolicy

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", require_non_empty(self.status, "status"))
        if not self.reason_codes:
            raise ValueError("research outcome requires reason codes")
        object.__setattr__(
            self,
            "reason_codes",
            tuple(require_non_empty(value, "reason code") for value in self.reason_codes),
        )
        if self.promotion_eligible:
            raise ValueError("A2 cannot be promotion eligible before A-share execution certification")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "ensemble_validation_passed": self.ensemble_validation_passed,
            "promotion_eligible": self.promotion_eligible,
            "reason_codes": list(self.reason_codes),
            "policy": self.policy.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AshareFactorResearchAcceptanceResult:
    mode: str
    data_version: str
    candidate_universe: AshareCandidateUniverseSelection
    universe_policy: AshareResearchUniverseReport
    candidates: tuple[GeneratedFeatureArtifact, ...]
    development_report: FactorQuantFamilyReport
    frozen_ensemble: AshareFrozenFactorEnsemble
    validation_report: FactorQuantFamilyReport
    validation_ensemble: FactorQuantCandidateReport
    validation_comparison: AshareFactorValidationComparison
    development_stability: FactorFamilyStabilityReport
    validation_stability: FactorFamilyStabilityReport
    validation_ensemble_stability: FactorCandidateStabilityReport
    research_outcome: AshareResearchOutcome
    reserve_start: str
    reserve_end: str
    discovery: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"deterministic", "agent", "replay"}:
            raise ValueError("A-share factor research mode is invalid")
        object.__setattr__(self, "data_version", require_non_empty(self.data_version, "data_version"))
        if not self.candidates:
            raise ValueError("A-share factor research requires candidates")
        candidate_digests = {artifact.digest for artifact in self.candidates}
        if candidate_digests != {
            candidate.feature_digest for candidate in self.development_report.candidates
        }:
            raise ValueError("development report denominator differs from candidate set")
        if candidate_digests != {
            candidate.feature_digest for candidate in self.validation_report.candidates
        }:
            raise ValueError("validation report denominator differs from candidate set")
        if not set(component.feature_digest for component in self.frozen_ensemble.components).issubset(
            candidate_digests
        ):
            raise ValueError("frozen ensemble references a candidate outside the search denominator")
        if self.validation_ensemble.feature_digest != self.frozen_ensemble.ensemble_id:
            raise ValueError("validation ensemble identity differs from frozen ensemble")
        if {candidate.feature_digest for candidate in self.development_stability.candidates} != candidate_digests:
            raise ValueError("development stability denominator differs from candidates")
        if {candidate.feature_digest for candidate in self.validation_stability.candidates} != candidate_digests:
            raise ValueError("validation stability denominator differs from candidates")
        if self.validation_ensemble_stability.feature_digest != self.frozen_ensemble.ensemble_id:
            raise ValueError("ensemble stability identity differs from frozen ensemble")
        object.__setattr__(
            self,
            "discovery",
            MappingProxyType(dict(self.discovery)) if self.discovery is not None else None,
        )

    @property
    def acceptance_id(self) -> str:
        payload = self.to_dict(include_id=False, include_mode=False)
        digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:24]
        return f"ashare-factor-acceptance-{digest}"

    def to_dict(
        self,
        *,
        include_id: bool = True,
        include_mode: bool = True,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.ashare-factor-research-acceptance.v2",
            "scope": (
                "bounded historical daily factor research only; no A-share execution, "
                "promotion, sealed holdout, paper or realtime claim"
            ),
            # Backward-compatible system-completion alias. Research validity is
            # reported separately and can fail while the workflow succeeds.
            "passed": True,
            "system_acceptance": {"passed": True, "status": "PASS"},
            "research_outcome": self.research_outcome.to_dict(),
            "data_version": self.data_version,
            "candidate_universe": self.candidate_universe.to_dict(),
            "universe_policy": self.universe_policy.to_dict(),
            "candidate_denominator": [
                {
                    "feature_id": artifact.spec.feature_id,
                    "feature_digest": artifact.digest,
                    "hypothesis": artifact.spec.hypothesis,
                    "input_fields": list(artifact.spec.input_fields),
                    "lookback": artifact.spec.lookback,
                    "generator_id": artifact.generator_id,
                }
                for artifact in self.candidates
            ],
            "development_report": self.development_report.to_dict(),
            "frozen_ensemble": self.frozen_ensemble.to_dict(),
            "validation_report": self.validation_report.to_dict(),
            "validation_ensemble": self.validation_ensemble.to_dict(),
            "validation_comparison": self.validation_comparison.to_dict(),
            "development_stability": self.development_stability.to_dict(),
            "validation_stability": self.validation_stability.to_dict(),
            "validation_ensemble_stability": self.validation_ensemble_stability.to_dict(),
            "reserve": {
                "start": self.reserve_start,
                "end": self.reserve_end,
                "status": "untouched",
            },
            "discovery": dict(self.discovery) if self.discovery is not None else None,
        }
        if include_mode:
            payload["mode"] = self.mode
        if include_id:
            payload["acceptance_id"] = self.acceptance_id
        return payload

    def write_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path


class AshareFactorResearchAcceptanceEngine:
    """Factor-level A2 acceptance without A-share execution or promotion claims."""

    def __init__(
        self,
        *,
        development_analyzer: FactorQuantAnalyzer,
        validation_analyzer: FactorQuantAnalyzer,
        selector: FactorEnsembleSelector,
        stability_config: FactorStabilityConfig = FactorStabilityConfig(),
        verdict_policy: AshareResearchVerdictPolicy = AshareResearchVerdictPolicy(),
    ) -> None:
        if development_analyzer.config.split_name == validation_analyzer.config.split_name:
            raise ValueError("development and validation analyzers must use different splits")
        if development_analyzer.config.primary_label != validation_analyzer.config.primary_label:
            raise ValueError("development and validation primary labels must match")
        self.development_analyzer = development_analyzer
        self.validation_analyzer = validation_analyzer
        self.selector = selector
        self.development_stability_analyzer = FactorStabilityAnalyzer(
            development_analyzer, config=stability_config
        )
        self.validation_stability_analyzer = FactorStabilityAnalyzer(
            validation_analyzer, config=stability_config
        )
        self.verdict_policy = verdict_policy

    def _ensemble_panel(
        self,
        candidates: Sequence[GeneratedFeatureArtifact],
        frozen: AshareFrozenFactorEnsemble,
        request: DatasetRequest,
    ) -> ResearchSplit:
        by_digest = {artifact.digest: artifact for artifact in candidates}
        datasets = [
            self.validation_analyzer.materializer.materialize(
                by_digest[component.feature_digest], request
            )
            for component in frozen.components
        ]
        split_name = self.validation_analyzer.config.split_name
        panels = [dataset.get_split(split_name) for dataset in datasets]
        first = panels[0]
        for panel in panels[1:]:
            if (
                panel.timestamps != first.timestamps
                or panel.assets != first.assets
                or panel.label_names != first.label_names
            ):
                raise ValueError("selected factor panels do not share a validation denominator")
            if not np.array_equal(panel.label_values, first.label_values, equal_nan=True):
                raise ValueError("selected factor panels contain different validation labels")

        eligibility = np.array(first.eligibility_mask, dtype=bool, copy=True)
        for panel in panels[1:]:
            eligibility &= np.asarray(panel.eligibility_mask, dtype=bool)
        output = np.full((first.n_times, first.n_assets), np.nan, dtype=float)
        for row in range(first.n_times):
            row_mask = eligibility[row].copy()
            raw_rows = [panel.feature_values[row, :, 0] for panel in panels]
            for values in raw_rows:
                row_mask &= np.isfinite(values)
            if int(row_mask.sum()) < self.validation_analyzer.config.min_cross_section:
                continue
            combined = np.zeros(first.n_assets, dtype=float)
            for component, values in zip(frozen.components, raw_rows, strict=True):
                winsorized = winsorize_cross_section(
                    values,
                    lower_quantile=self.validation_analyzer.config.winsor_lower_quantile,
                    upper_quantile=self.validation_analyzer.config.winsor_upper_quantile,
                    eligible=row_mask,
                )
                standardized = cross_sectional_zscore(winsorized, eligible=row_mask)
                combined[row_mask] += (
                    component.weight * component.direction * standardized[row_mask]
                )
            output[row, row_mask] = combined[row_mask]
            eligibility[row] &= row_mask

        return ResearchSplit(
            timestamps=first.timestamps,
            assets=first.assets,
            feature_names=("generated:a2-frozen-ensemble",),
            label_names=first.label_names,
            feature_values=output[:, :, None],
            label_values=first.label_values,
            eligibility_mask=eligibility,
            metadata={
                **dict(first.metadata),
                "frozen_ensemble_id": frozen.ensemble_id,
                "ensemble_normalization": "cross_sectional_winsorized_zscore",
            },
        )

    def _ensemble_report(
        self,
        panel: ResearchSplit,
        frozen: AshareFrozenFactorEnsemble,
    ) -> FactorQuantCandidateReport:
        analyzer = self.validation_analyzer
        factor = panel.feature_values[:, :, 0]
        eligibility = np.asarray(panel.eligibility_mask, dtype=bool)
        eligible_cells = int(eligibility.sum())
        valid_cells = int((eligibility & np.isfinite(factor)).sum())
        horizons = {
            label_name: analyzer._horizon_diagnostics(
                factor,
                panel.label_panel(label_name),
                eligibility,
                label_name,
            )
            for label_name in analyzer.config.labels
        }
        quantiles = analyzer._quantile_diagnostics(
            factor,
            panel.label_panel(analyzer.config.primary_label),
            eligibility,
        )
        return FactorQuantCandidateReport(
            feature_id="a2-frozen-ensemble",
            feature_digest=frozen.ensemble_id,
            primary_label=analyzer.config.primary_label,
            horizon_diagnostics=horizons,
            quantile_diagnostics=quantiles,
            coverage=float(valid_cells / eligible_cells) if eligible_cells else 0.0,
        )

    @staticmethod
    def _development_direction(candidate: FactorQuantCandidateReport) -> int:
        metric = candidate.primary.rank_ic
        if abs(metric) <= 1e-15:
            metric = candidate.primary.pearson_ic
        return 1 if metric >= 0 else -1

    @classmethod
    def _comparison(
        cls,
        development: FactorQuantFamilyReport,
        validation: FactorQuantFamilyReport,
        ensemble: FactorQuantCandidateReport,
    ) -> AshareFactorValidationComparison:
        oriented: list[tuple[float, str, int, FactorQuantCandidateReport]] = []
        for candidate in validation.candidates:
            direction = cls._development_direction(development.candidate(candidate.feature_digest))
            oriented.append(
                (
                    direction * candidate.primary.rank_icir,
                    candidate.feature_digest,
                    direction,
                    candidate,
                )
            )
        best_oriented_rank_icir, _, direction, best = max(
            oriented,
            key=lambda value: (value[0], value[1]),
        )
        raw_best_rank_icir = best.primary.rank_icir
        raw_best_sharpe = best.quantile_diagnostics.long_short_sharpe
        oriented_best_sharpe = direction * raw_best_sharpe
        ensemble_rank_icir = ensemble.primary.rank_icir
        ensemble_sharpe = ensemble.quantile_diagnostics.long_short_sharpe
        return AshareFactorValidationComparison(
            best_single_feature_digest=best.feature_digest,
            best_single_direction=direction,
            best_single_raw_rank_icir=raw_best_rank_icir,
            best_single_rank_icir=best_oriented_rank_icir,
            ensemble_rank_icir=ensemble_rank_icir,
            ensemble_minus_best_single_rank_icir=ensemble_rank_icir - best_oriented_rank_icir,
            absolute_rank_icir_magnitude_delta=abs(ensemble_rank_icir) - abs(best_oriented_rank_icir),
            best_single_raw_long_short_sharpe=raw_best_sharpe,
            best_single_long_short_sharpe=oriented_best_sharpe,
            ensemble_long_short_sharpe=ensemble_sharpe,
            ensemble_minus_best_single_long_short_sharpe=ensemble_sharpe - oriented_best_sharpe,
            absolute_long_short_sharpe_magnitude_delta=abs(ensemble_sharpe) - abs(oriented_best_sharpe),
        )

    def _research_outcome(
        self,
        ensemble: FactorQuantCandidateReport,
        stability: FactorCandidateStabilityReport,
    ) -> AshareResearchOutcome:
        policy = self.verdict_policy
        reasons: list[str] = []
        if ensemble.primary.rank_icir <= policy.min_validation_rank_icir:
            reasons.append("ENSEMBLE_RANK_ICIR_BELOW_THRESHOLD")
        if ensemble.quantile_diagnostics.long_short_sharpe <= policy.min_validation_long_short_sharpe:
            reasons.append("ENSEMBLE_LONG_SHORT_SHARPE_BELOW_THRESHOLD")
        if stability.hac_pvalue > policy.max_hac_pvalue:
            reasons.append("ENSEMBLE_HAC_NOT_SIGNIFICANT")
        if stability.bootstrap_pvalue > policy.max_bootstrap_pvalue:
            reasons.append("ENSEMBLE_BLOCK_BOOTSTRAP_NOT_SIGNIFICANT")
        passed = not reasons
        reasons.append("A_SHARE_EXECUTION_NOT_CERTIFIED")
        return AshareResearchOutcome(
            status=("ENSEMBLE_VALIDATION_PASSED_UNCONFIRMED" if passed else "ENSEMBLE_VALIDATION_FAILED"),
            ensemble_validation_passed=passed,
            promotion_eligible=False,
            reason_codes=tuple(reasons),
            policy=policy,
        )

    def run(
        self,
        *,
        mode: str,
        candidates: Sequence[GeneratedFeatureArtifact],
        development_request: DatasetRequest,
        validation_request: DatasetRequest,
        candidate_universe: AshareCandidateUniverseSelection,
        universe_policy: AshareResearchUniverseReport,
        reserve_start: str,
        reserve_end: str,
        development_report: FactorQuantFamilyReport | None = None,
        selection: FactorEnsembleSelection | None = None,
        discovery: Mapping[str, object] | None = None,
    ) -> AshareFactorResearchAcceptanceResult:
        artifacts = tuple(candidates)
        if not artifacts or len({artifact.digest for artifact in artifacts}) != len(artifacts):
            raise ValueError("A-share factor acceptance requires unique candidates")
        if tuple(development_request.universe) != tuple(validation_request.universe):
            raise ValueError("development and validation universes must match")
        if self.development_analyzer.adapter.data_version != self.validation_analyzer.adapter.data_version:
            raise ValueError("development and validation data versions differ")

        if development_report is None:
            development_report = self.development_analyzer.analyze(
                artifacts,
                request=development_request,
            )
        if selection is None:
            selection = self.selector.select(development_report)
        candidate_digests = {artifact.digest for artifact in artifacts}
        if candidate_digests != {
            candidate.feature_digest for candidate in development_report.candidates
        }:
            raise ValueError("development Factor Quant denominator differs from candidates")
        frozen = AshareFrozenFactorEnsemble.from_development(
            development_report,
            selection,
        )
        development_stability = self.development_stability_analyzer.analyze(
            artifacts, request=development_request
        )
        validation_report = self.validation_analyzer.analyze(
            artifacts,
            request=validation_request,
        )
        validation_stability = self.validation_stability_analyzer.analyze(
            artifacts, request=validation_request
        )
        panel = self._ensemble_panel(artifacts, frozen, validation_request)
        ensemble = self._ensemble_report(panel, frozen)
        ensemble_stability = self.validation_stability_analyzer.analyze_panel(
            feature_id=ensemble.feature_id,
            feature_digest=ensemble.feature_digest,
            panel=panel,
        )
        comparison = self._comparison(development_report, validation_report, ensemble)
        research_outcome = self._research_outcome(ensemble, ensemble_stability)
        return AshareFactorResearchAcceptanceResult(
            mode=mode,
            data_version=self.development_analyzer.adapter.data_version,
            candidate_universe=candidate_universe,
            universe_policy=universe_policy,
            candidates=artifacts,
            development_report=development_report,
            frozen_ensemble=frozen,
            validation_report=validation_report,
            validation_ensemble=ensemble,
            validation_comparison=comparison,
            development_stability=development_stability,
            validation_stability=validation_stability,
            validation_ensemble_stability=ensemble_stability,
            research_outcome=research_outcome,
            reserve_start=reserve_start,
            reserve_end=reserve_end,
            discovery=discovery,
        )

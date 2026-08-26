from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np
from scipy.stats import rankdata

from finagent.agents.generated_features import GeneratedFeatureArtifact
from finagent.domain._validation import require_non_empty
from finagent.domain.research import DatasetRequest, ResearchDataset
from finagent.models.alpha.primitives import winsorize_cross_section

from .generated_feature_eval import GeneratedFeatureMaterializer


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _icir(values: Sequence[float]) -> float:
    array = np.asarray(tuple(values), dtype=float)
    if array.size < 2:
        return 0.0
    std = float(np.std(array, ddof=1))
    return float(np.mean(array) / std) if std > 1e-15 else 0.0


def _safe_correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if left.size < 2 or right.size != left.size:
        return None
    if float(np.std(left)) <= 1e-15 or float(np.std(right)) <= 1e-15:
        return None
    value = float(np.corrcoef(left, right)[0, 1])
    return value if math.isfinite(value) else None


@dataclass(frozen=True, slots=True)
class FactorQuantConfig:
    """Development-only quantitative factor diagnostics.

    ``primary_label`` drives quantile portfolio diagnostics. ``decay_labels`` are
    additional explicit forward-return labels used to measure IC decay.  The engine
    never infers a horizon from a label name; horizon semantics remain owned by the
    canonical dataset contract.
    """

    split_name: str = "development"
    primary_label: str = "forward_simple_return_1"
    decay_labels: tuple[str, ...] = ()
    quantiles: int = 5
    min_cross_section: int = 5
    min_periods: int = 10
    annualization: float = 252.0
    winsor_lower_quantile: float = 0.01
    winsor_upper_quantile: float = 0.99

    def __post_init__(self) -> None:
        object.__setattr__(self, "split_name", require_non_empty(self.split_name, "split_name"))
        object.__setattr__(
            self, "primary_label", require_non_empty(self.primary_label, "primary_label")
        )
        decay = tuple(require_non_empty(value, "decay label") for value in self.decay_labels)
        if len(set(decay)) != len(decay) or self.primary_label in decay:
            raise ValueError("decay_labels must be unique and exclude primary_label")
        object.__setattr__(self, "decay_labels", decay)
        if isinstance(self.quantiles, bool) or not isinstance(self.quantiles, int) or self.quantiles < 2:
            raise ValueError("quantiles must be an integer >= 2")
        if (
            isinstance(self.min_cross_section, bool)
            or not isinstance(self.min_cross_section, int)
            or self.min_cross_section < self.quantiles
        ):
            raise ValueError("min_cross_section must be an integer >= quantiles")
        if isinstance(self.min_periods, bool) or not isinstance(self.min_periods, int) or self.min_periods < 2:
            raise ValueError("min_periods must be an integer >= 2")
        if self.annualization <= 0:
            raise ValueError("annualization must be > 0")
        if not 0.0 <= self.winsor_lower_quantile < self.winsor_upper_quantile <= 1.0:
            raise ValueError("invalid winsorization quantiles")

    @property
    def labels(self) -> tuple[str, ...]:
        return (self.primary_label, *self.decay_labels)


@dataclass(frozen=True, slots=True)
class FactorHorizonDiagnostics:
    label_name: str
    pearson_ic: float
    pearson_icir: float
    rank_ic: float
    rank_icir: float
    periods: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "label_name", require_non_empty(self.label_name, "label_name"))
        if self.periods < 1:
            raise ValueError("horizon diagnostics require at least one period")
        numeric = (self.pearson_ic, self.pearson_icir, self.rank_ic, self.rank_icir)
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("horizon diagnostics must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "label_name": self.label_name,
            "pearson_ic": self.pearson_ic,
            "pearson_icir": self.pearson_icir,
            "rank_ic": self.rank_ic,
            "rank_icir": self.rank_icir,
            "periods": self.periods,
        }


@dataclass(frozen=True, slots=True)
class QuantilePortfolioDiagnostics:
    quantile_mean_returns: tuple[float, ...]
    long_short_mean_return: float
    long_short_sharpe: float
    mean_one_way_turnover: float
    periods: int

    def __post_init__(self) -> None:
        if len(self.quantile_mean_returns) < 2 or self.periods < 1:
            raise ValueError("quantile diagnostics require >=2 buckets and >=1 period")
        numeric = (
            *self.quantile_mean_returns,
            self.long_short_mean_return,
            self.long_short_sharpe,
            self.mean_one_way_turnover,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("quantile diagnostics must be finite")
        if self.mean_one_way_turnover < 0:
            raise ValueError("mean_one_way_turnover must be >= 0")

    def to_dict(self) -> dict[str, object]:
        return {
            "quantile_mean_returns": list(self.quantile_mean_returns),
            "long_short_mean_return": self.long_short_mean_return,
            "long_short_sharpe": self.long_short_sharpe,
            "mean_one_way_turnover": self.mean_one_way_turnover,
            "periods": self.periods,
        }


@dataclass(frozen=True, slots=True)
class FactorQuantCandidateReport:
    feature_id: str
    feature_digest: str
    primary_label: str
    horizon_diagnostics: Mapping[str, FactorHorizonDiagnostics]
    quantile_diagnostics: QuantilePortfolioDiagnostics
    coverage: float

    def __post_init__(self) -> None:
        for name in ("feature_id", "feature_digest", "primary_label"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        horizons = dict(self.horizon_diagnostics)
        if not horizons or self.primary_label not in horizons:
            raise ValueError("horizon diagnostics must include primary_label")
        if any(key != value.label_name for key, value in horizons.items()):
            raise ValueError("horizon diagnostic keys must match label names")
        if not 0.0 <= float(self.coverage) <= 1.0:
            raise ValueError("coverage must be in [0, 1]")
        object.__setattr__(self, "horizon_diagnostics", MappingProxyType(horizons))
        object.__setattr__(self, "coverage", float(self.coverage))

    @property
    def primary(self) -> FactorHorizonDiagnostics:
        return self.horizon_diagnostics[self.primary_label]

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "feature_digest": self.feature_digest,
            "primary_label": self.primary_label,
            "horizon_diagnostics": {
                key: value.to_dict() for key, value in self.horizon_diagnostics.items()
            },
            "quantile_diagnostics": self.quantile_diagnostics.to_dict(),
            "coverage": self.coverage,
        }


@dataclass(frozen=True, slots=True)
class FactorQuantFamilyReport:
    data_version: str
    split_name: str
    primary_label: str
    candidates: tuple[FactorQuantCandidateReport, ...]
    factor_value_correlations: Mapping[str, float]

    def __post_init__(self) -> None:
        for name in ("data_version", "split_name", "primary_label"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if not self.candidates:
            raise ValueError("factor quant family report requires candidates")
        digests = {candidate.feature_digest for candidate in self.candidates}
        if len(digests) != len(self.candidates):
            raise ValueError("factor quant family report contains duplicate candidates")
        correlations = {str(key): float(value) for key, value in self.factor_value_correlations.items()}
        if any(not math.isfinite(value) or not -1.0 <= value <= 1.0 for value in correlations.values()):
            raise ValueError("factor value correlations must be finite and in [-1, 1]")
        object.__setattr__(self, "factor_value_correlations", MappingProxyType(correlations))

    @property
    def report_id(self) -> str:
        encoded = _canonical_json(self.to_dict(include_id=False)).encode()
        return f"factor-quant-{hashlib.sha256(encoded).hexdigest()[:24]}"

    def candidate(self, digest: str) -> FactorQuantCandidateReport:
        for candidate in self.candidates:
            if candidate.feature_digest == digest:
                return candidate
        raise KeyError(digest)

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "finagent.factor-quant-report.v2",
            "data_version": self.data_version,
            "split_name": self.split_name,
            "primary_label": self.primary_label,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "factor_value_correlations": dict(self.factor_value_correlations),
            "scope": "development_only_factor_quant_diagnostics",
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


class FactorQuantAnalyzer:
    """Compute transparent factor diagnostics from materialized PIT factor panels."""

    VERSION = "factor-quant-v2"

    def __init__(
        self,
        adapter,
        *,
        config: FactorQuantConfig = FactorQuantConfig(),
        materializer: GeneratedFeatureMaterializer | None = None,
    ) -> None:
        self.adapter = adapter
        self.config = config
        self.materializer = materializer or GeneratedFeatureMaterializer(adapter)

    def _horizon_diagnostics(
        self,
        factor: np.ndarray,
        labels: np.ndarray,
        eligibility: np.ndarray,
        label_name: str,
    ) -> FactorHorizonDiagnostics:
        pearson_values: list[float] = []
        rank_values: list[float] = []
        for row in range(factor.shape[0]):
            formation = eligibility[row] & np.isfinite(factor[row])
            realized = formation & np.isfinite(labels[row])
            if int(realized.sum()) < self.config.min_cross_section:
                continue
            raw_factor = factor[row][realized]
            target = labels[row][realized]
            winsorized = winsorize_cross_section(
                raw_factor,
                lower_quantile=self.config.winsor_lower_quantile,
                upper_quantile=self.config.winsor_upper_quantile,
            )
            pearson = _safe_correlation(np.asarray(winsorized, dtype=float), target)
            ranks = _safe_correlation(rankdata(raw_factor, method="average"), rankdata(target, method="average"))
            if pearson is not None:
                pearson_values.append(pearson)
            if ranks is not None:
                rank_values.append(ranks)
        common_periods = min(len(pearson_values), len(rank_values))
        if common_periods < self.config.min_periods:
            raise ValueError(
                f"factor has only {common_periods} usable IC periods for {label_name!r}; "
                f"minimum is {self.config.min_periods}"
            )
        return FactorHorizonDiagnostics(
            label_name=label_name,
            pearson_ic=float(np.mean(pearson_values)),
            pearson_icir=_icir(pearson_values),
            rank_ic=float(np.mean(rank_values)),
            rank_icir=_icir(rank_values),
            periods=common_periods,
        )

    def _quantile_diagnostics(
        self,
        factor: np.ndarray,
        labels: np.ndarray,
        eligibility: np.ndarray,
    ) -> QuantilePortfolioDiagnostics:
        quantile_returns: list[list[float]] = [[] for _ in range(self.config.quantiles)]
        spreads: list[float] = []
        turnovers: list[float] = []
        previous_weights = np.zeros(factor.shape[1], dtype=float)

        for row in range(factor.shape[0]):
            formation = eligibility[row] & np.isfinite(factor[row])
            indices = np.flatnonzero(formation)
            if len(indices) < self.config.min_cross_section:
                continue
            ordered = indices[np.argsort(factor[row][indices], kind="mergesort")]
            buckets = np.array_split(ordered, self.config.quantiles)
            if any(len(bucket) == 0 for bucket in buckets):
                continue
            active = np.concatenate((buckets[0], buckets[-1]))
            if not np.all(np.isfinite(labels[row][active])):
                continue
            bucket_values: list[float] = []
            valid_all = True
            for bucket in buckets:
                realized = labels[row][bucket]
                if not np.all(np.isfinite(realized)):
                    valid_all = False
                    break
                bucket_values.append(float(np.mean(realized)))
            if not valid_all:
                continue
            for target, value in zip(quantile_returns, bucket_values):
                target.append(value)
            spread = bucket_values[-1] - bucket_values[0]
            spreads.append(spread)

            weights = np.zeros_like(previous_weights)
            weights[buckets[-1]] = 0.5 / len(buckets[-1])
            weights[buckets[0]] = -0.5 / len(buckets[0])
            turnovers.append(float(0.5 * np.abs(weights - previous_weights).sum()))
            previous_weights = weights

        if len(spreads) < self.config.min_periods:
            raise ValueError(
                f"factor has only {len(spreads)} usable quantile periods; "
                f"minimum is {self.config.min_periods}"
            )
        spread_array = np.asarray(spreads, dtype=float)
        spread_std = float(np.std(spread_array, ddof=1)) if len(spreads) > 1 else 0.0
        sharpe = (
            float(np.mean(spread_array) / spread_std * math.sqrt(self.config.annualization))
            if spread_std > 1e-15
            else 0.0
        )
        return QuantilePortfolioDiagnostics(
            quantile_mean_returns=tuple(float(np.mean(values)) for values in quantile_returns),
            long_short_mean_return=float(np.mean(spread_array)),
            long_short_sharpe=sharpe,
            mean_one_way_turnover=float(np.mean(turnovers)),
            periods=len(spreads),
        )

    def _candidate_report(
        self,
        artifact: GeneratedFeatureArtifact,
        dataset: ResearchDataset,
    ) -> FactorQuantCandidateReport:
        panel = dataset.get_split(self.config.split_name)
        factor = panel.feature_values[:, :, 0]
        eligibility = np.asarray(panel.eligibility_mask, dtype=bool)
        eligible_cells = int(eligibility.sum())
        valid_cells = int((eligibility & np.isfinite(factor)).sum())
        horizons = {
            label_name: self._horizon_diagnostics(
                factor,
                panel.label_panel(label_name),
                eligibility,
                label_name,
            )
            for label_name in self.config.labels
        }
        quantiles = self._quantile_diagnostics(
            factor,
            panel.label_panel(self.config.primary_label),
            eligibility,
        )
        return FactorQuantCandidateReport(
            feature_id=artifact.spec.feature_id,
            feature_digest=artifact.digest,
            primary_label=self.config.primary_label,
            horizon_diagnostics=horizons,
            quantile_diagnostics=quantiles,
            coverage=float(valid_cells / eligible_cells) if eligible_cells else 0.0,
        )

    @staticmethod
    def _factor_value_correlation(left: ResearchDataset, right: ResearchDataset, split_name: str, min_cross_section: int) -> float:
        left_panel = left.get_split(split_name)
        right_panel = right.get_split(split_name)
        if left_panel.timestamps != right_panel.timestamps or left_panel.assets != right_panel.assets:
            raise ValueError("factor panels are not aligned")
        left_values = left_panel.feature_values[:, :, 0]
        right_values = right_panel.feature_values[:, :, 0]
        correlations: list[float] = []
        for row in range(left_panel.n_times):
            mask = (
                left_panel.eligibility_at(row)
                & right_panel.eligibility_at(row)
                & np.isfinite(left_values[row])
                & np.isfinite(right_values[row])
            )
            if int(mask.sum()) < min_cross_section:
                continue
            value = _safe_correlation(
                rankdata(left_values[row][mask], method="average"),
                rankdata(right_values[row][mask], method="average"),
            )
            if value is not None:
                correlations.append(value)
        return float(np.mean(correlations)) if correlations else 0.0

    def analyze(
        self,
        candidates: Sequence[GeneratedFeatureArtifact],
        *,
        request: DatasetRequest,
    ) -> FactorQuantFamilyReport:
        artifacts = tuple(candidates)
        if not artifacts:
            raise ValueError("factor quant analysis requires candidates")
        if len({artifact.digest for artifact in artifacts}) != len(artifacts):
            raise ValueError("factor quant analysis received duplicate feature digests")
        if self.config.split_name not in request.splits:
            raise KeyError(f"request has no split {self.config.split_name!r}")
        missing_labels = set(self.config.labels) - set(request.labels)
        if missing_labels:
            raise KeyError(f"factor quant request missing labels: {sorted(missing_labels)}")

        datasets: dict[str, ResearchDataset] = {}
        reports: list[FactorQuantCandidateReport] = []
        for artifact in artifacts:
            dataset = self.materializer.materialize(artifact, request)
            datasets[artifact.digest] = dataset
            reports.append(self._candidate_report(artifact, dataset))

        correlations: dict[str, float] = {}
        ordered = sorted(datasets)
        for index, left_digest in enumerate(ordered):
            for right_digest in ordered[index + 1 :]:
                key = f"{left_digest}|{right_digest}"
                correlations[key] = self._factor_value_correlation(
                    datasets[left_digest],
                    datasets[right_digest],
                    self.config.split_name,
                    self.config.min_cross_section,
                )

        return FactorQuantFamilyReport(
            data_version=self.adapter.data_version,
            split_name=self.config.split_name,
            primary_label=self.config.primary_label,
            candidates=tuple(reports),
            factor_value_correlations=correlations,
        )


@dataclass(frozen=True, slots=True)
class FactorEnsembleSelectionConfig:
    max_factors: int = 3
    max_abs_factor_correlation: float = 0.85
    quality_metric: str = "rank_icir"
    min_abs_quality: float = 0.0
    quality_power: float = 1.0

    def __post_init__(self) -> None:
        if isinstance(self.max_factors, bool) or not isinstance(self.max_factors, int) or self.max_factors < 1:
            raise ValueError("max_factors must be an integer >= 1")
        if not 0.0 <= self.max_abs_factor_correlation <= 1.0:
            raise ValueError("max_abs_factor_correlation must be in [0, 1]")
        if self.quality_metric not in {"rank_ic", "rank_icir", "pearson_ic", "pearson_icir", "long_short_sharpe"}:
            raise ValueError("unsupported factor ensemble quality_metric")
        if self.min_abs_quality < 0 or self.quality_power <= 0:
            raise ValueError("invalid factor ensemble quality thresholds")


@dataclass(frozen=True, slots=True)
class FactorEnsembleComponentSelection:
    feature_id: str
    feature_digest: str
    quality_score: float
    weight: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature_id", require_non_empty(self.feature_id, "feature_id"))
        object.__setattr__(self, "feature_digest", require_non_empty(self.feature_digest, "feature_digest"))
        if not math.isfinite(self.quality_score) or self.quality_score < 0:
            raise ValueError("quality_score must be finite and >= 0")
        if not math.isfinite(self.weight) or self.weight < 0:
            raise ValueError("weight must be finite and >= 0")


@dataclass(frozen=True, slots=True)
class FactorEnsembleSelection:
    report_id: str
    primary_label: str
    quality_metric: str
    components: tuple[FactorEnsembleComponentSelection, ...]

    def __post_init__(self) -> None:
        for name in ("report_id", "primary_label", "quality_metric"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if not self.components:
            raise ValueError("factor ensemble selection requires components")
        if len({component.feature_digest for component in self.components}) != len(self.components):
            raise ValueError("factor ensemble selection contains duplicate components")
        total = sum(component.weight for component in self.components)
        if abs(total - 1.0) > 1e-9:
            raise ValueError("factor ensemble weights must sum to one")

    @property
    def feature_digests(self) -> tuple[str, ...]:
        return tuple(component.feature_digest for component in self.components)

    @property
    def weights(self) -> tuple[float, ...]:
        return tuple(component.weight for component in self.components)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.factor-ensemble-selection.v1",
            "report_id": self.report_id,
            "primary_label": self.primary_label,
            "quality_metric": self.quality_metric,
            "components": [
                {
                    "feature_id": component.feature_id,
                    "feature_digest": component.feature_digest,
                    "quality_score": component.quality_score,
                    "weight": component.weight,
                }
                for component in self.components
            ],
        }


class FactorEnsembleSelector:
    """Greedy deterministic quality/redundancy selector for generated factors."""

    def __init__(self, config: FactorEnsembleSelectionConfig = FactorEnsembleSelectionConfig()) -> None:
        self.config = config

    @staticmethod
    def _correlation(report: FactorQuantFamilyReport, left: str, right: str) -> float:
        if left == right:
            return 1.0
        key = "|".join(sorted((left, right)))
        return float(report.factor_value_correlations.get(key, 0.0))

    def _quality(self, candidate: FactorQuantCandidateReport) -> float:
        if self.config.quality_metric == "long_short_sharpe":
            value = candidate.quantile_diagnostics.long_short_sharpe
        else:
            value = float(getattr(candidate.primary, self.config.quality_metric))
        return abs(float(value))

    def select(self, report: FactorQuantFamilyReport) -> FactorEnsembleSelection:
        ranked = sorted(
            (
                (self._quality(candidate), candidate)
                for candidate in report.candidates
                if self._quality(candidate) >= self.config.min_abs_quality
            ),
            key=lambda item: (-item[0], item[1].feature_digest),
        )
        if not ranked:
            raise ValueError("no factor candidate satisfies ensemble quality threshold")

        selected: list[tuple[float, FactorQuantCandidateReport]] = []
        for quality, candidate in ranked:
            if len(selected) >= self.config.max_factors:
                break
            if any(
                abs(self._correlation(report, candidate.feature_digest, chosen.feature_digest))
                > self.config.max_abs_factor_correlation
                for _, chosen in selected
            ):
                continue
            selected.append((quality, candidate))
        if not selected:
            raise ValueError("factor redundancy filter removed every candidate")

        masses = np.asarray(
            [max(quality, 1e-12) ** self.config.quality_power for quality, _ in selected],
            dtype=float,
        )
        masses /= float(masses.sum())
        components = tuple(
            FactorEnsembleComponentSelection(
                feature_id=candidate.feature_id,
                feature_digest=candidate.feature_digest,
                quality_score=float(quality),
                weight=float(masses[index]),
            )
            for index, (quality, candidate) in enumerate(selected)
        )
        return FactorEnsembleSelection(
            report_id=report.report_id,
            primary_label=report.primary_label,
            quality_metric=self.config.quality_metric,
            components=components,
        )

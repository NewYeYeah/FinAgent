from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from finagent.agents.domain import AgentTask
from finagent.domain._validation import require_non_empty
from finagent.domain.research import DatasetRequest

from .agent_market import MarketFeatureCandidateGenerator
from .factor_quant import FactorEnsembleSelection, FactorQuantFamilyReport


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def factor_quant_development_data_id(
    request: DatasetRequest,
    data_version: str,
    split_name: str,
) -> str:
    if split_name not in request.splits:
        raise KeyError(f"request has no split {split_name!r}")
    split = request.splits[split_name]
    payload = {
        "data_version": require_non_empty(data_version, "data_version"),
        "universe": [asset.key for asset in request.universe],
        "features": list(request.features),
        "labels": list(request.labels),
        "split_name": split_name,
        "split": [split.start.isoformat(), split.end.isoformat()],
        "dataset_id": request.dataset_id,
    }
    digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:24]
    return f"factor-quant-dev-{digest}"


def factor_ensemble_selection_id(selection: FactorEnsembleSelection) -> str:
    digest = hashlib.sha256(_canonical_json(selection.to_dict()).encode()).hexdigest()[:24]
    return f"factor-ensemble-selection-{digest}"


def _monotonicity(values: Sequence[float]) -> tuple[float, str]:
    array = np.asarray(tuple(values), dtype=float)
    if array.size < 2 or not np.isfinite(array).all():
        raise ValueError("quantile means must contain at least two finite values")
    std = float(np.std(array))
    if std <= 1e-15:
        return 0.0, "flat"
    buckets = np.arange(array.size, dtype=float)
    value = float(np.corrcoef(buckets, array)[0, 1])
    if not math.isfinite(value):
        return 0.0, "flat"
    direction = "increasing" if value > 0 else "decreasing"
    return abs(value), direction


@dataclass(frozen=True, slots=True)
class FactorQuantFeedbackHorizon:
    label_name: str
    pearson_ic: float
    pearson_icir: float
    rank_ic: float
    rank_icir: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "label_name", require_non_empty(self.label_name, "label_name"))
        values = (self.pearson_ic, self.pearson_icir, self.rank_ic, self.rank_icir)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("factor quant feedback horizon metrics must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "label_name": self.label_name,
            "pearson_ic": self.pearson_ic,
            "pearson_icir": self.pearson_icir,
            "rank_ic": self.rank_ic,
            "rank_icir": self.rank_icir,
        }


@dataclass(frozen=True, slots=True)
class FactorQuantFeedbackCandidate:
    feature_id: str
    feature_digest: str
    horizons: tuple[FactorQuantFeedbackHorizon, ...]
    quantile_mean_returns: tuple[float, ...]
    quantile_monotonicity: float
    quantile_direction: str
    long_short_mean_return: float
    long_short_sharpe: float
    mean_one_way_turnover: float
    coverage: float
    max_abs_factor_correlation: float
    most_correlated_feature_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "feature_id", require_non_empty(self.feature_id, "feature_id"))
        object.__setattr__(
            self,
            "feature_digest",
            require_non_empty(self.feature_digest, "feature_digest"),
        )
        if not self.horizons:
            raise ValueError("factor quant feedback candidate requires horizon diagnostics")
        if len({item.label_name for item in self.horizons}) != len(self.horizons):
            raise ValueError("factor quant feedback horizons must be unique")
        if len(self.quantile_mean_returns) < 2:
            raise ValueError("factor quant feedback requires at least two quantile returns")
        numeric = (
            *self.quantile_mean_returns,
            self.quantile_monotonicity,
            self.long_short_mean_return,
            self.long_short_sharpe,
            self.mean_one_way_turnover,
            self.coverage,
            self.max_abs_factor_correlation,
        )
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError("factor quant feedback metrics must be finite")
        if not 0.0 <= self.quantile_monotonicity <= 1.0:
            raise ValueError("quantile_monotonicity must be in [0, 1]")
        if self.quantile_direction not in {"increasing", "decreasing", "flat"}:
            raise ValueError("invalid quantile_direction")
        if self.mean_one_way_turnover < 0:
            raise ValueError("mean_one_way_turnover must be >= 0")
        if not 0.0 <= self.coverage <= 1.0:
            raise ValueError("coverage must be in [0, 1]")
        if not 0.0 <= self.max_abs_factor_correlation <= 1.0:
            raise ValueError("max_abs_factor_correlation must be in [0, 1]")
        object.__setattr__(
            self,
            "most_correlated_feature_digest",
            self.most_correlated_feature_digest.strip(),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id,
            "feature_digest": self.feature_digest,
            "horizons": [item.to_dict() for item in self.horizons],
            "quantile_mean_returns": list(self.quantile_mean_returns),
            "quantile_monotonicity": self.quantile_monotonicity,
            "quantile_direction": self.quantile_direction,
            "long_short_mean_return": self.long_short_mean_return,
            "long_short_sharpe": self.long_short_sharpe,
            "mean_one_way_turnover": self.mean_one_way_turnover,
            "coverage": self.coverage,
            "max_abs_factor_correlation": self.max_abs_factor_correlation,
            "most_correlated_feature_digest": self.most_correlated_feature_digest,
        }


@dataclass(frozen=True, slots=True)
class FactorQuantAgentFeedbackV2:
    report_id: str
    development_data_id: str
    primary_label: str
    candidates: tuple[FactorQuantFeedbackCandidate, ...]
    selected_feature_digests: tuple[str, ...] = ()
    selected_weights: tuple[float, ...] = ()
    selection_quality_metric: str = ""
    selection_id: str = ""

    def __post_init__(self) -> None:
        for name in ("report_id", "development_data_id", "primary_label"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if not self.candidates:
            raise ValueError("factor quant feedback requires candidates")
        candidate_digests = {item.feature_digest for item in self.candidates}
        if len(candidate_digests) != len(self.candidates):
            raise ValueError("factor quant feedback contains duplicate candidates")
        selected = tuple(self.selected_feature_digests)
        weights = tuple(float(value) for value in self.selected_weights)
        if bool(selected) != bool(weights):
            raise ValueError("selected_feature_digests and selected_weights must be supplied together")
        if selected:
            if len(selected) != len(weights) or len(set(selected)) != len(selected):
                raise ValueError("invalid selected factor denominator")
            if not set(selected).issubset(candidate_digests):
                raise ValueError("selected factor is absent from feedback candidates")
            if any(not math.isfinite(value) or value < 0 for value in weights):
                raise ValueError("selected weights must be finite and non-negative")
            if abs(sum(weights) - 1.0) > 1e-9:
                raise ValueError("selected weights must sum to one")
            object.__setattr__(
                self,
                "selection_quality_metric",
                require_non_empty(self.selection_quality_metric, "selection_quality_metric"),
            )
            object.__setattr__(self, "selection_id", require_non_empty(self.selection_id, "selection_id"))
        else:
            object.__setattr__(self, "selection_quality_metric", "")
            object.__setattr__(self, "selection_id", "")
        object.__setattr__(self, "selected_feature_digests", selected)
        object.__setattr__(self, "selected_weights", weights)

    @property
    def feedback_id(self) -> str:
        digest = hashlib.sha256(self.to_json().encode()).hexdigest()[:24]
        return f"factor-quant-feedback-v2-{digest}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.factor-quant-agent-feedback.v2",
            "report_id": self.report_id,
            "development_data_id": self.development_data_id,
            "primary_label": self.primary_label,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "ensemble_selection": {
                "selection_id": self.selection_id,
                "quality_metric": self.selection_quality_metric,
                "feature_digests": list(self.selected_feature_digests),
                "weights": list(self.selected_weights),
            }
            if self.selected_feature_digests
            else None,
            "scope": (
                "development_only_factor_quant_evidence; excludes outer-test, sealed holdout, "
                "promotion, paper and live evidence"
            ),
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_report(
        cls,
        report: FactorQuantFamilyReport,
        *,
        request: DatasetRequest,
        selection: FactorEnsembleSelection | None = None,
    ) -> FactorQuantAgentFeedbackV2:
        if report.split_name not in request.splits:
            raise KeyError(f"development request has no split {report.split_name!r}")
        if report.primary_label not in request.labels:
            raise ValueError("factor quant report label is absent from development request")
        development_data_id = factor_quant_development_data_id(
            request,
            report.data_version,
            report.split_name,
        )

        def correlation_summary(feature_digest: str) -> tuple[float, str]:
            best_abs = 0.0
            best_digest = ""
            for key, value in report.factor_value_correlations.items():
                left, right = key.split("|", 1)
                if feature_digest not in {left, right}:
                    continue
                peer = right if left == feature_digest else left
                absolute = abs(float(value))
                if absolute > best_abs or (
                    math.isclose(absolute, best_abs) and peer < best_digest
                ):
                    best_abs = absolute
                    best_digest = peer
            return best_abs, best_digest

        candidates: list[FactorQuantFeedbackCandidate] = []
        for candidate in report.candidates:
            quantile = candidate.quantile_diagnostics
            monotonicity, direction = _monotonicity(quantile.quantile_mean_returns)
            max_corr, peer = correlation_summary(candidate.feature_digest)
            candidates.append(
                FactorQuantFeedbackCandidate(
                    feature_id=candidate.feature_id,
                    feature_digest=candidate.feature_digest,
                    horizons=tuple(
                        FactorQuantFeedbackHorizon(
                            label_name=item.label_name,
                            pearson_ic=item.pearson_ic,
                            pearson_icir=item.pearson_icir,
                            rank_ic=item.rank_ic,
                            rank_icir=item.rank_icir,
                        )
                        for item in candidate.horizon_diagnostics.values()
                    ),
                    quantile_mean_returns=quantile.quantile_mean_returns,
                    quantile_monotonicity=monotonicity,
                    quantile_direction=direction,
                    long_short_mean_return=quantile.long_short_mean_return,
                    long_short_sharpe=quantile.long_short_sharpe,
                    mean_one_way_turnover=quantile.mean_one_way_turnover,
                    coverage=candidate.coverage,
                    max_abs_factor_correlation=max_corr,
                    most_correlated_feature_digest=peer,
                )
            )

        if selection is None:
            return cls(
                report_id=report.report_id,
                development_data_id=development_data_id,
                primary_label=report.primary_label,
                candidates=tuple(candidates),
            )
        if selection.report_id != report.report_id:
            raise ValueError("factor ensemble selection does not belong to factor quant report")
        return cls(
            report_id=report.report_id,
            development_data_id=development_data_id,
            primary_label=report.primary_label,
            candidates=tuple(candidates),
            selected_feature_digests=selection.feature_digests,
            selected_weights=selection.weights,
            selection_quality_metric=selection.quality_metric,
            selection_id=factor_ensemble_selection_id(selection),
        )


class FactorQuantFeedbackAwareMarketFeatureCandidateGenerator:
    """Inject only development Factor Quant v2 evidence into the next Agent round."""

    def __init__(self, base: MarketFeatureCandidateGenerator) -> None:
        self.base = base

    def generate(
        self,
        *,
        task: AgentTask,
        count: int,
        approved_input_fields: Sequence[str],
        smoke_inputs: Mapping[str, Sequence[int | float | None]],
        round_index: int,
        feedback: FactorQuantAgentFeedbackV2 | None = None,
    ):
        if round_index < 1:
            raise ValueError("round_index must be >= 1")
        objective = task.objective
        metadata = {**dict(task.metadata), "factor_quant_discovery_round": str(round_index)}
        if feedback is not None:
            objective = (
                f"{task.objective}\n\n"
                "DEVELOPMENT-ONLY FACTOR QUANT FEEDBACK V2:\n"
                f"{feedback.to_json()}\n\n"
                "Propose new economically interpretable factor hypotheses using only the "
                "approved PIT inputs. Prefer improvements in RankIC stability, explicit "
                "horizon persistence, quantile monotonicity and long-short spread while "
                "controlling turnover and coverage. Avoid factors highly correlated with "
                "existing candidates or trivial formula renamings. Do not infer or request "
                "outer-test, sealed-holdout, promotion, paper or live evidence."
            )
            metadata["factor_quant_feedback_id"] = feedback.feedback_id
            metadata["factor_quant_report_id"] = feedback.report_id
            if feedback.selection_id:
                metadata["factor_ensemble_selection_id"] = feedback.selection_id
        child = AgentTask(
            task_id=f"{task.task_id}:quant-discovery-round:{round_index:02d}",
            objective=objective,
            created_at=task.created_at,
            metadata=metadata,
        )
        return self.base.generate(
            task=child,
            count=count,
            approved_input_fields=approved_input_fields,
            smoke_inputs=smoke_inputs,
        )

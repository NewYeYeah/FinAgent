from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from finagent.research.us_baselines import (
    USBaselineCandidateDenominator,
    USBaselineFeatureSpec,
)

_CERTIFIED_OUTCOMES = frozenset(
    {
        "CERTIFIED_FOR_ENGINEERING_RESEARCH",
        "CERTIFIED_FOR_RESEARCH_UNDER_LIMITATIONS",
    }
)
_ALLOWED_LABEL_UNAVAILABLE = frozenset(
    {
        "target_crosses_session",
        "target_minute_missing",
    }
)


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _average_ranks(values: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted((float(value), asset) for asset, value in values.items())
    ranks: dict[str, float] = {}
    index = 0
    while index < len(ordered):
        end = index + 1
        value = ordered[index][0]
        while end < len(ordered) and ordered[end][0] == value:
            end += 1
        average_rank = ((index + 1) + end) / 2.0
        for _value, asset in ordered[index:end]:
            ranks[asset] = average_rank
        index = end
    return ranks


def _correlation(left: Mapping[str, float], right: Mapping[str, float]) -> float | None:
    common = sorted(set(left).intersection(right))
    if len(common) < 2:
        return None
    x = [left[item] for item in common]
    y = [right[item] for item in common]
    x_mean = sum(x) / len(x)
    y_mean = sum(y) / len(y)
    x_var = sum((value - x_mean) ** 2 for value in x)
    y_var = sum((value - y_mean) ** 2 for value in y)
    if x_var <= 1e-30 or y_var <= 1e-30:
        return None
    covariance = sum(
        (left_value - x_mean) * (right_value - y_mean)
        for left_value, right_value in zip(x, y, strict=True)
    )
    return covariance / math.sqrt(x_var * y_var)


def _rank_weights(feature_values: Mapping[str, float]) -> dict[str, float]:
    ranks = _average_ranks(feature_values)
    if len(ranks) < 2:
        return {asset: 0.0 for asset in ranks}
    mean_rank = sum(ranks.values()) / len(ranks)
    centered = {asset: rank - mean_rank for asset, rank in ranks.items()}
    gross = sum(abs(value) for value in centered.values())
    if gross <= 1e-30:
        return {asset: 0.0 for asset in ranks}
    return {asset: value / gross for asset, value in centered.items()}


def _turnover(previous: Mapping[str, float], current: Mapping[str, float]) -> tuple[float, float]:
    assets = set(previous).union(current)
    gross_traded = sum(
        abs(current.get(asset, 0.0) - previous.get(asset, 0.0)) for asset in assets
    )
    return 0.5 * gross_traded, gross_traded


@dataclass(frozen=True, slots=True)
class USBaselineRunSpec:
    certification_report_id: str
    certification_outcome: str
    engineering_universe_id: str
    denominator_id: str
    label_name: str = "us_same_session_60m_simple_return_raw"
    signal_interval: str = "15m"
    minimum_cross_section: int = 10
    minimum_evaluated_periods: int = 20
    minimum_ic_periods: int = 20
    fail_on_partial_realized_label: bool = True
    schema_version: str = "finagent.us-baseline-run-spec.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "certification_report_id",
            "certification_outcome",
            "engineering_universe_id",
            "denominator_id",
            "label_name",
            "signal_interval",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.certification_outcome not in _CERTIFIED_OUTCOMES:
            raise ValueError("US-B0 requires an accepted US-D3 certification outcome")
        if self.signal_interval != "15m":
            raise ValueError("US-B0 v1 formal evaluation uses the canonical 15m signal clock")
        if self.label_name != "us_same_session_60m_simple_return_raw":
            raise ValueError("US-B0 v1 requires the frozen same-session 60m RAW label")
        if self.minimum_cross_section < 2:
            raise ValueError("minimum_cross_section must be >= 2")
        if self.minimum_evaluated_periods < 1 or self.minimum_ic_periods < 1:
            raise ValueError("minimum evaluated/IC periods must be >= 1")
        # ``False`` is the bounded complete-case policy introduced after the first
        # real B0 run exposed one isolated missing target minute.  It omits the
        # entire formation cross-section; it never zero-fills, reweights, or uses
        # an alternate price source.

    @property
    def spec_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-baseline-run-spec")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "certification_report_id": self.certification_report_id,
            "certification_outcome": self.certification_outcome,
            "engineering_universe_id": self.engineering_universe_id,
            "denominator_id": self.denominator_id,
            "label_name": self.label_name,
            "signal_interval": self.signal_interval,
            "minimum_cross_section": self.minimum_cross_section,
            "minimum_evaluated_periods": self.minimum_evaluated_periods,
            "minimum_ic_periods": self.minimum_ic_periods,
            "fail_on_partial_realized_label": self.fail_on_partial_realized_label,
        }
        if include_id:
            payload["spec_id"] = self.spec_id
        return payload


@dataclass(frozen=True, slots=True)
class USBaselineObservation:
    feature_id: str
    feature_spec_id: str
    asset: str
    event_time: datetime
    feature_available_at: datetime
    eligible_at_formation: bool
    feature_value: float | None
    realized_label: float | None
    label_available_at: datetime | None
    label_unavailable_reason: str | None = None
    schema_version: str = "finagent.us-baseline-observation.v1"

    def __post_init__(self) -> None:
        for field_name in ("feature_id", "feature_spec_id", "asset"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        for field_name in ("event_time", "feature_available_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.feature_available_at <= self.event_time:
            raise ValueError("feature_available_at must be later than event_time")
        if self.feature_value is not None and not math.isfinite(self.feature_value):
            raise ValueError("feature_value must be finite when present")
        if self.realized_label is not None:
            if not math.isfinite(self.realized_label):
                raise ValueError("realized_label must be finite when present")
            if self.label_available_at is None:
                raise ValueError("realized_label requires label_available_at")
            if self.label_unavailable_reason is not None:
                raise ValueError("realized label cannot carry unavailable reason")
        else:
            if self.label_available_at is not None:
                raise ValueError("unavailable label cannot carry label_available_at")
            if self.label_unavailable_reason not in _ALLOWED_LABEL_UNAVAILABLE:
                raise ValueError("unavailable label requires a frozen D2 unavailable reason")
        if self.label_available_at is not None:
            if self.label_available_at.tzinfo is None or self.label_available_at.utcoffset() is None:
                raise ValueError("label_available_at must be timezone-aware")
            if self.label_available_at <= self.feature_available_at:
                raise ValueError("realized forward label must mature after feature formation")


@dataclass(frozen=True, slots=True)
class USBaselineCandidateEvidence:
    feature_id: str
    feature_spec_id: str
    run_spec_id: str
    observation_count: int
    eligible_cell_count: int
    valid_feature_cell_count: int
    evaluated_periods: int
    ic_periods: int
    boundary_unrealized_periods: int
    mean_rank_ic: float | None
    mean_gross_return: float | None
    mean_one_way_turnover: float | None
    mean_gross_traded_weight: float | None
    feature_coverage: float
    blockers: tuple[str, ...]
    partial_realized_label_omitted_periods: int = 0
    schema_version: str = "finagent.us-baseline-candidate-evidence.v1"

    def __post_init__(self) -> None:
        if self.partial_realized_label_omitted_periods < 0:
            raise ValueError("partial_realized_label_omitted_periods must be >= 0")

    @property
    def valid(self) -> bool:
        return not self.blockers

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-baseline-candidate-evidence",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "feature_id": self.feature_id,
            "feature_spec_id": self.feature_spec_id,
            "run_spec_id": self.run_spec_id,
            "observation_count": self.observation_count,
            "eligible_cell_count": self.eligible_cell_count,
            "valid_feature_cell_count": self.valid_feature_cell_count,
            "evaluated_periods": self.evaluated_periods,
            "ic_periods": self.ic_periods,
            "boundary_unrealized_periods": self.boundary_unrealized_periods,
            "mean_rank_ic": self.mean_rank_ic,
            "mean_gross_return": self.mean_gross_return,
            "mean_one_way_turnover": self.mean_one_way_turnover,
            "mean_gross_traded_weight": self.mean_gross_traded_weight,
            "feature_coverage": self.feature_coverage,
            "valid": self.valid,
            "blockers": list(self.blockers),
        }
        if self.partial_realized_label_omitted_periods:
            payload["partial_realized_label_omitted_periods"] = (
                self.partial_realized_label_omitted_periods
            )
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


@dataclass(frozen=True, slots=True)
class USBaselineEvaluationReport:
    run_spec: USBaselineRunSpec
    denominator_id: str
    candidates: tuple[USBaselineCandidateEvidence, ...]
    schema_version: str = "finagent.us-baseline-evaluation-report.v1"

    def __post_init__(self) -> None:
        if self.denominator_id != self.run_spec.denominator_id:
            raise ValueError("evaluation report denominator/run-spec identity mismatch")
        if not self.candidates:
            raise ValueError("evaluation report requires candidate evidence")
        ids = tuple(item.feature_id for item in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("evaluation report cannot repeat feature_id values")

    @property
    def valid_candidate_count(self) -> int:
        return sum(item.valid for item in self.candidates)

    @property
    def blockers(self) -> tuple[str, ...]:
        values: list[str] = []
        for item in self.candidates:
            values.extend(
                f"candidate:{item.feature_id}:{blocker}" for blocker in item.blockers
            )
        return tuple(values)

    @property
    def report_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-baseline-evaluation",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "run_spec": self.run_spec.to_dict(),
            "denominator_id": self.denominator_id,
            "candidate_count": len(self.candidates),
            "valid_candidate_count": self.valid_candidate_count,
            "blockers": list(self.blockers),
            "candidates": [item.to_dict() for item in self.candidates],
            "scope": "cost_free_diagnostic_pre_agent_baseline_evidence",
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


def _validate_observation_order(rows: Sequence[USBaselineObservation]) -> None:
    by_asset: dict[str, list[USBaselineObservation]] = defaultdict(list)
    for row in rows:
        by_asset[row.asset].append(row)
    for asset, asset_rows in by_asset.items():
        ordered = sorted(asset_rows, key=lambda item: item.feature_available_at)
        for left, right in pairwise(ordered):
            if right.feature_available_at <= left.feature_available_at:
                raise ValueError(
                    f"duplicate/non-increasing formation time for asset {asset!r}"
                )


def evaluate_us_baseline_candidate(
    spec: USBaselineFeatureSpec,
    observations: Sequence[USBaselineObservation],
    *,
    run_spec: USBaselineRunSpec,
) -> USBaselineCandidateEvidence:
    rows = tuple(observations)
    if any(
        row.feature_id != spec.feature_id or row.feature_spec_id != spec.spec_id
        for row in rows
    ):
        raise ValueError("observation feature identity mismatch")
    _validate_observation_order(rows)
    ordered = sorted(rows, key=lambda item: (item.feature_available_at, item.asset))
    groups: dict[datetime, list[USBaselineObservation]] = defaultdict(list)
    for row in ordered:
        groups[row.feature_available_at].append(row)

    eligible_cells = sum(row.eligible_at_formation for row in rows)
    valid_feature_cells = sum(
        row.eligible_at_formation and row.feature_value is not None for row in rows
    )
    blockers: list[str] = []
    rank_ics: list[float] = []
    gross_returns: list[float] = []
    turnovers: list[float] = []
    gross_traded_weights: list[float] = []
    boundary_periods = 0
    partial_label_omitted_periods = 0
    previous_weights: dict[str, float] = {}

    for formation_at in sorted(groups):
        period_rows = groups[formation_at]
        formation = {
            row.asset: float(row.feature_value)
            for row in period_rows
            if row.eligible_at_formation and row.feature_value is not None
        }
        if len(formation) < run_spec.minimum_cross_section:
            continue
        realized_by_asset = {
            row.asset: float(row.realized_label)
            for row in period_rows
            if row.asset in formation and row.realized_label is not None
        }
        missing_rows = [
            row for row in period_rows if row.asset in formation and row.realized_label is None
        ]
        if missing_rows and len(missing_rows) == len(formation) and all(
            row.label_unavailable_reason == "target_crosses_session" for row in missing_rows
        ):
            boundary_periods += 1
            continue
        if missing_rows:
            if run_spec.fail_on_partial_realized_label:
                blockers.append(f"partial_realized_label_missing:{formation_at.isoformat()}")
            else:
                partial_label_omitted_periods += 1
            continue

        weights = _rank_weights(formation)
        if not any(abs(value) > 1e-15 for value in weights.values()):
            continue
        feature_ranks = _average_ranks(formation)
        label_ranks = _average_ranks(realized_by_asset)
        rank_ic = _correlation(feature_ranks, label_ranks)
        if rank_ic is not None:
            rank_ics.append(rank_ic)
        gross_returns.append(
            sum(weights[asset] * realized_by_asset[asset] for asset in weights)
        )
        one_way, gross_traded = _turnover(previous_weights, weights)
        turnovers.append(one_way)
        gross_traded_weights.append(gross_traded)
        previous_weights = weights

    if len(gross_returns) < run_spec.minimum_evaluated_periods:
        blockers.append(
            "insufficient_evaluated_periods:"
            f"{len(gross_returns)}<{run_spec.minimum_evaluated_periods}"
        )
    if len(rank_ics) < run_spec.minimum_ic_periods:
        blockers.append(
            f"insufficient_ic_periods:{len(rank_ics)}<{run_spec.minimum_ic_periods}"
        )

    coverage = valid_feature_cells / eligible_cells if eligible_cells else 0.0
    return USBaselineCandidateEvidence(
        feature_id=spec.feature_id,
        feature_spec_id=spec.spec_id,
        run_spec_id=run_spec.spec_id,
        observation_count=len(rows),
        eligible_cell_count=eligible_cells,
        valid_feature_cell_count=valid_feature_cells,
        evaluated_periods=len(gross_returns),
        ic_periods=len(rank_ics),
        boundary_unrealized_periods=boundary_periods,
        mean_rank_ic=_mean(rank_ics),
        mean_gross_return=_mean(gross_returns),
        mean_one_way_turnover=_mean(turnovers),
        mean_gross_traded_weight=_mean(gross_traded_weights),
        feature_coverage=coverage,
        blockers=tuple(dict.fromkeys(blockers)),
        partial_realized_label_omitted_periods=partial_label_omitted_periods,
    )


def evaluate_us_baseline_denominator(
    denominator: USBaselineCandidateDenominator,
    observations_by_feature: Mapping[str, Sequence[USBaselineObservation]],
    *,
    run_spec: USBaselineRunSpec,
) -> USBaselineEvaluationReport:
    if run_spec.denominator_id != denominator.denominator_id:
        raise ValueError("run spec does not bind the supplied candidate denominator")
    expected_ids = tuple(item.feature_id for item in denominator.candidates)
    unexpected = sorted(set(observations_by_feature).difference(expected_ids))
    if unexpected:
        raise ValueError(f"observations contain feature ids outside denominator: {unexpected}")
    evidence = tuple(
        evaluate_us_baseline_candidate(
            candidate,
            observations_by_feature.get(candidate.feature_id, ()),
            run_spec=run_spec,
        )
        for candidate in denominator.candidates
    )
    return USBaselineEvaluationReport(
        run_spec=run_spec,
        denominator_id=denominator.denominator_id,
        candidates=evidence,
    )

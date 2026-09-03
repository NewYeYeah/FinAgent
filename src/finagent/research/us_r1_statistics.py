from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from finagent.domain.market_bars import BarInterval
from finagent.research.us_r1_evaluation_policy import USR1StatisticalEvaluationPolicy
from finagent.research.us_r1_inference import USR1FoldSeries, USR1PeriodMetricPoint
from finagent.research.us_r1_materialization import (
    USR1CandidateObservation,
    USR1ObservationRole,
)
from finagent.research.us_r1_protocol import USR1CandidateDenominator


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _finite(value: float, field_name: str) -> float:
    rendered = float(value)
    if not math.isfinite(rendered):
        raise ValueError(f"{field_name} must be finite")
    return rendered


def _average_ranks(values: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted((float(value), asset) for asset, value in values.items())
    ranks: dict[str, float] = {}
    index = 0
    while index < len(ordered):
        end = index + 1
        value = ordered[index][0]
        while end < len(ordered) and ordered[end][0] == value:
            end += 1
        average = ((index + 1) + end) / 2.0
        for _value, asset in ordered[index:end]:
            ranks[asset] = average
        index = end
    return ranks


def _correlation(left: Mapping[str, float], right: Mapping[str, float]) -> float | None:
    common = sorted(set(left).intersection(right))
    if len(common) < 2:
        return None
    x = np.asarray([left[item] for item in common], dtype=float)
    y = np.asarray([right[item] for item in common], dtype=float)
    x_dev = x - float(np.mean(x))
    y_dev = y - float(np.mean(y))
    denominator = math.sqrt(float(np.dot(x_dev, x_dev) * np.dot(y_dev, y_dev)))
    if denominator <= 1e-30:
        return None
    return float(np.dot(x_dev, y_dev) / denominator)


def _spearman(feature: Mapping[str, float], labels: Mapping[str, float]) -> float | None:
    return _correlation(_average_ranks(feature), _average_ranks(labels))


def _quantile_portfolio(
    feature: Mapping[str, float],
    labels: Mapping[str, float],
    *,
    quantile_count: int,
) -> tuple[float, float, dict[str, float]]:
    ordered = sorted((float(value), asset) for asset, value in feature.items())
    count = len(ordered)
    buckets: list[list[str]] = [[] for _ in range(quantile_count)]
    for index, (_value, asset) in enumerate(ordered):
        bucket = min(quantile_count - 1, index * quantile_count // count)
        buckets[bucket].append(asset)
    if any(not bucket for bucket in buckets):
        raise ValueError("US-R1 quantile assignment produced an empty bucket")
    bucket_means = [float(np.mean([labels[asset] for asset in bucket])) for bucket in buckets]
    long_short_bps = 10_000.0 * (bucket_means[-1] - bucket_means[0])
    bucket_values = {str(index): value for index, value in enumerate(bucket_means)}
    bucket_order = {str(index): float(index) for index in range(quantile_count)}
    monotonicity = _correlation(bucket_order, _average_ranks(bucket_values))
    weights: dict[str, float] = {}
    for asset in buckets[-1]:
        weights[asset] = 1.0 / len(buckets[-1])
    for asset in buckets[0]:
        weights[asset] = -1.0 / len(buckets[0])
    return long_short_bps, 0.0 if monotonicity is None else monotonicity, weights


def _one_way_turnover(previous: Mapping[str, float], current: Mapping[str, float]) -> float:
    assets = sorted(set(previous).union(current))
    return 0.5 * math.fsum(
        abs(current.get(asset, 0.0) - previous.get(asset, 0.0)) for asset in assets
    )


@dataclass(frozen=True, slots=True)
class USR1CandidateSliceStatistics:
    candidate_id: str
    role: USR1ObservationRole
    signal_interval: BarInterval
    label_horizon_trading_minutes: int
    period_count: int
    boundary_unrealized_period_count: int
    insufficient_cross_section_period_count: int
    mean_raw_rank_ic: float | None
    blockers: tuple[str, ...]
    partial_label_omitted_period_count: int = 0
    schema_version: str = "finagent.us-r1-candidate-slice-statistics.v1"

    def __post_init__(self) -> None:
        if self.partial_label_omitted_period_count < 0:
            raise ValueError("partial_label_omitted_period_count must be non-negative")

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def statistics_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-r1-candidate-slice-statistics",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "role": self.role.value,
            "signal_interval": self.signal_interval.value,
            "label_horizon_trading_minutes": self.label_horizon_trading_minutes,
            "period_count": self.period_count,
            "boundary_unrealized_period_count": self.boundary_unrealized_period_count,
            "insufficient_cross_section_period_count": (
                self.insufficient_cross_section_period_count
            ),
            "mean_raw_rank_ic": self.mean_raw_rank_ic,
            "passed": self.passed,
            "blockers": list(self.blockers),
        }
        if self.partial_label_omitted_period_count:
            payload["partial_label_omitted_period_count"] = (
                self.partial_label_omitted_period_count
            )
        if include_id:
            payload["statistics_id"] = self.statistics_id
        return payload


@dataclass(frozen=True, slots=True)
class USR1PeriodMetricRecord:
    candidate_id: str
    fold_id: str
    fold_ordinal: int
    signal_interval: BarInterval
    label_horizon_trading_minutes: int
    point: USR1PeriodMetricPoint
    schema_version: str = "finagent.us-r1-period-metric-record.v1"

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.fold_id.strip():
            raise ValueError("US-R1 period metric candidate/fold IDs must be non-empty")
        if self.fold_ordinal not in {1, 2, 3}:
            raise ValueError("US-R1 period metric fold ordinal must be 1,2,3")
        if self.signal_interval not in {
            BarInterval.MINUTE_5,
            BarInterval.MINUTE_15,
            BarInterval.MINUTE_30,
        }:
            raise ValueError("US-R1 period metric interval must be 5m/15m/30m")
        if self.label_horizon_trading_minutes not in {30, 60, 120}:
            raise ValueError("US-R1 period metric horizon must be 30m/60m/120m")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "fold_id": self.fold_id,
            "fold_ordinal": self.fold_ordinal,
            "signal_interval": self.signal_interval.value,
            "label_horizon_trading_minutes": self.label_horizon_trading_minutes,
            "event_time": self.point.event_time.isoformat(),
            "session_id": self.point.session_id,
            "rank_ic": self.point.rank_ic,
            "long_short_return_bps": self.point.long_short_return_bps,
            "one_way_turnover": self.point.one_way_turnover,
            "coverage": self.point.coverage,
            "quantile_monotonicity": self.point.quantile_monotonicity,
        }


@dataclass(frozen=True, slots=True)
class USR1CandidateDirectionEvidence:
    candidate_id: str
    evaluation_policy_id: str
    source_fold_id: str
    source_fold_manifest_id: str
    train_statistics_id: str
    train_period_count: int
    train_mean_rank_ic: float
    direction: int
    schema_version: str = "finagent.us-r1-candidate-direction-evidence.v1"

    def __post_init__(self) -> None:
        if self.direction not in {-1, 1}:
            raise ValueError("US-R1 direction must be -1 or 1")
        if self.train_period_count < 1:
            raise ValueError("US-R1 direction requires training periods")
        _finite(self.train_mean_rank_ic, "train_mean_rank_ic")

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-r1-candidate-direction",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "evaluation_policy_id": self.evaluation_policy_id,
            "source_fold_id": self.source_fold_id,
            "source_fold_manifest_id": self.source_fold_manifest_id,
            "train_statistics_id": self.train_statistics_id,
            "train_period_count": self.train_period_count,
            "train_mean_rank_ic": self.train_mean_rank_ic,
            "direction": self.direction,
            "direction_source": "fold_01_train_15m_60m_only",
            "oos_metrics_used_for_direction": False,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


@dataclass(frozen=True, slots=True)
class USR1DirectionEvidenceSet:
    denominator_id: str
    evaluation_policy_id: str
    source_fold_id: str
    source_fold_manifest_id: str
    candidates: tuple[USR1CandidateDirectionEvidence, ...]
    schema_version: str = "finagent.us-r1-direction-evidence-set.v1"

    def __post_init__(self) -> None:
        if not self.candidates:
            raise ValueError("US-R1 direction evidence set requires candidates")
        ids = tuple(item.candidate_id for item in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("US-R1 direction evidence cannot repeat candidates")

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-direction-set")

    def direction(self, candidate_id: str) -> int:
        match = next((item for item in self.candidates if item.candidate_id == candidate_id), None)
        if match is None:
            raise ValueError("candidate is absent from US-R1 direction evidence")
        return match.direction

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "denominator_id": self.denominator_id,
            "evaluation_policy_id": self.evaluation_policy_id,
            "source_fold_id": self.source_fold_id,
            "source_fold_manifest_id": self.source_fold_manifest_id,
            "candidate_count": len(self.candidates),
            "candidate_ids": [item.candidate_id for item in self.candidates],
            "candidates": [item.to_dict() for item in self.candidates],
            "selection_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


@dataclass(frozen=True, slots=True)
class USR1PeriodMetricArtifact:
    fold_id: str
    fold_ordinal: int
    denominator_id: str
    evaluation_policy_id: str
    row_count: int
    content_sha256: str
    output_filename: str
    schema_version: str = "finagent.us-r1-period-metric-artifact.v1"

    def __post_init__(self) -> None:
        if self.fold_ordinal not in {1, 2, 3} or self.row_count < 0:
            raise ValueError("US-R1 period metric artifact fold/count is invalid")
        digest = self.content_sha256.strip().lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("US-R1 period metric artifact requires SHA-256 hex")
        object.__setattr__(self, "content_sha256", digest)

    @property
    def artifact_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "fold_id": self.fold_id,
                "fold_ordinal": self.fold_ordinal,
                "denominator_id": self.denominator_id,
                "evaluation_policy_id": self.evaluation_policy_id,
                "row_count": self.row_count,
                "content_sha256": self.content_sha256,
            },
            prefix="us-r1-period-metrics",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "fold_id": self.fold_id,
            "fold_ordinal": self.fold_ordinal,
            "denominator_id": self.denominator_id,
            "evaluation_policy_id": self.evaluation_policy_id,
            "row_count": self.row_count,
            "content_sha256": self.content_sha256,
            "output_filename": self.output_filename,
        }


@dataclass(frozen=True, slots=True)
class USR1FoldStatisticsReport:
    fold_id: str
    fold_ordinal: int
    fold_materialization_manifest_id: str
    denominator_id: str
    evaluation_policy_id: str
    period_metric_artifact_id: str
    candidate_slices: tuple[USR1CandidateSliceStatistics, ...]
    schema_version: str = "finagent.us-r1-fold-statistics-report.v1"

    def __post_init__(self) -> None:
        if self.fold_ordinal not in {1, 2, 3}:
            raise ValueError("US-R1 fold statistics ordinal must be 1,2,3")
        if not self.candidate_slices:
            raise ValueError("US-R1 fold statistics requires candidate slices")

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(
            f"candidate:{item.candidate_id}:{item.signal_interval.value}:"
            f"{item.label_horizon_trading_minutes}m:{blocker}"
            for item in self.candidate_slices
            for blocker in item.blockers
        )

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def report_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-fold-statistics")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "fold_id": self.fold_id,
            "fold_ordinal": self.fold_ordinal,
            "fold_materialization_manifest_id": self.fold_materialization_manifest_id,
            "denominator_id": self.denominator_id,
            "evaluation_policy_id": self.evaluation_policy_id,
            "period_metric_artifact_id": self.period_metric_artifact_id,
            "candidate_slice_count": len(self.candidate_slices),
            "candidate_slices": [item.to_dict() for item in self.candidate_slices],
            "passed": self.passed,
            "blockers": list(self.blockers),
            "alpha_authority": False,
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


def evaluate_us_r1_candidate_slice(
    observations: Sequence[USR1CandidateObservation],
    *,
    candidate_id: str,
    role: USR1ObservationRole,
    signal_interval: BarInterval,
    label_horizon_trading_minutes: int,
    policy: USR1StatisticalEvaluationPolicy,
    minimum_periods: int,
) -> tuple[USR1CandidateSliceStatistics, tuple[USR1PeriodMetricPoint, ...]]:
    # Label availability is invariant across candidates.  Determine partial
    # formations from the complete slice before selecting one candidate so the
    # same period is omitted from every candidate, including candidates whose
    # feature happens to be unavailable for the affected asset.
    all_groups: dict[datetime, list[USR1CandidateObservation]] = defaultdict(list)
    for observation in observations:
        all_groups[observation.feature_available_at].append(observation)
    partial_label_formations = {
        formation_at
        for formation_at, period_rows in all_groups.items()
        if any(
            row.realized_label is None
            and row.label_unavailable_reason != "target_crosses_session"
            for row in period_rows
        )
    }
    rows = tuple(row for row in observations if row.candidate_id == candidate_id)
    if any(
        row.role is not role
        or row.signal_interval is not signal_interval
        or row.label_horizon_trading_minutes != label_horizon_trading_minutes
        for row in rows
    ):
        raise ValueError("US-R1 candidate slice contains mixed role/frequency/horizon evidence")
    groups: dict[datetime, list[USR1CandidateObservation]] = defaultdict(list)
    for row in rows:
        groups[row.feature_available_at].append(row)
    points: list[USR1PeriodMetricPoint] = []
    blockers: list[str] = []
    boundary_count = 0
    partial_label_omitted_count = 0
    insufficient_count = 0
    previous_session: str | None = None
    previous_weights: dict[str, float] = {}

    for formation_at in sorted(groups):
        period_rows = groups[formation_at]
        if formation_at in partial_label_formations:
            partial_label_omitted_count += 1
            continue
        session_ids = {row.session_id for row in period_rows}
        if len(session_ids) != 1:
            blockers.append(f"mixed_session_id:{formation_at.isoformat()}")
            continue
        session_id = next(iter(session_ids))
        feature_rows = [row for row in period_rows if row.feature_value is not None]
        if not feature_rows:
            insufficient_count += 1
            continue
        missing_labels = [row for row in feature_rows if row.realized_label is None]
        if missing_labels:
            if len(missing_labels) == len(feature_rows) and all(
                row.label_unavailable_reason == "target_crosses_session" for row in missing_labels
            ):
                boundary_count += 1
                continue
            # The canonical complete-case policy should have classified every
            # non-boundary missing label above.  Retain this defensive blocker
            # for malformed/internally inconsistent observations.
            blockers.append(f"unclassified_missing_label:{formation_at.isoformat()}")
            continue
        valid_rows = feature_rows
        if len(valid_rows) < policy.minimum_cross_section:
            insufficient_count += 1
            continue
        feature: dict[str, float] = {}
        labels: dict[str, float] = {}
        for row in valid_rows:
            feature_value = row.feature_value
            realized_label = row.realized_label
            if feature_value is None or realized_label is None:
                raise RuntimeError("US-R1 validated metric row unexpectedly lacks a value")
            feature[row.asset] = float(feature_value)
            labels[row.asset] = float(realized_label)
        rank_ic = _spearman(feature, labels)
        if rank_ic is None:
            blockers.append(f"rank_ic_undefined:{formation_at.isoformat()}")
            continue
        long_short_bps, monotonicity, weights = _quantile_portfolio(
            feature,
            labels,
            quantile_count=policy.quantile_count,
        )
        if previous_session != session_id:
            previous_weights = {}
        turnover = _one_way_turnover(previous_weights, weights)
        previous_session = session_id
        previous_weights = weights
        label_eligible_count = sum(row.realized_label is not None for row in period_rows)
        coverage = (
            len(valid_rows) / label_eligible_count if label_eligible_count > 0 else 0.0
        )
        points.append(
            USR1PeriodMetricPoint(
                event_time=formation_at,
                session_id=session_id,
                rank_ic=rank_ic,
                long_short_return_bps=long_short_bps,
                one_way_turnover=turnover,
                coverage=coverage,
                quantile_monotonicity=monotonicity,
            )
        )

    if len(points) < minimum_periods:
        blockers.append(f"insufficient_metric_periods:{len(points)}<{minimum_periods}")
    statistics = USR1CandidateSliceStatistics(
        candidate_id=candidate_id,
        role=role,
        signal_interval=signal_interval,
        label_horizon_trading_minutes=label_horizon_trading_minutes,
        period_count=len(points),
        boundary_unrealized_period_count=boundary_count,
        insufficient_cross_section_period_count=insufficient_count,
        mean_raw_rank_ic=(
            None if not points else float(np.mean([point.rank_ic for point in points]))
        ),
        blockers=tuple(dict.fromkeys(blockers)),
        partial_label_omitted_period_count=partial_label_omitted_count,
    )
    return statistics, tuple(points)


def build_us_r1_direction_evidence(
    train_observations: Sequence[USR1CandidateObservation],
    denominator: USR1CandidateDenominator,
    *,
    fold_id: str,
    fold_materialization_manifest_id: str,
    policy: USR1StatisticalEvaluationPolicy,
) -> USR1DirectionEvidenceSet:
    candidates: list[USR1CandidateDirectionEvidence] = []
    for provenance in denominator.candidates:
        candidate_id = provenance.candidate.candidate_id
        statistics, _points = evaluate_us_r1_candidate_slice(
            train_observations,
            candidate_id=candidate_id,
            role=USR1ObservationRole.TRAIN,
            signal_interval=BarInterval.MINUTE_15,
            label_horizon_trading_minutes=60,
            policy=policy,
            minimum_periods=policy.minimum_train_periods,
        )
        if not statistics.passed or statistics.mean_raw_rank_ic is None:
            rendered = ",".join(statistics.blockers) or "mean_rank_ic_unavailable"
            raise ValueError(f"US-R1 cannot freeze direction for {candidate_id}: {rendered}")
        mean_rank_ic = statistics.mean_raw_rank_ic
        direction = 1 if mean_rank_ic >= 0.0 else -1
        candidates.append(
            USR1CandidateDirectionEvidence(
                candidate_id=candidate_id,
                evaluation_policy_id=policy.policy_id,
                source_fold_id=fold_id,
                source_fold_manifest_id=fold_materialization_manifest_id,
                train_statistics_id=statistics.statistics_id,
                train_period_count=statistics.period_count,
                train_mean_rank_ic=mean_rank_ic,
                direction=direction,
            )
        )
    return USR1DirectionEvidenceSet(
        denominator_id=denominator.denominator_id,
        evaluation_policy_id=policy.policy_id,
        source_fold_id=fold_id,
        source_fold_manifest_id=fold_materialization_manifest_id,
        candidates=tuple(candidates),
    )


def build_us_r1_fold_statistics(
    observations_by_slice: Mapping[
        tuple[BarInterval, int], Sequence[USR1CandidateObservation]
    ],
    denominator: USR1CandidateDenominator,
    *,
    fold_id: str,
    fold_ordinal: int,
    fold_materialization_manifest_id: str,
    policy: USR1StatisticalEvaluationPolicy,
) -> tuple[tuple[USR1PeriodMetricRecord, ...], tuple[USR1CandidateSliceStatistics, ...]]:
    expected_slices = (
        (BarInterval.MINUTE_5, 60),
        (BarInterval.MINUTE_15, 30),
        (BarInterval.MINUTE_15, 60),
        (BarInterval.MINUTE_15, 120),
        (BarInterval.MINUTE_30, 60),
    )
    if set(observations_by_slice) != set(expected_slices):
        raise ValueError("US-R1 fold statistics requires the exact five OOS evidence slices")
    records: list[USR1PeriodMetricRecord] = []
    statistics_items: list[USR1CandidateSliceStatistics] = []
    for interval, horizon in expected_slices:
        observations = observations_by_slice[(interval, horizon)]
        for provenance in denominator.candidates:
            candidate_id = provenance.candidate.candidate_id
            statistics, points = evaluate_us_r1_candidate_slice(
                observations,
                candidate_id=candidate_id,
                role=USR1ObservationRole.EVALUATION,
                signal_interval=interval,
                label_horizon_trading_minutes=horizon,
                policy=policy,
                minimum_periods=policy.minimum_oos_periods_per_fold,
            )
            statistics_items.append(statistics)
            records.extend(
                USR1PeriodMetricRecord(
                    candidate_id=candidate_id,
                    fold_id=fold_id,
                    fold_ordinal=fold_ordinal,
                    signal_interval=interval,
                    label_horizon_trading_minutes=horizon,
                    point=point,
                )
                for point in points
            )
    return tuple(records), tuple(statistics_items)


def write_us_r1_period_metric_artifact(
    records: Sequence[USR1PeriodMetricRecord],
    output: str | Path,
    *,
    fold_id: str,
    fold_ordinal: int,
    denominator: USR1CandidateDenominator,
    policy: USR1StatisticalEvaluationPolicy,
) -> USR1PeriodMetricArtifact:
    target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        records,
        key=lambda item: (
            item.candidate_id,
            item.signal_interval.value,
            item.label_horizon_trading_minutes,
            item.point.event_time,
        ),
    )
    digest = hashlib.sha256()
    with target.open("wb") as handle:
        for record in ordered:
            payload = json.dumps(
                record.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8") + b"\n"
            handle.write(payload)
            digest.update(payload)
    return USR1PeriodMetricArtifact(
        fold_id=fold_id,
        fold_ordinal=fold_ordinal,
        denominator_id=denominator.denominator_id,
        evaluation_policy_id=policy.policy_id,
        row_count=len(ordered),
        content_sha256=digest.hexdigest(),
        output_filename=target.name,
    )


def build_us_r1_fold_series(
    records: Sequence[USR1PeriodMetricRecord],
    *,
    candidate_id: str,
    fold_id: str,
    interval: BarInterval,
    horizon: int,
) -> USR1FoldSeries:
    points = tuple(
        record.point
        for record in sorted(records, key=lambda item: item.point.event_time)
        if record.candidate_id == candidate_id
        and record.fold_id == fold_id
        and record.signal_interval is interval
        and record.label_horizon_trading_minutes == horizon
    )
    return USR1FoldSeries(fold_id=fold_id, points=points)

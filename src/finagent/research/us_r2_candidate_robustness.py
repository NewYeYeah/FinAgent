from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import numpy as np

from finagent.domain.market_bars import BarInterval
from finagent.research.us_a1_factor_graph import FactorGraphSpec
from finagent.research.us_a1_factor_materialization import (
    CompiledFactorBatch,
    compile_factor_graph_batch,
    materialize_compiled_factor_batch,
)
from finagent.research.us_a1_factor_validation import validate_factor_graph
from finagent.research.us_a1_legacy_graphs import legacy_a0_factor_graph_with_window
from finagent.research.us_baselines import USBaselineBar
from finagent.research.us_r1_gate import canonical_us_r1_alpha_gate_policy
from finagent.research.us_r1_materialization import (
    compile_us_r1_feature_spec,
    effective_us_r1_window_bars,
)
from finagent.research.us_r1_protocol import USR1CandidateDenominator
from finagent.research.us_r2_candidate_cache import (
    FROZEN_CANDIDATE_COUNT,
    validate_us_r2_candidate_denominator,
)
from finagent.research.us_r2_evaluation_policy import (
    USR2StatisticalEvaluationPolicy,
    canonical_us_r2_statistical_evaluation_policy,
)
from finagent.research.us_r2_frozen_protocol import (
    FROZEN_ASSETS,
    FROZEN_CANDIDATE_DENOMINATOR_ID,
    FROZEN_REGIME_LABELS,
    canonical_us_r2_frozen_protocol,
)
from finagent.research.us_r2_primary_statistics import (
    FROZEN_CANDIDATE_CACHE_BATCH_EVIDENCE_ID,
    FROZEN_CANDIDATE_CACHE_PLAN_ID,
    FROZEN_COMPILED_CANDIDATE_BATCH_ID,
    METRIC_AVAILABLE,
    METRIC_PARTIAL_LABEL_OMITTED,
    USR2AnnualPrimaryMetricArrays,
    USR2PrimaryDirectionEvidenceSet,
    USR2PrimaryStatisticsPlan,
    USR2RegimeSessionMap,
    _candidate_status_and_rank_ic,
)
from finagent.research.us_r2_protocol import USMultiRegimeFold
from finagent.research.us_r2_robustness_base import (
    FROZEN_POOLED_INFERENCE_REPORT_ID,
    USR2RobustnessSlice,
    canonical_us_r2_robustness_materialization_policy,
    canonical_us_r2_robustness_slices,
)
from finagent.research.us_r2_robustness_batch import (
    USR2RobustnessBaseBatchEvidence,
    canonical_us_r2_robustness_years,
)

FROZEN_PRIMARY_DIRECTION_EVIDENCE_ID = "us-r2-primary-direction-set-baf85b7070311daad95e7ada"
FROZEN_PRIMARY_STATISTICS_PLAN_ID = "us-r2-primary-statistics-plan-d52413a72d50cd2bf0b0b1a4"
FROZEN_PRIMARY_STATISTICS_REPORT_ID = "us-r2-primary-statistics-39329ed645222038a8e29fef"
ROBUSTNESS_METRIC_FILENAME = "us_r2_candidate_robustness_metrics.npz"
ROBUSTNESS_METRIC_EVIDENCE_FILENAME = "us_r2_candidate_robustness_metrics_evidence.json"
ROBUSTNESS_PLAN_FILENAME = "us_r2_candidate_robustness_plan.json"
ROBUSTNESS_REPORT_FILENAME = "us_r2_candidate_robustness_report.json"

_EPOCH_DATE = date(1970, 1, 1)
_EPOCH_DATETIME = datetime(1970, 1, 1, tzinfo=UTC)
_NPZ_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_METRIC_STATUS_NAMES = (
    "AVAILABLE",
    "PARTIAL_LABEL_OMITTED",
    "INSUFFICIENT_CROSS_SECTION",
    "BOUNDARY_UNREALIZED",
    "UNCLASSIFIED_MISSING_LABEL",
    "RANK_IC_UNDEFINED",
)
_SLICE_CODE_BY_ID = {
    item.slice_id: index for index, item in enumerate(canonical_us_r2_robustness_slices())
}
_SLICE_BY_ID = {item.slice_id: item for item in canonical_us_r2_robustness_slices()}
_REGIME_LABEL_BY_CODE = {index: label for index, label in enumerate(FROZEN_REGIME_LABELS)}
_ASSET_CODE_BY_ID = {asset: index for index, asset in enumerate(FROZEN_ASSETS)}


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return cast(Mapping[str, object], value)


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise TypeError(f"{field_name} must be an integer")


def _date_value(value: object, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(_text(value, field_name))


def _aware_datetime(value: object, field_name: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(_text(value, field_name))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    rendered = float(cast(Any, value))
    if not math.isfinite(rendered):
        raise ValueError("numeric robustness-base value must be finite")
    return rendered


def _optional_bool(value: object, field_name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean or null")
    return value


def _date_to_days(value: date) -> int:
    return (value - _EPOCH_DATE).days


def _datetime_to_us(value: datetime) -> int:
    delta = value.astimezone(UTC) - _EPOCH_DATETIME
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_us_r2_robustness_base_batch_gate(
    document: Mapping[str, object],
) -> USR2RobustnessBaseBatchEvidence:
    evidence = USR2RobustnessBaseBatchEvidence(
        policy_id=_text(document.get("policy_id"), "policy_id"),
        requested_years=tuple(
            _integer(item, "requested_years[]")
            for item in _sequence(document.get("requested_years"), "requested_years")
        ),
        annual_evidence_ids=tuple(
            _text(item, "annual_evidence_ids[]")
            for item in _sequence(document.get("annual_evidence_ids"), "annual_evidence_ids")
        ),
        annual_materialization_ids=tuple(
            _text(item, "annual_materialization_ids[]")
            for item in _sequence(
                document.get("annual_materialization_ids"), "annual_materialization_ids"
            )
        ),
        total_row_count=_integer(document.get("total_row_count"), "total_row_count"),
    )
    if dict(document) != evidence.to_dict():
        raise ValueError("US-R2 robustness-base batch content-addressed document mismatch")
    if evidence.policy_id != canonical_us_r2_robustness_materialization_policy().policy_id:
        raise ValueError("US-R2 candidate robustness requires the frozen robustness-base policy")
    if evidence.requested_years != canonical_us_r2_robustness_years() or not evidence.passed:
        raise ValueError("US-R2 candidate robustness requires the complete passed 2006-2026 base batch")
    return evidence


@dataclass(frozen=True, slots=True)
class USR2RobustnessCandidateBinding:
    slot: int
    r1_candidate_id: str
    structural_key: str
    signal_interval: BarInterval
    effective_window_bars: int
    feature_spec_id: str
    a1_candidate_id: str
    root_execution_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "slot": self.slot,
            "r1_candidate_id": self.r1_candidate_id,
            "structural_key": self.structural_key,
            "signal_interval": self.signal_interval.value,
            "effective_window_bars": self.effective_window_bars,
            "feature_spec_id": self.feature_spec_id,
            "a1_candidate_id": self.a1_candidate_id,
            "root_execution_id": self.root_execution_id,
        }


@dataclass(frozen=True, slots=True)
class USR2RobustnessCandidateExecution:
    signal_interval: BarInterval
    compiled: CompiledFactorBatch
    bindings: tuple[USR2RobustnessCandidateBinding, ...]

    def __post_init__(self) -> None:
        if len(self.bindings) != FROZEN_CANDIDATE_COUNT:
            raise ValueError("US-R2 robustness execution must retain all 37 candidates")
        if tuple(item.slot for item in self.bindings) != tuple(range(FROZEN_CANDIDATE_COUNT)):
            raise ValueError("US-R2 robustness execution candidate slots changed")
        if any(item.signal_interval is not self.signal_interval for item in self.bindings):
            raise ValueError("US-R2 robustness execution mixes signal intervals")
        root_by_candidate = {item.candidate_id: item for item in self.compiled.roots}
        bound_candidate_ids = {item.a1_candidate_id for item in self.bindings}
        if bound_candidate_ids != set(root_by_candidate):
            raise ValueError("US-R2 robustness compiled numeric roots/bindings differ")
        for binding in self.bindings:
            root = root_by_candidate[binding.a1_candidate_id]
            if binding.root_execution_id != root.root_execution_id:
                raise ValueError("US-R2 robustness binding/root execution identity mismatch")

    @property
    def numeric_graph_count(self) -> int:
        return len(self.compiled.roots)

    @property
    def collapsed_numeric_graph_count(self) -> int:
        return len(self.bindings) - self.numeric_graph_count

    def to_dict(self) -> dict[str, object]:
        return {
            "signal_interval": self.signal_interval.value,
            "compiled_batch_id": self.compiled.batch_id,
            "candidate_count": len(self.bindings),
            "numeric_graph_count": self.numeric_graph_count,
            "collapsed_numeric_graph_count": self.collapsed_numeric_graph_count,
            "naive_node_count": self.compiled.naive_node_count,
            "unique_node_count": self.compiled.unique_node_count,
            "reused_node_count": self.compiled.reused_node_count,
            "bindings": [item.to_dict() for item in self.bindings],
        }


def compile_us_r2_robustness_candidate_execution(
    denominator: USR1CandidateDenominator,
    signal_interval: BarInterval,
) -> USR2RobustnessCandidateExecution:
    if signal_interval not in {BarInterval.MINUTE_5, BarInterval.MINUTE_15, BarInterval.MINUTE_30}:
        raise ValueError("US-R2 robustness candidate interval must be 5m/15m/30m")
    if denominator.denominator_id != FROZEN_CANDIDATE_DENOMINATOR_ID:
        raise ValueError("US-R2 robustness candidate execution requires the frozen denominator")
    if len(denominator.candidates) != FROZEN_CANDIDATE_COUNT:
        raise ValueError("US-R2 robustness candidate execution requires exactly 37 candidates")

    graph_ids: list[str] = []
    effective_windows: list[int] = []
    feature_spec_ids: list[str] = []
    unique_graphs: dict[str, FactorGraphSpec] = {}
    for provenance in denominator.candidates:
        candidate = provenance.candidate
        effective_window = effective_us_r1_window_bars(candidate, signal_interval)
        graph = legacy_a0_factor_graph_with_window(candidate, window_bars=effective_window)
        graph_evidence = validate_factor_graph(graph)
        if not graph_evidence.valid or graph_evidence.canonicalization is None:
            raise RuntimeError("scaled legacy factor graph failed A1 canonical validation")
        numeric_candidate_id = graph_evidence.canonicalization.candidate_id
        existing = unique_graphs.get(numeric_candidate_id)
        if existing is None:
            unique_graphs[numeric_candidate_id] = graph
        else:
            existing_evidence = validate_factor_graph(existing)
            if (
                not existing_evidence.valid
                or existing_evidence.canonicalization is None
                or existing_evidence.canonicalization.root_digest
                != graph_evidence.canonicalization.root_digest
            ):
                raise RuntimeError("canonical robustness graph identity collision")
        graph_ids.append(numeric_candidate_id)
        effective_windows.append(effective_window)
        feature_spec_ids.append(compile_us_r1_feature_spec(candidate, signal_interval).spec_id)

    compiled = compile_factor_graph_batch(tuple(unique_graphs.values()))
    if signal_interval is BarInterval.MINUTE_15:
        if len(unique_graphs) != FROZEN_CANDIDATE_COUNT:
            raise RuntimeError("15m primary-compatible robustness graphs unexpectedly collapsed")
        if compiled.batch_id != FROZEN_COMPILED_CANDIDATE_BATCH_ID:
            raise RuntimeError("15m robustness graph batch diverged from the reviewed primary shared DAG")
    root_by_candidate = {item.candidate_id: item for item in compiled.roots}
    bindings = []
    for slot, provenance in enumerate(denominator.candidates):
        a1_candidate_id = graph_ids[slot]
        root = root_by_candidate.get(a1_candidate_id)
        if root is None:
            raise RuntimeError("compiled robustness DAG lost a numeric candidate root")
        candidate = provenance.candidate
        bindings.append(
            USR2RobustnessCandidateBinding(
                slot=slot,
                r1_candidate_id=candidate.candidate_id,
                structural_key=candidate.structural_key,
                signal_interval=signal_interval,
                effective_window_bars=effective_windows[slot],
                feature_spec_id=feature_spec_ids[slot],
                a1_candidate_id=a1_candidate_id,
                root_execution_id=root.root_execution_id,
            )
        )
    return USR2RobustnessCandidateExecution(
        signal_interval=signal_interval,
        compiled=compiled,
        bindings=tuple(bindings),
    )


@dataclass(frozen=True, slots=True)
class USR2CandidateRobustnessPlan:
    frozen_protocol_id: str
    evaluation_policy_id: str
    denominator_id: str
    robustness_policy_id: str
    robustness_base_batch_evidence_id: str
    regime_projection_evidence_id: str
    primary_statistics_plan_id: str
    primary_direction_evidence_id: str
    primary_statistics_report_id: str
    pooled_inference_report_id: str
    candidate_ids: tuple[str, ...]
    interval_executions: tuple[USR2RobustnessCandidateExecution, ...]
    schema_version: str = "finagent.us-r2-candidate-robustness-plan.v1"

    @property
    def plan_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-candidate-robustness-plan")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "frozen_protocol_id": self.frozen_protocol_id,
            "evaluation_policy_id": self.evaluation_policy_id,
            "denominator_id": self.denominator_id,
            "candidate_count": len(self.candidate_ids),
            "candidate_ids": list(self.candidate_ids),
            "robustness_policy_id": self.robustness_policy_id,
            "robustness_base_batch_evidence_id": self.robustness_base_batch_evidence_id,
            "regime_projection_evidence_id": self.regime_projection_evidence_id,
            "primary_statistics_plan_id": self.primary_statistics_plan_id,
            "primary_direction_evidence_id": self.primary_direction_evidence_id,
            "primary_statistics_report_id": self.primary_statistics_report_id,
            "pooled_inference_report_id": self.pooled_inference_report_id,
            "interval_executions": [item.to_dict() for item in self.interval_executions],
            "feature_interval_evaluation_count_per_year": 3,
            "robustness_slice_count": 4,
            "window_conversion": "1+ceil((base_window_bars-1)*15/target_interval_minutes)",
            "numeric_graph_collisions_preserve_external_candidate_slots": True,
            "direction_refit_allowed": False,
            "primary_15m_60m_feature_recomputation": False,
            "performance_filter_applied": False,
            "candidate_selection_applied": False,
            "alpha_gate_evaluated": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["plan_id"] = self.plan_id
        return payload


def build_us_r2_candidate_robustness_plan(
    denominator: USR1CandidateDenominator,
    *,
    robustness_base_batch_evidence_id: str,
    regime_projection_evidence_id: str,
    primary_plan: USR2PrimaryStatisticsPlan,
    primary_direction: USR2PrimaryDirectionEvidenceSet,
    primary_statistics_report_id: str,
) -> USR2CandidateRobustnessPlan:
    if denominator.denominator_id != FROZEN_CANDIDATE_DENOMINATOR_ID:
        raise ValueError("US-R2 robustness plan requires the exact frozen denominator")
    if primary_plan.plan_id != FROZEN_PRIMARY_STATISTICS_PLAN_ID:
        raise ValueError("US-R2 robustness plan requires the reviewed primary statistics plan")
    if primary_plan.candidate_cache_batch_evidence_id != FROZEN_CANDIDATE_CACHE_BATCH_EVIDENCE_ID:
        raise ValueError("US-R2 robustness plan primary source batch changed")
    if primary_plan.candidate_cache_plan_id != FROZEN_CANDIDATE_CACHE_PLAN_ID:
        raise ValueError("US-R2 robustness plan primary candidate-cache plan changed")
    if primary_direction.evidence_id != FROZEN_PRIMARY_DIRECTION_EVIDENCE_ID or not primary_direction.passed:
        raise ValueError("US-R2 robustness plan requires the reviewed passed primary direction")
    if primary_statistics_report_id != FROZEN_PRIMARY_STATISTICS_REPORT_ID:
        raise ValueError("US-R2 robustness plan requires the reviewed primary statistics report")
    if regime_projection_evidence_id != primary_plan.regime_projection_evidence_id:
        raise ValueError("US-R2 robustness plan regime identity differs from primary statistics")
    executions = tuple(
        compile_us_r2_robustness_candidate_execution(denominator, interval)
        for interval in (BarInterval.MINUTE_5, BarInterval.MINUTE_15, BarInterval.MINUTE_30)
    )
    candidate_ids = tuple(item.candidate.candidate_id for item in denominator.candidates)
    return USR2CandidateRobustnessPlan(
        frozen_protocol_id=canonical_us_r2_frozen_protocol().freeze_id,
        evaluation_policy_id=canonical_us_r2_statistical_evaluation_policy().policy_id,
        denominator_id=denominator.denominator_id,
        robustness_policy_id=canonical_us_r2_robustness_materialization_policy().policy_id,
        robustness_base_batch_evidence_id=robustness_base_batch_evidence_id,
        regime_projection_evidence_id=regime_projection_evidence_id,
        primary_statistics_plan_id=primary_plan.plan_id,
        primary_direction_evidence_id=primary_direction.evidence_id,
        primary_statistics_report_id=primary_statistics_report_id,
        pooled_inference_report_id=FROZEN_POOLED_INFERENCE_REPORT_ID,
        candidate_ids=candidate_ids,
        interval_executions=executions,
    )


@dataclass(frozen=True, slots=True)
class USR2RobustnessBaseRow:
    slice_id: str
    research_asset_id: str
    session_date: date
    session_id: str
    event_time: datetime
    available_at: datetime
    bar_index: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_complete: bool
    label_value: float | None
    label_available: bool | None
    unavailable_reason: str | None
    label_row_present: bool

    @property
    def slice(self) -> USR2RobustnessSlice:
        return _SLICE_BY_ID[self.slice_id]

    @property
    def asset_code(self) -> int:
        try:
            return _ASSET_CODE_BY_ID[self.research_asset_id]
        except KeyError as exc:
            raise ValueError("robustness-base row contains an asset outside the frozen 25") from exc

    def bar_identity(self) -> tuple[object, ...]:
        return (
            self.research_asset_id,
            self.session_date,
            self.session_id,
            self.event_time,
            self.available_at,
            self.bar_index,
            float(self.open).hex(),
            float(self.high).hex(),
            float(self.low).hex(),
            float(self.close).hex(),
            float(self.volume).hex(),
            self.is_complete,
        )


def parse_us_r2_robustness_base_row(document: Mapping[str, object]) -> USR2RobustnessBaseRow:
    slice_id = _text(document.get("slice_id"), "slice_id")
    if slice_id not in _SLICE_BY_ID:
        raise ValueError("robustness-base row has an unknown frozen slice")
    asset = _text(document.get("research_asset_id"), "research_asset_id")
    if asset not in _ASSET_CODE_BY_ID:
        raise ValueError("robustness-base row has an asset outside the frozen 25")
    label_reason_raw = document.get("unavailable_reason")
    label_reason = None if label_reason_raw is None else _text(label_reason_raw, "unavailable_reason")
    is_complete = document.get("is_complete")
    label_row_present = document.get("label_row_present")
    if not isinstance(is_complete, bool) or not isinstance(label_row_present, bool):
        raise TypeError("robustness-base completeness/presence flags must be boolean")
    return USR2RobustnessBaseRow(
        slice_id=slice_id,
        research_asset_id=asset,
        session_date=_date_value(document.get("session_date"), "session_date"),
        session_id=_text(document.get("session_id"), "session_id"),
        event_time=_aware_datetime(document.get("event_time"), "event_time"),
        available_at=_aware_datetime(document.get("available_at"), "available_at"),
        bar_index=_integer(document.get("bar_index"), "bar_index"),
        open=float(cast(Any, document.get("open"))),
        high=float(cast(Any, document.get("high"))),
        low=float(cast(Any, document.get("low"))),
        close=float(cast(Any, document.get("close"))),
        volume=float(cast(Any, document.get("volume"))),
        is_complete=is_complete,
        label_value=_optional_float(document.get("label_value")),
        label_available=_optional_bool(document.get("label_available"), "label_available"),
        unavailable_reason=label_reason,
        label_row_present=label_row_present,
    )


def _validate_slice_rows(
    rows: tuple[USR2RobustnessBaseRow, ...],
    slice_id: str,
) -> None:
    if not rows:
        raise ValueError(f"US-R2 robustness slice is empty: {slice_id}")
    previous_key: tuple[datetime, int] | None = None
    for row in rows:
        if row.slice_id != slice_id:
            raise ValueError("US-R2 robustness slice row identity mismatch")
        key = (row.available_at, row.asset_code)
        if previous_key is not None and key <= previous_key:
            raise ValueError("US-R2 robustness slice rows must be ordered by formation and asset")
        previous_key = key


def _validate_same_bar_rows(
    left: tuple[USR2RobustnessBaseRow, ...],
    right: tuple[USR2RobustnessBaseRow, ...],
) -> None:
    if len(left) != len(right):
        raise ValueError("US-R2 15m decay slices do not share the same bar denominator")
    for left_row, right_row in zip(left, right, strict=True):
        if left_row.bar_identity() != right_row.bar_identity():
            raise ValueError("US-R2 15m decay slices differ in bar content/order")


def _bar_rows_digest(rows: Sequence[USR2RobustnessBaseRow]) -> str:
    """Compactly bind an ordered bar denominator without retaining another slice."""

    digest = hashlib.sha256()
    for row in rows:
        payload = (
            row.research_asset_id,
            row.session_date.isoformat(),
            row.session_id,
            row.event_time.isoformat(),
            row.available_at.isoformat(),
            row.bar_index,
            float(row.open).hex(),
            float(row.high).hex(),
            float(row.low).hex(),
            float(row.close).hex(),
            float(row.volume).hex(),
            row.is_complete,
        )
        digest.update(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _materialize_candidate_matrix(
    rows: tuple[USR2RobustnessBaseRow, ...],
    execution: USR2RobustnessCandidateExecution,
    *,
    progress: Callable[[str, Mapping[str, object]], None] | None = None,
    slice_id: str | None = None,
) -> tuple[np.ndarray, int]:
    values = np.full((len(rows), FROZEN_CANDIDATE_COUNT), np.nan, dtype=np.float64)
    indices_by_asset: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        indices_by_asset.setdefault(row.research_asset_id, []).append(index)
    node_evaluations = 0
    bindings_by_a1: dict[str, list[USR2RobustnessCandidateBinding]] = {}
    for binding in execution.bindings:
        bindings_by_a1.setdefault(binding.a1_candidate_id, []).append(binding)
    for asset in FROZEN_ASSETS:
        indices = indices_by_asset.get(asset)
        if not indices:
            continue
        bars = tuple(
            USBaselineBar(
                event_time=rows[index].event_time,
                available_at=rows[index].available_at,
                session_id=rows[index].session_id,
                open=rows[index].open,
                high=rows[index].high,
                low=rows[index].low,
                close=rows[index].close,
                volume=rows[index].volume,
                is_complete=rows[index].is_complete,
            )
            for index in indices
        )
        materialized = materialize_compiled_factor_batch(
            execution.compiled,
            bars,
            maximum_bars_per_batch=100_000,
        )
        node_evaluations += materialized.node_series_evaluation_count
        for series in materialized.candidates:
            bindings = bindings_by_a1.get(series.candidate_id)
            if not bindings:
                raise RuntimeError("robustness materialization returned an unbound numeric candidate")
            if len(series.values) != len(indices):
                raise RuntimeError("robustness candidate series length mismatch")
            for binding in bindings:
                for local_index, value in enumerate(series.values):
                    if value is not None:
                        values[indices[local_index], binding.slot] = value
        if progress is not None:
            progress(
                "slice_asset_features_materialized",
                {
                    "slice_id": slice_id or rows[indices[0]].slice_id,
                    "research_asset_id": asset,
                    "asset_row_count": len(indices),
                },
            )
    return values, node_evaluations


def _formation_ranges(rows: tuple[USR2RobustnessBaseRow, ...]) -> Iterable[tuple[int, int]]:
    start = 0
    while start < len(rows):
        formation = rows[start].available_at
        end = start + 1
        while end < len(rows) and rows[end].available_at == formation:
            end += 1
        yield start, end
        start = end


def _is_partial_label_formation(rows: Sequence[USR2RobustnessBaseRow]) -> bool:
    return any(
        (not row.label_row_present) or row.unavailable_reason == "target_minute_missing"
        for row in rows
    )


def _label_reason_code(row: USR2RobustnessBaseRow) -> int:
    if not row.label_row_present or row.unavailable_reason == "target_minute_missing":
        return 2
    if row.label_available is True:
        return 0
    if row.unavailable_reason == "target_crosses_session":
        return 1
    return 3


def _fold_for_year(year: int) -> USMultiRegimeFold:
    frozen = canonical_us_r2_frozen_protocol()
    matches = tuple(
        fold
        for fold in frozen.walk_forward_protocol.folds
        if fold.evaluation_start.year <= year <= (fold.evaluation_end - timedelta(days=1)).year
    )
    if len(matches) != 1:
        raise ValueError(f"US-R2 robustness year {year} is not uniquely assigned to one fold")
    return matches[0]


@dataclass(frozen=True, slots=True)
class USR2AnnualRobustnessMetricArrays:
    session_date_days: np.ndarray
    formation_at_us: np.ndarray
    regime_codes: np.ndarray
    slice_codes: np.ndarray
    rank_ic: np.ndarray
    status_codes: np.ndarray

    @property
    def row_count(self) -> int:
        return int(self.rank_ic.shape[0])

    @property
    def candidate_count(self) -> int:
        return int(self.rank_ic.shape[1])

    def __post_init__(self) -> None:
        if self.rank_ic.ndim != 2 or self.rank_ic.shape[1] != FROZEN_CANDIDATE_COUNT:
            raise ValueError("US-R2 robustness metric RankIC must be N x 37")
        rows = self.rank_ic.shape[0]
        if self.status_codes.shape != self.rank_ic.shape:
            raise ValueError("US-R2 robustness metric status shape mismatch")
        for vector in (
            self.session_date_days,
            self.formation_at_us,
            self.regime_codes,
            self.slice_codes,
        ):
            if vector.shape != (rows,):
                raise ValueError("US-R2 robustness metric metadata vector shape mismatch")
        if np.any(self.regime_codes >= len(FROZEN_REGIME_LABELS)):
            raise ValueError("US-R2 robustness metric has an invalid regime code")
        if np.any(self.slice_codes >= len(_SLICE_CODE_BY_ID)):
            raise ValueError("US-R2 robustness metric has an invalid slice code")
        if not np.array_equal(np.isfinite(self.rank_ic), self.status_codes == METRIC_AVAILABLE):
            raise ValueError("US-R2 robustness RankIC finite mask differs from AVAILABLE status")

    def as_npz_arrays(self) -> dict[str, np.ndarray]:
        return {
            "session_date_days": self.session_date_days,
            "formation_at_us": self.formation_at_us,
            "regime_codes": self.regime_codes,
            "slice_codes": self.slice_codes,
            "rank_ic": self.rank_ic,
            "status_codes": self.status_codes,
        }


@dataclass(frozen=True, slots=True)
class USR2AnnualRobustnessEvaluationStats:
    feature_interval_evaluation_count: int
    node_series_evaluation_count: int
    source_slice_row_counts: tuple[tuple[str, int], ...]
    metric_slice_formation_counts: tuple[tuple[str, int], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "feature_interval_evaluation_count": self.feature_interval_evaluation_count,
            "node_series_evaluation_count": self.node_series_evaluation_count,
            "source_slice_row_counts": dict(self.source_slice_row_counts),
            "metric_slice_formation_counts": dict(self.metric_slice_formation_counts),
        }


def _evaluate_slice_metrics(
    rows: tuple[USR2RobustnessBaseRow, ...],
    candidate_values: np.ndarray,
    *,
    year: int,
    regime_sessions: USR2RegimeSessionMap,
    policy: USR2StatisticalEvaluationPolicy,
) -> tuple[list[int], list[int], list[int], list[list[float]], list[list[int]]]:
    fold = _fold_for_year(year)
    fold_id = fold.fold_id
    evaluation_start = fold.evaluation_start
    evaluation_end = fold.evaluation_end
    regime_by_key = regime_sessions.by_key()
    session_days_out: list[int] = []
    formation_us_out: list[int] = []
    regime_codes_out: list[int] = []
    rank_rows: list[list[float]] = []
    status_rows: list[list[int]] = []

    for start, end in _formation_ranges(rows):
        formation = rows[start:end]
        session_date = formation[0].session_date
        if any(row.session_date != session_date for row in formation):
            raise ValueError("US-R2 robustness formation mixes session dates")
        if not evaluation_start <= session_date < evaluation_end:
            continue
        regime = regime_by_key.get((fold_id, _date_to_days(session_date)))
        if regime is None:
            raise ValueError(f"US-R2 robustness formation lacks regime projection: {fold_id}:{session_date}")
        if not regime.available:
            continue
        if regime.regime_code is None:
            raise RuntimeError("available US-R2 robustness regime lost regime_code")

        rank_row = [float("nan")] * FROZEN_CANDIDATE_COUNT
        status_row = [METRIC_PARTIAL_LABEL_OMITTED] * FROZEN_CANDIDATE_COUNT
        if not _is_partial_label_formation(formation):
            asset_codes = np.asarray([row.asset_code for row in formation], dtype=np.uint8)
            labels = np.asarray(
                [float("nan") if row.label_value is None else row.label_value for row in formation],
                dtype=np.float64,
            )
            label_available = np.asarray(
                [row.label_available is True for row in formation],
                dtype=np.bool_,
            )
            label_reason_codes = np.asarray(
                [_label_reason_code(row) for row in formation],
                dtype=np.uint8,
            )
            for slot in range(FROZEN_CANDIDATE_COUNT):
                status, rank_ic, _valid = _candidate_status_and_rank_ic(
                    asset_codes=asset_codes,
                    candidate_values=candidate_values[start:end, slot],
                    label_values=labels,
                    label_available=label_available,
                    label_reason_codes=label_reason_codes,
                    minimum_cross_section=policy.minimum_cross_section,
                )
                status_row[slot] = status
                if status == METRIC_AVAILABLE:
                    if rank_ic is None:
                        raise RuntimeError("available robustness metric lost RankIC")
                    rank_row[slot] = rank_ic

        session_days_out.append(_date_to_days(session_date))
        formation_us_out.append(_datetime_to_us(formation[0].available_at))
        regime_codes_out.append(regime.regime_code)
        rank_rows.append(rank_row)
        status_rows.append(status_row)
    return session_days_out, formation_us_out, regime_codes_out, rank_rows, status_rows


def evaluate_us_r2_annual_candidate_robustness(
    rows_by_slice: Mapping[str, tuple[USR2RobustnessBaseRow, ...]],
    *,
    year: int,
    plan: USR2CandidateRobustnessPlan,
    regime_sessions: USR2RegimeSessionMap,
    policy: USR2StatisticalEvaluationPolicy | None = None,
) -> tuple[USR2AnnualRobustnessMetricArrays, USR2AnnualRobustnessEvaluationStats]:
    expected_slice_ids = tuple(item.slice_id for item in canonical_us_r2_robustness_slices())
    if tuple(rows_by_slice) != expected_slice_ids:
        raise ValueError("US-R2 robustness annual slice input order/denominator changed")
    _validate_same_bar_rows(
        rows_by_slice["decay_15m_30m"],
        rows_by_slice["decay_15m_120m"],
    )
    return evaluate_us_r2_annual_candidate_robustness_streaming(
        ((slice_id, rows_by_slice[slice_id]) for slice_id in expected_slice_ids),
        year=year,
        plan=plan,
        regime_sessions=regime_sessions,
        policy=policy,
    )


def evaluate_us_r2_annual_candidate_robustness_streaming(
    annual_slices: Iterable[tuple[str, tuple[USR2RobustnessBaseRow, ...]]],
    *,
    year: int,
    plan: USR2CandidateRobustnessPlan,
    regime_sessions: USR2RegimeSessionMap,
    policy: USR2StatisticalEvaluationPolicy | None = None,
    progress: Callable[[str, Mapping[str, object]], None] | None = None,
) -> tuple[USR2AnnualRobustnessMetricArrays, USR2AnnualRobustnessEvaluationStats]:
    """Evaluate ordered slices while retaining at most one candidate feature matrix."""

    active = policy or canonical_us_r2_statistical_evaluation_policy()
    expected_slices = canonical_us_r2_robustness_slices()
    expected_slice_ids = tuple(item.slice_id for item in expected_slices)
    slice_iterator = iter(annual_slices)
    execution_by_interval = {item.signal_interval: item for item in plan.interval_executions}
    shared_15m_matrix: np.ndarray | None = None
    shared_15m_bar_digest: str | None = None
    node_series_evaluation_count = 0

    session_day_chunks: list[np.ndarray] = []
    formation_us_chunks: list[np.ndarray] = []
    regime_code_chunks: list[np.ndarray] = []
    slice_code_chunks: list[np.ndarray] = []
    rank_chunks: list[np.ndarray] = []
    status_chunks: list[np.ndarray] = []
    source_slice_counts: list[tuple[str, int]] = []
    metric_slice_counts: list[tuple[str, int]] = []

    for expected_spec in expected_slices:
        try:
            slice_id, rows = next(slice_iterator)
        except StopIteration as exc:
            raise ValueError(
                f"US-R2 robustness annual slice input is missing: {expected_spec.slice_id}"
            ) from exc
        if slice_id != expected_spec.slice_id:
            raise ValueError("US-R2 robustness annual slice input order/denominator changed")
        _validate_slice_rows(rows, slice_id)
        source_slice_counts.append((slice_id, len(rows)))
        if progress is not None:
            progress("slice_loaded", {"slice_id": slice_id, "row_count": len(rows)})

        execution = execution_by_interval.get(expected_spec.signal_interval)
        if execution is None:
            raise ValueError("US-R2 robustness plan lost an interval execution")
        if expected_spec.signal_interval is BarInterval.MINUTE_15:
            current_digest = _bar_rows_digest(rows)
            if shared_15m_matrix is None:
                shared_15m_matrix, node_count = _materialize_candidate_matrix(
                    rows,
                    execution,
                    progress=progress,
                    slice_id=slice_id,
                )
                shared_15m_bar_digest = current_digest
                node_series_evaluation_count += node_count
            else:
                if shared_15m_bar_digest != current_digest:
                    raise ValueError("US-R2 15m decay slices differ in bar content/order")
                if shared_15m_matrix.shape[0] != len(rows):
                    raise RuntimeError(
                        "reused 15m candidate matrix does not align with 120m decay slice"
                    )
            if shared_15m_matrix is None:
                raise RuntimeError("US-R2 shared 15m candidate matrix was not materialized")
            matrix = shared_15m_matrix
        else:
            matrix, node_count = _materialize_candidate_matrix(
                rows,
                execution,
                progress=progress,
                slice_id=slice_id,
            )
            node_series_evaluation_count += node_count
        if progress is not None:
            progress(
                "slice_features_materialized",
                {
                    "slice_id": slice_id,
                    "signal_interval": expected_spec.signal_interval.value,
                    "candidate_count": FROZEN_CANDIDATE_COUNT,
                },
            )

        evaluated = _evaluate_slice_metrics(
            rows,
            matrix,
            year=year,
            regime_sessions=regime_sessions,
            policy=active,
        )
        days, times, regimes, ranks, statuses = evaluated
        metric_slice_counts.append((slice_id, len(ranks)))
        session_day_chunks.append(np.asarray(days, dtype=np.int32))
        formation_us_chunks.append(np.asarray(times, dtype=np.int64))
        regime_code_chunks.append(np.asarray(regimes, dtype=np.uint8))
        slice_code_chunks.append(
            np.full(len(ranks), _SLICE_CODE_BY_ID[slice_id], dtype=np.uint8)
        )
        rank_chunks.append(np.asarray(ranks, dtype=np.float64))
        status_chunks.append(np.asarray(statuses, dtype=np.uint8))
        if progress is not None:
            progress(
                "slice_metrics_reduced",
                {"slice_id": slice_id, "formation_count": len(ranks)},
            )

        if slice_id == "decay_15m_120m":
            shared_15m_matrix = None
            shared_15m_bar_digest = None
        del matrix, rows, evaluated, days, times, regimes, ranks, statuses

    try:
        next(slice_iterator)
    except StopIteration:
        pass
    else:
        raise ValueError("US-R2 robustness annual slice input contains extra slices")

    if not rank_chunks or not any(chunk.shape[0] for chunk in rank_chunks):
        raise ValueError(
            f"US-R2 robustness annual metrics contain no regime-available formations: {year}"
        )
    arrays = USR2AnnualRobustnessMetricArrays(
        session_date_days=np.concatenate(session_day_chunks),
        formation_at_us=np.concatenate(formation_us_chunks),
        regime_codes=np.concatenate(regime_code_chunks),
        slice_codes=np.concatenate(slice_code_chunks),
        rank_ic=np.concatenate(rank_chunks, axis=0),
        status_codes=np.concatenate(status_chunks, axis=0),
    )
    stats = USR2AnnualRobustnessEvaluationStats(
        feature_interval_evaluation_count=3,
        node_series_evaluation_count=node_series_evaluation_count,
        source_slice_row_counts=tuple(source_slice_counts),
        metric_slice_formation_counts=tuple(metric_slice_counts),
    )
    if tuple(slice_id for slice_id, _count in stats.source_slice_row_counts) != expected_slice_ids:
        raise RuntimeError("US-R2 robustness streaming slice order changed after evaluation")
    return arrays, stats


def write_deterministic_us_r2_robustness_metric_npz(
    path: Path,
    arrays: USR2AnnualRobustnessMetricArrays,
) -> tuple[str, int]:
    target = path.expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"US-R2 robustness metric output is immutable: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, mode="x", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for name, array in sorted(arrays.as_npz_arrays().items()):
            buffer = io.BytesIO()
            write_array = cast(
                Callable[..., None],
                np.lib.format.write_array,
            )
            write_array(buffer, np.ascontiguousarray(array), allow_pickle=False)
            info = zipfile.ZipInfo(filename=f"{name}.npy", date_time=_NPZ_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, buffer.getvalue())
    return _sha256_file(target), target.stat().st_size


def load_us_r2_robustness_metric_npz(path: Path) -> USR2AnnualRobustnessMetricArrays:
    target = path.expanduser().resolve()
    with np.load(target, allow_pickle=False) as archive:
        required = {
            "session_date_days",
            "formation_at_us",
            "regime_codes",
            "slice_codes",
            "rank_ic",
            "status_codes",
        }
        if set(archive.files) != required:
            raise ValueError("US-R2 robustness metric NPZ field set mismatch")
        return USR2AnnualRobustnessMetricArrays(
            session_date_days=np.asarray(archive["session_date_days"], dtype=np.int32),
            formation_at_us=np.asarray(archive["formation_at_us"], dtype=np.int64),
            regime_codes=np.asarray(archive["regime_codes"], dtype=np.uint8),
            slice_codes=np.asarray(archive["slice_codes"], dtype=np.uint8),
            rank_ic=np.asarray(archive["rank_ic"], dtype=np.float64),
            status_codes=np.asarray(archive["status_codes"], dtype=np.uint8),
        )


@dataclass(frozen=True, slots=True)
class USR2AnnualCandidateRobustnessEvidence:
    plan_id: str
    year: int
    robustness_base_evidence_id: str
    robustness_base_materialization_id: str
    row_count: int
    candidate_count: int
    feature_interval_evaluation_count: int
    node_series_evaluation_count: int
    source_slice_row_counts: tuple[tuple[str, int], ...]
    metric_slice_formation_counts: tuple[tuple[str, int], ...]
    status_counts: tuple[tuple[str, int], ...]
    output_filename: str
    output_size_bytes: int
    content_sha256: str
    blockers: tuple[str, ...] = ()
    schema_version: str = "finagent.us-r2-annual-candidate-robustness-evidence.v1"

    @property
    def passed(self) -> bool:
        return (
            not self.blockers
            and self.row_count > 0
            and self.candidate_count == FROZEN_CANDIDATE_COUNT
            and self.feature_interval_evaluation_count == 3
            and all(count > 0 for _slice_id, count in self.metric_slice_formation_counts)
        )

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-annual-candidate-robustness")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "year": self.year,
            "robustness_base_evidence_id": self.robustness_base_evidence_id,
            "robustness_base_materialization_id": self.robustness_base_materialization_id,
            "row_count": self.row_count,
            "candidate_count": self.candidate_count,
            "feature_interval_evaluation_count": self.feature_interval_evaluation_count,
            "node_series_evaluation_count": self.node_series_evaluation_count,
            "source_slice_row_counts": dict(self.source_slice_row_counts),
            "metric_slice_formation_counts": dict(self.metric_slice_formation_counts),
            "status_counts": dict(self.status_counts),
            "output_filename": self.output_filename,
            "output_size_bytes": self.output_size_bytes,
            "content_sha256": self.content_sha256,
            "blockers": list(self.blockers),
            "passed": self.passed,
            "source_kind": "annual_exact_robustness_base_parquet",
            "annual_robustness_base_parquet_scan_count": 1,
            "raw_minute_source_access": False,
            "primary_candidate_cache_access": False,
            "primary_feature_recomputation": False,
            "candidate_selection_applied": False,
            "alpha_gate_evaluated": False,
            "terminal_authority": False,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


def build_us_r2_annual_candidate_robustness_evidence(
    *,
    plan: USR2CandidateRobustnessPlan,
    year: int,
    robustness_base_evidence_id: str,
    robustness_base_materialization_id: str,
    arrays: USR2AnnualRobustnessMetricArrays,
    stats: USR2AnnualRobustnessEvaluationStats,
    output_filename: str,
    output_size_bytes: int,
    content_sha256: str,
) -> USR2AnnualCandidateRobustnessEvidence:
    counts = np.bincount(arrays.status_codes.ravel(), minlength=len(_METRIC_STATUS_NAMES))
    return USR2AnnualCandidateRobustnessEvidence(
        plan_id=plan.plan_id,
        year=year,
        robustness_base_evidence_id=robustness_base_evidence_id,
        robustness_base_materialization_id=robustness_base_materialization_id,
        row_count=arrays.row_count,
        candidate_count=arrays.candidate_count,
        feature_interval_evaluation_count=stats.feature_interval_evaluation_count,
        node_series_evaluation_count=stats.node_series_evaluation_count,
        source_slice_row_counts=stats.source_slice_row_counts,
        metric_slice_formation_counts=stats.metric_slice_formation_counts,
        status_counts=tuple(
            (name, int(counts[index])) for index, name in enumerate(_METRIC_STATUS_NAMES)
        ),
        output_filename=output_filename,
        output_size_bytes=output_size_bytes,
        content_sha256=content_sha256,
    )


def parse_us_r2_annual_candidate_robustness_evidence(
    document: Mapping[str, object],
) -> USR2AnnualCandidateRobustnessEvidence:
    evidence = USR2AnnualCandidateRobustnessEvidence(
        plan_id=_text(document.get("plan_id"), "plan_id"),
        year=_integer(document.get("year"), "year"),
        robustness_base_evidence_id=_text(
            document.get("robustness_base_evidence_id"), "robustness_base_evidence_id"
        ),
        robustness_base_materialization_id=_text(
            document.get("robustness_base_materialization_id"),
            "robustness_base_materialization_id",
        ),
        row_count=_integer(document.get("row_count"), "row_count"),
        candidate_count=_integer(document.get("candidate_count"), "candidate_count"),
        feature_interval_evaluation_count=_integer(
            document.get("feature_interval_evaluation_count"), "feature_interval_evaluation_count"
        ),
        node_series_evaluation_count=_integer(
            document.get("node_series_evaluation_count"), "node_series_evaluation_count"
        ),
        source_slice_row_counts=tuple(
            (str(key), _integer(value, f"source_slice_row_counts.{key}"))
            for key, value in sorted(
                _mapping(
                    document.get("source_slice_row_counts"), "source_slice_row_counts"
                ).items()
            )
        ),
        metric_slice_formation_counts=tuple(
            (str(key), _integer(value, f"metric_slice_formation_counts.{key}"))
            for key, value in sorted(
                _mapping(
                    document.get("metric_slice_formation_counts"),
                    "metric_slice_formation_counts",
                ).items()
            )
        ),
        status_counts=tuple(
            (str(key), _integer(value, f"status_counts.{key}"))
            for key, value in sorted(
                _mapping(document.get("status_counts"), "status_counts").items()
            )
        ),
        output_filename=_text(document.get("output_filename"), "output_filename"),
        output_size_bytes=_integer(document.get("output_size_bytes"), "output_size_bytes"),
        content_sha256=_text(document.get("content_sha256"), "content_sha256"),
        blockers=tuple(
            _text(item, "blockers[]") for item in _sequence(document.get("blockers"), "blockers")
        ),
    )
    if dict(document) != evidence.to_dict():
        raise ValueError("US-R2 annual candidate robustness evidence content identity mismatch")
    return evidence


def inspect_completed_us_r2_candidate_robustness_metric(
    *,
    data_path: Path,
    evidence_path: Path,
    plan: USR2CandidateRobustnessPlan,
    expected_year: int,
    expected_base_evidence_id: str,
    expected_base_materialization_id: str,
) -> USR2AnnualCandidateRobustnessEvidence | None:
    data_exists = data_path.is_file()
    evidence_exists = evidence_path.is_file()
    if not data_exists and not evidence_exists:
        return None
    if data_exists != evidence_exists:
        raise ValueError(f"US-R2 candidate robustness annual pair is partial: {expected_year}")
    evidence = parse_us_r2_annual_candidate_robustness_evidence(
        _mapping(json.loads(evidence_path.read_text(encoding="utf-8")), str(evidence_path))
    )
    if evidence.plan_id != plan.plan_id or evidence.year != expected_year or not evidence.passed:
        raise ValueError("US-R2 candidate robustness annual evidence is not admitted")
    if evidence.robustness_base_evidence_id != expected_base_evidence_id:
        raise ValueError("US-R2 candidate robustness annual base evidence changed")
    if evidence.robustness_base_materialization_id != expected_base_materialization_id:
        raise ValueError("US-R2 candidate robustness annual base materialization changed")
    if data_path.stat().st_size != evidence.output_size_bytes:
        raise ValueError("US-R2 candidate robustness annual metric size changed")
    if _sha256_file(data_path) != evidence.content_sha256:
        raise ValueError("US-R2 candidate robustness annual metric content hash changed")
    arrays = load_us_r2_robustness_metric_npz(data_path)
    if arrays.row_count != evidence.row_count or arrays.candidate_count != FROZEN_CANDIDATE_COUNT:
        raise ValueError("US-R2 candidate robustness annual metric shape changed")
    return evidence


@dataclass(frozen=True, slots=True)
class USR2RobustnessMean:
    mean_normalized_rank_ic: float
    period_count: int
    session_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "mean_normalized_rank_ic": self.mean_normalized_rank_ic,
            "period_count": self.period_count,
            "session_count": self.session_count,
        }


@dataclass(frozen=True, slots=True)
class USR2CandidateRegimeRobustness:
    candidate_id: str
    regime: str
    direction: int
    frequency_rank_ic: tuple[tuple[str, USR2RobustnessMean], ...]
    frequency_sign_consistency: float
    frequency_passed: bool
    decay_rank_ic: tuple[tuple[str, USR2RobustnessMean], ...]
    decay_sign_consistency: float
    decay_passed: bool
    blockers: tuple[str, ...] = ()

    @property
    def robustness_passed(self) -> bool:
        return not self.blockers and self.frequency_passed and self.decay_passed

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "regime": self.regime,
            "direction": self.direction,
            "frequency_rank_ic": {key: value.to_dict() for key, value in self.frequency_rank_ic},
            "frequency_sign_consistency": self.frequency_sign_consistency,
            "frequency_passed": self.frequency_passed,
            "decay_rank_ic": {key: value.to_dict() for key, value in self.decay_rank_ic},
            "decay_sign_consistency": self.decay_sign_consistency,
            "decay_passed": self.decay_passed,
            "robustness_passed": self.robustness_passed,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class USR2CandidateRobustnessSummary:
    candidate_id: str
    regime_cells: tuple[USR2CandidateRegimeRobustness, ...]

    @property
    def all_regimes_frequency_passed(self) -> bool:
        return all(item.frequency_passed and not item.blockers for item in self.regime_cells)

    @property
    def all_regimes_decay_passed(self) -> bool:
        return all(item.decay_passed and not item.blockers for item in self.regime_cells)

    @property
    def robustness_passed(self) -> bool:
        return self.all_regimes_frequency_passed and self.all_regimes_decay_passed

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "all_regimes_frequency_passed": self.all_regimes_frequency_passed,
            "all_regimes_decay_passed": self.all_regimes_decay_passed,
            "robustness_passed": self.robustness_passed,
            "regime_cells": [item.to_dict() for item in self.regime_cells],
        }


@dataclass(frozen=True, slots=True)
class USR2CandidateRobustnessReport:
    plan_id: str
    evaluation_policy_id: str
    robustness_base_batch_evidence_id: str
    primary_direction_evidence_id: str
    primary_statistics_report_id: str
    annual_robustness_metric_evidence_ids: tuple[str, ...]
    annual_primary_metric_evidence_ids: tuple[str, ...]
    candidates: tuple[USR2CandidateRobustnessSummary, ...]
    blockers: tuple[str, ...] = ()
    schema_version: str = "finagent.us-r2-candidate-robustness-report.v1"

    @property
    def passed(self) -> bool:
        return (
            not self.blockers
            and len(self.candidates) == FROZEN_CANDIDATE_COUNT
            and all(len(item.regime_cells) == len(FROZEN_REGIME_LABELS) for item in self.candidates)
        )

    @property
    def report_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-candidate-robustness")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "evaluation_policy_id": self.evaluation_policy_id,
            "robustness_base_batch_evidence_id": self.robustness_base_batch_evidence_id,
            "primary_direction_evidence_id": self.primary_direction_evidence_id,
            "primary_statistics_report_id": self.primary_statistics_report_id,
            "candidate_count": len(self.candidates),
            "regime_count": len(FROZEN_REGIME_LABELS),
            "annual_robustness_metric_evidence_ids": list(
                self.annual_robustness_metric_evidence_ids
            ),
            "annual_primary_metric_evidence_ids": list(self.annual_primary_metric_evidence_ids),
            "candidates": [item.to_dict() for item in self.candidates],
            "robustness_passed_candidate_count": sum(
                item.robustness_passed for item in self.candidates
            ),
            "frequency_robustness_evaluated": True,
            "decay_robustness_evaluated": True,
            "direction_refit_applied": False,
            "candidate_selection_applied": False,
            "performance_filter_applied": False,
            "alpha_gate_evaluated": False,
            "terminal_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
            "passed": self.passed,
            "blockers": list(self.blockers),
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


def _pooled_mean(
    arrays: Sequence[USR2AnnualRobustnessMetricArrays],
    *,
    regime_code: int,
    slice_code: int,
    candidate_slot: int,
    direction: int,
) -> USR2RobustnessMean | None:
    values: list[np.ndarray] = []
    sessions: set[int] = set()
    period_count = 0
    for item in arrays:
        mask = (
            (item.regime_codes == regime_code)
            & (item.slice_codes == slice_code)
            & (item.status_codes[:, candidate_slot] == METRIC_AVAILABLE)
        )
        current = item.rank_ic[mask, candidate_slot]
        if current.size:
            values.append(current)
            period_count += int(current.size)
            sessions.update(int(value) for value in item.session_date_days[mask])
    if not values:
        return None
    concatenated = np.concatenate(values)
    return USR2RobustnessMean(
        mean_normalized_rank_ic=direction * float(np.mean(concatenated, dtype=np.float64)),
        period_count=period_count,
        session_count=len(sessions),
    )


def _pooled_primary_mean(
    arrays: Sequence[USR2AnnualPrimaryMetricArrays],
    *,
    regime_code: int,
    candidate_slot: int,
    direction: int,
) -> USR2RobustnessMean | None:
    values: list[np.ndarray] = []
    sessions: set[int] = set()
    period_count = 0
    for item in arrays:
        mask = (
            (item.regime_codes == regime_code)
            & (item.status_codes[:, candidate_slot] == METRIC_AVAILABLE)
        )
        current = item.rank_ic[mask, candidate_slot]
        if current.size:
            values.append(current)
            period_count += int(current.size)
            sessions.update(int(value) for value in item.session_date_days[mask])
    if not values:
        return None
    concatenated = np.concatenate(values)
    return USR2RobustnessMean(
        mean_normalized_rank_ic=direction * float(np.mean(concatenated, dtype=np.float64)),
        period_count=period_count,
        session_count=len(sessions),
    )


def build_us_r2_candidate_robustness_report(
    robustness_arrays: Sequence[USR2AnnualRobustnessMetricArrays],
    primary_arrays: Sequence[USR2AnnualPrimaryMetricArrays],
    *,
    plan: USR2CandidateRobustnessPlan,
    direction_evidence: USR2PrimaryDirectionEvidenceSet,
    annual_robustness_metric_evidence_ids: Sequence[str],
    annual_primary_metric_evidence_ids: Sequence[str],
    policy: USR2StatisticalEvaluationPolicy | None = None,
) -> USR2CandidateRobustnessReport:
    active = policy or canonical_us_r2_statistical_evaluation_policy()
    gate = canonical_us_r1_alpha_gate_policy()
    if len(robustness_arrays) != len(canonical_us_r2_robustness_years()):
        raise ValueError("US-R2 robustness report requires all 21 annual alternative metric caches")
    if len(primary_arrays) != len(canonical_us_r2_robustness_years()):
        raise ValueError("US-R2 robustness report requires all 21 annual primary metric caches")
    if direction_evidence.evidence_id != plan.primary_direction_evidence_id:
        raise ValueError("US-R2 robustness report direction identity mismatch")

    candidates: list[USR2CandidateRobustnessSummary] = []
    report_blockers: list[str] = []
    for slot, candidate_id in enumerate(plan.candidate_ids):
        direction = direction_evidence.direction(candidate_id)
        cells: list[USR2CandidateRegimeRobustness] = []
        for regime_code, regime in _REGIME_LABEL_BY_CODE.items():
            alternate = {
                slice_id: _pooled_mean(
                    robustness_arrays,
                    regime_code=regime_code,
                    slice_code=_SLICE_CODE_BY_ID[slice_id],
                    candidate_slot=slot,
                    direction=direction,
                )
                for slice_id in _SLICE_CODE_BY_ID
            }
            primary = _pooled_primary_mean(
                primary_arrays,
                regime_code=regime_code,
                candidate_slot=slot,
                direction=direction,
            )
            blockers: list[str] = []
            if primary is None:
                blockers.append("primary_15m_60m_rank_ic_unavailable")
            for slice_id, mean in alternate.items():
                if mean is None:
                    blockers.append(f"{slice_id}_rank_ic_unavailable")
            if blockers:
                report_blockers.append(f"{candidate_id}:{regime}:" + ",".join(blockers))
                frequency_items: tuple[tuple[str, USR2RobustnessMean], ...] = ()
                decay_items: tuple[tuple[str, USR2RobustnessMean], ...] = ()
                frequency_fraction = 0.0
                decay_fraction = 0.0
            else:
                if primary is None or any(value is None for value in alternate.values()):
                    raise RuntimeError("robustness mean availability changed after blocker check")
                frequency_items = (
                    ("5m", cast(USR2RobustnessMean, alternate["frequency_5m_60m"])),
                    ("15m", primary),
                    ("30m", cast(USR2RobustnessMean, alternate["frequency_30m_60m"])),
                )
                decay_items = (
                    ("30m", cast(USR2RobustnessMean, alternate["decay_15m_30m"])),
                    ("60m", primary),
                    ("120m", cast(USR2RobustnessMean, alternate["decay_15m_120m"])),
                )
                frequency_fraction = sum(
                    value.mean_normalized_rank_ic > 0.0 for _key, value in frequency_items
                ) / 3.0
                decay_fraction = sum(
                    value.mean_normalized_rank_ic > 0.0 for _key, value in decay_items
                ) / 3.0
            cells.append(
                USR2CandidateRegimeRobustness(
                    candidate_id=candidate_id,
                    regime=regime,
                    direction=direction,
                    frequency_rank_ic=frequency_items,
                    frequency_sign_consistency=frequency_fraction,
                    frequency_passed=(
                        not blockers
                        and frequency_fraction >= gate.min_frequency_sign_consistency
                    ),
                    decay_rank_ic=decay_items,
                    decay_sign_consistency=decay_fraction,
                    decay_passed=(
                        not blockers and decay_fraction >= gate.min_decay_sign_consistency
                    ),
                    blockers=tuple(blockers),
                )
            )
        candidates.append(
            USR2CandidateRobustnessSummary(
                candidate_id=candidate_id,
                regime_cells=tuple(cells),
            )
        )
    return USR2CandidateRobustnessReport(
        plan_id=plan.plan_id,
        evaluation_policy_id=active.policy_id,
        robustness_base_batch_evidence_id=plan.robustness_base_batch_evidence_id,
        primary_direction_evidence_id=direction_evidence.evidence_id,
        primary_statistics_report_id=plan.primary_statistics_report_id,
        annual_robustness_metric_evidence_ids=tuple(annual_robustness_metric_evidence_ids),
        annual_primary_metric_evidence_ids=tuple(annual_primary_metric_evidence_ids),
        candidates=tuple(candidates),
        blockers=tuple(report_blockers),
    )


def validate_us_r2_candidate_denominator_document(
    document: Mapping[str, object],
) -> USR1CandidateDenominator:
    return validate_us_r2_candidate_denominator(document)

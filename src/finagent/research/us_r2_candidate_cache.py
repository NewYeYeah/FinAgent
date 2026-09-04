from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import numpy as np

from finagent.research.us_a1_factor_materialization import (
    CompiledFactorBatch,
    FactorMaterializationUnavailableReason,
    compile_factor_graph_batch,
    materialize_compiled_factor_batch,
)
from finagent.research.us_a1_factor_validation import validate_factor_graph
from finagent.research.us_a1_legacy_graphs import legacy_a0_candidate_factor_graph
from finagent.research.us_baselines import USBaselineBar
from finagent.research.us_r1_handoff import parse_us_r1_candidate_denominator
from finagent.research.us_r1_protocol import USR1CandidateDenominator
from finagent.research.us_r2_base_panel import (
    FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID,
    validate_us_r2_regime_projection_v2_gate,
)
from finagent.research.us_r2_base_panel_batch import (
    USR2BasePanelBatchEvidence,
    USR2CompletedAnnualBasePanel,
    canonical_us_r2_base_panel_years,
)
from finagent.research.us_r2_frozen_protocol import (
    FROZEN_ASSETS,
    FROZEN_CANDIDATE_DENOMINATOR_ID,
    canonical_us_r2_frozen_protocol,
)

FROZEN_BASE_PANEL_BATCH_EVIDENCE_ID = "us-r2-base-panel-batch-4833b15a9cb49649948d7118"
FROZEN_CANDIDATE_COUNT = 37
CANDIDATE_CACHE_FILENAME = "us_r2_candidate_cache.npz"
CANDIDATE_CACHE_EVIDENCE_FILENAME = "us_r2_candidate_cache_evidence.json"
CANDIDATE_CACHE_PLAN_FILENAME = "us_r2_candidate_cache_plan.json"
CANDIDATE_CACHE_BATCH_EVIDENCE_FILENAME = "us_r2_candidate_cache_batch_evidence.json"

_EPOCH_DATE = date(1970, 1, 1)
_EPOCH_DATETIME = datetime(1970, 1, 1, tzinfo=UTC)
_NPZ_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

_REASON_CODE_BY_A1 = {
    FactorMaterializationUnavailableReason.INSUFFICIENT_HISTORY: 1,
    FactorMaterializationUnavailableReason.CROSS_SESSION_WINDOW: 2,
    FactorMaterializationUnavailableReason.INCOMPLETE_BAR: 3,
    FactorMaterializationUnavailableReason.NUMERIC_UNAVAILABLE: 4,
}
_REASON_NAME_BY_CODE = {
    0: "AVAILABLE",
    1: "INSUFFICIENT_HISTORY",
    2: "CROSS_SESSION_WINDOW",
    3: "INCOMPLETE_BAR",
    4: "NUMERIC_UNAVAILABLE",
}
_LABEL_REASON_CODE = {
    None: 0,
    "target_crosses_session": 1,
    "target_minute_missing": 2,
}
_LABEL_REASON_NAME = {
    0: "AVAILABLE",
    1: "TARGET_CROSSES_SESSION",
    2: "TARGET_MINUTE_MISSING",
}


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


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _finite_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    rendered = float(value)
    if not math.isfinite(rendered):
        raise ValueError(f"{field_name} must be finite")
    return rendered


def _aware_datetime(value: object, field_name: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(_text(value, field_name))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _date_value(value: object, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(_text(value, field_name))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _datetime_to_us(value: datetime) -> int:
    delta = value.astimezone(UTC) - _EPOCH_DATETIME
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def _date_to_days(value: date) -> int:
    return (value - _EPOCH_DATE).days


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def validate_us_r2_base_panel_batch_gate(
    document: Mapping[str, object],
    *,
    expected_evidence_id: str = FROZEN_BASE_PANEL_BATCH_EVIDENCE_ID,
) -> USR2BasePanelBatchEvidence:
    """Reconstruct and content-validate the completed 2001-2026 base-panel batch."""

    requested = tuple(
        _integer(item, "requested_years[]")
        for item in _sequence(document.get("requested_years"), "requested_years")
    )
    if requested != canonical_us_r2_base_panel_years():
        raise ValueError("US-R2 candidate cache requires the complete frozen 2001-2026 base-panel batch")
    completed = tuple(
        _integer(item, "completed_years[]")
        for item in _sequence(document.get("completed_years"), "completed_years")
    )
    if completed != requested:
        raise ValueError("US-R2 base-panel batch completed years differ from the frozen request")

    annual_panels: list[USR2CompletedAnnualBasePanel] = []
    for index, raw in enumerate(_sequence(document.get("annual_panels"), "annual_panels")):
        item = _mapping(raw, f"annual_panels[{index}]")
        annual = USR2CompletedAnnualBasePanel(
            year=_integer(item.get("year"), "annual.year"),
            plan_id=_text(item.get("plan_id"), "annual.plan_id"),
            evidence_id=_text(item.get("evidence_id"), "annual.evidence_id"),
            materialization_id=_text(item.get("materialization_id"), "annual.materialization_id"),
            data_version=_text(item.get("data_version"), "annual.data_version"),
            row_count=_integer(item.get("row_count"), "annual.row_count"),
            asset_count=_integer(item.get("asset_count"), "annual.asset_count"),
            formation_count=_integer(item.get("formation_count"), "annual.formation_count"),
            formation_count_at_minimum_cross_section=_integer(
                item.get("formation_count_at_minimum_cross_section"),
                "annual.formation_count_at_minimum_cross_section",
            ),
            minimum_joint_breadth=_integer(
                item.get("minimum_joint_breadth"), "annual.minimum_joint_breadth"
            ),
            maximum_joint_breadth=_integer(
                item.get("maximum_joint_breadth"), "annual.maximum_joint_breadth"
            ),
            data_size_bytes=_integer(item.get("data_size_bytes"), "annual.data_size_bytes"),
        )
        if dict(item) != annual.to_dict():
            raise ValueError(f"US-R2 annual batch record content mismatch for {annual.year}")
        annual_panels.append(annual)

    evidence = USR2BasePanelBatchEvidence(
        requested_years=requested,
        annual_panels=tuple(annual_panels),
        blockers=tuple(
            _text(item, "blockers[]") for item in _sequence(document.get("blockers"), "blockers")
        ),
    )
    if dict(document) != evidence.to_dict():
        raise ValueError("US-R2 base-panel batch content-addressed document mismatch")
    if evidence.evidence_id != expected_evidence_id:
        raise ValueError("US-R2 base-panel batch evidence identity differs from the reviewed operator run")
    if not evidence.passed:
        raise ValueError("US-R2 candidate cache requires passed base-panel batch evidence")
    if document.get("candidate_dependent_scan") is not False:
        raise ValueError("US-R2 base-panel batch became candidate dependent")
    if document.get("candidate_performance_read") is not False:
        raise ValueError("US-R2 base-panel batch read candidate performance")
    return evidence


def validate_us_r2_candidate_denominator(
    document: Mapping[str, object],
) -> USR1CandidateDenominator:
    denominator = parse_us_r1_candidate_denominator(document)
    if denominator.denominator_id != FROZEN_CANDIDATE_DENOMINATOR_ID:
        raise ValueError("US-R2 candidate cache requires the exact frozen R1 denominator")
    if len(denominator.candidates) != FROZEN_CANDIDATE_COUNT:
        raise ValueError("US-R2 candidate cache requires exactly 37 frozen R1 candidates")
    if document.get("performance_filter_applied") is not False:
        raise ValueError("US-R2 cannot admit a performance-filtered candidate denominator")
    return denominator


@dataclass(frozen=True, slots=True)
class USR2CandidateBinding:
    slot: int
    r1_candidate_id: str
    structural_key: str
    feature_spec_id: str
    a1_candidate_id: str
    root_execution_id: str
    schema_version: str = "finagent.us-r2-candidate-binding.v1"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "slot": self.slot,
            "r1_candidate_id": self.r1_candidate_id,
            "structural_key": self.structural_key,
            "feature_spec_id": self.feature_spec_id,
            "a1_candidate_id": self.a1_candidate_id,
            "root_execution_id": self.root_execution_id,
        }


@dataclass(frozen=True, slots=True)
class USR2CandidateExecution:
    compiled: CompiledFactorBatch
    bindings: tuple[USR2CandidateBinding, ...]

    def __post_init__(self) -> None:
        if len(self.bindings) != len(self.compiled.roots):
            raise ValueError("US-R2 candidate binding/root count mismatch")
        r1_ids = tuple(item.r1_candidate_id for item in self.bindings)
        a1_ids = tuple(item.a1_candidate_id for item in self.bindings)
        if len(r1_ids) != len(set(r1_ids)) or len(a1_ids) != len(set(a1_ids)):
            raise ValueError("US-R2 candidate execution contains duplicate identities")


def compile_us_r2_candidate_execution(
    denominator: USR1CandidateDenominator,
) -> USR2CandidateExecution:
    graphs = tuple(
        legacy_a0_candidate_factor_graph(item.candidate).graph for item in denominator.candidates
    )
    compiled = compile_factor_graph_batch(graphs)
    root_by_a1 = {item.candidate_id: item for item in compiled.roots}
    bindings: list[USR2CandidateBinding] = []
    for slot, provenance in enumerate(denominator.candidates):
        candidate = provenance.candidate
        legacy = legacy_a0_candidate_factor_graph(candidate)
        graph_evidence = validate_factor_graph(legacy.graph)
        if not graph_evidence.valid or graph_evidence.canonicalization is None:
            raise RuntimeError("frozen R1 candidate failed A1 canonical validation")
        a1_candidate_id = graph_evidence.canonicalization.candidate_id
        root = root_by_a1.get(a1_candidate_id)
        if root is None:
            raise RuntimeError("compiled shared DAG lost a frozen R1 candidate root")
        bindings.append(
            USR2CandidateBinding(
                slot=slot,
                r1_candidate_id=candidate.candidate_id,
                structural_key=candidate.structural_key,
                feature_spec_id=candidate.compile_feature_spec().spec_id,
                a1_candidate_id=a1_candidate_id,
                root_execution_id=root.root_execution_id,
            )
        )
    return USR2CandidateExecution(compiled=compiled, bindings=tuple(bindings))


@dataclass(frozen=True, slots=True)
class USR2CandidateCachePlan:
    frozen_protocol_id: str
    denominator_id: str
    base_panel_batch_evidence_id: str
    regime_projection_evidence_id: str
    compiled_batch_id: str
    bindings: tuple[USR2CandidateBinding, ...]
    naive_node_count: int
    unique_node_count: int
    reused_node_count: int
    schema_version: str = "finagent.us-r2-candidate-cache-plan.v1"

    @property
    def plan_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-candidate-cache-plan")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "frozen_protocol_id": self.frozen_protocol_id,
            "denominator_id": self.denominator_id,
            "candidate_count": len(self.bindings),
            "base_panel_batch_evidence_id": self.base_panel_batch_evidence_id,
            "regime_projection_evidence_id": self.regime_projection_evidence_id,
            "compiled_batch_id": self.compiled_batch_id,
            "bindings": [item.to_dict() for item in self.bindings],
            "naive_node_count": self.naive_node_count,
            "unique_node_count": self.unique_node_count,
            "reused_node_count": self.reused_node_count,
            "execution_model": "a1_shared_canonical_subexpression_dag",
            "cache_layout": "annual_formation_wide_matrix_n_by_37",
            "candidate_value_dtype": "float64",
            "candidate_reason_dtype": "uint8",
            "npz_encoding": "zip_stored_fixed_timestamp_deterministic_v1",
            "base_parquet_scan_relation_count_per_year": 1,
            "candidate_dependent_scan": False,
            "candidate_performance_read": False,
            "raw_minute_source_access": False,
            "raw_minute_fallback_allowed": False,
            "regime_application": (
                "identity_gate_only_candidate_values_remain_regime_agnostic_until_statistical_evaluation"
            ),
            "performance_filter_applied": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["plan_id"] = self.plan_id
        return payload


def build_us_r2_candidate_cache_plan(
    denominator: USR1CandidateDenominator,
    *,
    base_panel_batch_evidence_id: str,
    regime_projection_evidence_id: str,
) -> tuple[USR2CandidateCachePlan, USR2CandidateExecution]:
    if denominator.denominator_id != FROZEN_CANDIDATE_DENOMINATOR_ID:
        raise ValueError("US-R2 cache plan cannot bind a non-frozen denominator")
    if len(denominator.candidates) != FROZEN_CANDIDATE_COUNT:
        raise ValueError("US-R2 cache plan requires the complete 37-candidate denominator")
    if base_panel_batch_evidence_id != FROZEN_BASE_PANEL_BATCH_EVIDENCE_ID:
        raise ValueError("US-R2 cache plan requires the reviewed complete base-panel batch")
    if regime_projection_evidence_id != FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID:
        raise ValueError("US-R2 cache plan requires the reviewed regime-v2 evidence")
    execution = compile_us_r2_candidate_execution(denominator)
    plan = USR2CandidateCachePlan(
        frozen_protocol_id=canonical_us_r2_frozen_protocol().freeze_id,
        denominator_id=denominator.denominator_id,
        base_panel_batch_evidence_id=base_panel_batch_evidence_id,
        regime_projection_evidence_id=regime_projection_evidence_id,
        compiled_batch_id=execution.compiled.batch_id,
        bindings=execution.bindings,
        naive_node_count=execution.compiled.naive_node_count,
        unique_node_count=execution.compiled.unique_node_count,
        reused_node_count=execution.compiled.reused_node_count,
    )
    return plan, execution


@dataclass(frozen=True, slots=True)
class _ParsedBaseRow:
    session_date: date
    bar: USBaselineBar
    label_available: bool
    label_value: float | None
    label_available_at: datetime | None
    label_reason: str | None


@dataclass(frozen=True, slots=True)
class USR2AssetCandidateCache:
    asset: str
    session_date_days: np.ndarray
    event_time_us: np.ndarray
    available_at_us: np.ndarray
    label_values: np.ndarray
    label_available: np.ndarray
    label_available_at_us: np.ndarray
    label_reason_codes: np.ndarray
    candidate_values: np.ndarray
    candidate_reason_codes: np.ndarray

    @property
    def row_count(self) -> int:
        return int(self.candidate_values.shape[0])

    def __post_init__(self) -> None:
        rows = self.candidate_values.shape[0]
        if self.candidate_values.ndim != 2 or self.candidate_reason_codes.shape != (
            rows,
            self.candidate_values.shape[1],
        ):
            raise ValueError("US-R2 candidate value/reason matrix shape mismatch")
        for array in (
            self.session_date_days,
            self.event_time_us,
            self.available_at_us,
            self.label_values,
            self.label_available,
            self.label_available_at_us,
            self.label_reason_codes,
        ):
            if array.shape != (rows,):
                raise ValueError("US-R2 candidate cache metadata arrays must align with rows")
        finite = np.isfinite(self.candidate_values)
        if not np.array_equal(self.candidate_reason_codes == 0, finite):
            raise ValueError("US-R2 candidate availability codes must match finite values")


def _parse_asset_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    expected_asset: str,
) -> tuple[_ParsedBaseRow, ...]:
    parsed: list[_ParsedBaseRow] = []
    for index, raw in enumerate(rows):
        asset = _text(raw.get("research_asset_id"), f"rows[{index}].research_asset_id")
        if asset != expected_asset:
            raise ValueError("US-R2 asset cache input mixes research assets")
        event_time = _aware_datetime(raw.get("event_time"), f"rows[{index}].event_time")
        available_at = _aware_datetime(raw.get("available_at"), f"rows[{index}].available_at")
        bar = USBaselineBar(
            event_time=event_time,
            available_at=available_at,
            session_id=_text(raw.get("session_id"), f"rows[{index}].session_id"),
            open=_finite_float(raw.get("open"), f"rows[{index}].open"),
            high=_finite_float(raw.get("high"), f"rows[{index}].high"),
            low=_finite_float(raw.get("low"), f"rows[{index}].low"),
            close=_finite_float(raw.get("close"), f"rows[{index}].close"),
            volume=_finite_float(raw.get("volume"), f"rows[{index}].volume"),
            is_complete=_boolean(raw.get("is_complete"), f"rows[{index}].is_complete"),
        )
        label_available = _boolean(
            raw.get("label_available"), f"rows[{index}].label_available"
        )
        if label_available:
            label_value = _finite_float(raw.get("label_value"), f"rows[{index}].label_value")
            label_available_at = _aware_datetime(
                raw.get("target_available_at"), f"rows[{index}].target_available_at"
            )
            label_reason = None
        else:
            label_value = None
            label_available_at = None
            label_reason = _text(
                raw.get("unavailable_reason"), f"rows[{index}].unavailable_reason"
            )
            if label_reason not in _LABEL_REASON_CODE:
                raise ValueError("US-R2 candidate cache encountered unsupported label unavailability")
        parsed.append(
            _ParsedBaseRow(
                session_date=_date_value(raw.get("session_date"), f"rows[{index}].session_date"),
                bar=bar,
                label_available=label_available,
                label_value=label_value,
                label_available_at=label_available_at,
                label_reason=label_reason,
            )
        )
    return tuple(parsed)


def materialize_us_r2_asset_candidate_cache(
    rows: Sequence[Mapping[str, object]],
    execution: USR2CandidateExecution,
    *,
    expected_asset: str,
) -> USR2AssetCandidateCache:
    if not rows:
        raise ValueError("US-R2 asset candidate materialization requires source rows")
    parsed = _parse_asset_rows(rows, expected_asset=expected_asset)
    bars = tuple(item.bar for item in parsed)
    materialized = materialize_compiled_factor_batch(execution.compiled, bars)
    series_by_a1 = {item.candidate_id: item for item in materialized.candidates}

    session_days: list[int] = []
    event_us: list[int] = []
    available_us: list[int] = []
    label_values: list[float] = []
    label_available: list[bool] = []
    label_available_at_us: list[int] = []
    label_reason_codes: list[int] = []
    candidate_values: list[list[float]] = []
    candidate_reasons: list[list[int]] = []

    for index, item in enumerate(parsed):
        bar = item.bar
        if not bar.is_complete:
            continue
        raw = rows[index]
        if not _boolean(raw.get("label_row_present"), f"rows[{index}].label_row_present"):
            raise ValueError("US-R2 candidate cache found a complete bar without label anchor row")
        source_available_at = _aware_datetime(
            raw.get("source_available_at"), f"rows[{index}].source_available_at"
        )
        if source_available_at != bar.available_at:
            raise ValueError("US-R2 candidate cache label source clock differs from formation clock")
        source_price = _finite_float(raw.get("source_price"), f"rows[{index}].source_price")
        if abs(source_price - bar.close) > max(1e-12, abs(bar.close) * 1e-12):
            raise ValueError("US-R2 candidate cache label close anchor differs from feature close")

        values_row: list[float] = []
        reasons_row: list[int] = []
        for binding in execution.bindings:
            series = series_by_a1[binding.a1_candidate_id]
            value = series.values[index]
            reason = series.unavailable_reasons[index]
            if value is None:
                if reason is None:
                    raise RuntimeError("A1 shared DAG returned unavailable value without reason")
                values_row.append(float("nan"))
                reasons_row.append(_REASON_CODE_BY_A1[reason])
            else:
                if reason is not None:
                    raise RuntimeError("A1 shared DAG returned value with unavailable reason")
                values_row.append(float(value))
                reasons_row.append(0)

        session_days.append(_date_to_days(item.session_date))
        event_us.append(_datetime_to_us(bar.event_time))
        available_us.append(_datetime_to_us(bar.available_at))
        label_available.append(item.label_available)
        if item.label_available:
            if item.label_value is None or item.label_available_at is None:
                raise RuntimeError("available label lost value or clock during candidate cache assembly")
            label_values.append(item.label_value)
            label_available_at_us.append(_datetime_to_us(item.label_available_at))
            label_reason_codes.append(0)
        else:
            label_values.append(float("nan"))
            label_available_at_us.append(-1)
            label_reason_codes.append(_LABEL_REASON_CODE[item.label_reason])
        candidate_values.append(values_row)
        candidate_reasons.append(reasons_row)

    candidate_count = len(execution.bindings)
    return USR2AssetCandidateCache(
        asset=expected_asset,
        session_date_days=np.asarray(session_days, dtype=np.int32),
        event_time_us=np.asarray(event_us, dtype=np.int64),
        available_at_us=np.asarray(available_us, dtype=np.int64),
        label_values=np.asarray(label_values, dtype=np.float64),
        label_available=np.asarray(label_available, dtype=np.bool_),
        label_available_at_us=np.asarray(label_available_at_us, dtype=np.int64),
        label_reason_codes=np.asarray(label_reason_codes, dtype=np.uint8),
        candidate_values=(
            np.asarray(candidate_values, dtype=np.float64).reshape((-1, candidate_count))
            if candidate_values
            else np.empty((0, candidate_count), dtype=np.float64)
        ),
        candidate_reason_codes=(
            np.asarray(candidate_reasons, dtype=np.uint8).reshape((-1, candidate_count))
            if candidate_reasons
            else np.empty((0, candidate_count), dtype=np.uint8)
        ),
    )


@dataclass(frozen=True, slots=True)
class USR2AnnualCandidateCacheArrays:
    asset_codes: np.ndarray
    session_date_days: np.ndarray
    event_time_us: np.ndarray
    available_at_us: np.ndarray
    label_values: np.ndarray
    label_available: np.ndarray
    label_available_at_us: np.ndarray
    label_reason_codes: np.ndarray
    candidate_values: np.ndarray
    candidate_reason_codes: np.ndarray

    @property
    def row_count(self) -> int:
        return int(self.candidate_values.shape[0])

    @property
    def candidate_count(self) -> int:
        return int(self.candidate_values.shape[1])

    def as_npz_arrays(self) -> dict[str, np.ndarray]:
        return {
            "asset_codes": self.asset_codes,
            "session_date_days": self.session_date_days,
            "event_time_us": self.event_time_us,
            "available_at_us": self.available_at_us,
            "label_values": self.label_values,
            "label_available": self.label_available,
            "label_available_at_us": self.label_available_at_us,
            "label_reason_codes": self.label_reason_codes,
            "candidate_values": self.candidate_values,
            "candidate_reason_codes": self.candidate_reason_codes,
        }


def combine_us_r2_asset_candidate_caches(
    caches: Sequence[USR2AssetCandidateCache],
    *,
    candidate_count: int,
) -> USR2AnnualCandidateCacheArrays:
    if not caches:
        raise ValueError("US-R2 annual candidate cache requires at least one observed asset")
    asset_code_by_name = {asset: index for index, asset in enumerate(FROZEN_ASSETS)}
    if len({item.asset for item in caches}) != len(caches):
        raise ValueError("US-R2 annual candidate cache repeats an asset")
    for cache in caches:
        if cache.asset not in asset_code_by_name:
            raise ValueError("US-R2 annual candidate cache contains asset outside frozen universe")
        if cache.candidate_values.shape[1] != candidate_count:
            raise ValueError("US-R2 annual asset cache candidate width mismatch")

    asset_codes = np.concatenate(
        [np.full(item.row_count, asset_code_by_name[item.asset], dtype=np.uint8) for item in caches]
    )
    arrays = USR2AnnualCandidateCacheArrays(
        asset_codes=asset_codes,
        session_date_days=np.concatenate([item.session_date_days for item in caches]),
        event_time_us=np.concatenate([item.event_time_us for item in caches]),
        available_at_us=np.concatenate([item.available_at_us for item in caches]),
        label_values=np.concatenate([item.label_values for item in caches]),
        label_available=np.concatenate([item.label_available for item in caches]),
        label_available_at_us=np.concatenate([item.label_available_at_us for item in caches]),
        label_reason_codes=np.concatenate([item.label_reason_codes for item in caches]),
        candidate_values=np.concatenate([item.candidate_values for item in caches], axis=0),
        candidate_reason_codes=np.concatenate(
            [item.candidate_reason_codes for item in caches], axis=0
        ),
    )
    order = np.lexsort((arrays.asset_codes, arrays.available_at_us))
    return USR2AnnualCandidateCacheArrays(
        asset_codes=arrays.asset_codes[order],
        session_date_days=arrays.session_date_days[order],
        event_time_us=arrays.event_time_us[order],
        available_at_us=arrays.available_at_us[order],
        label_values=arrays.label_values[order],
        label_available=arrays.label_available[order],
        label_available_at_us=arrays.label_available_at_us[order],
        label_reason_codes=arrays.label_reason_codes[order],
        candidate_values=arrays.candidate_values[order, :],
        candidate_reason_codes=arrays.candidate_reason_codes[order, :],
    )


def write_deterministic_us_r2_candidate_npz(
    path: Path,
    arrays: USR2AnnualCandidateCacheArrays,
) -> tuple[str, int]:
    target = path.expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"US-R2 candidate cache output is immutable: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, mode="x", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for name, array in sorted(arrays.as_npz_arrays().items()):
            buffer = io.BytesIO()
            np.lib.format.write_array(buffer, np.ascontiguousarray(array), allow_pickle=False)
            info = zipfile.ZipInfo(filename=f"{name}.npy", date_time=_NPZ_TIMESTAMP)
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, buffer.getvalue())
    return _sha256_file(target), target.stat().st_size


def load_us_r2_candidate_npz(
    path: Path,
    *,
    candidate_count: int,
) -> USR2AnnualCandidateCacheArrays:
    target = path.expanduser().resolve()
    with np.load(target, allow_pickle=False) as archive:
        required = {
            "asset_codes",
            "session_date_days",
            "event_time_us",
            "available_at_us",
            "label_values",
            "label_available",
            "label_available_at_us",
            "label_reason_codes",
            "candidate_values",
            "candidate_reason_codes",
        }
        if set(archive.files) != required:
            raise ValueError("US-R2 candidate cache NPZ field set mismatch")
        arrays = USR2AnnualCandidateCacheArrays(
            asset_codes=np.asarray(archive["asset_codes"], dtype=np.uint8),
            session_date_days=np.asarray(archive["session_date_days"], dtype=np.int32),
            event_time_us=np.asarray(archive["event_time_us"], dtype=np.int64),
            available_at_us=np.asarray(archive["available_at_us"], dtype=np.int64),
            label_values=np.asarray(archive["label_values"], dtype=np.float64),
            label_available=np.asarray(archive["label_available"], dtype=np.bool_),
            label_available_at_us=np.asarray(archive["label_available_at_us"], dtype=np.int64),
            label_reason_codes=np.asarray(archive["label_reason_codes"], dtype=np.uint8),
            candidate_values=np.asarray(archive["candidate_values"], dtype=np.float64),
            candidate_reason_codes=np.asarray(
                archive["candidate_reason_codes"], dtype=np.uint8
            ),
        )
    rows = arrays.row_count
    if arrays.candidate_count != candidate_count:
        raise ValueError("US-R2 candidate cache NPZ candidate width mismatch")
    for name, array in arrays.as_npz_arrays().items():
        if name in {"candidate_values", "candidate_reason_codes"}:
            if array.shape[0] != rows:
                raise ValueError("US-R2 candidate cache matrix row count mismatch")
        elif array.shape != (rows,):
            raise ValueError("US-R2 candidate cache metadata row count mismatch")
    if np.any(arrays.asset_codes >= len(FROZEN_ASSETS)):
        raise ValueError("US-R2 candidate cache contains invalid asset code")
    if not np.array_equal(arrays.candidate_reason_codes == 0, np.isfinite(arrays.candidate_values)):
        raise ValueError("US-R2 candidate cache value/reason availability mismatch")
    return arrays


@dataclass(frozen=True, slots=True)
class USR2AnnualCandidateCacheEvidence:
    plan_id: str
    year: int
    source_annual_evidence_id: str
    source_data_version: str
    candidate_count: int
    row_count: int
    available_candidate_value_count: int
    candidate_reason_counts: tuple[tuple[str, int], ...]
    label_available_count: int
    label_reason_counts: tuple[tuple[str, int], ...]
    output_filename: str
    output_size_bytes: int
    content_sha256: str
    blockers: tuple[str, ...] = ()
    schema_version: str = "finagent.us-r2-candidate-cache-evidence.v1"

    @property
    def passed(self) -> bool:
        return not self.blockers and self.row_count > 0 and self.candidate_count == FROZEN_CANDIDATE_COUNT

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-candidate-cache")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "year": self.year,
            "source_annual_evidence_id": self.source_annual_evidence_id,
            "source_data_version": self.source_data_version,
            "candidate_count": self.candidate_count,
            "row_count": self.row_count,
            "available_candidate_value_count": self.available_candidate_value_count,
            "candidate_reason_counts": dict(self.candidate_reason_counts),
            "label_available_count": self.label_available_count,
            "label_reason_counts": dict(self.label_reason_counts),
            "output_filename": self.output_filename,
            "output_size_bytes": self.output_size_bytes,
            "content_sha256": self.content_sha256,
            "blockers": list(self.blockers),
            "passed": self.passed,
            "source_kind": "annual_base_parquet_only",
            "candidate_dependent_scan": False,
            "candidate_performance_read": False,
            "raw_minute_source_access": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "order_authority": False,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


def build_us_r2_annual_candidate_cache_evidence(
    *,
    plan: USR2CandidateCachePlan,
    year: int,
    source_annual: USR2CompletedAnnualBasePanel,
    arrays: USR2AnnualCandidateCacheArrays,
    output_path: Path,
    content_sha256: str,
    output_size_bytes: int,
) -> USR2AnnualCandidateCacheEvidence:
    reason_counts = np.bincount(arrays.candidate_reason_codes.ravel(), minlength=5)
    label_reason_counts = np.bincount(arrays.label_reason_codes, minlength=3)
    finite_count = int(np.isfinite(arrays.candidate_values).sum())
    return USR2AnnualCandidateCacheEvidence(
        plan_id=plan.plan_id,
        year=year,
        source_annual_evidence_id=source_annual.evidence_id,
        source_data_version=source_annual.data_version,
        candidate_count=arrays.candidate_count,
        row_count=arrays.row_count,
        available_candidate_value_count=finite_count,
        candidate_reason_counts=tuple(
            (_REASON_NAME_BY_CODE[index], int(reason_counts[index])) for index in range(5)
        ),
        label_available_count=int(arrays.label_available.sum()),
        label_reason_counts=tuple(
            (_LABEL_REASON_NAME[index], int(label_reason_counts[index])) for index in range(3)
        ),
        output_filename=output_path.name,
        output_size_bytes=output_size_bytes,
        content_sha256=content_sha256,
    )


def parse_us_r2_annual_candidate_cache_evidence(
    document: Mapping[str, object],
) -> USR2AnnualCandidateCacheEvidence:
    candidate_reasons_map = _mapping(document.get("candidate_reason_counts"), "candidate_reason_counts")
    label_reasons_map = _mapping(document.get("label_reason_counts"), "label_reason_counts")
    evidence = USR2AnnualCandidateCacheEvidence(
        plan_id=_text(document.get("plan_id"), "plan_id"),
        year=_integer(document.get("year"), "year"),
        source_annual_evidence_id=_text(
            document.get("source_annual_evidence_id"), "source_annual_evidence_id"
        ),
        source_data_version=_text(document.get("source_data_version"), "source_data_version"),
        candidate_count=_integer(document.get("candidate_count"), "candidate_count"),
        row_count=_integer(document.get("row_count"), "row_count"),
        available_candidate_value_count=_integer(
            document.get("available_candidate_value_count"), "available_candidate_value_count"
        ),
        candidate_reason_counts=tuple(
            (name, _integer(candidate_reasons_map.get(name), f"candidate_reason_counts.{name}"))
            for name in _REASON_NAME_BY_CODE.values()
        ),
        label_available_count=_integer(
            document.get("label_available_count"), "label_available_count"
        ),
        label_reason_counts=tuple(
            (name, _integer(label_reasons_map.get(name), f"label_reason_counts.{name}"))
            for name in _LABEL_REASON_NAME.values()
        ),
        output_filename=_text(document.get("output_filename"), "output_filename"),
        output_size_bytes=_integer(document.get("output_size_bytes"), "output_size_bytes"),
        content_sha256=_text(document.get("content_sha256"), "content_sha256"),
        blockers=tuple(
            _text(item, "blockers[]") for item in _sequence(document.get("blockers"), "blockers")
        ),
    )
    if dict(document) != evidence.to_dict():
        raise ValueError("US-R2 annual candidate cache evidence content identity mismatch")
    return evidence


def inspect_completed_us_r2_candidate_cache(
    *,
    data_path: Path,
    evidence_path: Path,
    plan: USR2CandidateCachePlan,
    source_annual: USR2CompletedAnnualBasePanel,
) -> USR2AnnualCandidateCacheEvidence | None:
    data_exists = data_path.is_file()
    evidence_exists = evidence_path.is_file()
    if not data_exists and not evidence_exists:
        return None
    if data_exists != evidence_exists:
        raise ValueError(f"US-R2 candidate cache is partial for {source_annual.year}")
    raw: object = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence = parse_us_r2_annual_candidate_cache_evidence(
        _mapping(raw, str(evidence_path))
    )
    if evidence.plan_id != plan.plan_id:
        raise ValueError("US-R2 candidate cache evidence/plan identity mismatch")
    if evidence.year != source_annual.year:
        raise ValueError("US-R2 candidate cache evidence year mismatch")
    if evidence.source_annual_evidence_id != source_annual.evidence_id:
        raise ValueError("US-R2 candidate cache source annual evidence mismatch")
    if evidence.source_data_version != source_annual.data_version:
        raise ValueError("US-R2 candidate cache source data version mismatch")
    if evidence.output_filename != data_path.name:
        raise ValueError("US-R2 candidate cache output filename mismatch")
    if data_path.stat().st_size != evidence.output_size_bytes:
        raise ValueError("US-R2 candidate cache output size mismatch")
    if _sha256_file(data_path) != evidence.content_sha256:
        raise ValueError("US-R2 candidate cache output content hash mismatch")
    if not evidence.passed:
        raise ValueError("US-R2 completed candidate cache evidence is not passed")
    return evidence


@dataclass(frozen=True, slots=True)
class USR2CandidateCacheBatchEvidence:
    plan_id: str
    requested_years: tuple[int, ...]
    annual_evidence: tuple[USR2AnnualCandidateCacheEvidence, ...]
    blockers: tuple[str, ...] = ()
    schema_version: str = "finagent.us-r2-candidate-cache-batch-evidence.v1"

    @property
    def passed(self) -> bool:
        return (
            not self.blockers
            and tuple(item.year for item in self.annual_evidence) == self.requested_years
            and all(item.passed for item in self.annual_evidence)
        )

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-candidate-cache-batch")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "requested_years": list(self.requested_years),
            "completed_years": [item.year for item in self.annual_evidence],
            "annual_evidence_ids": [item.evidence_id for item in self.annual_evidence],
            "total_row_count": sum(item.row_count for item in self.annual_evidence),
            "candidate_count": FROZEN_CANDIDATE_COUNT,
            "blockers": list(self.blockers),
            "passed": self.passed,
            "base_panel_batch_evidence_id": FROZEN_BASE_PANEL_BATCH_EVIDENCE_ID,
            "denominator_id": FROZEN_CANDIDATE_DENOMINATOR_ID,
            "regime_projection_evidence_id": FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID,
            "candidate_dependent_scan": False,
            "candidate_performance_read": False,
            "raw_minute_source_access": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "order_authority": False,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


def validate_us_r2_regime_gate(document: Mapping[str, object]) -> str:
    return validate_us_r2_regime_projection_v2_gate(document)

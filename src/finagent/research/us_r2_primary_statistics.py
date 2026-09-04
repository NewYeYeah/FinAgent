from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

import numpy as np

from finagent.research.us_r1_evaluation_policy import canonical_us_r1_statistical_evaluation_policy
from finagent.research.us_r1_inference import rank_icir
from finagent.research.us_r1_protocol import USR1CandidateDenominator
from finagent.research.us_r2_candidate_cache import (
    CANDIDATE_CACHE_FILENAME,
    FROZEN_CANDIDATE_COUNT,
    USR2AnnualCandidateCacheArrays,
    USR2AnnualCandidateCacheEvidence,
    USR2CandidateCachePlan,
    build_us_r2_candidate_cache_plan,
    load_us_r2_candidate_npz,
    parse_us_r2_annual_candidate_cache_evidence,
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

FROZEN_CANDIDATE_CACHE_BATCH_EVIDENCE_ID = (
    "us-r2-candidate-cache-batch-7e6c9d5406cc1c444c4fd5ca"
)
FROZEN_CANDIDATE_CACHE_PLAN_ID = "us-r2-candidate-cache-plan-6028ce9e260a383b13aba78c"
FROZEN_COMPILED_CANDIDATE_BATCH_ID = "us-a1-compiled-factor-batch-e2f0f128d916bfaaf0dafeb0"
FROZEN_CANDIDATE_CACHE_TOTAL_ROWS = 2_896_731
PRIMARY_DIRECTION_FILENAME = "us_r2_primary_direction_evidence.json"
PRIMARY_POLICY_FILENAME = "us_r2_statistical_evaluation_policy.json"
PRIMARY_PLAN_FILENAME = "us_r2_primary_statistics_plan.json"
PRIMARY_METRIC_FILENAME = "us_r2_primary_period_metrics.npz"
PRIMARY_METRIC_EVIDENCE_FILENAME = "us_r2_primary_period_metrics_evidence.json"
PRIMARY_STATISTICS_REPORT_FILENAME = "us_r2_primary_statistics_report.json"

_EPOCH_DATE = date(1970, 1, 1)
_EPOCH_DATETIME = datetime(1970, 1, 1, tzinfo=UTC)
_NPZ_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

METRIC_AVAILABLE = 0
METRIC_PARTIAL_LABEL_OMITTED = 1
METRIC_INSUFFICIENT_CROSS_SECTION = 2
METRIC_BOUNDARY_UNREALIZED = 3
METRIC_UNCLASSIFIED_MISSING_LABEL = 4
METRIC_RANK_IC_UNDEFINED = 5
_METRIC_STATUS_NAMES = (
    "AVAILABLE",
    "PARTIAL_LABEL_OMITTED",
    "INSUFFICIENT_CROSS_SECTION",
    "BOUNDARY_UNREALIZED",
    "UNCLASSIFIED_MISSING_LABEL",
    "RANK_IC_UNDEFINED",
)

_REGIME_CODE_BY_LABEL = {label: index for index, label in enumerate(FROZEN_REGIME_LABELS)}
_REGIME_LABEL_BY_CODE = {value: key for key, value in _REGIME_CODE_BY_LABEL.items()}


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


def _finite(value: float, field_name: str) -> float:
    rendered = float(value)
    if not math.isfinite(rendered):
        raise ValueError(f"{field_name} must be finite")
    return rendered


def _date_value(value: object, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(_text(value, field_name))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _date_to_days(value: date) -> int:
    return (value - _EPOCH_DATE).days


def _days_to_date(value: int) -> date:
    return _EPOCH_DATE + timedelta(days=int(value))


def _us_to_datetime(value: int) -> datetime:
    return _EPOCH_DATETIME + timedelta(microseconds=int(value))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _rehash_document(document: Mapping[str, object], *, id_field: str, prefix: str) -> str:
    claimed = _text(document.get(id_field), id_field)
    payload = dict(document)
    del payload[id_field]
    if claimed != _canonical_hash(payload, prefix=prefix):
        raise ValueError(f"{id_field} content-addressed identity mismatch")
    return claimed


@dataclass(frozen=True, slots=True)
class USR2CandidateCacheBatchGate:
    evidence_id: str
    plan_id: str
    requested_years: tuple[int, ...]
    annual_evidence_ids: tuple[str, ...]
    total_row_count: int


def validate_us_r2_candidate_cache_batch_gate(
    batch_document: Mapping[str, object],
) -> USR2CandidateCacheBatchGate:
    if _text(batch_document.get("schema_version"), "schema_version") != (
        "finagent.us-r2-candidate-cache-batch-evidence.v1"
    ):
        raise ValueError("US-R2 primary statistics require candidate-cache batch evidence v1")
    evidence_id = _rehash_document(
        batch_document,
        id_field="evidence_id",
        prefix="us-r2-candidate-cache-batch",
    )
    if evidence_id != FROZEN_CANDIDATE_CACHE_BATCH_EVIDENCE_ID:
        raise ValueError("candidate-cache batch identity differs from the reviewed operator run")
    if _text(batch_document.get("plan_id"), "plan_id") != FROZEN_CANDIDATE_CACHE_PLAN_ID:
        raise ValueError("candidate-cache batch plan identity mismatch")
    years = tuple(
        _integer(item, "requested_years[]")
        for item in _sequence(batch_document.get("requested_years"), "requested_years")
    )
    expected_years = tuple(range(2001, 2027))
    if years != expected_years:
        raise ValueError("candidate-cache batch must cover the complete frozen 2001-2026 range")
    completed = tuple(
        _integer(item, "completed_years[]")
        for item in _sequence(batch_document.get("completed_years"), "completed_years")
    )
    if completed != years:
        raise ValueError("candidate-cache batch completed years differ from requested years")
    annual_ids = tuple(
        _text(item, "annual_evidence_ids[]")
        for item in _sequence(batch_document.get("annual_evidence_ids"), "annual_evidence_ids")
    )
    if len(annual_ids) != len(years) or len(set(annual_ids)) != len(annual_ids):
        raise ValueError("candidate-cache batch annual evidence denominator is incomplete")
    total_rows = _integer(batch_document.get("total_row_count"), "total_row_count")
    if total_rows != FROZEN_CANDIDATE_CACHE_TOTAL_ROWS:
        raise ValueError("candidate-cache batch row count differs from the reviewed run")
    if _integer(batch_document.get("candidate_count"), "candidate_count") != FROZEN_CANDIDATE_COUNT:
        raise ValueError("candidate-cache batch must retain all 37 candidates")
    if batch_document.get("blockers") != [] or batch_document.get("passed") is not True:
        raise ValueError("candidate-cache batch must be passed and blocker-free")
    if _text(batch_document.get("denominator_id"), "denominator_id") != (
        FROZEN_CANDIDATE_DENOMINATOR_ID
    ):
        raise ValueError("candidate-cache batch denominator identity mismatch")
    for field_name in (
        "candidate_dependent_scan",
        "candidate_performance_read",
        "raw_minute_source_access",
        "stage_exit_authority",
        "alpha_authority",
        "execution_authority",
        "order_authority",
    ):
        if _boolean(batch_document.get(field_name), field_name):
            raise ValueError(f"candidate-cache batch unexpectedly grants/uses {field_name}")
    return USR2CandidateCacheBatchGate(
        evidence_id=evidence_id,
        plan_id=FROZEN_CANDIDATE_CACHE_PLAN_ID,
        requested_years=years,
        annual_evidence_ids=annual_ids,
        total_row_count=total_rows,
    )


def validate_us_r2_candidate_cache_plan_gate(
    plan_document: Mapping[str, object],
    denominator_document: Mapping[str, object],
) -> tuple[USR2CandidateCachePlan, USR1CandidateDenominator]:
    denominator = validate_us_r2_candidate_denominator(denominator_document)
    expected, _execution = build_us_r2_candidate_cache_plan(
        denominator,
        base_panel_batch_evidence_id="us-r2-base-panel-batch-4833b15a9cb49649948d7118",
        regime_projection_evidence_id="us-r2-regime-projection-v2-337a6ce4272376aa401d4f4b",
    )
    if expected.plan_id != FROZEN_CANDIDATE_CACHE_PLAN_ID:
        raise RuntimeError("canonical candidate-cache plan no longer matches reviewed identity")
    if expected.compiled_batch_id != FROZEN_COMPILED_CANDIDATE_BATCH_ID:
        raise RuntimeError("canonical shared-DAG batch no longer matches reviewed identity")
    if dict(plan_document) != expected.to_dict():
        raise ValueError("candidate-cache plan differs from the canonical reviewed plan")
    return expected, denominator


def validate_and_load_us_r2_candidate_year(
    *,
    year: int,
    data_path: Path,
    evidence_document: Mapping[str, object],
    expected_evidence_id: str,
    expected_plan_id: str,
) -> tuple[USR2AnnualCandidateCacheArrays, USR2AnnualCandidateCacheEvidence]:
    evidence = parse_us_r2_annual_candidate_cache_evidence(evidence_document)
    if evidence.evidence_id != expected_evidence_id:
        raise ValueError(f"candidate-cache annual evidence identity mismatch for {year}")
    if evidence.year != year or evidence.plan_id != expected_plan_id:
        raise ValueError(f"candidate-cache annual plan/year mismatch for {year}")
    if evidence.candidate_count != FROZEN_CANDIDATE_COUNT or not evidence.passed:
        raise ValueError(f"candidate-cache annual evidence is not admitted for {year}")
    target = data_path.expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(f"candidate-cache NPZ is missing for {year}: {target}")
    if target.name != CANDIDATE_CACHE_FILENAME:
        raise ValueError("candidate-cache annual filename differs from the frozen layout")
    if target.stat().st_size != evidence.output_size_bytes:
        raise ValueError(f"candidate-cache NPZ size mismatch for {year}")
    if _sha256_file(target) != evidence.content_sha256:
        raise ValueError(f"candidate-cache NPZ SHA-256 mismatch for {year}")
    arrays = load_us_r2_candidate_npz(target, candidate_count=FROZEN_CANDIDATE_COUNT)
    if arrays.row_count != evidence.row_count:
        raise ValueError(f"candidate-cache NPZ row count mismatch for {year}")
    if not np.array_equal(arrays.label_available, arrays.label_reason_codes == 0):
        raise ValueError(f"candidate-cache label availability/reason mismatch for {year}")
    if not np.array_equal(np.isfinite(arrays.label_values), arrays.label_available):
        raise ValueError(f"candidate-cache label value availability mismatch for {year}")
    if np.any((~arrays.label_available) & (arrays.label_available_at_us != -1)):
        raise ValueError(f"candidate-cache unavailable label retained a target clock for {year}")
    if np.any(arrays.label_reason_codes > 2):
        raise ValueError(f"candidate-cache annual label reason code is unsupported for {year}")
    return arrays, evidence


@dataclass(frozen=True, slots=True)
class USR2RegimeSession:
    fold_id: str
    session_date_days: int
    regime_code: int | None
    available: bool
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class USR2RegimeSessionMap:
    evidence_id: str
    sessions: tuple[USR2RegimeSession, ...]

    def by_key(self) -> dict[tuple[str, int], USR2RegimeSession]:
        return {(item.fold_id, item.session_date_days): item for item in self.sessions}


def build_us_r2_regime_session_map(
    rows: Sequence[Mapping[str, object]],
    evidence_document: Mapping[str, object],
) -> USR2RegimeSessionMap:
    from finagent.research.us_r2_base_panel import validate_us_r2_regime_projection_v2_gate

    evidence_id = validate_us_r2_regime_projection_v2_gate(evidence_document)
    expected_rows = _integer(evidence_document.get("materialized_row_count"), "materialized_row_count")
    if len(rows) != expected_rows:
        raise ValueError("regime projection row count differs from reviewed evidence")
    frozen = canonical_us_r2_frozen_protocol()
    folds = {item.fold_id: item for item in frozen.walk_forward_protocol.folds}
    sessions: list[USR2RegimeSession] = []
    seen: set[tuple[str, int]] = set()
    counts: dict[str, dict[str, int]] = {
        fold_id: {label: 0 for label in FROZEN_REGIME_LABELS} for fold_id in folds
    }
    unavailable_counts: dict[str, dict[str, int]] = {fold_id: {} for fold_id in folds}
    available_counts = {fold_id: 0 for fold_id in folds}
    observed_counts = {fold_id: 0 for fold_id in folds}
    for index, raw in enumerate(rows):
        fold_id = _text(raw.get("fold_id"), f"rows[{index}].fold_id")
        fold = folds.get(fold_id)
        if fold is None:
            raise ValueError("regime projection contains an unknown fold")
        session_date = _date_value(raw.get("session_date"), f"rows[{index}].session_date")
        if not fold.evaluation_start <= session_date < fold.evaluation_end:
            raise ValueError("regime projection session falls outside its frozen evaluation window")
        day = _date_to_days(session_date)
        key = (fold_id, day)
        if key in seen:
            raise ValueError("regime projection repeats a fold/session key")
        seen.add(key)
        observed_counts[fold_id] += 1
        available = _boolean(raw.get("regime_available"), f"rows[{index}].regime_available")
        if available:
            label = _text(raw.get("regime_label"), f"rows[{index}].regime_label")
            code = _REGIME_CODE_BY_LABEL.get(label)
            if code is None:
                raise ValueError("regime projection contains a non-frozen regime label")
            if raw.get("unavailable_reason") is not None:
                raise ValueError("available regime row cannot carry an unavailable reason")
            available_counts[fold_id] += 1
            counts[fold_id][label] += 1
            reason = None
        else:
            if raw.get("regime_label") is not None:
                raise ValueError("unavailable regime row cannot carry a regime label")
            reason = _text(raw.get("unavailable_reason"), f"rows[{index}].unavailable_reason")
            unavailable_counts[fold_id][reason] = unavailable_counts[fold_id].get(reason, 0) + 1
            code = None
        sessions.append(
            USR2RegimeSession(
                fold_id=fold_id,
                session_date_days=day,
                regime_code=code,
                available=available,
                unavailable_reason=reason,
            )
        )

    raw_summaries = _sequence(evidence_document.get("fold_summaries"), "fold_summaries")
    summary_by_fold: dict[str, Mapping[str, object]] = {}
    for index, raw in enumerate(raw_summaries):
        summary = _mapping(raw, f"fold_summaries[{index}]")
        summary_by_fold[_text(summary.get("fold_id"), "fold_id")] = summary
    if set(summary_by_fold) != set(folds):
        raise ValueError("regime projection evidence fold summary set mismatch")
    for fold_id in folds:
        summary = summary_by_fold[fold_id]
        if _integer(summary.get("observed_session_count"), "observed_session_count") != observed_counts[fold_id]:
            raise ValueError("regime observed-session count differs from reviewed evidence")
        if _integer(summary.get("available_session_count"), "available_session_count") != available_counts[fold_id]:
            raise ValueError("regime available-session count differs from reviewed evidence")
        label_counts = _mapping(summary.get("label_counts"), "label_counts")
        if {label: _integer(label_counts.get(label), label) for label in FROZEN_REGIME_LABELS} != counts[fold_id]:
            raise ValueError("regime label counts differ from reviewed evidence")
        reason_counts = _mapping(summary.get("unavailable_reason_counts"), "unavailable_reason_counts")
        normalized_reasons = {
            str(reason): _integer(count, f"unavailable_reason_counts.{reason}")
            for reason, count in reason_counts.items()
            if _integer(count, f"unavailable_reason_counts.{reason}") > 0
        }
        if normalized_reasons != unavailable_counts[fold_id]:
            raise ValueError("regime unavailable-reason counts differ from reviewed evidence")
    return USR2RegimeSessionMap(evidence_id=evidence_id, sessions=tuple(sessions))


@dataclass(frozen=True, slots=True)
class USR2PrimaryStatisticsPlan:
    frozen_protocol_id: str
    evaluation_policy_id: str
    candidate_cache_batch_evidence_id: str
    candidate_cache_plan_id: str
    compiled_candidate_batch_id: str
    regime_projection_evidence_id: str
    denominator_id: str
    candidate_ids: tuple[str, ...]
    schema_version: str = "finagent.us-r2-primary-statistics-plan.v1"

    @property
    def plan_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-primary-statistics-plan")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        frozen = canonical_us_r2_frozen_protocol()
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "frozen_protocol_id": self.frozen_protocol_id,
            "evaluation_policy_id": self.evaluation_policy_id,
            "candidate_cache_batch_evidence_id": self.candidate_cache_batch_evidence_id,
            "candidate_cache_plan_id": self.candidate_cache_plan_id,
            "compiled_candidate_batch_id": self.compiled_candidate_batch_id,
            "regime_projection_evidence_id": self.regime_projection_evidence_id,
            "denominator_id": self.denominator_id,
            "candidate_count": len(self.candidate_ids),
            "candidate_ids": list(self.candidate_ids),
            "direction_source_fold_id": frozen.direction_source_fold_id,
            "direction_source_window": {
                "start": frozen.walk_forward_protocol.folds[0].train_start.isoformat(),
                "end": frozen.walk_forward_protocol.folds[0].train_end.isoformat(),
                "role": "TRAIN",
                "signal_interval": "15m",
                "label_horizon_trading_minutes": 60,
            },
            "evaluation_cells": [
                {"fold_id": fold.fold_id, "regime": regime}
                for fold in frozen.walk_forward_protocol.folds
                for regime in FROZEN_REGIME_LABELS
            ],
            "candidate_cache_scan_semantics": "one_npz_load_per_required_year_no_feature_recomputation",
            "regime_join_clock": "session_date_with_prior_session_lagged_regime_state",
            "raw_minute_source_access": False,
            "annual_base_parquet_access": False,
            "candidate_performance_used_to_define_regimes": False,
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


def build_us_r2_primary_statistics_plan(
    candidate_plan: USR2CandidateCachePlan,
    denominator: USR1CandidateDenominator,
    *,
    candidate_cache_batch_evidence_id: str,
    regime_projection_evidence_id: str,
) -> USR2PrimaryStatisticsPlan:
    if candidate_cache_batch_evidence_id != FROZEN_CANDIDATE_CACHE_BATCH_EVIDENCE_ID:
        raise ValueError("US-R2 primary statistics require the reviewed candidate-cache batch")
    if candidate_plan.plan_id != FROZEN_CANDIDATE_CACHE_PLAN_ID:
        raise ValueError("US-R2 primary statistics require the reviewed candidate-cache plan")
    if candidate_plan.compiled_batch_id != FROZEN_COMPILED_CANDIDATE_BATCH_ID:
        raise ValueError("US-R2 primary statistics require the reviewed shared-DAG batch")
    if denominator.denominator_id != FROZEN_CANDIDATE_DENOMINATOR_ID:
        raise ValueError("US-R2 primary statistics require the exact frozen denominator")
    if regime_projection_evidence_id != "us-r2-regime-projection-v2-337a6ce4272376aa401d4f4b":
        raise ValueError("US-R2 primary statistics require the reviewed regime-v2 evidence")
    policy = canonical_us_r2_statistical_evaluation_policy()
    return USR2PrimaryStatisticsPlan(
        frozen_protocol_id=canonical_us_r2_frozen_protocol().freeze_id,
        evaluation_policy_id=policy.policy_id,
        candidate_cache_batch_evidence_id=candidate_cache_batch_evidence_id,
        candidate_cache_plan_id=candidate_plan.plan_id,
        compiled_candidate_batch_id=candidate_plan.compiled_batch_id,
        regime_projection_evidence_id=regime_projection_evidence_id,
        denominator_id=denominator.denominator_id,
        candidate_ids=tuple(item.candidate.candidate_id for item in denominator.candidates),
    )


def _formation_ranges(arrays: USR2AnnualCandidateCacheArrays) -> Iterable[tuple[int, int]]:
    if arrays.row_count == 0:
        return
    if np.any(arrays.available_at_us[1:] < arrays.available_at_us[:-1]):
        raise ValueError("candidate-cache formation clock is not non-decreasing")
    start = 0
    while start < arrays.row_count:
        formation = arrays.available_at_us[start]
        end = start + 1
        while end < arrays.row_count and arrays.available_at_us[end] == formation:
            end += 1
        yield start, end
        start = end


def _validate_formation(arrays: USR2AnnualCandidateCacheArrays, start: int, end: int) -> int:
    days = arrays.session_date_days[start:end]
    if days.size == 0 or np.any(days != days[0]):
        raise ValueError("candidate-cache formation mixes session dates")
    assets = arrays.asset_codes[start:end]
    if np.any(assets[1:] <= assets[:-1]):
        raise ValueError("candidate-cache formation assets must be unique and sorted")
    return int(days[0])


def _average_ranks(asset_codes: np.ndarray, values: np.ndarray) -> np.ndarray:
    ordered = sorted(
        ((float(values[index]), int(asset_codes[index]), index) for index in range(values.size)),
        key=lambda item: (item[0], item[1]),
    )
    ranks = np.empty(values.size, dtype=np.float64)
    index = 0
    while index < len(ordered):
        end = index + 1
        value = ordered[index][0]
        while end < len(ordered) and ordered[end][0] == value:
            end += 1
        average = ((index + 1) + end) / 2.0
        for _value, _asset, original in ordered[index:end]:
            ranks[original] = average
        index = end
    return ranks


def _correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if left.size < 2 or right.size != left.size:
        return None
    x = np.asarray(left, dtype=np.float64)
    y = np.asarray(right, dtype=np.float64)
    x_dev = x - float(np.mean(x))
    y_dev = y - float(np.mean(y))
    denominator = math.sqrt(float(np.dot(x_dev, x_dev) * np.dot(y_dev, y_dev)))
    if denominator <= 1e-30:
        return None
    return float(np.dot(x_dev, y_dev) / denominator)


def _spearman(asset_codes: np.ndarray, feature: np.ndarray, labels: np.ndarray) -> float | None:
    order = np.argsort(asset_codes, kind="stable")
    assets = asset_codes[order]
    return _correlation(
        _average_ranks(assets, feature[order]),
        _average_ranks(assets, labels[order]),
    )


def _quantile_portfolio(
    asset_codes: np.ndarray,
    feature: np.ndarray,
    labels: np.ndarray,
    *,
    quantile_count: int,
) -> tuple[float, float, dict[int, float]]:
    ordered = sorted(
        (
            (float(feature[index]), int(asset_codes[index]), float(labels[index]))
            for index in range(feature.size)
        ),
        key=lambda item: (item[0], item[1]),
    )
    count = len(ordered)
    buckets: list[list[tuple[int, float]]] = [[] for _ in range(quantile_count)]
    for index, (_value, asset, label) in enumerate(ordered):
        bucket = min(quantile_count - 1, index * quantile_count // count)
        buckets[bucket].append((asset, label))
    if any(not bucket for bucket in buckets):
        raise ValueError("US-R2 quantile assignment produced an empty bucket")
    means = [float(np.mean([label for _asset, label in bucket])) for bucket in buckets]
    long_short_bps = 10_000.0 * (means[-1] - means[0])
    bucket_assets = np.arange(quantile_count, dtype=np.uint8)
    bucket_values = np.asarray(means, dtype=np.float64)
    monotonicity = _correlation(
        _average_ranks(bucket_assets, np.arange(quantile_count, dtype=np.float64)),
        _average_ranks(bucket_assets, bucket_values),
    )
    weights: dict[int, float] = {}
    for asset, _label in buckets[-1]:
        weights[asset] = 1.0 / len(buckets[-1])
    for asset, _label in buckets[0]:
        weights[asset] = -1.0 / len(buckets[0])
    return long_short_bps, 0.0 if monotonicity is None else monotonicity, weights


def _one_way_turnover(previous: Mapping[int, float], current: Mapping[int, float]) -> float:
    assets = sorted(set(previous).union(current))
    return 0.5 * math.fsum(
        abs(current.get(asset, 0.0) - previous.get(asset, 0.0)) for asset in assets
    )


def _partial_label_formation(label_reason_codes: np.ndarray) -> bool:
    return bool(np.any(label_reason_codes == 2))


def _candidate_status_and_rank_ic(
    *,
    asset_codes: np.ndarray,
    candidate_values: np.ndarray,
    label_values: np.ndarray,
    label_available: np.ndarray,
    label_reason_codes: np.ndarray,
    minimum_cross_section: int,
) -> tuple[int, float | None, np.ndarray | None]:
    feature_mask = np.isfinite(candidate_values)
    feature_count = int(feature_mask.sum())
    if feature_count == 0:
        return METRIC_INSUFFICIENT_CROSS_SECTION, None, None
    missing = feature_mask & ~label_available
    if np.any(missing):
        if int(missing.sum()) == feature_count and bool(np.all(label_reason_codes[missing] == 1)):
            return METRIC_BOUNDARY_UNREALIZED, None, None
        return METRIC_UNCLASSIFIED_MISSING_LABEL, None, None
    valid_indices = np.flatnonzero(feature_mask)
    if valid_indices.size < minimum_cross_section:
        return METRIC_INSUFFICIENT_CROSS_SECTION, None, None
    rank_ic = _spearman(
        asset_codes[valid_indices],
        candidate_values[valid_indices],
        label_values[valid_indices],
    )
    if rank_ic is None:
        return METRIC_RANK_IC_UNDEFINED, None, valid_indices
    return METRIC_AVAILABLE, rank_ic, valid_indices


@dataclass(frozen=True, slots=True)
class USR2CandidateDirectionEvidence:
    candidate_id: str
    period_count: int
    boundary_unrealized_period_count: int
    partial_label_omitted_period_count: int
    insufficient_cross_section_period_count: int
    mean_raw_rank_ic: float | None
    direction: int | None
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-r2-candidate-direction-evidence.v1"

    @property
    def passed(self) -> bool:
        return not self.blockers and self.mean_raw_rank_ic is not None and self.direction in {-1, 1}

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "period_count": self.period_count,
            "boundary_unrealized_period_count": self.boundary_unrealized_period_count,
            "partial_label_omitted_period_count": self.partial_label_omitted_period_count,
            "insufficient_cross_section_period_count": self.insufficient_cross_section_period_count,
            "mean_raw_rank_ic": self.mean_raw_rank_ic,
            "direction": self.direction,
            "passed": self.passed,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class USR2PrimaryDirectionEvidenceSet:
    plan_id: str
    evaluation_policy_id: str
    candidate_cache_batch_evidence_id: str
    source_fold_id: str
    source_years: tuple[int, ...]
    source_annual_evidence_ids: tuple[str, ...]
    candidates: tuple[USR2CandidateDirectionEvidence, ...]
    schema_version: str = "finagent.us-r2-primary-direction-evidence-set.v1"

    @property
    def passed(self) -> bool:
        return len(self.candidates) == FROZEN_CANDIDATE_COUNT and all(item.passed for item in self.candidates)

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-primary-direction-set")

    def direction(self, candidate_id: str) -> int:
        item = next((candidate for candidate in self.candidates if candidate.candidate_id == candidate_id), None)
        if item is None or item.direction not in {-1, 1}:
            raise ValueError("candidate lacks an admitted US-R2 primary direction")
        return item.direction

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "evaluation_policy_id": self.evaluation_policy_id,
            "candidate_cache_batch_evidence_id": self.candidate_cache_batch_evidence_id,
            "source_fold_id": self.source_fold_id,
            "source_years": list(self.source_years),
            "source_annual_evidence_ids": list(self.source_annual_evidence_ids),
            "candidate_count": len(self.candidates),
            "candidates": [item.to_dict() for item in self.candidates],
            "passed": self.passed,
            "direction_source": "fold_01_train_15m_60m_mean_cross_sectional_rank_ic",
            "oos_metrics_used_for_direction": False,
            "candidate_selection_applied": False,
            "alpha_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


def build_us_r2_primary_direction_evidence(
    annual_arrays: Iterable[tuple[int, USR2AnnualCandidateCacheArrays]],
    *,
    plan: USR2PrimaryStatisticsPlan,
    source_annual_evidence_ids: Mapping[int, str],
    policy: USR2StatisticalEvaluationPolicy | None = None,
) -> USR2PrimaryDirectionEvidenceSet:
    active = policy or canonical_us_r2_statistical_evaluation_policy()
    frozen = canonical_us_r2_frozen_protocol()
    fold = frozen.walk_forward_protocol.folds[0]
    candidate_count = len(plan.candidate_ids)
    counts = np.zeros(candidate_count, dtype=np.int64)
    rank_sums = np.zeros(candidate_count, dtype=np.float64)
    boundary = np.zeros(candidate_count, dtype=np.int64)
    partial = np.zeros(candidate_count, dtype=np.int64)
    insufficient = np.zeros(candidate_count, dtype=np.int64)
    blockers: list[list[str]] = [[] for _ in range(candidate_count)]
    seen_years: list[int] = []

    for year, arrays in annual_arrays:
        seen_years.append(year)
        for start, end in _formation_ranges(arrays):
            session_day = _validate_formation(arrays, start, end)
            session_date = _days_to_date(session_day)
            if not fold.train_start <= session_date < fold.train_end:
                continue
            reasons = arrays.label_reason_codes[start:end]
            if _partial_label_formation(reasons):
                partial += 1
                continue
            asset_codes = arrays.asset_codes[start:end]
            labels = arrays.label_values[start:end]
            label_available = arrays.label_available[start:end]
            values = arrays.candidate_values[start:end, :]
            formation_at = _us_to_datetime(int(arrays.available_at_us[start])).isoformat()
            for slot in range(candidate_count):
                status, rank_ic, _valid = _candidate_status_and_rank_ic(
                    asset_codes=asset_codes,
                    candidate_values=values[:, slot],
                    label_values=labels,
                    label_available=label_available,
                    label_reason_codes=reasons,
                    minimum_cross_section=active.minimum_cross_section,
                )
                if status == METRIC_AVAILABLE:
                    if rank_ic is None:
                        raise RuntimeError("available direction metric lost RankIC")
                    counts[slot] += 1
                    rank_sums[slot] += rank_ic
                elif status == METRIC_BOUNDARY_UNREALIZED:
                    boundary[slot] += 1
                elif status == METRIC_INSUFFICIENT_CROSS_SECTION:
                    insufficient[slot] += 1
                elif status == METRIC_UNCLASSIFIED_MISSING_LABEL:
                    blockers[slot].append(f"unclassified_missing_label:{formation_at}")
                elif status == METRIC_RANK_IC_UNDEFINED:
                    blockers[slot].append(f"rank_ic_undefined:{formation_at}")
                else:
                    raise RuntimeError("unexpected direction metric status")

    expected_years = tuple(range(fold.train_start.year, fold.train_end.year))
    if tuple(seen_years) != expected_years:
        raise ValueError("US-R2 direction input years must be exactly fold-01 TRAIN 2001-2005")
    candidates: list[USR2CandidateDirectionEvidence] = []
    for slot, candidate_id in enumerate(plan.candidate_ids):
        candidate_blockers = list(dict.fromkeys(blockers[slot]))
        if int(counts[slot]) < active.minimum_train_periods:
            candidate_blockers.append(
                f"insufficient_metric_periods:{int(counts[slot])}<{active.minimum_train_periods}"
            )
        mean_rank_ic = (
            None if counts[slot] == 0 else float(rank_sums[slot] / float(counts[slot]))
        )
        direction = None if mean_rank_ic is None or candidate_blockers else (1 if mean_rank_ic >= 0.0 else -1)
        candidates.append(
            USR2CandidateDirectionEvidence(
                candidate_id=candidate_id,
                period_count=int(counts[slot]),
                boundary_unrealized_period_count=int(boundary[slot]),
                partial_label_omitted_period_count=int(partial[slot]),
                insufficient_cross_section_period_count=int(insufficient[slot]),
                mean_raw_rank_ic=mean_rank_ic,
                direction=direction,
                blockers=tuple(candidate_blockers),
            )
        )
    source_ids = tuple(source_annual_evidence_ids[year] for year in expected_years)
    return USR2PrimaryDirectionEvidenceSet(
        plan_id=plan.plan_id,
        evaluation_policy_id=active.policy_id,
        candidate_cache_batch_evidence_id=plan.candidate_cache_batch_evidence_id,
        source_fold_id=fold.fold_id,
        source_years=expected_years,
        source_annual_evidence_ids=source_ids,
        candidates=tuple(candidates),
    )


@dataclass(frozen=True, slots=True)
class USR2AnnualPrimaryMetricArrays:
    session_date_days: np.ndarray
    formation_at_us: np.ndarray
    regime_codes: np.ndarray
    rank_ic: np.ndarray
    long_short_return_bps: np.ndarray
    one_way_turnover: np.ndarray
    coverage: np.ndarray
    quantile_monotonicity: np.ndarray
    status_codes: np.ndarray

    @property
    def row_count(self) -> int:
        return int(self.rank_ic.shape[0])

    @property
    def candidate_count(self) -> int:
        return int(self.rank_ic.shape[1])

    def __post_init__(self) -> None:
        rows = self.rank_ic.shape[0]
        candidates = self.rank_ic.shape[1] if self.rank_ic.ndim == 2 else -1
        if candidates < 1:
            raise ValueError("primary metric RankIC must be a non-empty matrix")
        for matrix in (
            self.long_short_return_bps,
            self.one_way_turnover,
            self.coverage,
            self.quantile_monotonicity,
            self.status_codes,
        ):
            if matrix.shape != (rows, candidates):
                raise ValueError("primary metric matrices must share an N x candidate shape")
        for vector in (self.session_date_days, self.formation_at_us, self.regime_codes):
            if vector.shape != (rows,):
                raise ValueError("primary metric metadata vectors must align with rows")
        if np.any(self.regime_codes >= len(FROZEN_REGIME_LABELS)):
            raise ValueError("primary metric cache contains an invalid regime code")
        available = self.status_codes == METRIC_AVAILABLE
        for matrix in (
            self.rank_ic,
            self.long_short_return_bps,
            self.one_way_turnover,
            self.coverage,
            self.quantile_monotonicity,
        ):
            if not np.array_equal(np.isfinite(matrix), available):
                raise ValueError("primary metric finite values must match AVAILABLE status")

    def as_npz_arrays(self) -> dict[str, np.ndarray]:
        return {
            "session_date_days": self.session_date_days,
            "formation_at_us": self.formation_at_us,
            "regime_codes": self.regime_codes,
            "rank_ic": self.rank_ic,
            "long_short_return_bps": self.long_short_return_bps,
            "one_way_turnover": self.one_way_turnover,
            "coverage": self.coverage,
            "quantile_monotonicity": self.quantile_monotonicity,
            "status_codes": self.status_codes,
        }


def evaluate_us_r2_annual_primary_metrics(
    arrays: USR2AnnualCandidateCacheArrays,
    *,
    year: int,
    plan: USR2PrimaryStatisticsPlan,
    regime_sessions: USR2RegimeSessionMap,
    policy: USR2StatisticalEvaluationPolicy | None = None,
) -> tuple[USR2AnnualPrimaryMetricArrays, str, int, int]:
    active = policy or canonical_us_r2_statistical_evaluation_policy()
    frozen = canonical_us_r2_frozen_protocol()
    folds = tuple(
        fold
        for fold in frozen.walk_forward_protocol.folds
        if fold.evaluation_start.year <= year <= (fold.evaluation_end - timedelta(days=1)).year
    )
    if len(folds) != 1:
        raise ValueError(f"US-R2 year {year} is not uniquely assigned to one evaluation fold")
    fold = folds[0]
    regime_by_key = regime_sessions.by_key()
    candidate_count = len(plan.candidate_ids)
    previous_sessions: list[int | None] = [None] * candidate_count
    previous_weights: list[dict[int, float]] = [{} for _ in range(candidate_count)]

    session_days_out: list[int] = []
    formation_us_out: list[int] = []
    regime_codes_out: list[int] = []
    rank_rows: list[list[float]] = []
    return_rows: list[list[float]] = []
    turnover_rows: list[list[float]] = []
    coverage_rows: list[list[float]] = []
    monotonicity_rows: list[list[float]] = []
    status_rows: list[list[int]] = []
    source_formation_count = 0
    unavailable_sessions: set[int] = set()

    for start, end in _formation_ranges(arrays):
        session_day = _validate_formation(arrays, start, end)
        session_date = _days_to_date(session_day)
        if not fold.evaluation_start <= session_date < fold.evaluation_end:
            continue
        source_formation_count += 1
        regime = regime_by_key.get((fold.fold_id, session_day))
        if regime is None:
            raise ValueError(
                f"candidate-cache formation lacks frozen regime projection: {fold.fold_id}:{session_date}"
            )
        if not regime.available:
            unavailable_sessions.add(session_day)
            continue
        if regime.regime_code is None:
            raise RuntimeError("available regime session lost its regime code")

        reasons = arrays.label_reason_codes[start:end]
        asset_codes = arrays.asset_codes[start:end]
        labels = arrays.label_values[start:end]
        label_available = arrays.label_available[start:end]
        values = arrays.candidate_values[start:end, :]
        label_eligible_count = int(label_available.sum())
        rank_row = [float("nan")] * candidate_count
        return_row = [float("nan")] * candidate_count
        turnover_row = [float("nan")] * candidate_count
        coverage_row = [float("nan")] * candidate_count
        monotonicity_row = [float("nan")] * candidate_count
        status_row = [METRIC_PARTIAL_LABEL_OMITTED] * candidate_count

        if not _partial_label_formation(reasons):
            for slot in range(candidate_count):
                status, rank_ic, valid_indices = _candidate_status_and_rank_ic(
                    asset_codes=asset_codes,
                    candidate_values=values[:, slot],
                    label_values=labels,
                    label_available=label_available,
                    label_reason_codes=reasons,
                    minimum_cross_section=active.minimum_cross_section,
                )
                status_row[slot] = status
                if status != METRIC_AVAILABLE:
                    continue
                if rank_ic is None or valid_indices is None:
                    raise RuntimeError("available primary metric lost RankIC/valid indices")
                long_short, monotonicity, weights = _quantile_portfolio(
                    asset_codes[valid_indices],
                    values[valid_indices, slot],
                    labels[valid_indices],
                    quantile_count=active.quantile_count,
                )
                if previous_sessions[slot] != session_day:
                    previous_weights[slot] = {}
                turnover = _one_way_turnover(previous_weights[slot], weights)
                previous_sessions[slot] = session_day
                previous_weights[slot] = weights
                coverage = len(valid_indices) / label_eligible_count if label_eligible_count else 0.0
                rank_row[slot] = rank_ic
                return_row[slot] = long_short
                turnover_row[slot] = turnover
                coverage_row[slot] = coverage
                monotonicity_row[slot] = monotonicity

        session_days_out.append(session_day)
        formation_us_out.append(int(arrays.available_at_us[start]))
        regime_codes_out.append(regime.regime_code)
        rank_rows.append(rank_row)
        return_rows.append(return_row)
        turnover_rows.append(turnover_row)
        coverage_rows.append(coverage_row)
        monotonicity_rows.append(monotonicity_row)
        status_rows.append(status_row)

    if not rank_rows:
        raise ValueError(f"US-R2 annual primary metrics contain no regime-available formations for {year}")
    result = USR2AnnualPrimaryMetricArrays(
        session_date_days=np.asarray(session_days_out, dtype=np.int32),
        formation_at_us=np.asarray(formation_us_out, dtype=np.int64),
        regime_codes=np.asarray(regime_codes_out, dtype=np.uint8),
        rank_ic=np.asarray(rank_rows, dtype=np.float64),
        long_short_return_bps=np.asarray(return_rows, dtype=np.float64),
        one_way_turnover=np.asarray(turnover_rows, dtype=np.float64),
        coverage=np.asarray(coverage_rows, dtype=np.float64),
        quantile_monotonicity=np.asarray(monotonicity_rows, dtype=np.float64),
        status_codes=np.asarray(status_rows, dtype=np.uint8),
    )
    return result, fold.fold_id, source_formation_count, len(unavailable_sessions)


def write_deterministic_us_r2_primary_metric_npz(
    path: Path,
    arrays: USR2AnnualPrimaryMetricArrays,
) -> tuple[str, int]:
    target = path.expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"US-R2 primary metric output is immutable: {target}")
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


def load_us_r2_primary_metric_npz(
    path: Path,
    *,
    candidate_count: int = FROZEN_CANDIDATE_COUNT,
) -> USR2AnnualPrimaryMetricArrays:
    target = path.expanduser().resolve()
    with np.load(target, allow_pickle=False) as archive:
        required = {
            "session_date_days",
            "formation_at_us",
            "regime_codes",
            "rank_ic",
            "long_short_return_bps",
            "one_way_turnover",
            "coverage",
            "quantile_monotonicity",
            "status_codes",
        }
        if set(archive.files) != required:
            raise ValueError("US-R2 primary metric NPZ field set mismatch")
        arrays = USR2AnnualPrimaryMetricArrays(
            session_date_days=np.asarray(archive["session_date_days"], dtype=np.int32),
            formation_at_us=np.asarray(archive["formation_at_us"], dtype=np.int64),
            regime_codes=np.asarray(archive["regime_codes"], dtype=np.uint8),
            rank_ic=np.asarray(archive["rank_ic"], dtype=np.float64),
            long_short_return_bps=np.asarray(archive["long_short_return_bps"], dtype=np.float64),
            one_way_turnover=np.asarray(archive["one_way_turnover"], dtype=np.float64),
            coverage=np.asarray(archive["coverage"], dtype=np.float64),
            quantile_monotonicity=np.asarray(archive["quantile_monotonicity"], dtype=np.float64),
            status_codes=np.asarray(archive["status_codes"], dtype=np.uint8),
        )
    if arrays.candidate_count != candidate_count:
        raise ValueError("US-R2 primary metric candidate width mismatch")
    if np.any(arrays.status_codes >= len(_METRIC_STATUS_NAMES)):
        raise ValueError("US-R2 primary metric status code is unsupported")
    return arrays


@dataclass(frozen=True, slots=True)
class USR2AnnualPrimaryMetricEvidence:
    plan_id: str
    year: int
    fold_id: str
    source_candidate_cache_evidence_id: str
    source_candidate_row_count: int
    source_formation_count: int
    metric_formation_count: int
    candidate_count: int
    available_metric_count: int
    status_counts: tuple[tuple[str, int], ...]
    regime_unavailable_session_count: int
    output_filename: str
    output_size_bytes: int
    content_sha256: str
    blockers: tuple[str, ...] = ()
    schema_version: str = "finagent.us-r2-annual-primary-metric-evidence.v1"

    @property
    def passed(self) -> bool:
        return not self.blockers and self.metric_formation_count > 0 and self.candidate_count == 37

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-annual-primary-metrics")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "year": self.year,
            "fold_id": self.fold_id,
            "source_candidate_cache_evidence_id": self.source_candidate_cache_evidence_id,
            "source_candidate_row_count": self.source_candidate_row_count,
            "source_formation_count": self.source_formation_count,
            "metric_formation_count": self.metric_formation_count,
            "candidate_count": self.candidate_count,
            "available_metric_count": self.available_metric_count,
            "status_counts": dict(self.status_counts),
            "regime_unavailable_session_count": self.regime_unavailable_session_count,
            "output_filename": self.output_filename,
            "output_size_bytes": self.output_size_bytes,
            "content_sha256": self.content_sha256,
            "blockers": list(self.blockers),
            "passed": self.passed,
            "source_kind": "annual_candidate_cache_npz_only",
            "raw_minute_source_access": False,
            "annual_base_parquet_access": False,
            "candidate_feature_recomputation": False,
            "candidate_selection_applied": False,
            "alpha_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


def build_us_r2_annual_primary_metric_evidence(
    *,
    plan: USR2PrimaryStatisticsPlan,
    year: int,
    fold_id: str,
    source_evidence: USR2AnnualCandidateCacheEvidence,
    source_formation_count: int,
    regime_unavailable_session_count: int,
    arrays: USR2AnnualPrimaryMetricArrays,
    output_path: Path,
    content_sha256: str,
    output_size_bytes: int,
) -> USR2AnnualPrimaryMetricEvidence:
    counts = np.bincount(arrays.status_codes.ravel(), minlength=len(_METRIC_STATUS_NAMES))
    blockers: list[str] = []
    if int(counts[METRIC_UNCLASSIFIED_MISSING_LABEL]) > 0:
        blockers.append("unclassified_missing_label_present")
    if int(counts[METRIC_RANK_IC_UNDEFINED]) > 0:
        blockers.append("rank_ic_undefined_present")
    return USR2AnnualPrimaryMetricEvidence(
        plan_id=plan.plan_id,
        year=year,
        fold_id=fold_id,
        source_candidate_cache_evidence_id=source_evidence.evidence_id,
        source_candidate_row_count=source_evidence.row_count,
        source_formation_count=source_formation_count,
        metric_formation_count=arrays.row_count,
        candidate_count=arrays.candidate_count,
        available_metric_count=int(counts[METRIC_AVAILABLE]),
        status_counts=tuple(
            (name, int(counts[index])) for index, name in enumerate(_METRIC_STATUS_NAMES)
        ),
        regime_unavailable_session_count=regime_unavailable_session_count,
        output_filename=output_path.name,
        output_size_bytes=output_size_bytes,
        content_sha256=content_sha256,
        blockers=tuple(blockers),
    )


def parse_us_r2_annual_primary_metric_evidence(
    document: Mapping[str, object],
) -> USR2AnnualPrimaryMetricEvidence:
    status = _mapping(document.get("status_counts"), "status_counts")
    evidence = USR2AnnualPrimaryMetricEvidence(
        plan_id=_text(document.get("plan_id"), "plan_id"),
        year=_integer(document.get("year"), "year"),
        fold_id=_text(document.get("fold_id"), "fold_id"),
        source_candidate_cache_evidence_id=_text(
            document.get("source_candidate_cache_evidence_id"), "source_candidate_cache_evidence_id"
        ),
        source_candidate_row_count=_integer(
            document.get("source_candidate_row_count"), "source_candidate_row_count"
        ),
        source_formation_count=_integer(document.get("source_formation_count"), "source_formation_count"),
        metric_formation_count=_integer(document.get("metric_formation_count"), "metric_formation_count"),
        candidate_count=_integer(document.get("candidate_count"), "candidate_count"),
        available_metric_count=_integer(document.get("available_metric_count"), "available_metric_count"),
        status_counts=tuple(
            (name, _integer(status.get(name), f"status_counts.{name}")) for name in _METRIC_STATUS_NAMES
        ),
        regime_unavailable_session_count=_integer(
            document.get("regime_unavailable_session_count"), "regime_unavailable_session_count"
        ),
        output_filename=_text(document.get("output_filename"), "output_filename"),
        output_size_bytes=_integer(document.get("output_size_bytes"), "output_size_bytes"),
        content_sha256=_text(document.get("content_sha256"), "content_sha256"),
        blockers=tuple(
            _text(item, "blockers[]") for item in _sequence(document.get("blockers"), "blockers")
        ),
    )
    if dict(document) != evidence.to_dict():
        raise ValueError("US-R2 annual primary metric evidence content identity mismatch")
    return evidence


def inspect_completed_us_r2_primary_metric_cache(
    *,
    data_path: Path,
    evidence_path: Path,
    plan: USR2PrimaryStatisticsPlan,
    source_evidence: USR2AnnualCandidateCacheEvidence,
) -> USR2AnnualPrimaryMetricEvidence | None:
    data_exists = data_path.is_file()
    evidence_exists = evidence_path.is_file()
    if not data_exists and not evidence_exists:
        return None
    if data_exists != evidence_exists:
        raise ValueError(f"US-R2 primary metric cache is partial for {source_evidence.year}")
    raw: object = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence = parse_us_r2_annual_primary_metric_evidence(_mapping(raw, str(evidence_path)))
    if evidence.plan_id != plan.plan_id or evidence.year != source_evidence.year:
        raise ValueError("US-R2 primary metric evidence plan/year mismatch")
    if evidence.source_candidate_cache_evidence_id != source_evidence.evidence_id:
        raise ValueError("US-R2 primary metric source candidate evidence mismatch")
    if evidence.output_filename != data_path.name:
        raise ValueError("US-R2 primary metric output filename mismatch")
    if data_path.stat().st_size != evidence.output_size_bytes:
        raise ValueError("US-R2 primary metric output size mismatch")
    if _sha256_file(data_path) != evidence.content_sha256:
        raise ValueError("US-R2 primary metric output SHA-256 mismatch")
    if not evidence.passed:
        raise ValueError("US-R2 completed primary metric evidence is blocked")
    return evidence


@dataclass(frozen=True, slots=True)
class USR2CandidateRegimeSliceStatistics:
    candidate_id: str
    fold_id: str
    regime: str
    direction: int
    period_count: int
    session_count: int
    boundary_unrealized_period_count: int
    partial_label_omitted_period_count: int
    insufficient_cross_section_period_count: int
    mean_raw_rank_ic: float | None
    mean_directed_rank_ic: float | None
    directed_rank_icir: float | None
    mean_directed_long_short_return_bps: float | None
    mean_one_way_turnover: float | None
    coverage_mean: float | None
    coverage_min: float | None
    directed_quantile_monotonicity: float | None
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-r2-candidate-regime-slice-statistics.v1"

    @property
    def passed(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "fold_id": self.fold_id,
            "regime": self.regime,
            "direction": self.direction,
            "period_count": self.period_count,
            "session_count": self.session_count,
            "boundary_unrealized_period_count": self.boundary_unrealized_period_count,
            "partial_label_omitted_period_count": self.partial_label_omitted_period_count,
            "insufficient_cross_section_period_count": self.insufficient_cross_section_period_count,
            "mean_raw_rank_ic": self.mean_raw_rank_ic,
            "mean_directed_rank_ic": self.mean_directed_rank_ic,
            "directed_rank_icir": self.directed_rank_icir,
            "mean_directed_long_short_return_bps": self.mean_directed_long_short_return_bps,
            "mean_one_way_turnover": self.mean_one_way_turnover,
            "coverage_mean": self.coverage_mean,
            "coverage_min": self.coverage_min,
            "directed_quantile_monotonicity": self.directed_quantile_monotonicity,
            "passed": self.passed,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class USR2PrimaryStatisticsReport:
    plan_id: str
    evaluation_policy_id: str
    direction_evidence_id: str
    annual_metric_evidence_ids: tuple[str, ...]
    slices: tuple[USR2CandidateRegimeSliceStatistics, ...]
    schema_version: str = "finagent.us-r2-primary-statistics-report.v1"

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(
            f"candidate:{item.candidate_id}:fold:{item.fold_id}:regime:{item.regime}:{blocker}"
            for item in self.slices
            for blocker in item.blockers
        )

    @property
    def passed(self) -> bool:
        return len(self.slices) == FROZEN_CANDIDATE_COUNT * 5 * 4 and not self.blockers

    @property
    def report_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-primary-statistics")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "evaluation_policy_id": self.evaluation_policy_id,
            "direction_evidence_id": self.direction_evidence_id,
            "annual_metric_evidence_ids": list(self.annual_metric_evidence_ids),
            "slice_count": len(self.slices),
            "slices": [item.to_dict() for item in self.slices],
            "passed": self.passed,
            "blockers": list(self.blockers),
            "scope": "primary_15m_60m_fold_x_regime_statistics_only",
            "hac_bootstrap_multiplicity_evaluated": False,
            "frequency_robustness_evaluated": False,
            "decay_robustness_evaluated": False,
            "alpha_gate_evaluated": False,
            "terminal_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


def build_us_r2_primary_statistics_report(
    metrics_by_fold: Mapping[str, Sequence[USR2AnnualPrimaryMetricArrays]],
    *,
    plan: USR2PrimaryStatisticsPlan,
    direction_evidence: USR2PrimaryDirectionEvidenceSet,
    annual_metric_evidence_ids: Sequence[str],
    policy: USR2StatisticalEvaluationPolicy | None = None,
) -> USR2PrimaryStatisticsReport:
    active = policy or canonical_us_r2_statistical_evaluation_policy()
    frozen = canonical_us_r2_frozen_protocol()
    if not direction_evidence.passed:
        raise ValueError("US-R2 primary statistics require complete frozen direction evidence")
    expected_folds = tuple(item.fold_id for item in frozen.walk_forward_protocol.folds)
    if tuple(metrics_by_fold) != expected_folds:
        raise ValueError("US-R2 primary statistics require all five folds in frozen order")
    slices: list[USR2CandidateRegimeSliceStatistics] = []
    for fold_id in expected_folds:
        annual_arrays = metrics_by_fold[fold_id]
        if not annual_arrays:
            raise ValueError(f"US-R2 primary statistics fold has no metric caches: {fold_id}")
        for regime_label in FROZEN_REGIME_LABELS:
            regime_code = _REGIME_CODE_BY_LABEL[regime_label]
            for slot, candidate_id in enumerate(plan.candidate_ids):
                rank_parts: list[np.ndarray] = []
                return_parts: list[np.ndarray] = []
                turnover_parts: list[np.ndarray] = []
                coverage_parts: list[np.ndarray] = []
                monotonicity_parts: list[np.ndarray] = []
                session_parts: list[np.ndarray] = []
                status_counts = np.zeros(len(_METRIC_STATUS_NAMES), dtype=np.int64)
                for arrays in annual_arrays:
                    regime_mask = arrays.regime_codes == regime_code
                    statuses = arrays.status_codes[regime_mask, slot]
                    status_counts += np.bincount(statuses, minlength=len(_METRIC_STATUS_NAMES))
                    available = statuses == METRIC_AVAILABLE
                    if not np.any(available):
                        continue
                    selected = np.flatnonzero(regime_mask)[available]
                    rank_parts.append(arrays.rank_ic[selected, slot])
                    return_parts.append(arrays.long_short_return_bps[selected, slot])
                    turnover_parts.append(arrays.one_way_turnover[selected, slot])
                    coverage_parts.append(arrays.coverage[selected, slot])
                    monotonicity_parts.append(arrays.quantile_monotonicity[selected, slot])
                    session_parts.append(arrays.session_date_days[selected])
                direction = direction_evidence.direction(candidate_id)
                blockers: list[str] = []
                if status_counts[METRIC_UNCLASSIFIED_MISSING_LABEL] > 0:
                    blockers.append("unclassified_missing_label_present")
                if status_counts[METRIC_RANK_IC_UNDEFINED] > 0:
                    blockers.append("rank_ic_undefined_present")
                if rank_parts:
                    rank_values = np.concatenate(rank_parts)
                    return_values = np.concatenate(return_parts)
                    turnover_values = np.concatenate(turnover_parts)
                    coverage_values = np.concatenate(coverage_parts)
                    monotonicity_values = np.concatenate(monotonicity_parts)
                    sessions = np.concatenate(session_parts)
                    period_count = int(rank_values.size)
                    session_count = int(np.unique(sessions).size)
                else:
                    rank_values = np.asarray([], dtype=np.float64)
                    return_values = np.asarray([], dtype=np.float64)
                    turnover_values = np.asarray([], dtype=np.float64)
                    coverage_values = np.asarray([], dtype=np.float64)
                    monotonicity_values = np.asarray([], dtype=np.float64)
                    period_count = 0
                    session_count = 0
                if period_count < active.minimum_oos_periods_per_fold_regime:
                    blockers.append(
                        "insufficient_metric_periods:"
                        f"{period_count}<{active.minimum_oos_periods_per_fold_regime}"
                    )
                if session_count < active.minimum_oos_sessions_per_fold_regime:
                    blockers.append(
                        "insufficient_metric_sessions:"
                        f"{session_count}<{active.minimum_oos_sessions_per_fold_regime}"
                    )
                if period_count:
                    directed_rank = direction * rank_values
                    directed_return = direction * return_values
                    directed_monotonicity = direction * monotonicity_values
                    mean_raw = float(np.mean(rank_values))
                    mean_directed = float(np.mean(directed_rank))
                    icir = rank_icir(tuple(float(item) for item in directed_rank))
                    mean_return = float(np.mean(directed_return))
                    mean_turnover = float(np.mean(turnover_values))
                    coverage_mean = float(np.mean(coverage_values))
                    coverage_min = float(np.min(coverage_values))
                    mean_monotonicity = float(np.mean(directed_monotonicity))
                else:
                    mean_raw = None
                    mean_directed = None
                    icir = None
                    mean_return = None
                    mean_turnover = None
                    coverage_mean = None
                    coverage_min = None
                    mean_monotonicity = None
                slices.append(
                    USR2CandidateRegimeSliceStatistics(
                        candidate_id=candidate_id,
                        fold_id=fold_id,
                        regime=regime_label,
                        direction=direction,
                        period_count=period_count,
                        session_count=session_count,
                        boundary_unrealized_period_count=int(
                            status_counts[METRIC_BOUNDARY_UNREALIZED]
                        ),
                        partial_label_omitted_period_count=int(
                            status_counts[METRIC_PARTIAL_LABEL_OMITTED]
                        ),
                        insufficient_cross_section_period_count=int(
                            status_counts[METRIC_INSUFFICIENT_CROSS_SECTION]
                        ),
                        mean_raw_rank_ic=mean_raw,
                        mean_directed_rank_ic=mean_directed,
                        directed_rank_icir=icir,
                        mean_directed_long_short_return_bps=mean_return,
                        mean_one_way_turnover=mean_turnover,
                        coverage_mean=coverage_mean,
                        coverage_min=coverage_min,
                        directed_quantile_monotonicity=mean_monotonicity,
                        blockers=tuple(dict.fromkeys(blockers)),
                    )
                )
    return USR2PrimaryStatisticsReport(
        plan_id=plan.plan_id,
        evaluation_policy_id=active.policy_id,
        direction_evidence_id=direction_evidence.evidence_id,
        annual_metric_evidence_ids=tuple(annual_metric_evidence_ids),
        slices=tuple(slices),
    )

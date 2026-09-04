from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from finagent.data.minute_store import MinuteMaterialization, MinuteQueryPlan
from finagent.data.minute_transform import (
    LabelQueryPlan,
    LabelSeriesEvidence,
    ResamplingEvidence,
    canonical_same_session_60m_label_spec,
)
from finagent.data.query import MarketDataField, SessionPolicy
from finagent.domain.labels import (
    AvailabilityPolicy,
    LabelHorizonUnit,
    LabelMetric,
    LabelSpec,
    ResearchPriceBasis,
)
from finagent.domain.market_bars import BarInterval
from finagent.research.us_r1_materialization import (
    USR1FoldMaterializationManifest,
    USR1InputPlan,
    USR1MaterializationSlice,
    USR1ObservationArtifact,
    USR1ObservationDiagnostics,
    USR1ObservationRole,
    build_us_r1_input_plan,
)
from finagent.research.us_r1_protocol import USR1CandidateDenominator
from finagent.research.us_r1_walkforward import USR1FoldExecutionSpec


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
    return value


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
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be integer-like")
    result = int(value)
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field_name} must be integer-like")
    return result


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def canonical_us_r1_label_spec(horizon_trading_minutes: int) -> LabelSpec:
    if horizon_trading_minutes == 60:
        return canonical_same_session_60m_label_spec()
    if horizon_trading_minutes not in {30, 120}:
        raise ValueError("US-R1 v1 label horizon must be 30m, 60m or 120m")
    return LabelSpec(
        metric=LabelMetric.SIMPLE_RETURN,
        horizon=horizon_trading_minutes,
        horizon_unit=LabelHorizonUnit.TRADING_MINUTES,
        allow_cross_session=False,
        price_basis=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
        name=f"us_r1_same_session_{horizon_trading_minutes}m_simple_return_raw",
    )


def build_authoritative_us_r1_input_plan(
    resampled_plan: MinuteQueryPlan,
    label_plan: LabelQueryPlan,
    resampling_evidence: ResamplingEvidence,
    label_evidence: LabelSeriesEvidence,
    *,
    execution_spec: USR1FoldExecutionSpec,
    denominator: USR1CandidateDenominator,
    role: USR1ObservationRole,
    label_horizon_trading_minutes: int,
) -> USR1InputPlan:
    query = resampled_plan.query
    label_query = label_plan.source_query
    if query.interval not in {
        BarInterval.MINUTE_5,
        BarInterval.MINUTE_15,
        BarInterval.MINUTE_30,
    }:
        raise ValueError("US-R1 bars must be 5m/15m/30m")
    if query.session_policy is not SessionPolicy.REGULAR:
        raise ValueError("US-R1 bars must use the regular XNYS session")
    if query.adjustment_policy is not ResearchPriceBasis.RAW:
        raise ValueError("US-R1 bars must use RAW research prices")
    if query.availability_policy is not AvailabilityPolicy.AVAILABLE_AT:
        raise ValueError("US-R1 bars must use available_at PIT semantics")
    if set(query.fields) != set(MarketDataField):
        raise ValueError("US-R1 bars require the complete OHLCV field set")
    if label_query.interval is not BarInterval.MINUTE_1:
        raise ValueError("US-R1 label source must remain canonical 1m")
    if label_query.session_policy is not SessionPolicy.REGULAR:
        raise ValueError("US-R1 labels must use the regular XNYS session")
    if label_query.adjustment_policy is not ResearchPriceBasis.RAW:
        raise ValueError("US-R1 labels must use RAW research prices")
    if label_query.availability_policy is not AvailabilityPolicy.AVAILABLE_AT:
        raise ValueError("US-R1 labels must use available_at PIT semantics")
    if label_query.fields != (MarketDataField.CLOSE,):
        raise ValueError("US-R1 label source fields must be exactly close")
    expected_label = canonical_us_r1_label_spec(label_horizon_trading_minutes)
    if label_plan.label_spec_id != expected_label.label_id:
        raise ValueError("US-R1 label-plan identity differs from the frozen horizon LabelSpec")
    if label_evidence.label_spec_id != expected_label.label_id:
        raise ValueError("US-R1 label evidence differs from the frozen horizon LabelSpec")
    expected_start = (
        execution_spec.train_start
        if role is USR1ObservationRole.TRAIN
        else execution_spec.evaluation_start
    )
    expected_end = (
        execution_spec.train_end
        if role is USR1ObservationRole.TRAIN
        else execution_spec.evaluation_end
    )
    if query.start != expected_start or query.end != expected_end:
        raise ValueError("US-R1 resampled query window differs from the frozen fold role")
    if label_query.start != expected_start or label_query.end != expected_end:
        raise ValueError("US-R1 label query window differs from the frozen fold role")
    return build_us_r1_input_plan(
        resampled_plan,
        label_plan,
        resampling_evidence,
        label_evidence,
        execution_spec=execution_spec,
        denominator=denominator,
        role=role,
        label_horizon_trading_minutes=label_horizon_trading_minutes,
    )


def validate_us_r1_input_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    expected_assets: Sequence[str],
) -> tuple[str, ...]:
    expected = tuple(dict.fromkeys(item.strip() for item in expected_assets if item.strip()))
    if not expected or len(expected) != len(tuple(expected_assets)):
        raise ValueError("US-R1 expected_assets must be non-empty and unique")
    expected_set = set(expected)
    observed: set[str] = set()
    complete: set[str] = set()
    blockers: list[str] = []
    for row in rows:
        asset = _text(row.get("research_asset_id"), "row.research_asset_id")
        if asset not in expected_set:
            raise ValueError(f"US-R1 input contains asset outside EngineeringUniverse: {asset!r}")
        observed.add(asset)
        if _boolean(row.get("is_complete"), "row.is_complete"):
            complete.add(asset)
        if not _boolean(row.get("label_row_present"), "row.label_row_present"):
            # A missing label anchor legitimately leaves the downstream
            # availability expression NULL.  The observation materializer
            # records the precise technical blocker; do not mask it with a
            # boolean type error at this earlier structural boundary.
            continue
        if _boolean(row.get("label_available"), "row.label_available"):
            available_at = row.get("available_at")
            target_available_at = row.get("target_available_at")
            if available_at is None or target_available_at is None:
                raise ValueError("available US-R1 label must contain formation/target clocks")
            left = str(available_at.isoformat() if hasattr(available_at, "isoformat") else available_at)
            right = str(
                target_available_at.isoformat()
                if hasattr(target_available_at, "isoformat")
                else target_available_at
            )
            from datetime import datetime

            formation = datetime.fromisoformat(left)
            target = datetime.fromisoformat(right)
            if formation.tzinfo is None or target.tzinfo is None or target <= formation:
                raise ValueError("US-R1 realized label must become available after feature formation")
    missing = tuple(sorted(expected_set.difference(observed)))
    without_complete = tuple(sorted(expected_set.difference(complete)))
    if missing:
        blockers.append("input:engineering_assets_missing:" + ",".join(missing))
    if without_complete:
        blockers.append("input:engineering_assets_without_complete_bar:" + ",".join(without_complete))
    return tuple(blockers)


def merge_us_r1_observation_blockers(
    diagnostics: USR1ObservationDiagnostics,
    blockers: Sequence[str],
) -> USR1ObservationDiagnostics:
    merged = tuple(dict.fromkeys((*diagnostics.blockers, *(item.strip() for item in blockers if item.strip()))))
    return USR1ObservationDiagnostics(
        input_row_count=diagnostics.input_row_count,
        complete_bar_count=diagnostics.complete_bar_count,
        incomplete_bar_count=diagnostics.incomplete_bar_count,
        label_anchor_missing_count=diagnostics.label_anchor_missing_count,
        close_anchor_mismatch_count=diagnostics.close_anchor_mismatch_count,
        observation_count=diagnostics.observation_count,
        available_feature_count=diagnostics.available_feature_count,
        available_label_count=diagnostics.available_label_count,
        blockers=merged,
    )


def validate_us_r1_input_plan_document(document: Mapping[str, object]) -> str:
    if _text(document.get("schema_version"), "input_plan.schema_version") != (
        "finagent.us-r1-input-plan.v1"
    ):
        raise ValueError("unsupported US-R1 input-plan schema")
    plan_id = _text(document.get("plan_id"), "input_plan.plan_id")
    payload = {
        "schema_version": document.get("schema_version"),
        "execution_spec_id": document.get("execution_spec_id"),
        "denominator_id": document.get("denominator_id"),
        "formation_policy_id": document.get("formation_policy_id"),
        "role": document.get("role"),
        "signal_interval": document.get("signal_interval"),
        "label_horizon_trading_minutes": document.get("label_horizon_trading_minutes"),
        "resampled_plan_id": document.get("resampled_plan_id"),
        "label_plan_id": document.get("label_plan_id"),
        "resampling_evidence_id": document.get("resampling_evidence_id"),
        "label_evidence_id": document.get("label_evidence_id"),
        "source_data_version": document.get("source_data_version"),
        "data_version": document.get("data_version"),
        "partition_months": list(
            _sequence(document.get("partition_months"), "input_plan.partition_months")
        ),
        "output_columns": list(
            _sequence(document.get("output_columns"), "input_plan.output_columns")
        ),
    }
    if plan_id != _canonical_hash(payload, prefix="us-r1-input-plan"):
        raise ValueError("US-R1 input-plan content identity mismatch")
    _integer(document.get("selected_size_bytes"), "input_plan.selected_size_bytes")
    return plan_id


def parse_minute_materialization(document: Mapping[str, object]) -> MinuteMaterialization:
    materialization = MinuteMaterialization(
        plan_id=_text(document.get("plan_id"), "materialization.plan_id"),
        data_version=_text(document.get("data_version"), "materialization.data_version"),
        row_count=_integer(document.get("row_count"), "materialization.row_count"),
        size_bytes=_integer(document.get("size_bytes"), "materialization.size_bytes"),
        content_sha256=_text(document.get("content_sha256"), "materialization.content_sha256"),
        output_filename=_text(document.get("output_filename"), "materialization.output_filename"),
    )
    if dict(document) != materialization.to_dict():
        raise ValueError("US-R1 input materialization content identity mismatch")
    return materialization


def parse_us_r1_observation_artifact(
    document: Mapping[str, object],
) -> USR1ObservationArtifact:
    artifact = USR1ObservationArtifact(
        execution_spec_id=_text(document.get("execution_spec_id"), "artifact.execution_spec_id"),
        denominator_id=_text(document.get("denominator_id"), "artifact.denominator_id"),
        input_plan_id=_text(document.get("input_plan_id"), "artifact.input_plan_id"),
        role=USR1ObservationRole(_text(document.get("role"), "artifact.role")),
        signal_interval=BarInterval(_text(document.get("signal_interval"), "artifact.signal_interval")),
        label_horizon_trading_minutes=_integer(
            document.get("label_horizon_trading_minutes"),
            "artifact.label_horizon_trading_minutes",
        ),
        row_count=_integer(document.get("row_count"), "artifact.row_count"),
        content_sha256=_text(document.get("content_sha256"), "artifact.content_sha256"),
        output_filename=_text(document.get("output_filename"), "artifact.output_filename"),
    )
    if dict(document) != artifact.to_dict():
        raise ValueError("US-R1 observation artifact content identity mismatch")
    return artifact


def parse_us_r1_observation_diagnostics(
    document: Mapping[str, object],
) -> USR1ObservationDiagnostics:
    diagnostics = USR1ObservationDiagnostics(
        input_row_count=_integer(document.get("input_row_count"), "diagnostics.input_row_count"),
        complete_bar_count=_integer(
            document.get("complete_bar_count"), "diagnostics.complete_bar_count"
        ),
        incomplete_bar_count=_integer(
            document.get("incomplete_bar_count"), "diagnostics.incomplete_bar_count"
        ),
        label_anchor_missing_count=_integer(
            document.get("label_anchor_missing_count"),
            "diagnostics.label_anchor_missing_count",
        ),
        close_anchor_mismatch_count=_integer(
            document.get("close_anchor_mismatch_count"),
            "diagnostics.close_anchor_mismatch_count",
        ),
        observation_count=_integer(
            document.get("observation_count"), "diagnostics.observation_count"
        ),
        available_feature_count=_integer(
            document.get("available_feature_count"), "diagnostics.available_feature_count"
        ),
        available_label_count=_integer(
            document.get("available_label_count"), "diagnostics.available_label_count"
        ),
        blockers=tuple(
            _text(item, "diagnostics.blockers[]")
            for item in _sequence(document.get("blockers"), "diagnostics.blockers")
        ),
    )
    if dict(document) != diagnostics.to_dict():
        raise ValueError("US-R1 observation diagnostics content identity mismatch")
    return diagnostics


def parse_us_r1_materialization_slice(
    document: Mapping[str, object],
) -> USR1MaterializationSlice:
    item = USR1MaterializationSlice(
        role=USR1ObservationRole(_text(document.get("role"), "slice.role")),
        signal_interval=BarInterval(_text(document.get("signal_interval"), "slice.signal_interval")),
        label_horizon_trading_minutes=_integer(
            document.get("label_horizon_trading_minutes"), "slice.label_horizon_trading_minutes"
        ),
        input_plan_id=_text(document.get("input_plan_id"), "slice.input_plan_id"),
        input_materialization_id=_text(
            document.get("input_materialization_id"), "slice.input_materialization_id"
        ),
        observation_artifact_id=_text(
            document.get("observation_artifact_id"), "slice.observation_artifact_id"
        ),
        diagnostics_id=_text(document.get("diagnostics_id"), "slice.diagnostics_id"),
        input_row_count=_integer(document.get("input_row_count"), "slice.input_row_count"),
        observation_row_count=_integer(
            document.get("observation_row_count"), "slice.observation_row_count"
        ),
        passed=_boolean(document.get("passed"), "slice.passed"),
        blockers=tuple(
            _text(item, "slice.blockers[]")
            for item in _sequence(document.get("blockers"), "slice.blockers")
        ),
    )
    if dict(document) != item.to_dict():
        raise ValueError("US-R1 materialization slice content mismatch")
    return item


def parse_us_r1_fold_materialization_manifest(
    document: Mapping[str, object],
) -> USR1FoldMaterializationManifest:
    slices = tuple(
        parse_us_r1_materialization_slice(_mapping(raw, f"manifest.slices[{index}]"))
        for index, raw in enumerate(_sequence(document.get("slices"), "manifest.slices"))
    )
    manifest = USR1FoldMaterializationManifest(
        research_protocol_id=_text(
            document.get("research_protocol_id"), "manifest.research_protocol_id"
        ),
        walk_forward_protocol_id=_text(
            document.get("walk_forward_protocol_id"), "manifest.walk_forward_protocol_id"
        ),
        execution_spec_id=_text(document.get("execution_spec_id"), "manifest.execution_spec_id"),
        denominator_id=_text(document.get("denominator_id"), "manifest.denominator_id"),
        formation_policy_id=_text(
            document.get("formation_policy_id"), "manifest.formation_policy_id"
        ),
        fold_id=_text(document.get("fold_id"), "manifest.fold_id"),
        fold_ordinal=_integer(document.get("fold_ordinal"), "manifest.fold_ordinal"),
        verified_gap_trading_minutes=_integer(
            document.get("verified_gap_trading_minutes"),
            "manifest.verified_gap_trading_minutes",
        ),
        required_gap_trading_minutes=_integer(
            document.get("required_gap_trading_minutes"),
            "manifest.required_gap_trading_minutes",
        ),
        slices=slices,
    )
    if dict(document) != manifest.to_dict():
        raise ValueError("US-R1 fold materialization manifest content identity mismatch")
    return manifest


def verify_us_r1_observation_file(
    path: str | Path,
    artifact: USR1ObservationArtifact,
) -> None:
    target = Path(path).expanduser().resolve()
    digest = hashlib.sha256()
    row_count = 0
    with target.open("rb") as handle:
        for line in handle:
            digest.update(line)
            row_count += 1
    if row_count != artifact.row_count or digest.hexdigest() != artifact.content_sha256:
        raise ValueError("US-R1 observation JSONL differs from its content-addressed artifact")

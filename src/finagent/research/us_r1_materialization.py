from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from finagent.data.minute_store import MinuteMaterialization, MinuteQueryPlan
from finagent.data.minute_transform import LabelQueryPlan, LabelSeriesEvidence, ResamplingEvidence
from finagent.domain.market_bars import BarInterval
from finagent.research.us_baselines import (
    USBaselineBar,
    USBaselineProtocol,
    evaluate_us_baseline_feature,
)
from finagent.research.us_r1_protocol import (
    USR1CandidateDenominator,
    canonical_us_r1_research_protocol,
)
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


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _aware(value: object, field_name: str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(_text(value, field_name))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def _float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


class USR1ObservationRole(StrEnum):
    TRAIN = "TRAIN"
    EVALUATION = "EVALUATION"


@dataclass(frozen=True, slots=True)
class USR1FeatureFormationPolicy:
    research_protocol_id: str
    window_semantics: str = "same_structural_window_bars_at_each_frequency"
    supported_intervals: tuple[BarInterval, ...] = (
        BarInterval.MINUTE_5,
        BarInterval.MINUTE_15,
        BarInterval.MINUTE_30,
    )
    same_session_only: bool = True
    require_complete_bars: bool = True
    schema_version: str = "finagent.us-r1-feature-formation-policy.v1"

    def __post_init__(self) -> None:
        protocol = canonical_us_r1_research_protocol()
        if self.research_protocol_id != protocol.protocol_id:
            raise ValueError("US-R1 formation policy/research protocol identity mismatch")
        if self.window_semantics != "same_structural_window_bars_at_each_frequency":
            raise ValueError("US-R1 v1 frequency robustness preserves structural bar counts")
        if self.supported_intervals != (
            BarInterval.MINUTE_5,
            BarInterval.MINUTE_15,
            BarInterval.MINUTE_30,
        ):
            raise ValueError("US-R1 formation intervals must be exactly 5m/15m/30m")
        if not self.same_session_only or not self.require_complete_bars:
            raise ValueError("US-R1 formation requires same-session complete bars")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-feature-formation-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "research_protocol_id": self.research_protocol_id,
            "window_semantics": self.window_semantics,
            "supported_intervals": [item.value for item in self.supported_intervals],
            "same_session_only": self.same_session_only,
            "require_complete_bars": self.require_complete_bars,
            "reuse_boundary": "existing_us_b0_a0_structural_feature_evaluator",
            "status_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


def canonical_us_r1_feature_formation_policy() -> USR1FeatureFormationPolicy:
    return USR1FeatureFormationPolicy(
        research_protocol_id=canonical_us_r1_research_protocol().protocol_id
    )


@dataclass(frozen=True, slots=True)
class USR1InputPlan:
    execution_spec_id: str
    denominator_id: str
    formation_policy_id: str
    role: USR1ObservationRole
    signal_interval: BarInterval
    label_horizon_trading_minutes: int
    resampled_plan_id: str
    label_plan_id: str
    resampling_evidence_id: str
    label_evidence_id: str
    source_data_version: str
    data_version: str
    sql: str
    partition_months: tuple[str, ...]
    selected_size_bytes: int
    output_columns: tuple[str, ...]
    schema_version: str = "finagent.us-r1-input-plan.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "execution_spec_id",
            "denominator_id",
            "formation_policy_id",
            "resampled_plan_id",
            "label_plan_id",
            "resampling_evidence_id",
            "label_evidence_id",
            "source_data_version",
            "data_version",
            "sql",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must be non-empty")
        if self.signal_interval not in {
            BarInterval.MINUTE_5,
            BarInterval.MINUTE_15,
            BarInterval.MINUTE_30,
        }:
            raise ValueError("US-R1 input interval must be 5m/15m/30m")
        if self.label_horizon_trading_minutes not in {30, 60, 120}:
            raise ValueError("US-R1 label horizon must be 30m/60m/120m")
        if self.role is USR1ObservationRole.TRAIN and (
            self.signal_interval is not BarInterval.MINUTE_15
            or self.label_horizon_trading_minutes != 60
        ):
            raise ValueError("US-R1 training materialization is exactly 15m/60m")
        if self.role is USR1ObservationRole.EVALUATION:
            allowed = {
                (BarInterval.MINUTE_5, 60),
                (BarInterval.MINUTE_15, 30),
                (BarInterval.MINUTE_15, 60),
                (BarInterval.MINUTE_15, 120),
                (BarInterval.MINUTE_30, 60),
            }
            if (self.signal_interval, self.label_horizon_trading_minutes) not in allowed:
                raise ValueError("unsupported US-R1 OOS frequency/horizon evidence slice")

    @property
    def plan_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "execution_spec_id": self.execution_spec_id,
                "denominator_id": self.denominator_id,
                "formation_policy_id": self.formation_policy_id,
                "role": self.role.value,
                "signal_interval": self.signal_interval.value,
                "label_horizon_trading_minutes": self.label_horizon_trading_minutes,
                "resampled_plan_id": self.resampled_plan_id,
                "label_plan_id": self.label_plan_id,
                "resampling_evidence_id": self.resampling_evidence_id,
                "label_evidence_id": self.label_evidence_id,
                "source_data_version": self.source_data_version,
                "data_version": self.data_version,
                "partition_months": list(self.partition_months),
                "output_columns": list(self.output_columns),
            },
            prefix="us-r1-input-plan",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "execution_spec_id": self.execution_spec_id,
            "denominator_id": self.denominator_id,
            "formation_policy_id": self.formation_policy_id,
            "role": self.role.value,
            "signal_interval": self.signal_interval.value,
            "label_horizon_trading_minutes": self.label_horizon_trading_minutes,
            "resampled_plan_id": self.resampled_plan_id,
            "label_plan_id": self.label_plan_id,
            "resampling_evidence_id": self.resampling_evidence_id,
            "label_evidence_id": self.label_evidence_id,
            "source_data_version": self.source_data_version,
            "data_version": self.data_version,
            "partition_months": list(self.partition_months),
            "selected_size_bytes": self.selected_size_bytes,
            "output_columns": list(self.output_columns),
        }


def build_us_r1_input_plan(
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
    interval = resampled_plan.query.interval
    if interval not in {BarInterval.MINUTE_5, BarInterval.MINUTE_15, BarInterval.MINUTE_30}:
        raise ValueError("US-R1 resampled plan must be 5m/15m/30m")
    if resampled_plan.query.assets != label_plan.source_query.assets:
        raise ValueError("US-R1 resampled/label asset sets must match")
    if resampled_plan.query.start != label_plan.source_query.start:
        raise ValueError("US-R1 resampled/label query starts must match")
    if resampled_plan.query.end != label_plan.source_query.end:
        raise ValueError("US-R1 resampled/label query ends must match")
    if resampling_evidence.resampled_plan_id != resampled_plan.plan_id:
        raise ValueError("US-R1 resampling evidence/plan mismatch")
    if label_evidence.label_plan_id != label_plan.plan_id:
        raise ValueError("US-R1 label evidence/plan mismatch")
    if resampling_evidence.calendar_id != label_evidence.calendar_id:
        raise ValueError("US-R1 resampling/label calendar mismatch")
    if resampling_evidence.source_data_version != label_evidence.source_data_version:
        raise ValueError("US-R1 resampling/label source-data mismatch")
    if execution_spec.denominator_id != denominator.denominator_id:
        raise ValueError("US-R1 execution/denominator identity mismatch")
    formation = canonical_us_r1_feature_formation_policy()
    data_version = _canonical_hash(
        {
            "execution_spec_id": execution_spec.execution_spec_id,
            "denominator_id": denominator.denominator_id,
            "formation_policy_id": formation.policy_id,
            "role": role.value,
            "signal_interval": interval.value,
            "label_horizon_trading_minutes": label_horizon_trading_minutes,
            "resampled_data_version": resampled_plan.data_version,
            "label_data_version": label_plan.data_version,
            "join_clock": "bar.available_at=label.source_available_at",
        },
        prefix="us-r1-input-data-version",
    )
    output_columns = (
        "research_asset_id",
        "session_date",
        "session_id",
        "event_time",
        "available_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "is_complete",
        "source_available_at",
        "source_price",
        "target_available_at",
        "label_value",
        "label_available",
        "unavailable_reason",
        "label_row_present",
        "close_anchor_difference",
    )
    sql = f"""
        WITH bars AS (
            {resampled_plan.sql}
        ),
        labels AS (
            {label_plan.sql}
        )
        SELECT
            b.research_asset_id,
            b.session_date,
            b.session_id,
            b.event_time,
            b.available_at,
            CAST(b.open AS DOUBLE) AS open,
            CAST(b.high AS DOUBLE) AS high,
            CAST(b.low AS DOUBLE) AS low,
            CAST(b.close AS DOUBLE) AS close,
            CAST(b.volume AS DOUBLE) AS volume,
            b.is_complete,
            l.source_available_at,
            CAST(l.source_price AS DOUBLE) AS source_price,
            l.target_available_at,
            CAST(l.label_value AS DOUBLE) AS label_value,
            l.label_available,
            l.unavailable_reason,
            l.source_available_at IS NOT NULL AS label_row_present,
            CASE
                WHEN l.source_price IS NULL THEN NULL
                ELSE abs(CAST(b.close AS DOUBLE) - CAST(l.source_price AS DOUBLE))
            END AS close_anchor_difference
        FROM bars AS b
        LEFT JOIN labels AS l
          ON l.research_asset_id = b.research_asset_id
         AND l.session_date = b.session_date
         AND l.source_available_at = b.available_at
        ORDER BY b.available_at, b.research_asset_id
    """.strip()
    partitions = tuple(sorted(set(resampled_plan.partition_months).union(label_plan.partition_months)))
    return USR1InputPlan(
        execution_spec_id=execution_spec.execution_spec_id,
        denominator_id=denominator.denominator_id,
        formation_policy_id=formation.policy_id,
        role=role,
        signal_interval=interval,
        label_horizon_trading_minutes=label_horizon_trading_minutes,
        resampled_plan_id=resampled_plan.plan_id,
        label_plan_id=label_plan.plan_id,
        resampling_evidence_id=resampling_evidence.evidence_id,
        label_evidence_id=label_evidence.evidence_id,
        source_data_version=resampling_evidence.source_data_version,
        data_version=data_version,
        sql=sql,
        partition_months=partitions,
        selected_size_bytes=max(resampled_plan.selected_size_bytes, label_plan.selected_size_bytes),
        output_columns=output_columns,
    )


@dataclass(frozen=True, slots=True)
class USR1CandidateObservation:
    candidate_id: str
    feature_spec_id: str
    role: USR1ObservationRole
    signal_interval: BarInterval
    label_horizon_trading_minutes: int
    asset: str
    session_id: str
    event_time: datetime
    feature_available_at: datetime
    feature_value: float | None
    feature_unavailable_reason: str | None
    realized_label: float | None
    label_available_at: datetime | None
    label_unavailable_reason: str | None
    schema_version: str = "finagent.us-r1-candidate-observation.v1"

    def __post_init__(self) -> None:
        for field_name in ("candidate_id", "feature_spec_id", "asset", "session_id"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must be non-empty")
        if self.event_time.tzinfo is None or self.event_time.utcoffset() is None:
            raise ValueError("event_time must be timezone-aware")
        if self.feature_available_at.tzinfo is None or self.feature_available_at.utcoffset() is None:
            raise ValueError("feature_available_at must be timezone-aware")
        if bool(self.feature_value is None) == bool(self.feature_unavailable_reason is None):
            raise ValueError("exactly one feature value/unavailable reason is required")
        if self.realized_label is None:
            if self.label_available_at is not None or self.label_unavailable_reason is None:
                raise ValueError("unavailable label requires reason and no available_at")
        elif self.label_available_at is None or self.label_unavailable_reason is not None:
            raise ValueError("available label requires label_available_at and no reason")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "feature_spec_id": self.feature_spec_id,
            "role": self.role.value,
            "signal_interval": self.signal_interval.value,
            "label_horizon_trading_minutes": self.label_horizon_trading_minutes,
            "asset": self.asset,
            "session_id": self.session_id,
            "event_time": self.event_time.isoformat(),
            "feature_available_at": self.feature_available_at.isoformat(),
            "feature_value": self.feature_value,
            "feature_unavailable_reason": self.feature_unavailable_reason,
            "realized_label": self.realized_label,
            "label_available_at": self.label_available_at.isoformat() if self.label_available_at else None,
            "label_unavailable_reason": self.label_unavailable_reason,
        }


@dataclass(frozen=True, slots=True)
class USR1ObservationDiagnostics:
    input_row_count: int
    complete_bar_count: int
    incomplete_bar_count: int
    label_anchor_missing_count: int
    close_anchor_mismatch_count: int
    observation_count: int
    available_feature_count: int
    available_label_count: int
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-r1-observation-diagnostics.v1"

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def diagnostics_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-observation-diagnostics")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "passed": self.passed,
            "input_row_count": self.input_row_count,
            "complete_bar_count": self.complete_bar_count,
            "incomplete_bar_count": self.incomplete_bar_count,
            "label_anchor_missing_count": self.label_anchor_missing_count,
            "close_anchor_mismatch_count": self.close_anchor_mismatch_count,
            "observation_count": self.observation_count,
            "available_feature_count": self.available_feature_count,
            "available_label_count": self.available_label_count,
            "blockers": list(self.blockers),
        }
        if include_id:
            payload["diagnostics_id"] = self.diagnostics_id
        return payload


def materialize_us_r1_candidate_observations(
    rows: Sequence[Mapping[str, object]],
    denominator: USR1CandidateDenominator,
    *,
    role: USR1ObservationRole,
    signal_interval: BarInterval,
    label_horizon_trading_minutes: int,
    expected_assets: Sequence[str],
) -> tuple[tuple[USR1CandidateObservation, ...], USR1ObservationDiagnostics]:
    expected = tuple(dict.fromkeys(item.strip() for item in expected_assets if item.strip()))
    if not expected or len(expected) != len(tuple(expected_assets)):
        raise ValueError("US-R1 expected_assets must be non-empty and unique")
    expected_set = set(expected)
    histories: dict[str, list[USBaselineBar]] = defaultdict(list)
    observations: list[USR1CandidateObservation] = []
    complete_count = 0
    incomplete_count = 0
    anchor_missing = 0
    close_mismatch = 0
    available_features = 0
    available_labels = 0
    blockers: list[str] = []
    baseline_protocol = USBaselineProtocol()

    for raw in rows:
        asset = _text(raw.get("research_asset_id"), "row.research_asset_id")
        if asset not in expected_set:
            raise ValueError(f"US-R1 input contains asset outside EngineeringUniverse: {asset!r}")
        event_time = _aware(raw.get("event_time"), "row.event_time")
        available_at = _aware(raw.get("available_at"), "row.available_at")
        bar = USBaselineBar(
            event_time=event_time,
            available_at=available_at,
            session_id=_text(raw.get("session_id"), "row.session_id"),
            open=_float(raw.get("open"), "row.open"),
            high=_float(raw.get("high"), "row.high"),
            low=_float(raw.get("low"), "row.low"),
            close=_float(raw.get("close"), "row.close"),
            volume=_float(raw.get("volume"), "row.volume"),
            is_complete=_boolean(raw.get("is_complete"), "row.is_complete"),
        )
        history = histories[asset]
        if history and available_at <= history[-1].available_at:
            raise ValueError("US-R1 formation clock must be strictly increasing per asset")
        history.append(bar)
        if not bar.is_complete:
            incomplete_count += 1
            continue
        complete_count += 1

        if not _boolean(raw.get("label_row_present"), "row.label_row_present"):
            anchor_missing += 1
            blockers.append(f"label_anchor_missing:{asset}:{available_at.isoformat()}")
            continue
        source_available_at = _aware(raw.get("source_available_at"), "row.source_available_at")
        if source_available_at != available_at:
            raise ValueError("US-R1 label source availability must equal feature formation time")
        source_price = _float(raw.get("source_price"), "row.source_price")
        if abs(bar.close - source_price) > max(1e-12, abs(bar.close) * 1e-12):
            close_mismatch += 1
            blockers.append(f"close_anchor_mismatch:{asset}:{available_at.isoformat()}")
            continue

        label_available = _boolean(raw.get("label_available"), "row.label_available")
        if label_available:
            realized_label = _float(raw.get("label_value"), "row.label_value")
            label_available_at = _aware(raw.get("target_available_at"), "row.target_available_at")
            label_reason = None
            available_labels += 1
        else:
            realized_label = None
            label_available_at = None
            label_reason = _text(raw.get("unavailable_reason"), "row.unavailable_reason")
            if label_reason not in {"target_crosses_session", "target_minute_missing"}:
                raise ValueError("US-R1 input contains unsupported label unavailability reason")

        for provenance in denominator.candidates:
            candidate = provenance.candidate
            spec = candidate.compile_feature_spec()
            feature = evaluate_us_baseline_feature(
                spec,
                tuple(history),
                protocol=baseline_protocol,
            )
            if feature.value is not None:
                available_features += 1
            reason = feature.unavailable_reason.value if feature.unavailable_reason else None
            observations.append(
                USR1CandidateObservation(
                    candidate_id=candidate.candidate_id,
                    feature_spec_id=spec.spec_id,
                    role=role,
                    signal_interval=signal_interval,
                    label_horizon_trading_minutes=label_horizon_trading_minutes,
                    asset=asset,
                    session_id=bar.session_id,
                    event_time=feature.event_time,
                    feature_available_at=feature.available_at,
                    feature_value=feature.value,
                    feature_unavailable_reason=reason,
                    realized_label=realized_label,
                    label_available_at=label_available_at,
                    label_unavailable_reason=label_reason,
                )
            )

    if complete_count == 0:
        blockers.append("input:no_complete_bars")
    diagnostics = USR1ObservationDiagnostics(
        input_row_count=len(rows),
        complete_bar_count=complete_count,
        incomplete_bar_count=incomplete_count,
        label_anchor_missing_count=anchor_missing,
        close_anchor_mismatch_count=close_mismatch,
        observation_count=len(observations),
        available_feature_count=available_features,
        available_label_count=available_labels,
        blockers=tuple(dict.fromkeys(blockers)),
    )
    return tuple(observations), diagnostics


@dataclass(frozen=True, slots=True)
class USR1ObservationArtifact:
    execution_spec_id: str
    denominator_id: str
    input_plan_id: str
    role: USR1ObservationRole
    signal_interval: BarInterval
    label_horizon_trading_minutes: int
    row_count: int
    content_sha256: str
    output_filename: str
    schema_version: str = "finagent.us-r1-observation-artifact.v1"

    def __post_init__(self) -> None:
        if self.row_count < 0:
            raise ValueError("US-R1 observation row_count must be non-negative")
        digest = self.content_sha256.strip().lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("US-R1 observation content_sha256 must be SHA-256 hex")
        object.__setattr__(self, "content_sha256", digest)

    @property
    def artifact_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "execution_spec_id": self.execution_spec_id,
                "denominator_id": self.denominator_id,
                "input_plan_id": self.input_plan_id,
                "role": self.role.value,
                "signal_interval": self.signal_interval.value,
                "label_horizon_trading_minutes": self.label_horizon_trading_minutes,
                "row_count": self.row_count,
                "content_sha256": self.content_sha256,
            },
            prefix="us-r1-observations",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "execution_spec_id": self.execution_spec_id,
            "denominator_id": self.denominator_id,
            "input_plan_id": self.input_plan_id,
            "role": self.role.value,
            "signal_interval": self.signal_interval.value,
            "label_horizon_trading_minutes": self.label_horizon_trading_minutes,
            "row_count": self.row_count,
            "content_sha256": self.content_sha256,
            "output_filename": self.output_filename,
        }


def write_us_r1_observation_artifact(
    observations: Sequence[USR1CandidateObservation],
    output: str | Path,
    *,
    execution_spec: USR1FoldExecutionSpec,
    denominator: USR1CandidateDenominator,
    input_plan: USR1InputPlan,
) -> USR1ObservationArtifact:
    target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        observations,
        key=lambda item: (
            item.candidate_id,
            item.feature_available_at,
            item.asset,
        ),
    )
    digest = hashlib.sha256()
    with target.open("wb") as handle:
        for observation in ordered:
            payload = json.dumps(
                observation.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8") + b"\n"
            handle.write(payload)
            digest.update(payload)
    return USR1ObservationArtifact(
        execution_spec_id=execution_spec.execution_spec_id,
        denominator_id=denominator.denominator_id,
        input_plan_id=input_plan.plan_id,
        role=input_plan.role,
        signal_interval=input_plan.signal_interval,
        label_horizon_trading_minutes=input_plan.label_horizon_trading_minutes,
        row_count=len(ordered),
        content_sha256=digest.hexdigest(),
        output_filename=target.name,
    )


@dataclass(frozen=True, slots=True)
class USR1MaterializationSlice:
    role: USR1ObservationRole
    signal_interval: BarInterval
    label_horizon_trading_minutes: int
    input_plan_id: str
    input_materialization_id: str
    observation_artifact_id: str
    diagnostics_id: str
    input_row_count: int
    observation_row_count: int
    passed: bool
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-r1-materialization-slice.v1"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "role": self.role.value,
            "signal_interval": self.signal_interval.value,
            "label_horizon_trading_minutes": self.label_horizon_trading_minutes,
            "input_plan_id": self.input_plan_id,
            "input_materialization_id": self.input_materialization_id,
            "observation_artifact_id": self.observation_artifact_id,
            "diagnostics_id": self.diagnostics_id,
            "input_row_count": self.input_row_count,
            "observation_row_count": self.observation_row_count,
            "passed": self.passed,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class USR1FoldMaterializationManifest:
    research_protocol_id: str
    walk_forward_protocol_id: str
    execution_spec_id: str
    denominator_id: str
    formation_policy_id: str
    fold_id: str
    fold_ordinal: int
    verified_gap_trading_minutes: int
    required_gap_trading_minutes: int
    slices: tuple[USR1MaterializationSlice, ...]
    schema_version: str = "finagent.us-r1-fold-materialization-manifest.v1"

    def __post_init__(self) -> None:
        if self.fold_ordinal not in {1, 2, 3}:
            raise ValueError("US-R1 materialization fold ordinal must be 1,2,3")
        if self.verified_gap_trading_minutes < self.required_gap_trading_minutes:
            raise ValueError("US-R1 materialization manifest gap verification failed")
        expected = (
            (USR1ObservationRole.TRAIN, BarInterval.MINUTE_15, 60),
            (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_5, 60),
            (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_15, 30),
            (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_15, 60),
            (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_15, 120),
            (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_30, 60),
        )
        observed = tuple(
            (item.role, item.signal_interval, item.label_horizon_trading_minutes)
            for item in self.slices
        )
        if observed != expected:
            raise ValueError("US-R1 fold manifest must contain the exact six frozen evidence slices")

    @property
    def passed(self) -> bool:
        return all(item.passed for item in self.slices)

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(
            f"{item.role.value}:{item.signal_interval.value}:{item.label_horizon_trading_minutes}m:{blocker}"
            for item in self.slices
            for blocker in item.blockers
        )

    @property
    def manifest_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-fold-materialization")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "research_protocol_id": self.research_protocol_id,
            "walk_forward_protocol_id": self.walk_forward_protocol_id,
            "execution_spec_id": self.execution_spec_id,
            "denominator_id": self.denominator_id,
            "formation_policy_id": self.formation_policy_id,
            "fold_id": self.fold_id,
            "fold_ordinal": self.fold_ordinal,
            "verified_gap_trading_minutes": self.verified_gap_trading_minutes,
            "required_gap_trading_minutes": self.required_gap_trading_minutes,
            "slices": [item.to_dict() for item in self.slices],
            "passed": self.passed,
            "blockers": list(self.blockers),
            "scope": "materialized_multifrequency_observation_evidence_not_alpha_assessment",
            "status_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["manifest_id"] = self.manifest_id
        return payload


def build_us_r1_materialization_slice(
    *,
    input_plan: USR1InputPlan,
    input_materialization: MinuteMaterialization,
    observation_artifact: USR1ObservationArtifact,
    diagnostics: USR1ObservationDiagnostics,
) -> USR1MaterializationSlice:
    if input_materialization.plan_id != input_plan.plan_id:
        raise ValueError("US-R1 input materialization/plan identity mismatch")
    if observation_artifact.input_plan_id != input_plan.plan_id:
        raise ValueError("US-R1 observation artifact/input plan mismatch")
    return USR1MaterializationSlice(
        role=input_plan.role,
        signal_interval=input_plan.signal_interval,
        label_horizon_trading_minutes=input_plan.label_horizon_trading_minutes,
        input_plan_id=input_plan.plan_id,
        input_materialization_id=input_materialization.materialization_id,
        observation_artifact_id=observation_artifact.artifact_id,
        diagnostics_id=diagnostics.diagnostics_id,
        input_row_count=input_materialization.row_count,
        observation_row_count=observation_artifact.row_count,
        passed=diagnostics.passed,
        blockers=diagnostics.blockers,
    )

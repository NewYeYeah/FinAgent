from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from finagent.data.minute_store import (
    DEFAULT_DUCKDB_EXECUTION_POLICY,
    DuckDBExecutionPolicy,
    DuckDBParquetMinuteStore,
    count_plan_rows,
    fetch_plan_rows,
)
from finagent.data.minute_transform import (
    CalendarSessionizedMinuteStore,
    SameSessionLabelStore,
    SessionResampledMinuteStore,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import (
    AvailabilityPolicy,
    LabelHorizonUnit,
    LabelMetric,
    LabelSpec,
    ResearchPriceBasis,
)
from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence
from finagent.realtime.algorithm import AlgorithmRunner
from finagent.realtime.database_replay import DatabaseReplaySource
from finagent.realtime.events import RealtimeEventKind
from finagent.realtime.sources import (
    MarketDataSubscription,
    ReplayPacingMode,
    StrategyFreshnessBudget,
)
from finagent.realtime.streaming_research import USBaselineStreamingAlgorithm
from finagent.research.streaming_experiment_bridge import (
    StreamingExperimentLabel,
    build_streaming_research_evidence_bundle,
    evaluate_streaming_b0_with_existing_runner,
    materialize_streaming_a0_observations,
    materialize_streaming_b0_observations,
    materialize_streaming_r1_candidate_observations,
    streaming_experiment_rows,
)
from finagent.research.us_agent_value_evaluation import (
    USAgentValueEvaluationDenominator,
    materialize_us_a0_observations,
)
from finagent.research.us_baseline_evaluation import USBaselineObservation, USBaselineRunSpec
from finagent.research.us_baseline_materialization import (
    evaluate_materialized_us_baselines,
    materialize_us_baseline_observations,
)
from finagent.research.us_baselines import canonical_us_baseline_denominator
from finagent.research.us_r1_materialization import (
    USR1CandidateObservation,
    USR1ObservationRole,
    materialize_us_r1_candidate_observations,
)
from finagent.research.us_r1_protocol import USR1CandidateDenominator

_CAMPAIGN_SLICES = (
    (BarInterval.MINUTE_5, 60),
    (BarInterval.MINUTE_15, 30),
    (BarInterval.MINUTE_15, 60),
    (BarInterval.MINUTE_15, 120),
    (BarInterval.MINUTE_30, 60),
)
_CAMPAIGN_SURFACES = frozenset(
    {
        "rows:5m:60m",
        "rows:15m:30m",
        "rows:15m:60m",
        "rows:15m:120m",
        "rows:30m:60m",
        "b0:observations",
        "b0:materialization-diagnostics",
        "b0:evaluation",
        "a0:observations",
        "a0:materialization-diagnostics",
        "r1:TRAIN:15m:60m",
        "r1:EVALUATION:5m:60m",
        "r1:EVALUATION:15m:30m",
        "r1:EVALUATION:15m:60m",
        "r1:EVALUATION:15m:120m",
        "r1:EVALUATION:30m:60m",
    }
)


def _hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        _normalize(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _digest(payload: object) -> str:
    encoded = json.dumps(
        _normalize(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize(value: object) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("campaign payload datetime must be timezone-aware")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported campaign payload type: {type(value)!r}")


def _aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    return float(value)


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


class ReplayCampaignSourceScope(StrEnum):
    FIXTURE = "FIXTURE"
    LOCAL_BOUNDED = "LOCAL_BOUNDED"


@dataclass(frozen=True, slots=True)
class ReplayExperimentCampaignSpec:
    source_scope: ReplayCampaignSourceScope
    required_symbols: tuple[str, ...]
    event_start: datetime
    event_end: datetime
    maximum_batch_rows: int = 100_000
    schema_version: str = "finagent.replay-experiment-campaign-spec.v1"

    def __post_init__(self) -> None:
        symbols = tuple(sorted(_text(item, "required_symbols[]") for item in self.required_symbols))
        if len(symbols) < 2 or len(symbols) != len(set(symbols)):
            raise ValueError("campaign requires at least two unique symbols")
        start = _aware(self.event_start, "event_start")
        end = _aware(self.event_end, "event_end")
        if end <= start:
            raise ValueError("campaign event_end must be later than event_start")
        if self.maximum_batch_rows < 1 or self.maximum_batch_rows > 1_000_000:
            raise ValueError("maximum_batch_rows must be in 1..1000000")
        object.__setattr__(self, "required_symbols", symbols)
        object.__setattr__(self, "event_start", start)
        object.__setattr__(self, "event_end", end)

    @property
    def spec_id(self) -> str:
        return _hash(self.to_dict(include_id=False), prefix="replay-experiment-campaign-spec")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "source_scope": self.source_scope.value,
            "required_symbols": list(self.required_symbols),
            "event_start": self.event_start.isoformat(),
            "event_end": self.event_end.isoformat(),
            "maximum_batch_rows": self.maximum_batch_rows,
            "engineering_only": True,
            "research_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["spec_id"] = self.spec_id
        return payload


@dataclass(frozen=True, slots=True)
class ReplayBatchSliceEvidence:
    signal_interval: BarInterval
    label_horizon_trading_minutes: int
    resampling_spec_id: str
    label_spec_id: str
    bar_plan_id: str
    label_plan_id: str
    source_data_version: str
    row_count: int
    row_digest: str
    schema_version: str = "finagent.replay-batch-slice-evidence.v1"

    @property
    def slice_id(self) -> str:
        return _hash(self.to_dict(include_id=False), prefix="replay-batch-slice")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "signal_interval": self.signal_interval.value,
            "label_horizon_trading_minutes": self.label_horizon_trading_minutes,
            "resampling_spec_id": self.resampling_spec_id,
            "label_spec_id": self.label_spec_id,
            "bar_plan_id": self.bar_plan_id,
            "label_plan_id": self.label_plan_id,
            "source_data_version": self.source_data_version,
            "row_count": self.row_count,
            "row_digest": self.row_digest,
            "engineering_only": True,
        }
        if include_id:
            payload["slice_id"] = self.slice_id
        return payload


@dataclass(frozen=True, slots=True)
class ReplayExperimentParityCheck:
    surface: str
    streaming_count: int
    batch_count: int
    streaming_digest: str
    batch_digest: str
    equal: bool
    schema_version: str = "finagent.replay-experiment-parity-check.v1"

    @property
    def check_id(self) -> str:
        return _hash(self.to_dict(include_id=False), prefix="replay-experiment-parity")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "surface": self.surface,
            "streaming_count": self.streaming_count,
            "batch_count": self.batch_count,
            "streaming_digest": self.streaming_digest,
            "batch_digest": self.batch_digest,
            "equal": self.equal,
        }
        if include_id:
            payload["check_id"] = self.check_id
        return payload


@dataclass(frozen=True, slots=True)
class ReplayExperimentCampaignReport:
    spec: ReplayExperimentCampaignSpec
    source_manifest_id: str
    source_run_report_id: str
    streaming_bundle_id: str
    b0_run_spec_id: str
    b0_denominator_id: str
    a0_denominator_id: str
    r1_denominator_id: str
    batch_slices: tuple[ReplayBatchSliceEvidence, ...]
    parity_checks: tuple[ReplayExperimentParityCheck, ...]
    schema_version: str = "finagent.replay-experiment-campaign-report.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "source_manifest_id",
            "source_run_report_id",
            "streaming_bundle_id",
            "b0_run_spec_id",
            "b0_denominator_id",
            "a0_denominator_id",
            "r1_denominator_id",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        if self.b0_denominator_id != canonical_us_baseline_denominator().denominator_id:
            raise ValueError("campaign report must bind the canonical B0 denominator")
        slice_keys = tuple(
            (item.signal_interval, item.label_horizon_trading_minutes)
            for item in self.batch_slices
        )
        if len(slice_keys) != len(_CAMPAIGN_SLICES) or set(slice_keys) != set(_CAMPAIGN_SLICES):
            raise ValueError("campaign report requires the frozen five unique batch slices")
        surfaces = tuple(item.surface for item in self.parity_checks)
        if len(surfaces) != len(_CAMPAIGN_SURFACES) or set(surfaces) != _CAMPAIGN_SURFACES:
            raise ValueError("campaign report requires the frozen sixteen unique parity surfaces")

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(f"parity:{item.surface}" for item in self.parity_checks if not item.equal)

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def report_id(self) -> str:
        return _hash(self.to_dict(include_id=False), prefix="replay-experiment-campaign")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "passed": self.passed,
            "blockers": list(self.blockers),
            "spec": self.spec.to_dict(),
            "source_manifest_id": self.source_manifest_id,
            "source_run_report_id": self.source_run_report_id,
            "streaming_bundle_id": self.streaming_bundle_id,
            "b0_run_spec_id": self.b0_run_spec_id,
            "b0_denominator_id": self.b0_denominator_id,
            "a0_denominator_id": self.a0_denominator_id,
            "r1_denominator_id": self.r1_denominator_id,
            "batch_slices": [item.to_dict() for item in self.batch_slices],
            "parity_checks": [item.to_dict() for item in self.parity_checks],
            "engineering_only": True,
            "formal_us_b0_operator_invoked": False,
            "us_d3_certification_consumed": False,
            "certification_authority": False,
            "research_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


@dataclass(frozen=True, slots=True)
class _BatchSlice:
    evidence: ReplayBatchSliceEvidence
    rows: tuple[dict[str, object], ...]


def _label_spec(horizon: int) -> LabelSpec:
    if horizon not in {30, 60, 120}:
        raise ValueError("campaign label horizon must be 30m/60m/120m")
    name = (
        "us_same_session_60m_simple_return_raw"
        if horizon == 60
        else f"engineering_same_session_{horizon}m_simple_return_raw"
    )
    return LabelSpec(
        metric=LabelMetric.SIMPLE_RETURN,
        horizon=horizon,
        horizon_unit=LabelHorizonUnit.TRADING_MINUTES,
        allow_cross_session=False,
        price_basis=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
        name=name,
    )


def _bar_query(spec: ReplayExperimentCampaignSpec, interval: BarInterval) -> MarketDataQuery:
    return MarketDataQuery(
        market_id="XNYS",
        assets=spec.required_symbols,
        start=spec.event_start,
        end=spec.event_end + timedelta(minutes=1),
        interval=interval,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )


def _label_query(spec: ReplayExperimentCampaignSpec) -> MarketDataQuery:
    return MarketDataQuery(
        market_id="XNYS",
        assets=spec.required_symbols,
        start=spec.event_start,
        end=spec.event_end + timedelta(minutes=1),
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.CLOSE,),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )


def _batch_row(
    bar: Mapping[str, object],
    label: Mapping[str, object] | None,
) -> dict[str, object]:
    label_present = label is not None
    source_price = None if label is None else label.get("source_price")
    return {
        "research_asset_id": _text(bar.get("research_asset_id"), "bar.research_asset_id"),
        "session_id": _text(bar.get("session_id"), "bar.session_id"),
        "event_time": _aware(bar.get("event_time"), "bar.event_time"),
        "available_at": _aware(bar.get("available_at"), "bar.available_at"),
        "open": _number(bar.get("open"), "bar.open"),
        "high": _number(bar.get("high"), "bar.high"),
        "low": _number(bar.get("low"), "bar.low"),
        "close": _number(bar.get("close"), "bar.close"),
        "volume": _number(bar.get("volume"), "bar.volume"),
        "bar_index": int(_number(bar.get("bar_index"), "bar.bar_index")),
        "observed_minute_count": int(
            _number(bar.get("observed_minute_count"), "bar.observed_minute_count")
        ),
        "expected_minute_count": int(
            _number(bar.get("expected_minute_count"), "bar.expected_minute_count")
        ),
        "coverage_ratio": _number(bar.get("coverage_ratio"), "bar.coverage_ratio"),
        "is_complete": _boolean(bar.get("is_complete"), "bar.is_complete"),
        "label_row_present": label_present,
        "source_event_time": None if label is None else label.get("source_event_time"),
        "source_available_at": None if label is None else label.get("source_available_at"),
        "source_price": source_price,
        "target_event_time": None if label is None else label.get("target_event_time"),
        "target_available_at": None if label is None else label.get("target_available_at"),
        "label_value": None if label is None else label.get("label_value"),
        "label_available": False
        if label is None
        else _boolean(label.get("label_available"), "label.label_available"),
        "unavailable_reason": None if label is None else label.get("unavailable_reason"),
        "close_anchor_difference": (
            None
            if source_price is None
            else abs(
                _number(bar.get("close"), "bar.close")
                - _number(source_price, "label.source_price")
            )
        ),
    }


def _fetch_batch_slice(
    resampled: SessionResampledMinuteStore,
    labels: SameSessionLabelStore,
    *,
    spec: ReplayExperimentCampaignSpec,
    interval: BarInterval,
    horizon: int,
    policy: DuckDBExecutionPolicy,
    temp_directory: str | Path | None,
) -> _BatchSlice:
    bar_plan, resampling = resampled.plan(_bar_query(spec, interval))
    label_plan, label_evidence = labels.plan(_label_query(spec), _label_spec(horizon))
    bar_count = count_plan_rows(bar_plan, policy=policy, temp_directory=temp_directory)
    label_count = count_plan_rows(label_plan, policy=policy, temp_directory=temp_directory)
    if bar_count > spec.maximum_batch_rows or label_count > spec.maximum_batch_rows:
        raise ValueError("campaign batch slice exceeds maximum_batch_rows")
    bars = fetch_plan_rows(
        bar_plan,
        limit=bar_count,
        policy=policy,
        temp_directory=temp_directory,
    )
    label_rows = fetch_plan_rows(
        label_plan,
        limit=label_count,
        policy=policy,
        temp_directory=temp_directory,
    )
    label_by_key = {
        (
            _text(row.get("research_asset_id"), "label.research_asset_id"),
            row.get("session_date"),
            _aware(row.get("source_available_at"), "label.source_available_at"),
        ): row
        for row in label_rows
    }
    rows = tuple(
        _batch_row(
            bar,
            label_by_key.get(
                (
                    _text(bar.get("research_asset_id"), "bar.research_asset_id"),
                    bar.get("session_date"),
                    _aware(bar.get("available_at"), "bar.available_at"),
                )
            ),
        )
        for bar in bars
    )
    evidence = ReplayBatchSliceEvidence(
        signal_interval=interval,
        label_horizon_trading_minutes=horizon,
        resampling_spec_id=resampling.spec_id,
        label_spec_id=label_evidence.label_spec_id,
        bar_plan_id=bar_plan.plan_id,
        label_plan_id=label_plan.plan_id,
        source_data_version=resampling.source_data_version,
        row_count=len(rows),
        row_digest=_digest(rows),
    )
    return _BatchSlice(evidence=evidence, rows=rows)


def _labels_from_batch(slices: Sequence[_BatchSlice]) -> tuple[StreamingExperimentLabel, ...]:
    labels: dict[tuple[str, BarInterval, int, datetime], StreamingExperimentLabel] = {}
    for batch_slice in slices:
        interval = batch_slice.evidence.signal_interval
        horizon = batch_slice.evidence.label_horizon_trading_minutes
        for row in batch_slice.rows:
            if row["label_row_present"] is not True:
                continue
            formation_event_time = _aware(row["event_time"], "row.event_time")
            source_available_at = _aware(row["source_available_at"], "row.source_available_at")
            price_event_time = _aware(row["source_event_time"], "row.source_event_time")
            target_event_time = (
                None
                if row["target_event_time"] is None
                else _aware(row["target_event_time"], "row.target_event_time")
            )
            target_available_at = (
                None
                if row["target_available_at"] is None
                else _aware(row["target_available_at"], "row.target_available_at")
            )
            label = StreamingExperimentLabel(
                asset=_text(row["research_asset_id"], "row.research_asset_id"),
                session_id=_text(row["session_id"], "row.session_id"),
                signal_interval=interval,
                label_horizon_trading_minutes=horizon,
                source_event_time=formation_event_time,
                source_available_at=source_available_at,
                source_price=_number(row["source_price"], "row.source_price"),
                label_available=_boolean(row["label_available"], "row.label_available"),
                target_event_time=target_event_time,
                target_available_at=target_available_at,
                label_value=(
                    None
                    if row["label_value"] is None
                    else _number(row["label_value"], "row.label_value")
                ),
                unavailable_reason=(
                    None
                    if row["unavailable_reason"] is None
                    else _text(row["unavailable_reason"], "row.unavailable_reason")
                ),
                price_event_time=price_event_time,
            )
            key = label.semantic_key
            previous = labels.get(key)
            if previous is not None and previous.label_id != label.label_id:
                raise ValueError("batch slices produced conflicting label evidence")
            labels[key] = label
    return tuple(
        sorted(
            labels.values(),
            key=lambda item: (
                item.source_available_at,
                item.asset,
                item.signal_interval.value,
                item.label_horizon_trading_minutes,
            ),
        )
    )


def _baseline_observation_payload(
    values: Mapping[str, Sequence[USBaselineObservation]],
) -> dict[str, list[dict[str, object]]]:
    payload: dict[str, list[dict[str, object]]] = {}
    for feature_id in sorted(values):
        rows = sorted(
            values[feature_id],
            key=lambda item: (item.feature_available_at, item.asset),
        )
        payload[feature_id] = [
            {
                "feature_id": item.feature_id,
                "feature_spec_id": item.feature_spec_id,
                "asset": item.asset,
                "event_time": item.event_time,
                "feature_available_at": item.feature_available_at,
                "eligible_at_formation": item.eligible_at_formation,
                "feature_value": item.feature_value,
                "realized_label": item.realized_label,
                "label_available_at": item.label_available_at,
                "label_unavailable_reason": item.label_unavailable_reason,
            }
            for item in rows
        ]
    return payload


def _r1_payload(values: Sequence[USR1CandidateObservation]) -> list[dict[str, object]]:
    return [
        item.to_dict()
        for item in sorted(
            values,
            key=lambda item: (
                item.feature_available_at,
                item.asset,
                item.candidate_id,
            ),
        )
    ]


def _parity(
    surface: str,
    streaming: object,
    batch: object,
    *,
    streaming_count: int,
    batch_count: int,
) -> ReplayExperimentParityCheck:
    streaming_digest = _digest(streaming)
    batch_digest = _digest(batch)
    return ReplayExperimentParityCheck(
        surface=surface,
        streaming_count=streaming_count,
        batch_count=batch_count,
        streaming_digest=streaming_digest,
        batch_digest=batch_digest,
        equal=streaming_count == batch_count and streaming_digest == batch_digest,
    )


def _slice_map(slices: Sequence[_BatchSlice]) -> dict[tuple[BarInterval, int], _BatchSlice]:
    result = {
        (
            item.evidence.signal_interval,
            item.evidence.label_horizon_trading_minutes,
        ): item
        for item in slices
    }
    if set(result) != set(_CAMPAIGN_SLICES):
        raise ValueError("campaign requires the frozen five interval/horizon slices")
    return result


async def run_replay_experiment_campaign(
    store: DuckDBParquetMinuteStore,
    calendar: TradingCalendarEvidence,
    *,
    spec: ReplayExperimentCampaignSpec,
    b0_run_spec: USBaselineRunSpec,
    a0_denominator: USAgentValueEvaluationDenominator,
    r1_denominator: USR1CandidateDenominator,
    execution_policy: DuckDBExecutionPolicy = DEFAULT_DUCKDB_EXECUTION_POLICY,
    temp_directory: str | Path | None = None,
) -> ReplayExperimentCampaignReport:
    if b0_run_spec.denominator_id != canonical_us_baseline_denominator().denominator_id:
        raise ValueError("campaign B0 run spec must bind the canonical B0 denominator")
    source = DatabaseReplaySource(
        store,
        execution_policy=execution_policy,
        temp_directory=temp_directory,
    )
    subscription = MarketDataSubscription(
        symbols=spec.required_symbols,
        event_kinds=(RealtimeEventKind.BAR,),
        start=spec.event_start + timedelta(minutes=1),
        end=spec.event_end + timedelta(minutes=1),
        interval_seconds=60,
        pacing_mode=ReplayPacingMode.FAST,
    )
    algorithm_report = await AlgorithmRunner().run(
        source,
        subscription,
        USBaselineStreamingAlgorithm(calendar, required_symbols=spec.required_symbols),
        freshness_budget=StrategyFreshnessBudget(
            maximum_source_delay_seconds=0.0,
            maximum_event_age_seconds=120.0,
            allow_replay=True,
        ),
    )
    sessionized = CalendarSessionizedMinuteStore(store, calendar)
    resampled = SessionResampledMinuteStore(sessionized)
    label_store = SameSessionLabelStore(sessionized)
    batch_slices = tuple(
        _fetch_batch_slice(
            resampled,
            label_store,
            spec=spec,
            interval=interval,
            horizon=horizon,
            policy=execution_policy,
            temp_directory=temp_directory,
        )
        for interval, horizon in _CAMPAIGN_SLICES
    )
    labels = _labels_from_batch(batch_slices)
    bundle = build_streaming_research_evidence_bundle(
        algorithm_report,
        required_symbols=spec.required_symbols,
        labels=labels,
    )
    if bundle.required_symbols != spec.required_symbols:
        raise ValueError("streaming bundle denominator differs from campaign spec")
    by_slice = _slice_map(batch_slices)
    checks: list[ReplayExperimentParityCheck] = []

    for interval, horizon in _CAMPAIGN_SLICES:
        batch_slice = by_slice[(interval, horizon)]
        streaming_rows = streaming_experiment_rows(
            bundle,
            signal_interval=interval,
            label_horizon_trading_minutes=horizon,
        )
        checks.append(
            _parity(
                f"rows:{interval.value}:{horizon}m",
                streaming_rows,
                batch_slice.rows,
                streaming_count=len(streaming_rows),
                batch_count=len(batch_slice.rows),
            )
        )

    batch_15m_60 = by_slice[(BarInterval.MINUTE_15, 60)].rows
    streaming_b0, streaming_b0_diag = materialize_streaming_b0_observations(
        bundle,
        b0_run_spec,
    )
    batch_b0, batch_b0_diag = materialize_us_baseline_observations(
        batch_15m_60,
        canonical_us_baseline_denominator(),
        expected_assets=spec.required_symbols,
    )
    streaming_b0_payload = _baseline_observation_payload(streaming_b0)
    batch_b0_payload = _baseline_observation_payload(batch_b0)
    checks.append(
        _parity(
            "b0:observations",
            streaming_b0_payload,
            batch_b0_payload,
            streaming_count=sum(len(items) for items in streaming_b0.values()),
            batch_count=sum(len(items) for items in batch_b0.values()),
        )
    )
    checks.append(
        _parity(
            "b0:materialization-diagnostics",
            streaming_b0_diag.to_dict(),
            batch_b0_diag.to_dict(),
            streaming_count=1,
            batch_count=1,
        )
    )
    streaming_b0_eval, _ = evaluate_streaming_b0_with_existing_runner(bundle, b0_run_spec)
    batch_b0_eval = evaluate_materialized_us_baselines(
        canonical_us_baseline_denominator(),
        batch_b0,
        run_spec=b0_run_spec,
    )
    checks.append(
        _parity(
            "b0:evaluation",
            streaming_b0_eval.to_dict(),
            batch_b0_eval.to_dict(),
            streaming_count=len(streaming_b0_eval.candidates),
            batch_count=len(batch_b0_eval.candidates),
        )
    )

    streaming_a0, streaming_a0_diag = materialize_streaming_a0_observations(
        bundle,
        a0_denominator,
    )
    batch_a0, batch_a0_diag = materialize_us_a0_observations(
        batch_15m_60,
        a0_denominator,
        expected_assets=spec.required_symbols,
    )
    checks.append(
        _parity(
            "a0:observations",
            _baseline_observation_payload(streaming_a0),
            _baseline_observation_payload(batch_a0),
            streaming_count=sum(len(items) for items in streaming_a0.values()),
            batch_count=sum(len(items) for items in batch_a0.values()),
        )
    )
    checks.append(
        _parity(
            "a0:materialization-diagnostics",
            streaming_a0_diag.to_dict(),
            batch_a0_diag.to_dict(),
            streaming_count=1,
            batch_count=1,
        )
    )

    r1_slices = (
        (USR1ObservationRole.TRAIN, BarInterval.MINUTE_15, 60),
        (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_5, 60),
        (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_15, 30),
        (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_15, 60),
        (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_15, 120),
        (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_30, 60),
    )
    for role, interval, horizon in r1_slices:
        batch_rows = by_slice[(interval, horizon)].rows
        streaming_r1, _streaming_diag = materialize_streaming_r1_candidate_observations(
            bundle,
            r1_denominator,
            role=role,
            signal_interval=interval,
            label_horizon_trading_minutes=horizon,
        )
        batch_r1, _batch_diag = materialize_us_r1_candidate_observations(
            batch_rows,
            r1_denominator,
            role=role,
            signal_interval=interval,
            label_horizon_trading_minutes=horizon,
            expected_assets=spec.required_symbols,
        )
        checks.append(
            _parity(
                f"r1:{role.value}:{interval.value}:{horizon}m",
                _r1_payload(streaming_r1),
                _r1_payload(batch_r1),
                streaming_count=len(streaming_r1),
                batch_count=len(batch_r1),
            )
        )

    return ReplayExperimentCampaignReport(
        spec=spec,
        source_manifest_id=store.manifest.manifest_id,
        source_run_report_id=algorithm_report.report_id,
        streaming_bundle_id=bundle.bundle_id,
        b0_run_spec_id=b0_run_spec.spec_id,
        b0_denominator_id=canonical_us_baseline_denominator().denominator_id,
        a0_denominator_id=a0_denominator.denominator_id,
        r1_denominator_id=r1_denominator.denominator_id,
        batch_slices=tuple(item.evidence for item in batch_slices),
        parity_checks=tuple(checks),
    )


def write_replay_experiment_campaign_report(
    report: ReplayExperimentCampaignReport,
    output: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    target = Path(output).expanduser().resolve()
    if target.exists() and not overwrite:
        raise FileExistsError(f"campaign report already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target

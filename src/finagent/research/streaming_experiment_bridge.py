from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from finagent.domain.market_bars import BarInterval
from finagent.realtime.algorithm import AlgorithmRunReport
from finagent.realtime.events import BarEvent
from finagent.realtime.serialization import realtime_event_from_dict
from finagent.realtime.streaming_features import (
    StreamingCrossSectionSnapshot,
    StreamingFeatureSnapshot,
)
from finagent.realtime.streaming_resample import StreamingResampledBar
from finagent.realtime.streaming_research import StreamingResearchUpdate
from finagent.research.us_agent_value_evaluation import (
    USAgentValueEvaluationDenominator,
    materialize_us_a0_observations,
)
from finagent.research.us_baseline_evaluation import (
    USBaselineEvaluationReport,
    USBaselineObservation,
    USBaselineRunSpec,
)
from finagent.research.us_baseline_materialization import (
    USBaselineCandidateMaterializationCheck,
    USBaselineMaterializationDiagnostics,
    evaluate_materialized_us_baselines,
)
from finagent.research.us_baselines import (
    USBaselineFeatureEvaluation,
    USBaselineUnavailableReason,
    canonical_us_baseline_denominator,
)
from finagent.research.us_r1_materialization import (
    USR1CandidateObservation,
    USR1ObservationDiagnostics,
    USR1ObservationRole,
    materialize_us_r1_candidate_observations,
)
from finagent.research.us_r1_protocol import USR1CandidateDenominator

_ALLOWED_INTERVALS = frozenset(
    {BarInterval.MINUTE_5, BarInterval.MINUTE_15, BarInterval.MINUTE_30}
)
_ALLOWED_LABEL_HORIZONS = frozenset({30, 60, 120})
_ALLOWED_LABEL_UNAVAILABLE = frozenset(
    {"target_crosses_session", "target_minute_missing"}
)
_R1_EVALUATION_SLICES = frozenset(
    {
        (BarInterval.MINUTE_5, 60),
        (BarInterval.MINUTE_15, 30),
        (BarInterval.MINUTE_15, 60),
        (BarInterval.MINUTE_15, 120),
        (BarInterval.MINUTE_30, 60),
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


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be integer-like")
    rendered = int(value)
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field_name} must be integer-like")
    return rendered


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be numeric")
    rendered = float(value)
    if not math.isfinite(rendered):
        raise ValueError(f"{field_name} must be finite")
    return rendered


def _optional_number(value: object, field_name: str) -> float | None:
    return None if value is None else _number(value, field_name)


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _aware(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(_text(value, field_name))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _optional_aware(value: object, field_name: str) -> datetime | None:
    return None if value is None else _aware(value, field_name)


def _interval_seconds(interval: BarInterval) -> int:
    minutes = interval.minutes
    if minutes is None or interval not in _ALLOWED_INTERVALS:
        raise ValueError("streaming experiment bridge supports only 5m/15m/30m")
    return minutes * 60


@dataclass(frozen=True, slots=True)
class StreamingExperimentLabel:
    asset: str
    session_id: str
    signal_interval: BarInterval
    label_horizon_trading_minutes: int
    source_event_time: datetime
    source_available_at: datetime
    source_price: float
    label_available: bool
    target_event_time: datetime | None = None
    target_available_at: datetime | None = None
    label_value: float | None = None
    unavailable_reason: str | None = None
    schema_version: str = "finagent.streaming-experiment-label.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", _text(self.asset, "asset"))
        object.__setattr__(self, "session_id", _text(self.session_id, "session_id"))
        if self.signal_interval not in _ALLOWED_INTERVALS:
            raise ValueError("streaming experiment label interval must be 5m/15m/30m")
        if self.label_horizon_trading_minutes not in _ALLOWED_LABEL_HORIZONS:
            raise ValueError("streaming experiment label horizon must be 30m/60m/120m")
        object.__setattr__(
            self,
            "source_event_time",
            _aware(self.source_event_time, "source_event_time"),
        )
        object.__setattr__(
            self,
            "source_available_at",
            _aware(self.source_available_at, "source_available_at"),
        )
        source_price = _number(self.source_price, "source_price")
        if source_price <= 0:
            raise ValueError("source_price must be positive")
        object.__setattr__(self, "source_price", source_price)
        target_event_time = _optional_aware(self.target_event_time, "target_event_time")
        target_available_at = _optional_aware(self.target_available_at, "target_available_at")
        object.__setattr__(self, "target_event_time", target_event_time)
        object.__setattr__(self, "target_available_at", target_available_at)
        if self.label_available:
            if self.label_value is None or target_event_time is None or target_available_at is None:
                raise ValueError("available label requires value and target clocks")
            value = _number(self.label_value, "label_value")
            object.__setattr__(self, "label_value", value)
            if self.unavailable_reason is not None:
                raise ValueError("available label cannot carry unavailable_reason")
            if target_available_at <= self.source_available_at:
                raise ValueError("label target must mature after feature formation")
        else:
            if self.label_value is not None:
                raise ValueError("unavailable label cannot carry label_value")
            if target_event_time is not None or target_available_at is not None:
                raise ValueError("unavailable label cannot carry target clocks")
            reason = _text(self.unavailable_reason, "unavailable_reason")
            if reason not in _ALLOWED_LABEL_UNAVAILABLE:
                raise ValueError("unsupported streaming label unavailable reason")
            object.__setattr__(self, "unavailable_reason", reason)

    @property
    def label_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="streaming-experiment-label")

    @property
    def semantic_key(self) -> tuple[str, BarInterval, int, datetime]:
        return (
            self.asset,
            self.signal_interval,
            self.label_horizon_trading_minutes,
            self.source_available_at,
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "asset": self.asset,
            "session_id": self.session_id,
            "signal_interval": self.signal_interval.value,
            "label_horizon_trading_minutes": self.label_horizon_trading_minutes,
            "source_event_time": self.source_event_time.isoformat(),
            "source_available_at": self.source_available_at.isoformat(),
            "source_price": self.source_price,
            "target_event_time": (
                self.target_event_time.isoformat() if self.target_event_time is not None else None
            ),
            "target_available_at": (
                self.target_available_at.isoformat() if self.target_available_at is not None else None
            ),
            "label_value": self.label_value,
            "label_available": self.label_available,
            "unavailable_reason": self.unavailable_reason,
        }
        if include_id:
            payload["label_id"] = self.label_id
        return payload


@dataclass(frozen=True, slots=True)
class StreamingResearchEvidenceBundle:
    source_run_report_id: str
    source_profile_id: str
    subscription_id: str
    update_ids: tuple[str, ...]
    denominator_id: str
    required_symbols: tuple[str, ...]
    resampled_bars: tuple[StreamingResampledBar, ...]
    feature_snapshots: tuple[StreamingFeatureSnapshot, ...]
    cross_section_snapshots: tuple[StreamingCrossSectionSnapshot, ...]
    labels: tuple[StreamingExperimentLabel, ...]
    schema_version: str = "finagent.streaming-research-evidence-bundle.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "source_run_report_id",
            "source_profile_id",
            "subscription_id",
            "denominator_id",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        updates = tuple(_text(update_id, "update_ids[]") for update_id in self.update_ids)
        if not updates or len(updates) != len(set(updates)):
            raise ValueError("streaming evidence update_ids must be non-empty and unique")
        object.__setattr__(self, "update_ids", updates)
        symbols = tuple(sorted(_text(symbol, "required_symbols[]") for symbol in self.required_symbols))
        if not symbols or len(symbols) != len(set(symbols)):
            raise ValueError("streaming evidence required_symbols must be non-empty and unique")
        object.__setattr__(self, "required_symbols", symbols)
        if not self.resampled_bars or not self.feature_snapshots or not self.cross_section_snapshots:
            raise ValueError("streaming experiment evidence requires bars, features and cross-sections")
        if not self.labels:
            raise ValueError("streaming experiment evidence requires explicit label evidence")
        if self.denominator_id != canonical_us_baseline_denominator().denominator_id:
            raise ValueError("streaming evidence must bind the canonical US-B0 denominator")
        self._validate_content()

    def _validate_content(self) -> None:
        bar_by_key: dict[tuple[str, int, datetime], StreamingResampledBar] = {}
        bar_by_id: dict[str, StreamingResampledBar] = {}
        for resampled in self.resampled_bars:
            key = (resampled.bar.symbol, resampled.bar.interval_seconds, resampled.bar.event_time)
            previous_bar = bar_by_key.get(key)
            if (
                previous_bar is not None
                and previous_bar.resampled_bar_id != resampled.resampled_bar_id
            ):
                raise ValueError("conflicting resampled bars share one semantic key")
            bar_by_key[key] = resampled
            if resampled.resampled_bar_id in bar_by_id:
                raise ValueError("duplicate resampled_bar_id in streaming evidence")
            bar_by_id[resampled.resampled_bar_id] = resampled

        feature_by_id: dict[str, StreamingFeatureSnapshot] = {}
        feature_groups: dict[tuple[datetime, datetime, str, str], set[str]] = defaultdict(set)
        for feature in self.feature_snapshots:
            if feature.denominator_id != self.denominator_id:
                raise ValueError("streaming feature denominator differs from bundle denominator")
            if feature.symbol not in self.required_symbols:
                raise ValueError("streaming feature symbol lies outside required denominator")
            bar = bar_by_id.get(feature.resampled_bar_id)
            if bar is None:
                raise ValueError("streaming feature refers to a missing resampled bar")
            if bar.bar.symbol != feature.symbol or bar.bar.interval_seconds != 15 * 60:
                raise ValueError("streaming feature must refer to its canonical 15m symbol bar")
            if bar.bar.event_time != feature.event_time or bar.available_at != feature.available_at:
                raise ValueError("streaming feature/bar clock mismatch")
            if bar.session_id != feature.session_id:
                raise ValueError("streaming feature/bar session mismatch")
            if feature.snapshot_id in feature_by_id:
                raise ValueError("duplicate feature snapshot identity in bundle")
            feature_by_id[feature.snapshot_id] = feature
            group_key = (
                feature.event_time,
                feature.available_at,
                feature.session_id,
                feature.denominator_id,
            )
            if feature.symbol in feature_groups[group_key]:
                raise ValueError("duplicate feature snapshot symbol inside one formation")
            feature_groups[group_key].add(feature.symbol)

        expected_symbols = set(self.required_symbols)
        if any(group_symbols != expected_symbols for group_symbols in feature_groups.values()):
            raise ValueError("partial streaming feature denominator cannot enter experiment evidence")

        cross_groups: dict[tuple[datetime, datetime, str, str], str] = {}
        for cross_section in self.cross_section_snapshots:
            if cross_section.denominator_id != self.denominator_id:
                raise ValueError("cross-section denominator differs from bundle denominator")
            if cross_section.required_symbols != self.required_symbols:
                raise ValueError("cross-section required symbols differ from bundle denominator")
            group_key = (
                cross_section.event_time,
                cross_section.available_at,
                cross_section.session_id,
                cross_section.denominator_id,
            )
            if group_key in cross_groups:
                raise ValueError("duplicate cross-section formation in streaming evidence")
            expected_ids = tuple(
                snapshot.snapshot_id
                for snapshot in sorted(
                    cross_section.feature_snapshots,
                    key=lambda value: value.symbol,
                )
            )
            actual_ids = tuple(
                feature_by_id[snapshot_id].snapshot_id
                for snapshot_id in expected_ids
                if snapshot_id in feature_by_id
            )
            if actual_ids != expected_ids:
                raise ValueError("cross-section references feature snapshot outside bundle")
            cross_groups[group_key] = cross_section.snapshot_id
        if set(cross_groups) != set(feature_groups):
            raise ValueError("streaming evidence requires one full cross-section per feature formation")

        label_keys: dict[
            tuple[str, BarInterval, int, datetime],
            StreamingExperimentLabel,
        ] = {}
        for label in self.labels:
            previous_label = label_keys.get(label.semantic_key)
            if previous_label is not None:
                raise ValueError("duplicate streaming label semantic key")
            label_keys[label.semantic_key] = label
            interval_seconds = _interval_seconds(label.signal_interval)
            bar_key = (label.asset, interval_seconds, label.source_event_time)
            label_bar = bar_by_key.get(bar_key)
            if label_bar is None:
                raise ValueError("streaming label anchor is not backed by persisted resampled bar")
            if label_bar.session_id != label.session_id:
                raise ValueError("streaming label/bar session mismatch")
            if label_bar.available_at != label.source_available_at:
                raise ValueError("streaming label/bar formation clock mismatch")
            tolerance = max(1e-12, abs(label_bar.bar.close) * 1e-12)
            if abs(label_bar.bar.close - label.source_price) > tolerance:
                raise ValueError("streaming label source price differs from persisted bar close")

    @property
    def bundle_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="streaming-research-evidence")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "source_run_report_id": self.source_run_report_id,
            "source_profile_id": self.source_profile_id,
            "subscription_id": self.subscription_id,
            "update_ids": list(self.update_ids),
            "denominator_id": self.denominator_id,
            "required_symbols": list(self.required_symbols),
            "resampled_bars": [resampled.to_dict() for resampled in self.resampled_bars],
            "feature_snapshots": [feature.to_dict() for feature in self.feature_snapshots],
            "cross_section_snapshots": [
                cross_section.to_dict() for cross_section in self.cross_section_snapshots
            ],
            "labels": [label.to_dict() for label in self.labels],
            "resampled_bar_count": len(self.resampled_bars),
            "feature_snapshot_count": len(self.feature_snapshots),
            "cross_section_snapshot_count": len(self.cross_section_snapshots),
            "label_count": len(self.labels),
            "feature_authority_recomputed": False,
            "statistical_authority_recomputed": False,
            "engineering_only": True,
            "research_authority": False,
            "agent_value_gate_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["bundle_id"] = self.bundle_id
        return payload


@dataclass(frozen=True, slots=True)
class StreamingResearchEvidenceArtifact:
    bundle_id: str
    row_count: int
    byte_count: int
    content_sha256: str
    output_filename: str
    schema_version: str = "finagent.streaming-research-evidence-artifact.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_id", _text(self.bundle_id, "bundle_id"))
        if self.row_count != 1:
            raise ValueError("streaming evidence v1 artifact stores exactly one canonical bundle record")
        if self.byte_count <= 0:
            raise ValueError("streaming evidence artifact byte_count must be positive")
        digest = self.content_sha256.strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("content_sha256 must be a SHA-256 hex digest")
        object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(
            self,
            "output_filename",
            _text(self.output_filename, "output_filename"),
        )

    @property
    def artifact_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="streaming-research-artifact")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "bundle_id": self.bundle_id,
            "row_count": self.row_count,
            "byte_count": self.byte_count,
            "content_sha256": self.content_sha256,
            "output_filename": self.output_filename,
            "engineering_only": True,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["artifact_id"] = self.artifact_id
        return payload


def _dedupe_resampled(
    items: Sequence[StreamingResampledBar],
) -> tuple[StreamingResampledBar, ...]:
    by_key: dict[tuple[str, int, datetime], StreamingResampledBar] = {}
    for item in items:
        key = (item.bar.symbol, item.bar.interval_seconds, item.bar.event_time)
        existing = by_key.get(key)
        if existing is not None:
            if existing.resampled_bar_id == item.resampled_bar_id:
                continue
            raise ValueError("conflicting streaming resampled bars share semantic key")
        by_key[key] = item
    return tuple(
        sorted(
            by_key.values(),
            key=lambda item: (
                item.bar.event_time,
                item.bar.symbol,
                item.bar.interval_seconds,
            ),
        )
    )


def _dedupe_features(
    items: Sequence[StreamingFeatureSnapshot],
) -> tuple[StreamingFeatureSnapshot, ...]:
    by_key: dict[tuple[str, datetime, str], StreamingFeatureSnapshot] = {}
    for item in items:
        key = (item.symbol, item.event_time, item.denominator_id)
        existing = by_key.get(key)
        if existing is not None:
            if existing.snapshot_id == item.snapshot_id:
                continue
            raise ValueError("conflicting streaming feature snapshots share semantic key")
        by_key[key] = item
    return tuple(sorted(by_key.values(), key=lambda item: (item.event_time, item.symbol)))


def _dedupe_cross_sections(
    items: Sequence[StreamingCrossSectionSnapshot],
) -> tuple[StreamingCrossSectionSnapshot, ...]:
    by_key: dict[tuple[datetime, str], StreamingCrossSectionSnapshot] = {}
    for item in items:
        key = (item.event_time, item.denominator_id)
        existing = by_key.get(key)
        if existing is not None:
            if existing.snapshot_id == item.snapshot_id:
                continue
            raise ValueError("conflicting streaming cross-sections share semantic key")
        by_key[key] = item
    return tuple(sorted(by_key.values(), key=lambda item: item.event_time))


def _dedupe_labels(
    items: Sequence[StreamingExperimentLabel],
) -> tuple[StreamingExperimentLabel, ...]:
    by_key: dict[
        tuple[str, BarInterval, int, datetime],
        StreamingExperimentLabel,
    ] = {}
    for item in items:
        existing = by_key.get(item.semantic_key)
        if existing is not None:
            if existing.label_id == item.label_id:
                continue
            raise ValueError("conflicting streaming labels share semantic key")
        by_key[item.semantic_key] = item
    return tuple(
        sorted(
            by_key.values(),
            key=lambda item: (
                item.source_available_at,
                item.asset,
                item.signal_interval.value,
                item.label_horizon_trading_minutes,
            ),
        )
    )


def build_streaming_research_evidence_bundle(
    report: AlgorithmRunReport,
    *,
    required_symbols: Sequence[str],
    labels: Sequence[StreamingExperimentLabel],
) -> StreamingResearchEvidenceBundle:
    updates = tuple(
        item for item in report.outputs if isinstance(item, StreamingResearchUpdate)
    )
    if not updates:
        raise ValueError("algorithm run contains no streaming research outputs to freeze")
    update_ids = tuple(dict.fromkeys(item.update_id for item in updates))
    resampled = _dedupe_resampled(
        tuple(item for update in updates for item in update.resampled_bars)
    )
    features = _dedupe_features(
        tuple(item for update in updates for item in update.feature_snapshots)
    )
    cross_sections = _dedupe_cross_sections(
        tuple(item for update in updates for item in update.cross_section_snapshots)
    )
    if not features:
        raise ValueError("streaming run produced no B0-compatible feature snapshots")
    denominators = {item.denominator_id for item in features}
    if len(denominators) != 1:
        raise ValueError("streaming feature output contains multiple denominator identities")
    denominator_id = next(iter(denominators))
    return StreamingResearchEvidenceBundle(
        source_run_report_id=report.report_id,
        source_profile_id=report.source_profile_id,
        subscription_id=report.subscription_id,
        update_ids=update_ids,
        denominator_id=denominator_id,
        required_symbols=tuple(required_symbols),
        resampled_bars=resampled,
        feature_snapshots=features,
        cross_section_snapshots=cross_sections,
        labels=_dedupe_labels(labels),
    )


def write_streaming_research_evidence_artifact(
    bundle: StreamingResearchEvidenceBundle,
    output: str | Path,
) -> StreamingResearchEvidenceArtifact:
    target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        bundle.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    target.write_bytes(payload)
    return StreamingResearchEvidenceArtifact(
        bundle_id=bundle.bundle_id,
        row_count=1,
        byte_count=len(payload),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        output_filename=target.name,
    )


def _parse_resampled_bar(document: Mapping[str, object]) -> StreamingResampledBar:
    event = realtime_event_from_dict(_mapping(document.get("bar"), "resampled.bar"))
    if not isinstance(event, BarEvent):
        raise TypeError("persisted streaming resample does not contain a BarEvent")
    item = StreamingResampledBar(
        bar=event,
        available_at=_aware(document.get("available_at"), "resampled.available_at"),
        session_id=_text(document.get("session_id"), "resampled.session_id"),
        session_open=_aware(document.get("session_open"), "resampled.session_open"),
        session_close=_aware(document.get("session_close"), "resampled.session_close"),
        bar_index=_integer(document.get("bar_index"), "resampled.bar_index"),
        observed_minute_count=_integer(
            document.get("observed_minute_count"),
            "resampled.observed_minute_count",
        ),
        expected_minute_count=_integer(
            document.get("expected_minute_count"),
            "resampled.expected_minute_count",
        ),
        coverage_ratio=_number(document.get("coverage_ratio"), "resampled.coverage_ratio"),
        is_half_day=_boolean(document.get("is_half_day"), "resampled.is_half_day"),
        resampling_spec_id=_text(
            document.get("resampling_spec_id"),
            "resampled.resampling_spec_id",
        ),
        source_event_ids=tuple(
            _text(value, "resampled.source_event_ids[]")
            for value in _sequence(
                document.get("source_event_ids"),
                "resampled.source_event_ids",
            )
        ),
    )
    if dict(document) != item.to_dict():
        raise ValueError("persisted streaming resampled bar content mismatch")
    return item


def _parse_feature_evaluation(document: Mapping[str, object]) -> USBaselineFeatureEvaluation:
    unavailable_raw = document.get("unavailable_reason")
    unavailable = (
        None
        if unavailable_raw is None
        else USBaselineUnavailableReason(
            _text(unavailable_raw, "evaluation.unavailable_reason")
        )
    )
    value = _optional_number(document.get("value"), "evaluation.value")
    item = USBaselineFeatureEvaluation(
        feature_id=_text(document.get("feature_id"), "evaluation.feature_id"),
        spec_id=_text(document.get("spec_id"), "evaluation.spec_id"),
        event_time=_aware(document.get("event_time"), "evaluation.event_time"),
        available_at=_aware(document.get("available_at"), "evaluation.available_at"),
        session_id=_text(document.get("session_id"), "evaluation.session_id"),
        used_bar_count=_integer(
            document.get("used_bar_count"),
            "evaluation.used_bar_count",
        ),
        value=value,
        unavailable_reason=unavailable,
    )
    if dict(document) != item.to_dict():
        raise ValueError("persisted streaming feature evaluation content mismatch")
    return item


def _parse_feature_snapshot(document: Mapping[str, object]) -> StreamingFeatureSnapshot:
    evaluations = tuple(
        _parse_feature_evaluation(_mapping(value, "feature.evaluations[]"))
        for value in _sequence(document.get("evaluations"), "feature.evaluations")
    )
    item = StreamingFeatureSnapshot(
        symbol=_text(document.get("symbol"), "feature.symbol"),
        event_time=_aware(document.get("event_time"), "feature.event_time"),
        available_at=_aware(document.get("available_at"), "feature.available_at"),
        session_id=_text(document.get("session_id"), "feature.session_id"),
        resampled_bar_id=_text(
            document.get("resampled_bar_id"),
            "feature.resampled_bar_id",
        ),
        denominator_id=_text(document.get("denominator_id"), "feature.denominator_id"),
        evaluations=evaluations,
    )
    if dict(document) != item.to_dict():
        raise ValueError("persisted streaming feature snapshot content mismatch")
    return item


def _parse_cross_section(
    document: Mapping[str, object],
    features_by_id: Mapping[str, StreamingFeatureSnapshot],
) -> StreamingCrossSectionSnapshot:
    snapshot_ids = tuple(
        _text(value, "cross_section.feature_snapshot_ids[]")
        for value in _sequence(
            document.get("feature_snapshot_ids"),
            "cross_section.feature_snapshot_ids",
        )
    )
    snapshots: list[StreamingFeatureSnapshot] = []
    for snapshot_id in snapshot_ids:
        snapshot = features_by_id.get(snapshot_id)
        if snapshot is None:
            raise ValueError("cross-section references missing persisted feature snapshot")
        snapshots.append(snapshot)
    item = StreamingCrossSectionSnapshot(
        event_time=_aware(document.get("event_time"), "cross_section.event_time"),
        available_at=_aware(document.get("available_at"), "cross_section.available_at"),
        session_id=_text(document.get("session_id"), "cross_section.session_id"),
        required_symbols=tuple(
            _text(value, "cross_section.required_symbols[]")
            for value in _sequence(
                document.get("required_symbols"),
                "cross_section.required_symbols",
            )
        ),
        feature_snapshots=tuple(snapshots),
        denominator_id=_text(
            document.get("denominator_id"),
            "cross_section.denominator_id",
        ),
    )
    if dict(document) != item.to_dict():
        raise ValueError("persisted streaming cross-section content mismatch")
    return item


def _parse_label(document: Mapping[str, object]) -> StreamingExperimentLabel:
    item = StreamingExperimentLabel(
        asset=_text(document.get("asset"), "label.asset"),
        session_id=_text(document.get("session_id"), "label.session_id"),
        signal_interval=BarInterval(
            _text(document.get("signal_interval"), "label.signal_interval")
        ),
        label_horizon_trading_minutes=_integer(
            document.get("label_horizon_trading_minutes"),
            "label.label_horizon_trading_minutes",
        ),
        source_event_time=_aware(
            document.get("source_event_time"),
            "label.source_event_time",
        ),
        source_available_at=_aware(
            document.get("source_available_at"),
            "label.source_available_at",
        ),
        source_price=_number(document.get("source_price"), "label.source_price"),
        target_event_time=_optional_aware(
            document.get("target_event_time"),
            "label.target_event_time",
        ),
        target_available_at=_optional_aware(
            document.get("target_available_at"),
            "label.target_available_at",
        ),
        label_value=_optional_number(document.get("label_value"), "label.label_value"),
        label_available=_boolean(document.get("label_available"), "label.label_available"),
        unavailable_reason=(
            None
            if document.get("unavailable_reason") is None
            else _text(document.get("unavailable_reason"), "label.unavailable_reason")
        ),
    )
    if dict(document) != item.to_dict():
        raise ValueError("persisted streaming label content mismatch")
    return item


def _parse_bundle(document: Mapping[str, object]) -> StreamingResearchEvidenceBundle:
    bars = tuple(
        _parse_resampled_bar(_mapping(value, "bundle.resampled_bars[]"))
        for value in _sequence(document.get("resampled_bars"), "bundle.resampled_bars")
    )
    features = tuple(
        _parse_feature_snapshot(_mapping(value, "bundle.feature_snapshots[]"))
        for value in _sequence(
            document.get("feature_snapshots"),
            "bundle.feature_snapshots",
        )
    )
    features_by_id = {item.snapshot_id: item for item in features}
    cross_sections = tuple(
        _parse_cross_section(
            _mapping(value, "bundle.cross_section_snapshots[]"),
            features_by_id,
        )
        for value in _sequence(
            document.get("cross_section_snapshots"),
            "bundle.cross_section_snapshots",
        )
    )
    labels = tuple(
        _parse_label(_mapping(value, "bundle.labels[]"))
        for value in _sequence(document.get("labels"), "bundle.labels")
    )
    bundle = StreamingResearchEvidenceBundle(
        source_run_report_id=_text(
            document.get("source_run_report_id"),
            "bundle.source_run_report_id",
        ),
        source_profile_id=_text(
            document.get("source_profile_id"),
            "bundle.source_profile_id",
        ),
        subscription_id=_text(document.get("subscription_id"), "bundle.subscription_id"),
        update_ids=tuple(
            _text(value, "bundle.update_ids[]")
            for value in _sequence(document.get("update_ids"), "bundle.update_ids")
        ),
        denominator_id=_text(document.get("denominator_id"), "bundle.denominator_id"),
        required_symbols=tuple(
            _text(value, "bundle.required_symbols[]")
            for value in _sequence(
                document.get("required_symbols"),
                "bundle.required_symbols",
            )
        ),
        resampled_bars=bars,
        feature_snapshots=features,
        cross_section_snapshots=cross_sections,
        labels=labels,
    )
    if dict(document) != bundle.to_dict():
        raise ValueError("persisted streaming research bundle content mismatch")
    return bundle


def read_streaming_research_evidence_artifact(
    path: str | Path,
    artifact: StreamingResearchEvidenceArtifact,
) -> StreamingResearchEvidenceBundle:
    target = Path(path).expanduser().resolve()
    payload = target.read_bytes()
    if len(payload) != artifact.byte_count:
        raise ValueError("streaming evidence artifact byte count mismatch")
    if hashlib.sha256(payload).hexdigest() != artifact.content_sha256:
        raise ValueError("streaming evidence artifact SHA-256 mismatch")
    lines = payload.splitlines()
    if len(lines) != artifact.row_count:
        raise ValueError("streaming evidence artifact row count mismatch")
    loaded = json.loads(lines[0])
    bundle = _parse_bundle(_mapping(loaded, "bundle"))
    if bundle.bundle_id != artifact.bundle_id:
        raise ValueError("streaming evidence artifact/bundle identity mismatch")
    return bundle


def streaming_experiment_rows(
    bundle: StreamingResearchEvidenceBundle,
    *,
    signal_interval: BarInterval,
    label_horizon_trading_minutes: int,
) -> tuple[dict[str, object], ...]:
    interval_seconds = _interval_seconds(signal_interval)
    if label_horizon_trading_minutes not in _ALLOWED_LABEL_HORIZONS:
        raise ValueError("experiment row label horizon must be 30m/60m/120m")
    labels = {
        label.semantic_key: label
        for label in bundle.labels
        if label.signal_interval is signal_interval
        and label.label_horizon_trading_minutes == label_horizon_trading_minutes
    }
    rows: list[dict[str, object]] = []
    for item in bundle.resampled_bars:
        if item.bar.interval_seconds != interval_seconds:
            continue
        if item.bar.symbol not in bundle.required_symbols:
            continue
        label_key = (
            item.bar.symbol,
            signal_interval,
            label_horizon_trading_minutes,
            item.available_at,
        )
        label = labels.get(label_key)
        row: dict[str, object] = {
            "research_asset_id": item.bar.symbol,
            "session_id": item.session_id,
            "event_time": item.bar.event_time,
            "available_at": item.available_at,
            "open": item.bar.open,
            "high": item.bar.high,
            "low": item.bar.low,
            "close": item.bar.close,
            "volume": item.bar.volume,
            "bar_index": item.bar_index,
            "observed_minute_count": item.observed_minute_count,
            "expected_minute_count": item.expected_minute_count,
            "coverage_ratio": item.coverage_ratio,
            "is_complete": item.bar.complete,
            "label_row_present": label is not None,
            "source_event_time": label.source_event_time if label is not None else None,
            "source_available_at": label.source_available_at if label is not None else None,
            "source_price": label.source_price if label is not None else None,
            "target_event_time": label.target_event_time if label is not None else None,
            "target_available_at": label.target_available_at if label is not None else None,
            "label_value": label.label_value if label is not None else None,
            "label_available": label.label_available if label is not None else False,
            "unavailable_reason": label.unavailable_reason if label is not None else None,
            "close_anchor_difference": (
                abs(item.bar.close - label.source_price) if label is not None else None
            ),
        }
        rows.append(row)
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                _aware(row["available_at"], "row.available_at"),
                str(row["research_asset_id"]),
            ),
        )
    )


def _labels_by_b0_formation(
    bundle: StreamingResearchEvidenceBundle,
) -> dict[tuple[str, datetime], StreamingExperimentLabel]:
    return {
        (label.asset, label.source_available_at): label
        for label in bundle.labels
        if label.signal_interval is BarInterval.MINUTE_15
        and label.label_horizon_trading_minutes == 60
    }


def materialize_streaming_b0_observations(
    bundle: StreamingResearchEvidenceBundle,
    run_spec: USBaselineRunSpec,
) -> tuple[
    dict[str, tuple[USBaselineObservation, ...]],
    USBaselineMaterializationDiagnostics,
]:
    if run_spec.denominator_id != bundle.denominator_id:
        raise ValueError("B0 run-spec denominator differs from streaming evidence denominator")
    denominator = canonical_us_baseline_denominator()
    if run_spec.denominator_id != denominator.denominator_id:
        raise ValueError("streaming B0 bridge requires canonical B0 denominator")

    bars_by_id = {item.resampled_bar_id: item for item in bundle.resampled_bars}
    labels = _labels_by_b0_formation(bundle)
    expected_set = set(bundle.required_symbols)
    observed_assets = {
        item.bar.symbol
        for item in bundle.resampled_bars
        if item.bar.interval_seconds == 15 * 60
    }
    complete_assets: set[str] = set()
    observations: dict[str, list[USBaselineObservation]] = {
        spec.feature_id: [] for spec in denominator.candidates
    }
    unavailable: dict[str, dict[str, int]] = {
        spec.feature_id: defaultdict(int) for spec in denominator.candidates
    }
    available_counts = {spec.feature_id: 0 for spec in denominator.candidates}
    complete_count = 0
    incomplete_count = 0
    anchor_missing = 0
    label_available_count = 0
    crosses_count = 0
    target_missing_count = 0
    blockers: list[str] = []

    ordered_features = sorted(
        bundle.feature_snapshots,
        key=lambda item: (item.available_at, item.symbol),
    )
    for snapshot in ordered_features:
        bar = bars_by_id[snapshot.resampled_bar_id]
        if not bar.bar.complete:
            incomplete_count += 1
            continue
        complete_count += 1
        complete_assets.add(snapshot.symbol)
        label = labels.get((snapshot.symbol, snapshot.available_at))
        if label is None:
            anchor_missing += 1
            blockers.append(
                f"label_anchor_missing:{snapshot.symbol}:{snapshot.available_at.isoformat()}"
            )
            continue
        if label.label_available:
            label_available_count += 1
        elif label.unavailable_reason == "target_crosses_session":
            crosses_count += 1
        elif label.unavailable_reason == "target_minute_missing":
            target_missing_count += 1

        evaluations = {item.feature_id: item for item in snapshot.evaluations}
        for spec in denominator.candidates:
            evaluation = evaluations.get(spec.feature_id)
            if evaluation is None or evaluation.spec_id != spec.spec_id:
                raise ValueError("streaming B0 feature snapshot is missing canonical evaluation")
            if evaluation.value is None:
                reason = evaluation.unavailable_reason
                if reason is None:
                    raise RuntimeError("unavailable streaming feature has no reason")
                unavailable[spec.feature_id][reason.value] += 1
            else:
                available_counts[spec.feature_id] += 1
            observations[spec.feature_id].append(
                USBaselineObservation(
                    feature_id=spec.feature_id,
                    feature_spec_id=spec.spec_id,
                    asset=snapshot.symbol,
                    event_time=snapshot.event_time,
                    feature_available_at=snapshot.available_at,
                    eligible_at_formation=True,
                    feature_value=evaluation.value,
                    realized_label=label.label_value,
                    label_available_at=label.target_available_at,
                    label_unavailable_reason=label.unavailable_reason,
                )
            )

    missing_assets = tuple(sorted(expected_set.difference(observed_assets)))
    assets_without_complete = tuple(sorted(expected_set.difference(complete_assets)))
    if missing_assets:
        blockers.append("input:engineering_assets_missing:" + ",".join(missing_assets))
    if assets_without_complete:
        blockers.append(
            "input:engineering_assets_without_complete_bar:" + ",".join(assets_without_complete)
        )
    if complete_count == 0:
        blockers.append("input:no_complete_15m_bars")
    if anchor_missing:
        blockers.append(f"input:label_anchor_missing_count:{anchor_missing}")

    checks = tuple(
        USBaselineCandidateMaterializationCheck(
            feature_id=spec.feature_id,
            feature_spec_id=spec.spec_id,
            observation_count=len(observations[spec.feature_id]),
            available_feature_count=available_counts[spec.feature_id],
            unavailable_reason_counts=tuple(sorted(unavailable[spec.feature_id].items())),
        )
        for spec in denominator.candidates
    )
    diagnostics = USBaselineMaterializationDiagnostics(
        input_row_count=sum(
            item.bar.interval_seconds == 15 * 60 for item in bundle.resampled_bars
        ),
        expected_asset_count=len(bundle.required_symbols),
        observed_asset_count=len(observed_assets),
        missing_assets=missing_assets,
        assets_without_complete_bar=assets_without_complete,
        complete_bar_count=complete_count,
        incomplete_bar_count=incomplete_count,
        label_anchor_missing_count=anchor_missing,
        close_anchor_mismatch_count=0,
        label_available_count=label_available_count,
        target_crosses_session_count=crosses_count,
        target_minute_missing_count=target_missing_count,
        candidate_checks=checks,
        blockers=tuple(dict.fromkeys(blockers)),
    )
    frozen = {
        feature_id: tuple(rows) for feature_id, rows in observations.items()
    }
    return frozen, diagnostics


def evaluate_streaming_b0_with_existing_runner(
    bundle: StreamingResearchEvidenceBundle,
    run_spec: USBaselineRunSpec,
) -> tuple[USBaselineEvaluationReport, USBaselineMaterializationDiagnostics]:
    observations, diagnostics = materialize_streaming_b0_observations(bundle, run_spec)
    report = evaluate_materialized_us_baselines(
        canonical_us_baseline_denominator(),
        observations,
        run_spec=run_spec,
    )
    return report, diagnostics


def materialize_streaming_a0_observations(
    bundle: StreamingResearchEvidenceBundle,
    denominator: USAgentValueEvaluationDenominator,
    *,
    expected_assets: Sequence[str] | None = None,
) -> tuple[
    dict[str, tuple[USBaselineObservation, ...]],
    USBaselineMaterializationDiagnostics,
]:
    rows = streaming_experiment_rows(
        bundle,
        signal_interval=BarInterval.MINUTE_15,
        label_horizon_trading_minutes=60,
    )
    assets = tuple(expected_assets) if expected_assets is not None else bundle.required_symbols
    return materialize_us_a0_observations(
        rows,
        denominator,
        expected_assets=assets,
    )


def materialize_streaming_r1_candidate_observations(
    bundle: StreamingResearchEvidenceBundle,
    denominator: USR1CandidateDenominator,
    *,
    role: USR1ObservationRole,
    signal_interval: BarInterval,
    label_horizon_trading_minutes: int,
    expected_assets: Sequence[str] | None = None,
) -> tuple[tuple[USR1CandidateObservation, ...], USR1ObservationDiagnostics]:
    if role is USR1ObservationRole.TRAIN:
        if (
            signal_interval is not BarInterval.MINUTE_15
            or label_horizon_trading_minutes != 60
        ):
            raise ValueError("R1 TRAIN streaming bridge is exactly 15m/60m")
    elif (signal_interval, label_horizon_trading_minutes) not in _R1_EVALUATION_SLICES:
        raise ValueError("unsupported R1 streaming evaluation slice")
    rows = streaming_experiment_rows(
        bundle,
        signal_interval=signal_interval,
        label_horizon_trading_minutes=label_horizon_trading_minutes,
    )
    assets = tuple(expected_assets) if expected_assets is not None else bundle.required_symbols
    return materialize_us_r1_candidate_observations(
        rows,
        denominator,
        role=role,
        signal_interval=signal_interval,
        label_horizon_trading_minutes=label_horizon_trading_minutes,
        expected_assets=assets,
    )
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from finagent.domain.trading_calendar import TradingCalendarEvidence
from finagent.realtime.events import CanonicalRealtimeEvent
from finagent.realtime.projections import RealtimeProjectionSnapshot
from finagent.realtime.streaming_features import (
    StreamingCrossSectionCoordinator,
    StreamingCrossSectionSnapshot,
    StreamingFeatureSnapshot,
    StreamingUSBaselineFeatureEngine,
)
from finagent.realtime.streaming_resample import StreamingBarAggregator, StreamingResampledBar


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class StreamingResearchUpdate:
    input_event_id: str
    resampled_bars: tuple[StreamingResampledBar, ...]
    feature_snapshots: tuple[StreamingFeatureSnapshot, ...]
    cross_section_snapshots: tuple[StreamingCrossSectionSnapshot, ...]
    schema_version: str = "finagent.streaming-us-research-update.v1"

    def __post_init__(self) -> None:
        if not self.input_event_id.strip():
            raise ValueError("input_event_id must be non-empty")
        if not (self.resampled_bars or self.feature_snapshots or self.cross_section_snapshots):
            raise ValueError("streaming research update cannot be empty")

    @property
    def update_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="streaming-research-update")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "input_event_id": self.input_event_id,
            "resampled_bar_ids": [item.resampled_bar_id for item in self.resampled_bars],
            "feature_snapshot_ids": [item.snapshot_id for item in self.feature_snapshots],
            "cross_section_snapshot_ids": [
                item.snapshot_id for item in self.cross_section_snapshots
            ],
            "uses_existing_us_b0_feature_authority": True,
            "a0_r1_downstream_compatible": True,
            "engineering_only": True,
            "research_authority": False,
            "factor_selection_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["update_id"] = self.update_id
        return payload


class USBaselineStreamingAlgorithm:
    """Provider-neutral streaming bridge into the existing US-B0 feature contracts.

    The source-specific runtime remains outside this class. It receives only canonical events,
    reproduces accepted US-D2 5m/15m/30m resampling semantics, reuses US-B0 feature formulas,
    and waits for the full required symbol denominator before emitting cross-sectional state.
    A0/R1 may consume the resulting B0-compatible feature identities downstream; this class
    deliberately does not recompute their statistical authority inside the realtime loop.
    """

    def __init__(
        self,
        calendar: TradingCalendarEvidence,
        *,
        required_symbols: tuple[str, ...],
    ) -> None:
        self._resampler = StreamingBarAggregator(calendar)
        self._features = StreamingUSBaselineFeatureEngine()
        self._cross_section = StreamingCrossSectionCoordinator(required_symbols)

    @property
    def resampler(self) -> StreamingBarAggregator:
        return self._resampler

    @property
    def feature_engine(self) -> StreamingUSBaselineFeatureEngine:
        return self._features

    @property
    def required_symbols(self) -> tuple[str, ...]:
        return self._cross_section.required_symbols

    def on_event(
        self,
        event: CanonicalRealtimeEvent,
        state: RealtimeProjectionSnapshot,
    ) -> StreamingResearchUpdate | None:
        del state
        resampled = self._resampler.on_event(event)
        if not resampled:
            return None
        feature_snapshots: list[StreamingFeatureSnapshot] = []
        cross_sections: list[StreamingCrossSectionSnapshot] = []
        for item in resampled:
            feature = self._features.on_bar(item)
            if feature is None:
                continue
            feature_snapshots.append(feature)
            cross_section = self._cross_section.on_snapshot(feature)
            if cross_section is not None:
                cross_sections.append(cross_section)
        return StreamingResearchUpdate(
            input_event_id=event.event_id,
            resampled_bars=resampled,
            feature_snapshots=tuple(feature_snapshots),
            cross_section_snapshots=tuple(cross_sections),
        )

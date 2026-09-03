from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from finagent.research.us_baselines import (
    USBaselineCandidateDenominator,
    USBaselineFeatureEvaluation,
    USBaselineBar,
    canonical_us_baseline_denominator,
    evaluate_us_baseline_feature,
)
from finagent.realtime.streaming_resample import StreamingResampledBar


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class StreamingFeatureSnapshot:
    symbol: str
    event_time: datetime
    available_at: datetime
    session_id: str
    resampled_bar_id: str
    denominator_id: str
    evaluations: tuple[USBaselineFeatureEvaluation, ...]
    schema_version: str = "finagent.streaming-us-baseline-feature-snapshot.v1"

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.session_id.strip():
            raise ValueError("feature snapshot symbol/session_id must be non-empty")
        object.__setattr__(self, "event_time", _aware(self.event_time, "event_time"))
        object.__setattr__(self, "available_at", _aware(self.available_at, "available_at"))
        if self.available_at <= self.event_time:
            raise ValueError("feature snapshot available_at must be later than event_time")
        if not self.resampled_bar_id.strip() or not self.denominator_id.strip():
            raise ValueError("feature snapshot identities must be non-empty")
        if not self.evaluations:
            raise ValueError("feature snapshot requires baseline evaluations")
        feature_ids = tuple(item.feature_id for item in self.evaluations)
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("feature snapshot cannot repeat feature_id values")
        if any(item.event_time != self.event_time for item in self.evaluations):
            raise ValueError("feature evaluation event_time mismatch")
        if any(item.available_at != self.available_at for item in self.evaluations):
            raise ValueError("feature evaluation available_at mismatch")
        if any(item.session_id != self.session_id for item in self.evaluations):
            raise ValueError("feature evaluation session_id mismatch")

    @property
    def snapshot_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="streaming-feature-snapshot")

    @property
    def available_feature_count(self) -> int:
        return sum(item.available for item in self.evaluations)

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "event_time": self.event_time.isoformat(),
            "available_at": self.available_at.isoformat(),
            "session_id": self.session_id,
            "resampled_bar_id": self.resampled_bar_id,
            "denominator_id": self.denominator_id,
            "evaluation_count": len(self.evaluations),
            "available_feature_count": self.available_feature_count,
            "evaluations": [item.to_dict() for item in self.evaluations],
            "uses_existing_us_b0_feature_authority": True,
            "engineering_only": True,
            "research_authority": False,
            "factor_selection_authority": False,
            "alpha_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["snapshot_id"] = self.snapshot_id
        return payload


@dataclass(frozen=True, slots=True)
class StreamingCrossSectionSnapshot:
    event_time: datetime
    available_at: datetime
    session_id: str
    required_symbols: tuple[str, ...]
    feature_snapshots: tuple[StreamingFeatureSnapshot, ...]
    denominator_id: str
    schema_version: str = "finagent.streaming-us-baseline-cross-section.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_time", _aware(self.event_time, "event_time"))
        object.__setattr__(self, "available_at", _aware(self.available_at, "available_at"))
        required = tuple(item.strip() for item in self.required_symbols if item.strip())
        if not required or len(required) != len(set(required)):
            raise ValueError("cross-section required_symbols must be non-empty and unique")
        if len(required) != len(self.feature_snapshots):
            raise ValueError("cross-section requires one feature snapshot per required symbol")
        snapshots_by_symbol = {item.symbol: item for item in self.feature_snapshots}
        if set(snapshots_by_symbol) != set(required):
            raise ValueError("cross-section feature snapshots do not match required denominator")
        ordered = tuple(snapshots_by_symbol[symbol] for symbol in required)
        if any(item.event_time != self.event_time for item in ordered):
            raise ValueError("cross-section event_time mismatch")
        if any(item.available_at != self.available_at for item in ordered):
            raise ValueError("cross-section available_at mismatch")
        if any(item.session_id != self.session_id for item in ordered):
            raise ValueError("cross-section session_id mismatch")
        if any(item.denominator_id != self.denominator_id for item in ordered):
            raise ValueError("cross-section baseline denominator mismatch")
        object.__setattr__(self, "required_symbols", required)
        object.__setattr__(self, "feature_snapshots", ordered)

    @property
    def snapshot_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="streaming-cross-section")

    @property
    def fully_available_feature_ids(self) -> tuple[str, ...]:
        common: set[str] | None = None
        for snapshot in self.feature_snapshots:
            available = {item.feature_id for item in snapshot.evaluations if item.available}
            common = available if common is None else common & available
        return tuple(sorted(common or set()))

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "event_time": self.event_time.isoformat(),
            "available_at": self.available_at.isoformat(),
            "session_id": self.session_id,
            "required_symbols": list(self.required_symbols),
            "denominator_id": self.denominator_id,
            "feature_snapshot_ids": [item.snapshot_id for item in self.feature_snapshots],
            "fully_available_feature_ids": list(self.fully_available_feature_ids),
            "partial_symbol_denominator_allowed": False,
            "derived_ranks_computed": False,
            "engineering_only": True,
            "research_authority": False,
            "alpha_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["snapshot_id"] = self.snapshot_id
        return payload


class StreamingUSBaselineFeatureEngine:
    """Reuse the accepted deterministic US-B0 feature formulas over completed 15m bars."""

    def __init__(
        self,
        *,
        denominator: USBaselineCandidateDenominator | None = None,
    ) -> None:
        self._denominator = denominator or canonical_us_baseline_denominator()
        self._history: dict[str, list[USBaselineBar]] = {}
        self._maximum_window = max(item.window_bars for item in self._denominator.candidates)

    @property
    def denominator(self) -> USBaselineCandidateDenominator:
        return self._denominator

    def on_bar(self, item: StreamingResampledBar) -> StreamingFeatureSnapshot | None:
        if item.bar.interval_seconds != 15 * 60:
            return None
        baseline_bar = USBaselineBar(
            event_time=item.bar.event_time,
            available_at=item.available_at,
            session_id=item.session_id,
            open=item.bar.open,
            high=item.bar.high,
            low=item.bar.low,
            close=item.bar.close,
            volume=item.bar.volume,
            is_complete=item.bar.complete,
        )
        history = self._history.setdefault(item.bar.symbol, [])
        if history and baseline_bar.event_time <= history[-1].event_time:
            if baseline_bar.event_time == history[-1].event_time:
                raise ValueError("conflicting duplicate 15m bar entered streaming feature history")
            raise ValueError("streaming feature history regressed")
        history.append(baseline_bar)
        if len(history) > self._maximum_window:
            del history[: len(history) - self._maximum_window]
        bars = tuple(history)
        evaluations = tuple(
            evaluate_us_baseline_feature(
                spec,
                bars,
                protocol=self._denominator.protocol,
            )
            for spec in self._denominator.candidates
        )
        return StreamingFeatureSnapshot(
            symbol=item.bar.symbol,
            event_time=baseline_bar.event_time,
            available_at=baseline_bar.available_at,
            session_id=baseline_bar.session_id,
            resampled_bar_id=item.resampled_bar_id,
            denominator_id=self._denominator.denominator_id,
            evaluations=evaluations,
        )


class StreamingCrossSectionCoordinator:
    """Emit a cross-section only after every required symbol has the same 15m snapshot."""

    def __init__(self, required_symbols: tuple[str, ...]) -> None:
        required = tuple(sorted(item.strip() for item in required_symbols if item.strip()))
        if not required or len(required) != len(set(required)):
            raise ValueError("cross-section required_symbols must be non-empty and unique")
        self._required = required
        self._pending: dict[
            tuple[datetime, datetime, str, str],
            dict[str, StreamingFeatureSnapshot],
        ] = {}

    @property
    def required_symbols(self) -> tuple[str, ...]:
        return self._required

    def on_snapshot(
        self,
        snapshot: StreamingFeatureSnapshot,
    ) -> StreamingCrossSectionSnapshot | None:
        if snapshot.symbol not in self._required:
            raise ValueError("feature snapshot symbol is outside the cross-section denominator")
        key = (
            snapshot.event_time,
            snapshot.available_at,
            snapshot.session_id,
            snapshot.denominator_id,
        )
        pending = self._pending.setdefault(key, {})
        existing = pending.get(snapshot.symbol)
        if existing is not None:
            if existing.snapshot_id == snapshot.snapshot_id:
                return None
            raise ValueError("conflicting feature snapshot for one symbol/time denominator")
        pending[snapshot.symbol] = snapshot
        if set(pending) != set(self._required):
            return None
        result = StreamingCrossSectionSnapshot(
            event_time=snapshot.event_time,
            available_at=snapshot.available_at,
            session_id=snapshot.session_id,
            required_symbols=self._required,
            feature_snapshots=tuple(pending[symbol] for symbol in self._required),
            denominator_id=snapshot.denominator_id,
        )
        del self._pending[key]
        return result

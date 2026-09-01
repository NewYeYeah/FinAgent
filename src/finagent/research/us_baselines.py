from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


class USBaselineFeatureKind(StrEnum):
    REVERSAL = "reversal"
    MOMENTUM = "momentum"
    RANGE_MEAN = "range_mean"
    RETURN_VOLATILITY = "return_volatility"
    VOLUME_SURPRISE = "volume_surprise"
    CLOSE_LOCATION = "close_location"


class USBaselineUnavailableReason(StrEnum):
    INSUFFICIENT_HISTORY = "insufficient_history"
    CROSS_SESSION_WINDOW = "cross_session_window"
    INCOMPLETE_BAR = "incomplete_bar"
    ZERO_REFERENCE_VOLUME = "zero_reference_volume"


@dataclass(frozen=True, slots=True)
class USBaselineProtocol:
    signal_interval: BarInterval = BarInterval.MINUTE_15
    robustness_intervals: tuple[BarInterval, ...] = (
        BarInterval.MINUTE_5,
        BarInterval.MINUTE_30,
    )
    label_name: str = "us_same_session_60m_simple_return_raw"
    label_horizon_trading_minutes: int = 60
    same_session_only: bool = True
    price_basis: ResearchPriceBasis = ResearchPriceBasis.RAW
    availability_policy: AvailabilityPolicy = AvailabilityPolicy.AVAILABLE_AT
    require_complete_bars: bool = True
    schema_version: str = "finagent.us-baseline-protocol.v1"

    def __post_init__(self) -> None:
        if self.signal_interval is not BarInterval.MINUTE_15:
            raise ValueError("US-B0 v1 canonical signal interval must be 15m")
        if self.robustness_intervals != (
            BarInterval.MINUTE_5,
            BarInterval.MINUTE_30,
        ):
            raise ValueError("US-B0 v1 robustness intervals must be exactly 5m and 30m")
        if not self.label_name.strip():
            raise ValueError("label_name must be non-empty")
        if self.label_horizon_trading_minutes != 60:
            raise ValueError("US-B0 v1 label horizon must be 60 trading minutes")
        if not self.same_session_only:
            raise ValueError("US-B0 v1 features must be same-session only")
        if self.price_basis is not ResearchPriceBasis.RAW:
            raise ValueError("US-B0 v1 uses the accepted RAW same-session price authority")
        if self.availability_policy is not AvailabilityPolicy.AVAILABLE_AT:
            raise ValueError("US-B0 v1 formation clock must be available_at")
        if not self.require_complete_bars:
            raise ValueError("US-B0 v1 requires complete resampled bars")
        object.__setattr__(self, "label_name", self.label_name.strip())

    @property
    def protocol_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-baseline-protocol")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "signal_interval": self.signal_interval.value,
            "robustness_intervals": [item.value for item in self.robustness_intervals],
            "label_name": self.label_name,
            "label_horizon_trading_minutes": self.label_horizon_trading_minutes,
            "same_session_only": self.same_session_only,
            "price_basis": self.price_basis.value,
            "availability_policy": self.availability_policy.value,
            "require_complete_bars": self.require_complete_bars,
        }
        if include_id:
            payload["protocol_id"] = self.protocol_id
        return payload


@dataclass(frozen=True, slots=True)
class USBaselineFeatureSpec:
    feature_id: str
    kind: USBaselineFeatureKind
    window_bars: int
    input_fields: tuple[str, ...]
    hypothesis: str
    description: str
    protocol_id: str
    schema_version: str = "finagent.us-baseline-feature-spec.v1"

    def __post_init__(self) -> None:
        for field_name in ("feature_id", "hypothesis", "description", "protocol_id"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.window_bars < 1:
            raise ValueError("window_bars must be >= 1")
        fields = tuple(dict.fromkeys(item.strip() for item in self.input_fields if item.strip()))
        if not fields or len(fields) != len(self.input_fields):
            raise ValueError("input_fields must be non-empty and unique")
        object.__setattr__(self, "input_fields", fields)

    @property
    def spec_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-baseline-feature")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "feature_id": self.feature_id,
            "kind": self.kind.value,
            "window_bars": self.window_bars,
            "input_fields": list(self.input_fields),
            "hypothesis": self.hypothesis,
            "description": self.description,
            "protocol_id": self.protocol_id,
        }
        if include_id:
            payload["spec_id"] = self.spec_id
        return payload


@dataclass(frozen=True, slots=True)
class USBaselineCandidateDenominator:
    protocol: USBaselineProtocol
    candidates: tuple[USBaselineFeatureSpec, ...]
    generator_type: str = "MANUAL"
    schema_version: str = "finagent.us-baseline-candidate-denominator.v1"

    def __post_init__(self) -> None:
        if not self.candidates:
            raise ValueError("baseline candidate denominator requires candidates")
        feature_ids = tuple(item.feature_id for item in self.candidates)
        spec_ids = tuple(item.spec_id for item in self.candidates)
        if len(feature_ids) != len(set(feature_ids)):
            raise ValueError("baseline denominator contains duplicate feature_id values")
        if len(spec_ids) != len(set(spec_ids)):
            raise ValueError("baseline denominator contains duplicate feature specifications")
        if any(item.protocol_id != self.protocol.protocol_id for item in self.candidates):
            raise ValueError("baseline candidate protocol identity mismatch")
        generator_type = self.generator_type.strip().upper()
        if generator_type != "MANUAL":
            raise ValueError("US-B0 v1 denominator is the deterministic MANUAL arm")
        object.__setattr__(self, "generator_type", generator_type)

    @property
    def denominator_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-baseline-denominator")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol": self.protocol.to_dict(),
            "generator_type": self.generator_type,
            "candidate_count": len(self.candidates),
            "candidate_spec_ids": [item.spec_id for item in self.candidates],
            "candidates": [item.to_dict() for item in self.candidates],
            "scope": "deterministic_pre_agent_baseline_denominator",
        }
        if include_id:
            payload["denominator_id"] = self.denominator_id
        return payload


@dataclass(frozen=True, slots=True)
class USBaselineBar:
    event_time: datetime
    available_at: datetime
    session_id: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_complete: bool = True

    def __post_init__(self) -> None:
        if self.event_time.tzinfo is None or self.event_time.utcoffset() is None:
            raise ValueError("event_time must be timezone-aware")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("available_at must be timezone-aware")
        if self.available_at <= self.event_time:
            raise ValueError("available_at must be later than event_time")
        session_id = self.session_id.strip()
        if not session_id:
            raise ValueError("session_id must be non-empty")
        object.__setattr__(self, "session_id", session_id)
        values = (self.open, self.high, self.low, self.close, self.volume)
        if any(not math.isfinite(float(value)) for value in values):
            raise ValueError("OHLCV values must be finite")
        if self.low < 0 or self.open < 0 or self.high < 0 or self.close < 0:
            raise ValueError("OHLC values must be non-negative")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be >= open/close/low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be <= open/close/high")
        if self.volume < 0:
            raise ValueError("volume must be non-negative")


@dataclass(frozen=True, slots=True)
class USBaselineFeatureEvaluation:
    feature_id: str
    spec_id: str
    event_time: datetime
    available_at: datetime
    session_id: str
    used_bar_count: int
    value: float | None
    unavailable_reason: USBaselineUnavailableReason | None
    schema_version: str = "finagent.us-baseline-feature-evaluation.v1"

    def __post_init__(self) -> None:
        if bool(self.value is None) == bool(self.unavailable_reason is None):
            raise ValueError("exactly one of value or unavailable_reason must be set")
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError("baseline feature value must be finite")
        if self.used_bar_count < 1:
            raise ValueError("used_bar_count must be >= 1")

    @property
    def available(self) -> bool:
        return self.value is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "feature_id": self.feature_id,
            "spec_id": self.spec_id,
            "event_time": self.event_time.isoformat(),
            "available_at": self.available_at.isoformat(),
            "session_id": self.session_id,
            "used_bar_count": self.used_bar_count,
            "available": self.available,
            "value": self.value,
            "unavailable_reason": (
                self.unavailable_reason.value if self.unavailable_reason is not None else None
            ),
        }


def _unavailable(
    spec: USBaselineFeatureSpec,
    current: USBaselineBar,
    used_bar_count: int,
    reason: USBaselineUnavailableReason,
) -> USBaselineFeatureEvaluation:
    return USBaselineFeatureEvaluation(
        feature_id=spec.feature_id,
        spec_id=spec.spec_id,
        event_time=current.event_time,
        available_at=current.available_at,
        session_id=current.session_id,
        used_bar_count=used_bar_count,
        value=None,
        unavailable_reason=reason,
    )


def _evaluate_value(
    spec: USBaselineFeatureSpec,
    window: tuple[USBaselineBar, ...],
) -> float | USBaselineUnavailableReason:
    first = window[0]
    last = window[-1]
    if spec.kind in {USBaselineFeatureKind.REVERSAL, USBaselineFeatureKind.MOMENTUM}:
        raw_return = last.close / first.close - 1.0
        return -raw_return if spec.kind is USBaselineFeatureKind.REVERSAL else raw_return
    if spec.kind is USBaselineFeatureKind.RANGE_MEAN:
        return sum((bar.high - bar.low) / bar.close for bar in window) / len(window)
    if spec.kind is USBaselineFeatureKind.RETURN_VOLATILITY:
        returns = [
            math.log(window[index].close / window[index - 1].close)
            for index in range(1, len(window))
        ]
        mean_return = sum(returns) / len(returns)
        variance = sum((value - mean_return) ** 2 for value in returns) / len(returns)
        return math.sqrt(variance)
    if spec.kind is USBaselineFeatureKind.VOLUME_SURPRISE:
        reference = tuple(bar.volume for bar in window[:-1])
        reference_mean = sum(reference) / len(reference)
        if reference_mean <= 0:
            return USBaselineUnavailableReason.ZERO_REFERENCE_VOLUME
        return last.volume / reference_mean - 1.0
    if spec.kind is USBaselineFeatureKind.CLOSE_LOCATION:
        spread = last.high - last.low
        if spread <= 1e-15:
            return 0.0
        return (last.close - last.low) / spread - 0.5
    raise ValueError(f"unsupported baseline feature kind: {spec.kind!r}")


def evaluate_us_baseline_feature(
    spec: USBaselineFeatureSpec,
    bars: tuple[USBaselineBar, ...],
    *,
    protocol: USBaselineProtocol,
) -> USBaselineFeatureEvaluation:
    if not bars:
        raise ValueError("baseline evaluation requires at least the current bar")
    if spec.protocol_id != protocol.protocol_id:
        raise ValueError("feature/protocol identity mismatch")
    for left, right in zip(bars, bars[1:]):
        if right.event_time <= left.event_time:
            raise ValueError("baseline input bars must be strictly ordered by event_time")
        if right.available_at <= left.available_at:
            raise ValueError("baseline input bars must be strictly ordered by available_at")

    current = bars[-1]
    if len(bars) < spec.window_bars:
        return _unavailable(
            spec,
            current,
            len(bars),
            USBaselineUnavailableReason.INSUFFICIENT_HISTORY,
        )
    window = bars[-spec.window_bars :]
    if protocol.same_session_only and any(
        item.session_id != current.session_id for item in window
    ):
        return _unavailable(
            spec,
            current,
            len(window),
            USBaselineUnavailableReason.CROSS_SESSION_WINDOW,
        )
    if protocol.require_complete_bars and any(not item.is_complete for item in window):
        return _unavailable(
            spec,
            current,
            len(window),
            USBaselineUnavailableReason.INCOMPLETE_BAR,
        )

    value = _evaluate_value(spec, window)
    if isinstance(value, USBaselineUnavailableReason):
        return _unavailable(spec, current, len(window), value)
    return USBaselineFeatureEvaluation(
        feature_id=spec.feature_id,
        spec_id=spec.spec_id,
        event_time=current.event_time,
        available_at=current.available_at,
        session_id=current.session_id,
        used_bar_count=len(window),
        value=float(value),
        unavailable_reason=None,
    )


def canonical_us_baseline_denominator() -> USBaselineCandidateDenominator:
    protocol = USBaselineProtocol()
    protocol_id = protocol.protocol_id
    candidates = (
        USBaselineFeatureSpec(
            feature_id="manual_reversal_1bar",
            kind=USBaselineFeatureKind.REVERSAL,
            window_bars=2,
            input_fields=("close",),
            hypothesis="Very short-horizon price moves partially reverse within the same session.",
            description="Negative one-bar simple close return on completed 15m bars.",
            protocol_id=protocol_id,
        ),
        USBaselineFeatureSpec(
            feature_id="manual_reversal_2bar",
            kind=USBaselineFeatureKind.REVERSAL,
            window_bars=3,
            input_fields=("close",),
            hypothesis="Short intraday dislocations can mean-revert over roughly 30 minutes.",
            description="Negative two-bar simple close return on completed 15m bars.",
            protocol_id=protocol_id,
        ),
        USBaselineFeatureSpec(
            feature_id="manual_momentum_4bar",
            kind=USBaselineFeatureKind.MOMENTUM,
            window_bars=5,
            input_fields=("close",),
            hypothesis="Persistent intraday order flow can create one-hour price continuation.",
            description="Four-bar simple close return on completed 15m bars.",
            protocol_id=protocol_id,
        ),
        USBaselineFeatureSpec(
            feature_id="manual_momentum_8bar",
            kind=USBaselineFeatureKind.MOMENTUM,
            window_bars=9,
            input_fields=("close",),
            hypothesis="Longer same-session trends can persist over roughly two trading hours.",
            description="Eight-bar simple close return on completed 15m bars.",
            protocol_id=protocol_id,
        ),
        USBaselineFeatureSpec(
            feature_id="manual_range_mean_4bar",
            kind=USBaselineFeatureKind.RANGE_MEAN,
            window_bars=4,
            input_fields=("high", "low", "close"),
            hypothesis="Recent normalized intraday range captures short-horizon volatility state.",
            description="Mean normalized high-low range over four completed 15m bars.",
            protocol_id=protocol_id,
        ),
        USBaselineFeatureSpec(
            feature_id="manual_return_volatility_4bar",
            kind=USBaselineFeatureKind.RETURN_VOLATILITY,
            window_bars=5,
            input_fields=("close",),
            hypothesis="Recent return dispersion captures short-horizon volatility regime.",
            description="Population volatility of four adjacent 15m log returns.",
            protocol_id=protocol_id,
        ),
        USBaselineFeatureSpec(
            feature_id="manual_volume_surprise_8bar",
            kind=USBaselineFeatureKind.VOLUME_SURPRISE,
            window_bars=9,
            input_fields=("volume",),
            hypothesis="Unusually high current volume relative to recent same-session bars is informative.",
            description="Current 15m volume divided by the mean of the prior eight bars minus one.",
            protocol_id=protocol_id,
        ),
        USBaselineFeatureSpec(
            feature_id="manual_close_location_1bar",
            kind=USBaselineFeatureKind.CLOSE_LOCATION,
            window_bars=1,
            input_fields=("high", "low", "close"),
            hypothesis="The close location inside the current bar range captures directional pressure.",
            description="Close location in the current 15m high-low range, centered at zero.",
            protocol_id=protocol_id,
        ),
    )
    return USBaselineCandidateDenominator(protocol=protocol, candidates=candidates)

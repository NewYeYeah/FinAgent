from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _snap_seconds(value: float, quantum: int) -> int:
    scaled = value / quantum
    if scaled >= 0:
        return math.floor(scaled + 0.5) * quantum
    return math.ceil(scaled - 0.5) * quantum


@dataclass(frozen=True, slots=True)
class MT5BrokerClockPolicy:
    minimum_reference_count: int = 3
    offset_snap_seconds: int = 60
    maximum_reference_residual_seconds: float = 15.0
    maximum_abs_offset_seconds: int = 14 * 60 * 60
    schema_version: str = "finagent.mt5-broker-clock-policy.v1"

    def __post_init__(self) -> None:
        if self.minimum_reference_count < 2:
            raise ValueError("minimum_reference_count must be >= 2")
        if self.offset_snap_seconds < 1:
            raise ValueError("offset_snap_seconds must be >= 1")
        if self.maximum_reference_residual_seconds < 0:
            raise ValueError("maximum_reference_residual_seconds must be >= 0")
        if self.maximum_abs_offset_seconds < self.offset_snap_seconds:
            raise ValueError("maximum_abs_offset_seconds must cover at least one snap quantum")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="mt5-broker-clock-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "minimum_reference_count": self.minimum_reference_count,
            "offset_snap_seconds": self.offset_snap_seconds,
            "maximum_reference_residual_seconds": self.maximum_reference_residual_seconds,
            "maximum_abs_offset_seconds": self.maximum_abs_offset_seconds,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


DEFAULT_MT5_BROKER_CLOCK_POLICY = MT5BrokerClockPolicy()


@dataclass(frozen=True, slots=True)
class MT5BrokerClockObservation:
    symbol: str
    raw_broker_time_msc: int
    retrieved_at_utc: datetime
    bid: float
    ask: float
    schema_version: str = "finagent.mt5-broker-clock-observation.v1"

    def __post_init__(self) -> None:
        symbol = self.symbol.strip()
        if not symbol:
            raise ValueError("clock reference symbol must be non-empty")
        if self.raw_broker_time_msc <= 0:
            raise ValueError("raw_broker_time_msc must be positive")
        retrieved = _aware_utc(self.retrieved_at_utc, "retrieved_at_utc")
        if not math.isfinite(self.bid) or not math.isfinite(self.ask):
            raise ValueError("clock reference bid/ask must be finite")
        if self.bid <= 0 or self.ask <= 0 or self.ask < self.bid:
            raise ValueError("clock reference requires positive bid/ask with ask >= bid")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "retrieved_at_utc", retrieved)

    @property
    def raw_broker_wall_time(self) -> datetime:
        """Render the broker epoch as a wall-clock value without claiming UTC authority."""
        return datetime.fromtimestamp(self.raw_broker_time_msc / 1000.0, tz=UTC)

    @property
    def observed_offset_seconds(self) -> float:
        return (self.raw_broker_wall_time - self.retrieved_at_utc).total_seconds()

    @property
    def observation_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="mt5-broker-clock-observation",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "raw_broker_time_msc": self.raw_broker_time_msc,
            "raw_broker_wall_time": self.raw_broker_wall_time.isoformat(),
            "retrieved_at_utc": self.retrieved_at_utc.isoformat(),
            "observed_offset_seconds": self.observed_offset_seconds,
            "bid": self.bid,
            "ask": self.ask,
        }
        if include_id:
            payload["observation_id"] = self.observation_id
        return payload


@dataclass(frozen=True, slots=True)
class MT5BrokerClockEvidence:
    broker_server: str
    policy: MT5BrokerClockPolicy
    observations: tuple[MT5BrokerClockObservation, ...]
    inferred_offset_seconds: int | None
    generated_at: datetime
    schema_version: str = "finagent.mt5-broker-clock-evidence.v1"

    def __post_init__(self) -> None:
        server = self.broker_server.strip()
        if not server:
            raise ValueError("broker_server must be non-empty")
        generated = _aware_utc(self.generated_at, "generated_at")
        symbols = tuple(item.symbol for item in self.observations)
        if len(symbols) != len(set(symbols)):
            raise ValueError("clock evidence cannot repeat reference symbols")
        object.__setattr__(self, "broker_server", server)
        object.__setattr__(self, "generated_at", generated)

    @property
    def reference_symbols(self) -> tuple[str, ...]:
        return tuple(item.symbol for item in self.observations)

    @property
    def residual_seconds(self) -> tuple[float, ...]:
        if self.inferred_offset_seconds is None:
            return ()
        return tuple(
            item.observed_offset_seconds - self.inferred_offset_seconds
            for item in self.observations
        )

    @property
    def maximum_abs_residual_seconds(self) -> float | None:
        values = self.residual_seconds
        return max((abs(item) for item in values), default=None)

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if len(self.observations) < self.policy.minimum_reference_count:
            blockers.append(
                f"broker_clock:insufficient_references:{len(self.observations)}"
                f"<{self.policy.minimum_reference_count}"
            )
        if self.inferred_offset_seconds is None:
            blockers.append("broker_clock:offset_unavailable")
        else:
            if abs(self.inferred_offset_seconds) > self.policy.maximum_abs_offset_seconds:
                blockers.append(
                    "broker_clock:offset_out_of_bounds:"
                    f"{self.inferred_offset_seconds}"
                )
            for observation, residual in zip(
                self.observations,
                self.residual_seconds,
                strict=True,
            ):
                if abs(residual) > self.policy.maximum_reference_residual_seconds:
                    blockers.append(
                        "broker_clock:reference_residual_exceeded:"
                        f"{observation.symbol}:{residual:.3f}"
                    )
        return tuple(dict.fromkeys(blockers))

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "broker_server": self.broker_server,
                "policy_id": self.policy.policy_id,
                "observations": [item.to_dict() for item in self.observations],
                "inferred_offset_seconds": self.inferred_offset_seconds,
            },
            prefix="mt5-broker-clock-evidence",
        )

    def normalize_epoch_msc(self, raw_broker_time_msc: int) -> datetime:
        if not self.passed or self.inferred_offset_seconds is None:
            raise ValueError("broker clock evidence must pass before timestamp normalization")
        if raw_broker_time_msc <= 0:
            raise ValueError("raw broker timestamp must be positive")
        raw_wall = datetime.fromtimestamp(raw_broker_time_msc / 1000.0, tz=UTC)
        return raw_wall - timedelta(seconds=self.inferred_offset_seconds)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "passed": self.passed,
            "blockers": list(self.blockers),
            "broker_server": self.broker_server,
            "policy": self.policy.to_dict(),
            "reference_count": len(self.observations),
            "reference_symbols": list(self.reference_symbols),
            "inferred_offset_seconds": self.inferred_offset_seconds,
            "maximum_abs_residual_seconds": self.maximum_abs_residual_seconds,
            "observations": [item.to_dict() for item in self.observations],
            "generated_at": self.generated_at.isoformat(),
            "authority": "observed_broker_clock_normalization_only",
        }


def build_mt5_broker_clock_evidence(
    broker_server: str,
    observations: tuple[MT5BrokerClockObservation, ...],
    *,
    policy: MT5BrokerClockPolicy = DEFAULT_MT5_BROKER_CLOCK_POLICY,
    generated_at: datetime | None = None,
) -> MT5BrokerClockEvidence:
    ordered = tuple(sorted(observations, key=lambda item: item.symbol))
    inferred: int | None = None
    if ordered:
        inferred = _snap_seconds(
            float(median(item.observed_offset_seconds for item in ordered)),
            policy.offset_snap_seconds,
        )
    timestamp = generated_at or datetime.now(UTC)
    return MT5BrokerClockEvidence(
        broker_server=broker_server,
        policy=policy,
        observations=ordered,
        inferred_offset_seconds=inferred,
        generated_at=timestamp,
    )


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
    return int(value)


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be numeric")
    return float(value)


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _datetime(value: object, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, field_name))
    return _aware_utc(parsed, field_name)


def mt5_broker_clock_evidence_from_document(
    document: Mapping[str, object],
) -> MT5BrokerClockEvidence:
    schema = _text(document.get("schema_version"), "clock.schema_version")
    if schema != "finagent.mt5-broker-clock-evidence.v1":
        raise ValueError(f"unsupported broker clock evidence schema: {schema}")
    policy_raw = _mapping(document.get("policy"), "clock.policy")
    policy = MT5BrokerClockPolicy(
        minimum_reference_count=_integer(
            policy_raw.get("minimum_reference_count"),
            "clock.policy.minimum_reference_count",
        ),
        offset_snap_seconds=_integer(
            policy_raw.get("offset_snap_seconds"),
            "clock.policy.offset_snap_seconds",
        ),
        maximum_reference_residual_seconds=_number(
            policy_raw.get("maximum_reference_residual_seconds"),
            "clock.policy.maximum_reference_residual_seconds",
        ),
        maximum_abs_offset_seconds=_integer(
            policy_raw.get("maximum_abs_offset_seconds"),
            "clock.policy.maximum_abs_offset_seconds",
        ),
    )
    stored_policy_id = policy_raw.get("policy_id")
    if stored_policy_id is not None and str(stored_policy_id) != policy.policy_id:
        raise ValueError("stored broker clock policy_id does not match policy content")

    observations: list[MT5BrokerClockObservation] = []
    for raw in _sequence(document.get("observations", ()), "clock.observations"):
        row = _mapping(raw, "clock.observations[]")
        observation = MT5BrokerClockObservation(
            symbol=_text(row.get("symbol"), "clock.observations[].symbol"),
            raw_broker_time_msc=_integer(
                row.get("raw_broker_time_msc"),
                "clock.observations[].raw_broker_time_msc",
            ),
            retrieved_at_utc=_datetime(
                row.get("retrieved_at_utc"),
                "clock.observations[].retrieved_at_utc",
            ),
            bid=_number(row.get("bid"), "clock.observations[].bid"),
            ask=_number(row.get("ask"), "clock.observations[].ask"),
        )
        stored_observation_id = row.get("observation_id")
        if (
            stored_observation_id is not None
            and str(stored_observation_id) != observation.observation_id
        ):
            raise ValueError("stored broker clock observation_id does not match content")
        observations.append(observation)

    inferred_raw = document.get("inferred_offset_seconds")
    inferred = (
        None
        if inferred_raw is None
        else _integer(inferred_raw, "clock.inferred_offset_seconds")
    )
    evidence = MT5BrokerClockEvidence(
        broker_server=_text(document.get("broker_server"), "clock.broker_server"),
        policy=policy,
        observations=tuple(observations),
        inferred_offset_seconds=inferred,
        generated_at=_datetime(document.get("generated_at"), "clock.generated_at"),
    )
    stored_id = document.get("evidence_id")
    if stored_id is not None and str(stored_id) != evidence.evidence_id:
        raise ValueError("stored broker clock evidence_id does not match evidence content")
    stored_passed = document.get("passed")
    if stored_passed is not None and stored_passed is not evidence.passed:
        raise ValueError("stored broker clock passed flag does not match evidence content")
    return evidence

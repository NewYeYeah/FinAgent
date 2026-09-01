from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from ._validation import require_aware_datetime, require_non_empty, require_non_negative


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _normalized_limitations(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


class InstrumentMappingStatus(StrEnum):
    REVIEW_REQUIRED = "review_required"
    ACCEPTED_FOR_ENGINEERING = "accepted_for_engineering"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ResearchInstrument:
    source_symbol: str
    source_candidate: str
    source_revision: str
    asset_class: str = "equity"
    quote_currency: str = "USD"
    venue_code: str | None = None
    lifecycle_policy: str = "historical_symbol_without_lifecycle"
    limitations: tuple[str, ...] = (
        "identity:no_point_in_time_security_master",
        "identity:listed_venue_not_authoritative_from_ohlcv_source",
    )
    schema_version: str = "finagent.research-instrument.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_symbol", require_non_empty(self.source_symbol, "source_symbol"))
        object.__setattr__(
            self, "source_candidate", require_non_empty(self.source_candidate, "source_candidate")
        )
        object.__setattr__(
            self, "source_revision", require_non_empty(self.source_revision, "source_revision")
        )
        object.__setattr__(self, "asset_class", require_non_empty(self.asset_class, "asset_class"))
        object.__setattr__(
            self, "quote_currency", require_non_empty(self.quote_currency, "quote_currency").upper()
        )
        if self.venue_code is not None:
            venue = self.venue_code.strip().upper()
            object.__setattr__(self, "venue_code", venue or None)
        object.__setattr__(
            self, "lifecycle_policy", require_non_empty(self.lifecycle_policy, "lifecycle_policy")
        )
        object.__setattr__(self, "limitations", _normalized_limitations(self.limitations))

    @property
    def research_instrument_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="research-instrument")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "source_symbol": self.source_symbol,
            "source_candidate": self.source_candidate,
            "source_revision": self.source_revision,
            "asset_class": self.asset_class,
            "quote_currency": self.quote_currency,
            "venue_code": self.venue_code,
            "lifecycle_policy": self.lifecycle_policy,
            "limitations": list(self.limitations),
        }
        if include_id:
            payload["research_instrument_id"] = self.research_instrument_id
        return payload


@dataclass(frozen=True, slots=True)
class BrokerInstrument:
    broker_symbol: str
    broker_server: str
    terminal_capability_id: str
    symbol_spec_id: str
    path: str
    visible: bool
    tradable: bool
    trade_mode: int
    trade_calc_mode: int
    point: float
    tick_size: float
    tick_value: float
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    margin_initial: float
    margin_maintenance: float
    swap_mode: int
    swap_long: float
    swap_short: float
    filling_mode: int
    order_mode: int
    currency_base: str
    currency_profit: str
    currency_margin: str
    limitations: tuple[str, ...] = ("identity:broker_path_not_exchange_authority",)
    schema_version: str = "finagent.broker-instrument.v1"

    def __post_init__(self) -> None:
        for name in ("broker_symbol", "broker_server", "terminal_capability_id", "symbol_spec_id"):
            object.__setattr__(self, name, require_non_empty(str(getattr(self, name)), name))
        object.__setattr__(self, "path", self.path.strip())
        for name in ("trade_mode", "trade_calc_mode", "swap_mode", "filling_mode", "order_mode"):
            if int(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be >= 0")
        for name in (
            "point",
            "tick_size",
            "tick_value",
            "contract_size",
            "volume_min",
            "volume_max",
            "volume_step",
            "margin_initial",
            "margin_maintenance",
        ):
            object.__setattr__(
                self, name, require_non_negative(float(getattr(self, name)), name)
            )
        if self.volume_max and self.volume_min > self.volume_max:
            raise ValueError("volume_min cannot exceed volume_max")
        for name in ("currency_base", "currency_profit", "currency_margin"):
            object.__setattr__(self, name, str(getattr(self, name)).strip().upper())
        object.__setattr__(self, "limitations", _normalized_limitations(self.limitations))

    @property
    def broker_instrument_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="broker-instrument")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "broker_symbol": self.broker_symbol,
            "broker_server": self.broker_server,
            "terminal_capability_id": self.terminal_capability_id,
            "symbol_spec_id": self.symbol_spec_id,
            "path": self.path,
            "visible": self.visible,
            "tradable": self.tradable,
            "trade_mode": self.trade_mode,
            "trade_calc_mode": self.trade_calc_mode,
            "point": self.point,
            "tick_size": self.tick_size,
            "tick_value": self.tick_value,
            "contract_size": self.contract_size,
            "volume_min": self.volume_min,
            "volume_max": self.volume_max,
            "volume_step": self.volume_step,
            "margin_initial": self.margin_initial,
            "margin_maintenance": self.margin_maintenance,
            "swap_mode": self.swap_mode,
            "swap_long": self.swap_long,
            "swap_short": self.swap_short,
            "filling_mode": self.filling_mode,
            "order_mode": self.order_mode,
            "currency_base": self.currency_base,
            "currency_profit": self.currency_profit,
            "currency_margin": self.currency_margin,
            "limitations": list(self.limitations),
        }
        if include_id:
            payload["broker_instrument_id"] = self.broker_instrument_id
        return payload


@dataclass(frozen=True, slots=True)
class InstrumentMappingEvidence:
    research_instrument_id: str
    broker_instrument_id: str
    mt5_probe_id: str
    observed_at: datetime
    research_symbol: str
    broker_symbol: str
    symbol_text_matches: bool
    quote_currency_matches: bool
    broker_path: str
    operator_attested_same_security: bool
    broker_path_is_exchange_authority: bool = False
    limitations: tuple[str, ...] = (
        "evidence:broker_path_not_listed_exchange_authority",
        "evidence:no_pit_security_master",
    )
    schema_version: str = "finagent.instrument-mapping-evidence.v1"

    def __post_init__(self) -> None:
        for name in (
            "research_instrument_id",
            "broker_instrument_id",
            "mt5_probe_id",
            "research_symbol",
            "broker_symbol",
        ):
            object.__setattr__(self, name, require_non_empty(str(getattr(self, name)), name))
        object.__setattr__(
            self, "observed_at", require_aware_datetime(self.observed_at, "observed_at")
        )
        object.__setattr__(self, "broker_path", self.broker_path.strip())
        if self.broker_path_is_exchange_authority:
            raise ValueError("MT5 broker path cannot be promoted to listed-exchange authority")
        object.__setattr__(self, "limitations", _normalized_limitations(self.limitations))

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="instrument-mapping-evidence")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "research_instrument_id": self.research_instrument_id,
            "broker_instrument_id": self.broker_instrument_id,
            "mt5_probe_id": self.mt5_probe_id,
            "observed_at": self.observed_at.astimezone(UTC).isoformat(),
            "research_symbol": self.research_symbol,
            "broker_symbol": self.broker_symbol,
            "symbol_text_matches": self.symbol_text_matches,
            "quote_currency_matches": self.quote_currency_matches,
            "broker_path": self.broker_path,
            "operator_attested_same_security": self.operator_attested_same_security,
            "broker_path_is_exchange_authority": self.broker_path_is_exchange_authority,
            "limitations": list(self.limitations),
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


@dataclass(frozen=True, slots=True)
class InstrumentMapping:
    research: ResearchInstrument
    broker: BrokerInstrument
    evidence: InstrumentMappingEvidence
    status: InstrumentMappingStatus
    rejection_reason: str | None = None
    schema_version: str = "finagent.instrument-mapping.v1"

    def __post_init__(self) -> None:
        if self.evidence.research_instrument_id != self.research.research_instrument_id:
            raise ValueError("mapping evidence research identity mismatch")
        if self.evidence.broker_instrument_id != self.broker.broker_instrument_id:
            raise ValueError("mapping evidence broker identity mismatch")
        reason = self.rejection_reason.strip() if self.rejection_reason else None
        object.__setattr__(self, "rejection_reason", reason)
        if self.status is InstrumentMappingStatus.REJECTED and not reason:
            raise ValueError("rejected mapping requires rejection_reason")
        if self.status is InstrumentMappingStatus.ACCEPTED_FOR_ENGINEERING:
            if not self.broker.visible or not self.broker.tradable:
                raise ValueError("accepted engineering mapping requires visible/tradable broker symbol")
            if not self.evidence.operator_attested_same_security:
                raise ValueError("accepted engineering mapping requires explicit operator attestation")
            if not self.evidence.quote_currency_matches:
                raise ValueError("accepted engineering mapping requires quote-currency match")
            if reason is not None:
                raise ValueError("accepted mapping cannot carry rejection_reason")

    @property
    def mapping_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="instrument-mapping")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "research": self.research.to_dict(),
            "broker": self.broker.to_dict(),
            "evidence": self.evidence.to_dict(),
            "status": self.status.value,
            "rejection_reason": self.rejection_reason,
        }
        if include_id:
            payload["mapping_id"] = self.mapping_id
        return payload


@dataclass(frozen=True, slots=True)
class EngineeringUniverse:
    mappings: tuple[InstrumentMapping, ...]
    limitations: tuple[str, ...] = (
        "universe:engineering_integration_only",
        "universe:not_survivorship_unbiased",
        "universe:no_market_wide_alpha_claim",
    )
    schema_version: str = "finagent.engineering-universe.v1"

    def __post_init__(self) -> None:
        if not self.mappings:
            raise ValueError("engineering universe requires at least one mapping")
        if any(
            mapping.status is not InstrumentMappingStatus.ACCEPTED_FOR_ENGINEERING
            for mapping in self.mappings
        ):
            raise ValueError("engineering universe can contain only accepted engineering mappings")
        research_ids = tuple(mapping.research.research_instrument_id for mapping in self.mappings)
        broker_ids = tuple(mapping.broker.broker_instrument_id for mapping in self.mappings)
        if len(research_ids) != len(set(research_ids)):
            raise ValueError("engineering universe cannot repeat research instruments")
        if len(broker_ids) != len(set(broker_ids)):
            raise ValueError("engineering universe cannot repeat broker instruments")
        object.__setattr__(self, "limitations", _normalized_limitations(self.limitations))

    @property
    def universe_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="engineering-universe")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "mapping_ids": [mapping.mapping_id for mapping in self.mappings],
            "research_instrument_ids": [
                mapping.research.research_instrument_id for mapping in self.mappings
            ],
            "broker_instrument_ids": [
                mapping.broker.broker_instrument_id for mapping in self.mappings
            ],
            "limitations": list(self.limitations),
        }
        if include_id:
            payload["universe_id"] = self.universe_id
        return payload

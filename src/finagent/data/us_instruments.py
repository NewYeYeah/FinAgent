from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from finagent.domain.instruments import (
    BrokerInstrument,
    EngineeringUniverse,
    InstrumentMapping,
    InstrumentMappingEvidence,
    InstrumentMappingStatus,
    ResearchInstrument,
)


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{field_name} must be a sequence")
    return value


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _optional_text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return int(value)
    raise ValueError(f"{field_name} must be integer-like")


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float, str)):
        return float(value)
    raise ValueError(f"{field_name} must be numeric")


def _boolean(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field_name} must be boolean")


def _aware_datetime(value: object, field_name: str) -> datetime:
    rendered = _text(value, field_name).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(rendered)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _normalized_pairs(values: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []
    seen_research: set[str] = set()
    for research_symbol, broker_symbol in values:
        research = research_symbol.strip()
        broker = broker_symbol.strip()
        if not research or not broker:
            raise ValueError("mapping pairs require non-empty research and broker symbols")
        if research in seen_research:
            raise ValueError(f"duplicate research mapping request: {research}")
        seen_research.add(research)
        normalized.append((research, broker))
    if not normalized:
        raise ValueError("at least one mapping pair is required")
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class EngineeringUniverseMaterialization:
    source_candidate: str
    source_revision: str
    mt5_probe_id: str
    broker_server: str
    requested_pairs: tuple[tuple[str, str], ...]
    mappings: tuple[InstrumentMapping, ...]
    unmapped_requests: tuple[str, ...]
    generated_at: datetime
    schema_version: str = "finagent.engineering-universe-materialization.v1"

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers = list(self.unmapped_requests)
        for mapping in self.mappings:
            if mapping.status is InstrumentMappingStatus.REVIEW_REQUIRED:
                blockers.append(
                    f"mapping:{mapping.research.source_symbol}:operator_attestation_required"
                )
            elif mapping.status is InstrumentMappingStatus.REJECTED:
                blockers.append(
                    f"mapping:{mapping.research.source_symbol}:"
                    f"{mapping.rejection_reason or 'rejected'}"
                )
        return tuple(dict.fromkeys(blockers))

    @property
    def accepted(self) -> bool:
        return not self.blockers and bool(self.mappings)

    @property
    def universe(self) -> EngineeringUniverse | None:
        if not self.accepted:
            return None
        return EngineeringUniverse(mappings=self.mappings)

    @property
    def limitations(self) -> tuple[str, ...]:
        values: list[str] = [
            "universe:engineering_integration_only",
            "universe:not_survivorship_unbiased",
            "identity:no_point_in_time_security_master",
            "identity:broker_path_not_exchange_authority",
        ]
        for mapping in self.mappings:
            values.extend(mapping.research.limitations)
            values.extend(mapping.broker.limitations)
            values.extend(mapping.evidence.limitations)
        return tuple(dict.fromkeys(values))

    @property
    def materialization_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="engineering-universe-materialization",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        universe = self.universe
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "source_candidate": self.source_candidate,
            "source_revision": self.source_revision,
            "mt5_probe_id": self.mt5_probe_id,
            "broker_server": self.broker_server,
            "requested_pairs": [
                {"research_symbol": research, "broker_symbol": broker}
                for research, broker in self.requested_pairs
            ],
            "mappings": [mapping.to_dict() for mapping in self.mappings],
            "unmapped_requests": list(self.unmapped_requests),
            "generated_at": self.generated_at.astimezone(UTC).isoformat(),
            "accepted": self.accepted,
            "blockers": list(self.blockers),
            "limitations": list(self.limitations),
            "universe": universe.to_dict() if universe is not None else None,
        }
        if include_id:
            payload["materialization_id"] = self.materialization_id
        return payload


def _broker_instrument_from_spec(
    spec: Mapping[str, object],
    *,
    broker_server: str,
    terminal_capability_id: str,
) -> BrokerInstrument:
    return BrokerInstrument(
        broker_symbol=_text(spec.get("symbol"), "symbols[].symbol"),
        broker_server=broker_server,
        terminal_capability_id=terminal_capability_id,
        symbol_spec_id=_text(spec.get("spec_id"), "symbols[].spec_id"),
        path=_optional_text(spec.get("path")),
        visible=_boolean(spec.get("visible"), "symbols[].visible"),
        tradable=_boolean(spec.get("tradable"), "symbols[].tradable"),
        trade_mode=_integer(spec.get("trade_mode"), "symbols[].trade_mode"),
        trade_calc_mode=_integer(spec.get("trade_calc_mode"), "symbols[].trade_calc_mode"),
        point=_number(spec.get("point"), "symbols[].point"),
        tick_size=_number(spec.get("tick_size"), "symbols[].tick_size"),
        tick_value=_number(spec.get("tick_value"), "symbols[].tick_value"),
        contract_size=_number(spec.get("contract_size"), "symbols[].contract_size"),
        volume_min=_number(spec.get("volume_min"), "symbols[].volume_min"),
        volume_max=_number(spec.get("volume_max"), "symbols[].volume_max"),
        volume_step=_number(spec.get("volume_step"), "symbols[].volume_step"),
        margin_initial=_number(spec.get("margin_initial"), "symbols[].margin_initial"),
        margin_maintenance=_number(
            spec.get("margin_maintenance"),
            "symbols[].margin_maintenance",
        ),
        swap_mode=_integer(spec.get("swap_mode"), "symbols[].swap_mode"),
        swap_long=_number(spec.get("swap_long"), "symbols[].swap_long"),
        swap_short=_number(spec.get("swap_short"), "symbols[].swap_short"),
        filling_mode=_integer(spec.get("filling_mode"), "symbols[].filling_mode"),
        order_mode=_integer(spec.get("order_mode"), "symbols[].order_mode"),
        currency_base=_optional_text(spec.get("currency_base")),
        currency_profit=_optional_text(spec.get("currency_profit")),
        currency_margin=_optional_text(spec.get("currency_margin")),
    )


def materialize_engineering_universe_from_mt5_probe(
    probe: Mapping[str, object],
    *,
    mapping_pairs: tuple[tuple[str, str], ...],
    accepted_research_symbols: frozenset[str] = frozenset(),
    source_candidate: str = "hf-mito0o852-ohlcv-1m",
    source_revision: str = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56",
    generated_at: datetime | None = None,
) -> EngineeringUniverseMaterialization:
    pairs = _normalized_pairs(mapping_pairs)
    probe_id = _text(probe.get("probe_id"), "probe_id")
    terminal = _mapping(probe.get("terminal"), "terminal")
    broker_server = _text(terminal.get("broker_server"), "terminal.broker_server")
    terminal_capability_id = _text(
        terminal.get("capability_id"),
        "terminal.capability_id",
    )
    observed_at = _aware_datetime(probe.get("probed_at"), "probed_at")
    generated = generated_at or datetime.now(UTC)
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")

    symbol_specs: dict[str, Mapping[str, object]] = {}
    for raw in _sequence(probe.get("symbols"), "symbols"):
        spec = _mapping(raw, "symbols[]")
        symbol = _text(spec.get("symbol"), "symbols[].symbol")
        if symbol in symbol_specs:
            raise ValueError(f"duplicate broker symbol in probe: {symbol}")
        symbol_specs[symbol] = spec

    mappings: list[InstrumentMapping] = []
    unmapped: list[str] = []
    attested = frozenset(
        symbol.strip() for symbol in accepted_research_symbols if symbol.strip()
    )

    for research_symbol, broker_symbol in pairs:
        spec = symbol_specs.get(broker_symbol)
        if spec is None:
            unmapped.append(
                f"mapping:{research_symbol}:broker_symbol_missing:{broker_symbol}"
            )
            continue

        research = ResearchInstrument(
            source_symbol=research_symbol,
            source_candidate=source_candidate,
            source_revision=source_revision,
        )
        broker = _broker_instrument_from_spec(
            spec,
            broker_server=broker_server,
            terminal_capability_id=terminal_capability_id,
        )
        quote_matches = research.quote_currency in {
            broker.currency_base,
            broker.currency_profit,
            broker.currency_margin,
        }
        operator_attested = research_symbol in attested
        evidence = InstrumentMappingEvidence(
            research_instrument_id=research.research_instrument_id,
            broker_instrument_id=broker.broker_instrument_id,
            mt5_probe_id=probe_id,
            observed_at=observed_at,
            research_symbol=research_symbol,
            broker_symbol=broker_symbol,
            symbol_text_matches=research_symbol == broker_symbol,
            quote_currency_matches=quote_matches,
            broker_path=broker.path,
            operator_attested_same_security=operator_attested,
        )

        rejection_reason: str | None = None
        if not broker.visible:
            rejection_reason = "broker_symbol_not_visible"
        elif not broker.tradable:
            rejection_reason = "broker_symbol_not_tradable"
        elif not quote_matches:
            rejection_reason = "quote_currency_mismatch"

        if rejection_reason is not None:
            status = InstrumentMappingStatus.REJECTED
        elif operator_attested:
            status = InstrumentMappingStatus.ACCEPTED_FOR_ENGINEERING
        else:
            status = InstrumentMappingStatus.REVIEW_REQUIRED

        mappings.append(
            InstrumentMapping(
                research=research,
                broker=broker,
                evidence=evidence,
                status=status,
                rejection_reason=rejection_reason,
            )
        )

    return EngineeringUniverseMaterialization(
        source_candidate=source_candidate.strip(),
        source_revision=source_revision.strip(),
        mt5_probe_id=probe_id,
        broker_server=broker_server,
        requested_pairs=pairs,
        mappings=tuple(mappings),
        unmapped_requests=tuple(unmapped),
        generated_at=generated.astimezone(UTC),
    )

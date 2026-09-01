from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from finagent.data.us_instruments import (
    EngineeringUniverseMaterialization,
    materialize_engineering_universe_from_mt5_probe,
)


def _canonical_hash(payload: Mapping[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
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


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be numeric")
    return float(value)


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be integer-like")
    return int(value)


def _aware(value: object, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, field_name).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class USCandidateQuoteSnapshot:
    symbol: str
    sampled_at: datetime
    bid: float
    ask: float
    visible: bool
    tradable: bool
    schema_version: str = "finagent.us-candidate-quote-snapshot.v1"

    def __post_init__(self) -> None:
        symbol = self.symbol.strip()
        if not symbol:
            raise ValueError("symbol must be non-empty")
        if self.sampled_at.tzinfo is None or self.sampled_at.utcoffset() is None:
            raise ValueError("sampled_at must be timezone-aware")
        if self.bid <= 0 or self.ask <= 0 or self.ask < self.bid:
            raise ValueError("candidate quote requires positive bid/ask with ask >= bid")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "sampled_at", self.sampled_at.astimezone(UTC))

    @property
    def midpoint(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread_bps(self) -> float:
        return (self.ask - self.bid) / self.midpoint * 10_000.0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "sampled_at": self.sampled_at.isoformat(),
            "bid": self.bid,
            "ask": self.ask,
            "midpoint": self.midpoint,
            "spread_bps": self.spread_bps,
            "visible": self.visible,
            "tradable": self.tradable,
        }


@dataclass(frozen=True, slots=True)
class USCandidateQuoteProbeReport:
    candidate_selection_id: str
    mt5_capability_probe_id: str
    broker_server: str
    requested_symbols: tuple[str, ...]
    quotes: tuple[USCandidateQuoteSnapshot, ...]
    missing_or_invalid_symbols: tuple[str, ...]
    minimum_valid_quote_count: int
    required_seed_symbols: tuple[str, ...]
    generated_at: datetime
    schema_version: str = "finagent.us-candidate-quote-probe-report.v1"

    @property
    def valid_quote_symbols(self) -> tuple[str, ...]:
        return tuple(item.symbol for item in self.quotes)

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if len(self.quotes) < self.minimum_valid_quote_count:
            blockers.append(
                f"quote_probe:insufficient_valid_quotes:{len(self.quotes)}"
                f"<{self.minimum_valid_quote_count}"
            )
        available = set(self.valid_quote_symbols)
        blockers.extend(
            f"quote_probe:seed_quote_missing:{symbol}"
            for symbol in self.required_seed_symbols
            if symbol not in available
        )
        return tuple(blockers)

    @property
    def ready_for_finalization(self) -> bool:
        return not self.blockers

    @property
    def report_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "candidate_selection_id": self.candidate_selection_id,
                "mt5_capability_probe_id": self.mt5_capability_probe_id,
                "broker_server": self.broker_server,
                "requested_symbols": list(self.requested_symbols),
                "quotes": [item.to_dict() for item in self.quotes],
                "missing_or_invalid_symbols": list(self.missing_or_invalid_symbols),
                "minimum_valid_quote_count": self.minimum_valid_quote_count,
                "required_seed_symbols": list(self.required_seed_symbols),
            },
            prefix="us-candidate-quote-probe",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "candidate_selection_id": self.candidate_selection_id,
            "mt5_capability_probe_id": self.mt5_capability_probe_id,
            "broker_server": self.broker_server,
            "requested_symbols": list(self.requested_symbols),
            "valid_quote_count": len(self.quotes),
            "missing_or_invalid_symbols": list(self.missing_or_invalid_symbols),
            "minimum_valid_quote_count": self.minimum_valid_quote_count,
            "required_seed_symbols": list(self.required_seed_symbols),
            "ready_for_finalization": self.ready_for_finalization,
            "blockers": list(self.blockers),
            "quotes": [item.to_dict() for item in self.quotes],
            "generated_at": self.generated_at.astimezone(UTC).isoformat(),
        }


def build_candidate_quote_probe_report(
    candidate_document: Mapping[str, object],
    mt5_probe_document: Mapping[str, object],
    symbol_rows: Sequence[Mapping[str, object]],
    *,
    generated_at: datetime | None = None,
) -> USCandidateQuoteProbeReport:
    if not _boolean(candidate_document.get("ready_for_spread_probe"), "candidate.ready_for_spread_probe"):
        raise ValueError("candidate report is not ready for quote probing")
    selection_id = _text(candidate_document.get("selection_id"), "candidate.selection_id")
    requested = tuple(
        _text(item, "candidate.spread_probe_symbols[]")
        for item in _sequence(candidate_document.get("spread_probe_symbols"), "candidate.spread_probe_symbols")
    )
    policy = _mapping(candidate_document.get("policy"), "candidate.policy")
    minimum_count = _integer(
        policy.get("minimum_selected_count"),
        "candidate.policy.minimum_selected_count",
    )
    seeds = tuple(
        _text(item, "candidate.policy.seed_symbols[]")
        for item in _sequence(policy.get("seed_symbols", ()), "candidate.policy.seed_symbols")
    )
    probe_id = _text(mt5_probe_document.get("probe_id"), "mt5_probe.probe_id")
    terminal = _mapping(mt5_probe_document.get("terminal"), "mt5_probe.terminal")
    broker_server = _text(terminal.get("broker_server"), "mt5_probe.terminal.broker_server")

    rows_by_symbol: dict[str, Mapping[str, object]] = {}
    for row in symbol_rows:
        symbol = _text(row.get("name", row.get("symbol")), "symbol_rows[].name")
        rows_by_symbol[symbol] = row

    quotes: list[USCandidateQuoteSnapshot] = []
    invalid: list[str] = []
    for symbol in requested:
        row = rows_by_symbol.get(symbol)
        if row is None:
            invalid.append(symbol)
            continue
        try:
            bid = _number(row.get("bid"), f"symbol_rows[{symbol}].bid")
            ask = _number(row.get("ask"), f"symbol_rows[{symbol}].ask")
            time_value = row.get("time")
            sampled_at = datetime.fromtimestamp(
                _integer(time_value, f"symbol_rows[{symbol}].time"),
                tz=UTC,
            )
            trade_mode = _integer(
                row.get("trade_mode"),
                f"symbol_rows[{symbol}].trade_mode",
            )
            quote = USCandidateQuoteSnapshot(
                symbol=symbol,
                sampled_at=sampled_at,
                bid=bid,
                ask=ask,
                visible=_boolean(
                    row.get("visible", False),
                    f"symbol_rows[{symbol}].visible",
                ),
                tradable=trade_mode != 0,
            )
        except (TypeError, ValueError, OverflowError, OSError):
            invalid.append(symbol)
            continue
        quotes.append(quote)

    timestamp = generated_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    return USCandidateQuoteProbeReport(
        candidate_selection_id=selection_id,
        mt5_capability_probe_id=probe_id,
        broker_server=broker_server,
        requested_symbols=requested,
        quotes=tuple(sorted(quotes, key=lambda item: item.symbol)),
        missing_or_invalid_symbols=tuple(sorted(dict.fromkeys(invalid))),
        minimum_valid_quote_count=minimum_count,
        required_seed_symbols=tuple(sorted(dict.fromkeys(seeds))),
        generated_at=timestamp.astimezone(UTC),
    )


@dataclass(frozen=True, slots=True)
class USUniverseFinalizationPolicy:
    target_count: int = 25
    minimum_count: int = 20
    maximum_count: int = 30
    maximum_current_spread_bps: float = 50.0
    require_tradable: bool = True
    require_operator_attestation: bool = True
    schema_version: str = "finagent.us-engineering-universe-finalization-policy.v1"

    def __post_init__(self) -> None:
        if not 1 <= self.minimum_count <= self.target_count <= self.maximum_count:
            raise ValueError("universe counts must satisfy 1 <= minimum <= target <= maximum")
        if self.maximum_current_spread_bps <= 0:
            raise ValueError("maximum_current_spread_bps must be positive")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-universe-final-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "target_count": self.target_count,
            "minimum_count": self.minimum_count,
            "maximum_count": self.maximum_count,
            "maximum_current_spread_bps": self.maximum_current_spread_bps,
            "require_tradable": self.require_tradable,
            "require_operator_attestation": self.require_operator_attestation,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


@dataclass(frozen=True, slots=True)
class USUniverseFinalizationReport:
    policy: USUniverseFinalizationPolicy
    candidate_selection_id: str
    quote_probe_id: str
    selected_symbols: tuple[str, ...]
    excluded_by_spread: tuple[str, ...]
    operator_attested: bool
    materialization: EngineeringUniverseMaterialization | None
    generated_at: datetime
    schema_version: str = "finagent.us-engineering-universe-finalization-report.v1"

    @property
    def universe_id(self) -> str | None:
        universe = self.materialization.universe if self.materialization is not None else None
        return universe.universe_id if universe is not None else None

    @property
    def accepted_mapping_count(self) -> int:
        if self.materialization is None:
            return 0
        return sum(
            mapping.status.value == "accepted_for_engineering"
            for mapping in self.materialization.mappings
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if len(self.selected_symbols) < self.policy.target_count:
            blockers.append(
                f"universe:insufficient_spread_eligible:{len(self.selected_symbols)}"
                f"<{self.policy.target_count}"
            )
        if self.policy.require_operator_attestation and not self.operator_attested:
            blockers.append("universe:operator_attestation_required")
        if self.materialization is None:
            blockers.append("universe:materialization_missing")
        else:
            blockers.extend(self.materialization.blockers)
        return tuple(dict.fromkeys(blockers))

    @property
    def accepted(self) -> bool:
        return not self.blockers and self.universe_id is not None

    @property
    def report_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "policy_id": self.policy.policy_id,
                "candidate_selection_id": self.candidate_selection_id,
                "quote_probe_id": self.quote_probe_id,
                "selected_symbols": list(self.selected_symbols),
                "excluded_by_spread": list(self.excluded_by_spread),
                "operator_attested": self.operator_attested,
                "materialization_id": (
                    self.materialization.materialization_id
                    if self.materialization is not None
                    else None
                ),
            },
            prefix="us-engineering-universe-finalization",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "policy": self.policy.to_dict(),
            "candidate_selection_id": self.candidate_selection_id,
            "quote_probe_id": self.quote_probe_id,
            "selected_symbols": list(self.selected_symbols),
            "excluded_by_spread": list(self.excluded_by_spread),
            "operator_attested": self.operator_attested,
            "materialization": (
                self.materialization.to_dict() if self.materialization is not None else None
            ),
            "universe_id": self.universe_id,
            "accepted": self.accepted,
            "accepted_mapping_count": self.accepted_mapping_count,
            "blockers": list(self.blockers),
            "limitations": [
                "universe:engineering_integration_only",
                "universe:not_survivorship_unbiased",
                "identity:no_point_in_time_security_master",
                "identity:exact_symbol_match_requires_operator_attestation",
                "spread:single_quote_snapshot_is_engineering_filter_not_execution_cost_authority",
            ],
            "generated_at": self.generated_at.astimezone(UTC).isoformat(),
        }


def finalize_us_engineering_universe(
    candidate_document: Mapping[str, object],
    quote_document: Mapping[str, object],
    mt5_probe_document: Mapping[str, object],
    *,
    policy: USUniverseFinalizationPolicy = USUniverseFinalizationPolicy(),
    operator_attested: bool = False,
    generated_at: datetime | None = None,
) -> USUniverseFinalizationReport:
    candidate_id = _text(candidate_document.get("selection_id"), "candidate.selection_id")
    quote_id = _text(quote_document.get("report_id"), "quote.report_id")
    if _text(
        quote_document.get("candidate_selection_id"),
        "quote.candidate_selection_id",
    ) != candidate_id:
        raise ValueError("quote probe does not bind the supplied candidate selection")
    if not _boolean(quote_document.get("ready_for_finalization"), "quote.ready_for_finalization"):
        raise ValueError("quote probe is not ready for finalization")

    quote_bps: dict[str, float] = {}
    for raw in _sequence(quote_document.get("quotes"), "quote.quotes"):
        row = _mapping(raw, "quote.quotes[]")
        symbol = _text(row.get("symbol"), "quote.quotes[].symbol")
        if policy.require_tradable and not _boolean(
            row.get("tradable"),
            "quote.quotes[].tradable",
        ):
            continue
        quote_bps[symbol] = _number(row.get("spread_bps"), "quote.quotes[].spread_bps")

    candidates: list[tuple[int, str]] = []
    excluded: list[str] = []
    for raw in _sequence(candidate_document.get("candidates"), "candidate.candidates"):
        row = _mapping(raw, "candidate.candidates[]")
        symbol = _text(row.get("research_symbol"), "candidate.candidates[].research_symbol")
        rank = _integer(row.get("rank"), "candidate.candidates[].rank")
        spread = quote_bps.get(symbol)
        if spread is None or spread > policy.maximum_current_spread_bps:
            excluded.append(symbol)
            continue
        candidates.append((rank, symbol))

    candidates.sort(key=lambda item: (item[0], item[1]))
    selected = tuple(symbol for _rank, symbol in candidates[: policy.target_count])
    materialization: EngineeringUniverseMaterialization | None = None
    if selected:
        materialization = materialize_engineering_universe_from_mt5_probe(
            mt5_probe_document,
            mapping_pairs=tuple((symbol, symbol) for symbol in selected),
            accepted_research_symbols=(
                frozenset(selected) if operator_attested else frozenset()
            ),
        )

    timestamp = generated_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    return USUniverseFinalizationReport(
        policy=policy,
        candidate_selection_id=candidate_id,
        quote_probe_id=quote_id,
        selected_symbols=selected,
        excluded_by_spread=tuple(sorted(dict.fromkeys(excluded))),
        operator_attested=operator_attested,
        materialization=materialization,
        generated_at=timestamp.astimezone(UTC),
    )

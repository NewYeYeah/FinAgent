from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from finagent.brokers.mt5.clock import (
    MT5BrokerClockEvidence,
    mt5_broker_clock_evidence_from_document,
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


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be integer-like")
    return int(value)


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _parse_datetime(value: object, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, field_name))
    return _aware_utc(parsed, field_name)


def _raw_time_msc(row: Mapping[str, object], field_name: str) -> int:
    raw_msc = row.get("time_msc")
    if raw_msc is not None:
        value = _integer(raw_msc, f"{field_name}.time_msc")
        if value > 0:
            return value
    seconds = _integer(row.get("time"), f"{field_name}.time")
    if seconds <= 0:
        raise ValueError(f"{field_name} timestamp must be positive")
    return seconds * 1000


@dataclass(frozen=True, slots=True)
class USCandidateQuoteProbePolicyV2:
    maximum_quote_age_seconds: int = 900
    maximum_future_quote_skew_seconds: int = 60
    require_visible: bool = True
    require_tradable: bool = True
    schema_version: str = "finagent.us-candidate-quote-probe-policy.v2"

    def __post_init__(self) -> None:
        if self.maximum_quote_age_seconds < 1:
            raise ValueError("maximum_quote_age_seconds must be >= 1")
        if self.maximum_future_quote_skew_seconds < 0:
            raise ValueError("maximum_future_quote_skew_seconds must be >= 0")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-candidate-quote-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "maximum_quote_age_seconds": self.maximum_quote_age_seconds,
            "maximum_future_quote_skew_seconds": self.maximum_future_quote_skew_seconds,
            "require_visible": self.require_visible,
            "require_tradable": self.require_tradable,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


DEFAULT_US_CANDIDATE_QUOTE_PROBE_POLICY_V2 = USCandidateQuoteProbePolicyV2()


@dataclass(frozen=True, slots=True)
class USCandidateQuoteSnapshotV2:
    symbol: str
    raw_broker_time_msc: int
    broker_clock_offset_seconds: int
    normalized_sampled_at_utc: datetime
    retrieved_at_utc: datetime
    bid: float
    ask: float
    visible: bool
    tradable: bool
    clock_evidence_id: str
    schema_version: str = "finagent.us-candidate-quote-snapshot.v2"

    def __post_init__(self) -> None:
        symbol = self.symbol.strip()
        evidence_id = self.clock_evidence_id.strip()
        if not symbol or not evidence_id:
            raise ValueError("symbol and clock_evidence_id must be non-empty")
        if self.raw_broker_time_msc <= 0:
            raise ValueError("raw_broker_time_msc must be positive")
        normalized = _aware_utc(
            self.normalized_sampled_at_utc,
            "normalized_sampled_at_utc",
        )
        retrieved = _aware_utc(self.retrieved_at_utc, "retrieved_at_utc")
        if not math.isfinite(self.bid) or not math.isfinite(self.ask):
            raise ValueError("quote bid/ask must be finite")
        if self.bid <= 0 or self.ask <= 0 or self.ask < self.bid:
            raise ValueError("quote requires positive bid/ask with ask >= bid")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "clock_evidence_id", evidence_id)
        object.__setattr__(self, "normalized_sampled_at_utc", normalized)
        object.__setattr__(self, "retrieved_at_utc", retrieved)

    @property
    def raw_broker_wall_time(self) -> datetime:
        return datetime.fromtimestamp(self.raw_broker_time_msc / 1000.0, tz=UTC)

    @property
    def quote_age_at_retrieval_seconds(self) -> float:
        return (self.retrieved_at_utc - self.normalized_sampled_at_utc).total_seconds()

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
            "raw_broker_time_msc": self.raw_broker_time_msc,
            "raw_broker_wall_time": self.raw_broker_wall_time.isoformat(),
            "broker_clock_offset_seconds": self.broker_clock_offset_seconds,
            "normalized_sampled_at_utc": self.normalized_sampled_at_utc.isoformat(),
            "retrieved_at_utc": self.retrieved_at_utc.isoformat(),
            "quote_age_at_retrieval_seconds": self.quote_age_at_retrieval_seconds,
            "bid": self.bid,
            "ask": self.ask,
            "midpoint": self.midpoint,
            "spread_bps": self.spread_bps,
            "visible": self.visible,
            "tradable": self.tradable,
            "clock_evidence_id": self.clock_evidence_id,
        }


@dataclass(frozen=True, slots=True)
class USCandidateQuoteIssue:
    symbol: str
    reasons: tuple[str, ...]
    schema_version: str = "finagent.us-candidate-quote-issue.v1"

    def __post_init__(self) -> None:
        symbol = self.symbol.strip()
        reasons = tuple(dict.fromkeys(item.strip() for item in self.reasons if item.strip()))
        if not symbol or not reasons:
            raise ValueError("quote issue requires symbol and at least one reason")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "reasons", reasons)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class USCandidateQuoteProbeReportV2:
    candidate_selection_id: str
    mt5_capability_probe_id: str
    broker_server: str
    policy: USCandidateQuoteProbePolicyV2
    broker_clock_evidence: MT5BrokerClockEvidence
    requested_symbols: tuple[str, ...]
    quotes: tuple[USCandidateQuoteSnapshotV2, ...]
    issues: tuple[USCandidateQuoteIssue, ...]
    minimum_valid_quote_count: int
    required_seed_symbols: tuple[str, ...]
    generated_at: datetime
    schema_version: str = "finagent.us-candidate-quote-probe-report.v2"

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_selection_id",
            "mt5_capability_probe_id",
            "broker_server",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.minimum_valid_quote_count < 1:
            raise ValueError("minimum_valid_quote_count must be >= 1")
        if self.broker_clock_evidence.broker_server != self.broker_server:
            raise ValueError("quote report broker server must match broker clock evidence")
        requested = tuple(dict.fromkeys(self.requested_symbols))
        if len(requested) != len(self.requested_symbols):
            raise ValueError("requested_symbols must be unique")
        quote_symbols = tuple(item.symbol for item in self.quotes)
        if len(quote_symbols) != len(set(quote_symbols)):
            raise ValueError("quote report cannot repeat quote symbols")
        issue_symbols = tuple(item.symbol for item in self.issues)
        if len(issue_symbols) != len(set(issue_symbols)):
            raise ValueError("quote report cannot repeat issue symbols")
        generated = _aware_utc(self.generated_at, "generated_at")
        object.__setattr__(self, "generated_at", generated)

    @property
    def issue_by_symbol(self) -> dict[str, tuple[str, ...]]:
        return {item.symbol: item.reasons for item in self.issues}

    @property
    def valid_quote_symbols(self) -> tuple[str, ...]:
        invalid = set(self.issue_by_symbol)
        return tuple(item.symbol for item in self.quotes if item.symbol not in invalid)

    @property
    def fresh_quote_symbols(self) -> tuple[str, ...]:
        return self.valid_quote_symbols

    @property
    def missing_or_invalid_symbols(self) -> tuple[str, ...]:
        return tuple(item.symbol for item in self.issues)

    @property
    def invalid_reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            for reason in issue.reasons:
                counts[reason] = counts.get(reason, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.broker_clock_evidence.passed:
            blockers.append("quote_probe:broker_clock_evidence_failed")
        valid = set(self.valid_quote_symbols)
        if len(valid) < self.minimum_valid_quote_count:
            blockers.append(
                f"quote_probe:insufficient_valid_quotes:{len(valid)}"
                f"<{self.minimum_valid_quote_count}"
            )
        blockers.extend(
            f"quote_probe:seed_quote_invalid:{symbol}"
            for symbol in self.required_seed_symbols
            if symbol not in valid
        )
        return tuple(dict.fromkeys(blockers))

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
                "policy_id": self.policy.policy_id,
                "broker_clock_evidence_id": self.broker_clock_evidence.evidence_id,
                "requested_symbols": list(self.requested_symbols),
                "quotes": [item.to_dict() for item in self.quotes],
                "issues": [item.to_dict() for item in self.issues],
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
            "policy": self.policy.to_dict(),
            "broker_clock_evidence_id": self.broker_clock_evidence.evidence_id,
            "broker_clock_evidence": self.broker_clock_evidence.to_dict(),
            "requested_symbols": list(self.requested_symbols),
            "valid_quote_count": len(self.valid_quote_symbols),
            "valid_quote_symbols": list(self.valid_quote_symbols),
            "fresh_quote_symbols": list(self.fresh_quote_symbols),
            "missing_or_invalid_symbols": list(self.missing_or_invalid_symbols),
            "invalid_quote_reasons": {
                item.symbol: list(item.reasons) for item in self.issues
            },
            "invalid_reason_counts": self.invalid_reason_counts,
            "minimum_valid_quote_count": self.minimum_valid_quote_count,
            "required_seed_symbols": list(self.required_seed_symbols),
            "ready_for_finalization": self.ready_for_finalization,
            "blockers": list(self.blockers),
            "quotes": [item.to_dict() for item in self.quotes],
            "generated_at": self.generated_at.isoformat(),
        }


def build_candidate_quote_probe_report_v2(
    candidate_document: Mapping[str, object],
    mt5_probe_document: Mapping[str, object],
    symbol_rows: Sequence[Mapping[str, object]],
    tick_rows: Mapping[str, Mapping[str, object] | None],
    retrieved_at_by_symbol: Mapping[str, datetime],
    broker_clock_evidence: MT5BrokerClockEvidence,
    *,
    policy: USCandidateQuoteProbePolicyV2 = (
        DEFAULT_US_CANDIDATE_QUOTE_PROBE_POLICY_V2
    ),
    generated_at: datetime | None = None,
) -> USCandidateQuoteProbeReportV2:
    if not _boolean(
        candidate_document.get("ready_for_spread_probe"),
        "candidate.ready_for_spread_probe",
    ):
        raise ValueError("candidate report is not ready for quote probing")
    selection_id = _text(candidate_document.get("selection_id"), "candidate.selection_id")
    requested = tuple(
        _text(item, "candidate.spread_probe_symbols[]")
        for item in _sequence(
            candidate_document.get("spread_probe_symbols"),
            "candidate.spread_probe_symbols",
        )
    )
    candidate_policy = _mapping(candidate_document.get("policy"), "candidate.policy")
    minimum_count = _integer(
        candidate_policy.get("minimum_selected_count"),
        "candidate.policy.minimum_selected_count",
    )
    seeds = tuple(
        sorted(
            dict.fromkeys(
                _text(item, "candidate.policy.seed_symbols[]")
                for item in _sequence(
                    candidate_policy.get("seed_symbols", ()),
                    "candidate.policy.seed_symbols",
                )
            )
        )
    )

    probe_id = _text(mt5_probe_document.get("probe_id"), "mt5_probe.probe_id")
    terminal = _mapping(mt5_probe_document.get("terminal"), "mt5_probe.terminal")
    broker_server = _text(
        terminal.get("broker_server"),
        "mt5_probe.terminal.broker_server",
    )
    candidate_probe_id = _text(
        candidate_document.get("mt5_probe_id"),
        "candidate.mt5_probe_id",
    )
    candidate_server = _text(
        candidate_document.get("broker_server"),
        "candidate.broker_server",
    )
    if candidate_probe_id != probe_id:
        raise ValueError("candidate report does not bind the supplied accepted MT5-P0 probe")
    if candidate_server != broker_server:
        raise ValueError("candidate report broker server does not match accepted MT5-P0 probe")
    if broker_clock_evidence.broker_server != broker_server:
        raise ValueError("broker clock evidence server does not match accepted MT5-P0 probe")

    inventory_by_symbol: dict[str, Mapping[str, object]] = {}
    for row in symbol_rows:
        symbol = _text(row.get("name", row.get("symbol")), "symbol_rows[].name")
        inventory_by_symbol[symbol] = row

    quotes: list[USCandidateQuoteSnapshotV2] = []
    issues: list[USCandidateQuoteIssue] = []
    for symbol in requested:
        reasons: list[str] = []
        inventory = inventory_by_symbol.get(symbol)
        if inventory is None:
            reasons.append("symbol_missing")
        else:
            visible = _boolean(
                inventory.get("visible", False),
                f"symbol_rows[{symbol}].visible",
            )
            trade_mode = _integer(
                inventory.get("trade_mode"),
                f"symbol_rows[{symbol}].trade_mode",
            )
            tradable = trade_mode != 0
            if policy.require_visible and not visible:
                reasons.append("not_visible")
            if policy.require_tradable and not tradable:
                reasons.append("not_tradable")

            tick = tick_rows.get(symbol)
            retrieved_raw = retrieved_at_by_symbol.get(symbol)
            if reasons:
                pass
            elif tick is None:
                reasons.append("tick_unavailable")
            elif retrieved_raw is None:
                reasons.append("retrieval_time_unavailable")
            elif not broker_clock_evidence.passed:
                reasons.append("broker_clock_unavailable")
            else:
                try:
                    bid = _number(tick.get("bid"), f"tick_rows[{symbol}].bid")
                    ask = _number(tick.get("ask"), f"tick_rows[{symbol}].ask")
                    if bid <= 0:
                        reasons.append("non_positive_bid")
                    if ask <= 0:
                        reasons.append("non_positive_ask")
                    if bid > 0 and ask > 0 and ask < bid:
                        reasons.append("ask_below_bid")
                    raw_msc = _raw_time_msc(tick, f"tick_rows[{symbol}]")
                    retrieved = _aware_utc(
                        retrieved_raw,
                        f"retrieved_at_by_symbol[{symbol}]",
                    )
                    if not reasons:
                        normalized = broker_clock_evidence.normalize_epoch_msc(raw_msc)
                        quote = USCandidateQuoteSnapshotV2(
                            symbol=symbol,
                            raw_broker_time_msc=raw_msc,
                            broker_clock_offset_seconds=(
                                broker_clock_evidence.inferred_offset_seconds or 0
                            ),
                            normalized_sampled_at_utc=normalized,
                            retrieved_at_utc=retrieved,
                            bid=bid,
                            ask=ask,
                            visible=visible,
                            tradable=tradable,
                            clock_evidence_id=broker_clock_evidence.evidence_id,
                        )
                        age = quote.quote_age_at_retrieval_seconds
                        if age > policy.maximum_quote_age_seconds:
                            reasons.append("stale_quote")
                        if age < -policy.maximum_future_quote_skew_seconds:
                            reasons.append("future_quote")
                        quotes.append(quote)
                except (TypeError, ValueError, OverflowError, OSError):
                    reasons.append("invalid_tick_payload")

        if reasons:
            issues.append(
                USCandidateQuoteIssue(
                    symbol=symbol,
                    reasons=tuple(dict.fromkeys(reasons)),
                )
            )

    timestamp = generated_at or datetime.now(UTC)
    return USCandidateQuoteProbeReportV2(
        candidate_selection_id=selection_id,
        mt5_capability_probe_id=probe_id,
        broker_server=broker_server,
        policy=policy,
        broker_clock_evidence=broker_clock_evidence,
        requested_symbols=requested,
        quotes=tuple(sorted(quotes, key=lambda item: item.symbol)),
        issues=tuple(sorted(issues, key=lambda item: item.symbol)),
        minimum_valid_quote_count=minimum_count,
        required_seed_symbols=seeds,
        generated_at=timestamp,
    )


def candidate_quote_probe_report_v2_from_document(
    document: Mapping[str, object],
) -> USCandidateQuoteProbeReportV2:
    schema = _text(document.get("schema_version"), "quote.schema_version")
    if schema != "finagent.us-candidate-quote-probe-report.v2":
        raise ValueError(f"unsupported candidate quote report schema: {schema}")

    policy_raw = _mapping(document.get("policy"), "quote.policy")
    policy = USCandidateQuoteProbePolicyV2(
        maximum_quote_age_seconds=_integer(
            policy_raw.get("maximum_quote_age_seconds"),
            "quote.policy.maximum_quote_age_seconds",
        ),
        maximum_future_quote_skew_seconds=_integer(
            policy_raw.get("maximum_future_quote_skew_seconds"),
            "quote.policy.maximum_future_quote_skew_seconds",
        ),
        require_visible=_boolean(
            policy_raw.get("require_visible"),
            "quote.policy.require_visible",
        ),
        require_tradable=_boolean(
            policy_raw.get("require_tradable"),
            "quote.policy.require_tradable",
        ),
    )
    stored_policy_id = policy_raw.get("policy_id")
    if stored_policy_id is not None and str(stored_policy_id) != policy.policy_id:
        raise ValueError("stored quote probe policy_id does not match policy content")

    clock_raw = _mapping(
        document.get("broker_clock_evidence"),
        "quote.broker_clock_evidence",
    )
    clock = mt5_broker_clock_evidence_from_document(clock_raw)
    stored_clock_id = _text(
        document.get("broker_clock_evidence_id"),
        "quote.broker_clock_evidence_id",
    )
    if stored_clock_id != clock.evidence_id:
        raise ValueError("quote report broker clock evidence id does not match content")

    quotes: list[USCandidateQuoteSnapshotV2] = []
    for raw in _sequence(document.get("quotes", ()), "quote.quotes"):
        row = _mapping(raw, "quote.quotes[]")
        snapshot = USCandidateQuoteSnapshotV2(
            symbol=_text(row.get("symbol"), "quote.quotes[].symbol"),
            raw_broker_time_msc=_integer(
                row.get("raw_broker_time_msc"),
                "quote.quotes[].raw_broker_time_msc",
            ),
            broker_clock_offset_seconds=_integer(
                row.get("broker_clock_offset_seconds"),
                "quote.quotes[].broker_clock_offset_seconds",
            ),
            normalized_sampled_at_utc=_parse_datetime(
                row.get("normalized_sampled_at_utc"),
                "quote.quotes[].normalized_sampled_at_utc",
            ),
            retrieved_at_utc=_parse_datetime(
                row.get("retrieved_at_utc"),
                "quote.quotes[].retrieved_at_utc",
            ),
            bid=_number(row.get("bid"), "quote.quotes[].bid"),
            ask=_number(row.get("ask"), "quote.quotes[].ask"),
            visible=_boolean(row.get("visible"), "quote.quotes[].visible"),
            tradable=_boolean(row.get("tradable"), "quote.quotes[].tradable"),
            clock_evidence_id=_text(
                row.get("clock_evidence_id"),
                "quote.quotes[].clock_evidence_id",
            ),
        )
        if snapshot.clock_evidence_id != clock.evidence_id:
            raise ValueError("quote snapshot clock_evidence_id does not match report evidence")
        if snapshot.broker_clock_offset_seconds != clock.inferred_offset_seconds:
            raise ValueError("quote snapshot broker clock offset does not match clock evidence")
        if snapshot.normalized_sampled_at_utc != clock.normalize_epoch_msc(
            snapshot.raw_broker_time_msc
        ):
            raise ValueError("quote snapshot normalized timestamp does not match clock evidence")
        quotes.append(snapshot)

    issue_raw = _mapping(
        document.get("invalid_quote_reasons", {}),
        "quote.invalid_quote_reasons",
    )
    issues: list[USCandidateQuoteIssue] = []
    for symbol, raw_reasons in issue_raw.items():
        issues.append(
            USCandidateQuoteIssue(
                symbol=str(symbol),
                reasons=tuple(
                    _text(item, f"quote.invalid_quote_reasons[{symbol}][]")
                    for item in _sequence(
                        raw_reasons,
                        f"quote.invalid_quote_reasons[{symbol}]",
                    )
                ),
            )
        )

    report = USCandidateQuoteProbeReportV2(
        candidate_selection_id=_text(
            document.get("candidate_selection_id"),
            "quote.candidate_selection_id",
        ),
        mt5_capability_probe_id=_text(
            document.get("mt5_capability_probe_id"),
            "quote.mt5_capability_probe_id",
        ),
        broker_server=_text(document.get("broker_server"), "quote.broker_server"),
        policy=policy,
        broker_clock_evidence=clock,
        requested_symbols=tuple(
            _text(item, "quote.requested_symbols[]")
            for item in _sequence(
                document.get("requested_symbols"),
                "quote.requested_symbols",
            )
        ),
        quotes=tuple(sorted(quotes, key=lambda item: item.symbol)),
        issues=tuple(sorted(issues, key=lambda item: item.symbol)),
        minimum_valid_quote_count=_integer(
            document.get("minimum_valid_quote_count"),
            "quote.minimum_valid_quote_count",
        ),
        required_seed_symbols=tuple(
            _text(item, "quote.required_seed_symbols[]")
            for item in _sequence(
                document.get("required_seed_symbols", ()),
                "quote.required_seed_symbols",
            )
        ),
        generated_at=_parse_datetime(document.get("generated_at"), "quote.generated_at"),
    )
    stored_report_id = _text(document.get("report_id"), "quote.report_id")
    if stored_report_id != report.report_id:
        raise ValueError("stored quote report_id does not match report content")
    stored_ready = document.get("ready_for_finalization")
    if stored_ready is not None and stored_ready is not report.ready_for_finalization:
        raise ValueError("stored quote ready_for_finalization does not match report content")
    return report

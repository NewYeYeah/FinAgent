from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from finagent.brokers.mt5.clock import MT5BrokerClockEvidence


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


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


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


@dataclass(frozen=True, slots=True)
class MT5ContinuousQuoteSmokePolicy:
    minimum_symbol_count: int = 3
    maximum_quote_age_seconds: int = 60
    maximum_future_quote_skew_seconds: int = 5
    require_visible: bool = True
    require_tradable: bool = True
    schema_version: str = "finagent.mt5-continuous-quote-smoke-policy.v1"

    def __post_init__(self) -> None:
        if self.minimum_symbol_count < 1:
            raise ValueError("minimum_symbol_count must be >= 1")
        if self.maximum_quote_age_seconds < 1:
            raise ValueError("maximum_quote_age_seconds must be >= 1")
        if self.maximum_future_quote_skew_seconds < 0:
            raise ValueError("maximum_future_quote_skew_seconds must be >= 0")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="mt5-continuous-quote-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "minimum_symbol_count": self.minimum_symbol_count,
            "maximum_quote_age_seconds": self.maximum_quote_age_seconds,
            "maximum_future_quote_skew_seconds": self.maximum_future_quote_skew_seconds,
            "require_visible": self.require_visible,
            "require_tradable": self.require_tradable,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


DEFAULT_MT5_CONTINUOUS_QUOTE_SMOKE_POLICY = MT5ContinuousQuoteSmokePolicy()


@dataclass(frozen=True, slots=True)
class MT5ContinuousQuoteCheck:
    symbol: str
    raw_broker_time_msc: int | None
    normalized_sampled_at_utc: datetime | None
    retrieved_at_utc: datetime
    bid: float | None
    ask: float | None
    visible: bool
    tradable: bool
    blockers: tuple[str, ...]
    schema_version: str = "finagent.mt5-continuous-quote-check.v1"

    def __post_init__(self) -> None:
        symbol = self.symbol.strip()
        if not symbol:
            raise ValueError("symbol must be non-empty")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "retrieved_at_utc", _aware_utc(self.retrieved_at_utc, "retrieved_at_utc"))
        if self.normalized_sampled_at_utc is not None:
            object.__setattr__(
                self,
                "normalized_sampled_at_utc",
                _aware_utc(self.normalized_sampled_at_utc, "normalized_sampled_at_utc"),
            )
        if self.raw_broker_time_msc is not None and self.raw_broker_time_msc <= 0:
            raise ValueError("raw_broker_time_msc must be positive when present")
        for field_name in ("bid", "ask"):
            value = getattr(self, field_name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{field_name} must be finite when present")
        object.__setattr__(self, "blockers", tuple(dict.fromkeys(self.blockers)))

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def quote_age_seconds(self) -> float | None:
        if self.normalized_sampled_at_utc is None:
            return None
        return (self.retrieved_at_utc - self.normalized_sampled_at_utc).total_seconds()

    @property
    def spread_bps(self) -> float | None:
        if self.bid is None or self.ask is None or self.bid <= 0 or self.ask < self.bid:
            return None
        midpoint = (self.bid + self.ask) / 2.0
        if midpoint <= 0:
            return None
        return (self.ask - self.bid) / midpoint * 10_000.0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "passed": self.passed,
            "blockers": list(self.blockers),
            "raw_broker_time_msc": self.raw_broker_time_msc,
            "normalized_sampled_at_utc": (
                self.normalized_sampled_at_utc.isoformat()
                if self.normalized_sampled_at_utc is not None
                else None
            ),
            "retrieved_at_utc": self.retrieved_at_utc.isoformat(),
            "quote_age_seconds": self.quote_age_seconds,
            "bid": self.bid,
            "ask": self.ask,
            "spread_bps": self.spread_bps,
            "visible": self.visible,
            "tradable": self.tradable,
        }


@dataclass(frozen=True, slots=True)
class MT5ContinuousQuoteSmokeReport:
    broker_server: str
    clock_evidence: MT5BrokerClockEvidence
    policy: MT5ContinuousQuoteSmokePolicy
    requested_symbols: tuple[str, ...]
    checks: tuple[MT5ContinuousQuoteCheck, ...]
    generated_at: datetime
    schema_version: str = "finagent.mt5-continuous-quote-smoke-report.v1"

    def __post_init__(self) -> None:
        broker_server = self.broker_server.strip()
        if not broker_server:
            raise ValueError("broker_server must be non-empty")
        object.__setattr__(self, "broker_server", broker_server)
        object.__setattr__(self, "generated_at", _aware_utc(self.generated_at, "generated_at"))
        requested = tuple(dict.fromkeys(item.strip() for item in self.requested_symbols if item.strip()))
        if not requested or len(requested) != len(self.requested_symbols):
            raise ValueError("requested_symbols must be non-empty and unique")
        object.__setattr__(self, "requested_symbols", requested)
        if self.clock_evidence.broker_server != broker_server:
            raise ValueError("clock evidence broker server mismatch")

    @property
    def passed_symbol_count(self) -> int:
        return sum(item.passed for item in self.checks)

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.clock_evidence.passed:
            blockers.append("continuous_quote_smoke:broker_clock_evidence_failed")
        if self.passed_symbol_count < self.policy.minimum_symbol_count:
            blockers.append(
                f"continuous_quote_smoke:insufficient_fresh_symbols:{self.passed_symbol_count}"
                f"<{self.policy.minimum_symbol_count}"
            )
        blockers.extend(
            f"continuous_quote_smoke:{check.symbol}:{blocker}"
            for check in self.checks
            for blocker in check.blockers
        )
        return tuple(dict.fromkeys(blockers))

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def report_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "broker_server": self.broker_server,
                "clock_evidence_id": self.clock_evidence.evidence_id,
                "policy_id": self.policy.policy_id,
                "requested_symbols": list(self.requested_symbols),
                "checks": [item.to_dict() for item in self.checks],
            },
            prefix="mt5-continuous-quote-smoke",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "passed": self.passed,
            "blockers": list(self.blockers),
            "broker_server": self.broker_server,
            "clock_evidence_id": self.clock_evidence.evidence_id,
            "clock_evidence": self.clock_evidence.to_dict(),
            "policy": self.policy.to_dict(),
            "requested_symbols": list(self.requested_symbols),
            "passed_symbol_count": self.passed_symbol_count,
            "checks": [item.to_dict() for item in self.checks],
            "generated_at": self.generated_at.isoformat(),
            "scope": "engineering_smoke_only_not_us_i0_or_us_d3_evidence",
            "stage_exit_authority": False,
            "research_universe_authority": False,
            "execution_authority": False,
        }


def build_mt5_continuous_quote_smoke_report(
    broker_server: str,
    requested_symbols: Sequence[str],
    inventory_rows: Sequence[Mapping[str, object]],
    tick_rows: Mapping[str, Mapping[str, object] | None],
    retrieved_at_by_symbol: Mapping[str, datetime],
    clock_evidence: MT5BrokerClockEvidence,
    *,
    policy: MT5ContinuousQuoteSmokePolicy = DEFAULT_MT5_CONTINUOUS_QUOTE_SMOKE_POLICY,
    generated_at: datetime | None = None,
) -> MT5ContinuousQuoteSmokeReport:
    inventory: dict[str, Mapping[str, object]] = {}
    for row in inventory_rows:
        symbol = _text(row.get("name", row.get("symbol")), "inventory_rows[].symbol")
        inventory[symbol] = row

    checks: list[MT5ContinuousQuoteCheck] = []
    for requested in requested_symbols:
        symbol = requested.strip()
        blockers: list[str] = []
        info = inventory.get(symbol)
        tick = tick_rows.get(symbol)
        retrieved = _aware_utc(retrieved_at_by_symbol[symbol], f"retrieved_at_by_symbol[{symbol}]")
        visible = bool(info.get("visible", False)) if info is not None else False
        trade_mode = _integer(info.get("trade_mode", 0), "inventory.trade_mode") if info is not None else 0
        tradable = trade_mode != 0
        if info is None:
            blockers.append("missing_inventory")
        if policy.require_visible and not visible:
            blockers.append("not_visible")
        if policy.require_tradable and not tradable:
            blockers.append("not_tradable")

        raw_msc: int | None = None
        normalized: datetime | None = None
        bid: float | None = None
        ask: float | None = None
        if tick is None:
            blockers.append("tick_unavailable")
        else:
            raw_msc = _integer(tick.get("time_msc", 0), "tick.time_msc")
            bid = _number(tick.get("bid", 0.0), "tick.bid")
            ask = _number(tick.get("ask", 0.0), "tick.ask")
            if raw_msc <= 0:
                blockers.append("invalid_tick_time")
                raw_msc = None
            if bid <= 0 or ask <= 0 or ask < bid:
                blockers.append("invalid_bid_ask")
            if raw_msc is not None and clock_evidence.passed:
                normalized = clock_evidence.normalize_epoch_msc(raw_msc)
                age = (retrieved - normalized).total_seconds()
                if age > policy.maximum_quote_age_seconds:
                    blockers.append("stale_quote")
                elif age < -policy.maximum_future_quote_skew_seconds:
                    blockers.append("future_quote")
            elif raw_msc is not None:
                blockers.append("broker_clock_unavailable")

        checks.append(
            MT5ContinuousQuoteCheck(
                symbol=symbol,
                raw_broker_time_msc=raw_msc,
                normalized_sampled_at_utc=normalized,
                retrieved_at_utc=retrieved,
                bid=bid,
                ask=ask,
                visible=visible,
                tradable=tradable,
                blockers=tuple(blockers),
            )
        )

    timestamp = generated_at or datetime.now(UTC)
    return MT5ContinuousQuoteSmokeReport(
        broker_server=broker_server,
        clock_evidence=clock_evidence,
        policy=policy,
        requested_symbols=tuple(requested_symbols),
        checks=tuple(checks),
        generated_at=timestamp,
    )

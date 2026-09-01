from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from finagent.domain._validation import (
    require_aware_datetime,
    require_non_empty,
    require_non_negative,
)


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class MT5TerminalCapability:
    package_version: str
    terminal_version: str
    terminal_build: int
    terminal_name: str
    terminal_company: str
    connected: bool
    trade_allowed: bool
    tradeapi_disabled: bool
    broker_server: str = ""
    broker_company: str = ""
    account_currency: str = ""
    mutation_authority: bool = False
    schema_version: str = "finagent.mt5-terminal-capability.v1"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "package_version",
            require_non_empty(self.package_version, "package_version"),
        )
        object.__setattr__(
            self,
            "terminal_version",
            require_non_empty(self.terminal_version, "terminal_version"),
        )
        if self.terminal_build < 0:
            raise ValueError("terminal_build must be >= 0")
        object.__setattr__(self, "terminal_name", self.terminal_name.strip())
        object.__setattr__(self, "terminal_company", self.terminal_company.strip())
        object.__setattr__(self, "broker_server", self.broker_server.strip())
        object.__setattr__(self, "broker_company", self.broker_company.strip())
        object.__setattr__(self, "account_currency", self.account_currency.strip().upper())
        if self.mutation_authority:
            raise ValueError("MT5-P0 cannot carry broker mutation authority")

    @property
    def capability_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="mt5-terminal")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "package_version": self.package_version,
            "terminal_version": self.terminal_version,
            "terminal_build": self.terminal_build,
            "terminal_name": self.terminal_name,
            "terminal_company": self.terminal_company,
            "connected": self.connected,
            "trade_allowed": self.trade_allowed,
            "tradeapi_disabled": self.tradeapi_disabled,
            "broker_server": self.broker_server,
            "broker_company": self.broker_company,
            "account_currency": self.account_currency,
            "mutation_authority": self.mutation_authority,
        }
        if include_id:
            payload["capability_id"] = self.capability_id
        return payload


@dataclass(frozen=True, slots=True)
class MT5SymbolSpec:
    symbol: str
    path: str
    visible: bool
    trade_mode: int
    trade_calc_mode: int
    digits: int
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
    currency_base: str = ""
    currency_profit: str = ""
    currency_margin: str = ""
    schema_version: str = "finagent.mt5-symbol-spec.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", require_non_empty(self.symbol, "symbol"))
        object.__setattr__(self, "path", self.path.strip())
        for name in (
            "trade_mode",
            "trade_calc_mode",
            "digits",
            "swap_mode",
            "filling_mode",
            "order_mode",
        ):
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
            object.__setattr__(self, name, require_non_negative(float(getattr(self, name)), name))
        if self.volume_max and self.volume_min > self.volume_max:
            raise ValueError("volume_min cannot exceed volume_max")
        object.__setattr__(self, "currency_base", self.currency_base.strip().upper())
        object.__setattr__(self, "currency_profit", self.currency_profit.strip().upper())
        object.__setattr__(self, "currency_margin", self.currency_margin.strip().upper())

    @property
    def tradable(self) -> bool:
        # MetaTrader 5 SYMBOL_TRADE_MODE_DISABLED is 0.
        return self.trade_mode != 0

    @property
    def spec_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="mt5-symbol")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "path": self.path,
            "visible": self.visible,
            "tradable": self.tradable,
            "trade_mode": self.trade_mode,
            "trade_calc_mode": self.trade_calc_mode,
            "digits": self.digits,
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
        }
        if include_id:
            payload["spec_id"] = self.spec_id
        return payload


@dataclass(frozen=True, slots=True)
class MT5HistoryCapability:
    symbol: str
    requested_bar_start: datetime
    requested_bar_end: datetime
    m1_bar_count: int
    m1_first_at: datetime | None
    m1_last_at: datetime | None
    requested_tick_start: datetime | None = None
    requested_tick_end: datetime | None = None
    tick_count: int = 0
    tick_first_at: datetime | None = None
    tick_last_at: datetime | None = None
    tick_window_m1_bar_count: int = 0
    tick_window_basis: str = "not_requested"
    schema_version: str = "finagent.mt5-history-capability.v2"

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", require_non_empty(self.symbol, "symbol"))
        start = require_aware_datetime(self.requested_bar_start, "requested_bar_start")
        end = require_aware_datetime(self.requested_bar_end, "requested_bar_end")
        if end <= start:
            raise ValueError("requested_bar_end must be later than requested_bar_start")
        object.__setattr__(self, "requested_bar_start", start)
        object.__setattr__(self, "requested_bar_end", end)
        if self.m1_bar_count < 0 or self.tick_count < 0 or self.tick_window_m1_bar_count < 0:
            raise ValueError("history counts must be >= 0")
        for name in (
            "m1_first_at",
            "m1_last_at",
            "requested_tick_start",
            "requested_tick_end",
            "tick_first_at",
            "tick_last_at",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_aware_datetime(value, name))
        if self.m1_bar_count == 0 and (
            self.m1_first_at is not None or self.m1_last_at is not None
        ):
            raise ValueError("zero M1 bars cannot carry first/last timestamps")
        if self.m1_bar_count > 0 and (self.m1_first_at is None or self.m1_last_at is None):
            raise ValueError("non-zero M1 bars require first/last timestamps")
        if (self.requested_tick_start is None) != (self.requested_tick_end is None):
            raise ValueError("tick request start/end must be both set or both omitted")
        if (
            self.requested_tick_start is not None
            and self.requested_tick_end is not None
            and self.requested_tick_end <= self.requested_tick_start
        ):
            raise ValueError("requested_tick_end must be later than requested_tick_start")
        basis = self.tick_window_basis.strip()
        if basis not in {"not_requested", "explicit", "derived_from_m1_tail"}:
            raise ValueError(f"unsupported tick_window_basis {basis!r}")
        object.__setattr__(self, "tick_window_basis", basis)
        tick_requested = self.requested_tick_start is not None
        if not tick_requested and (
            self.tick_count != 0
            or self.tick_first_at is not None
            or self.tick_last_at is not None
            or self.tick_window_m1_bar_count != 0
            or basis != "not_requested"
        ):
            raise ValueError("tick evidence cannot exist without a requested tick window")
        if tick_requested and basis == "not_requested":
            raise ValueError("requested tick window requires an explicit basis")
        if self.tick_count == 0 and (
            self.tick_first_at is not None or self.tick_last_at is not None
        ):
            raise ValueError("zero ticks cannot carry first/last timestamps")
        if self.tick_count > 0 and (self.tick_first_at is None or self.tick_last_at is None):
            raise ValueError("non-zero ticks require first/last timestamps")

    @property
    def history_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="mt5-history")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "requested_bar_start": self.requested_bar_start.astimezone(UTC).isoformat(),
            "requested_bar_end": self.requested_bar_end.astimezone(UTC).isoformat(),
            "m1_bar_count": self.m1_bar_count,
            "m1_first_at": (
                self.m1_first_at.astimezone(UTC).isoformat() if self.m1_first_at else None
            ),
            "m1_last_at": (
                self.m1_last_at.astimezone(UTC).isoformat() if self.m1_last_at else None
            ),
            "requested_tick_start": (
                self.requested_tick_start.astimezone(UTC).isoformat()
                if self.requested_tick_start
                else None
            ),
            "requested_tick_end": (
                self.requested_tick_end.astimezone(UTC).isoformat()
                if self.requested_tick_end
                else None
            ),
            "tick_window_basis": self.tick_window_basis,
            "tick_window_m1_bar_count": self.tick_window_m1_bar_count,
            "tick_count": self.tick_count,
            "tick_first_at": (
                self.tick_first_at.astimezone(UTC).isoformat() if self.tick_first_at else None
            ),
            "tick_last_at": (
                self.tick_last_at.astimezone(UTC).isoformat() if self.tick_last_at else None
            ),
        }
        if include_id:
            payload["history_id"] = self.history_id
        return payload


@dataclass(frozen=True, slots=True)
class MT5SpreadSample:
    symbol: str
    sampled_at: datetime
    bid: float
    ask: float
    last: float
    point: float
    schema_version: str = "finagent.mt5-spread-sample.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", require_non_empty(self.symbol, "symbol"))
        object.__setattr__(self, "sampled_at", require_aware_datetime(self.sampled_at, "sampled_at"))
        for name in ("bid", "ask", "last", "point"):
            object.__setattr__(self, name, require_non_negative(float(getattr(self, name)), name))
        if self.bid and self.ask and self.ask < self.bid:
            raise ValueError("ask cannot be below bid")

    @property
    def spread_points(self) -> float | None:
        if self.point <= 0 or self.bid <= 0 or self.ask <= 0:
            return None
        return (self.ask - self.bid) / self.point

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "sampled_at": self.sampled_at.astimezone(UTC).isoformat(),
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "point": self.point,
            "spread_points": self.spread_points,
        }


@dataclass(frozen=True, slots=True)
class MT5CapabilityProbeReport:
    terminal: MT5TerminalCapability
    symbols: tuple[MT5SymbolSpec, ...]
    history: tuple[MT5HistoryCapability, ...]
    spread_samples: tuple[MT5SpreadSample, ...]
    probed_at: datetime
    symbol_group: str = ""
    read_only: bool = True
    mutation_authority: bool = False
    schema_version: str = "finagent.mt5-capability-probe-report.v2"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "probed_at",
            require_aware_datetime(self.probed_at, "probed_at"),
        )
        object.__setattr__(self, "symbol_group", self.symbol_group.strip())
        if not self.read_only:
            raise ValueError("MT5-P0 report must be read_only=true")
        if self.mutation_authority:
            raise ValueError("MT5-P0 report cannot carry mutation authority")
        names = tuple(item.symbol for item in self.symbols)
        if len(names) != len(set(names)):
            raise ValueError("MT5 symbol inventory cannot contain duplicate symbols")

    @property
    def visible_symbol_count(self) -> int:
        return sum(item.visible for item in self.symbols)

    @property
    def tradable_symbol_count(self) -> int:
        return sum(item.tradable for item in self.symbols)

    @property
    def probe_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "terminal": self.terminal.to_dict(),
            "symbols": [item.to_dict() for item in self.symbols],
            "history": [item.to_dict() for item in self.history],
            "spread_samples": [item.to_dict() for item in self.spread_samples],
            "symbol_group": self.symbol_group,
            "read_only": self.read_only,
            "mutation_authority": self.mutation_authority,
        }
        return _canonical_hash(payload, prefix="mt5-capability-probe")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "probe_id": self.probe_id,
            "probed_at": self.probed_at.astimezone(UTC).isoformat(),
            "read_only": self.read_only,
            "mutation_authority": self.mutation_authority,
            "symbol_group": self.symbol_group,
            "terminal": self.terminal.to_dict(),
            "symbol_count": len(self.symbols),
            "visible_symbol_count": self.visible_symbol_count,
            "tradable_symbol_count": self.tradable_symbol_count,
            "symbols": [item.to_dict() for item in self.symbols],
            "history": [item.to_dict() for item in self.history],
            "spread_samples": [item.to_dict() for item in self.spread_samples],
        }

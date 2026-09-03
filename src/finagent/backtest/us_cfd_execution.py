from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_FLOOR
from enum import StrEnum

from finagent.brokers.mt5.capabilities import MT5SymbolSpec


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _text(value: str, field_name: str) -> str:
    rendered = value.strip()
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _finite(value: float, field_name: str) -> float:
    rendered = float(value)
    if not math.isfinite(rendered):
        raise ValueError(f"{field_name} must be finite")
    return rendered


def _positive(value: float, field_name: str) -> float:
    rendered = _finite(value, field_name)
    if rendered <= 0:
        raise ValueError(f"{field_name} must be positive")
    return rendered


def _non_negative(value: float, field_name: str) -> float:
    rendered = _finite(value, field_name)
    if rendered < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return rendered


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _round_abs_lots_toward_zero(raw_lots: float, step: float) -> float:
    if raw_lots < 0:
        raise ValueError("raw_lots must be non-negative")
    if step <= 0:
        raise ValueError("step must be positive")
    raw = Decimal(str(raw_lots))
    quantum = Decimal(str(step))
    steps = (raw / quantum).to_integral_value(rounding=ROUND_FLOOR)
    return float(steps * quantum)


class CFDOrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class CFDInstrumentSpec:
    symbol: str
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    margin_rate: float
    tick_size: float
    currency_profit: str = "USD"
    currency_margin: str = "USD"
    source_mt5_spec_id: str | None = None
    schema_version: str = "finagent.us-cfd-instrument-spec.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol"))
        object.__setattr__(self, "contract_size", _positive(self.contract_size, "contract_size"))
        object.__setattr__(self, "volume_min", _positive(self.volume_min, "volume_min"))
        object.__setattr__(self, "volume_max", _positive(self.volume_max, "volume_max"))
        object.__setattr__(self, "volume_step", _positive(self.volume_step, "volume_step"))
        object.__setattr__(self, "margin_rate", _positive(self.margin_rate, "margin_rate"))
        object.__setattr__(self, "tick_size", _positive(self.tick_size, "tick_size"))
        if self.volume_min > self.volume_max:
            raise ValueError("volume_min cannot exceed volume_max")
        if self.margin_rate > 1:
            raise ValueError("margin_rate must be in (0,1]")
        object.__setattr__(self, "currency_profit", _text(self.currency_profit, "currency_profit").upper())
        object.__setattr__(self, "currency_margin", _text(self.currency_margin, "currency_margin").upper())
        if self.source_mt5_spec_id is not None:
            object.__setattr__(
                self,
                "source_mt5_spec_id",
                _text(self.source_mt5_spec_id, "source_mt5_spec_id"),
            )

    @classmethod
    def from_mt5_symbol_spec(
        cls,
        spec: MT5SymbolSpec,
        *,
        margin_rate: float,
    ) -> CFDInstrumentSpec:
        if not spec.tradable:
            raise ValueError("cannot build CFD instrument from disabled MT5 symbol")
        if spec.contract_size <= 0:
            raise ValueError("MT5 symbol contract_size must be positive")
        if spec.volume_min <= 0 or spec.volume_max <= 0 or spec.volume_step <= 0:
            raise ValueError("MT5 symbol volume constraints must be positive")
        if spec.tick_size <= 0:
            raise ValueError("MT5 symbol tick_size must be positive")
        return cls(
            symbol=spec.symbol,
            contract_size=spec.contract_size,
            volume_min=spec.volume_min,
            volume_max=spec.volume_max,
            volume_step=spec.volume_step,
            margin_rate=margin_rate,
            tick_size=spec.tick_size,
            currency_profit=spec.currency_profit or "USD",
            currency_margin=spec.currency_margin or spec.currency_profit or "USD",
            source_mt5_spec_id=spec.spec_id,
        )

    @property
    def instrument_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-cfd-instrument")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "contract_size": self.contract_size,
            "volume_min": self.volume_min,
            "volume_max": self.volume_max,
            "volume_step": self.volume_step,
            "margin_rate": self.margin_rate,
            "tick_size": self.tick_size,
            "currency_profit": self.currency_profit,
            "currency_margin": self.currency_margin,
            "source_mt5_spec_id": self.source_mt5_spec_id,
        }
        if include_id:
            payload["instrument_id"] = self.instrument_id
        return payload


@dataclass(frozen=True, slots=True)
class CFDAccountSpec:
    base_currency: str
    initial_balance: float
    max_margin_utilization: float = 0.50
    schema_version: str = "finagent.us-cfd-account-spec.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_currency", _text(self.base_currency, "base_currency").upper())
        object.__setattr__(self, "initial_balance", _positive(self.initial_balance, "initial_balance"))
        utilization = _positive(self.max_margin_utilization, "max_margin_utilization")
        if utilization > 1:
            raise ValueError("max_margin_utilization must be in (0,1]")
        object.__setattr__(self, "max_margin_utilization", utilization)

    @property
    def account_spec_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-cfd-account")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "base_currency": self.base_currency,
            "initial_balance": self.initial_balance,
            "max_margin_utilization": self.max_margin_utilization,
        }
        if include_id:
            payload["account_spec_id"] = self.account_spec_id
        return payload


@dataclass(frozen=True, slots=True)
class CFDExecutionCostPolicy:
    spread_bps: float
    slippage_bps: float
    commission_bps: float
    schema_version: str = "finagent.us-cfd-execution-cost-policy.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "spread_bps", _non_negative(self.spread_bps, "spread_bps"))
        object.__setattr__(self, "slippage_bps", _non_negative(self.slippage_bps, "slippage_bps"))
        object.__setattr__(self, "commission_bps", _non_negative(self.commission_bps, "commission_bps"))

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-cfd-cost-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "spread_bps": self.spread_bps,
            "spread_semantics": "full_bid_ask_spread_half_applied_per_side",
            "slippage_bps": self.slippage_bps,
            "commission_bps": self.commission_bps,
            "swap_model": "zero_by_intraday_flat_design",
            "broker_execution_authority": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


@dataclass(frozen=True, slots=True)
class CFDReferencePrice:
    symbol: str
    price: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol"))
        object.__setattr__(self, "price", _positive(self.price, "price"))

    def to_dict(self) -> dict[str, object]:
        return {"symbol": self.symbol, "price": self.price}


@dataclass(frozen=True, slots=True)
class CFDTargetWeight:
    symbol: str
    weight: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol"))
        object.__setattr__(self, "weight", _finite(self.weight, "weight"))

    def to_dict(self) -> dict[str, object]:
        return {"symbol": self.symbol, "weight": self.weight}


@dataclass(frozen=True, slots=True)
class CFDHistoricalStep:
    asof: datetime
    prices: tuple[CFDReferencePrice, ...]
    targets: tuple[CFDTargetWeight, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "asof", _aware(self.asof, "asof"))
        price_symbols = tuple(item.symbol for item in self.prices)
        target_symbols = tuple(item.symbol for item in self.targets)
        if not price_symbols:
            raise ValueError("historical step requires at least one price")
        if len(price_symbols) != len(set(price_symbols)):
            raise ValueError("historical step contains duplicate price symbols")
        if len(target_symbols) != len(set(target_symbols)):
            raise ValueError("historical step contains duplicate target symbols")
        if set(target_symbols) != set(price_symbols):
            raise ValueError("historical step targets must cover exactly the priced symbols")

    def price_map(self) -> dict[str, float]:
        return {item.symbol: item.price for item in self.prices}

    def target_map(self) -> dict[str, float]:
        return {item.symbol: item.weight for item in self.targets}

    def to_dict(self) -> dict[str, object]:
        return {
            "asof": self.asof.isoformat(),
            "prices": [item.to_dict() for item in self.prices],
            "targets": [item.to_dict() for item in self.targets],
        }


@dataclass(frozen=True, slots=True)
class CFDPosition:
    symbol: str
    lots: float
    average_price: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol"))
        lots = _finite(self.lots, "lots")
        if abs(lots) <= 1e-12:
            raise ValueError("position lots cannot be zero")
        object.__setattr__(self, "lots", lots)
        object.__setattr__(self, "average_price", _positive(self.average_price, "average_price"))

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "lots": self.lots,
            "average_price": self.average_price,
        }


@dataclass(frozen=True, slots=True)
class CFDAccountState:
    asof: datetime
    balance: float
    equity: float
    margin_used: float
    positions: tuple[CFDPosition, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "asof", _aware(self.asof, "asof"))
        object.__setattr__(self, "balance", _finite(self.balance, "balance"))
        object.__setattr__(self, "equity", _finite(self.equity, "equity"))
        object.__setattr__(self, "margin_used", _non_negative(self.margin_used, "margin_used"))
        symbols = tuple(item.symbol for item in self.positions)
        if len(symbols) != len(set(symbols)):
            raise ValueError("account state contains duplicate positions")

    @property
    def margin_utilization(self) -> float:
        if self.equity <= 0:
            return math.inf if self.margin_used > 0 else 0.0
        return self.margin_used / self.equity

    def position_map(self) -> dict[str, CFDPosition]:
        return {item.symbol: item for item in self.positions}

    def to_dict(self) -> dict[str, object]:
        return {
            "asof": self.asof.isoformat(),
            "balance": self.balance,
            "equity": self.equity,
            "margin_used": self.margin_used,
            "margin_utilization": self.margin_utilization,
            "positions": [item.to_dict() for item in self.positions],
        }


@dataclass(frozen=True, slots=True)
class CFDCompiledTarget:
    symbol: str
    weight: float
    raw_target_lots: float
    target_lots: float
    current_lots: float
    delta_lots: float
    below_minimum: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "weight": self.weight,
            "raw_target_lots": self.raw_target_lots,
            "target_lots": self.target_lots,
            "current_lots": self.current_lots,
            "delta_lots": self.delta_lots,
            "below_minimum": self.below_minimum,
        }


@dataclass(frozen=True, slots=True)
class CFDOrderIntent:
    order_id: str
    symbol: str
    side: CFDOrderSide
    lots: float
    reference_price: float
    created_at: datetime
    target_lots: float
    current_lots: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "order_id", _text(self.order_id, "order_id"))
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol"))
        object.__setattr__(self, "lots", _positive(self.lots, "lots"))
        object.__setattr__(self, "reference_price", _positive(self.reference_price, "reference_price"))
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        object.__setattr__(self, "target_lots", _finite(self.target_lots, "target_lots"))
        object.__setattr__(self, "current_lots", _finite(self.current_lots, "current_lots"))

    def to_dict(self) -> dict[str, object]:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "lots": self.lots,
            "reference_price": self.reference_price,
            "created_at": self.created_at.isoformat(),
            "target_lots": self.target_lots,
            "current_lots": self.current_lots,
        }


@dataclass(frozen=True, slots=True)
class CFDHistoricalFill:
    fill_id: str
    order_id: str
    symbol: str
    side: CFDOrderSide
    lots: float
    reference_price: float
    fill_price: float
    executed_at: datetime
    spread_cost: float
    slippage_cost: float
    commission: float
    realized_pnl: float

    def __post_init__(self) -> None:
        for field_name in ("fill_id", "order_id", "symbol"):
            object.__setattr__(self, field_name, _text(str(getattr(self, field_name)), field_name))
        object.__setattr__(self, "lots", _positive(self.lots, "lots"))
        object.__setattr__(self, "reference_price", _positive(self.reference_price, "reference_price"))
        object.__setattr__(self, "fill_price", _positive(self.fill_price, "fill_price"))
        object.__setattr__(self, "executed_at", _aware(self.executed_at, "executed_at"))
        for field_name in ("spread_cost", "slippage_cost", "commission"):
            object.__setattr__(
                self,
                field_name,
                _non_negative(float(getattr(self, field_name)), field_name),
            )
        object.__setattr__(self, "realized_pnl", _finite(self.realized_pnl, "realized_pnl"))

    @property
    def transaction_cost(self) -> float:
        return self.spread_cost + self.slippage_cost + self.commission

    def to_dict(self) -> dict[str, object]:
        return {
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "lots": self.lots,
            "reference_price": self.reference_price,
            "fill_price": self.fill_price,
            "executed_at": self.executed_at.isoformat(),
            "spread_cost": self.spread_cost,
            "slippage_cost": self.slippage_cost,
            "commission": self.commission,
            "realized_pnl": self.realized_pnl,
            "transaction_cost": self.transaction_cost,
        }


@dataclass(frozen=True, slots=True)
class CFDHistoricalStepResult:
    asof: datetime
    compiled_targets: tuple[CFDCompiledTarget, ...]
    orders: tuple[CFDOrderIntent, ...]
    fills: tuple[CFDHistoricalFill, ...]
    pre_state: CFDAccountState
    post_state: CFDAccountState
    blockers: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def transaction_cost(self) -> float:
        return sum(item.transaction_cost for item in self.fills)

    def to_dict(self) -> dict[str, object]:
        return {
            "asof": self.asof.isoformat(),
            "passed": self.passed,
            "compiled_targets": [item.to_dict() for item in self.compiled_targets],
            "orders": [item.to_dict() for item in self.orders],
            "fills": [item.to_dict() for item in self.fills],
            "pre_state": self.pre_state.to_dict(),
            "post_state": self.post_state.to_dict(),
            "blockers": list(self.blockers),
            "transaction_cost": self.transaction_cost,
        }


@dataclass(frozen=True, slots=True)
class CFDHistoricalExecutionReport:
    account_spec: CFDAccountSpec
    cost_policy: CFDExecutionCostPolicy
    instruments: tuple[CFDInstrumentSpec, ...]
    steps: tuple[CFDHistoricalStepResult, ...]
    final_state: CFDAccountState
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-cfd-historical-execution-report.v1"

    @property
    def passed(self) -> bool:
        return not self.blockers and all(item.passed for item in self.steps)

    @property
    def total_transaction_cost(self) -> float:
        return sum(item.transaction_cost for item in self.steps)

    @property
    def net_pnl(self) -> float:
        return self.final_state.equity - self.account_spec.initial_balance

    @property
    def gross_pnl_before_costs(self) -> float:
        return self.net_pnl + self.total_transaction_cost

    @property
    def report_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-cfd-historical-execution")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "account_spec": self.account_spec.to_dict(),
            "cost_policy": self.cost_policy.to_dict(),
            "instruments": [item.to_dict() for item in self.instruments],
            "steps": [item.to_dict() for item in self.steps],
            "final_state": self.final_state.to_dict(),
            "passed": self.passed,
            "blockers": list(self.blockers),
            "total_transaction_cost": self.total_transaction_cost,
            "net_pnl": self.net_pnl,
            "gross_pnl_before_costs": self.gross_pnl_before_costs,
            "intraday_flat": not self.final_state.positions,
            "scope": "historical_deterministic_execution_implementation",
            "real_alpha_evidence_required_for_us_x_progression": True,
            "broker_execution_authority": False,
            "paper_authority": False,
            "status_authority": False,
            "stage_exit_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


def compile_cfd_target(
    instrument: CFDInstrumentSpec,
    *,
    weight: float,
    equity: float,
    reference_price: float,
    current_lots: float,
) -> CFDCompiledTarget:
    equity_value = _positive(equity, "equity")
    price = _positive(reference_price, "reference_price")
    weight_value = _finite(weight, "weight")
    current = _finite(current_lots, "current_lots")
    raw_abs = abs(weight_value) * equity_value / (price * instrument.contract_size)
    below_minimum = 0 < raw_abs < instrument.volume_min
    rounded_abs = _round_abs_lots_toward_zero(raw_abs, instrument.volume_step)
    if below_minimum or rounded_abs < instrument.volume_min:
        target = 0.0
    else:
        if rounded_abs > instrument.volume_max + 1e-12:
            raise ValueError(f"target for {instrument.symbol} exceeds volume_max")
        target = rounded_abs if weight_value >= 0 else -rounded_abs
    delta = target - current
    return CFDCompiledTarget(
        symbol=instrument.symbol,
        weight=weight_value,
        raw_target_lots=raw_abs if weight_value >= 0 else -raw_abs,
        target_lots=target,
        current_lots=current,
        delta_lots=delta,
        below_minimum=below_minimum,
    )


def _position_state(
    *,
    asof: datetime,
    balance: float,
    positions: dict[str, CFDPosition],
    prices: dict[str, float],
    instruments: dict[str, CFDInstrumentSpec],
) -> CFDAccountState:
    unrealized = 0.0
    margin = 0.0
    ordered: list[CFDPosition] = []
    for symbol in sorted(positions):
        position = positions[symbol]
        price = prices[symbol]
        instrument = instruments[symbol]
        unrealized += (
            position.lots
            * instrument.contract_size
            * (price - position.average_price)
        )
        margin += abs(position.lots) * instrument.contract_size * price * instrument.margin_rate
        ordered.append(position)
    equity = balance + unrealized
    return CFDAccountState(
        asof=asof,
        balance=balance,
        equity=equity,
        margin_used=margin,
        positions=tuple(ordered),
    )


def _estimated_cost(
    order_lots: float,
    instrument: CFDInstrumentSpec,
    reference_price: float,
    policy: CFDExecutionCostPolicy,
) -> float:
    notional = abs(order_lots) * instrument.contract_size * reference_price
    return notional * (
        policy.spread_bps / 2.0 + policy.slippage_bps + policy.commission_bps
    ) / 10_000.0


def _order_for_target(
    compiled: CFDCompiledTarget,
    *,
    reference_price: float,
    asof: datetime,
) -> CFDOrderIntent | None:
    if abs(compiled.delta_lots) <= 1e-12:
        return None
    side = CFDOrderSide.BUY if compiled.delta_lots > 0 else CFDOrderSide.SELL
    payload = {
        "symbol": compiled.symbol,
        "side": side.value,
        "lots": abs(compiled.delta_lots),
        "reference_price": reference_price,
        "created_at": asof.isoformat(),
        "target_lots": compiled.target_lots,
        "current_lots": compiled.current_lots,
    }
    return CFDOrderIntent(
        order_id=_canonical_hash(payload, prefix="us-cfd-order"),
        symbol=compiled.symbol,
        side=side,
        lots=abs(compiled.delta_lots),
        reference_price=reference_price,
        created_at=asof,
        target_lots=compiled.target_lots,
        current_lots=compiled.current_lots,
    )


def _apply_fill_to_position(
    current: CFDPosition | None,
    *,
    signed_fill_lots: float,
    fill_price: float,
    instrument: CFDInstrumentSpec,
) -> tuple[CFDPosition | None, float]:
    if abs(signed_fill_lots) <= 1e-12:
        raise ValueError("signed_fill_lots cannot be zero")
    if current is None:
        return (
            CFDPosition(
                symbol=instrument.symbol,
                lots=signed_fill_lots,
                average_price=fill_price,
            ),
            0.0,
        )

    old_lots = current.lots
    if old_lots * signed_fill_lots > 0:
        new_lots = old_lots + signed_fill_lots
        average = (
            abs(old_lots) * current.average_price
            + abs(signed_fill_lots) * fill_price
        ) / abs(new_lots)
        return CFDPosition(instrument.symbol, new_lots, average), 0.0

    close_lots = min(abs(old_lots), abs(signed_fill_lots))
    old_sign = 1.0 if old_lots > 0 else -1.0
    realized = (
        close_lots
        * instrument.contract_size
        * (fill_price - current.average_price)
        * old_sign
    )
    new_lots = old_lots + signed_fill_lots
    if abs(new_lots) <= 1e-12:
        return None, realized
    if old_lots * new_lots > 0:
        return CFDPosition(instrument.symbol, new_lots, current.average_price), realized
    return CFDPosition(instrument.symbol, new_lots, fill_price), realized


def _execute_order(
    order: CFDOrderIntent,
    *,
    instrument: CFDInstrumentSpec,
    policy: CFDExecutionCostPolicy,
    current: CFDPosition | None,
) -> tuple[CFDHistoricalFill, CFDPosition | None, float]:
    sign = 1.0 if order.side is CFDOrderSide.BUY else -1.0
    half_spread_rate = policy.spread_bps / 2.0 / 10_000.0
    slippage_rate = policy.slippage_bps / 10_000.0
    fill_price = order.reference_price * (1.0 + sign * (half_spread_rate + slippage_rate))
    notional = order.lots * instrument.contract_size * order.reference_price
    spread_cost = notional * policy.spread_bps / 2.0 / 10_000.0
    slippage_cost = notional * policy.slippage_bps / 10_000.0
    commission = notional * policy.commission_bps / 10_000.0
    new_position, realized = _apply_fill_to_position(
        current,
        signed_fill_lots=sign * order.lots,
        fill_price=fill_price,
        instrument=instrument,
    )
    payload = {
        "order_id": order.order_id,
        "symbol": order.symbol,
        "side": order.side.value,
        "lots": order.lots,
        "reference_price": order.reference_price,
        "fill_price": fill_price,
        "executed_at": order.created_at.isoformat(),
        "spread_cost": spread_cost,
        "slippage_cost": slippage_cost,
        "commission": commission,
        "realized_pnl": realized,
    }
    fill = CFDHistoricalFill(
        fill_id=_canonical_hash(payload, prefix="us-cfd-fill"),
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        lots=order.lots,
        reference_price=order.reference_price,
        fill_price=fill_price,
        executed_at=order.created_at,
        spread_cost=spread_cost,
        slippage_cost=slippage_cost,
        commission=commission,
        realized_pnl=realized,
    )
    balance_delta = realized - commission
    return fill, new_position, balance_delta


def run_cfd_historical_execution(
    *,
    account_spec: CFDAccountSpec,
    instruments: tuple[CFDInstrumentSpec, ...],
    cost_policy: CFDExecutionCostPolicy,
    steps: tuple[CFDHistoricalStep, ...],
) -> CFDHistoricalExecutionReport:
    if not instruments:
        raise ValueError("at least one CFD instrument is required")
    if not steps:
        raise ValueError("at least one historical step is required")
    instrument_map = {item.symbol: item for item in instruments}
    if len(instrument_map) != len(instruments):
        raise ValueError("duplicate CFD instrument symbols")
    for instrument in instruments:
        if instrument.currency_profit != account_spec.base_currency:
            raise ValueError("CFD v1 does not infer profit-currency conversion")
        if instrument.currency_margin != account_spec.base_currency:
            raise ValueError("CFD v1 does not infer margin-currency conversion")
    previous_asof: datetime | None = None
    for step in steps:
        if previous_asof is not None and step.asof <= previous_asof:
            raise ValueError("historical steps must be strictly ordered")
        if set(step.price_map()) != set(instrument_map):
            raise ValueError("every historical step must cover exactly the instrument set")
        previous_asof = step.asof

    first_prices = steps[0].price_map()
    balance = account_spec.initial_balance
    positions: dict[str, CFDPosition] = {}
    state = _position_state(
        asof=steps[0].asof,
        balance=balance,
        positions=positions,
        prices=first_prices,
        instruments=instrument_map,
    )
    step_results: list[CFDHistoricalStepResult] = []
    run_blockers: list[str] = []

    for step_index, step in enumerate(steps):
        prices = step.price_map()
        targets = step.target_map()
        pre_state = _position_state(
            asof=step.asof,
            balance=balance,
            positions=positions,
            prices=prices,
            instruments=instrument_map,
        )
        current_map = pre_state.position_map()
        compiled: list[CFDCompiledTarget] = []
        orders: list[CFDOrderIntent] = []
        for symbol in sorted(instrument_map):
            current_lots = current_map[symbol].lots if symbol in current_map else 0.0
            target = compile_cfd_target(
                instrument_map[symbol],
                weight=targets[symbol],
                equity=pre_state.equity,
                reference_price=prices[symbol],
                current_lots=current_lots,
            )
            compiled.append(target)
            order = _order_for_target(
                target,
                reference_price=prices[symbol],
                asof=step.asof,
            )
            if order is not None:
                orders.append(order)

        projected_margin = sum(
            abs(item.target_lots)
            * instrument_map[item.symbol].contract_size
            * prices[item.symbol]
            * instrument_map[item.symbol].margin_rate
            for item in compiled
        )
        estimated_cost = sum(
            _estimated_cost(
                order.lots,
                instrument_map[order.symbol],
                order.reference_price,
                cost_policy,
            )
            for order in orders
        )
        projected_equity = pre_state.equity - estimated_cost
        blockers: list[str] = []
        if projected_equity <= 0:
            blockers.append("margin:projected_equity_non_positive_after_costs")
        elif projected_margin > projected_equity * account_spec.max_margin_utilization + 1e-9:
            blockers.append("margin:projected_utilization_exceeds_limit")

        fills: list[CFDHistoricalFill] = []
        if not blockers:
            for order in orders:
                current = positions.get(order.symbol)
                fill, new_position, balance_delta = _execute_order(
                    order,
                    instrument=instrument_map[order.symbol],
                    policy=cost_policy,
                    current=current,
                )
                balance += balance_delta
                if new_position is None:
                    positions.pop(order.symbol, None)
                else:
                    positions[order.symbol] = new_position
                fills.append(fill)

        post_state = _position_state(
            asof=step.asof,
            balance=balance,
            positions=positions,
            prices=prices,
            instruments=instrument_map,
        )
        if not blockers and (
            post_state.margin_utilization > account_spec.max_margin_utilization + 1e-9
        ):
            raise RuntimeError("post-trade margin invariant violated after passing projected gate")
        result = CFDHistoricalStepResult(
            asof=step.asof,
            compiled_targets=tuple(compiled),
            orders=tuple(orders),
            fills=tuple(fills),
            pre_state=pre_state,
            post_state=post_state,
            blockers=tuple(blockers),
        )
        step_results.append(result)
        run_blockers.extend(f"step_{step_index}:{item}" for item in blockers)
        state = post_state

    if state.positions:
        run_blockers.append("intraday_flat:open_positions_at_end")
    if state.equity <= 0:
        run_blockers.append("account:non_positive_final_equity")
    return CFDHistoricalExecutionReport(
        account_spec=account_spec,
        cost_policy=cost_policy,
        instruments=instruments,
        steps=tuple(step_results),
        final_state=state,
        blockers=tuple(run_blockers),
    )

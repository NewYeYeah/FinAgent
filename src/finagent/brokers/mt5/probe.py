from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from .capabilities import (
    MT5CapabilityProbeReport,
    MT5HistoryCapability,
    MT5SpreadSample,
    MT5SymbolSpec,
    MT5TerminalCapability,
)
from .client import MT5ReadOnlyClientProtocol


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    asdict = getattr(value, "_asdict", None)
    if callable(asdict):
        mapped = asdict()
        if isinstance(mapped, Mapping):
            return mapped
    raise TypeError(f"MT5 response must be mapping/namedtuple-like, got {type(value)!r}")


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    if hasattr(value, name):
        return getattr(value, name)
    try:
        return value[name]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        return default


def _rows(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray, Mapping)) or not isinstance(value, Iterable):
        raise TypeError("MT5 row collection must be an iterable of rows")
    return tuple(value)


def _scalar_item(value: object) -> object:
    item = getattr(value, "item", None)
    if callable(item):
        return item()
    return value


def _integer(value: object, default: int = 0) -> int:
    if value is None:
        return default
    scalar = _scalar_item(value)
    if isinstance(scalar, (bool, int, float, str, bytes, bytearray)):
        return int(scalar)
    raise TypeError(f"MT5 integer field has unsupported type {type(value)!r}")


def _number(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    scalar = _scalar_item(value)
    if isinstance(scalar, (bool, int, float, str, bytes, bytearray)):
        return float(scalar)
    raise TypeError(f"MT5 numeric field has unsupported type {type(value)!r}")


def _text(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(_scalar_item(value))


def _unix_timestamp(value: object) -> datetime:
    return datetime.fromtimestamp(_integer(value), tz=UTC)


def _tick_timestamp(row: object) -> datetime:
    time_msc = _field(row, "time_msc")
    if time_msc is not None:
        return datetime.fromtimestamp(_integer(time_msc) / 1000.0, tz=UTC)
    time_value = _field(row, "time")
    if time_value is None:
        raise ValueError("MT5 tick row has no time/time_msc")
    return _unix_timestamp(time_value)


def _terminal_capability(
    client: MT5ReadOnlyClientProtocol,
    terminal_raw: object,
    account_raw: object,
) -> MT5TerminalCapability:
    terminal = _mapping(terminal_raw)
    account = _mapping(account_raw)
    version_raw = client.version()
    if isinstance(version_raw, (tuple, list)):
        terminal_version = "/".join(str(item) for item in version_raw)
    else:
        terminal_version = str(version_raw)
    build = _integer(terminal.get("build"))
    if build == 0 and isinstance(version_raw, (tuple, list)) and len(version_raw) > 1:
        build = _integer(version_raw[1])
    return MT5TerminalCapability(
        package_version=client.package_version,
        terminal_version=terminal_version,
        terminal_build=build,
        terminal_name=_text(terminal.get("name")),
        terminal_company=_text(terminal.get("company")),
        connected=bool(terminal.get("connected", False)),
        trade_allowed=bool(terminal.get("trade_allowed", False)),
        tradeapi_disabled=bool(terminal.get("tradeapi_disabled", False)),
        broker_server=_text(account.get("server")),
        broker_company=_text(account.get("company")),
        account_currency=_text(account.get("currency")),
    )


def _symbol_spec(raw: object) -> MT5SymbolSpec:
    value = _mapping(raw)
    return MT5SymbolSpec(
        symbol=_text(value.get("name")),
        path=_text(value.get("path")),
        visible=bool(value.get("visible", False)),
        trade_mode=_integer(value.get("trade_mode")),
        trade_calc_mode=_integer(value.get("trade_calc_mode")),
        digits=_integer(value.get("digits")),
        point=_number(value.get("point")),
        tick_size=_number(value.get("trade_tick_size")),
        tick_value=_number(value.get("trade_tick_value")),
        contract_size=_number(value.get("trade_contract_size")),
        volume_min=_number(value.get("volume_min")),
        volume_max=_number(value.get("volume_max")),
        volume_step=_number(value.get("volume_step")),
        margin_initial=_number(value.get("margin_initial")),
        margin_maintenance=_number(value.get("margin_maintenance")),
        swap_mode=_integer(value.get("swap_mode")),
        swap_long=_number(value.get("swap_long")),
        swap_short=_number(value.get("swap_short")),
        filling_mode=_integer(value.get("filling_mode")),
        order_mode=_integer(value.get("order_mode")),
        currency_base=_text(value.get("currency_base")),
        currency_profit=_text(value.get("currency_profit")),
        currency_margin=_text(value.get("currency_margin")),
    )


def _history_capability(
    client: MT5ReadOnlyClientProtocol,
    symbol: str,
    *,
    bar_start: datetime,
    bar_end: datetime,
    tick_requested: bool,
    tick_start: datetime | None,
    tick_end: datetime | None,
    auto_tick_window_minutes: int | None,
) -> MT5HistoryCapability:
    rates = _rows(client.copy_rates_range(symbol, bar_start, bar_end))
    rate_times = tuple(_unix_timestamp(_field(row, "time")) for row in rates)
    m1_first = rate_times[0] if rate_times else None
    m1_last = rate_times[-1] if rate_times else None

    actual_tick_start: datetime | None = None
    actual_tick_end: datetime | None = None
    tick_window_basis = "not_requested"
    if tick_requested and tick_start is not None and tick_end is not None:
        actual_tick_start = tick_start
        actual_tick_end = tick_end
        tick_window_basis = "explicit"
    elif tick_requested and auto_tick_window_minutes is not None and rate_times:
        actual_tick_end = rate_times[-1] + timedelta(minutes=1)
        actual_tick_start = actual_tick_end - timedelta(minutes=auto_tick_window_minutes)
        tick_window_basis = "derived_from_m1_tail"

    tick_window_m1_bar_count = 0
    ticks: tuple[object, ...] = ()
    if actual_tick_start is not None and actual_tick_end is not None:
        tick_window_m1_bar_count = sum(
            actual_tick_start <= item < actual_tick_end for item in rate_times
        )
        ticks = _rows(client.copy_ticks_range(symbol, actual_tick_start, actual_tick_end))
    tick_first = _tick_timestamp(ticks[0]) if ticks else None
    tick_last = _tick_timestamp(ticks[-1]) if ticks else None
    return MT5HistoryCapability(
        symbol=symbol,
        requested_bar_start=bar_start,
        requested_bar_end=bar_end,
        m1_bar_count=len(rates),
        m1_first_at=m1_first,
        m1_last_at=m1_last,
        requested_tick_start=actual_tick_start,
        requested_tick_end=actual_tick_end,
        tick_count=len(ticks),
        tick_first_at=tick_first,
        tick_last_at=tick_last,
        tick_window_m1_bar_count=tick_window_m1_bar_count,
        tick_window_basis=tick_window_basis,
    )


def _spread_sample(
    client: MT5ReadOnlyClientProtocol,
    symbol: str,
    *,
    point: float,
    fallback_at: datetime,
) -> MT5SpreadSample:
    tick = client.symbol_info_tick(symbol)
    timestamp = fallback_at
    if _field(tick, "time_msc") is not None or _field(tick, "time") is not None:
        timestamp = _tick_timestamp(tick)
    return MT5SpreadSample(
        symbol=symbol,
        sampled_at=timestamp,
        bid=_number(_field(tick, "bid")),
        ask=_number(_field(tick, "ask")),
        last=_number(_field(tick, "last")),
        point=point,
    )


def probe_mt5_capabilities(
    client: MT5ReadOnlyClientProtocol,
    *,
    symbol_group: str = "",
    history_symbols: tuple[str, ...] = (),
    tick_history_symbols: tuple[str, ...] = (),
    bar_start: datetime | None = None,
    bar_end: datetime | None = None,
    tick_start: datetime | None = None,
    tick_end: datetime | None = None,
    auto_tick_window_minutes: int | None = None,
    spread_symbols: tuple[str, ...] = (),
    probed_at: datetime | None = None,
) -> MT5CapabilityProbeReport:
    observed_at = probed_at or datetime.now(UTC)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("probed_at must be timezone-aware")
    normalized_history = tuple(
        dict.fromkeys(item.strip() for item in history_symbols if item.strip())
    )
    normalized_tick_history = tuple(
        dict.fromkeys(item.strip() for item in tick_history_symbols if item.strip())
    )
    normalized_spread = tuple(
        dict.fromkeys(item.strip() for item in spread_symbols if item.strip())
    )
    if normalized_history and (bar_start is None or bar_end is None):
        raise ValueError("history_symbols require bar_start and bar_end")
    if (tick_start is None) != (tick_end is None):
        raise ValueError("tick_start and tick_end must be both set or both omitted")
    if tick_start is not None and auto_tick_window_minutes is not None:
        raise ValueError("explicit tick window and auto_tick_window_minutes are mutually exclusive")
    if auto_tick_window_minutes is not None and auto_tick_window_minutes < 1:
        raise ValueError("auto_tick_window_minutes must be >= 1")
    if (tick_start is not None or auto_tick_window_minutes is not None) and not normalized_history:
        raise ValueError("tick history window requires at least one history symbol")
    if not normalized_tick_history and tick_start is not None:
        normalized_tick_history = normalized_history
    if normalized_tick_history and not set(normalized_tick_history).issubset(normalized_history):
        raise ValueError("tick_history_symbols must be a subset of history_symbols")
    if normalized_tick_history and tick_start is None and auto_tick_window_minutes is None:
        raise ValueError("tick_history_symbols require explicit or automatic tick window")

    terminal = _terminal_capability(client, client.terminal_info(), client.account_info())
    symbols = tuple(
        sorted(
            (_symbol_spec(item) for item in _rows(client.symbols_get(symbol_group))),
            key=lambda item: item.symbol,
        )
    )
    point_by_symbol = {item.symbol: item.point for item in symbols}

    history: list[MT5HistoryCapability] = []
    if normalized_history:
        assert bar_start is not None and bar_end is not None
        tick_targets = set(normalized_tick_history)
        for symbol in normalized_history:
            history.append(
                _history_capability(
                    client,
                    symbol,
                    bar_start=bar_start,
                    bar_end=bar_end,
                    tick_requested=symbol in tick_targets,
                    tick_start=tick_start,
                    tick_end=tick_end,
                    auto_tick_window_minutes=auto_tick_window_minutes,
                )
            )

    samples: list[MT5SpreadSample] = []
    for symbol in normalized_spread or normalized_history:
        samples.append(
            _spread_sample(
                client,
                symbol,
                point=point_by_symbol.get(symbol, 0.0),
                fallback_at=observed_at,
            )
        )

    return MT5CapabilityProbeReport(
        terminal=terminal,
        symbols=symbols,
        history=tuple(history),
        spread_samples=tuple(samples),
        probed_at=observed_at,
        symbol_group=symbol_group,
    )


def run_mt5_readonly_probe(
    client: MT5ReadOnlyClientProtocol,
    **kwargs: Any,
) -> MT5CapabilityProbeReport:
    client.initialize()
    try:
        return probe_mt5_capabilities(client, **kwargs)
    finally:
        client.shutdown()

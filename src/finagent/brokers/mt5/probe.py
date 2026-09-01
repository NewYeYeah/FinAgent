from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
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
    if isinstance(value, (str, bytes, bytearray, Mapping)):
        raise TypeError("MT5 row collection must be iterable rows, not scalar/mapping")
    try:
        return tuple(iter(value))  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError(f"MT5 row collection is not iterable: {type(value)!r}") from exc


def _integer(value: object, default: int = 0) -> int:
    if value is None:
        return default
    return int(value)


def _number(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    return float(value)


def _text(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _unix_timestamp(value: object) -> datetime:
    return datetime.fromtimestamp(int(value), tz=UTC)


def _tick_timestamp(row: object) -> datetime:
    time_msc = _field(row, "time_msc")
    if time_msc is not None:
        return datetime.fromtimestamp(int(time_msc) / 1000.0, tz=UTC)
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
    tick_start: datetime | None,
    tick_end: datetime | None,
) -> MT5HistoryCapability:
    rates = _rows(client.copy_rates_range(symbol, bar_start, bar_end))
    m1_first = _unix_timestamp(_field(rates[0], "time")) if rates else None
    m1_last = _unix_timestamp(_field(rates[-1], "time")) if rates else None

    ticks: tuple[object, ...] = ()
    if tick_start is not None and tick_end is not None:
        ticks = _rows(client.copy_ticks_range(symbol, tick_start, tick_end))
    tick_first = _tick_timestamp(ticks[0]) if ticks else None
    tick_last = _tick_timestamp(ticks[-1]) if ticks else None
    return MT5HistoryCapability(
        symbol=symbol,
        requested_bar_start=bar_start,
        requested_bar_end=bar_end,
        m1_bar_count=len(rates),
        m1_first_at=m1_first,
        m1_last_at=m1_last,
        requested_tick_start=tick_start,
        requested_tick_end=tick_end,
        tick_count=len(ticks),
        tick_first_at=tick_first,
        tick_last_at=tick_last,
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
    bar_start: datetime | None = None,
    bar_end: datetime | None = None,
    tick_start: datetime | None = None,
    tick_end: datetime | None = None,
    spread_symbols: tuple[str, ...] = (),
    probed_at: datetime | None = None,
) -> MT5CapabilityProbeReport:
    observed_at = probed_at or datetime.now(UTC)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("probed_at must be timezone-aware")
    normalized_history = tuple(dict.fromkeys(item.strip() for item in history_symbols if item.strip()))
    normalized_spread = tuple(dict.fromkeys(item.strip() for item in spread_symbols if item.strip()))
    if normalized_history and (bar_start is None or bar_end is None):
        raise ValueError("history_symbols require bar_start and bar_end")
    if (tick_start is None) != (tick_end is None):
        raise ValueError("tick_start and tick_end must be both set or both omitted")
    if (tick_start is not None or tick_end is not None) and not normalized_history:
        raise ValueError("tick history window requires at least one history symbol")

    terminal = _terminal_capability(client, client.terminal_info(), client.account_info())
    symbols = tuple(sorted((_symbol_spec(item) for item in _rows(client.symbols_get(symbol_group))), key=lambda item: item.symbol))
    point_by_symbol = {item.symbol: item.point for item in symbols}

    history: list[MT5HistoryCapability] = []
    if normalized_history:
        assert bar_start is not None and bar_end is not None
        for symbol in normalized_history:
            history.append(
                _history_capability(
                    client,
                    symbol,
                    bar_start=bar_start,
                    bar_end=bar_end,
                    tick_start=tick_start,
                    tick_end=tick_end,
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

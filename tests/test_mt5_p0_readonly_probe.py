from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from finagent.brokers.mt5 import (
    MetaTrader5ReadOnlyClient,
    MT5ReadOnlyClientProtocol,
    probe_mt5_capabilities,
    run_mt5_readonly_probe,
)


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class FakeReadOnlyClient:
    package_version = "5.0.6147"
    timeframe_m1 = 1
    copy_ticks_all = 0

    def __init__(self) -> None:
        self.initialized = False
        self.shutdown_called = False

    def initialize(self) -> None:
        self.initialized = True

    def shutdown(self) -> None:
        self.shutdown_called = True
        self.initialized = False

    def version(self) -> object:
        return (500, 6147, "27 Aug 2026")

    def terminal_info(self) -> object:
        return {
            "build": 6147,
            "name": "MetaTrader 5",
            "company": "MetaQuotes Ltd.",
            "connected": True,
            "trade_allowed": True,
            "tradeapi_disabled": False,
            "path": "C:/sensitive/path/not-persisted",
        }

    def account_info(self) -> object:
        return {
            "login": 123456789,
            "server": "Broker-Demo",
            "company": "Example Broker",
            "currency": "USD",
        }

    def symbols_get(self, group: str = "") -> object:
        del group
        common = {
            "path": "Stocks\\US",
            "visible": True,
            "trade_mode": 4,
            "trade_calc_mode": 32,
            "digits": 2,
            "point": 0.01,
            "trade_tick_size": 0.01,
            "trade_tick_value": 1.0,
            "trade_contract_size": 1.0,
            "volume_min": 1.0,
            "volume_max": 1000.0,
            "volume_step": 1.0,
            "margin_initial": 0.0,
            "margin_maintenance": 0.0,
            "swap_mode": 0,
            "swap_long": 0.0,
            "swap_short": 0.0,
            "filling_mode": 1,
            "order_mode": 127,
            "currency_base": "USD",
            "currency_profit": "USD",
            "currency_margin": "USD",
        }
        return ({**common, "name": "AAPL"}, {**common, "name": "MSFT"})

    def symbol_info_tick(self, symbol: str) -> object:
        assert symbol in {"AAPL", "MSFT"}
        return {
            "time_msc": 1_772_980_200_000,
            "bid": 100.0,
            "ask": 100.05,
            "last": 100.02,
        }

    def copy_rates_range(self, symbol: str, date_from: object, date_to: object) -> object:
        assert symbol in {"AAPL", "MSFT"}
        assert date_from is not None and date_to is not None
        return (
            {"time": 1_772_980_200},
            {"time": 1_772_980_260},
            {"time": 1_772_980_320},
        )

    def copy_ticks_range(self, symbol: str, date_from: object, date_to: object) -> object:
        assert symbol in {"AAPL", "MSFT"}
        assert date_from is not None and date_to is not None
        return (
            {"time_msc": 1_772_980_200_100},
            {"time_msc": 1_772_980_200_900},
        )


def test_protocol_surface_is_read_only_by_construction() -> None:
    assert isinstance(FakeReadOnlyClient(), MT5ReadOnlyClientProtocol)
    for forbidden in (
        "order_send",
        "order_check",
        "symbol_select",
        "market_book_add",
        "positions_get",
    ):
        assert not hasattr(MetaTrader5ReadOnlyClient, forbidden)


def test_probe_preserves_capabilities_without_account_or_path_secrets() -> None:
    client = FakeReadOnlyClient()
    report = run_mt5_readonly_probe(
        client,
        history_symbols=("AAPL",),
        bar_start=_utc(2026, 3, 9, 13, 30),
        bar_end=_utc(2026, 3, 9, 20, 0),
        tick_start=_utc(2026, 3, 9, 13, 30),
        tick_end=_utc(2026, 3, 9, 14, 30),
        spread_symbols=("MSFT",),
        probed_at=_utc(2026, 3, 9, 20, 1),
    )

    assert client.shutdown_called is True
    assert report.read_only is True
    assert report.mutation_authority is False
    assert len(report.symbols) == 2
    assert report.visible_symbol_count == 2
    assert report.tradable_symbol_count == 2
    assert report.history[0].m1_bar_count == 3
    assert report.history[0].tick_count == 2
    assert report.spread_samples[0].spread_points == pytest.approx(5.0)
    payload = report.to_dict()
    rendered = str(payload)
    assert "123456789" not in rendered
    assert "sensitive/path" not in rendered
    assert payload["terminal"]["broker_server"] == "Broker-Demo"  # type: ignore[index]


def test_probe_rejects_unbounded_history_request() -> None:
    client = FakeReadOnlyClient()
    client.initialize()
    with pytest.raises(ValueError, match="require bar_start and bar_end"):
        probe_mt5_capabilities(client, history_symbols=("AAPL",))


def test_official_client_fails_closed_on_package_version_mismatch() -> None:
    fake_module = SimpleNamespace(
        __version__="5.0.9999",
        TIMEFRAME_M1=1,
        COPY_TICKS_ALL=0,
    )
    with pytest.raises(RuntimeError, match="package version mismatch"):
        MetaTrader5ReadOnlyClient(
            expected_package_version="5.0.6147",
            module=fake_module,
        )


def test_official_client_initialization_and_group_filter_are_read_only() -> None:
    calls: list[object] = []

    def initialize() -> bool:
        calls.append("initialize")
        return True

    def shutdown() -> None:
        calls.append("shutdown")

    def symbols_get(*, group: str = "") -> tuple[object, ...]:
        calls.append(("symbols_get", group))
        return ()

    fake_module = SimpleNamespace(
        __version__="5.0.6147",
        TIMEFRAME_M1=1,
        COPY_TICKS_ALL=0,
        initialize=initialize,
        shutdown=shutdown,
        last_error=lambda: (1, "ok"),
        symbols_get=symbols_get,
    )
    client = MetaTrader5ReadOnlyClient(module=fake_module)
    client.initialize()
    assert client.symbols_get("*USD*") == ()
    client.shutdown()

    assert calls == ["initialize", ("symbols_get", "*USD*"), "shutdown"]

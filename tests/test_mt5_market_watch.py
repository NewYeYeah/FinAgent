from __future__ import annotations

from types import SimpleNamespace

import pytest

from finagent.brokers.mt5 import MetaTrader5MarketWatchClient
from scripts.ensure_mt5_market_watch import _report_id


class FakeMT5Module:
    __version__ = "5.0.6147"
    TIMEFRAME_M1 = 1
    COPY_TICKS_ALL = 0

    def __init__(self, *, trade_allowed: bool = False, tradeapi_disabled: bool = True) -> None:
        self.trade_allowed = trade_allowed
        self.tradeapi_disabled = tradeapi_disabled
        self.visible = {"AMD.NAS": False, "NVDA.NAS": True}
        self.select_calls: list[tuple[str, bool]] = []
        self.shutdown_calls = 0

    def initialize(self) -> bool:
        return True

    def shutdown(self) -> None:
        self.shutdown_calls += 1

    def last_error(self) -> tuple[int, str]:
        return (1, "ok")

    def terminal_info(self) -> object:
        return SimpleNamespace(
            trade_allowed=self.trade_allowed,
            tradeapi_disabled=self.tradeapi_disabled,
        )

    def symbol_info(self, symbol: str) -> object | None:
        if symbol not in self.visible:
            return None
        return SimpleNamespace(visible=self.visible[symbol])

    def symbol_select(self, symbol: str, visible: bool) -> bool:
        self.select_calls.append((symbol, visible))
        if symbol not in self.visible:
            return False
        self.visible[symbol] = visible
        return True


def test_adds_allowlisted_symbol_and_is_idempotent() -> None:
    module = FakeMT5Module()
    client = MetaTrader5MarketWatchClient(
        allowed_symbols=("AMD.NAS", "NVDA.NAS"),
        module=module,
    )

    with client:
        added = client.ensure_visible("AMD.NAS")
        unchanged = client.ensure_visible("NVDA.NAS")

    assert added.changed is True
    assert added.was_visible is False
    assert added.is_visible is True
    assert unchanged.changed is False
    assert module.select_calls == [("AMD.NAS", True)]
    assert module.shutdown_calls == 1


def test_refuses_symbol_outside_per_run_allowlist() -> None:
    module = FakeMT5Module()
    client = MetaTrader5MarketWatchClient(
        allowed_symbols=("AMD.NAS",),
        module=module,
    )

    with client, pytest.raises(PermissionError, match="explicit allowlist"):
        client.ensure_visible("NVDA.NAS")

    assert module.select_calls == []


@pytest.mark.parametrize(
    ("trade_allowed", "tradeapi_disabled"),
    ((True, True), (False, False), (True, False)),
)
def test_inherits_funded_account_trading_lockout(
    trade_allowed: bool,
    tradeapi_disabled: bool,
) -> None:
    module = FakeMT5Module(
        trade_allowed=trade_allowed,
        tradeapi_disabled=tradeapi_disabled,
    )
    client = MetaTrader5MarketWatchClient(
        allowed_symbols=("AMD.NAS",),
        module=module,
    )

    with pytest.raises(RuntimeError, match="read-only lockout is not active"):
        client.initialize()

    assert module.select_calls == []
    assert module.shutdown_calls == 1


def test_exposes_no_trading_or_position_surface() -> None:
    for forbidden in (
        "order_send",
        "order_check",
        "order_calc_margin",
        "order_calc_profit",
        "positions_get",
        "orders_get",
        "history_orders_get",
        "history_deals_get",
        "market_book_add",
    ):
        assert not hasattr(MetaTrader5MarketWatchClient, forbidden)


def test_market_watch_report_id_is_content_addressed() -> None:
    first = {"mode": "apply", "symbols": ["AMD.NAS", "NVDA.NAS"]}
    reordered = {"symbols": ["AMD.NAS", "NVDA.NAS"], "mode": "apply"}

    assert _report_id(first) == _report_id(reordered)
    assert _report_id(first).startswith("mt5-market-watch-change-")
    assert _report_id(first) != _report_id({"mode": "dry_run", "symbols": first["symbols"]})

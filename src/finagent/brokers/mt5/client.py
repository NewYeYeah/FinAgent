from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any, Protocol, Self, runtime_checkable

RECOMMENDED_MT5_PACKAGE_VERSION = "5.0.6147"


@runtime_checkable
class MT5ReadOnlyClientProtocol(Protocol):
    """Narrow MT5-P0 surface.

    Deliberately excludes order checks/sends, symbol selection, market-book
    subscriptions, and any account/position mutation surface.
    """

    @property
    def package_version(self) -> str: ...

    @property
    def timeframe_m1(self) -> int: ...

    @property
    def copy_ticks_all(self) -> int: ...

    def initialize(self) -> None: ...

    def shutdown(self) -> None: ...

    def version(self) -> object: ...

    def terminal_info(self) -> object: ...

    def account_info(self) -> object: ...

    def symbols_get(self, group: str = "") -> object: ...

    def symbol_info_tick(self, symbol: str) -> object: ...

    def copy_rates_range(
        self,
        symbol: str,
        date_from: object,
        date_to: object,
    ) -> object: ...

    def copy_ticks_range(
        self,
        symbol: str,
        date_from: object,
        date_to: object,
    ) -> object: ...


class MetaTrader5ReadOnlyClient:
    """Import-safe adapter over the official Windows MetaTrader5 Python package."""

    def __init__(
        self,
        *,
        expected_package_version: str = RECOMMENDED_MT5_PACKAGE_VERSION,
        module: ModuleType | Any | None = None,
    ) -> None:
        if module is None:
            try:
                module = importlib.import_module("MetaTrader5")
            except ImportError as exc:
                raise RuntimeError(
                    "MT5-P0 local probing requires the official MetaTrader5 package in the "
                    "active Windows Conda environment"
                ) from exc
        self._module: Any = module
        observed = str(getattr(self._module, "__version__", "")).strip()
        if not observed:
            raise RuntimeError("MetaTrader5 package does not expose __version__")
        if expected_package_version and observed != expected_package_version:
            raise RuntimeError(
                f"MetaTrader5 package version mismatch: observed {observed}, "
                f"expected {expected_package_version}"
            )
        self._package_version = observed
        self._initialized = False

    @property
    def package_version(self) -> str:
        return self._package_version

    @property
    def timeframe_m1(self) -> int:
        return int(self._module.TIMEFRAME_M1)

    @property
    def copy_ticks_all(self) -> int:
        return int(self._module.COPY_TICKS_ALL)

    def _last_error(self) -> object:
        return self._module.last_error()

    def initialize(self) -> None:
        if self._initialized:
            return
        if not bool(self._module.initialize()):
            raise RuntimeError(f"MetaTrader5 initialize() failed: {self._last_error()!r}")
        self._initialized = True

    def shutdown(self) -> None:
        if self._initialized:
            self._module.shutdown()
            self._initialized = False

    def __enter__(self) -> Self:
        self.initialize()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.shutdown()

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("MetaTrader5 client is not initialized")

    def _required_result(self, value: object, operation: str) -> object:
        if value is None:
            raise RuntimeError(f"MetaTrader5 {operation} failed: {self._last_error()!r}")
        return value

    def version(self) -> object:
        self._require_initialized()
        return self._required_result(self._module.version(), "version()")

    def terminal_info(self) -> object:
        self._require_initialized()
        return self._required_result(self._module.terminal_info(), "terminal_info()")

    def account_info(self) -> object:
        self._require_initialized()
        return self._required_result(self._module.account_info(), "account_info()")

    def symbols_get(self, group: str = "") -> object:
        self._require_initialized()
        if group.strip():
            value = self._module.symbols_get(group=group.strip())
        else:
            value = self._module.symbols_get()
        return self._required_result(value, "symbols_get()")

    def symbol_info_tick(self, symbol: str) -> object:
        self._require_initialized()
        value = self._module.symbol_info_tick(symbol)
        return self._required_result(value, f"symbol_info_tick({symbol!r})")

    def copy_rates_range(
        self,
        symbol: str,
        date_from: object,
        date_to: object,
    ) -> object:
        self._require_initialized()
        value = self._module.copy_rates_range(
            symbol,
            self.timeframe_m1,
            date_from,
            date_to,
        )
        return self._required_result(value, f"copy_rates_range({symbol!r})")

    def copy_ticks_range(
        self,
        symbol: str,
        date_from: object,
        date_to: object,
    ) -> object:
        self._require_initialized()
        value = self._module.copy_ticks_range(
            symbol,
            date_from,
            date_to,
            self.copy_ticks_all,
        )
        return self._required_result(value, f"copy_ticks_range({symbol!r})")

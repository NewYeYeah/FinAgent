from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from .client import RECOMMENDED_MT5_PACKAGE_VERSION, MetaTrader5ReadOnlyClient


@dataclass(frozen=True, slots=True)
class MT5MarketWatchChange:
    """Auditable result of an add-only Market Watch visibility request."""

    symbol: str
    was_visible: bool
    is_visible: bool
    changed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "was_visible": self.was_visible,
            "is_visible": self.is_visible,
            "changed": self.changed,
        }


class MetaTrader5MarketWatchClient(MetaTrader5ReadOnlyClient):
    """Opt-in, add-only Market Watch client with no trading surface.

    The inherited initialization guard still requires terminal trading and external
    Python trading to be disabled. Only exact constructor-approved symbols may be
    made visible. Removing symbols is intentionally outside this capability.
    """

    def __init__(
        self,
        *,
        allowed_symbols: Iterable[str],
        expected_package_version: str = RECOMMENDED_MT5_PACKAGE_VERSION,
        module: ModuleType | Any | None = None,
    ) -> None:
        normalized = tuple(dict.fromkeys(symbol.strip() for symbol in allowed_symbols))
        if not normalized or any(not symbol for symbol in normalized):
            raise ValueError("allowed_symbols must contain non-empty exact broker symbols")
        super().__init__(
            expected_package_version=expected_package_version,
            module=module,
        )
        self._allowed_symbols = frozenset(normalized)

    @property
    def allowed_symbols(self) -> tuple[str, ...]:
        return tuple(sorted(self._allowed_symbols))

    def ensure_visible(self, symbol: str) -> MT5MarketWatchChange:
        """Make one explicitly allowed broker symbol visible in Market Watch."""

        self._require_initialized()
        exact_symbol = symbol.strip()
        if exact_symbol not in self._allowed_symbols:
            raise PermissionError(
                f"Market Watch symbol is not in the explicit allowlist: {exact_symbol!r}"
            )
        before = self.symbol_info(exact_symbol)
        was_visible = bool(getattr(before, "visible", False))
        if was_visible:
            return MT5MarketWatchChange(
                symbol=exact_symbol,
                was_visible=True,
                is_visible=True,
                changed=False,
            )
        if not bool(self._module.symbol_select(exact_symbol, True)):
            raise RuntimeError(
                f"MetaTrader5 symbol_select({exact_symbol!r}, True) failed: "
                f"{self._last_error()!r}"
            )
        after = self.symbol_info(exact_symbol)
        is_visible = bool(getattr(after, "visible", False))
        if not is_visible:
            raise RuntimeError(
                f"MetaTrader5 reported success but {exact_symbol!r} is not visible"
            )
        return MT5MarketWatchChange(
            symbol=exact_symbol,
            was_visible=False,
            is_visible=True,
            changed=True,
        )

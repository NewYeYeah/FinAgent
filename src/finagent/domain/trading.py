from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True, slots=True)
class TradeActivity:
    """Canonical traded-weight convention shared by research and portfolio code.

    ``gross_traded_weight`` is the economic quantity used for linear bps cost:

        sum_i |w_new_i - w_old_i|

    ``one_way_turnover`` is the common reporting convention:

        0.5 * gross_traded_weight

    Keeping both names explicit prevents a silent factor-of-two change when a cost
    rate is moved between feature research, portfolio optimization and backtests.
    """

    gross_traded_weight: float
    one_way_turnover: float
    buy_weight: float
    sell_weight: float
    traded_notional: float | None = None

    def __post_init__(self) -> None:
        values = (
            self.gross_traded_weight,
            self.one_way_turnover,
            self.buy_weight,
            self.sell_weight,
        )
        if any(not np.isfinite(v) or v < -1e-12 for v in values):
            raise ValueError("trade activity weights must be finite and non-negative")
        if abs(self.gross_traded_weight - (self.buy_weight + self.sell_weight)) > 1e-9:
            raise ValueError("gross_traded_weight must equal buy_weight + sell_weight")
        if abs(self.one_way_turnover - 0.5 * self.gross_traded_weight) > 1e-9:
            raise ValueError("one_way_turnover must equal 0.5 * gross_traded_weight")
        if self.traded_notional is not None:
            if not np.isfinite(self.traded_notional) or self.traded_notional < -1e-12:
                raise ValueError("traded_notional must be finite and non-negative")

    @classmethod
    def from_weights(
        cls,
        previous: Sequence[float],
        target: Sequence[float],
        *,
        nav: float | None = None,
    ) -> "TradeActivity":
        old = np.asarray(previous, dtype=float)
        new = np.asarray(target, dtype=float)
        if old.shape != new.shape or old.ndim != 1:
            raise ValueError("previous and target weights must be aligned one-dimensional arrays")
        if not np.all(np.isfinite(old)) or not np.all(np.isfinite(new)):
            raise ValueError("weights must be finite")
        delta = new - old
        buy = float(np.clip(delta, 0.0, None).sum())
        sell = float(np.clip(-delta, 0.0, None).sum())
        gross = buy + sell
        notional = None
        if nav is not None:
            nav = float(nav)
            if not np.isfinite(nav) or nav < 0:
                raise ValueError("nav must be finite and non-negative")
            notional = gross * nav
        return cls(gross, 0.5 * gross, buy, sell, notional)

    @classmethod
    def from_traded_notional(cls, traded_notional: float, nav: float) -> "TradeActivity":
        traded_notional = float(traded_notional)
        nav = float(nav)
        if not np.isfinite(traded_notional) or traded_notional < 0:
            raise ValueError("traded_notional must be finite and non-negative")
        if not np.isfinite(nav) or nav <= 0:
            raise ValueError("nav must be finite and > 0")
        gross = traded_notional / nav
        # Fill-level data alone cannot distinguish buys from sells without the order
        # side.  The symmetric split is used only for aggregate reporting; gross and
        # one-way quantities remain exact.
        half = 0.5 * gross
        return cls(gross, half, half, half, traded_notional)

    def linear_cost_fraction(self, bps: float) -> float:
        bps = float(bps)
        if not np.isfinite(bps) or bps < 0:
            raise ValueError("bps must be finite and non-negative")
        return self.gross_traded_weight * bps / 10_000.0

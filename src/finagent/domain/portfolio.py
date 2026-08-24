from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping

from ._validation import (
    freeze_mapping,
    require_aware_datetime,
    require_finite,
    require_non_empty,
    require_positive,
)
from .assets import AssetId
from .forecasts import ModelRef


@dataclass(frozen=True, slots=True)
class PortfolioState:
    """Marked portfolio state in one base currency.

    FX translation is deliberately out of scope for Phase 0.5.  All assets must
    be valued in `base_currency` by the adapter/service constructing this state.
    """

    asof: datetime
    base_currency: str
    cash: float
    positions: Mapping[AssetId, float] = field(default_factory=dict)
    marks: Mapping[AssetId, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        asof = require_aware_datetime(self.asof, "asof")
        base_currency = require_non_empty(self.base_currency, "base_currency").upper()
        cash = require_finite(self.cash, "cash")

        positions = {
            asset: require_finite(quantity, f"positions[{asset.key}]")
            for asset, quantity in self.positions.items()
        }
        marks = {
            asset: require_positive(price, f"marks[{asset.key}]")
            for asset, price in self.marks.items()
        }
        missing_marks = {asset for asset, quantity in positions.items() if quantity != 0 and asset not in marks}
        if missing_marks:
            keys = ", ".join(sorted(asset.key for asset in missing_marks))
            raise ValueError(f"non-zero positions require marks; missing: {keys}")

        object.__setattr__(self, "asof", asof)
        object.__setattr__(self, "base_currency", base_currency)
        object.__setattr__(self, "cash", cash)
        object.__setattr__(self, "positions", freeze_mapping(positions))
        object.__setattr__(self, "marks", freeze_mapping(marks))

    @property
    def nav(self) -> float:
        return self.cash + sum(quantity * self.marks[asset] for asset, quantity in self.positions.items())

    def market_value(self, asset: AssetId) -> float:
        return self.positions.get(asset, 0.0) * self.marks.get(asset, 0.0)

    def weight(self, asset: AssetId) -> float:
        nav = self.nav
        if abs(nav) <= 1e-15:
            raise ZeroDivisionError("portfolio NAV is zero; weights are undefined")
        return self.market_value(asset) / nav


@dataclass(frozen=True, slots=True)
class PortfolioTarget:
    """Canonical portfolio contract passed downstream from portfolio construction."""

    asof: datetime
    weights: Mapping[AssetId, float]
    cash_weight: float
    source: ModelRef
    metadata: Mapping[str, str] = field(default_factory=dict)
    weight_tolerance: float = 1e-10

    def __post_init__(self) -> None:
        asof = require_aware_datetime(self.asof, "asof")
        if self.weight_tolerance < 0:
            raise ValueError("weight_tolerance must be >= 0")

        weights = {
            asset: require_finite(weight, f"weights[{asset.key}]")
            for asset, weight in self.weights.items()
        }
        cash_weight = require_finite(self.cash_weight, "cash_weight")
        total = sum(weights.values()) + cash_weight
        if abs(total - 1.0) > self.weight_tolerance:
            raise ValueError(
                f"portfolio target must satisfy sum(weights)+cash_weight=1; got {total:.16g}"
            )

        object.__setattr__(self, "asof", asof)
        object.__setattr__(self, "weights", freeze_mapping(weights))
        object.__setattr__(self, "cash_weight", cash_weight)
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))

    @property
    def gross_exposure(self) -> float:
        return sum(abs(weight) for weight in self.weights.values())

    @property
    def net_exposure(self) -> float:
        return sum(self.weights.values())


@dataclass(frozen=True, slots=True)
class RiskViolation:
    code: str
    message: str
    observed: float | None = None
    limit: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", require_non_empty(self.code, "code"))
        object.__setattr__(self, "message", require_non_empty(self.message, "message"))
        if self.observed is not None:
            object.__setattr__(self, "observed", require_finite(self.observed, "observed"))
        if self.limit is not None:
            object.__setattr__(self, "limit", require_finite(self.limit, "limit"))


class RiskStatus(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUIRE_RESOLVE = "require_resolve"


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """Explicit risk decision; risk controls never silently rewrite a target."""

    status: RiskStatus
    violations: tuple[RiskViolation, ...] = ()
    checked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.checked_at is not None:
            object.__setattr__(self, "checked_at", require_aware_datetime(self.checked_at, "checked_at"))
        if self.status is RiskStatus.APPROVE and self.violations:
            raise ValueError("APPROVE decisions cannot carry violations")
        if self.status is not RiskStatus.APPROVE and not self.violations:
            raise ValueError("non-APPROVE decisions must include at least one violation")

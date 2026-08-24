from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ._validation import require_non_empty


class AssetType(str, Enum):
    EQUITY = "equity"
    ETF = "etf"
    FUTURE = "future"
    FX = "fx"
    CRYPTO = "crypto"
    CASH = "cash"
    OTHER = "other"


@dataclass(frozen=True, slots=True, order=True)
class AssetId:
    """Stable identity for a tradeable instrument.

    `symbol` alone is not assumed globally unique.  Venue, asset type and currency
    are part of the identity so adapters can map vendor-specific symbols onto a
    deterministic internal key.
    """

    symbol: str
    asset_type: AssetType = AssetType.EQUITY
    venue: str = ""
    currency: str = "USD"

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", require_non_empty(self.symbol, "symbol").upper())
        object.__setattr__(self, "venue", self.venue.strip().upper())
        object.__setattr__(self, "currency", require_non_empty(self.currency, "currency").upper())

    @property
    def key(self) -> str:
        venue = self.venue or "-"
        return f"{self.asset_type.value}:{venue}:{self.symbol}:{self.currency}"

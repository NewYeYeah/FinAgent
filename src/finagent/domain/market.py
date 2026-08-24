from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from ._validation import (
    freeze_mapping,
    require_aware_datetime,
    require_finite,
    require_non_empty,
    require_non_negative,
    require_positive,
)
from .assets import AssetId


@dataclass(frozen=True, slots=True)
class PriceBar:
    """Point-in-time safe OHLCV observation.

    `event_time` is the market timestamp represented by the bar. `available_at`
    is the timestamp at which the system could actually have observed the bar.
    A MarketSnapshot rejects observations whose `available_at` is after its `asof`.
    """

    event_time: datetime
    available_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        event_time = require_aware_datetime(self.event_time, "event_time")
        available_at = require_aware_datetime(self.available_at, "available_at")
        if available_at < event_time:
            raise ValueError("available_at cannot be earlier than event_time")

        open_ = require_positive(self.open, "open")
        high = require_positive(self.high, "high")
        low = require_positive(self.low, "low")
        close = require_positive(self.close, "close")
        volume = require_non_negative(self.volume, "volume")

        if high < max(open_, low, close):
            raise ValueError("high must be >= open, low and close")
        if low > min(open_, high, close):
            raise ValueError("low must be <= open, high and close")

        object.__setattr__(self, "event_time", event_time)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "open", open_)
        object.__setattr__(self, "high", high)
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "close", close)
        object.__setattr__(self, "volume", volume)


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """The complete market information available to a component at one instant."""

    asof: datetime
    bars: Mapping[AssetId, PriceBar]
    data_version: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        asof = require_aware_datetime(self.asof, "asof")
        data_version = require_non_empty(self.data_version, "data_version")
        bars = freeze_mapping(self.bars)
        metadata = freeze_mapping(self.metadata)

        for asset, bar in bars.items():
            if not isinstance(asset, AssetId):
                raise TypeError("bars keys must be AssetId instances")
            if not isinstance(bar, PriceBar):
                raise TypeError("bars values must be PriceBar instances")
            if bar.available_at > asof:
                raise ValueError(
                    f"look-ahead detected for {asset.key}: available_at={bar.available_at.isoformat()} "
                    f"> snapshot.asof={asof.isoformat()}"
                )

        object.__setattr__(self, "asof", asof)
        object.__setattr__(self, "data_version", data_version)
        object.__setattr__(self, "bars", bars)
        object.__setattr__(self, "metadata", metadata)

    def price(self, asset: AssetId) -> float:
        try:
            return self.bars[asset].close
        except KeyError as exc:
            raise KeyError(f"no price available for {asset.key}") from exc

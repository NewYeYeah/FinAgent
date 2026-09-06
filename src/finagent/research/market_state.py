"""Causal research MarketState contracts and session-local OHLCV features.

This is a research object, distinct from realtime market/account projections.
The accepted 15m FactorGraph clock is reused; input bars come from minute OHLCV.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise

from finagent.domain._validation import require_aware_datetime, require_non_empty
from finagent.research.us_a1_factor_panel_materialization import FactorPanelAsset, _validate_panel
from finagent.research.us_baselines import _canonical_hash


def utc_text(value: datetime) -> str:
    require_aware_datetime(value, "timestamp")
    return value.astimezone(UTC).isoformat()


@dataclass(frozen=True)
class MarketStateSource:
    source_id: str
    source_revision: str
    data_version: str
    admission_id: str
    calendar_id: str
    scope: str = "local_development_only"

    def __post_init__(self) -> None:
        for name in ("source_id", "source_revision", "data_version", "admission_id", "calendar_id"):
            require_non_empty(getattr(self, name), name)
        if self.scope != "local_development_only":
            raise ValueError("MarketState v1 admits development data only")

    @property
    def identity(self) -> str:
        return str(_canonical_hash(asdict(self), prefix="market-state-source"))


@dataclass(frozen=True)
class MarketFeatureConfig:
    proxy_asset: str = "IWM"
    lookback_returns: int = 4

    def __post_init__(self) -> None:
        require_non_empty(self.proxy_asset, "proxy_asset")
        if type(self.lookback_returns) is not int or not 2 <= self.lookback_returns <= 32:
            raise ValueError("lookback_returns must be an integer in 2..32")

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "version": "finagent.market-features.v1",
            "features": [
                "proxy_close[t]/proxy_close[t-lookback_returns]-1",
                "sqrt(mean(square(adjacent_proxy_simple_returns)))",
            ],
            "interval": "15m",
            "price_basis": "RAW",
            "window": "same_session_complete_consecutive_bars_only",
            "available_at": "current_bar_close",
            "missing": "unavailable_no_imputation_no_compressed_gaps",
        }


@dataclass(frozen=True)
class MarketFeatureRow:
    event_time: datetime
    available_at: datetime
    session_id: str
    values: tuple[float, float] | None
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        require_aware_datetime(self.event_time, "event_time")
        require_aware_datetime(self.available_at, "available_at")
        require_non_empty(self.session_id, "session_id")
        if self.available_at != self.event_time + timedelta(minutes=15):
            raise ValueError("features require canonical 15m bar-close availability")
        if (self.values is None) == (self.unavailable_reason is None):
            raise ValueError("exactly one of values/unavailable_reason is required")
        if self.values is not None and (
            len(self.values) != 2
            or any(not math.isfinite(v) for v in self.values)
            or self.values[1] < 0
        ):
            raise ValueError("invalid market features")

    def to_dict(self) -> dict[str, object]:
        return {
            "event_time": utc_text(self.event_time),
            "available_at": utc_text(self.available_at),
            "session_id": self.session_id,
            "values": self.values,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True)
class MarketFeatures:
    source: MarketStateSource
    config: MarketFeatureConfig
    rows: tuple[MarketFeatureRow, ...]

    def __post_init__(self) -> None:
        if not self.rows or any(
            a.event_time >= b.event_time for a, b in zip(self.rows, self.rows[1:])
        ):
            raise ValueError("market feature rows must be nonempty and strictly chronological")


def build_market_features(
    assets: tuple[FactorPanelAsset, ...],
    source: MarketStateSource,
    config: MarketFeatureConfig | None = None,
) -> MarketFeatures:
    """No normalizer is fitted here; each row consumes only its own past window."""
    config = config or MarketFeatureConfig()
    _validate_panel(assets, maximum_assets=256, maximum_bars_per_asset=32_768)
    by_asset = {asset.asset_id: asset.bars for asset in assets}
    if config.proxy_asset not in by_asset:
        raise ValueError("declared market proxy is missing from the admitted universe")
    bars = by_asset[config.proxy_asset]
    rows = []
    start = 0
    for i, bar in enumerate(bars):
        if i == 0 or bars[i - 1].session_id != bar.session_id:
            start = i
        values = None
        reason = None
        if i - start < config.lookback_returns:
            reason = "INSUFFICIENT_SESSION_HISTORY"
        else:
            window = bars[i - config.lookback_returns : i + 1]
            if any(not b.is_complete for b in window):
                reason = "INCOMPLETE_PROXY_WINDOW"
            else:
                returns = [b.close / a.close - 1 for a, b in pairwise(window)]
                values = (
                    bar.close / window[0].close - 1,
                    math.sqrt(math.fsum(r * r for r in returns) / len(returns)),
                )
                if any(not math.isfinite(v) for v in values):
                    values, reason = None, "NUMERIC_UNAVAILABLE"
        rows.append(
            MarketFeatureRow(bar.event_time, bar.available_at, bar.session_id, values, reason)
        )
    return MarketFeatures(source, config, tuple(rows))


@dataclass(frozen=True)
class MarketStateRow:
    model_id: str
    event_time: datetime
    available_at: datetime
    session_id: str
    probabilities: tuple[float, ...] | None
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.model_id, "model_id")
        require_non_empty(self.session_id, "session_id")
        require_aware_datetime(self.event_time, "event_time")
        require_aware_datetime(self.available_at, "available_at")
        if self.available_at < self.event_time:
            raise ValueError("state cannot precede its event")
        if (self.probabilities is None) == (self.unavailable_reason is None):
            raise ValueError("exactly one of probabilities/unavailable_reason is required")
        if self.probabilities is not None and (
            not self.probabilities
            or any(not math.isfinite(p) or not 0 <= p <= 1 for p in self.probabilities)
            or not math.isclose(math.fsum(self.probabilities), 1.0, abs_tol=1e-12)
        ):
            raise ValueError("state probabilities must be finite, nonnegative and sum to one")

    @property
    def state(self) -> int | None:
        probabilities = self.probabilities
        if probabilities is None:
            return None
        return max(range(len(probabilities)), key=lambda i: probabilities[i])

    def to_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "event_time": utc_text(self.event_time),
            "available_at": utc_text(self.available_at),
            "session_id": self.session_id,
            "probabilities": self.probabilities,
            "state": self.state,
            "unavailable_reason": self.unavailable_reason,
        }

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence

import numpy as np

from ._validation import require_aware_datetime, require_non_empty
from .assets import AssetId


@dataclass(frozen=True, slots=True)
class UniverseSnapshot:
    """Point-in-time investability state for a candidate asset set.

    Identity remains in ``AssetId``.  Listing/trading/borrow/membership state is
    deliberately time-varying and therefore belongs here rather than in AssetId.
    """

    asof: datetime
    eligible: Mapping[AssetId, bool]
    reasons: Mapping[AssetId, str] = field(default_factory=dict)
    data_version: str = "universe-v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "asof", require_aware_datetime(self.asof, "asof"))
        if not self.eligible:
            raise ValueError("UniverseSnapshot.eligible cannot be empty")
        normalized = {asset: bool(value) for asset, value in self.eligible.items()}
        reasons = {asset: str(value) for asset, value in self.reasons.items()}
        unknown = set(reasons) - set(normalized)
        if unknown:
            raise ValueError("UniverseSnapshot reasons contain unknown assets")
        object.__setattr__(self, "eligible", MappingProxyType(normalized))
        object.__setattr__(self, "reasons", MappingProxyType(reasons))
        object.__setattr__(self, "data_version", require_non_empty(self.data_version, "data_version"))

    @property
    def eligible_assets(self) -> tuple[AssetId, ...]:
        return tuple(asset for asset, flag in self.eligible.items() if flag)

    def mask(self, assets: Sequence[AssetId]) -> np.ndarray:
        missing = [asset.key for asset in assets if asset not in self.eligible]
        if missing:
            raise KeyError(f"universe snapshot does not cover assets: {missing}")
        result = np.asarray([self.eligible[asset] for asset in assets], dtype=bool)
        result.setflags(write=False)
        return result


class UniverseProvider(Protocol):
    @property
    def data_version(self) -> str: ...

    def snapshot(self, asof: datetime, assets: tuple[AssetId, ...]) -> UniverseSnapshot: ...


class StaticUniverseProvider:
    """Explicit all-eligible provider for fixed-universe research and tests."""

    def __init__(self, *, data_version: str = "static-universe-v1") -> None:
        self._data_version = require_non_empty(data_version, "data_version")

    @property
    def data_version(self) -> str:
        return self._data_version

    def snapshot(self, asof: datetime, assets: tuple[AssetId, ...]) -> UniverseSnapshot:
        if not assets:
            raise ValueError("assets cannot be empty")
        return UniverseSnapshot(
            asof=asof,
            eligible={asset: True for asset in assets},
            data_version=self.data_version,
        )


class ScheduledUniverseProvider:
    """Deterministic PIT universe schedule for historical tests and adapters.

    Each schedule key is the time at which the new eligibility state became known.
    ``snapshot(asof)`` uses only the latest schedule entry at or before ``asof``.
    """

    def __init__(
        self,
        schedule: Mapping[datetime, Sequence[AssetId]],
        *,
        data_version: str = "scheduled-universe-v1",
    ) -> None:
        if not schedule:
            raise ValueError("schedule cannot be empty")
        normalized: list[tuple[datetime, frozenset[AssetId]]] = []
        for asof, assets in schedule.items():
            normalized.append((require_aware_datetime(asof, "schedule asof"), frozenset(assets)))
        normalized.sort(key=lambda item: item[0])
        self._schedule = tuple(normalized)
        self._data_version = require_non_empty(data_version, "data_version")

    @property
    def data_version(self) -> str:
        return self._data_version

    def snapshot(self, asof: datetime, assets: tuple[AssetId, ...]) -> UniverseSnapshot:
        asof = require_aware_datetime(asof, "asof")
        selected: frozenset[AssetId] | None = None
        for effective_at, eligible in self._schedule:
            if effective_at > asof:
                break
            selected = eligible
        if selected is None:
            raise KeyError("no universe schedule is available at or before asof")
        return UniverseSnapshot(
            asof=asof,
            eligible={asset: asset in selected for asset in assets},
            reasons={asset: "not eligible in PIT universe" for asset in assets if asset not in selected},
            data_version=self.data_version,
        )

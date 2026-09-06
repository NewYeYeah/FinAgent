"""Causal same-slot activity context and one bounded reversal hypothesis."""

from __future__ import annotations

import math
from collections import deque
from datetime import date
from statistics import median
from typing import cast

from finagent.research.us_a1_factor_panel_materialization import FactorPanelAsset
from finagent.research.us_r3_economics import EconomicPolicy, positive_weights

ACTIVITY_ARMS = (
    "activity_relative_reversal",
    "activity_reversal_ablation",
    "activity_trigger_equal_weight",
)


class ActivityHistory:
    """Exactly 20 preceding calendar sessions; gaps are retained, never skipped.

    Call once per accepted calendar session, including missing sessions. Slots
    are offsets from local session open, so DST cannot change slot identity.
    The caller binds calendar chronology and pads missing source observations.
    """

    def __init__(self) -> None:
        self.history: deque[dict[tuple[str, int], float | None]] = deque(maxlen=20)
        self.last_date: date | None = None

    def process(
        self, day: date, assets: tuple[FactorPanelAsset, ...]
    ) -> dict[str, list[float | None]]:
        if self.last_date is not None and day <= self.last_date:
            raise ValueError("activity sessions must be strictly chronological")
        current: dict[tuple[str, int], float | None] = {}
        ratios: dict[str, list[float | None]] = {}
        for asset in assets:
            if asset.asset_id in ratios or len(asset.bars) > 64 or len(assets) > 256:
                raise ValueError("duplicate or unbounded activity panel")
            values: list[float | None] = []
            for slot, bar in enumerate(asset.bars):
                if not math.isfinite(bar.volume) or bar.volume < 0:
                    raise ValueError("activity volume must be nonnegative finite")
                key = (asset.asset_id, slot)
                volume = float(bar.volume) if bar.is_complete else None
                previous = [row.get(key) for row in self.history]
                baseline = (
                    median([v for v in previous if v is not None])
                    if len(previous) == 20 and all(v is not None for v in previous)
                    else None
                )
                values.append(
                    volume / baseline
                    if volume is not None and baseline is not None and baseline > 0
                    else None
                )
                current[key] = volume
            ratios[asset.asset_id] = values
        # Mutate state only after computing every output; current-session values
        # and later slots cannot enter their own historical denominator.
        self.history.append(current)
        self.last_date = day
        return ratios


def activity_targets(
    assets: tuple[FactorPanelAsset, ...],
    ratios: dict[str, list[float | None]],
    policy: EconomicPolicy,
) -> dict[str, list[dict[str, float]]]:
    targets: dict[str, list[dict[str, float]]] = {name: [] for name in ACTIVITY_ARMS}
    for slot in range(len(assets[0].bars)):
        valid = {
            a.asset_id: a.bars[slot].close / a.bars[slot].open - 1.0
            for a in assets
            if a.bars[slot].is_complete and ratios[a.asset_id][slot] is not None
        }
        mean = math.fsum(valid.values()) / len(valid) if valid else 0.0
        scores = {
            a.asset_id: mean - valid[a.asset_id] if a.asset_id in valid else None for a in assets
        }
        masked = {
            a: value
            if ratios[a][slot] is not None and cast(float, ratios[a][slot]) >= 2.0
            else (0.0 if value is not None else None)
            for a, value in scores.items()
        }
        selected = positive_weights(masked, policy)
        targets[ACTIVITY_ARMS[0]].append(selected)
        targets[ACTIVITY_ARMS[1]].append(positive_weights(scores, policy))
        # Identical signal trigger, broad valid-history universe; does not use
        # future performance or execution prices to choose the comparison day.
        targets[ACTIVITY_ARMS[2]].append(
            {a: 1.0 / len(valid) for a in sorted(valid)} if selected else {}
        )
    return targets

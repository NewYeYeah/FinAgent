from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from collections.abc import Sequence

from .base import NormalizedBarRecord


@dataclass(frozen=True, slots=True)
class ProviderDiffReport:
    left_provider: str
    right_provider: str
    common_rows: int
    missing_left: tuple[str, ...]
    missing_right: tuple[str, ...]
    max_close_abs_error: float
    max_close_rel_error: float
    max_volume_rel_error: float

    @property
    def exact_calendar_match(self) -> bool:
        return not self.missing_left and not self.missing_right

    @property
    def passed_basic_qa(self) -> bool:
        return self.exact_calendar_match and self.common_rows > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "left_provider": self.left_provider,
            "right_provider": self.right_provider,
            "common_rows": self.common_rows,
            "missing_left": list(self.missing_left),
            "missing_right": list(self.missing_right),
            "exact_calendar_match": self.exact_calendar_match,
            "max_close_abs_error": self.max_close_abs_error,
            "max_close_rel_error": self.max_close_rel_error,
            "max_volume_rel_error": self.max_volume_rel_error,
            "passed_basic_qa": self.passed_basic_qa,
        }


def _key(record: NormalizedBarRecord) -> tuple[str, str]:
    return record.asset.key, record.bar.event_time.date().isoformat()


def _render_key(key: tuple[str, str]) -> str:
    return f"{key[0]}@{key[1]}"


def _relative_error(left: float, right: float) -> float:
    denominator = max(abs(right), 1e-12)
    return abs(left - right) / denominator


def compare_provider_records(
    left_provider: str,
    left: Sequence[NormalizedBarRecord],
    right_provider: str,
    right: Sequence[NormalizedBarRecord],
) -> ProviderDiffReport:
    """Compare already-normalized evidence without silently reconciling providers."""

    left_map = {_key(record): record for record in left}
    right_map = {_key(record): record for record in right}
    if len(left_map) != len(left):
        raise ValueError("left provider records contain duplicate canonical keys")
    if len(right_map) != len(right):
        raise ValueError("right provider records contain duplicate canonical keys")

    left_keys = set(left_map)
    right_keys = set(right_map)
    common = sorted(left_keys & right_keys)
    close_abs = 0.0
    close_rel = 0.0
    volume_rel = 0.0
    for key in common:
        lbar = left_map[key].bar
        rbar = right_map[key].bar
        close_abs = max(close_abs, abs(lbar.close - rbar.close))
        close_rel = max(close_rel, _relative_error(lbar.close, rbar.close))
        volume_rel = max(volume_rel, _relative_error(lbar.volume, rbar.volume))

    values = (close_abs, close_rel, volume_rel)
    if not all(isfinite(value) for value in values):
        raise ValueError("provider diff produced non-finite error metrics")

    return ProviderDiffReport(
        left_provider=left_provider.strip().lower(),
        right_provider=right_provider.strip().lower(),
        common_rows=len(common),
        missing_left=tuple(_render_key(key) for key in sorted(right_keys - left_keys)),
        missing_right=tuple(_render_key(key) for key in sorted(left_keys - right_keys)),
        max_close_abs_error=close_abs,
        max_close_rel_error=close_rel,
        max_volume_rel_error=volume_rel,
    )

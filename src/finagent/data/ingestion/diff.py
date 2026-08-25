from __future__ import annotations

from dataclasses import dataclass
from math import isclose

from .base import NormalizedBarRecord


@dataclass(frozen=True, slots=True)
class ProviderDiffReport:
    left_provider: str
    right_provider: str
    common_rows: int
    missing_left: tuple[str, ...]
    missing_right: tuple[str, ...]
    close_mismatches: int
    volume_mismatches: int
    max_close_abs_error: float
    max_close_rel_error: float

    @property
    def passed(self) -> bool:
        return not self.missing_left and not self.missing_right and self.close_mismatches == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "left_provider": self.left_provider,
            "right_provider": self.right_provider,
            "passed": self.passed,
            "common_rows": self.common_rows,
            "missing_left": list(self.missing_left),
            "missing_right": list(self.missing_right),
            "close_mismatches": self.close_mismatches,
            "volume_mismatches": self.volume_mismatches,
            "max_close_abs_error": self.max_close_abs_error,
            "max_close_rel_error": self.max_close_rel_error,
        }


def _key(record: NormalizedBarRecord) -> tuple[str, str]:
    return record.asset.symbol, record.bar.event_time.date().isoformat()


def compare_provider_records(
    left_provider: str,
    left: tuple[NormalizedBarRecord, ...] | list[NormalizedBarRecord],
    right_provider: str,
    right: tuple[NormalizedBarRecord, ...] | list[NormalizedBarRecord],
    *,
    close_abs_tolerance: float = 1e-8,
    close_rel_tolerance: float = 1e-8,
    volume_rel_tolerance: float = 1e-6,
) -> ProviderDiffReport:
    """Compare normalized providers on canonical symbol/session keys.

    Venue identity is intentionally excluded from the comparison key because vendors may
    encode listing/execution venues differently. Symbol mapping must happen before this
    stage; a missing session remains explicit evidence rather than an automatic fallback.
    """

    left_map = {_key(record): record for record in left}
    right_map = {_key(record): record for record in right}
    left_keys = set(left_map)
    right_keys = set(right_map)
    common = sorted(left_keys & right_keys)
    missing_left = tuple(f"{symbol}@{day}" for symbol, day in sorted(right_keys - left_keys))
    missing_right = tuple(f"{symbol}@{day}" for symbol, day in sorted(left_keys - right_keys))

    close_mismatches = 0
    volume_mismatches = 0
    max_abs = 0.0
    max_rel = 0.0
    for key in common:
        lhs = left_map[key].bar
        rhs = right_map[key].bar
        abs_error = abs(lhs.close - rhs.close)
        denominator = max(abs(lhs.close), abs(rhs.close), 1e-12)
        rel_error = abs_error / denominator
        max_abs = max(max_abs, abs_error)
        max_rel = max(max_rel, rel_error)
        if not isclose(
            lhs.close,
            rhs.close,
            rel_tol=close_rel_tolerance,
            abs_tol=close_abs_tolerance,
        ):
            close_mismatches += 1
        if not isclose(lhs.volume, rhs.volume, rel_tol=volume_rel_tolerance, abs_tol=0.0):
            volume_mismatches += 1

    return ProviderDiffReport(
        left_provider=left_provider,
        right_provider=right_provider,
        common_rows=len(common),
        missing_left=missing_left,
        missing_right=missing_right,
        close_mismatches=close_mismatches,
        volume_mismatches=volume_mismatches,
        max_close_abs_error=max_abs,
        max_close_rel_error=max_rel,
    )

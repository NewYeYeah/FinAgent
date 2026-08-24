from __future__ import annotations

import math
from datetime import datetime
from types import MappingProxyType
from typing import Mapping, TypeVar

K = TypeVar("K")
V = TypeVar("V")


def require_non_empty(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string")
    return normalized


def require_finite(value: float, field_name: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite, got {value!r}")
    return value


def require_non_negative(value: float, field_name: str) -> float:
    value = require_finite(value, field_name)
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0, got {value}")
    return value


def require_positive(value: float, field_name: str) -> float:
    value = require_finite(value, field_name)
    if value <= 0:
        raise ValueError(f"{field_name} must be > 0, got {value}")
    return value


def require_aware_datetime(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def freeze_mapping(mapping: Mapping[K, V] | None) -> Mapping[K, V]:
    """Return a defensive, read-only shallow copy suitable for frozen dataclasses."""

    return MappingProxyType(dict(mapping or {}))

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from enum import Enum

from ._validation import require_positive


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


class LabelMetric(str, Enum):
    SIMPLE_RETURN = "simple_return"
    LOG_RETURN = "log_return"


class LabelHorizonUnit(str, Enum):
    TRADING_MINUTES = "trading_minutes"
    BARS = "bars"
    TRADING_DAYS = "trading_days"


class ResearchPriceBasis(str, Enum):
    RAW = "raw"
    SPLIT_ADJUSTED = "split_adjusted"
    TOTAL_RETURN_ADJUSTED = "total_return_adjusted"


class AvailabilityPolicy(str, Enum):
    AVAILABLE_AT = "available_at"
    EVENT_TIME = "event_time"


@dataclass(frozen=True, slots=True)
class LabelSpec:
    metric: LabelMetric
    horizon: int
    horizon_unit: LabelHorizonUnit
    allow_cross_session: bool
    price_basis: ResearchPriceBasis
    availability_policy: AvailabilityPolicy = AvailabilityPolicy.AVAILABLE_AT
    name: str = ""
    schema_version: str = "finagent.label-spec.v1"

    def __post_init__(self) -> None:
        if self.horizon < 1:
            raise ValueError("label horizon must be >= 1")
        if self.horizon_unit is LabelHorizonUnit.TRADING_DAYS and not self.allow_cross_session:
            raise ValueError("trading-day labels require allow_cross_session=true")
        object.__setattr__(self, "name", self.name.strip())

    @property
    def label_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "metric": self.metric.value,
            "horizon": self.horizon,
            "horizon_unit": self.horizon_unit.value,
            "allow_cross_session": self.allow_cross_session,
            "price_basis": self.price_basis.value,
            "availability_policy": self.availability_policy.value,
            "name": self.name,
        }
        return _canonical_hash(payload, prefix="label-spec")

    def validate_target_session(
        self,
        source_session_date: date,
        target_session_date: date,
    ) -> None:
        if not self.allow_cross_session and target_session_date != source_session_date:
            raise ValueError(
                "label target crosses session boundary while allow_cross_session=false"
            )
        if target_session_date < source_session_date:
            raise ValueError("label target session cannot precede source session")

    def compute(self, start_price: float, end_price: float) -> float:
        start = require_positive(start_price, "start_price")
        end = require_positive(end_price, "end_price")
        if self.metric is LabelMetric.SIMPLE_RETURN:
            return end / start - 1.0
        if self.metric is LabelMetric.LOG_RETURN:
            return math.log(end / start)
        raise ValueError(f"unsupported label metric {self.metric!r}")  # pragma: no cover

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "label_id": self.label_id,
            "metric": self.metric.value,
            "horizon": self.horizon,
            "horizon_unit": self.horizon_unit.value,
            "allow_cross_session": self.allow_cross_session,
            "price_basis": self.price_basis.value,
            "availability_policy": self.availability_policy.value,
            "name": self.name,
        }

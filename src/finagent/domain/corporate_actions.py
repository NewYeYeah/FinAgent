from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ._validation import (
    require_aware_datetime,
    require_non_empty,
    require_positive,
)


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


class CorporateActionEventType(str, Enum):
    SPLIT = "split"
    CASH_DIVIDEND = "cash_dividend"
    CASH_EVENT = "cash_event"


@dataclass(frozen=True, slots=True)
class CorporateActionEvent:
    event_id: str
    asset: str
    action_type: CorporateActionEventType
    effective_at: datetime
    available_at: datetime
    source: str
    source_revision: str
    split_ratio: float | None = None
    cash_amount: float | None = None
    currency: str = "USD"
    schema_version: str = "finagent.corporate-action-event.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", require_non_empty(self.event_id, "event_id"))
        object.__setattr__(self, "asset", require_non_empty(self.asset, "asset"))
        object.__setattr__(
            self,
            "effective_at",
            require_aware_datetime(self.effective_at, "effective_at"),
        )
        object.__setattr__(
            self,
            "available_at",
            require_aware_datetime(self.available_at, "available_at"),
        )
        object.__setattr__(self, "source", require_non_empty(self.source, "source"))
        object.__setattr__(
            self,
            "source_revision",
            require_non_empty(self.source_revision, "source_revision"),
        )
        object.__setattr__(self, "currency", require_non_empty(self.currency, "currency").upper())

        if self.action_type is CorporateActionEventType.SPLIT:
            if self.split_ratio is None:
                raise ValueError("split event requires split_ratio")
            ratio = require_positive(self.split_ratio, "split_ratio")
            if abs(ratio - 1.0) <= 1e-15:
                raise ValueError("split_ratio must differ from 1")
            if self.cash_amount not in (None, 0.0):
                raise ValueError("split event cannot carry cash_amount")
            object.__setattr__(self, "split_ratio", ratio)
            object.__setattr__(self, "cash_amount", None)
        else:
            if self.split_ratio is not None:
                raise ValueError("cash event cannot carry split_ratio")
            if self.cash_amount is None:
                raise ValueError("cash event requires cash_amount")
            object.__setattr__(
                self,
                "cash_amount",
                require_positive(self.cash_amount, "cash_amount"),
            )

    @property
    def split_price_factor(self) -> float | None:
        if self.action_type is not CorporateActionEventType.SPLIT:
            return None
        assert self.split_ratio is not None
        return 1.0 / self.split_ratio

    def known_by(self, asof: datetime) -> bool:
        return require_aware_datetime(asof, "asof") >= self.available_at

    @property
    def evidence_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "asset": self.asset,
            "action_type": self.action_type.value,
            "effective_at": self.effective_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "source": self.source,
            "source_revision": self.source_revision,
            "split_ratio": self.split_ratio,
            "cash_amount": self.cash_amount,
            "currency": self.currency,
        }
        return _canonical_hash(payload, prefix="corporate-action")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id,
            "event_id": self.event_id,
            "asset": self.asset,
            "action_type": self.action_type.value,
            "effective_at": self.effective_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "source": self.source,
            "source_revision": self.source_revision,
            "split_ratio": self.split_ratio,
            "cash_amount": self.cash_amount,
            "currency": self.currency,
        }

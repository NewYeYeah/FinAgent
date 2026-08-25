from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping

import numpy as np

from finagent.domain._validation import (
    freeze_mapping,
    require_aware_datetime,
    require_finite,
    require_non_empty,
    require_non_negative,
    require_positive,
)
from finagent.domain.assets import AssetId
from finagent.domain.execution import Fill
from finagent.domain.orders import OrderSide


class BrokerOrderStatus(str, Enum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {
            BrokerOrderStatus.FILLED,
            BrokerOrderStatus.REJECTED,
            BrokerOrderStatus.CANCELLED,
        }


@dataclass(frozen=True, slots=True)
class PaperOrder:
    client_order_id: str
    asset: AssetId
    side: OrderSide
    quantity: float
    submitted_at: datetime
    updated_at: datetime
    status: BrokerOrderStatus = BrokerOrderStatus.NEW
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    commission: float = 0.0
    rejection_reason: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "client_order_id", require_non_empty(self.client_order_id, "client_order_id"))
        object.__setattr__(self, "quantity", require_positive(self.quantity, "quantity"))
        object.__setattr__(self, "submitted_at", require_aware_datetime(self.submitted_at, "submitted_at"))
        object.__setattr__(self, "updated_at", require_aware_datetime(self.updated_at, "updated_at"))
        if self.updated_at < self.submitted_at:
            raise ValueError("updated_at cannot precede submitted_at")
        filled = require_non_negative(self.filled_quantity, "filled_quantity")
        if filled > self.quantity + 1e-12:
            raise ValueError("filled_quantity cannot exceed quantity")
        avg = require_non_negative(self.average_fill_price, "average_fill_price")
        commission = require_non_negative(self.commission, "commission")
        if filled <= 1e-15 and avg != 0.0:
            raise ValueError("average_fill_price must be zero before any fill")
        if filled > 1e-15 and avg <= 0:
            raise ValueError("average_fill_price must be positive after a fill")
        if self.status is BrokerOrderStatus.NEW and filled > 1e-15:
            raise ValueError("NEW order cannot carry fills")
        if self.status is BrokerOrderStatus.PARTIALLY_FILLED and not (0 < filled < self.quantity):
            raise ValueError("PARTIALLY_FILLED requires 0 < filled_quantity < quantity")
        if self.status is BrokerOrderStatus.FILLED and abs(filled - self.quantity) > 1e-10:
            raise ValueError("FILLED requires filled_quantity == quantity")
        reason = self.rejection_reason.strip()
        if self.status is BrokerOrderStatus.REJECTED and not reason:
            raise ValueError("REJECTED order requires rejection_reason")
        if self.status is not BrokerOrderStatus.REJECTED and reason:
            raise ValueError("only REJECTED orders may carry rejection_reason")
        object.__setattr__(self, "filled_quantity", filled)
        object.__setattr__(self, "average_fill_price", avg)
        object.__setattr__(self, "commission", commission)
        object.__setattr__(self, "rejection_reason", reason)
        object.__setattr__(self, "metadata", freeze_mapping(self.metadata))

    @property
    def remaining_quantity(self) -> float:
        return max(self.quantity - self.filled_quantity, 0.0)


@dataclass(frozen=True, slots=True)
class PaperBrokerCycle:
    asof: datetime
    fills: tuple[Fill, ...]
    order_ids: tuple[str, ...]
    account_nav: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "asof", require_aware_datetime(self.asof, "asof"))
        if not np.isfinite(self.account_nav):
            raise ValueError("account_nav must be finite")


class ReconciliationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class ReconciliationIssue:
    code: str
    severity: ReconciliationSeverity
    message: str
    asset: AssetId | None = None
    expected: float | None = None
    actual: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", require_non_empty(self.code, "code"))
        object.__setattr__(self, "message", require_non_empty(self.message, "message"))
        if self.expected is not None:
            object.__setattr__(self, "expected", require_finite(self.expected, "expected"))
        if self.actual is not None:
            object.__setattr__(self, "actual", require_finite(self.actual, "actual"))


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    asof: datetime
    issues: tuple[ReconciliationIssue, ...]
    cash_difference: float
    nav_difference: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "asof", require_aware_datetime(self.asof, "asof"))
        object.__setattr__(self, "cash_difference", require_finite(self.cash_difference, "cash_difference"))
        object.__setattr__(self, "nav_difference", require_finite(self.nav_difference, "nav_difference"))

    @property
    def critical_count(self) -> int:
        return sum(issue.severity is ReconciliationSeverity.CRITICAL for issue in self.issues)

    @property
    def ok(self) -> bool:
        return not self.issues


class KillSwitchStatus(str, Enum):
    ARMED = "armed"
    HALTED = "halted"


@dataclass(frozen=True, slots=True)
class KillSwitchSnapshot:
    status: KillSwitchStatus
    updated_at: datetime
    reasons: tuple[str, ...] = ()
    actor: str = "system"

    def __post_init__(self) -> None:
        object.__setattr__(self, "updated_at", require_aware_datetime(self.updated_at, "updated_at"))
        object.__setattr__(self, "actor", require_non_empty(self.actor, "actor"))
        normalized = tuple(require_non_empty(reason, "kill-switch reason") for reason in self.reasons)
        if self.status is KillSwitchStatus.HALTED and not normalized:
            raise ValueError("HALTED kill switch requires at least one reason")
        if self.status is KillSwitchStatus.ARMED and normalized:
            raise ValueError("ARMED kill switch cannot carry halt reasons")
        object.__setattr__(self, "reasons", normalized)


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    approved: bool
    checked_at: datetime
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "checked_at", require_aware_datetime(self.checked_at, "checked_at"))
        normalized = tuple(require_non_empty(reason, "safety reason") for reason in self.reasons)
        if self.approved and normalized:
            raise ValueError("approved safety decision cannot carry reasons")
        if not self.approved and not normalized:
            raise ValueError("rejected safety decision requires reasons")
        object.__setattr__(self, "reasons", normalized)


class CorporateActionType(str, Enum):
    SPLIT = "split"
    CASH_DIVIDEND = "cash_dividend"


@dataclass(frozen=True, slots=True)
class CorporateAction:
    action_id: str
    asset: AssetId
    action_type: CorporateActionType
    effective_at: datetime
    ratio: float = 1.0
    cash_amount: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_id", require_non_empty(self.action_id, "action_id"))
        object.__setattr__(self, "effective_at", require_aware_datetime(self.effective_at, "effective_at"))
        object.__setattr__(self, "ratio", require_positive(self.ratio, "ratio"))
        object.__setattr__(self, "cash_amount", require_non_negative(self.cash_amount, "cash_amount"))
        if self.action_type is CorporateActionType.SPLIT and self.cash_amount != 0.0:
            raise ValueError("split cannot carry cash_amount")
        if self.action_type is CorporateActionType.CASH_DIVIDEND and self.cash_amount <= 0:
            raise ValueError("cash dividend requires cash_amount > 0")


@dataclass(frozen=True, slots=True)
class HumanApproval:
    approval_id: str
    request_type: str
    snapshot_id: str
    approved_by: str
    approved_at: datetime
    policy_id: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_id", require_non_empty(self.approval_id, "approval_id"))
        object.__setattr__(self, "request_type", require_non_empty(self.request_type, "request_type"))
        object.__setattr__(self, "snapshot_id", require_non_empty(self.snapshot_id, "snapshot_id"))
        object.__setattr__(self, "approved_by", require_non_empty(self.approved_by, "approved_by"))
        object.__setattr__(self, "approved_at", require_aware_datetime(self.approved_at, "approved_at"))
        object.__setattr__(self, "policy_id", self.policy_id.strip())
        object.__setattr__(self, "reason", self.reason.strip())


@dataclass(frozen=True, slots=True)
class OperationalApplication:
    approval_id: str
    request_type: str
    snapshot_id: str
    applied_at: datetime
    applied_by: str
    policy_id: str = ""
    mutation_performed: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_id", require_non_empty(self.approval_id, "approval_id"))
        object.__setattr__(self, "request_type", require_non_empty(self.request_type, "request_type"))
        object.__setattr__(self, "snapshot_id", require_non_empty(self.snapshot_id, "snapshot_id"))
        object.__setattr__(self, "applied_at", require_aware_datetime(self.applied_at, "applied_at"))
        object.__setattr__(self, "applied_by", require_non_empty(self.applied_by, "applied_by"))
        object.__setattr__(self, "policy_id", self.policy_id.strip())


@dataclass(frozen=True, slots=True)
class ShadowComparison:
    asof: datetime
    primary_source: str
    shadow_source: str
    max_abs_weight_difference: float
    active_turnover: float
    cosine_similarity: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "asof", require_aware_datetime(self.asof, "asof"))
        object.__setattr__(self, "primary_source", require_non_empty(self.primary_source, "primary_source"))
        object.__setattr__(self, "shadow_source", require_non_empty(self.shadow_source, "shadow_source"))
        for name in ("max_abs_weight_difference", "active_turnover", "cosine_similarity"):
            value = require_finite(getattr(self, name), name)
            object.__setattr__(self, name, value)
        if self.max_abs_weight_difference < 0 or self.active_turnover < 0:
            raise ValueError("shadow distance metrics must be >= 0")


@dataclass(frozen=True, slots=True)
class ExecutionCostCalibration:
    fill_count: int
    notional: float
    weighted_slippage_bps: float
    weighted_commission_bps: float
    weighted_participation_rate: float

    def __post_init__(self) -> None:
        if self.fill_count < 1:
            raise ValueError("fill_count must be >= 1")
        for name in (
            "notional",
            "weighted_slippage_bps",
            "weighted_commission_bps",
            "weighted_participation_rate",
        ):
            value = require_non_negative(getattr(self, name), name)
            object.__setattr__(self, name, value)

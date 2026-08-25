from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from finagent.domain.execution import ExecutionSnapshot
from finagent.domain.orders import OrderIntent
from finagent.domain.portfolio import PortfolioState

from .domain import KillSwitchSnapshot, KillSwitchStatus, ReconciliationReport, SafetyDecision


class KillSwitchStore(Protocol):
    def get_kill_switch(self) -> KillSwitchSnapshot: ...
    def set_kill_switch(self, snapshot: KillSwitchSnapshot) -> None: ...


@dataclass(frozen=True, slots=True)
class TradingSafetyLimits:
    max_order_notional: float = 100_000.0
    max_batch_notional: float = 500_000.0
    max_daily_loss_fraction: float = 0.05
    max_critical_reconciliation_issues: int = 0

    def __post_init__(self) -> None:
        if self.max_order_notional <= 0 or self.max_batch_notional <= 0:
            raise ValueError("notional limits must be > 0")
        if not 0 <= self.max_daily_loss_fraction < 1:
            raise ValueError("max_daily_loss_fraction must be in [0, 1)")
        if self.max_critical_reconciliation_issues < 0:
            raise ValueError("max_critical_reconciliation_issues must be >= 0")


class TradingSafetyController:
    def __init__(self, *, store: KillSwitchStore, limits: TradingSafetyLimits | None = None) -> None:
        self.store = store
        self.limits = limits or TradingSafetyLimits()

    def evaluate(
        self,
        *,
        orders: tuple[OrderIntent, ...],
        snapshot: ExecutionSnapshot,
        account: PortfolioState,
        session_start_nav: float,
        reconciliation: ReconciliationReport | None = None,
    ) -> SafetyDecision:
        switch = self.store.get_kill_switch()
        reasons: list[str] = []
        if switch.status is KillSwitchStatus.HALTED:
            reasons.append("kill_switch_halted")
        if session_start_nav <= 0:
            reasons.append("invalid_session_start_nav")
        else:
            loss_fraction = max((session_start_nav - account.nav) / session_start_nav, 0.0)
            if loss_fraction > self.limits.max_daily_loss_fraction:
                reasons.append("daily_loss_limit")
        batch_notional = 0.0
        for order in orders:
            try:
                notional = order.quantity * snapshot.price(order.asset)
            except KeyError:
                reasons.append(f"missing_execution_quote:{order.asset.key}")
                continue
            batch_notional += notional
            if notional > self.limits.max_order_notional:
                reasons.append(f"order_notional_limit:{order.client_order_id}")
        if batch_notional > self.limits.max_batch_notional:
            reasons.append("batch_notional_limit")
        if reconciliation is not None and reconciliation.critical_count > self.limits.max_critical_reconciliation_issues:
            reasons.append("reconciliation_critical")
        if reasons:
            return SafetyDecision(False, snapshot.asof, tuple(dict.fromkeys(reasons)))
        return SafetyDecision(True, snapshot.asof)

    def trip(self, *, at: datetime, reason: str, actor: str = "system") -> KillSwitchSnapshot:
        snapshot = KillSwitchSnapshot(KillSwitchStatus.HALTED, at, (reason,), actor)
        self.store.set_kill_switch(snapshot)
        return snapshot

    def reset(self, *, at: datetime, actor: str) -> KillSwitchSnapshot:
        snapshot = KillSwitchSnapshot(KillSwitchStatus.ARMED, at, (), actor)
        self.store.set_kill_switch(snapshot)
        return snapshot

from __future__ import annotations

from dataclasses import dataclass

from finagent.domain.execution import ExecutionSnapshot
from finagent.domain.orders import OrderIntent
from finagent.domain.portfolio import PortfolioState

from .domain import PaperBrokerCycle, ReconciliationReport, SafetyDecision
from .paper import PaperBroker
from .reconciliation import PortfolioReconciler
from .safety import TradingSafetyController
from .store import SQLitePaperBrokerStore


@dataclass(frozen=True, slots=True)
class PaperTradingValidation:
    safety: SafetyDecision
    cycle: PaperBrokerCycle | None = None
    reconciliation: ReconciliationReport | None = None


class ApprovedPaperTradingController:
    """Paper-trading application path downstream of human Supervisor approval."""

    def __init__(
        self,
        *,
        broker: PaperBroker,
        store: SQLitePaperBrokerStore,
        safety: TradingSafetyController,
        reconciler: PortfolioReconciler | None = None,
    ) -> None:
        self.broker = broker
        self.store = store
        self.safety = safety
        self.reconciler = reconciler or PortfolioReconciler()

    def execute_rebalance(
        self,
        *,
        snapshot_id: str,
        approval_id: str,
        orders: tuple[OrderIntent, ...],
        execution_snapshot: ExecutionSnapshot,
        session_start_nav: float,
    ) -> PaperTradingValidation:
        registered = self.store.rebalance_approval_id(snapshot_id)
        if registered != approval_id:
            raise PermissionError("paper rebalance requires the exact registered human approval")
        account = self.broker.account()
        decision = self.safety.evaluate(
            orders=orders,
            snapshot=execution_snapshot,
            account=account,
            session_start_nav=session_start_nav,
        )
        if not decision.approved:
            self.store.record_event(
                "paper_cycle_blocked",
                execution_snapshot.asof,
                {"snapshot_id": snapshot_id, "reasons": list(decision.reasons)},
            )
            return PaperTradingValidation(decision)
        self.broker.submit(orders)
        cycle = self.broker.process(execution_snapshot)
        return PaperTradingValidation(decision, cycle)

    def reconcile(self, *, expected: PortfolioState, at_snapshot_id: str) -> ReconciliationReport:
        actual = self.broker.account()
        report = self.reconciler.reconcile(expected, actual)
        self.store.record_event(
            "reconciliation",
            actual.asof,
            {
                "snapshot_id": at_snapshot_id,
                "critical_count": report.critical_count,
                "issue_codes": [issue.code for issue in report.issues],
                "cash_difference": report.cash_difference,
                "nav_difference": report.nav_difference,
            },
        )
        if report.critical_count:
            self.safety.trip(
                at=actual.asof,
                reason=f"reconciliation critical issues: {report.critical_count}",
                actor="paper-trading-controller",
            )
        return report

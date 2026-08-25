from __future__ import annotations

from dataclasses import dataclass

from finagent.domain.portfolio import PortfolioState

from .domain import ReconciliationIssue, ReconciliationReport, ReconciliationSeverity


@dataclass(frozen=True, slots=True)
class PortfolioReconciler:
    cash_tolerance: float = 1e-6
    position_tolerance: float = 1e-8
    mark_tolerance: float = 1e-8
    nav_tolerance: float = 1e-6

    def __post_init__(self) -> None:
        if min(self.cash_tolerance, self.position_tolerance, self.mark_tolerance, self.nav_tolerance) < 0:
            raise ValueError("reconciliation tolerances must be >= 0")

    def reconcile(self, expected: PortfolioState, actual: PortfolioState) -> ReconciliationReport:
        if expected.base_currency != actual.base_currency:
            raise ValueError("expected and actual accounts must share base_currency")
        if expected.asof != actual.asof:
            raise ValueError("expected and actual accounts must share asof")
        issues: list[ReconciliationIssue] = []
        cash_diff = actual.cash - expected.cash
        if abs(cash_diff) > self.cash_tolerance:
            issues.append(
                ReconciliationIssue(
                    "CASH_MISMATCH",
                    ReconciliationSeverity.CRITICAL,
                    "paper-broker cash differs from deterministic ledger",
                    expected=expected.cash,
                    actual=actual.cash,
                )
            )
        assets = sorted(set(expected.positions) | set(actual.positions))
        for asset in assets:
            expected_qty = expected.positions.get(asset, 0.0)
            actual_qty = actual.positions.get(asset, 0.0)
            if abs(actual_qty - expected_qty) > self.position_tolerance:
                issues.append(
                    ReconciliationIssue(
                        "POSITION_MISMATCH",
                        ReconciliationSeverity.CRITICAL,
                        "paper-broker position differs from deterministic ledger",
                        asset=asset,
                        expected=expected_qty,
                        actual=actual_qty,
                    )
                )
            if expected_qty != 0.0 and actual_qty != 0.0:
                expected_mark = expected.marks[asset]
                actual_mark = actual.marks[asset]
                if abs(actual_mark - expected_mark) > self.mark_tolerance:
                    issues.append(
                        ReconciliationIssue(
                            "MARK_MISMATCH",
                            ReconciliationSeverity.WARNING,
                            "paper-broker mark differs from deterministic ledger",
                            asset=asset,
                            expected=expected_mark,
                            actual=actual_mark,
                        )
                    )
        nav_diff = actual.nav - expected.nav
        if abs(nav_diff) > self.nav_tolerance and not any(
            issue.code in {"CASH_MISMATCH", "POSITION_MISMATCH"} for issue in issues
        ):
            issues.append(
                ReconciliationIssue(
                    "NAV_MISMATCH",
                    ReconciliationSeverity.WARNING,
                    "paper-broker NAV differs from deterministic ledger",
                    expected=expected.nav,
                    actual=actual.nav,
                )
            )
        return ReconciliationReport(
            asof=actual.asof,
            issues=tuple(issues),
            cash_difference=cash_diff,
            nav_difference=nav_diff,
        )

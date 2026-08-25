from __future__ import annotations

from dataclasses import dataclass

from finagent.domain.portfolio import PortfolioState

from .domain import CorporateAction, CorporateActionType


@dataclass(frozen=True, slots=True)
class CorporateActionProcessor:
    zero_tolerance: float = 1e-12

    def __post_init__(self) -> None:
        if self.zero_tolerance < 0:
            raise ValueError("zero_tolerance must be >= 0")

    def apply(self, state: PortfolioState, action: CorporateAction) -> PortfolioState:
        if action.effective_at < state.asof:
            raise ValueError("corporate action cannot precede account state")
        positions = dict(state.positions)
        marks = dict(state.marks)
        cash = state.cash
        quantity = positions.get(action.asset, 0.0)

        if action.action_type is CorporateActionType.SPLIT:
            if abs(quantity) > self.zero_tolerance:
                positions[action.asset] = quantity * action.ratio
                marks[action.asset] = marks[action.asset] / action.ratio
        elif action.action_type is CorporateActionType.CASH_DIVIDEND:
            if abs(quantity) > self.zero_tolerance:
                cash += quantity * action.cash_amount
        else:  # pragma: no cover
            raise ValueError(f"unsupported corporate action {action.action_type}")

        return PortfolioState(
            asof=action.effective_at,
            base_currency=state.base_currency,
            cash=cash,
            positions=positions,
            marks=marks,
        )

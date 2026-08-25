from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from finagent.domain.execution import ExecutionReport
from finagent.domain.forecasts import AlphaForecast, RiskForecast
from finagent.domain.portfolio import PortfolioState, PortfolioTarget, RiskDecision, RiskStatus
from finagent.domain.research import ResearchDataset
from finagent.ports import (
    AlphaModel,
    DataAdapter,
    ExecutionDataAdapter,
    PortfolioOptimizer,
    RiskGate,
    RiskModel,
    TimedExecutionVenue,
)
from finagent.services.execution import AccountLedger, TimedSimulatedExchange
from finagent.services.portfolio import OrderPlanner


@dataclass(frozen=True, slots=True)
class TimedBacktestConfig:
    train_split: str = "train"
    test_split: str = "test"
    initial_cash: float = 1_000_000.0
    lookback: int = 60
    rebalance_every: int = 1
    execution_lag_events: int = 1
    execution_price_field: str = "open"
    annualization_factor: float = 252.0

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be > 0")
        if self.lookback <= 0 or self.rebalance_every <= 0:
            raise ValueError("lookback and rebalance_every must be >= 1")
        if self.execution_lag_events <= 0:
            raise ValueError("execution_lag_events must be >= 1")
        if self.execution_price_field not in {"open", "close"}:
            raise ValueError("execution_price_field must be 'open' or 'close'")
        if self.annualization_factor <= 0:
            raise ValueError("annualization_factor must be > 0")


@dataclass(frozen=True, slots=True)
class TimedBacktestPoint:
    information_at: datetime
    execution_at: datetime | None
    nav: float
    cash: float
    turnover: float
    transaction_cost: float
    target: PortfolioTarget | None = None
    risk_decision: RiskDecision | None = None
    execution: ExecutionReport | None = None

    def __post_init__(self) -> None:
        if self.execution_at is not None and self.execution_at <= self.information_at:
            raise ValueError("execution_at must be later than information_at")


@dataclass(frozen=True, slots=True)
class TimedBacktestResult:
    points: tuple[TimedBacktestPoint, ...]
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe: float
    max_drawdown: float
    total_turnover: float
    total_transaction_cost: float


class TimedEventDrivenBacktestEngine:
    """Phase 2 event-time engine separating information and execution clocks.

    Signals are formed using a PIT ``MarketSnapshot``/``FeatureWindow`` at
    ``information_at``.  Approved orders are executed only on a later field-level
    ``ExecutionSnapshot``.  The default convention is next executable bar open.
    """

    def __init__(
        self,
        adapter: DataAdapter,
        execution_adapter: ExecutionDataAdapter,
        *,
        config: TimedBacktestConfig | None = None,
        ledger: AccountLedger | None = None,
        planner: OrderPlanner | None = None,
        exchange: TimedExecutionVenue | None = None,
    ) -> None:
        self.adapter = adapter
        self.execution_adapter = execution_adapter
        self.config = config or TimedBacktestConfig()
        self.ledger = ledger or AccountLedger()
        self.planner = planner or OrderPlanner()
        self.exchange = exchange or TimedSimulatedExchange()
        if self.execution_adapter.data_version != self.adapter.data_version:
            raise ValueError("research and execution adapters must share data_version")

    @staticmethod
    def _ordered_union(*groups: tuple[str, ...]) -> tuple[str, ...]:
        result: list[str] = []
        for group in groups:
            for item in group:
                if item not in result:
                    result.append(item)
        return tuple(result)

    def _next_execution_time(
        self,
        information_at: datetime,
        universe,
        hard_end: datetime,
    ) -> datetime | None:
        # Start one microsecond after the information timestamp so same-instant
        # execution is impossible by construction.
        events = self.execution_adapter.execution_calendar(
            information_at + timedelta(microseconds=1),
            hard_end,
            universe,
            price_field=self.config.execution_price_field,
        )
        index = self.config.execution_lag_events - 1
        if len(events) <= index:
            return None
        return events[index]

    def run(
        self,
        dataset: ResearchDataset,
        alpha_model: AlphaModel,
        risk_model: RiskModel,
        optimizer: PortfolioOptimizer,
        risk_gate: RiskGate,
    ) -> TimedBacktestResult:
        if not dataset.point_in_time:
            raise ValueError("backtest requires a point-in-time dataset")
        alpha_model.fit(dataset, split=self.config.train_split)
        risk_model.fit(dataset, split=self.config.train_split)
        test_panel = dataset.get_split(self.config.test_split)
        required_features = self._ordered_union(
            alpha_model.required_features, risk_model.required_features
        )
        lookback = max(self.config.lookback, alpha_model.min_lookback, risk_model.min_lookback)

        first_snapshot = self.adapter.market_snapshot(test_panel.timestamps[0], dataset.universe)
        state = PortfolioState(
            asof=first_snapshot.asof,
            base_currency=dataset.universe[0].currency,
            cash=self.config.initial_cash,
            positions={},
            marks={},
        )
        points: list[TimedBacktestPoint] = []
        # Execution may use a later bar inside the declared test range, but the final
        # information point cannot open a position whose holding return is outside
        # the evaluation panel.
        hard_end = dataset.splits[self.config.test_split].end

        for step, information_at in enumerate(test_panel.timestamps):
            decision_snapshot = self.adapter.market_snapshot(information_at, dataset.universe)
            state = self.ledger.mark_to_market(state, decision_snapshot)
            target = None
            decision = None
            execution = None
            execution_at = None
            turnover = 0.0
            transaction_cost = 0.0

            if step % self.config.rebalance_every == 0 and step < len(test_panel.timestamps) - 1:
                window = self.adapter.feature_window(
                    asof=information_at,
                    universe=dataset.universe,
                    features=required_features,
                    lookback=lookback,
                )
                alpha: AlphaForecast = alpha_model.predict(window)
                risk: RiskForecast = risk_model.predict(window)
                target = optimizer.optimize(alpha, risk, state)
                decision = risk_gate.assess(target, state, decision_snapshot)
                if decision.status is RiskStatus.APPROVE:
                    orders = self.planner.plan(target, state, decision_snapshot, decision)
                    execution_at = self._next_execution_time(
                        information_at, dataset.universe, hard_end
                    )
                    if execution_at is not None and orders:
                        execution_snapshot = self.execution_adapter.execution_snapshot(
                            execution_at,
                            dataset.universe,
                            price_field=self.config.execution_price_field,
                        )
                        pre_trade_nav = state.nav
                        execution = self.exchange.execute(orders, execution_snapshot)
                        state = self.ledger.apply_execution_snapshot(
                            state, execution, execution_snapshot
                        )
                        gross_notional = sum(fill.notional for fill in execution.fills)
                        turnover = gross_notional / pre_trade_nav if pre_trade_nav > 0 else 0.0
                        transaction_cost = sum(
                            fill.commission + fill.slippage for fill in execution.fills
                        )

            points.append(
                TimedBacktestPoint(
                    information_at=information_at,
                    execution_at=execution_at,
                    nav=state.nav,
                    cash=state.cash,
                    turnover=turnover,
                    transaction_cost=transaction_cost,
                    target=target,
                    risk_decision=decision,
                    execution=execution,
                )
            )

        return self._summarize(tuple(points))

    def _summarize(self, points: tuple[TimedBacktestPoint, ...]) -> TimedBacktestResult:
        if not points:
            raise ValueError("backtest produced no points")
        observed_nav = np.asarray([point.nav for point in points], dtype=float)
        if np.any(observed_nav <= 0):
            raise ValueError("backtest NAV must remain positive")
        # Include the transition from initial cash to the first evaluation point.
        # Otherwise the first execution cost and first marked holding return vanish
        # from every walk-forward fold.
        nav = np.concatenate(([self.config.initial_cash], observed_nav))
        returns = nav[1:] / nav[:-1] - 1.0
        total_return = float(nav[-1] / nav[0] - 1.0)
        annualized_return = float(
            (nav[-1] / nav[0]) ** (self.config.annualization_factor / len(returns)) - 1.0
        )
        if len(returns) > 1:
            std = float(np.std(returns, ddof=1))
            mean = float(np.mean(returns))
            annualized_volatility = std * np.sqrt(self.config.annualization_factor)
            sharpe = mean / std * np.sqrt(self.config.annualization_factor) if std > 0 else 0.0
        else:
            annualized_volatility = 0.0
            sharpe = 0.0
        running_max = np.maximum.accumulate(nav)
        drawdowns = nav / running_max - 1.0
        return TimedBacktestResult(
            points=points,
            total_return=total_return,
            annualized_return=annualized_return,
            annualized_volatility=float(annualized_volatility),
            sharpe=float(sharpe),
            max_drawdown=float(np.min(drawdowns)),
            total_turnover=float(sum(point.turnover for point in points)),
            total_transaction_cost=float(sum(point.transaction_cost for point in points)),
        )

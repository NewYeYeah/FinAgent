from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from finagent.domain.execution import ExecutionReport
from finagent.domain.forecasts import AlphaForecast, RiskForecast
from finagent.domain.portfolio import PortfolioState, PortfolioTarget, RiskDecision, RiskStatus
from finagent.domain.research import ResearchDataset
from finagent.ports import AlphaModel, DataAdapter, PortfolioOptimizer, RiskGate, RiskModel
from finagent.services.execution import AccountLedger, SimulatedExchange
from finagent.services.portfolio import OrderPlanner


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    test_split: str = "test"
    train_split: str = "train"
    initial_cash: float = 1_000_000.0
    lookback: int = 60
    rebalance_every: int = 1
    annualization_factor: float = 252.0

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be > 0")
        if self.lookback <= 0:
            raise ValueError("lookback must be >= 1")
        if self.rebalance_every <= 0:
            raise ValueError("rebalance_every must be >= 1")
        if self.annualization_factor <= 0:
            raise ValueError("annualization_factor must be > 0")


@dataclass(frozen=True, slots=True)
class BacktestPoint:
    asof: datetime
    nav: float
    cash: float
    turnover: float
    transaction_cost: float
    target: PortfolioTarget | None = None
    risk_decision: RiskDecision | None = None
    execution: ExecutionReport | None = None


@dataclass(frozen=True, slots=True)
class BacktestResult:
    points: tuple[BacktestPoint, ...]
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe: float
    max_drawdown: float
    total_turnover: float
    total_transaction_cost: float

    @property
    def nav(self) -> np.ndarray:
        return np.asarray([point.nav for point in self.points], dtype=float)


class EventDrivenBacktestEngine:
    """Phase 1 sequential out-of-sample backtest.

    Models are fitted only on ``train_split``. At each test timestamp the adapter
    materializes a PIT-safe feature window, forecasts are generated, the optimizer
    emits a target, a hard risk gate approves/rejects it, and orders are executed.

    Execution uses the already-observed snapshot close. This is an intentionally
    idealised close-on-close research convention: the new position only affects P&L
    after that timestamp. A next-bar/open execution model belongs in Phase 2 because
    OHLC fields require finer availability semantics than one bar-level timestamp.
    """

    def __init__(
        self,
        adapter: DataAdapter,
        *,
        config: BacktestConfig | None = None,
        ledger: AccountLedger | None = None,
        planner: OrderPlanner | None = None,
        exchange: SimulatedExchange | None = None,
    ) -> None:
        self.adapter = adapter
        self.config = config or BacktestConfig()
        self.ledger = ledger or AccountLedger()
        self.planner = planner or OrderPlanner()
        self.exchange = exchange or SimulatedExchange()

    @staticmethod
    def _ordered_union(*groups: tuple[str, ...]) -> tuple[str, ...]:
        result: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for item in group:
                if item not in seen:
                    seen.add(item)
                    result.append(item)
        return tuple(result)

    def run(
        self,
        dataset: ResearchDataset,
        alpha_model: AlphaModel,
        risk_model: RiskModel,
        optimizer: PortfolioOptimizer,
        risk_gate: RiskGate,
    ) -> BacktestResult:
        if not dataset.point_in_time:
            raise ValueError("backtest requires a point-in-time dataset")
        if dataset.metadata.get("data_version") not in {None, self.adapter.data_version}:
            raise ValueError("dataset data_version does not match DataAdapter")

        alpha_model.fit(dataset, split=self.config.train_split)
        risk_model.fit(dataset, split=self.config.train_split)
        test_panel = dataset.get_split(self.config.test_split)
        required_features = self._ordered_union(
            alpha_model.required_features,
            risk_model.required_features,
        )
        missing = set(required_features) - set(dataset.features)
        if missing:
            raise ValueError(f"dataset is missing model features: {sorted(missing)}")
        lookback = max(
            self.config.lookback,
            alpha_model.min_lookback,
            risk_model.min_lookback,
        )

        first_snapshot = self.adapter.market_snapshot(test_panel.timestamps[0], dataset.universe)
        state = PortfolioState(
            asof=first_snapshot.asof,
            base_currency=dataset.universe[0].currency,
            cash=self.config.initial_cash,
            positions={},
            marks={},
        )
        points: list[BacktestPoint] = []

        for step, asof in enumerate(test_panel.timestamps):
            snapshot = self.adapter.market_snapshot(asof, dataset.universe)
            state = self.ledger.mark_to_market(state, snapshot)
            target = None
            decision = None
            execution = None
            turnover = 0.0
            transaction_cost = 0.0

            if step % self.config.rebalance_every == 0:
                window = self.adapter.feature_window(
                    asof=asof,
                    universe=dataset.universe,
                    features=required_features,
                    lookback=lookback,
                )
                alpha: AlphaForecast = alpha_model.predict(window)
                risk: RiskForecast = risk_model.predict(window)
                target = optimizer.optimize(alpha, risk, state)
                decision = risk_gate.assess(target, state, snapshot)
                if decision.status is RiskStatus.APPROVE:
                    pre_trade_nav = state.nav
                    orders = self.planner.plan(target, state, snapshot, decision)
                    execution = self.exchange.execute(orders, snapshot)
                    state = self.ledger.apply_execution(state, execution, snapshot)
                    gross_notional = sum(fill.notional for fill in execution.fills)
                    turnover = gross_notional / pre_trade_nav if pre_trade_nav > 0 else 0.0
                    transaction_cost = sum(
                        fill.commission + fill.slippage for fill in execution.fills
                    )

            points.append(
                BacktestPoint(
                    asof=asof,
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

    def _summarize(self, points: tuple[BacktestPoint, ...]) -> BacktestResult:
        if not points:
            raise ValueError("backtest produced no points")
        nav = np.asarray([point.nav for point in points], dtype=float)
        if np.any(nav <= 0):
            raise ValueError("backtest NAV must remain positive")
        returns = nav[1:] / nav[:-1] - 1.0
        total_return = float(nav[-1] / nav[0] - 1.0) if len(nav) > 1 else 0.0
        if len(returns) > 0:
            periods = len(returns)
            annualized_return = float((nav[-1] / nav[0]) ** (self.config.annualization_factor / periods) - 1.0)
        else:
            annualized_return = 0.0
        if len(returns) > 1:
            mean = float(np.mean(returns))
            std = float(np.std(returns, ddof=1))
            annualized_volatility = std * np.sqrt(self.config.annualization_factor)
            sharpe = (
                mean / std * np.sqrt(self.config.annualization_factor)
                if std > 0
                else 0.0
            )
        else:
            annualized_volatility = 0.0
            sharpe = 0.0
        running_max = np.maximum.accumulate(nav)
        drawdowns = nav / running_max - 1.0
        max_drawdown = float(np.min(drawdowns))
        return BacktestResult(
            points=points,
            total_return=total_return,
            annualized_return=annualized_return,
            annualized_volatility=float(annualized_volatility),
            sharpe=float(sharpe),
            max_drawdown=max_drawdown,
            total_turnover=float(sum(point.turnover for point in points)),
            total_transaction_cost=float(sum(point.transaction_cost for point in points)),
        )

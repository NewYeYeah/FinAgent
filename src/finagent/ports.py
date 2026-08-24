from __future__ import annotations

from typing import Protocol

from .domain.execution import ExecutionReport
from .domain.experiments import ArtifactRef
from .domain.forecasts import AlphaForecast, RiskForecast
from .domain.market import MarketSnapshot
from .domain.orders import OrderIntent
from .domain.portfolio import PortfolioState, PortfolioTarget, RiskDecision
from .domain.research import ResearchDataset


class AlphaModel(Protocol):
    def fit(self, dataset: ResearchDataset) -> ArtifactRef: ...

    def predict(self, snapshot: MarketSnapshot) -> AlphaForecast: ...


class RiskModel(Protocol):
    def fit(self, dataset: ResearchDataset) -> ArtifactRef: ...

    def predict(self, snapshot: MarketSnapshot) -> RiskForecast: ...


class PortfolioOptimizer(Protocol):
    def optimize(
        self,
        alpha: AlphaForecast,
        risk: RiskForecast,
        state: PortfolioState,
    ) -> PortfolioTarget: ...


class RiskGate(Protocol):
    def assess(
        self,
        target: PortfolioTarget,
        state: PortfolioState,
        snapshot: MarketSnapshot,
    ) -> RiskDecision: ...


class ExecutionVenue(Protocol):
    def execute(
        self,
        orders: tuple[OrderIntent, ...],
        snapshot: MarketSnapshot,
    ) -> ExecutionReport: ...

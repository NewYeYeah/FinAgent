from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .domain.assets import AssetId
from .domain.execution import ExecutionReport
from .domain.experiments import ArtifactRef
from .domain.forecasts import AlphaForecast, RiskForecast
from .domain.market import MarketSnapshot
from .domain.orders import OrderIntent
from .domain.portfolio import PortfolioState, PortfolioTarget, RiskDecision
from .domain.research import DatasetRequest, FeatureWindow, ResearchDataset


class DataAdapter(Protocol):
    """Canonical Phase 1 data boundary.

    Adapters own vendor/file-specific schemas. Downstream code receives only typed
    domain objects and immutable NumPy panels.
    """

    @property
    def data_version(self) -> str: ...

    def build_dataset(self, request: DatasetRequest) -> ResearchDataset: ...

    def feature_window(
        self,
        asof: datetime,
        universe: tuple[AssetId, ...],
        features: tuple[str, ...],
        lookback: int,
    ) -> FeatureWindow: ...

    def market_snapshot(
        self,
        asof: datetime,
        universe: tuple[AssetId, ...],
    ) -> MarketSnapshot: ...

    def calendar(
        self,
        start: datetime,
        end: datetime,
        universe: tuple[AssetId, ...],
    ) -> tuple[datetime, ...]: ...


class AlphaModel(Protocol):
    @property
    def required_features(self) -> tuple[str, ...]: ...

    @property
    def min_lookback(self) -> int: ...

    def fit(self, dataset: ResearchDataset, split: str = "train") -> ArtifactRef: ...

    def predict(self, window: FeatureWindow) -> AlphaForecast: ...


class RiskModel(Protocol):
    @property
    def required_features(self) -> tuple[str, ...]: ...

    @property
    def min_lookback(self) -> int: ...

    def fit(self, dataset: ResearchDataset, split: str = "train") -> ArtifactRef: ...

    def predict(self, window: FeatureWindow) -> RiskForecast: ...


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

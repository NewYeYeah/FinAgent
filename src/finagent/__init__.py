"""FinAgent domain kernel.

Phase 0.5 intentionally contains no LLM, broker, dataframe, or external market-data
framework dependency. Third-party systems are expected to connect through adapters
in later phases.
"""

from .domain.assets import AssetId, AssetType
from .domain.execution import ExecutionReport, Fill, OrderRejection
from .domain.experiments import (
    ArtifactRef,
    ArtifactType,
    ExperimentResult,
    ExperimentRun,
    ExperimentRunStatus,
    ExperimentSpec,
)
from .domain.forecasts import AlphaForecast, ModelRef, RiskForecast
from .domain.market import MarketSnapshot, PriceBar
from .domain.orders import OrderIntent, OrderSide, OrderType
from .domain.portfolio import (
    PortfolioState,
    PortfolioTarget,
    RiskDecision,
    RiskStatus,
    RiskViolation,
)
from .domain.research import ResearchDataset, TimeRange

__all__ = [
    "AlphaForecast",
    "ArtifactRef",
    "ArtifactType",
    "AssetId",
    "AssetType",
    "ExecutionReport",
    "ExperimentResult",
    "ExperimentRun",
    "ExperimentRunStatus",
    "ExperimentSpec",
    "Fill",
    "MarketSnapshot",
    "ModelRef",
    "OrderIntent",
    "OrderRejection",
    "OrderSide",
    "OrderType",
    "PortfolioState",
    "PortfolioTarget",
    "PriceBar",
    "ResearchDataset",
    "RiskDecision",
    "RiskForecast",
    "RiskStatus",
    "RiskViolation",
    "TimeRange",
]

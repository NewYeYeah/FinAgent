from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from finagent.agents.generated_features import SQLiteGeneratedFeatureStore
from finagent.backtest.market_study import MarketStudyConfig
from finagent.domain._validation import require_aware_datetime, require_non_empty
from finagent.domain.experiments import ArtifactRef
from finagent.domain.forecasts import AlphaForecast, RiskForecast
from finagent.domain.model_registry import ModelStage, RegisteredModel
from finagent.domain.orders import OrderIntent
from finagent.domain.portfolio import PortfolioState, PortfolioTarget, RiskDecision
from finagent.domain.research import ResearchDataset
from finagent.models.alpha import GeneratedFeatureAlphaModel
from finagent.models.risk import GARCH11RiskModel
from finagent.portfolio import MeanVarianceConfig, MeanVarianceOptimizer
from finagent.research.final_strategy import FinalStrategySpec
from finagent.research.registry import SQLiteResearchRegistry
from finagent.services import OrderPlanner, StaticRiskGate


@dataclass(frozen=True, slots=True)
class PaperStrategyRuntimeConfig:
    """Operational-only controls for one PAPER planning cycle.

    Research/portfolio parameters are not configurable here. They are reconstructed
    from the frozen FinalStrategySpec so PAPER does not silently become a new strategy.
    """

    calibration_split: str = "train"
    min_order_notional: float = 0.0
    quantity_precision: int = 8

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "calibration_split",
            require_non_empty(self.calibration_split, "calibration_split"),
        )
        if self.min_order_notional < 0:
            raise ValueError("min_order_notional must be >= 0")
        if self.quantity_precision < 0:
            raise ValueError("quantity_precision must be >= 0")


@dataclass(frozen=True, slots=True)
class PaperStrategyPlan:
    """Non-mutating output of one deterministic PAPER strategy cycle."""

    model_id: str
    final_strategy_id: str
    program_id: str
    asof: datetime
    calibration_dataset_digest: str
    alpha_artifact: ArtifactRef
    risk_artifact: ArtifactRef
    alpha: AlphaForecast
    risk: RiskForecast
    marked_state: PortfolioState
    target: PortfolioTarget
    risk_decision: RiskDecision
    orders: tuple[OrderIntent, ...]
    execution_price_field: str = "open"

    def __post_init__(self) -> None:
        for name in ("model_id", "final_strategy_id", "program_id", "calibration_dataset_digest"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        object.__setattr__(self, "asof", require_aware_datetime(self.asof, "asof"))
        if self.execution_price_field != "open":
            raise ValueError("PAPER runtime currently preserves the frozen next-open protocol only")
        if not (
            self.alpha.asof
            == self.risk.asof
            == self.marked_state.asof
            == self.target.asof
            == self.asof
        ):
            raise ValueError("PAPER plan clocks are not aligned")


class PaperStrategyRuntime:
    """Recreate one frozen generated-feature strategy for supervised PAPER use.

    The runtime is deliberately non-mutating. It does not submit orders, promote model
    stages, choose a calibration window, or perform human approval. Its only job is to
    reconstruct the frozen numerical protocol from explicit PIT inputs and return an
    auditable plan for the existing operational approval/execution path.
    """

    IMPLEMENTATION = {
        "alpha_model": "GeneratedFeatureAlphaModel",
        "risk_model": "GARCH11RiskModel",
        "portfolio_optimizer": "MeanVarianceOptimizer",
        "risk_gate": "StaticRiskGate",
        "execution_engine": "TimedEventDrivenBacktestEngine",
        "execution_price_field": "open",
        "annualization_factor": 252.0,
    }

    def __init__(
        self,
        *,
        adapter,
        registry: SQLiteResearchRegistry,
        generated_feature_store: SQLiteGeneratedFeatureStore,
        config: PaperStrategyRuntimeConfig | None = None,
    ) -> None:
        self.adapter = adapter
        self.registry = registry
        self.generated_feature_store = generated_feature_store
        self.config = config or PaperStrategyRuntimeConfig()

    @staticmethod
    def _decode_protocol(strategy: FinalStrategySpec) -> tuple[MarketStudyConfig, str]:
        payload = json.loads(strategy.research_protocol_json)
        if payload.get("schema_version") != "finagent.final-strategy-protocol.v1":
            raise ValueError("unsupported final strategy protocol schema")
        if payload.get("implementation") != PaperStrategyRuntime.IMPLEMENTATION:
            raise ValueError("PAPER runtime implementation differs from frozen research protocol")
        agent = payload.get("agent_market")
        market_payload = payload.get("market")
        if not isinstance(agent, dict) or not isinstance(market_payload, dict):
            raise ValueError("final strategy protocol is missing agent_market/market configuration")
        label_name = str(agent.get("label_name", "")).strip()
        if not label_name:
            raise ValueError("final strategy protocol has no label_name")
        return MarketStudyConfig(**market_payload), label_name

    def _validate_model_identity(
        self,
        *,
        model_id: str,
        strategy: FinalStrategySpec,
    ) -> RegisteredModel:
        model = self.registry.get_model(model_id)
        if model.stage is not ModelStage.PAPER:
            raise PermissionError("PAPER strategy runtime requires ModelStage.PAPER")
        if model.family != "generated-feature-strategy":
            raise ValueError("PAPER model is not a generated-feature strategy")
        metadata = model.metadata
        if metadata.get("final_strategy_id", "") != strategy.strategy_id:
            raise ValueError("PAPER model final strategy identity mismatch")
        if metadata.get("program_id", "") != strategy.program_id:
            raise ValueError("PAPER model ResearchProgram identity mismatch")
        if metadata.get("family_id", "") != strategy.family_id:
            raise ValueError("PAPER model ExperimentFamily identity mismatch")
        return model

    def _validate_calibration_dataset(
        self,
        *,
        dataset: ResearchDataset,
        strategy: FinalStrategySpec,
        label_name: str,
        required_features: tuple[str, ...],
        asof: datetime,
    ) -> None:
        if not dataset.point_in_time:
            raise ValueError("PAPER calibration dataset must be point-in-time")
        if tuple(dataset.universe) != tuple(strategy.universe):
            raise ValueError("PAPER calibration universe differs from frozen strategy")
        if dataset.artifact.version != self.adapter.data_version:
            raise ValueError("PAPER calibration data version differs from active adapter")
        missing_features = set(required_features) - set(dataset.features)
        if missing_features:
            raise KeyError(
                f"PAPER calibration dataset missing features: {sorted(missing_features)}"
            )
        if label_name not in dataset.labels:
            raise KeyError(f"PAPER calibration dataset missing label {label_name!r}")
        if self.config.calibration_split not in dataset.splits:
            raise KeyError(
                f"PAPER calibration split {self.config.calibration_split!r} is not declared"
            )
        split_range = dataset.splits[self.config.calibration_split]
        if split_range.end > asof:
            raise ValueError("PAPER calibration split extends beyond planning asof")
        panel = dataset.get_split(self.config.calibration_split)
        if panel.timestamps[-1] > asof:
            raise ValueError("PAPER calibration panel contains observations after planning asof")

    @staticmethod
    def _marked_state(
        *,
        state: PortfolioState,
        market_snapshot,
        universe,
    ) -> PortfolioState:
        nonzero_assets = {
            asset for asset, quantity in state.positions.items() if abs(quantity) > 1e-15
        }
        outside = nonzero_assets - set(universe)
        if outside:
            keys = ", ".join(sorted(asset.key for asset in outside))
            raise ValueError(f"PAPER account contains positions outside frozen universe: {keys}")
        marks = {
            asset: market_snapshot.price(asset)
            for asset in set(universe) | nonzero_assets
        }
        return PortfolioState(
            asof=market_snapshot.asof,
            base_currency=state.base_currency,
            cash=state.cash,
            positions=state.positions,
            marks=marks,
        )

    def prepare(
        self,
        *,
        model_id: str,
        strategy: FinalStrategySpec,
        calibration_dataset: ResearchDataset,
        state: PortfolioState,
        asof: datetime,
    ) -> PaperStrategyPlan:
        """Build one non-mutating PAPER plan from explicit calibration evidence."""

        asof = require_aware_datetime(asof, "asof")
        model = self._validate_model_identity(model_id=model_id, strategy=strategy)
        experiment = self.registry.get_experiment(strategy.selected_experiment_id)
        if experiment.metadata.get("generated_feature_digest", "") != strategy.selected_feature_digest:
            raise ValueError("formal ExperimentSpec feature identity differs from frozen strategy")
        if experiment.dataset.digest != strategy.primary_dataset.digest:
            raise ValueError("formal ExperimentSpec primary dataset identity differs from frozen strategy")

        feature = self.generated_feature_store.get(strategy.selected_feature_digest)
        if feature.digest != strategy.selected_feature_digest:
            raise ValueError("generated feature store returned a different feature digest")
        market, label_name = self._decode_protocol(strategy)

        required_features = tuple(
            dict.fromkeys((*feature.spec.input_fields, "log_return_1"))
        )
        self._validate_calibration_dataset(
            dataset=calibration_dataset,
            strategy=strategy,
            label_name=label_name,
            required_features=required_features,
            asof=asof,
        )

        alpha_model = GeneratedFeatureAlphaModel(
            feature,
            label_name=label_name,
            min_observations=max(10, market.ar_min_observations),
        )
        risk_model = GARCH11RiskModel(
            min_observations=market.garch_min_observations,
            correlation_lookback=market.correlation_lookback,
        )
        alpha_artifact = alpha_model.fit(
            calibration_dataset,
            split=self.config.calibration_split,
        )
        risk_artifact = risk_model.fit(
            calibration_dataset,
            split=self.config.calibration_split,
        )

        lookback = max(market.lookback, feature.spec.lookback, risk_model.min_lookback)
        window = self.adapter.feature_window(
            asof,
            strategy.universe,
            required_features,
            lookback,
        )
        if window.data_version != calibration_dataset.artifact.version:
            raise ValueError("PAPER inference and calibration data versions are not aligned")
        market_snapshot = self.adapter.market_snapshot(asof, strategy.universe)
        marked_state = self._marked_state(
            state=state,
            market_snapshot=market_snapshot,
            universe=strategy.universe,
        )

        alpha = alpha_model.predict(window)
        risk = risk_model.predict(window)
        optimizer = MeanVarianceOptimizer(
            MeanVarianceConfig(
                risk_aversion=market.risk_aversion,
                cash_weight=market.cash_weight,
                long_only=True,
                max_abs_weight=market.max_weight,
                turnover_penalty=market.turnover_penalty,
            )
        )
        target = optimizer.optimize(alpha, risk, marked_state)
        gate = StaticRiskGate(
            max_gross_exposure=1.0,
            max_abs_weight=market.max_weight,
            min_cash_weight=market.cash_weight - 1e-9,
        )
        risk_decision = gate.assess(target, marked_state, market_snapshot)
        planner = OrderPlanner(
            min_notional=self.config.min_order_notional,
            quantity_precision=self.config.quantity_precision,
        )
        orders = planner.plan(target, marked_state, market_snapshot, risk_decision)

        # Model identity is deliberately checked even though its artifact is not used as
        # executable code: the executable recipe is the frozen FinalStrategySpec plus the
        # exact generated feature artifact referenced by it.
        if model.artifact.digest.strip() == "":  # pragma: no cover - domain invariant
            raise ValueError("PAPER registered model artifact digest is empty")

        return PaperStrategyPlan(
            model_id=model.model_id,
            final_strategy_id=strategy.strategy_id,
            program_id=strategy.program_id,
            asof=asof,
            calibration_dataset_digest=calibration_dataset.artifact.digest,
            alpha_artifact=alpha_artifact,
            risk_artifact=risk_artifact,
            alpha=alpha,
            risk=risk,
            marked_state=marked_state,
            target=target,
            risk_decision=risk_decision,
            orders=orders,
        )

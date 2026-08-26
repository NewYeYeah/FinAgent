from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from finagent.agents.generated_features import (
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
    SQLiteGeneratedFeatureStore,
)
from finagent.backtest.market_study import MarketStudyConfig
from finagent.data import InMemoryPriceDataAdapter
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiments import ArtifactRef, ArtifactType, ExperimentSpec
from finagent.domain.market import PriceBar
from finagent.domain.model_registry import ModelStage, RegisteredModel
from finagent.domain.portfolio import PortfolioState, RiskStatus
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.operations.paper_strategy import PaperStrategyRuntime
from finagent.research.agent_market import AgentMarketResearchConfig
from finagent.research.final_strategy import FinalStrategySpec
from finagent.research.registry import SQLiteResearchRegistry
from finagent.sandbox import FeatureSandboxRequest, LocalFeatureSandbox


NOW = datetime(2026, 8, 26, 6, 0, tzinfo=UTC)


def _market_config() -> MarketStudyConfig:
    return MarketStudyConfig(
        outer_train_size=50,
        outer_test_size=15,
        outer_step_size=15,
        inner_train_size=30,
        inner_test_size=10,
        inner_step_size=10,
        purge_bars=1,
        embargo_bars=0,
        initial_cash=1_000_000.0,
        lookback=10,
        rebalance_every=2,
        execution_lag_events=1,
        cash_weight=0.20,
        max_weight=0.50,
        commission_bps=0.5,
        slippage_bps=0.5,
        impact_bps=0.0,
        max_participation_rate=0.10,
        garch_min_observations=10,
        correlation_lookback=10,
        ar_min_observations=10,
        risk_aversion=20.0,
        turnover_penalty=0.001,
    )


def _adapter(days: int = 130):
    assets = tuple(
        AssetId(symbol, AssetType.ETF, venue="ARCX", currency="USD")
        for symbol in ("SPY", "QQQ", "IWM")
    )
    start = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    histories = {}
    for asset_index, asset in enumerate(assets):
        price = 100.0 + 8.0 * asset_index
        bars = []
        for day in range(days):
            event_time = start + timedelta(days=day)
            cycle = 0.0025 * np.sin((day + 2 * asset_index) / 6.0)
            drift = 0.0005 + 0.0001 * asset_index
            price *= 1.0 + drift + cycle
            bars.append(
                PriceBar(
                    event_time=event_time,
                    available_at=event_time + timedelta(hours=6, minutes=30),
                    open=price * 0.999,
                    high=price * 1.004,
                    low=price * 0.996,
                    close=price,
                    volume=2_000_000.0 + 20_000.0 * day + 5000.0 * asset_index,
                )
            )
        histories[asset] = tuple(bars)
    return InMemoryPriceDataAdapter(histories, data_version="paper-data-v1"), assets, start


def _feature() -> GeneratedFeatureArtifact:
    spec = FeatureSpec(
        feature_id="momentum",
        name="momentum",
        description="one-day continuation",
        hypothesis="one-day return continuation",
        input_fields=("simple_return_1",),
        lookback=3,
    )
    source = 'def compute_feature(inputs):\n    return inputs["simple_return_1"]\n'
    validator = FeatureCodeValidator()
    validation = validator.validate(source)
    smoke = LocalFeatureSandbox(validator=validator).run(
        FeatureSandboxRequest(
            spec,
            source,
            {"simple_return_1": [0.01, -0.02, 0.03]},
        )
    )
    return GeneratedFeatureArtifact(
        spec=spec,
        source=source,
        validation=validation,
        generated_at=NOW,
        generator_id="unit-test",
        smoke_output_digest=smoke.output_digest,
    )


def _protocol() -> str:
    config = AgentMarketResearchConfig(max_candidates=1, market=_market_config())
    payload = {
        "schema_version": "finagent.final-strategy-protocol.v1",
        "agent_market": {
            "max_candidates": config.max_candidates,
            "family_alpha": config.family_alpha,
            "selection_metric": config.selection_metric,
            "label_name": config.label_name,
            "transaction_cost_bps": config.transaction_cost_bps,
            "min_cross_section": config.min_cross_section,
            "min_periods": config.min_periods,
            "require_statistical_acceptance": config.require_statistical_acceptance,
        },
        "market": asdict(config.market),
        "implementation": PaperStrategyRuntime.IMPLEMENTATION,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _setup(tmp_path: Path, *, stage: ModelStage = ModelStage.PAPER):
    adapter, universe, start = _adapter()
    feature = _feature()
    feature_store = SQLiteGeneratedFeatureStore(tmp_path / "features.sqlite")
    feature_store.register(feature)

    registry = SQLiteResearchRegistry(tmp_path / "registry.sqlite")
    development_dataset = ArtifactRef(
        "development-dataset",
        ArtifactType.DATASET,
        "development-v1",
        "d" * 64,
    )
    experiment_id = "family-001:candidate:1"
    registry.register_experiment(
        ExperimentSpec(
            experiment_id=experiment_id,
            hypothesis=feature.spec.hypothesis,
            dataset=development_dataset,
            code=feature.code_artifact_ref(),
            universe=universe,
            parameters={"feature_digest": feature.digest},
            seed=0,
            parent_artifacts=(feature.factor_artifact_ref(),),
            metadata={
                "generated_feature_digest": feature.digest,
                "program_id": "program-001",
                "family_id": "family-001",
            },
        )
    )
    protocol = _protocol()
    strategy = FinalStrategySpec(
        program_id="program-001",
        family_id="family-001",
        family_validation_report_id="validation-001",
        selected_experiment_id=experiment_id,
        selected_feature_digest=feature.digest,
        primary_dataset=development_dataset,
        universe=universe,
        research_protocol_json=protocol,
        research_protocol_digest=hashlib.sha256(protocol.encode()).hexdigest(),
        selection_rule="unit-test-selection-rule",
        created_at=NOW,
    )
    model = RegisteredModel(
        model_id=f"validated-{strategy.strategy_id}",
        family="generated-feature-strategy",
        artifact=ArtifactRef(
            f"research-model:{strategy.strategy_id}",
            ArtifactType.MODEL,
            "1.2.2",
            "m" * 64,
        ),
        stage=stage,
        created_at=NOW,
        metadata={
            "promotion_id": "promotion-001",
            "program_id": strategy.program_id,
            "family_id": strategy.family_id,
            "final_strategy_id": strategy.strategy_id,
            "holdout_evaluation_id": "holdout-eval-001",
        },
    )
    registry.register_model(model)

    calibration_end = start + timedelta(days=90)
    calibration = adapter.build_dataset(
        DatasetRequest(
            universe=universe,
            features=("simple_return_1", "log_return_1"),
            labels=("forward_simple_return_1",),
            splits={"train": TimeRange(start - timedelta(hours=1), calibration_end)},
            dataset_id="paper-calibration-001",
        )
    )
    asof = start + timedelta(days=100, hours=6, minutes=30)
    state = PortfolioState(
        asof=asof - timedelta(days=1),
        base_currency="USD",
        cash=1_000_000.0,
    )
    runtime = PaperStrategyRuntime(
        adapter=adapter,
        registry=registry,
        generated_feature_store=feature_store,
    )
    return runtime, registry, strategy, calibration, state, asof


def test_paper_runtime_recreates_frozen_protocol_and_plans_orders(tmp_path) -> None:
    runtime, registry, strategy, calibration, state, asof = _setup(tmp_path)

    plan = runtime.prepare(
        model_id=f"validated-{strategy.strategy_id}",
        strategy=strategy,
        calibration_dataset=calibration,
        state=state,
        asof=asof,
    )

    assert plan.model_id == f"validated-{strategy.strategy_id}"
    assert plan.final_strategy_id == strategy.strategy_id
    assert plan.calibration_dataset_digest == calibration.artifact.digest
    assert plan.asof == asof
    assert plan.risk_decision.status is RiskStatus.APPROVE
    assert plan.target.asof == asof
    assert plan.marked_state.asof == asof
    assert plan.orders
    assert {order.asset for order in plan.orders} <= set(strategy.universe)
    assert plan.execution_price_field == "open"
    assert registry.get_model(plan.model_id).stage is ModelStage.PAPER
    assert registry.model_history(plan.model_id) == ()


def test_paper_runtime_rejects_non_paper_model(tmp_path) -> None:
    runtime, _registry, strategy, calibration, state, asof = _setup(
        tmp_path,
        stage=ModelStage.VALIDATED,
    )

    with pytest.raises(PermissionError, match="ModelStage.PAPER"):
        runtime.prepare(
            model_id=f"validated-{strategy.strategy_id}",
            strategy=strategy,
            calibration_dataset=calibration,
            state=state,
            asof=asof,
        )


def test_paper_runtime_requires_explicit_fully_realized_calibration_window(tmp_path) -> None:
    runtime, _registry, strategy, calibration, state, asof = _setup(tmp_path)
    future_split = TimeRange(calibration.splits["train"].start, asof + timedelta(days=1))
    future_calibration = type(calibration)(
        artifact=calibration.artifact,
        universe=calibration.universe,
        features=calibration.features,
        labels=calibration.labels,
        splits={"train": future_split},
        point_in_time=True,
        metadata=calibration.metadata,
        panels={},
    )

    with pytest.raises(ValueError, match="extends beyond planning asof"):
        runtime.prepare(
            model_id=f"validated-{strategy.strategy_id}",
            strategy=strategy,
            calibration_dataset=future_calibration,
            state=state,
            asof=asof,
        )


def test_paper_runtime_rejects_positions_outside_frozen_universe(tmp_path) -> None:
    runtime, _registry, strategy, calibration, _state, asof = _setup(tmp_path)
    outside = AssetId("DIA", AssetType.ETF, venue="ARCX", currency="USD")
    state = PortfolioState(
        asof=asof - timedelta(days=1),
        base_currency="USD",
        cash=900_000.0,
        positions={outside: 100.0},
        marks={outside: 100.0},
    )

    with pytest.raises(ValueError, match="outside frozen universe"):
        runtime.prepare(
            model_id=f"validated-{strategy.strategy_id}",
            strategy=strategy,
            calibration_dataset=calibration,
            state=state,
            asof=asof,
        )

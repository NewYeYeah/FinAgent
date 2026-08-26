from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from finagent.agents.domain import AgentTask
from finagent.agents.generated_features import (
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
)
from finagent.backtest import MarketStudyConfig
from finagent.data import InMemoryPriceDataAdapter
from finagent.data.ingestion.base import MarketRegion
from finagent.data.ingestion.provider import (
    ALPACA_CAPABILITIES,
    DataFrequency,
    ResearchDataRequirement,
)
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.market import PriceBar
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.models.alpha import GeneratedFeatureAlphaModel
from finagent.research import (
    AgentMarketResearchConfig,
    AgentMarketResearchRunner,
    ResearchProgram,
    SQLiteAgentMarketResearchStore,
    SQLiteResearchProgramStore,
    holm_adjusted_pvalues,
)
from finagent.sandbox import FeatureSandboxRequest, LocalFeatureSandbox


def _artifact(feature_id: str, source: str, hypothesis: str) -> GeneratedFeatureArtifact:
    spec = FeatureSpec(
        feature_id=feature_id,
        name=feature_id,
        description=f"test feature {feature_id}",
        hypothesis=hypothesis,
        input_fields=("simple_return_1",),
        lookback=3,
    )
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
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        generator_id="unit-test",
        smoke_output_digest=smoke.output_digest,
    )


def _adapter(days: int = 90) -> tuple[InMemoryPriceDataAdapter, tuple[AssetId, ...]]:
    assets = tuple(
        AssetId(symbol, AssetType.ETF, venue="NYSE", currency="USD")
        for symbol in ("SPY", "QQQ", "IWM", "DIA")
    )
    start = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    histories = {}
    for asset_index, asset in enumerate(assets):
        bars = []
        price = 100.0 + 5.0 * asset_index
        for day in range(days):
            event_time = start + timedelta(days=day)
            drift = 0.0004 + 0.00015 * asset_index
            cycle = 0.003 * np.sin((day + asset_index) / 5.0)
            price *= 1.0 + drift + cycle
            bars.append(
                PriceBar(
                    event_time=event_time,
                    available_at=event_time + timedelta(hours=6, minutes=30),
                    open=price * 0.999,
                    high=price * 1.004,
                    low=price * 0.996,
                    close=price,
                    volume=1_000_000.0 + 10_000.0 * day + 1000.0 * asset_index,
                )
            )
        histories[asset] = tuple(bars)
    return InMemoryPriceDataAdapter(histories, data_version="synthetic-us-v1"), assets


def test_holm_adjustment_is_monotone_and_family_bounded() -> None:
    adjusted = holm_adjusted_pvalues({"a": 0.01, "b": 0.03, "c": 0.20})
    assert adjusted["a"] == pytest.approx(0.03)
    assert adjusted["b"] == pytest.approx(0.06)
    assert adjusted["c"] == pytest.approx(0.20)


def test_generated_feature_alpha_model_calibrates_and_predicts() -> None:
    adapter, universe = _adapter(50)
    artifact = _artifact(
        "momentum",
        'def compute_feature(inputs):\n    return inputs["simple_return_1"]\n',
        "one-day continuation",
    )
    calendar = adapter.calendar(
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 3, 31, tzinfo=UTC),
        universe,
    )
    split = TimeRange(calendar[3], calendar[35] + timedelta(microseconds=1))
    dataset = adapter.build_dataset(
        DatasetRequest(
            universe=universe,
            features=("simple_return_1",),
            labels=("forward_simple_return_1",),
            splits={"train": split},
            dataset_id="generated-alpha-test",
        )
    )
    model = GeneratedFeatureAlphaModel(artifact, min_observations=20)
    model.fit(dataset)
    window = adapter.feature_window(
        calendar[40], universe, ("simple_return_1",), artifact.spec.lookback
    )
    forecast = model.predict(window)
    assert set(forecast.expected_returns) == set(universe)
    assert model.calibration.observations >= 20
    assert np.isfinite(model.calibration.slope)


def test_agent_market_runner_reserves_budget_and_persists_evidence(tmp_path: Path) -> None:
    adapter, universe = _adapter(90)
    momentum = _artifact(
        "momentum",
        'def compute_feature(inputs):\n    return inputs["simple_return_1"]\n',
        "one-day continuation",
    )
    reversal = _artifact(
        "reversal",
        'def compute_feature(inputs):\n    return [-x for x in inputs["simple_return_1"]]\n',
        "one-day reversal",
    )
    program_store = SQLiteResearchProgramStore(tmp_path / "program.sqlite")
    program_store.register(
        ResearchProgram(
            program_id="us-agent-program",
            alpha_budget=0.05,
            max_families=2,
            max_experiments=4,
        )
    )
    market = MarketStudyConfig(
        outer_train_size=30,
        outer_test_size=10,
        outer_step_size=10,
        inner_train_size=15,
        inner_test_size=5,
        inner_step_size=5,
        purge_bars=1,
        embargo_bars=0,
        lookback=10,
        rebalance_every=2,
        execution_lag_events=1,
        cash_weight=0.20,
        max_weight=0.40,
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
    config = AgentMarketResearchConfig(
        max_candidates=2,
        family_alpha=0.05,
        transaction_cost_bps=1.0,
        min_cross_section=2,
        min_periods=3,
        require_statistical_acceptance=False,
        market=market,
    )
    runner = AgentMarketResearchRunner(
        adapter=adapter,
        capabilities=ALPACA_CAPABILITIES,
        requirement=ResearchDataRequirement(
            market=MarketRegion.US_EQUITY,
            frequency=DataFrequency.DAILY,
        ),
        program_store=program_store,
        config=config,
    )
    calendar = adapter.calendar(
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2025, 6, 30, tzinfo=UTC),
        universe,
    )
    task = AgentTask(
        task_id="task-us-etf",
        objective="find a bounded ETF signal",
        created_at=calendar[-1],
    )
    result = runner.run(
        task=task,
        candidates=(momentum, reversal),
        universe=universe,
        start=calendar[0],
        end=calendar[-1] + timedelta(microseconds=1),
        program_id="us-agent-program",
        family_id="family-001",
    )
    assert result.folds
    assert all(fold.selected_feature_id in {"momentum", "reversal"} for fold in result.folds)
    assert result.aggregate_portfolio_metrics["oos_periods"] > 0
    budget = program_store.budget_snapshot("us-agent-program")
    assert budget.family_count == 1
    assert budget.experiment_count == 2
    assert budget.alpha_spent == pytest.approx(0.05)

    store = SQLiteAgentMarketResearchStore(tmp_path / "evidence.sqlite")
    store.register(result)
    store.register(result)
    stored = store.get(result.study_id)
    assert stored["task_id"] == "task-us-etf"
    assert stored["provider"] == "alpaca"


def test_requirement_blocks_wrong_market(tmp_path: Path) -> None:
    adapter, _universe = _adapter(20)
    store = SQLiteResearchProgramStore(tmp_path / "program.sqlite")
    with pytest.raises(ValueError, match="does not satisfy"):
        AgentMarketResearchRunner(
            adapter=adapter,
            capabilities=ALPACA_CAPABILITIES,
            requirement=ResearchDataRequirement(
                market=MarketRegion.A_SHARE,
                frequency=DataFrequency.DAILY,
            ),
            program_store=store,
        )

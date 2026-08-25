from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from finagent.backtest import MarketStudyConfig, run_nested_market_study
from finagent.data import InMemoryPriceDataAdapter
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.market import PriceBar


def _market() -> tuple[InMemoryPriceDataAdapter, tuple[AssetId, ...], datetime, datetime]:
    assets = (
        AssetId("ETF_A", AssetType.ETF, "XNAS", "USD"),
        AssetId("ETF_B", AssetType.ETF, "ARCX", "USD"),
    )
    bars = {}
    first_day = datetime(2023, 1, 2, tzinfo=UTC)
    for asset_index, asset in enumerate(assets):
        history = []
        for index in range(150):
            day = first_day + timedelta(days=index)
            trend = 100.0 + index * (0.08 + asset_index * 0.02)
            close = trend + math.sin(index / (6.0 + asset_index))
            open_price = close * (1.0 + 0.0005 * math.cos(index / 5.0))
            history.append(
                PriceBar(
                    event_time=day.replace(hour=14, minute=30),
                    available_at=day.replace(hour=21),
                    open=open_price,
                    high=max(open_price, close) * 1.002,
                    low=min(open_price, close) * 0.998,
                    close=close,
                    volume=50_000_000.0,
                )
            )
        bars[asset] = history
    adapter = InMemoryPriceDataAdapter(bars, data_version="synthetic-market-m1")
    return adapter, assets, first_day, first_day + timedelta(days=151)


def _config(**overrides) -> MarketStudyConfig:
    values = {
        "outer_train_size": 80,
        "outer_test_size": 20,
        "outer_step_size": 20,
        "inner_train_size": 40,
        "inner_test_size": 15,
        "inner_step_size": 15,
        "purge_bars": 1,
        "embargo_bars": 1,
        "lookback": 15,
        "rebalance_every": 5,
        "cash_weight": 0.20,
        "max_weight": 0.60,
        "garch_min_observations": 12,
        "correlation_lookback": 15,
        "ar_min_observations": 20,
        "candidate_names": ("equal_weight", "minimum_variance", "ar1_mean_variance"),
    }
    values.update(overrides)
    return MarketStudyConfig(**values)


def test_nested_market_study_selects_only_on_inner_folds() -> None:
    adapter, universe, start, end = _market()
    result = run_nested_market_study(
        adapter,
        universe=universe,
        start=start,
        end=end,
        config=_config(),
    )

    assert result.data_version == "synthetic-market-m1"
    assert len(result.folds) == 3
    assert result.aggregate_metrics["oos_periods"] == 60
    assert result.aggregate_metrics["transaction_cost"] >= 0
    for fold in result.folds:
        assert fold.selected_candidate in fold.inner_mean_sharpe
        assert set(fold.inner_mean_sharpe) == {
            "equal_weight",
            "minimum_variance",
            "ar1_mean_variance",
        }
        assert fold.outer_metrics["gross_traded_weight"] >= 0


def test_market_study_id_is_deterministic_for_same_evidence() -> None:
    adapter, universe, start, end = _market()
    config = _config(candidate_names=("equal_weight",))
    first = run_nested_market_study(
        adapter, universe=universe, start=start, end=end, config=config
    )
    second = run_nested_market_study(
        adapter, universe=universe, start=start, end=end, config=config
    )
    assert first.study_id == second.study_id
    assert first.to_dict() == second.to_dict()


def test_market_study_rejects_cross_currency_universe() -> None:
    adapter, universe, start, end = _market()
    mixed = (universe[0], AssetId("OTHER", AssetType.ETF, "SSE", "CNY"))
    with pytest.raises(ValueError, match="one base currency"):
        run_nested_market_study(adapter, universe=mixed, start=start, end=end, config=_config())

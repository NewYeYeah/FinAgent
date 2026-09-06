from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

import pytest

from finagent.domain.research import TimeRange
from finagent.research.market_state import (
    MarketFeatureConfig,
    MarketFeatures,
    MarketStateRow,
    MarketStateSource,
    build_market_features,
)
from finagent.research.market_state_gmm import (
    GMMConfig,
    MarketStateModel,
    fit_market_state,
    project_market_state,
)
from tests.test_us_a1_factor_panel_materialization import _panel


def market_fixture():
    assets = _panel(asset_count=4, bar_count=26)
    source = MarketStateSource("synthetic", "v1", "v1", "fixture", "fixture-calendar")
    config = MarketFeatureConfig("A0")
    first = assets[0].bars[0]
    fit = TimeRange(first.event_time, assets[0].bars[-1].available_at)
    future = tuple(
        replace(
            a,
            bars=tuple(
                replace(
                    b,
                    event_time=b.event_time + timedelta(days=1),
                    available_at=b.available_at + timedelta(days=1),
                    session_id="next-session",
                )
                for b in a.bars
            ),
        )
        for a in assets
    )
    return assets, future, source, config, fit


def test_train_only_fit_future_mutation_and_json_projection_replay():
    assets, future, source, config, fit = market_fixture()
    train = build_market_features(assets, source, config)
    projected = build_market_features(future, source, config)
    all_features = replace(train, rows=train.rows + projected.rows)
    model = fit_market_state(all_features, fit)
    extreme = replace(
        all_features,
        rows=train.rows
        + tuple(
            replace(row, values=(999999.0, 99999.0), unavailable_reason=None)
            for row in projected.rows
        ),
    )
    assert fit_market_state(extreme, fit) == model == fit_market_state(train, fit)
    restored = MarketStateModel.from_dict(json.loads(json.dumps(model.to_dict())))
    states = project_market_state(model, all_features, as_of=projected.rows[-1].available_at)
    assert states == project_market_state(
        restored, all_features, as_of=projected.rows[-1].available_at
    )
    assert all(row.unavailable_reason == "FIT_HISTORY_NOT_PROJECTION" for row in states[:26])
    for state in states[30:]:
        assert state.probabilities is not None
        assert sum(state.probabilities) == pytest.approx(1.0)
        assert all(0 <= p <= 1 for p in state.probabilities)
    late_mutation = replace(projected, rows=projected.rows[:16] + extreme.rows[42:])
    assert (
        project_market_state(model, projected, as_of=projected.rows[-1].available_at)[:16]
        == (project_market_state(model, late_mutation, as_of=projected.rows[-1].available_at)[:16])
    )
    assert model.to_dict()["state_interpretation"] == sorted(
        model.to_dict()["state_interpretation"], key=lambda row: row["train_centroid"]
    )


def test_fit_cutoff_window_and_seed_are_part_of_identity():
    assets, _, source, config, fit = market_fixture()
    features = build_market_features(assets, source, config)
    model = fit_market_state(features, fit)
    shifted = fit_market_state(features, TimeRange(fit.start + timedelta(minutes=15), fit.end))
    assert shifted.model_id != model.model_id
    assert shifted.scaler_mean == model.scaler_mean  # only unavailable warmup excluded
    assert (
        fit_market_state(features, fit, config=GMMConfig(random_seed=19)).model_id != model.model_id
    )
    with pytest.raises(ValueError, match="unavailable by fit cutoff"):
        fit_market_state(features, TimeRange(fit.start, fit.end - timedelta(minutes=7)))
    with pytest.raises(ValueError, match="precedes fit window"):
        fit_market_state(features, fit, available_at=fit.end - timedelta(seconds=1))


def test_missing_bars_are_unavailable_not_imputed_or_skipped():
    assets, _, source, config, _ = market_fixture()
    damaged = list(assets)
    bars = list(damaged[0].bars)
    bars[10] = replace(bars[10], is_complete=False)
    damaged[0] = replace(damaged[0], bars=tuple(bars))
    first = build_market_features(tuple(damaged), source, config)
    bars[10] = replace(bars[10], open=900, high=900, low=900, close=900)
    damaged[0] = replace(damaged[0], bars=tuple(bars))
    assert first == build_market_features(tuple(damaged), source, config)
    assert all(row.values is None for row in first.rows[10:15])
    assert first.rows[15].values is not None
    with pytest.raises(ValueError, match="proxy is missing"):
        build_market_features(assets, source, MarketFeatureConfig("ABSENT"))
    damaged[0] = replace(
        damaged[0],
        bars=tuple(replace(b, available_at=b.available_at + timedelta(seconds=1)) for b in bars),
    )
    with pytest.raises(ValueError, match="availability"):
        build_market_features(tuple(damaged), source, config)


def test_no_probability_before_model_or_observation_available():
    assets, future, source, config, fit = market_fixture()
    train = build_market_features(assets, source, config)
    features = build_market_features(future, source, config)
    model = fit_market_state(train, fit, available_at=features.rows[8].available_at)
    rows = project_market_state(model, features, as_of=features.rows[15].available_at)
    assert rows[7].unavailable_reason == "MODEL_NOT_AVAILABLE"
    assert rows[8].probabilities is not None
    assert rows[16].unavailable_reason == "OBSERVATION_NOT_AVAILABLE"
    with pytest.raises(ValueError, match="identity mismatch"):
        project_market_state(
            model, replace(features, source=replace(source, source_revision="v2")), as_of=fit.end
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        project_market_state(model, features, as_of=fit.end.replace(tzinfo=None))


def test_insufficient_degenerate_and_nonconverged_training_fail_explicitly():
    assets, _, source, config, fit = market_fixture()
    features = build_market_features(assets, source, config)
    with pytest.raises(ValueError, match="INSUFFICIENT"):
        fit_market_state(replace(features, rows=features.rows[:10]), fit)
    constant = replace(
        features,
        rows=tuple(
            replace(row, values=(0.0, 0.0), unavailable_reason=None) for row in features.rows
        ),
    )
    with pytest.raises(ValueError, match="DEGENERATE"):
        fit_market_state(constant, fit)
    with pytest.raises(ValueError, match="NOT_CONVERGED"):
        fit_market_state(features, fit, config=GMMConfig(max_iter=1, tol=1e-12))


@pytest.mark.parametrize("probabilities", [(0.2, 0.2), (-0.1, 1.1), (float("nan"), 1), ()])
def test_invalid_probabilities_rejected(probabilities):
    assets, _, _, _, _ = market_fixture()
    bar = assets[0].bars[0]
    with pytest.raises(ValueError, match="probabilities"):
        MarketStateRow("model", bar.event_time, bar.available_at, bar.session_id, probabilities)


def test_model_tampering_and_feature_order_rejected():
    assets, _, source, config, fit = market_fixture()
    features = build_market_features(assets, source, config)
    payload = json.loads(json.dumps(fit_market_state(features, fit).to_dict()))
    payload["scaler_mean"][0] += 1
    with pytest.raises(ValueError, match="identity mismatch"):
        MarketStateModel.from_dict(payload)
    with pytest.raises(ValueError, match="chronological"):
        MarketFeatures(source, config, tuple(reversed(features.rows)))


def test_feature_construction_cannot_see_future_ohlcv_or_another_session():
    assets, future, source, config, _ = market_fixture()
    original = build_market_features(assets, source, config)
    mutated = tuple(
        replace(
            a,
            bars=a.bars[:15]
            + tuple(
                replace(
                    b,
                    open=b.open * 3,
                    high=b.high * 3,
                    low=b.low * 3,
                    close=b.close * 3,
                    volume=b.volume * 5,
                )
                for b in a.bars[15:]
            ),
        )
        for a in assets
    )
    assert build_market_features(mutated, source, config).rows[:15] == original.rows[:15]
    joined = tuple(replace(a, bars=a.bars + b.bars) for a, b in zip(assets, future, strict=True))
    expected = original.rows + build_market_features(future, source, config).rows
    assert build_market_features(joined, source, config).rows == expected

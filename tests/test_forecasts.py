from datetime import timedelta

import pytest

from finagent.domain.forecasts import AlphaForecast, ModelRef, RiskForecast


def test_alpha_forecast_validates_uncertainty(now, assets):
    a, b = assets
    forecast = AlphaForecast(
        asof=now,
        horizon=timedelta(days=1),
        expected_returns={a: 0.01, b: -0.005},
        uncertainty={a: 0.02},
        source=ModelRef("ar1", "1"),
    )
    assert forecast.expected_returns[a] == pytest.approx(0.01)
    assert forecast.uncertainty[a] == pytest.approx(0.02)

    with pytest.raises(ValueError, match="absent"):
        AlphaForecast(
            asof=now,
            horizon=timedelta(days=1),
            expected_returns={a: 0.01},
            uncertainty={b: 0.02},
            source=ModelRef("ar1", "1"),
        )


def test_risk_forecast_requires_complete_symmetric_matrix(now, assets):
    a, b = assets
    good = RiskForecast(
        asof=now,
        horizon=timedelta(days=1),
        volatilities={a: 0.2, b: 0.1},
        covariance={(a, a): 0.04, (a, b): 0.01, (b, a): 0.01, (b, b): 0.01},
        source=ModelRef("ewma", "1"),
    )
    assert good.covariance[(a, b)] == pytest.approx(0.01)

    with pytest.raises(ValueError, match="incomplete"):
        RiskForecast(
            asof=now,
            horizon=timedelta(days=1),
            volatilities={a: 0.2, b: 0.1},
            covariance={(a, a): 0.04, (a, b): 0.01, (b, b): 0.01},
            source=ModelRef("ewma", "1"),
        )

    with pytest.raises(ValueError, match="not symmetric"):
        RiskForecast(
            asof=now,
            horizon=timedelta(days=1),
            volatilities={a: 0.2, b: 0.1},
            covariance={(a, a): 0.04, (a, b): 0.01, (b, a): 0.02, (b, b): 0.01},
            source=ModelRef("ewma", "1"),
        )


def test_risk_forecast_diagonal_must_match_volatility(now, assets):
    a = assets[0]
    with pytest.raises(ValueError, match=r"volatility\^2"):
        RiskForecast(
            asof=now,
            horizon=timedelta(days=1),
            volatilities={a: 0.2},
            covariance={(a, a): 0.03},
            source=ModelRef("ewma", "1"),
        )

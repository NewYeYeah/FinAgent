from __future__ import annotations

from typing import cast

import pytest

import finagent.runtime.ashare_historical_acceptance_terminal as terminal
from finagent.runtime.ashare_historical_acceptance import AshareHistoricalAcceptanceConfig


def _robust(status: str, components: list[object] | None = None) -> dict[str, object]:
    return {
        "frozen_selection": {
            "status": status,
            "components": [] if components is None else components,
        }
    }


def _a4(
    status: str,
    *,
    execution_validation_passed: bool = False,
    promotion_eligible: bool = False,
) -> dict[str, object]:
    return {
        "research_outcome": {
            "status": status,
            "execution_validation_passed": execution_validation_passed,
            "promotion_eligible": promotion_eligible,
            "reason_codes": [
                "NO_A2P6_FACTOR_PASSED_PREREGISTERED_GATE",
                "NO_PORTFOLIO_BACKTEST_EXECUTED",
                "RESERVE_UNTOUCHED",
            ],
        }
    }


def test_no_alpha_terminal_requires_exact_research_and_a4_outcomes() -> None:
    assert terminal.is_no_alpha_terminal(
        _robust("NO_ROBUST_FACTOR_FOUND"),
        _a4("NO_ROBUST_FACTOR_FAMILY"),
    )
    assert not terminal.is_no_alpha_terminal(
        _robust("ROBUST_FACTOR_FAMILY_FROZEN", [object()]),
        _a4("NO_ROBUST_FACTOR_FAMILY"),
    )
    assert not terminal.is_no_alpha_terminal(
        _robust("NO_ROBUST_FACTOR_FOUND"),
        _a4("PASS"),
    )
    assert not terminal.is_no_alpha_terminal(
        _robust("NO_ROBUST_FACTOR_FOUND"),
        _a4("NO_ROBUST_FACTOR_FAMILY", execution_validation_passed=True),
    )


def test_runner_recovers_only_empty_strategy_date_range(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()

    class FakeRunner:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run(self):
            raise RuntimeError(
                "A-C3 host materializer failed: StrategyDecisionSeries has no date range"
            )

    monkeypatch.setattr(terminal, "AshareHistoricalAcceptanceRunner", FakeRunner)
    monkeypatch.setattr(terminal, "_complete_no_alpha_terminal", lambda _runner: sentinel)
    config = cast(AshareHistoricalAcceptanceConfig, object())
    assert terminal.run_ashare_historical_acceptance(config, confirmed=True) is sentinel


def test_runner_does_not_hide_unrelated_materializer_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunner:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run(self):
            raise RuntimeError("A-C3 host materializer failed: frozen dataset mismatch")

    monkeypatch.setattr(terminal, "AshareHistoricalAcceptanceRunner", FakeRunner)
    config = cast(AshareHistoricalAcceptanceConfig, object())
    with pytest.raises(RuntimeError, match="frozen dataset mismatch"):
        terminal.run_ashare_historical_acceptance(config, confirmed=True)

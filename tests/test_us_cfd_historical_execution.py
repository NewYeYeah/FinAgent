from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from finagent.backtest.us_cfd_execution import (
    CFDAccountSpec,
    CFDExecutionCostPolicy,
    CFDHistoricalStep,
    CFDInstrumentSpec,
    CFDReferencePrice,
    CFDTargetWeight,
    compile_cfd_target,
    run_cfd_historical_execution,
)
from finagent.brokers.mt5.capabilities import MT5SymbolSpec

START = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)


def _instrument(*, margin_rate: float = 0.10) -> CFDInstrumentSpec:
    return CFDInstrumentSpec(
        symbol="US500.CFD",
        contract_size=10.0,
        volume_min=0.1,
        volume_max=100.0,
        volume_step=0.1,
        margin_rate=margin_rate,
        tick_size=0.01,
        currency_profit="USD",
        currency_margin="USD",
    )


def _account(*, max_margin_utilization: float = 0.50) -> CFDAccountSpec:
    return CFDAccountSpec(
        base_currency="USD",
        initial_balance=100_000.0,
        max_margin_utilization=max_margin_utilization,
    )


def _cost() -> CFDExecutionCostPolicy:
    return CFDExecutionCostPolicy(
        spread_bps=10.0,
        slippage_bps=2.0,
        commission_bps=1.0,
    )


def _step(minutes: int, price: float, weight: float) -> CFDHistoricalStep:
    return CFDHistoricalStep(
        asof=START + timedelta(minutes=minutes),
        prices=(CFDReferencePrice("US500.CFD", price),),
        targets=(CFDTargetWeight("US500.CFD", weight),),
    )


def test_target_compiler_rounds_lots_toward_zero_and_respects_minimum() -> None:
    instrument = _instrument()
    compiled = compile_cfd_target(
        instrument,
        weight=0.12345,
        equity=100_000.0,
        reference_price=100.0,
        current_lots=0.0,
    )
    assert compiled.raw_target_lots == pytest.approx(12.345)
    assert compiled.target_lots == pytest.approx(12.3)
    assert compiled.delta_lots == pytest.approx(12.3)
    assert not compiled.below_minimum

    below = compile_cfd_target(
        instrument,
        weight=0.0005,
        equity=100_000.0,
        reference_price=1_000.0,
        current_lots=0.0,
    )
    assert 0 < below.raw_target_lots < instrument.volume_min
    assert below.target_lots == 0.0
    assert below.below_minimum


def test_long_round_trip_recovers_mid_price_gross_pnl_after_cost_attribution() -> None:
    report = run_cfd_historical_execution(
        account_spec=_account(),
        instruments=(_instrument(),),
        cost_policy=_cost(),
        steps=(
            _step(0, 100.0, 0.50),
            _step(60, 101.0, 0.0),
        ),
    )
    assert report.passed
    assert not report.final_state.positions
    assert report.final_state.margin_used == 0.0
    assert report.total_transaction_cost > 0
    assert report.net_pnl < 500.0
    assert report.gross_pnl_before_costs == pytest.approx(500.0)
    assert report.net_pnl + report.total_transaction_cost == pytest.approx(500.0)

    opening_fill = report.steps[0].fills[0]
    closing_fill = report.steps[1].fills[0]
    assert opening_fill.fill_price > opening_fill.reference_price
    assert closing_fill.fill_price < closing_fill.reference_price


def test_short_round_trip_has_symmetric_gross_pnl_and_adverse_costs() -> None:
    report = run_cfd_historical_execution(
        account_spec=_account(),
        instruments=(_instrument(),),
        cost_policy=_cost(),
        steps=(
            _step(0, 100.0, -0.50),
            _step(60, 99.0, 0.0),
        ),
    )
    assert report.passed
    assert report.gross_pnl_before_costs == pytest.approx(500.0)
    assert report.net_pnl < report.gross_pnl_before_costs
    assert report.steps[0].fills[0].fill_price < 100.0
    assert report.steps[1].fills[0].fill_price > 99.0


def test_long_to_short_reversal_realizes_old_leg_and_resets_residual_entry() -> None:
    report = run_cfd_historical_execution(
        account_spec=_account(),
        instruments=(_instrument(),),
        cost_policy=_cost(),
        steps=(
            _step(0, 100.0, 0.25),
            _step(30, 101.0, -0.25),
            _step(60, 100.0, 0.0),
        ),
    )
    assert report.passed
    assert not report.final_state.positions
    reversal = report.steps[1]
    assert len(reversal.fills) == 1
    assert reversal.fills[0].realized_pnl > 0
    assert len(reversal.post_state.positions) == 1
    residual = reversal.post_state.positions[0]
    assert residual.lots < 0
    assert residual.average_price == pytest.approx(reversal.fills[0].fill_price)
    assert report.steps[2].fills[0].realized_pnl > 0


def test_margin_gate_rejects_step_atomically_without_partial_positions() -> None:
    report = run_cfd_historical_execution(
        account_spec=_account(max_margin_utilization=0.10),
        instruments=(_instrument(margin_rate=0.50),),
        cost_policy=_cost(),
        steps=(
            _step(0, 100.0, 0.50),
            _step(60, 101.0, 0.0),
        ),
    )
    assert not report.passed
    assert "step_0:margin:projected_utilization_exceeds_limit" in report.blockers
    assert not report.steps[0].fills
    assert not report.final_state.positions
    assert report.final_state.balance == pytest.approx(100_000.0)


def test_intraday_flat_is_a_hard_historical_execution_boundary() -> None:
    report = run_cfd_historical_execution(
        account_spec=_account(),
        instruments=(_instrument(),),
        cost_policy=_cost(),
        steps=(_step(0, 100.0, 0.25),),
    )
    assert not report.passed
    assert "intraday_flat:open_positions_at_end" in report.blockers
    assert report.final_state.positions


def test_mt5_symbol_spec_adapter_preserves_contract_identity_without_live_authority() -> None:
    spec = MT5SymbolSpec(
        symbol="US500.CFD",
        path="CFD\\Indices\\US500.CFD",
        visible=True,
        trade_mode=4,
        trade_calc_mode=1,
        digits=2,
        point=0.01,
        tick_size=0.01,
        tick_value=0.10,
        contract_size=10.0,
        volume_min=0.1,
        volume_max=100.0,
        volume_step=0.1,
        margin_initial=0.0,
        margin_maintenance=0.0,
        swap_mode=0,
        swap_long=0.0,
        swap_short=0.0,
        filling_mode=1,
        order_mode=127,
        currency_base="USD",
        currency_profit="USD",
        currency_margin="USD",
    )
    instrument = CFDInstrumentSpec.from_mt5_symbol_spec(spec, margin_rate=0.10)
    assert instrument.source_mt5_spec_id == spec.spec_id
    assert instrument.contract_size == 10.0
    assert instrument.volume_step == 0.1


def test_report_is_content_addressed_and_explicitly_non_authoritative() -> None:
    kwargs = {
        "account_spec": _account(),
        "instruments": (_instrument(),),
        "cost_policy": _cost(),
        "steps": (_step(0, 100.0, 0.25), _step(60, 100.5, 0.0)),
    }
    first = run_cfd_historical_execution(**kwargs)
    second = run_cfd_historical_execution(**kwargs)
    assert first.to_dict() == second.to_dict()
    assert first.report_id == second.report_id

    payload = first.to_dict()
    assert payload["broker_execution_authority"] is False
    assert payload["paper_authority"] is False
    assert payload["status_authority"] is False
    assert payload["stage_exit_authority"] is False
    assert payload["live_capital_authority"] is False
    assert payload["real_alpha_evidence_required_for_us_x_progression"] is True

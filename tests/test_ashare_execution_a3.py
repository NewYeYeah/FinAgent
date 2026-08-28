from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest

from finagent.data.ashare_execution import LocalAshareDailyExecutionAdapter
from finagent.data.local_ashare import LocalAshareDatasetLayout
from finagent.domain.ashare_execution import (
    AshareAccountState,
    AshareBoard,
    AshareDailyExecutionSnapshot,
    AshareOrderDecisionStatus,
    AshareOrderReason,
    AsharePosition,
    AshareSessionStatus,
    AshareTradeability,
    infer_ashare_board,
)
from finagent.domain.assets import AssetId
from finagent.domain.forecasts import ModelRef
from finagent.domain.orders import OrderSide
from finagent.domain.portfolio import PortfolioTarget
from finagent.services.ashare_execution import (
    AshareExecutionSession,
    AshareFeeSchedule,
    AshareInventoryLedger,
    AshareLotPolicy,
    AshareOrderCompiler,
    AshareOrderCompilerConfig,
)


ROOT = Path(__file__).resolve().parents[1]
SSE = AssetId("600000", venue="SSE", currency="CNY")
STAR = AssetId("688001", venue="SSE", currency="CNY")
SZSE = AssetId("000001", venue="SZSE", currency="CNY")
CHINEXT = AssetId("300001", venue="SZSE", currency="CNY")
BSE = AssetId("920001", venue="BSE", currency="CNY")


def _write_parquet(csv_path: Path, parquet_path: Path) -> None:
    source = csv_path.resolve().as_posix().replace("'", "''")
    target = parquet_path.resolve().as_posix().replace("'", "''")
    duckdb.connect().execute(
        f"COPY (SELECT * FROM read_csv_auto('{source}', header=true)) "
        f"TO '{target}' (FORMAT PARQUET)"
    )


def _vendor(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    basic = root / "basic.csv"
    with basic.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ts_code", "name", "market", "list_date"])
        writer.writerow(["600000.SH", "A", "主板", "1999-01-01"])
        writer.writerow(["000001.SZ", "B", "主板", "1991-01-01"])
    _write_parquet(basic, root / "stock_basic_data.parquet")

    daily = root / "daily.csv"
    fields = [
        "ts_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "vol",
        "amount",
        "adj_factor",
        "up_limit",
        "down_limit",
        "is_st",
    ]
    rows = [
        {
            "ts_code": "600000.SH",
            "trade_date": "2024-01-02",
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "close": 10.2,
            "pre_close": 10.0,
            "vol": 100000,
            "amount": 1000000,
            "adj_factor": 1.0,
            "up_limit": 11.0,
            "down_limit": 9.0,
            "is_st": 0,
        },
        {
            "ts_code": "600000.SH",
            "trade_date": "2024-01-03",
            "open": 10.2,
            "high": 10.6,
            "low": 10.0,
            "close": 10.4,
            "pre_close": 10.2,
            "vol": 120000,
            "amount": 1200000,
            "adj_factor": 1.0,
            "up_limit": 11.22,
            "down_limit": 9.18,
            "is_st": 0,
        },
        {
            "ts_code": "600000.SH",
            "trade_date": "2024-01-04",
            "open": 11.44,
            "high": 11.44,
            "low": 11.44,
            "close": 11.44,
            "pre_close": 10.4,
            "vol": 50000,
            "amount": 550000,
            "adj_factor": 1.0,
            "up_limit": 11.44,
            "down_limit": 9.36,
            "is_st": 0,
        },
        {
            "ts_code": "000001.SZ",
            "trade_date": "2024-01-02",
            "open": 0.0,
            "high": 0.0,
            "low": 0.0,
            "close": 12.0,
            "pre_close": 12.0,
            "vol": 0,
            "amount": 0,
            "adj_factor": 1.0,
            "up_limit": 13.2,
            "down_limit": 10.8,
            "is_st": 0,
        },
    ]
    with daily.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    _write_parquet(daily, root / "stock_daily.parquet")


def _state(
    asset: AssetId,
    *,
    price: float = 10.0,
    upper: float | None = 11.0,
    lower: float | None = 9.0,
    status: AshareSessionStatus = AshareSessionStatus.TRADABLE,
    session: date = date(2024, 1, 2),
) -> AshareTradeability:
    return AshareTradeability(
        asset=asset,
        board=infer_ashare_board(asset),
        session_date=session,
        observed_at=datetime(session.year, session.month, session.day, 1, 30, tzinfo=UTC),
        status=status,
        execution_price=price if status not in {AshareSessionStatus.SUSPENDED, AshareSessionStatus.NO_SESSION_DATA} else None,
        mark_price=price,
        previous_close=price,
        upper_limit=upper,
        lower_limit=lower,
        volume=1_000_000 if status is AshareSessionStatus.TRADABLE else 0.0,
    )


def _snapshot(
    *states: AshareTradeability,
) -> AshareDailyExecutionSnapshot:
    session = states[0].session_date
    return AshareDailyExecutionSnapshot(
        session_date=session,
        asof=states[0].observed_at,
        states={state.asset: state for state in states},
        data_version="a3-test-data",
    )


def _target(
    asof: datetime,
    weights: dict[AssetId, float],
    cash_weight: float,
) -> PortfolioTarget:
    return PortfolioTarget(
        asof=asof,
        weights=weights,
        cash_weight=cash_weight,
        source=ModelRef("a3-test", "1"),
    )


def test_board_mapping_and_board_specific_lot_rules() -> None:
    assert infer_ashare_board(SSE) is AshareBoard.SSE_MAIN
    assert infer_ashare_board(STAR) is AshareBoard.SSE_STAR
    assert infer_ashare_board(SZSE) is AshareBoard.SZSE_MAIN
    assert infer_ashare_board(CHINEXT) is AshareBoard.SZSE_CHINEXT
    assert infer_ashare_board(BSE) is AshareBoard.BSE

    policy = AshareLotPolicy()
    assert policy.round_buy(AshareBoard.SSE_MAIN, 157)[0] == 100
    assert policy.round_buy(AshareBoard.SSE_STAR, 157)[0] == 0
    assert policy.round_buy(AshareBoard.SSE_STAR, 257.9)[0] == 257
    assert policy.round_buy(AshareBoard.BSE, 257)[0] == 200
    assert policy.round_sell(AshareBoard.SSE_MAIN, 160, 250)[0] == 150
    assert policy.round_sell(AshareBoard.SSE_MAIN, 250, 250)[0] == 250
    assert policy.round_sell(AshareBoard.SSE_STAR, 199, 500)[0] == 0
    assert policy.round_sell(AshareBoard.SSE_STAR, 250, 500)[0] == 250


def test_tradeability_is_side_specific_and_fail_closed() -> None:
    upper = _state(SSE, price=11.0)
    lower = _state(SSE, price=9.0)
    suspended = _state(SSE, status=AshareSessionStatus.SUSPENDED)
    limits_missing = _state(
        SSE,
        upper=None,
        lower=None,
        status=AshareSessionStatus.LIMITS_UNAVAILABLE,
    )

    assert upper.block_reason(OrderSide.BUY) is AshareOrderReason.BUY_BLOCKED_AT_LIMIT_UP
    assert upper.block_reason(OrderSide.SELL) is None
    assert lower.block_reason(OrderSide.SELL) is AshareOrderReason.SELL_BLOCKED_AT_LIMIT_DOWN
    assert lower.block_reason(OrderSide.BUY) is None
    assert suspended.block_reason(OrderSide.BUY) is AshareOrderReason.SUSPENDED
    assert suspended.block_reason(OrderSide.SELL) is AshareOrderReason.SUSPENDED
    assert limits_missing.block_reason(OrderSide.BUY) is AshareOrderReason.PRICE_LIMITS_UNAVAILABLE
    assert limits_missing.block_reason(OrderSide.BUY, require_price_limits=False) is None


def test_local_execution_adapter_uses_exact_session_not_stale_quote(tmp_path: Path) -> None:
    root = tmp_path / "vendor"
    _vendor(root)
    adapter = LocalAshareDailyExecutionAdapter(
        LocalAshareDatasetLayout(root),
        data_version="frozen-a3",
    )

    normal = adapter.snapshot(date(2024, 1, 2), (SSE, SZSE))
    assert normal.state(SSE).status is AshareSessionStatus.TRADABLE
    assert normal.state(SSE).execution_price == pytest.approx(10.0)
    assert normal.state(SZSE).status is AshareSessionStatus.SUSPENDED
    assert normal.state(SZSE).mark_price == pytest.approx(12.0)

    missing = adapter.snapshot(date(2024, 1, 3), (SSE, SZSE))
    assert missing.state(SZSE).status is AshareSessionStatus.NO_SESSION_DATA
    assert missing.state(SZSE).execution_price is None

    limit_up = adapter.snapshot(date(2024, 1, 4), (SSE,))
    assert limit_up.state(SSE).at_upper_limit is True
    assert limit_up.state(SSE).block_reason(OrderSide.BUY) is AshareOrderReason.BUY_BLOCKED_AT_LIMIT_UP


def test_fee_schedule_preserves_buy_sell_asymmetry() -> None:
    schedule = AshareFeeSchedule(
        broker_commission_rate=0.0003,
        minimum_broker_commission=5.0,
        stamp_duty_sell_rate=0.0005,
        transfer_fee_rate=0.00001,
    )
    buy = schedule.estimate(
        side=OrderSide.BUY,
        notional=10_000.0,
        board=AshareBoard.SSE_MAIN,
    )
    sell = schedule.estimate(
        side=OrderSide.SELL,
        notional=10_000.0,
        board=AshareBoard.SSE_MAIN,
    )
    assert buy.broker_commission == pytest.approx(5.0)
    assert buy.stamp_duty == 0.0
    assert buy.transfer_fee == pytest.approx(0.1)
    assert sell.stamp_duty == pytest.approx(5.0)
    assert sell.total > buy.total


def test_t1_inventory_same_day_sell_block_and_next_day_settlement() -> None:
    fees = AshareFeeSchedule(
        broker_commission_rate=0.0,
        minimum_broker_commission=0.0,
        stamp_duty_sell_rate=0.0005,
        transfer_fee_rate=0.0,
    )
    compiler = AshareOrderCompiler(
        config=AshareOrderCompilerConfig(slippage_bps=0.0),
        fee_schedule=fees,
    )
    session = AshareExecutionSession(compiler=compiler)
    day1 = _snapshot(_state(SSE, session=date(2024, 1, 2)))
    account = AshareAccountState(
        session_date=date(2024, 1, 1),
        cash=100_000.0,
    )
    buy_target = _target(
        datetime(2024, 1, 1, 8, 0, tzinfo=UTC),
        {SSE: 0.5},
        0.5,
    )
    buy_cycle = session.run(buy_target, account, day1)
    position = buy_cycle.state_after.position(SSE)
    assert position.total_quantity == 5000
    assert position.sellable_quantity == 0
    assert position.unsettled_quantity == 5000
    assert buy_cycle.execution.fills[0].fees.stamp_duty == 0.0

    same_day_exit = _target(
        datetime(2024, 1, 1, 9, 0, tzinfo=UTC),
        {SSE: 0.0},
        1.0,
    )
    same_day = compiler.compile(same_day_exit, buy_cycle.state_after, day1)
    assert same_day.orders == ()
    assert AshareOrderReason.T1_SELLABLE_QUANTITY_CLIPPED.value in (
        same_day.decisions[0].reason_codes
    )

    day2 = _snapshot(_state(SSE, price=10.2, upper=11.22, lower=9.18, session=date(2024, 1, 3)))
    exit_target = _target(
        datetime(2024, 1, 2, 8, 0, tzinfo=UTC),
        {SSE: 0.0},
        1.0,
    )
    exit_cycle = session.run(exit_target, buy_cycle.state_after, day2)
    assert exit_cycle.execution.fills[0].side is OrderSide.SELL
    assert exit_cycle.execution.fills[0].quantity == 5000
    assert exit_cycle.execution.fills[0].fees.stamp_duty > 0
    assert exit_cycle.state_after.position(SSE).total_quantity == 0
    assert exit_cycle.state_after.cash > account.cash


def test_compiler_applies_proportional_cash_scaling_and_deterministic_ids() -> None:
    fees = AshareFeeSchedule(
        broker_commission_rate=0.0003,
        minimum_broker_commission=5.0,
        stamp_duty_sell_rate=0.0005,
        transfer_fee_rate=0.00001,
    )
    compiler = AshareOrderCompiler(fee_schedule=fees)
    snapshot = _snapshot(_state(SSE), _state(SZSE))
    account = AshareAccountState(
        session_date=date(2024, 1, 2),
        cash=100_000.0,
    )
    target = _target(
        datetime(2024, 1, 1, 8, 0, tzinfo=UTC),
        {SSE: 0.5, SZSE: 0.5},
        0.0,
    )
    first = compiler.compile(target, account, snapshot)
    second = compiler.compile(target, account, snapshot)
    assert [order.client_order_id for order in first.orders] == [
        order.client_order_id for order in second.orders
    ]
    assert sum(
        decision.executable_quantity * decision.desired.reference_price
        + decision.estimated_fees.total
        for decision in first.decisions
        if decision.executable_order is not None and decision.desired.side is OrderSide.BUY
    ) <= account.cash + 1e-9
    assert any(
        AshareOrderReason.INSUFFICIENT_CASH_SCALED.value in decision.reason_codes
        for decision in first.decisions
    )


def test_target_must_be_prior_and_long_only() -> None:
    compiler = AshareOrderCompiler()
    snapshot = _snapshot(_state(SSE))
    account = AshareAccountState(
        session_date=date(2024, 1, 2),
        cash=100_000.0,
    )
    same_time = _target(snapshot.asof, {SSE: 0.5}, 0.5)
    with pytest.raises(ValueError, match="TARGET_INFORMATION_NOT_PRIOR"):
        compiler.compile(same_time, account, snapshot)
    short_target = _target(
        datetime(2024, 1, 1, 8, 0, tzinfo=UTC),
        {SSE: -0.1},
        1.1,
    )
    with pytest.raises(ValueError, match="LONG_ONLY_TARGET_REQUIRED"):
        compiler.compile(short_target, account, snapshot)


def test_a3_smoke_cli_runs_on_synthetic_local_parquet(tmp_path: Path) -> None:
    root = tmp_path / "vendor"
    _vendor(root)
    report = tmp_path / "report.json"
    config = tmp_path / "a3.toml"
    config.write_text(
        f'''
[ashare_execution_smoke]
root = "{root.as_posix()}"
data_version = "a3-smoke-data"
report_path = "{report.as_posix()}"
symbols = ["600000.SH"]
buy_session = 2024-01-02
sell_session = 2024-01-03
initial_cash = 100000.0
invested_weight = 0.5
broker_commission_rate = 0.0
minimum_broker_commission = 0.0
stamp_duty_sell_rate = 0.0005
transfer_fee_rate = 0.0
slippage_bps = 0.0
'''.strip()
        + "\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_ashare_execution_smoke.py"),
            str(config),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "finagent.ashare-execution-smoke.v1"
    assert payload["passed"] is True
    assert payload["checks"]["same_session_sell_blocked_by_t1"] is True
    assert payload["checks"]["next_session_sell_executed"] is True
    assert payload["checks"]["sell_stamp_duty_positive"] is True

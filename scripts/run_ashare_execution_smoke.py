#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tomllib
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from finagent.data.ashare_execution import LocalAshareDailyExecutionAdapter
from finagent.data.local_ashare import (
    SHANGHAI,
    LocalAshareDatasetLayout,
    _asset_from_ts_code,
)
from finagent.data.local_ashare_freeze import LocalAshareFrozenManifest
from finagent.domain.ashare_execution import (
    AshareAccountState,
    AshareOrderReason,
)
from finagent.domain.forecasts import ModelRef
from finagent.domain.orders import OrderSide
from finagent.domain.portfolio import PortfolioTarget
from finagent.services.ashare_execution import (
    AshareExecutionSession,
    AshareFeeSchedule,
    AshareOrderCompiler,
    AshareOrderCompilerConfig,
)


def _load(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    values = payload.get("ashare_execution_smoke")
    if not isinstance(values, dict):
        raise TypeError("configuration must contain [ashare_execution_smoke]")
    return values


def _date(value: object, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must use YYYY-MM-DD") from exc


def _symbols(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise TypeError("symbols must be a non-empty array")
    values = tuple(str(item).strip().upper() for item in value)
    if any(not item for item in values) or len(set(values)) != len(values):
        raise ValueError("symbols must contain unique non-empty ts_code values")
    return values


def _previous_close_information(session_date: date) -> datetime:
    local = datetime.combine(session_date - timedelta(days=1), time(16, 0), tzinfo=SHANGHAI)
    return local.astimezone(UTC)


def _same_day_close_information(session_date: date) -> datetime:
    local = datetime.combine(session_date, time(16, 0), tzinfo=SHANGHAI)
    return local.astimezone(UTC)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a deterministic local A-share A3 execution-semantics smoke. "
            "This is not a strategy backtest, reserve evaluation, promotion or PAPER run."
        )
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--verify-content", action="store_true")
    args = parser.parse_args()

    values = _load(args.config)
    root = args.root or Path(str(values["root"]))
    report_path = args.report or Path(str(values.get("report_path", "reports/ashare_execution_smoke.json")))
    layout = LocalAshareDatasetLayout(root)

    manifest_value = str(values.get("frozen_manifest", "")).strip()
    manifest_version = ""
    if manifest_value:
        manifest = LocalAshareFrozenManifest.read_json(Path(manifest_value))
        manifest.verify(layout, verify_content=bool(args.verify_content))
        manifest_version = manifest.dataset_version
    data_version = str(values.get("data_version", manifest_version or "local-ashare-a3-smoke")).strip()
    if not data_version:
        raise ValueError("data_version cannot be empty")

    assets = tuple(_asset_from_ts_code(value) for value in _symbols(values["symbols"]))
    buy_session = _date(values["buy_session"], "buy_session")
    sell_session = _date(values["sell_session"], "sell_session")
    if sell_session <= buy_session:
        raise ValueError("sell_session must be later than buy_session")
    initial_cash = float(values.get("initial_cash", 1_000_000.0))
    invested_weight = float(values.get("invested_weight", 0.8))
    if initial_cash <= 0 or not 0 < invested_weight < 1:
        raise ValueError("initial_cash must be > 0 and invested_weight must be in (0, 1)")

    fee_schedule = AshareFeeSchedule(
        broker_commission_rate=float(values.get("broker_commission_rate", 0.0003)),
        minimum_broker_commission=float(values.get("minimum_broker_commission", 5.0)),
        stamp_duty_sell_rate=float(values.get("stamp_duty_sell_rate", 0.0005)),
        transfer_fee_rate=float(values.get("transfer_fee_rate", 0.00001)),
        sse_szse_handling_rate=float(values.get("sse_szse_handling_rate", 0.0000341)),
        bse_handling_rate=float(values.get("bse_handling_rate", 0.000125)),
        regulatory_fee_rate=float(values.get("regulatory_fee_rate", 0.00002)),
        pass_through_exchange_handling=bool(
            values.get("pass_through_exchange_handling", False)
        ),
        pass_through_regulatory_fee=bool(
            values.get("pass_through_regulatory_fee", False)
        ),
    )
    compiler = AshareOrderCompiler(
        config=AshareOrderCompilerConfig(
            require_prior_information=True,
            require_price_limits=bool(values.get("require_price_limits", True)),
            minimum_notional=float(values.get("minimum_notional", 0.0)),
            slippage_bps=float(values.get("slippage_bps", 0.0)),
        ),
        fee_schedule=fee_schedule,
    )
    execution_session = AshareExecutionSession(compiler=compiler)
    adapter = LocalAshareDailyExecutionAdapter(
        layout,
        data_version=data_version,
        require_price_limits=compiler.config.require_price_limits,
    )
    buy_snapshot = adapter.snapshot(buy_session, assets)
    sell_snapshot = adapter.snapshot(sell_session, assets)

    initial_state = AshareAccountState(
        session_date=buy_session - timedelta(days=1),
        cash=initial_cash,
        metadata={"scope": "A3 execution-semantics smoke"},
    )
    per_asset = invested_weight / len(assets)
    buy_target = PortfolioTarget(
        asof=_previous_close_information(buy_session),
        weights={asset: per_asset for asset in assets},
        cash_weight=1.0 - invested_weight,
        source=ModelRef("ashare-execution-smoke", "A3"),
        metadata={"stage": "buy"},
    )
    buy_cycle = execution_session.run(buy_target, initial_state, buy_snapshot)

    same_session_exit = PortfolioTarget(
        asof=buy_snapshot.asof - timedelta(microseconds=1),
        weights={asset: 0.0 for asset in assets},
        cash_weight=1.0,
        source=ModelRef("ashare-execution-smoke", "A3"),
        metadata={"stage": "same_session_T+1_probe"},
    )
    same_session_compilation = compiler.compile(
        same_session_exit,
        buy_cycle.state_after,
        buy_snapshot,
    )

    exit_target = PortfolioTarget(
        asof=_same_day_close_information(buy_session),
        weights={asset: 0.0 for asset in assets},
        cash_weight=1.0,
        source=ModelRef("ashare-execution-smoke", "A3"),
        metadata={"stage": "next_session_exit"},
    )
    sell_cycle = execution_session.run(
        exit_target,
        buy_cycle.state_after,
        sell_snapshot,
    )

    buy_fills = tuple(
        fill for fill in buy_cycle.execution.fills if fill.side is OrderSide.BUY
    )
    sell_fills = tuple(
        fill for fill in sell_cycle.execution.fills if fill.side is OrderSide.SELL
    )
    same_session_reasons = {
        reason
        for decision in same_session_compilation.decisions
        for reason in decision.reason_codes
    }
    checks = {
        "buy_orders_executed": bool(buy_fills),
        "buy_inventory_unsettled": bool(buy_cycle.state_after.positions)
        and all(
            position.sellable_quantity == 0
            and position.unsettled_quantity == position.total_quantity
            for position in buy_cycle.state_after.positions.values()
        ),
        "same_session_sell_blocked_by_t1": (
            not same_session_compilation.orders
            and AshareOrderReason.T1_SELLABLE_QUANTITY_CLIPPED.value
            in same_session_reasons
        ),
        "next_session_sell_executed": bool(sell_fills),
        "positions_closed": all(
            sell_cycle.state_after.position(asset).total_quantity == 0
            for asset in assets
        ),
        "buy_stamp_duty_zero": all(fill.fees.stamp_duty == 0 for fill in buy_fills),
        "sell_stamp_duty_positive": all(fill.fees.stamp_duty > 0 for fill in sell_fills),
        "cash_non_negative": sell_cycle.state_after.cash >= 0,
        "integer_execution_quantities": all(
            isinstance(fill.quantity, int)
            for fill in (*buy_fills, *sell_fills)
        ),
    }
    passed = all(checks.values())
    payload = {
        "schema_version": "finagent.ashare-execution-smoke.v1",
        "scope": (
            "historical A-share execution-semantics acceptance only; no factor reserve, "
            "promotion, PAPER, realtime or live-capital claim"
        ),
        "passed": passed,
        "data_version": data_version,
        "manifest_version": manifest_version or None,
        "symbols": [asset.key for asset in assets],
        "buy_session": buy_session.isoformat(),
        "sell_session": sell_session.isoformat(),
        "fee_schedule": fee_schedule.to_dict(),
        "checks": checks,
        "buy_snapshot": buy_snapshot.to_dict(),
        "buy_cycle": buy_cycle.to_dict(),
        "same_session_compilation": same_session_compilation.to_dict(),
        "sell_snapshot": sell_snapshot.to_dict(),
        "sell_cycle": sell_cycle.to_dict(),
        "boundaries": {
            "long_only": True,
            "execution_price": "exact next-session open",
            "T_plus_1_inventory": True,
            "portfolio_economic_validation": False,
            "reserve_consumed": False,
            "promotion_eligible": False,
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

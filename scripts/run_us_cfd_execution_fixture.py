from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from finagent.backtest.us_cfd_execution import (
    CFDAccountSpec,
    CFDExecutionCostPolicy,
    CFDHistoricalStep,
    CFDInstrumentSpec,
    CFDReferencePrice,
    CFDTargetWeight,
    run_cfd_historical_execution,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a deterministic intraday CFD historical-execution fixture. "
            "The result validates execution accounting only and carries no Alpha, broker, "
            "PAPER, stage, or live-capital authority."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/development/us_cfd_historical_execution_fixture.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    start = datetime(2026, 9, 3, 14, 30, tzinfo=UTC)
    instrument = CFDInstrumentSpec(
        symbol="US500.CFD",
        contract_size=10.0,
        volume_min=0.1,
        volume_max=100.0,
        volume_step=0.1,
        margin_rate=0.10,
        tick_size=0.01,
        currency_profit="USD",
        currency_margin="USD",
    )
    report = run_cfd_historical_execution(
        account_spec=CFDAccountSpec(
            base_currency="USD",
            initial_balance=100_000.0,
            max_margin_utilization=0.50,
        ),
        instruments=(instrument,),
        cost_policy=CFDExecutionCostPolicy(
            spread_bps=10.0,
            slippage_bps=2.0,
            commission_bps=1.0,
        ),
        steps=(
            CFDHistoricalStep(
                asof=start,
                prices=(CFDReferencePrice("US500.CFD", 100.0),),
                targets=(CFDTargetWeight("US500.CFD", 0.50),),
            ),
            CFDHistoricalStep(
                asof=start + timedelta(minutes=60),
                prices=(CFDReferencePrice("US500.CFD", 101.0),),
                targets=(CFDTargetWeight("US500.CFD", 0.0),),
            ),
        ),
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    if output.exists():
        existing = output.read_text(encoding="utf-8")
        if existing != encoded:
            raise RuntimeError("existing CFD fixture differs; do not overwrite divergent evidence")
    else:
        output.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {
                "report_id": report.report_id,
                "passed": report.passed,
                "intraday_flat": not report.final_state.positions,
                "gross_pnl_before_costs": report.gross_pnl_before_costs,
                "total_transaction_cost": report.total_transaction_cost,
                "net_pnl": report.net_pnl,
                "broker_execution_authority": False,
                "paper_authority": False,
                "status_authority": False,
                "stage_exit_authority": False,
                "live_capital_authority": False,
                "output": str(output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

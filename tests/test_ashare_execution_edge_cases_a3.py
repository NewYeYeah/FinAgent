from __future__ import annotations

from datetime import UTC, date, datetime

from finagent.domain.ashare_execution import (
    AshareAccountState,
    AshareBoard,
    AshareDailyExecutionSnapshot,
    AshareOrderReason,
    AsharePosition,
    AshareSessionStatus,
    AshareTradeability,
)
from finagent.domain.assets import AssetId
from finagent.domain.forecasts import ModelRef
from finagent.domain.portfolio import PortfolioTarget
from finagent.services.ashare_execution import AshareExecutionSession


ASSET = AssetId("600000", venue="SSE", currency="CNY")


def test_missing_exact_session_preserves_mark_but_blocks_held_position_trade() -> None:
    session_date = date(2024, 1, 3)
    snapshot = AshareDailyExecutionSnapshot(
        session_date=session_date,
        asof=datetime(2024, 1, 3, 1, 30, tzinfo=UTC),
        states={
            ASSET: AshareTradeability(
                asset=ASSET,
                board=AshareBoard.SSE_MAIN,
                session_date=session_date,
                observed_at=datetime(2024, 1, 3, 1, 30, tzinfo=UTC),
                status=AshareSessionStatus.NO_SESSION_DATA,
            )
        },
        data_version="a3-edge-data",
    )
    state = AshareAccountState(
        session_date=date(2024, 1, 2),
        cash=0.0,
        positions={ASSET: AsharePosition(100, 100, 0)},
        marks={ASSET: 10.0},
    )
    target = PortfolioTarget(
        asof=datetime(2024, 1, 2, 8, 0, tzinfo=UTC),
        weights={ASSET: 0.0},
        cash_weight=1.0,
        source=ModelRef("a3-edge", "1"),
    )

    cycle = AshareExecutionSession().run(target, state, snapshot)

    assert cycle.state_before.nav == 1000.0
    assert cycle.compilation.pretrade_nav == 1000.0
    assert cycle.compilation.orders == ()
    assert cycle.execution.fills == ()
    assert cycle.state_after.position(ASSET).total_quantity == 100
    assert cycle.state_after.marks[ASSET] == 10.0
    assert cycle.compilation.decisions[0].reason_codes == (
        AshareOrderReason.NO_SESSION_DATA.value,
    )

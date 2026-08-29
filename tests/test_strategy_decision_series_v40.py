from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from finagent.backtest.strategy_decision_series import (
    StrategyDecisionSeriesProjection,
    canonical_execution_ledger_digest,
    materialize_strategy_decision_rows,
    write_strategy_decision_series,
)
from tests.test_ashare_portfolio_validation_a4 import (
    test_a4_cli_runs_internal_execution_validation_and_exact_replay as _prepare_a4,
)


ROOT = Path(__file__).resolve().parents[1]
ASSET = "equity:SSE:600000:CNY"


def _state(*, cash: float, quantity: int, mark: float | None) -> dict[str, object]:
    positions = (
        {
            ASSET: {
                "total_quantity": quantity,
                "sellable_quantity": quantity,
                "unsettled_quantity": 0,
            }
        }
        if quantity
        else {}
    )
    marks = {ASSET: mark} if quantity and mark is not None else {}
    nav = cash + (quantity * mark if quantity and mark is not None else 0.0)
    return {
        "session_date": "2024-01-02",
        "cash": cash,
        "nav": nav,
        "base_currency": "CNY",
        "positions": positions,
        "marks": marks,
        "metadata": {},
    }


def _fill(*, price: float, fees: float, slippage: float, order_id: str) -> dict[str, object]:
    return {
        "client_order_id": order_id,
        "asset": ASSET,
        "side": "buy",
        "quantity": 50,
        "reference_price": 10.0,
        "execution_price": price,
        "executed_at": "2024-01-02T01:30:00+00:00",
        "notional": 50 * price,
        "fees": {
            "broker_commission": fees,
            "stamp_duty": 0.0,
            "transfer_fee": 0.0,
            "exchange_handling_fee": 0.0,
            "regulatory_fee": 0.0,
            "total": fees,
        },
        "slippage": slippage,
        "metadata": {},
    }


def _decision(order_id: str) -> dict[str, object]:
    return {
        "desired": {
            "asset": ASSET,
            "side": "buy",
            "requested_quantity": 50.0,
            "current_quantity": 0,
            "target_quantity": 50.0,
            "reference_price": 10.0,
        },
        "status": "accepted",
        "executable_quantity": 50,
        "rejected_quantity": 0.0,
        "reason_codes": ["ACCEPTED"],
        "estimated_fees": {"total": 1.0},
        "client_order_id": order_id,
    }


def _cycle(*, price: float, fees: float, slippage: float, order_id: str) -> dict[str, object]:
    state_before = _state(cash=1000.0, quantity=0, mark=None)
    fill = _fill(price=price, fees=fees, slippage=slippage, order_id=order_id)
    cash_after = 1000.0 - 50 * price - fees
    state_after = _state(cash=cash_after, quantity=50, mark=price)
    return {
        "compilation": {
            "session_date": "2024-01-02",
            "pretrade_nav": 1000.0,
            "available_cash_before_buys": 1000.0,
            "estimated_total_fees": fees,
            "orders": [order_id],
            "decisions": [_decision(order_id)],
            "metadata": {},
        },
        "execution": {
            "session_date": "2024-01-02",
            "orders": [order_id],
            "fills": [fill],
            "rejections": {},
            "total_fees": fees,
            "total_slippage": slippage,
            "metadata": {},
        },
        "state_before": state_before,
        "state_after": state_after,
    }


def _synthetic_ledger() -> tuple[dict[str, object], ...]:
    net_close_1 = _state(cash=494.0, quantity=50, mark=11.0)
    gross_close_1 = _state(cash=500.0, quantity=50, mark=11.0)
    net_close_2 = _state(cash=494.0, quantity=50, mark=12.0)
    gross_close_2 = _state(cash=500.0, quantity=50, mark=12.0)
    return (
        {
            "fold_id": "wf-1",
            "point": {
                "session_date": "2024-01-02",
                "signal_asof": "2024-01-02T01:29:59.999999+00:00",
                "rebalanced": True,
                "cash_fallback": False,
                "target_id": "a4-target-1",
            },
            "target": {
                "asof": "2024-01-02T01:29:59.999999+00:00",
                "weights": {ASSET: 0.5},
                "cash_weight": 0.5,
                "metadata": {"reason": "MODEL_TARGET"},
            },
            "net_cycle": _cycle(price=10.1, fees=1.0, slippage=5.0, order_id="net-1"),
            "gross_cycle": _cycle(price=10.0, fees=0.0, slippage=0.0, order_id="gross-1"),
            "net_close_state": net_close_1,
            "gross_close_state": gross_close_1,
            "ex_post_close_snapshot": {
                "session_date": "2024-01-02",
                "asof": "2024-01-02T08:00:00+00:00",
                "data_version": "data-v1",
                "marks": {ASSET: 11.0},
            },
        },
        {
            "fold_id": "wf-1",
            "point": {
                "session_date": "2024-01-03",
                "signal_asof": "2024-01-03T01:29:59.999999+00:00",
                "rebalanced": False,
                "cash_fallback": False,
                "target_id": "",
            },
            "target": None,
            "net_cycle": None,
            "gross_cycle": None,
            "net_close_state": net_close_2,
            "gross_close_state": gross_close_2,
            "ex_post_close_snapshot": {
                "session_date": "2024-01-03",
                "asof": "2024-01-03T08:00:00+00:00",
                "data_version": "data-v1",
                "marks": {ASSET: 12.0},
            },
        },
    )


def _alpha(fold_id: str, signal_asof: datetime):
    assert fold_id == "wf-1"
    assert signal_asof == datetime(2024, 1, 2, 1, 29, 59, 999999, tzinfo=UTC)
    return {
        ASSET: {
            "score": 1.25,
            "rank": 1,
            "expected_return": 0.02,
            "uncertainty": 0.01,
        }
    }


def _write_jsonl(path: Path, rows: tuple[dict[str, object], ...]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    row,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                + "\n"
            )


def test_v40_rows_preserve_decision_path_and_reconcile_asset_pnl() -> None:
    ledger = _synthetic_ledger()
    digest = canonical_execution_ledger_digest(ledger)
    rows = materialize_strategy_decision_rows(
        ledger_rows=ledger,
        expected_ledger_digest=digest,
        initial_cash=1000.0,
        alpha_provider=_alpha,
    )
    assert len(rows) == 2
    first, second = rows
    assert first.session_date == date(2024, 1, 2)
    assert first.alpha_score == pytest.approx(1.25)
    assert first.alpha_rank == 1
    assert first.alpha_expected_return == pytest.approx(0.02)
    assert first.pre_trade_weight == pytest.approx(0.0)
    assert first.target_weight == pytest.approx(0.5)
    assert first.realized_weight == pytest.approx(550.0 / 1044.0)
    assert first.desired_quantity == pytest.approx(50.0)
    assert first.executable_quantity == 50
    assert first.filled_quantity == 50
    assert first.reference_price == pytest.approx(10.0)
    assert first.fill_price == pytest.approx(10.1)
    assert first.close_price == pytest.approx(11.0)
    assert first.fees == pytest.approx(1.0)
    assert first.slippage == pytest.approx(5.0)
    assert first.gross_pnl == pytest.approx(50.0)
    assert first.net_pnl == pytest.approx(44.0)
    assert first.constraint_codes == ("ACCEPTED",)

    assert second.session_date == date(2024, 1, 3)
    assert second.alpha_score is None
    assert second.target_weight is None
    assert second.gross_pnl == pytest.approx(50.0)
    assert second.net_pnl == pytest.approx(50.0)
    assert [row.row_id for row in rows] == [row.row_id for row in rows]


def test_v40_manifest_and_projection_are_identity_bound_and_bounded(tmp_path: Path) -> None:
    ledger = _synthetic_ledger()
    ledger_digest = canonical_execution_ledger_digest(ledger)
    report = {
        "schema_version": "finagent.ashare-portfolio-validation.v1",
        "portfolio_validation_id": "a4-validation-v40",
        "ledger_digest": ledger_digest,
        "validation_spec": {
            "spec_id": "a4-spec-v40",
            "source_program_result_id": "program-result-v40",
            "source_program_spec_id": "program-spec-v40",
            "source_selection_id": "selection-v40",
            "source_report_digest": "f" * 64,
            "data_version": "data-v1",
            "selected_feature_digests": ["factor-v40"],
            "selected_weights": [1.0],
            "selected_directions": [1],
            "validation_config": {"initial_cash": 1000.0},
        },
    }
    report_path = tmp_path / "a4.json"
    ledger_path = tmp_path / "a4.jsonl"
    manifest_path = tmp_path / "a4.strategy-decisions.json"
    data_path = tmp_path / "a4.strategy-decisions.parquet"
    report_path.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    _write_jsonl(ledger_path, ledger)
    rows = materialize_strategy_decision_rows(
        ledger_rows=ledger,
        expected_ledger_digest=ledger_digest,
        initial_cash=1000.0,
        alpha_provider=_alpha,
    )
    manifest = write_strategy_decision_series(
        a4_report=report,
        rows=rows,
        source_report_path=report_path,
        source_ledger_path=ledger_path,
        manifest_path=manifest_path,
        data_path=data_path,
    )
    assert manifest.authority == "authoritative"
    assert manifest.row_count == 2
    assert manifest.source_session_count == 2
    assert manifest.row_session_count == 2
    assert manifest.asset_count == 1
    assert manifest.series_id.startswith("strategy-decision-series-")

    projection = StrategyDecisionSeriesProjection(manifest_path)
    selected = projection.query(
        asset=ASSET,
        start=date(2024, 1, 2),
        end=date(2024, 1, 2),
        fold_id="wf-1",
        limit=10,
    )
    assert selected["authority"] == "authoritative"
    assert selected["total"] == 1
    item = selected["items"][0]
    assert item["asset"] == ASSET
    assert item["alpha_rank"] == 1
    assert item["constraint_codes"] == ["ACCEPTED"]
    with pytest.raises(ValueError, match="limit"):
        projection.query(limit=5001)
    with pytest.raises(ValueError, match="end cannot be before start"):
        projection.query(start=date(2024, 1, 3), end=date(2024, 1, 2))

    original = data_path.read_bytes()
    data_path.write_bytes(original + b"tamper")
    with pytest.raises(ValueError, match="Parquet SHA-256 mismatch"):
        StrategyDecisionSeriesProjection(manifest_path)


def test_v40_cli_materializes_from_real_a4_without_mutating_a4(tmp_path: Path) -> None:
    _prepare_a4(tmp_path)
    report = tmp_path / "a4.json"
    ledger = tmp_path / "a4.jsonl"
    config = tmp_path / "a4.toml"
    before_report = report.read_bytes()
    before_ledger = ledger.read_bytes()

    first_manifest = tmp_path / "v40-first.json"
    first_data = tmp_path / "v40-first.parquet"
    command = [
        sys.executable,
        str(ROOT / "scripts" / "materialize_strategy_decision_series.py"),
        str(config),
        "--a4-report",
        str(report),
        "--ledger",
        str(ledger),
        "--manifest",
        str(first_manifest),
        "--data",
        str(first_data),
    ]
    first = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr + first.stdout
    first_payload = json.loads(first_manifest.read_text(encoding="utf-8"))
    assert first_payload["schema_version"] == "finagent.strategy-decision-series.manifest.v1"
    assert first_payload["authority"] == "authoritative"
    assert first_payload["portfolio_validation_id"] == json.loads(
        report.read_text(encoding="utf-8")
    )["portfolio_validation_id"]
    assert first_payload["row_count"] > 0
    assert first_payload["source_session_count"] > 400
    projection = StrategyDecisionSeriesProjection(first_manifest)
    sample = projection.query(limit=100)
    assert sample["total"] == first_payload["row_count"]
    assert sample["items"]
    assert any(item["alpha_score"] is not None for item in sample["items"])

    second_manifest = tmp_path / "v40-second.json"
    second_data = tmp_path / "v40-second.parquet"
    second = subprocess.run(
        [
            *command[:-4],
            "--manifest",
            str(second_manifest),
            "--data",
            str(second_data),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr + second.stdout
    second_payload = json.loads(second_manifest.read_text(encoding="utf-8"))
    assert second_payload["series_id"] == first_payload["series_id"]
    assert second_payload["rows_digest"] == first_payload["rows_digest"]
    assert report.read_bytes() == before_report
    assert ledger.read_bytes() == before_ledger

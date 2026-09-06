from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import duckdb
import pytest

from finagent.data.minute_store import manifest_from_directory
from finagent.domain.trading_calendar import TradingSession
from finagent.research.us_r3_economic_campaign import freeze_campaign, run_campaign
from finagent.research.us_r3_economics import EconomicPolicy
from finagent.research.us_r3_minute_liquidity import audit_campaign, audit_ledger
from tests.test_us_r3_economic_campaign import fixture_inputs


def test_exact_minute_clock_signed_netting_and_capital_scaling() -> None:
    session = TradingSession(
        date(2025, 1, 2),
        datetime(2025, 1, 2, 14, 30, tzinfo=UTC),
        datetime(2025, 1, 2, 21, tzinfo=UTC),
    )
    clock = session.open_at + timedelta(minutes=5)
    ledger = [
        {
            "bar_index": 0,
            "reference_minutes": 5,
            "net_trades": {"A": -0.01, "B": 0},
            "gross_traded_notional": 1.0,
        }
    ]
    bars = {("A", clock): (100.0, 1000.0), ("A", clock + timedelta(minutes=1)): (999.0, 1.0)}
    result = audit_ledger(ledger, bars, session, opening_capital=1000, participation_limit=0.01)
    assert result["trade_legs"] == result["matched_legs"] == 1
    assert result["max_positive_volume_participation"] == 0.01
    assert result["all_legs_volume_proxy_capital_ceiling"] == 1000
    assert result["over_limit_legs"] == result["notional_mismatch_frames"] == 0
    larger = audit_ledger(ledger, bars, session, opening_capital=2000, participation_limit=0.01)
    assert larger["over_limit_legs"] == 1
    assert larger["max_positive_volume_participation"] == 0.02
    del bars["A", clock]
    missing = audit_ledger(ledger, bars, session, opening_capital=1000, participation_limit=0.01)
    assert missing["missing_minutes"] == 1
    assert missing["all_legs_volume_proxy_capital_ceiling"] is None


def test_zero_volume_mismatched_prices_and_half_day_boundary() -> None:
    session = TradingSession(
        date(2025, 11, 28),
        datetime(2025, 11, 28, 14, 30, tzinfo=UTC),
        datetime(2025, 11, 28, 18, tzinfo=UTC),
        is_half_day=True,
    )
    frame = {
        "bar_index": 41,
        "reference_minutes": 5,
        "net_trades": {"A": 0.01},
        "gross_traded_notional": 1.0,
    }
    result = audit_ledger(
        [frame],
        {("A", session.close_at): (200.0, 0.0)},
        session,
        opening_capital=1000,
        participation_limit=0.01,
    )
    assert result["zero_volume_legs"] == result["notional_mismatch_frames"] == 1
    assert result["all_legs_volume_proxy_capital_ceiling"] == 0
    frame["bar_index"] = 42
    with pytest.raises(ValueError, match="outside session"):
        audit_ledger([frame], {}, session, opening_capital=1000, participation_limit=0.01)


@pytest.mark.parametrize("capital,limit", [(0, 0.01), (float("nan"), 0.01), (100, 0), (100, 1.1)])
def test_invalid_policy(capital, limit) -> None:
    session = TradingSession(
        date(2025, 1, 2),
        datetime(2025, 1, 2, 14, 30, tzinfo=UTC),
        datetime(2025, 1, 2, 21, tzinfo=UTC),
    )
    with pytest.raises(ValueError):
        audit_ledger([], {}, session, opening_capital=capital, participation_limit=limit)


def test_real_store_campaign_all_arms_and_immutable_replay(tmp_path) -> None:
    inputs = fixture_inputs(tmp_path / "input", five_minute=True)
    root = tmp_path / "campaign"
    protocol = root / "protocol.json"
    freeze_campaign(
        *inputs,
        protocol,
        start=date(2025, 1, 2),
        end=date(2025, 1, 3),
        policy=EconomicPolicy(
            minimum_breadth=3, selection_count=1, execution_profile="pending_exit_5m"
        ),
    )
    run_campaign(protocol, root)
    raw = tmp_path / "ohlcv_2025-01.parquet"
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TEMP TABLE raw AS SELECT available_at - INTERVAL '1 minute' AS timestamp, "
            "open, high, low, close, volume, research_asset_id AS ticker "
            "FROM read_parquet(?) WHERE slice_id = 'frequency_5m_60m'",
            [str(inputs[0])],
        )
        connection.execute("COPY raw TO ? (FORMAT PARQUET)", [str(raw)])
    manifest = manifest_from_directory(
        tmp_path,
        source_id="fixture",
        source_revision="v1",
        inventory_id="fixture",
        cleaning_identity="fixture",
    )
    report = audit_campaign(
        root, manifest, tmp_path / "out", start=date(2025, 1, 2), end=date(2025, 1, 3)
    )
    assert report["scheduled_sessions"] == 2
    assert len(report["strategies"]) == 7
    assert all(r["complete_ledger_reference_check"] for r in report["strategies"].values())
    assert report["strategies"]["cash"]["all_legs_volume_proxy_capital_ceiling"] is None
    assert report["daily"][0]["expected_regular_minutes"] == 4 * 390
    assert report["daily"][0]["observed_regular_minutes"] == 4 * 78
    assert (
        audit_campaign(
            root, manifest, tmp_path / "out", start=date(2025, 1, 2), end=date(2025, 1, 3)
        )
        == report
    )
    with pytest.raises(ValueError, match="immutable evidence mismatch"):
        audit_campaign(
            root,
            manifest,
            tmp_path / "out",
            start=date(2025, 1, 2),
            end=date(2025, 1, 3),
            opening_capital=200_000,
        )
    (root / "sessions/2025-01-03.json").unlink()
    with pytest.raises(FileNotFoundError):
        audit_campaign(
            root, manifest, tmp_path / "missing", start=date(2025, 1, 2), end=date(2025, 1, 3)
        )

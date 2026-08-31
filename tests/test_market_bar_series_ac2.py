from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from finagent.data.market_bar_series import (
    MarketBarSeriesEvidence,
    ashare_session_spec,
    write_market_bar_series,
)
from finagent.domain.market_bars import (
    BarInterval,
    BarTimestampConvention,
    LabelHorizonMode,
    LabelHorizonPolicy,
    MarketBarRow,
)
from finagent.visualization.strategy_explorer import StrategyDecisionExplorerProjection
from finagent.visualization.workbench_api import create_workspace_app
from tests.test_strategy_explorer_v42 import _write_v40
from tests.test_strategy_decision_series_v40 import ASSET


def _rows(data_version: str = "data-v42") -> tuple[MarketBarRow, ...]:
    return (
        MarketBarRow(
            asset=ASSET,
            session_date=date(2024, 1, 2),
            event_time=datetime(2024, 1, 2, 1, 30, tzinfo=UTC),
            available_at=datetime(2024, 1, 2, 8, 0, tzinfo=UTC),
            interval=BarInterval.DAY_1,
            open=10.0,
            high=11.5,
            low=9.8,
            close=11.0,
            volume=1_000_000.0,
            session_id="CN_A_SHARE:2024-01-02",
            session_type="regular",
            source="synthetic-certified-ashare",
            data_version=data_version,
        ),
        MarketBarRow(
            asset=ASSET,
            session_date=date(2024, 1, 3),
            event_time=datetime(2024, 1, 3, 1, 30, tzinfo=UTC),
            available_at=datetime(2024, 1, 3, 8, 0, tzinfo=UTC),
            interval=BarInterval.DAY_1,
            open=11.1,
            high=12.4,
            low=10.9,
            close=12.0,
            volume=1_200_000.0,
            session_id="CN_A_SHARE:2024-01-03",
            session_type="regular",
            source="synthetic-certified-ashare",
            data_version=data_version,
        ),
    )


def _write_ac2(
    root: Path,
    strategy_series_id: str,
    validation_id: str,
    *,
    data_version: str = "data-v42",
    suffix: str = "",
) -> str:
    manifest = write_market_bar_series(
        linked_strategy_series_id=strategy_series_id,
        portfolio_validation_id=validation_id,
        source_identity=f"synthetic-certified-ashare:{data_version}:{suffix or 'base'}",
        data_version=data_version,
        interval=BarInterval.DAY_1,
        timestamp_convention=BarTimestampConvention.SESSION_OPEN,
        session_spec=ashare_session_spec(),
        label_horizon_policy=LabelHorizonPolicy(
            LabelHorizonMode.TRADING_DAYS,
            1,
            True,
        ),
        rows=_rows(data_version),
        manifest_path=root / f"market-bars{suffix}.json",
        data_path=root / f"market-bars{suffix}.parquet",
    )
    return manifest.series_id


def test_ac2_domain_contract_rejects_lookahead_and_cross_session_same_session() -> None:
    try:
        MarketBarRow(
            asset=ASSET,
            session_date=date(2024, 1, 2),
            event_time=datetime(2024, 1, 2, 8, 0, tzinfo=UTC),
            available_at=datetime(2024, 1, 2, 7, 59, tzinfo=UTC),
            interval=BarInterval.MINUTE_1,
            open=10.0,
            high=10.1,
            low=9.9,
            close=10.0,
            volume=1.0,
            session_id="session",
            session_type="regular",
            source="test",
            data_version="v1",
        )
    except ValueError as exc:
        assert "available_at" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("look-ahead MarketBarRow must be rejected")

    try:
        LabelHorizonPolicy(LabelHorizonMode.SAME_SESSION, 1, True)
    except ValueError as exc:
        assert "same-session" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("same-session policy cannot cross sessions")

    spec = ashare_session_spec()
    assert spec.timezone == "Asia/Shanghai"
    assert [(segment.start, segment.end) for segment in spec.segments] == [
        ("09:30", "11:30"),
        ("13:00", "15:00"),
    ]


def test_ac2_market_bar_manifest_and_projection_are_content_verified(tmp_path: Path) -> None:
    _, strategy_series_id, validation_id = _write_v40(tmp_path)
    market_series_id = _write_ac2(tmp_path, strategy_series_id, validation_id)

    evidence = MarketBarSeriesEvidence(tmp_path / "market-bars.json")
    assert evidence.manifest.series_id == market_series_id
    assert evidence.manifest.linked_strategy_series_id == strategy_series_id
    assert evidence.manifest.portfolio_validation_id == validation_id
    assert evidence.manifest.interval is BarInterval.DAY_1
    assert evidence.manifest.timestamp_convention is BarTimestampConvention.SESSION_OPEN
    assert evidence.manifest.label_horizon_policy.mode is LabelHorizonMode.TRADING_DAYS

    query = evidence.query(asset=ASSET, start=date(2024, 1, 2), end=date(2024, 1, 3))
    assert query["read_only"] is True
    assert query["authority"] == "authoritative"
    assert query["total"] == 2
    assert query["items"][0]["open"] == 10.0
    assert query["items"][0]["high"] == 11.5
    assert query["items"][0]["low"] == 9.8
    assert query["items"][0]["close"] == 11.0


def test_ac2_strategy_binds_verified_market_bars_and_exposes_get_only_routes(
    tmp_path: Path,
) -> None:
    _, strategy_series_id, validation_id = _write_v40(tmp_path)
    market_series_id = _write_ac2(tmp_path, strategy_series_id, validation_id)

    projection = StrategyDecisionExplorerProjection((tmp_path,))
    item = projection.item(strategy_series_id)
    assert item.ohlc_available is True
    assert item.market_bar_series_id == market_series_id
    assert item.market_bar_interval == "1d"
    dimensions = projection.dimensions(strategy_series_id)
    assert dimensions["ohlc_available"] is True
    assert dimensions["market_bar_series_id"] == market_series_id
    assert dimensions["price_semantics"] == "OHLC from bound MarketBarSeriesEvidence"
    assert projection.status()["ohlc_authority"] == "MarketBarSeriesEvidence"

    app = create_workspace_app(
        report_paths=(tmp_path,),
        config_paths=(),
        frontend_dir=None,
    )
    client = TestClient(app)

    status = client.get("/api/v3/workbench/status").json()
    assert status["linked_analytics_acceptance"]["accepted"] is True
    assert all(status["linked_analytics_acceptance"]["runtime_checks"].values())

    catalog = client.get("/api/v4/strategy-series").json()
    strategy_item = catalog["items"][0]
    assert strategy_item["ohlc_available"] is True
    assert strategy_item["market_bar_series_id"] == market_series_id

    binding = client.get(
        f"/api/v4/strategy-series/{strategy_series_id}/market-bar-binding"
    )
    assert binding.status_code == 200
    assert binding.json()["authority"] == "authoritative"
    assert binding.json()["browser_recomputation"] is False
    assert binding.json()["interval"] == "1d"

    bars = client.get(
        f"/api/v4/strategy-series/{strategy_series_id}/market-bars",
        params={
            "asset": ASSET,
            "start": "2024-01-02",
            "end": "2024-01-03",
            "limit": 5000,
        },
    )
    assert bars.status_code == 200
    payload = bars.json()
    assert payload["authority"] == "authoritative"
    assert payload["total"] == 2
    assert [row["close"] for row in payload["items"]] == [11.0, 12.0]

    assert client.get(
        f"/api/v4/strategy-series/{strategy_series_id}/market-bars",
        params={"limit": 5001},
    ).status_code == 422
    assert client.post(
        f"/api/v4/strategy-series/{strategy_series_id}/market-bars"
    ).status_code == 405
    assert client.post(
        f"/api/v4/strategy-series/{strategy_series_id}/market-bar-binding"
    ).status_code == 405


def test_ac2_mismatched_market_data_version_is_fail_closed(tmp_path: Path) -> None:
    _, strategy_series_id, validation_id = _write_v40(tmp_path)
    _write_ac2(
        tmp_path,
        strategy_series_id,
        validation_id,
        data_version="different-data-version",
    )

    projection = StrategyDecisionExplorerProjection((tmp_path,))
    item = projection.item(strategy_series_id)
    assert item.ohlc_available is False
    assert item.market_bar_series_id is None
    assert projection.status()["ohlc_authority"] == "unavailable"
    assert any("data_version does not match" in warning for warning in projection.warnings)

    app = create_workspace_app(
        report_paths=(tmp_path,),
        config_paths=(),
        frontend_dir=None,
    )
    client = TestClient(app)
    response = client.get(
        f"/api/v4/strategy-series/{strategy_series_id}/market-bars"
    )
    assert response.status_code == 404
    assert "unavailable" in response.json()["detail"]
    acceptance = client.get("/api/v4/linked-analytics/status").json()
    assert acceptance["accepted"] is True
    assert all(acceptance["runtime_checks"].values())


def test_ac2_conflicting_market_bar_bindings_are_fail_closed(tmp_path: Path) -> None:
    _, strategy_series_id, validation_id = _write_v40(tmp_path)
    _write_ac2(tmp_path, strategy_series_id, validation_id)
    _write_ac2(tmp_path, strategy_series_id, validation_id, suffix="-other")

    projection = StrategyDecisionExplorerProjection((tmp_path,))
    assert projection.item(strategy_series_id).ohlc_available is False
    assert any("multiple MarketBarSeries bind" in warning for warning in projection.warnings)

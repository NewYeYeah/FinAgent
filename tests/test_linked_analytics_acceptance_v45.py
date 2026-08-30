from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from finagent.visualization.portfolio_execution import (
    PortfolioExecutionInteractiveProjection,
)
from finagent.visualization.workbench_api import create_workspace_app
from tests.test_portfolio_execution_v44 import _write_v44

pytest_plugins = ("tests.test_factor_series_v41",)


V4_READ_ONLY_PREFIXES = (
    "/api/v4/strategy-series",
    "/api/v4/factor-series",
    "/api/v4/portfolio-execution",
    "/api/v4/linked-analytics",
)


def test_v45_accepts_the_linked_v4_system_as_one_read_only_product(
    v41_evidence: dict[str, object],
) -> None:
    root = Path(v41_evidence["root"])
    validation_id, strategy_series_id = _write_v44(root)
    app = create_workspace_app(
        report_paths=(root,),
        config_paths=(),
        frontend_dir=None,
    )
    client = TestClient(app)

    workbench_response = client.get("/api/v3/workbench/status")
    assert workbench_response.status_code == 200
    workbench = workbench_response.json()
    assert workbench["version"] == "finagent-workbench-api-v4.5"
    assert workbench["read_only"] is True
    assert workbench["evidence_plane"] is True
    assert workbench["control_plane_enabled"] is False
    assert workbench["command_execution_enabled"] is False

    acceptance = workbench["linked_analytics_acceptance"]
    assert acceptance["accepted"] is True
    assert acceptance["authority"] == "acceptance_contract_only_no_financial_authority"
    assert acceptance["browser_recomputation"] is False
    assert acceptance["browser_row_limit"] == 5000
    assert acceptance["server_side_pagination_required_for_full_aggregates"] is True
    assert acceptance["evidence_plane_methods"] == ["GET", "HEAD", "OPTIONS"]
    assert acceptance["control_authority_ceiling"] == ["L0", "L1"]
    assert acceptance["missing_evidence_policy"] == "explicit_unavailable_not_inferred"
    assert set(acceptance["context_keys"]) == {
        "program_id",
        "factor_id",
        "portfolio_validation_id",
        "asset_id",
        "order_id",
        "date_range",
        "session_date",
        "fold_id",
    }
    assert all(acceptance["runtime_checks"].values())

    surface_by_name = {
        surface["surface"]: surface for surface in acceptance["surfaces"]
    }
    assert set(surface_by_name) == {"strategy", "factors", "portfolio", "execution"}
    assert "StrategyDecisionSeriesEvidence V4-0" in surface_by_name["strategy"][
        "required_evidence"
    ]
    assert "OHLC candlesticks" in surface_by_name["strategy"][
        "unavailable_not_inferred"
    ]
    assert "Agent generation chronology" in surface_by_name["factors"][
        "unavailable_not_inferred"
    ]
    assert "benchmark return/NAV" in surface_by_name["portfolio"][
        "unavailable_not_inferred"
    ]
    assert "capacity/impact model" in surface_by_name["execution"][
        "unavailable_not_inferred"
    ]
    assert all(surface["browser_recomputation"] is False for surface in surface_by_name.values())

    status_response = client.get("/api/v4/linked-analytics/status")
    assert status_response.status_code == 200
    assert status_response.json() == acceptance
    assert client.post("/api/v4/linked-analytics/status").status_code == 405

    strategy_catalog = client.get("/api/v4/strategy-series").json()
    assert strategy_catalog["items"][0]["series_id"] == strategy_series_id
    strategy_detail = client.get(
        f"/api/v4/strategy-series/{strategy_series_id}"
    ).json()
    assert strategy_detail["presentation"]["browser_recomputation"] is False
    assert strategy_detail["presentation"]["ohlc_available"] is False

    factor_catalog = client.get("/api/v4/factor-series").json()
    factor_series_id = factor_catalog["items"][0]["series_id"]
    factor_detail = client.get(f"/api/v4/factor-series/{factor_series_id}").json()
    factor_provenance = client.get(
        f"/api/v4/factor-series/{factor_series_id}/provenance"
    ).json()
    assert factor_detail["presentation"]["browser_recomputation"] is False
    assert factor_detail["presentation"]["agent_chronology_available"] is False
    assert factor_provenance["agent_chronology_available"] is False

    portfolio_detail = client.get(
        f"/api/v4/portfolio-execution/{validation_id}"
    ).json()
    assert portfolio_detail["presentation"]["browser_recomputation"] is False
    assert portfolio_detail["presentation"]["benchmark_available"] is False
    assert portfolio_detail["presentation"]["order_id_available"] is True

    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith(V4_READ_ONLY_PREFIXES):
            continue
        methods = set(getattr(route, "methods", set()) or set())
        assert methods <= {"GET", "HEAD", "OPTIONS"}, (path, methods)


def test_v45_all_linked_row_endpoints_keep_the_5000_browser_bound(
    v41_evidence: dict[str, object],
) -> None:
    root = Path(v41_evidence["root"])
    validation_id, strategy_series_id = _write_v44(root)
    app = create_workspace_app(
        report_paths=(root,),
        config_paths=(),
        frontend_dir=None,
    )
    client = TestClient(app)

    factor_series_id = client.get("/api/v4/factor-series").json()["items"][0][
        "series_id"
    ]
    bounded_requests = (
        f"/api/v4/strategy-series/{strategy_series_id}/decisions",
        f"/api/v4/factor-series/{factor_series_id}/rows",
        f"/api/v4/portfolio-execution/{validation_id}/series",
        f"/api/v4/portfolio-execution/{validation_id}/decisions",
    )
    for path in bounded_requests:
        assert client.get(path, params={"limit": 5000}).status_code == 200
        assert client.get(path, params={"limit": 5001}).status_code == 422


class _AnnualizationWorkspace:
    def portfolio_cockpit(self, validation_id: str) -> dict[str, object]:
        del validation_id
        return {"derived_rolling": {"annualization": 252.0}}


class _PagedAcceptanceProjection(PortfolioExecutionInteractiveProjection):
    def __init__(self, row_count: int) -> None:
        self.workspace_v2 = _AnnualizationWorkspace()  # type: ignore[assignment]
        self.strategy_explorer = SimpleNamespace()  # type: ignore[assignment]
        self.row_count = row_count
        self.requested_offsets: list[int] = []

    def item(self, validation_id: str) -> Any:
        del validation_id
        return SimpleNamespace(strategy_series_id="series-v45")

    def _portfolio_points(self, *args: Any, **kwargs: Any) -> list[dict[str, object]]:
        del args, kwargs
        return []

    def _query_decisions(
        self,
        validation_id: str,
        *,
        asset: str | None,
        start: Any,
        end: Any,
        fold_id: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, object]:
        del validation_id, asset, start, end, fold_id
        self.requested_offsets.append(offset)
        stop = min(offset + limit, self.row_count)
        items = [
            {
                "fees": 1.0,
                "slippage": 2.0,
                "desired_quantity": 1.0,
                "executable_quantity": 1.0,
                "filled_quantity": 1.0,
                "decision_status": "accepted",
                "constraint_codes": ["ACCEPTED"],
            }
            for _ in range(offset, stop)
        ]
        return {
            "schema_version": "finagent.strategy-decision-series.query.v1",
            "read_only": True,
            "authority": "authoritative",
            "series_id": "series-v45",
            "total": self.row_count,
            "offset": offset,
            "limit": limit,
            "items": items,
        }


def test_v45_server_side_execution_aggregates_page_past_5000_rows() -> None:
    projection = _PagedAcceptanceProjection(5001)
    analytics = projection.analytics("portfolio-v45")

    assert projection.requested_offsets == [0, 5000]
    assert analytics["filtered_costs"]["decision_row_count"] == 5001
    assert analytics["filtered_costs"]["fees"] == 5001.0
    assert analytics["filtered_costs"]["slippage"] == 10002.0
    assert analytics["order_funnel"]["desired"] == 5001
    assert analytics["order_funnel"]["executable"] == 5001
    assert analytics["order_funnel"]["filled"] == 5001
    assert analytics["constraint_attribution"]["reason_counts"] == {"ACCEPTED": 5001}

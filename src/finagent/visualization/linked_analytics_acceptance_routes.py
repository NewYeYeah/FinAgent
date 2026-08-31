from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException, Query

from .linked_analytics_acceptance import LinkedAnalyticsAcceptanceProjection


def attach_linked_analytics_acceptance_routes(
    app: FastAPI,
    projection: LinkedAnalyticsAcceptanceProjection,
) -> None:
    """Attach GET-only linked-analytics and A-C2 MarketBarSeries capabilities."""

    @app.get("/api/v4/linked-analytics/status")
    def get_v4_linked_analytics_status() -> dict[str, object]:
        return projection.status()

    @app.get("/api/v4/strategy-series/{series_id}/market-bar-binding")
    def get_v4_strategy_market_bar_binding(series_id: str) -> dict[str, object]:
        try:
            projection.strategy_explorer.item(series_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="strategy series not found") from exc
        binding = projection.strategy_explorer.market_bar_binding(series_id)
        if binding is None:
            raise HTTPException(
                status_code=404,
                detail="verified MarketBarSeries is unavailable for this strategy series",
            )
        return {
            "schema_version": "finagent.strategy-market-bar-binding.v1",
            "read_only": True,
            "browser_recomputation": False,
            **binding,
        }

    @app.get("/api/v4/strategy-series/{series_id}/market-bars")
    def get_v4_strategy_market_bars(
        series_id: str,
        asset: str | None = None,
        start: date | None = None,
        end: date | None = None,
        limit: int = Query(default=1000, ge=1, le=5000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, object]:
        try:
            return projection.strategy_explorer.bars(
                series_id,
                asset=asset,
                start=start,
                end=end,
                limit=limit,
                offset=offset,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="verified MarketBarSeries is unavailable for this strategy series",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException, Query

from .portfolio_execution import PortfolioExecutionInteractiveProjection


def attach_portfolio_execution_routes(
    app: FastAPI,
    projection: PortfolioExecutionInteractiveProjection,
) -> None:
    """Attach GET-only V4-4 Portfolio / Execution Interactive Pack routes."""

    @app.get("/api/v4/portfolio-execution/status")
    def get_v4_portfolio_execution_status() -> dict[str, object]:
        return projection.status()

    @app.get("/api/v4/portfolio-execution")
    def get_v4_portfolio_execution_catalog() -> dict[str, object]:
        return projection.catalog()

    @app.get("/api/v4/portfolio-execution/{validation_id}")
    def get_v4_portfolio_execution_detail(validation_id: str) -> dict[str, object]:
        try:
            return projection.detail(validation_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="portfolio execution evidence not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v4/portfolio-execution/{validation_id}/series")
    def get_v4_portfolio_execution_series(
        validation_id: str,
        start: date | None = None,
        end: date | None = None,
        fold_id: str | None = None,
        limit: int = Query(default=1000, ge=1, le=5000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, object]:
        try:
            return projection.portfolio_series(
                validation_id,
                start=start,
                end=end,
                fold_id=fold_id,
                limit=limit,
                offset=offset,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="portfolio execution evidence not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v4/portfolio-execution/{validation_id}/analytics")
    def get_v4_portfolio_execution_analytics(
        validation_id: str,
        asset: str | None = None,
        start: date | None = None,
        end: date | None = None,
        fold_id: str | None = None,
        window: int = Query(default=20, ge=2, le=252),
    ) -> dict[str, object]:
        try:
            return projection.analytics(
                validation_id,
                asset=asset,
                start=start,
                end=end,
                fold_id=fold_id,
                window=window,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="portfolio execution evidence not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v4/portfolio-execution/{validation_id}/decisions")
    def get_v4_portfolio_execution_decisions(
        validation_id: str,
        asset: str | None = None,
        session_date: date | None = None,
        start: date | None = None,
        end: date | None = None,
        fold_id: str | None = None,
        limit: int = Query(default=1000, ge=1, le=5000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, object]:
        try:
            return projection.decisions(
                validation_id,
                asset=asset,
                session_date=session_date,
                start=start,
                end=end,
                fold_id=fold_id,
                limit=limit,
                offset=offset,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="portfolio execution evidence not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

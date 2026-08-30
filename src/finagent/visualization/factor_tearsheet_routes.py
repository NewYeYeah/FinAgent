from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException, Query

from .factor_tearsheet import FactorTearSheetProjection
from .portfolio_execution import PortfolioExecutionInteractiveProjection
from .portfolio_execution_routes import attach_portfolio_execution_routes


def attach_factor_tearsheet_routes(
    app: FastAPI,
    projection: FactorTearSheetProjection,
) -> None:
    """Attach GET-only V4-3/V4-4 linked analytics routes to the Evidence Plane."""

    @app.get("/api/v4/factor-series/status")
    def get_v4_factor_series_status() -> dict[str, object]:
        return projection.status()

    @app.get("/api/v4/factor-series")
    def get_v4_factor_series() -> dict[str, object]:
        return projection.catalog()

    @app.get("/api/v4/factor-series/by-program/{program_id}")
    def get_v4_factor_series_by_program(program_id: str) -> dict[str, object]:
        try:
            return projection.by_program(program_id).to_dict()
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="FactorSeries not found for ResearchProgram",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v4/factor-series/{series_id}")
    def get_v4_factor_series_detail(series_id: str) -> dict[str, object]:
        try:
            item = projection.item(series_id)
            manifest = projection.projection(series_id).manifest
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="factor series not found") from exc
        return {
            "schema_version": "finagent.factor-tear-sheet.series.v1",
            "read_only": True,
            "item": item.to_dict(),
            "manifest": manifest.to_dict(),
            "presentation": {
                "browser_recomputation": False,
                "period_series_source": "verified V4-1 FactorSeries",
                "statistical_summary_source": "frozen A2.6 walk-forward report",
                "heatmap_authority": "derived_presentation",
                "correlation_cluster_authority": "derived_presentation",
                "agent_chronology_available": False,
            },
        }

    @app.get("/api/v4/factor-series/{series_id}/dimensions")
    def get_v4_factor_series_dimensions(series_id: str) -> dict[str, object]:
        try:
            return projection.dimensions(series_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="factor series not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v4/factor-series/{series_id}/summary")
    def get_v4_factor_series_summary(
        series_id: str,
        feature_digest: str | None = None,
    ) -> dict[str, object]:
        try:
            return projection.summary(series_id, feature_digest=feature_digest)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="factor summary not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v4/factor-series/{series_id}/correlations")
    def get_v4_factor_series_correlations(series_id: str) -> dict[str, object]:
        try:
            return projection.correlations(series_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="factor series not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v4/factor-series/{series_id}/heatmap")
    def get_v4_factor_series_heatmap(
        series_id: str,
        feature_digest: str | None = None,
        label_name: str | None = None,
        metric: str = "rank_ic",
    ) -> dict[str, object]:
        try:
            return projection.heatmap(
                series_id,
                feature_digest=feature_digest,
                label_name=label_name,
                metric=metric,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="factor not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/v4/factor-series/{series_id}/provenance")
    def get_v4_factor_series_provenance(series_id: str) -> dict[str, object]:
        try:
            return projection.provenance(series_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="factor series not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v4/factor-series/{series_id}/rows")
    def get_v4_factor_series_rows(
        series_id: str,
        feature_digest: str | None = None,
        fold_id: str | None = None,
        series_kind: str | None = None,
        metric: str | None = None,
        label_name: str | None = None,
        quantile: int | None = Query(default=None, ge=1),
        start: date | None = None,
        end: date | None = None,
        limit: int = Query(default=1000, ge=1, le=5000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, object]:
        try:
            return projection.query(
                series_id,
                feature_digest=feature_digest,
                fold_id=fold_id,
                series_kind=series_kind,
                metric=metric,
                label_name=label_name,
                quantile=quantile,
                start=start,
                end=end,
                limit=limit,
                offset=offset,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="factor series not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    portfolio_execution = PortfolioExecutionInteractiveProjection(
        app.state.workspace_v2,
        app.state.strategy_explorer,
    )
    app.state.portfolio_execution = portfolio_execution
    attach_portfolio_execution_routes(app, portfolio_execution)

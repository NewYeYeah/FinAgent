from __future__ import annotations

from fastapi import FastAPI

from .linked_analytics_acceptance import LinkedAnalyticsAcceptanceProjection


def attach_linked_analytics_acceptance_routes(
    app: FastAPI,
    projection: LinkedAnalyticsAcceptanceProjection,
) -> None:
    """Attach the V4-5 GET-only linked-analytics acceptance capability."""

    @app.get("/api/v4/linked-analytics/status")
    def get_v4_linked_analytics_status() -> dict[str, object]:
        return projection.status()

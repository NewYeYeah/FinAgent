from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .linked_strategy_analytics import LinkedStrategyAnalyticsProjection
from .semantic import EvidenceContractError


def attach_linked_strategy_analytics_routes(
    app: FastAPI,
    projection: LinkedStrategyAnalyticsProjection,
) -> None:
    @app.get("/api/v3/linked-strategy")
    def get_linked_strategy_index() -> dict[str, object]:
        try:
            return projection.index()
        except EvidenceContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v3/linked-strategy/cycles/{cycle_id}")
    def get_linked_strategy_cycle(cycle_id: str) -> dict[str, object]:
        try:
            return projection.cycle(cycle_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="research cycle not found") from exc
        except EvidenceContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

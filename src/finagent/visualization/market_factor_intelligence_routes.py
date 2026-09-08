from __future__ import annotations

import sqlite3

from fastapi import FastAPI, HTTPException

from .market_factor_intelligence import MarketFactorIntelligenceProjection
from .semantic import EvidenceContractError


def attach_market_factor_intelligence_routes(
    app: FastAPI,
    projection: MarketFactorIntelligenceProjection,
) -> None:
    @app.get("/api/v3/market-factor/status")
    def get_market_factor_status() -> dict[str, object]:
        return projection.status()

    @app.get("/api/v3/market-state")
    def get_market_state_index() -> dict[str, object]:
        try:
            return projection.markets()
        except (OSError, sqlite3.Error, EvidenceContractError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/v3/market-state/{model_id}")
    def get_market_state_detail(model_id: str) -> dict[str, object]:
        try:
            return projection.market(model_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="market state model not found") from exc
        except (OSError, sqlite3.Error, EvidenceContractError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/v3/factor-intelligence")
    def get_factor_intelligence_index() -> dict[str, object]:
        try:
            return projection.factors()
        except (OSError, sqlite3.Error, EvidenceContractError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/v3/factor-intelligence/{factor_id}")
    def get_factor_intelligence_detail(factor_id: str) -> dict[str, object]:
        try:
            return projection.factor(factor_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="factor intelligence not found") from exc
        except (OSError, sqlite3.Error, EvidenceContractError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

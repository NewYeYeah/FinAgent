from __future__ import annotations

import sqlite3

from fastapi import FastAPI, HTTPException, Query

from .research_workspace import ResearchWorkspaceProjection
from .semantic import EvidenceContractError


def attach_research_workspace_routes(
    app: FastAPI,
    projection: ResearchWorkspaceProjection,
) -> None:
    @app.get("/api/v3/research-workspace/status")
    def get_research_workspace_status() -> dict[str, object]:
        return projection.status()

    @app.get("/api/v3/research-cycles")
    def get_research_cycles() -> dict[str, object]:
        return projection.cycles()

    @app.get("/api/v3/research-experiments")
    def get_research_experiments(
        run_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        try:
            return projection.experiments(run_id=run_id)
        except (FileNotFoundError, sqlite3.Error) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except EvidenceContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v3/research-experiments/compare")
    def compare_research_experiments(
        experiment_id: list[str] = Query(default=[]),
    ) -> dict[str, object]:
        try:
            return projection.comparison(experiment_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (FileNotFoundError, sqlite3.Error) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except EvidenceContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v3/research-experiments/{identity}")
    def get_research_experiment(identity: str) -> dict[str, object]:
        try:
            return projection.experiment(identity)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="research experiment not found") from exc
        except (FileNotFoundError, sqlite3.Error) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except EvidenceContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v3/research-graph")
    def get_research_graph(
        run_id: str | None = Query(default=None),
    ) -> dict[str, object]:
        try:
            return projection.graph(run_id=run_id)
        except (FileNotFoundError, sqlite3.Error) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except EvidenceContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

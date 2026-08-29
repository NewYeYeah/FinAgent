from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from finagent.runtime import DEFAULT_PARALLEL_POLICY, ParallelPlan

from .agent_projection import load_agent_run_projection
from .reserve_projection import ReserveWorkspaceProjection
from .semantic import (
    EvidenceBundle,
    EvidenceContractError,
    EvidenceStage,
    load_evidence_report,
)
from .widgets import default_widget_specs
from .workspace_v2 import WorkspaceV2Projection


WORKSPACE_API_VERSION = "finagent-workspace-api-v2"
SUPPORTED_REPORT_SUFFIX = ".json"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _semantic_payload_digest(path: Path) -> str:
    """Digest a report while ignoring the non-authoritative replay mode field."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise EvidenceContractError("report root must be a JSON object")
    normalized = dict(payload)
    normalized.pop("mode", None)
    return hashlib.sha256(_canonical_json(normalized).encode()).hexdigest()


def _safe_json_object(raw: object) -> Mapping[str, Any]:
    if raw is None:
        return {}
    try:
        value = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, Mapping) else {}


def _read_only_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


@dataclass(frozen=True, slots=True)
class WorkspaceCatalogItem:
    evidence_id: str
    evidence_type: str
    stage: str
    authority: str
    system_status: str
    research_status: str
    reserve_status: str
    promotion_eligible: bool
    program_id: str
    spec_id: str
    data_version: str
    source_uri: str
    factor_count: int
    has_portfolio: bool
    has_execution: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "stage": self.stage,
            "authority": self.authority,
            "system_status": self.system_status,
            "research_status": self.research_status,
            "reserve_status": self.reserve_status,
            "promotion_eligible": self.promotion_eligible,
            "program_id": self.program_id,
            "spec_id": self.spec_id,
            "data_version": self.data_version,
            "source_uri": self.source_uri,
            "factor_count": self.factor_count,
            "has_portfolio": self.has_portfolio,
            "has_execution": self.has_execution,
            "detail_url": f"/api/v1/evidence/{quote(self.evidence_id, safe='')}",
        }


class WorkspaceEvidenceCatalog:
    """In-memory, disposable index over immutable report artifacts.

    The catalog is a read model. Reports remain authoritative and are parsed through
    the V0 semantic contract. A restart is intentionally required to discover new
    files; V1 exposes no refresh/write endpoint.
    """

    def __init__(
        self,
        report_paths: Sequence[str | Path],
        *,
        git_sha: str = "",
    ) -> None:
        self.report_paths = tuple(Path(value).expanduser() for value in report_paths)
        self.git_sha = git_sha.strip()
        self._bundles: dict[str, EvidenceBundle] = {}
        self._semantic_digests: dict[str, str] = {}
        self._warnings: list[str] = []
        self._notices: list[str] = []
        self._parallel_plan: ParallelPlan | None = None
        self._lock = RLock()
        self._scan()

    @staticmethod
    def _candidates(paths: Iterable[Path]) -> tuple[Path, ...]:
        output: set[Path] = set()
        for root in paths:
            if root.is_file() and root.suffix.lower() == SUPPORTED_REPORT_SUFFIX:
                output.add(root.resolve())
            elif root.is_dir():
                output.update(
                    value.resolve()
                    for value in root.rglob(f"*{SUPPORTED_REPORT_SUFFIX}")
                    if value.is_file()
                )
        return tuple(sorted(output, key=lambda value: value.as_posix()))

    def _scan(self) -> None:
        bundles: dict[str, EvidenceBundle] = {}
        digests: dict[str, str] = {}
        warnings: list[str] = []
        notices: list[str] = []
        conflicts: set[str] = set()
        paths = self._candidates(self.report_paths)
        plan = DEFAULT_PARALLEL_POLICY.resolve(
            len(paths), workload="io", per_worker_memory_mb=64
        )

        def project(path: Path):
            try:
                return path, load_evidence_report(path, git_sha=self.git_sha), _semantic_payload_digest(path), None
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                return path, None, None, exc

        if plan.workers > 1 and len(paths) > 1:
            with ThreadPoolExecutor(
                max_workers=plan.workers,
                thread_name_prefix="finagent-evidence-scan",
            ) as executor:
                projected = tuple(executor.map(project, paths))
        else:
            projected = tuple(project(path) for path in paths)

        for path, bundle, semantic_digest, error in projected:
            if error is not None:
                warnings.append(f"{path}: {type(error).__name__}: {error}")
                continue
            assert bundle is not None and semantic_digest is not None
            evidence_id = bundle.root.evidence_id
            if evidence_id in conflicts:
                continue
            if evidence_id in bundles:
                if digests[evidence_id] == semantic_digest:
                    notices.append(
                        f"{path}: duplicate replay/equivalent evidence {evidence_id!r} ignored"
                    )
                    continue
                warnings.append(
                    f"{path}: conflicting payloads share evidence_id {evidence_id!r}; "
                    "the identity is omitted until the conflict is resolved"
                )
                bundles.pop(evidence_id, None)
                digests.pop(evidence_id, None)
                conflicts.add(evidence_id)
                continue
            bundles[evidence_id] = bundle
            digests[evidence_id] = semantic_digest
        with self._lock:
            self._bundles = bundles
            self._semantic_digests = digests
            self._warnings = warnings
            self._notices = notices
            self._parallel_plan = plan

    @property
    def warnings(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._warnings)

    @property
    def notices(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._notices)

    @property
    def parallel_plan(self) -> ParallelPlan | None:
        with self._lock:
            return self._parallel_plan

    def bundle(self, evidence_id: str) -> EvidenceBundle:
        with self._lock:
            try:
                return self._bundles[evidence_id]
            except KeyError as exc:
                raise KeyError(evidence_id) from exc

    def bundles(self) -> tuple[EvidenceBundle, ...]:
        with self._lock:
            return tuple(
                self._bundles[key]
                for key in sorted(self._bundles)
            )

    @staticmethod
    def _item(bundle: EvidenceBundle) -> WorkspaceCatalogItem:
        root = bundle.root
        return WorkspaceCatalogItem(
            evidence_id=root.evidence_id,
            evidence_type=root.evidence_type,
            stage=root.stage.value,
            authority=root.authority.value,
            system_status=bundle.system_status,
            research_status=bundle.research_status,
            reserve_status=bundle.reserve_status,
            promotion_eligible=bundle.promotion_eligible,
            program_id=root.program_id,
            spec_id=root.spec_id,
            data_version=root.data_version,
            source_uri=root.source_uri,
            factor_count=len(bundle.factors),
            has_portfolio=bundle.portfolio is not None,
            has_execution=bundle.execution is not None,
        )

    def items(self) -> tuple[WorkspaceCatalogItem, ...]:
        return tuple(self._item(bundle) for bundle in self.bundles())

    def programs(self) -> tuple[WorkspaceCatalogItem, ...]:
        return tuple(
            item
            for item in self.items()
            if item.stage == EvidenceStage.A2P6_ROBUST_RESEARCH.value
        )

    def portfolio_validations(self) -> tuple[WorkspaceCatalogItem, ...]:
        return tuple(
            item
            for item in self.items()
            if item.stage == EvidenceStage.A4_PORTFOLIO_VALIDATION.value
        )

    def program(self, program_id: str) -> EvidenceBundle:
        matches = [
            bundle
            for bundle in self.bundles()
            if bundle.root.program_id == program_id
            and bundle.root.stage is EvidenceStage.A2P6_ROBUST_RESEARCH
        ]
        if len(matches) != 1:
            raise KeyError(program_id)
        return matches[0]

    def factor_occurrences(self, digest: str) -> tuple[dict[str, object], ...]:
        output: list[dict[str, object]] = []
        for bundle in self.bundles():
            for factor in bundle.factors:
                if factor.feature_digest != digest:
                    continue
                output.append(
                    {
                        "parent_evidence_id": bundle.root.evidence_id,
                        "parent_stage": bundle.root.stage.value,
                        "program_id": bundle.root.program_id,
                        "research_status": bundle.research_status,
                        "reserve_status": bundle.reserve_status,
                        "factor": factor.to_dict(),
                    }
                )
        return tuple(output)


def _agent_run_summaries(path: Path) -> tuple[dict[str, object], ...]:
    with _read_only_connection(path) as connection:
        rows = connection.execute(
            "SELECT run_id, task_id, payload_json, decision_json "
            "FROM agent_runs ORDER BY rowid DESC"
        ).fetchall()
    output: list[dict[str, object]] = []
    for run_id, task_id, payload_json, decision_json in rows:
        payload = _safe_json_object(payload_json)
        task = payload.get("task", {})
        context = payload.get("context", {})
        decision = _safe_json_object(decision_json)
        task_mapping = task if isinstance(task, Mapping) else {}
        context_mapping = context if isinstance(context, Mapping) else {}
        metadata = context_mapping.get("metadata", {})
        metadata_mapping = metadata if isinstance(metadata, Mapping) else {}
        output.append(
            {
                "run_id": str(run_id),
                "task_id": str(task_id),
                "objective": str(task_mapping.get("objective", "")),
                "actor": str(context_mapping.get("actor", "")),
                "started_at": str(context_mapping.get("started_at", "")),
                "finished_at": str(decision.get("finished_at", "")),
                "status": str(decision.get("status", "running")),
                "project_id": str(metadata_mapping.get("project_id", "")),
                "thread_id": str(metadata_mapping.get("thread_id", "")),
                "trigger_type": str(metadata_mapping.get("trigger_type", "manual")),
            }
        )
    return tuple(output)


def create_workspace_app(
    *,
    report_paths: Sequence[str | Path] = ("reports",),
    agent_audit_path: str | Path | None = None,
    frontend_dir: str | Path | None = "workspace/dist",
    git_sha: str = "",
    catalog_db_path: str | Path | None = None,
    reserve_eligibility_path: str | Path | None = None,
    reserve_consumption_path: str | Path | None = None,
    reserve_terminal_path: str | Path | None = None,
    cors_origins: Sequence[str] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ),
) -> FastAPI:
    catalog = WorkspaceEvidenceCatalog(report_paths, git_sha=git_sha)
    agent_path = Path(agent_audit_path).expanduser() if agent_audit_path else None
    static_root = Path(frontend_dir).expanduser() if frontend_dir else None
    reserve_projection = ReserveWorkspaceProjection(
        eligibility_path=reserve_eligibility_path,
        consumption_path=reserve_consumption_path,
        terminal_path=reserve_terminal_path,
    )
    v2 = WorkspaceV2Projection(
        catalog.bundles(),
        report_paths=report_paths,
        catalog_db_path=catalog_db_path,
        git_sha=git_sha,
        reserve_projection=reserve_projection,
    )

    app = FastAPI(
        title="FinAgent Workspace API",
        version="1.0.0",
        description=(
            "Read-only Evidence API over immutable FinAgent A2/A2.6/A4 artifacts "
            "and canonical Agent audit projections."
        ),
    )
    app.state.catalog = catalog
    app.state.agent_audit_path = agent_path
    app.state.read_only = True
    app.state.workspace_v2 = v2
    app.state.reserve_projection = reserve_projection
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "HEAD", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "version": WORKSPACE_API_VERSION,
            "read_only": True,
            "evidence_count": len(catalog.items()),
            "warning_count": len(catalog.warnings),
            "notice_count": len(catalog.notices),
            "agent_audit_configured": agent_path is not None,
            "workspace_v2": True,
            "v2_warning_count": len(v2.warnings),
            "reserve_lifecycle": reserve_projection.configuration(),
            "parallelism": {
                "catalog": catalog.parallel_plan.to_dict() if catalog.parallel_plan else None,
                **v2.parallel_diagnostics(),
            },
        }

    @app.get("/api/v1/catalog")
    def get_catalog() -> dict[str, object]:
        return {
            "schema_version": "finagent.workspace.catalog.v1",
            "read_only": True,
            "items": [item.to_dict() for item in catalog.items()],
            "warnings": list(catalog.warnings),
            "notices": list(catalog.notices),
        }

    @app.get("/api/v1/evidence/{evidence_id}")
    def get_evidence(evidence_id: str) -> dict[str, object]:
        try:
            return catalog.bundle(evidence_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="evidence not found") from exc

    @app.get("/api/v1/programs")
    def get_programs() -> dict[str, object]:
        return {
            "items": [item.to_dict() for item in catalog.programs()],
            "read_only": True,
        }

    @app.get("/api/v1/programs/{program_id}")
    def get_program(program_id: str) -> dict[str, object]:
        try:
            return catalog.program(program_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="program not found") from exc

    @app.get("/api/v1/portfolio-validations")
    def get_portfolio_validations() -> dict[str, object]:
        return {
            "items": [item.to_dict() for item in catalog.portfolio_validations()],
            "read_only": True,
        }

    @app.get("/api/v1/portfolio-validations/{validation_id}")
    def get_portfolio_validation(validation_id: str) -> dict[str, object]:
        try:
            bundle = catalog.bundle(validation_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="validation not found") from exc
        if bundle.root.stage is not EvidenceStage.A4_PORTFOLIO_VALIDATION:
            raise HTTPException(status_code=404, detail="validation not found")
        return bundle.to_dict()

    @app.get("/api/v1/factors/{feature_digest}")
    def get_factor(feature_digest: str) -> dict[str, object]:
        occurrences = catalog.factor_occurrences(feature_digest)
        if not occurrences:
            raise HTTPException(status_code=404, detail="factor not found")
        return {
            "feature_digest": feature_digest,
            "occurrences": list(occurrences),
            "read_only": True,
        }

    @app.get("/api/v1/lineage/{evidence_id}")
    def get_lineage(evidence_id: str) -> dict[str, object]:
        try:
            return catalog.bundle(evidence_id).lineage().to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="lineage not found") from exc

    @app.get("/api/v1/widgets")
    def get_widgets() -> dict[str, object]:
        return {
            "schema_version": "finagent.workspace.widgets.v1",
            "items": [value.to_dict() for value in default_widget_specs()],
            "read_only": True,
        }

    @app.get("/api/v1/agent/runs")
    def get_agent_runs() -> dict[str, object]:
        if agent_path is None:
            return {"items": [], "configured": False, "read_only": True}
        try:
            items = _agent_run_summaries(agent_path)
        except (FileNotFoundError, sqlite3.Error) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"items": list(items), "configured": True, "read_only": True}

    @app.get("/api/v1/agent/runs/{run_id}")
    def get_agent_run(run_id: str) -> dict[str, object]:
        if agent_path is None:
            raise HTTPException(status_code=404, detail="agent audit is not configured")
        try:
            return load_agent_run_projection(agent_path, run_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="agent run not found") from exc
        except (FileNotFoundError, sqlite3.Error, EvidenceContractError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Visualization V2: all product routes remain GET-only. Derived projections
    # organize immutable evidence for human review before one-shot reserve use.
    @app.get("/api/v2/catalog")
    def get_v2_catalog() -> dict[str, object]:
        return v2.catalog()

    @app.get("/api/v2/projects")
    def get_v2_projects() -> dict[str, object]:
        try:
            return v2.projects()
        except EvidenceContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v2/programs/{program_id}/cockpit")
    def get_v2_program_cockpit(program_id: str) -> dict[str, object]:
        try:
            return v2.program_cockpit(program_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="program not found") from exc
        except EvidenceContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v2/programs/{program_id}/gates")
    def get_v2_program_gates(program_id: str) -> dict[str, object]:
        try:
            return v2.program_gates(program_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="program not found") from exc

    @app.get("/api/v2/programs/{program_id}/statistics")
    def get_v2_program_statistics(program_id: str) -> dict[str, object]:
        try:
            return v2.program_statistics(program_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="program not found") from exc

    @app.get("/api/v2/a4/{validation_id}/cockpit")
    def get_v2_a4_cockpit(validation_id: str) -> dict[str, object]:
        try:
            return v2.portfolio_cockpit(validation_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="validation not found") from exc
        except EvidenceContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v2/a4/{validation_id}/execution")
    def get_v2_execution_cockpit(validation_id: str) -> dict[str, object]:
        try:
            return v2.execution_cockpit(validation_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="validation not found") from exc
        except EvidenceContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v2/governance/{evidence_id}")
    def get_v2_governance(evidence_id: str) -> dict[str, object]:
        try:
            return v2.governance(evidence_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="evidence not found") from exc
        except EvidenceContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v2/reserves")
    def get_v2_reserves() -> dict[str, object]:
        try:
            return reserve_projection.list()
        except EvidenceContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except sqlite3.Error as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/v2/reserves/{reserve_id}")
    def get_v2_reserve(reserve_id: str) -> dict[str, object]:
        try:
            return reserve_projection.get(reserve_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="reserve lifecycle not found") from exc
        except EvidenceContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except sqlite3.Error as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/v2/reserves/{reserve_id}/ledger")
    def get_v2_reserve_ledger(reserve_id: str) -> dict[str, object]:
        try:
            return reserve_projection.ledger(reserve_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="reserve ledger not found") from exc
        except EvidenceContractError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except sqlite3.Error as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/v2/protocol-diff")
    def get_v2_protocol_diff(left: str, right: str) -> dict[str, object]:
        try:
            return v2.protocol_diff(left, right)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="protocol evidence not found") from exc

    @app.get("/api/v2/evidence/{evidence_id}/raw")
    def get_v2_raw_evidence(evidence_id: str) -> dict[str, object]:
        try:
            return v2.raw_evidence(evidence_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="raw evidence not found") from exc

    @app.get("/api/v2/a4/{validation_id}/review-bundle")
    def get_v2_review_bundle(validation_id: str) -> Response:
        try:
            payload = v2.review_bundle(validation_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="validation not found") from exc
        return Response(
            content=payload,
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="finagent-review-{validation_id}.zip"'
                )
            },
        )

    if static_root is not None and static_root.is_dir():
        assets = static_root / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="workspace-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def workspace_frontend(full_path: str, request: Request):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="not found")
            requested = (static_root / full_path).resolve()
            try:
                requested.relative_to(static_root.resolve())
            except ValueError as exc:
                raise HTTPException(status_code=404, detail="not found") from exc
            if requested.is_file():
                return FileResponse(requested)
            index = static_root / "index.html"
            if index.is_file():
                return FileResponse(index)
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Workspace frontend has not been built",
                    "request_path": request.url.path,
                },
            )

    return app


def create_app_from_environment() -> FastAPI:
    raw_reports = os.environ.get("FINAGENT_WORKSPACE_REPORTS", "reports")
    report_paths = tuple(value for value in raw_reports.split(os.pathsep) if value)
    agent_audit = os.environ.get("FINAGENT_WORKSPACE_AGENT_AUDIT") or None
    frontend = os.environ.get("FINAGENT_WORKSPACE_FRONTEND", "workspace/dist") or None
    git_sha = os.environ.get("FINAGENT_WORKSPACE_GIT_SHA", "")
    catalog_db = os.environ.get("FINAGENT_WORKSPACE_CATALOG_DB") or None
    reserve_eligibility = os.environ.get("FINAGENT_WORKSPACE_RESERVE_ELIGIBILITY") or None
    reserve_consumption = os.environ.get("FINAGENT_WORKSPACE_RESERVE_CONSUMPTION") or None
    reserve_terminal = os.environ.get("FINAGENT_WORKSPACE_RESERVE_TERMINAL") or None
    return create_workspace_app(
        report_paths=report_paths,
        agent_audit_path=agent_audit,
        frontend_dir=frontend,
        git_sha=git_sha,
        catalog_db_path=catalog_db,
        reserve_eligibility_path=reserve_eligibility,
        reserve_consumption_path=reserve_consumption,
        reserve_terminal_path=reserve_terminal,
    )

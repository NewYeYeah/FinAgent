from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from urllib.parse import quote

from .agent_projection import AgentRunProjection, load_agent_run_projections
from .semantic import EvidenceBundle, EvidenceContractError


_FALLBACK_PREFIX = "finagent-derived"


def _normalized_id(value: object) -> str:
    return str(value or "").strip()


def _derived_id(kind: str, *parts: str) -> str:
    payload = "\x1f".join(("finagent.agent-index.v1", kind, *parts)).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[:24]
    return f"{_FALLBACK_PREFIX}-{kind}-{digest}"


def _run_updated_at(run: AgentRunProjection) -> datetime:
    return run.finished_at or run.started_at


def _merge_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for raw in values if (value := _normalized_id(raw))))


@dataclass(frozen=True, slots=True)
class AgentArtifactRef:
    artifact_id: str
    artifact_type: str
    authority: str
    detail_url: str
    verification: str = "workspace_catalog"
    evidence_ids: tuple[str, ...] = ()
    source_uris: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "artifact_id",
            "artifact_type",
            "authority",
            "detail_url",
            "verification",
        ):
            if not _normalized_id(getattr(self, name)):
                raise EvidenceContractError(f"AgentArtifactRef.{name} must be non-empty")
        evidence_ids = _merge_unique(self.evidence_ids)
        source_uris = _merge_unique(self.source_uris)
        if not evidence_ids and not source_uris:
            raise EvidenceContractError(
                "AgentArtifactRef requires a verifiable evidence or source identity"
            )
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "source_uris", source_uris)

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "authority": self.authority,
            "detail_url": self.detail_url,
            "verification": self.verification,
            "evidence_ids": list(self.evidence_ids),
            "source_uris": list(self.source_uris),
        }


@dataclass(frozen=True, slots=True)
class AgentRunSummary:
    run_id: str
    task_id: str
    project_id: str
    thread_id: str
    project_identity_source: str
    thread_identity_source: str
    objective: str
    actor: str
    trigger_type: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    item_count: int
    artifact_refs: tuple[AgentArtifactRef, ...] = ()
    unresolved_artifact_count: int = 0
    error: str = ""

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "task_id",
            "project_id",
            "thread_id",
            "project_identity_source",
            "thread_identity_source",
            "objective",
            "actor",
            "trigger_type",
            "status",
        ):
            if not _normalized_id(getattr(self, name)):
                raise EvidenceContractError(f"AgentRunSummary.{name} must be non-empty")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise EvidenceContractError("AgentRunSummary.started_at must be timezone-aware")
        if self.finished_at is not None:
            if self.finished_at.tzinfo is None or self.finished_at.utcoffset() is None:
                raise EvidenceContractError(
                    "AgentRunSummary.finished_at must be timezone-aware"
                )
            if self.finished_at < self.started_at:
                raise EvidenceContractError("AgentRunSummary cannot finish before it starts")
        if self.item_count < 0 or self.unresolved_artifact_count < 0:
            raise EvidenceContractError("AgentRunSummary counts must be non-negative")
        artifact_ids = [value.artifact_id for value in self.artifact_refs]
        if len(set(artifact_ids)) != len(artifact_ids):
            raise EvidenceContractError("AgentRunSummary artifact refs must be unique")

    @property
    def updated_at(self) -> datetime:
        return self.finished_at or self.started_at

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "thread_id": self.thread_id,
            "project_identity_source": self.project_identity_source,
            "thread_identity_source": self.thread_identity_source,
            "objective": self.objective,
            "actor": self.actor,
            "trigger_type": self.trigger_type,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "updated_at": self.updated_at.isoformat(),
            "item_count": self.item_count,
            "artifact_count": len(self.artifact_refs),
            "artifact_refs": [value.to_dict() for value in self.artifact_refs],
            "unresolved_artifact_count": self.unresolved_artifact_count,
            "error": self.error,
            "detail_url": f"/api/v3/agent/runs/{quote(self.run_id, safe='')}",
        }


@dataclass(frozen=True, slots=True)
class AgentThreadProjection:
    thread_id: str
    project_id: str
    identity_source: str
    label: str
    started_at: datetime
    updated_at: datetime
    status: str
    runs: tuple[AgentRunSummary, ...]
    artifact_refs: tuple[AgentArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        for name in ("thread_id", "project_id", "identity_source", "label", "status"):
            if not _normalized_id(getattr(self, name)):
                raise EvidenceContractError(
                    f"AgentThreadProjection.{name} must be non-empty"
                )
        if not self.runs:
            raise EvidenceContractError("AgentThreadProjection requires at least one run")
        if self.started_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise EvidenceContractError("AgentThreadProjection times must be timezone-aware")
        if self.updated_at < self.started_at:
            raise EvidenceContractError("AgentThreadProjection updated_at precedes started_at")
        if any(value.thread_id != self.thread_id for value in self.runs):
            raise EvidenceContractError("thread projection contains a run from another thread")
        if any(value.project_id != self.project_id for value in self.runs):
            raise EvidenceContractError("thread projection contains a run from another project")
        run_ids = [value.run_id for value in self.runs]
        if len(set(run_ids)) != len(run_ids):
            raise EvidenceContractError("thread projection run ids must be unique")

    def to_summary_dict(self) -> dict[str, object]:
        return {
            "thread_id": self.thread_id,
            "project_id": self.project_id,
            "identity_source": self.identity_source,
            "label": self.label,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "run_count": len(self.runs),
            "artifact_count": len(self.artifact_refs),
            "detail_url": f"/api/v3/agent/threads/{quote(self.thread_id, safe='')}",
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.visualization.agent-thread-projection.v1",
            **self.to_summary_dict(),
            "runs": [value.to_dict() for value in self.runs],
            "artifact_refs": [value.to_dict() for value in self.artifact_refs],
            "read_only": True,
        }


@dataclass(frozen=True, slots=True)
class AgentProjectProjection:
    project_id: str
    identity_source: str
    label: str
    started_at: datetime
    updated_at: datetime
    status: str
    threads: tuple[AgentThreadProjection, ...]
    artifact_refs: tuple[AgentArtifactRef, ...] = ()

    def __post_init__(self) -> None:
        for name in ("project_id", "identity_source", "label", "status"):
            if not _normalized_id(getattr(self, name)):
                raise EvidenceContractError(
                    f"AgentProjectProjection.{name} must be non-empty"
                )
        if not self.threads:
            raise EvidenceContractError("AgentProjectProjection requires at least one thread")
        if self.started_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise EvidenceContractError("AgentProjectProjection times must be timezone-aware")
        if self.updated_at < self.started_at:
            raise EvidenceContractError("AgentProjectProjection updated_at precedes started_at")
        if any(value.project_id != self.project_id for value in self.threads):
            raise EvidenceContractError("project projection contains a foreign thread")
        thread_ids = [value.thread_id for value in self.threads]
        if len(set(thread_ids)) != len(thread_ids):
            raise EvidenceContractError("project projection thread ids must be unique")

    @property
    def run_count(self) -> int:
        return sum(len(value.runs) for value in self.threads)

    def to_summary_dict(self) -> dict[str, object]:
        return {
            "project_id": self.project_id,
            "identity_source": self.identity_source,
            "label": self.label,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "thread_count": len(self.threads),
            "run_count": self.run_count,
            "artifact_count": len(self.artifact_refs),
            "detail_url": f"/api/v3/agent/projects/{quote(self.project_id, safe='')}",
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.visualization.agent-project-projection.v1",
            **self.to_summary_dict(),
            "threads": [value.to_summary_dict() for value in self.threads],
            "artifact_refs": [value.to_dict() for value in self.artifact_refs],
            "read_only": True,
        }


@dataclass(frozen=True, slots=True)
class AgentIndexProjection:
    projects: tuple[AgentProjectProjection, ...]
    runs: Mapping[str, AgentRunProjection]
    run_summaries: Mapping[str, AgentRunSummary]
    threads: Mapping[str, AgentThreadProjection]

    def __post_init__(self) -> None:
        object.__setattr__(self, "runs", MappingProxyType(dict(self.runs)))
        object.__setattr__(self, "run_summaries", MappingProxyType(dict(self.run_summaries)))
        object.__setattr__(self, "threads", MappingProxyType(dict(self.threads)))
        project_ids = [value.project_id for value in self.projects]
        if len(set(project_ids)) != len(project_ids):
            raise EvidenceContractError("Agent index project ids must be unique")

    def projects_response(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.workspace.agent-project-index.v1",
            "items": [value.to_summary_dict() for value in self.projects],
            "read_only": True,
            "hidden_reasoning": "not_persisted_not_projected",
        }

    def project(self, project_id: str) -> AgentProjectProjection:
        for value in self.projects:
            if value.project_id == project_id:
                return value
        raise KeyError(project_id)

    def thread(self, thread_id: str) -> AgentThreadProjection:
        try:
            return self.threads[thread_id]
        except KeyError as exc:
            raise KeyError(thread_id) from exc

    def run_response(self, run_id: str) -> dict[str, object]:
        try:
            run = self.runs[run_id]
            summary = self.run_summaries[run_id]
        except KeyError as exc:
            raise KeyError(run_id) from exc
        return {
            "schema_version": "finagent.workspace.agent-run-detail.v1",
            "summary": summary.to_dict(),
            "run": run.to_dict(),
            "artifact_refs": [value.to_dict() for value in summary.artifact_refs],
            "unresolved_artifact_count": summary.unresolved_artifact_count,
            "read_only": True,
            "hidden_reasoning": "not_persisted_not_projected",
        }


def build_agent_artifact_catalog(
    bundles: Sequence[EvidenceBundle],
) -> Mapping[str, AgentArtifactRef]:
    """Build a verified artifact lookup from immutable Workspace evidence only.

    Unknown ids from Agent outputs intentionally remain unresolved. This function does
    not inspect Phoenix/OTLP and never upgrades an arbitrary audit string into a product
    artifact reference.
    """

    mutable: dict[str, AgentArtifactRef] = {}

    def merge(value: AgentArtifactRef) -> None:
        existing = mutable.get(value.artifact_id)
        if existing is None:
            mutable[value.artifact_id] = value
            return
        if (
            existing.artifact_type != value.artifact_type
            or existing.authority != value.authority
            or existing.detail_url != value.detail_url
            or existing.verification != value.verification
        ):
            raise EvidenceContractError(
                f"conflicting verified Agent artifact identity {value.artifact_id!r}"
            )
        mutable[value.artifact_id] = AgentArtifactRef(
            artifact_id=existing.artifact_id,
            artifact_type=existing.artifact_type,
            authority=existing.authority,
            detail_url=existing.detail_url,
            verification=existing.verification,
            evidence_ids=_merge_unique((*existing.evidence_ids, *value.evidence_ids)),
            source_uris=_merge_unique((*existing.source_uris, *value.source_uris)),
        )

    for bundle in bundles:
        for ref in bundle.refs:
            merge(
                AgentArtifactRef(
                    artifact_id=ref.evidence_id,
                    artifact_type="evidence",
                    authority=ref.authority.value,
                    detail_url=f"/evidence/{quote(ref.evidence_id, safe='')}",
                    evidence_ids=(ref.evidence_id,),
                    source_uris=(ref.source_uri,) if ref.source_uri else (),
                )
            )
        for factor in bundle.factors:
            merge(
                AgentArtifactRef(
                    artifact_id=factor.feature_digest,
                    artifact_type="factor",
                    authority=bundle.root.authority.value,
                    detail_url=f"/factor/{quote(factor.feature_digest, safe='')}",
                    evidence_ids=(bundle.root.evidence_id,),
                    source_uris=(bundle.root.source_uri,) if bundle.root.source_uri else (),
                )
            )
    return MappingProxyType(dict(sorted(mutable.items())))


def _identity_source(values: Sequence[str]) -> str:
    normalized = tuple(dict.fromkeys(values))
    if "explicit" in normalized:
        return "explicit"
    if len(normalized) == 1:
        return normalized[0]
    return "derived"


def _artifact_refs_for_run(
    run: AgentRunProjection,
    artifact_catalog: Mapping[str, AgentArtifactRef],
) -> tuple[tuple[AgentArtifactRef, ...], int]:
    refs = tuple(
        artifact_catalog[artifact_id]
        for artifact_id in sorted(set(run.artifact_ids))
        if artifact_id in artifact_catalog
    )
    unresolved = sum(
        1 for artifact_id in set(run.artifact_ids) if artifact_id not in artifact_catalog
    )
    return refs, unresolved


def _aggregate_artifacts(runs: Sequence[AgentRunSummary]) -> tuple[AgentArtifactRef, ...]:
    merged: dict[str, AgentArtifactRef] = {}
    for run in runs:
        for ref in run.artifact_refs:
            existing = merged.get(ref.artifact_id)
            if existing is not None and existing != ref:
                raise EvidenceContractError(
                    f"conflicting Agent artifact ref {ref.artifact_id!r} within index"
                )
            merged[ref.artifact_id] = ref
    return tuple(merged[key] for key in sorted(merged))


def load_agent_index(
    path: str | Path,
    *,
    artifact_catalog: Mapping[str, AgentArtifactRef] | None = None,
) -> AgentIndexProjection:
    source = Path(path).expanduser()
    verified_artifacts = artifact_catalog or MappingProxyType({})
    raw_runs = load_agent_run_projections(source)

    explicit_thread_projects: dict[str, str] = {}
    for run in raw_runs:
        project_id = _normalized_id(run.project_id)
        thread_id = _normalized_id(run.thread_id)
        if not project_id or not thread_id:
            continue
        previous = explicit_thread_projects.setdefault(thread_id, project_id)
        if previous != project_id:
            raise EvidenceContractError(
                f"Agent thread {thread_id!r} is bound to conflicting projects "
                f"{previous!r} and {project_id!r}"
            )

    summaries: list[AgentRunSummary] = []
    effective_thread_projects: dict[str, str] = {}
    project_sources: dict[str, list[str]] = {}
    thread_sources: dict[str, list[str]] = {}

    for run in raw_runs:
        explicit_project = _normalized_id(run.project_id)
        explicit_thread = _normalized_id(run.thread_id)

        if explicit_project:
            project_id = explicit_project
            project_source = "explicit"
        elif explicit_thread and explicit_thread in explicit_thread_projects:
            project_id = explicit_thread_projects[explicit_thread]
            project_source = "thread_inferred"
        elif explicit_thread:
            project_id = _derived_id("project-thread", explicit_thread)
            project_source = "thread_fallback"
        else:
            project_id = _derived_id("project-task", run.task_id)
            project_source = "task_fallback"

        if explicit_thread:
            thread_id = explicit_thread
            thread_source = "explicit"
        else:
            thread_id = _derived_id("thread-task", project_id, run.task_id)
            thread_source = "task_fallback"

        previous_project = effective_thread_projects.setdefault(thread_id, project_id)
        if previous_project != project_id:
            raise EvidenceContractError(
                f"Agent thread {thread_id!r} resolves to conflicting projects "
                f"{previous_project!r} and {project_id!r}"
            )
        project_sources.setdefault(project_id, []).append(project_source)
        thread_sources.setdefault(thread_id, []).append(thread_source)

        artifact_refs, unresolved_count = _artifact_refs_for_run(run, verified_artifacts)
        summaries.append(
            AgentRunSummary(
                run_id=run.run_id,
                task_id=run.task_id,
                project_id=project_id,
                thread_id=thread_id,
                project_identity_source=project_source,
                thread_identity_source=thread_source,
                objective=run.objective,
                actor=run.actor,
                trigger_type=run.trigger_type,
                status=run.status,
                started_at=run.started_at,
                finished_at=run.finished_at,
                item_count=len(run.items),
                artifact_refs=artifact_refs,
                unresolved_artifact_count=unresolved_count,
                error=run.error,
            )
        )

    summaries.sort(key=lambda value: (-value.started_at.timestamp(), value.run_id))
    summary_by_id = {value.run_id: value for value in summaries}
    run_by_id = {run.run_id: run for run in raw_runs}

    thread_groups: dict[str, list[AgentRunSummary]] = {}
    for summary in summaries:
        thread_groups.setdefault(summary.thread_id, []).append(summary)

    threads: list[AgentThreadProjection] = []
    for thread_id, thread_runs in thread_groups.items():
        ordered = tuple(
            sorted(thread_runs, key=lambda value: (-value.started_at.timestamp(), value.run_id))
        )
        latest = ordered[0]
        threads.append(
            AgentThreadProjection(
                thread_id=thread_id,
                project_id=latest.project_id,
                identity_source=_identity_source(thread_sources[thread_id]),
                label=latest.objective,
                started_at=min(value.started_at for value in ordered),
                updated_at=max(value.updated_at for value in ordered),
                status=latest.status,
                runs=ordered,
                artifact_refs=_aggregate_artifacts(ordered),
            )
        )
    threads.sort(key=lambda value: (-value.updated_at.timestamp(), value.thread_id))
    thread_by_id = {value.thread_id: value for value in threads}

    project_groups: dict[str, list[AgentThreadProjection]] = {}
    for thread in threads:
        project_groups.setdefault(thread.project_id, []).append(thread)

    projects: list[AgentProjectProjection] = []
    for project_id, project_threads in project_groups.items():
        ordered_threads = tuple(
            sorted(
                project_threads,
                key=lambda value: (-value.updated_at.timestamp(), value.thread_id),
            )
        )
        latest_thread = ordered_threads[0]
        latest_run = latest_thread.runs[0]
        project_runs = tuple(run for thread in ordered_threads for run in thread.runs)
        projects.append(
            AgentProjectProjection(
                project_id=project_id,
                identity_source=_identity_source(project_sources[project_id]),
                label=latest_run.objective,
                started_at=min(value.started_at for value in ordered_threads),
                updated_at=max(value.updated_at for value in ordered_threads),
                status=latest_run.status,
                threads=ordered_threads,
                artifact_refs=_aggregate_artifacts(project_runs),
            )
        )
    projects.sort(key=lambda value: (-value.updated_at.timestamp(), value.project_id))

    return AgentIndexProjection(
        projects=tuple(projects),
        runs=run_by_id,
        run_summaries=summary_by_id,
        threads=thread_by_id,
    )

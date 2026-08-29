from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import quote

from .agent_index import load_agent_index
from .semantic import EvidenceBundle, EvidenceContractError, EvidenceRef, EvidenceStage
from .workbench_control_catalog import ConfigRegistry
from .workspace_api import WorkspaceEvidenceCatalog
from .workspace_v2 import WorkspaceV2Projection
from .reserve_projection import ReserveWorkspaceProjection

WORKBENCH_REFERENCE_SCHEMA = "finagent.workbench.reference.v1"
WORKBENCH_ARTIFACT_SCHEMA = "finagent.workbench.artifact-inspection.v1"
COMMAND_RUN_PROJECTION_SCHEMA = "finagent.workbench.command-run-projection.v1"

ReferenceKind = Literal[
    "evidence",
    "artifact",
    "factor",
    "research_program",
    "portfolio_validation",
    "reserve",
    "agent_run",
    "config_snapshot",
    "config_diff",
    "command_run",
]

_REFERENCE_KINDS: frozenset[str] = frozenset(
    {
        "evidence",
        "artifact",
        "factor",
        "research_program",
        "portfolio_validation",
        "reserve",
        "agent_run",
        "config_snapshot",
        "config_diff",
        "command_run",
    }
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )


def _digest(prefix: str, value: object, length: int = 24) -> str:
    return f"{prefix}-{hashlib.sha256(_canonical_json(value).encode()).hexdigest()[:length]}"


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _json_object(value: object) -> dict[str, object]:
    if value is None:
        return {}
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(decoded, dict):
        return {}
    return {str(key): item for key, item in decoded.items()}


def _json_strings(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(str(item).strip() for item in decoded if str(item).strip())


def _reference_url(kind: str, identity: str) -> str:
    return f"/ref/{quote(kind, safe='')}/{quote(identity, safe='')}"


@dataclass(frozen=True, slots=True)
class WorkbenchReferenceSummary:
    kind: ReferenceKind
    identity: str
    label: str
    authority: str
    verification: str
    detail_url: str
    target_url: str = ""
    context: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("kind", "identity", "label", "authority", "verification", "detail_url"):
            if not _text(getattr(self, name)):
                raise EvidenceContractError(f"WorkbenchReferenceSummary.{name} must be non-empty")
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "identity": self.identity,
            "label": self.label,
            "authority": self.authority,
            "verification": self.verification,
            "detail_url": self.detail_url,
            "target_url": self.target_url,
            "context": dict(self.context),
        }


@dataclass(frozen=True, slots=True)
class WorkbenchReference:
    kind: ReferenceKind
    identity: str
    label: str
    authority: str
    verification: str
    detail_url: str
    target_url: str
    context: Mapping[str, str]
    metadata: Mapping[str, object]
    related: tuple[WorkbenchReferenceSummary, ...] = ()
    read_only: bool = True
    schema_version: str = WORKBENCH_REFERENCE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_summary(self) -> WorkbenchReferenceSummary:
        return WorkbenchReferenceSummary(
            kind=self.kind,
            identity=self.identity,
            label=self.label,
            authority=self.authority,
            verification=self.verification,
            detail_url=self.detail_url,
            target_url=self.target_url,
            context=self.context,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "read_only": self.read_only,
            **self.to_summary().to_dict(),
            "metadata": dict(self.metadata),
            "related": [item.to_dict() for item in self.related],
        }


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    artifact_id: str
    artifact_type: str
    label: str
    authority: str
    verification: str
    source_uri: str
    evidence_ids: tuple[str, ...]
    target_url: str
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class WorkspaceArtifactCatalog:
    """Verified artifact index built only from configured immutable evidence.

    Browser input never becomes a filesystem path. Source report artifacts are
    registered at startup from EvidenceRef.source_uri and are previewed only when the
    resolved path stays inside a configured report root. Generated-feature entries are
    metadata-only identities keyed by their canonical feature digest.
    """

    def __init__(
        self,
        bundles: Sequence[EvidenceBundle],
        *,
        report_paths: Sequence[str | Path],
        max_preview_bytes: int = 256 * 1024,
    ) -> None:
        self._bundles = tuple(bundles)
        self._roots = tuple(Path(value).expanduser().resolve() for value in report_paths)
        self._max_preview_bytes = max(4096, int(max_preview_bytes))
        self._items: dict[str, ArtifactDescriptor] = {}
        self._build()

    @staticmethod
    def source_artifact_id(bundle: EvidenceBundle) -> str:
        return _digest(
            "source-artifact",
            {
                "evidence_id": bundle.root.evidence_id,
                "artifact_digest": bundle.root.artifact_digest,
                "source_uri": bundle.root.source_uri,
            },
        )

    def _merge(self, item: ArtifactDescriptor) -> None:
        existing = self._items.get(item.artifact_id)
        if existing is None:
            self._items[item.artifact_id] = item
            return
        if (
            existing.artifact_type != item.artifact_type
            or existing.source_uri != item.source_uri
            or existing.target_url != item.target_url
        ):
            raise EvidenceContractError(
                f"conflicting verified artifact identity {item.artifact_id!r}"
            )
        self._items[item.artifact_id] = ArtifactDescriptor(
            artifact_id=existing.artifact_id,
            artifact_type=existing.artifact_type,
            label=existing.label,
            authority=existing.authority,
            verification=existing.verification,
            source_uri=existing.source_uri,
            evidence_ids=tuple(dict.fromkeys((*existing.evidence_ids, *item.evidence_ids))),
            target_url=existing.target_url,
            metadata={**dict(existing.metadata), **dict(item.metadata)},
        )

    def _build(self) -> None:
        for bundle in self._bundles:
            root = bundle.root
            source_id = self.source_artifact_id(bundle)
            self._merge(
                ArtifactDescriptor(
                    artifact_id=source_id,
                    artifact_type="source_report",
                    label=f"Source report · {root.evidence_type}",
                    authority=root.authority.value,
                    verification="workspace_catalog",
                    source_uri=root.source_uri,
                    evidence_ids=(root.evidence_id,),
                    target_url=f"/evidence/{quote(root.evidence_id, safe='')}",
                    metadata={
                        "artifact_digest": root.artifact_digest,
                        "schema_version": root.schema_version,
                        "stage": root.stage.value,
                    },
                )
            )
            for factor in bundle.factors:
                self._merge(
                    ArtifactDescriptor(
                        artifact_id=factor.feature_digest,
                        artifact_type="generated_feature",
                        label=f"Generated feature · {factor.feature_id}",
                        authority=root.authority.value,
                        verification="workspace_catalog",
                        source_uri="",
                        evidence_ids=(root.evidence_id,),
                        target_url=f"/factor/{quote(factor.feature_digest, safe='')}",
                        metadata={
                            "feature_id": factor.feature_id,
                            "hypothesis": factor.hypothesis,
                            "selected": factor.selected,
                            "direction": factor.direction,
                            "status": factor.status,
                            "reason_codes": list(factor.reason_codes),
                        },
                    )
                )

    def descriptor(self, artifact_id: str) -> ArtifactDescriptor:
        try:
            return self._items[artifact_id]
        except KeyError as exc:
            raise KeyError(artifact_id) from exc

    def descriptors(self) -> tuple[ArtifactDescriptor, ...]:
        return tuple(self._items[key] for key in sorted(self._items))

    def _allowed_source(self, source_uri: str) -> Path | None:
        if not source_uri:
            return None
        try:
            source = Path(source_uri).expanduser().resolve()
        except OSError:
            return None
        for root in self._roots:
            if root.is_file() and source == root:
                return source
            if root.is_dir() and source.is_relative_to(root):
                return source
        return None

    def inspect(self, artifact_id: str) -> dict[str, object]:
        item = self.descriptor(artifact_id)
        payload: dict[str, object] = {
            "schema_version": WORKBENCH_ARTIFACT_SCHEMA,
            "read_only": True,
            "artifact_id": item.artifact_id,
            "artifact_type": item.artifact_type,
            "label": item.label,
            "authority": item.authority,
            "verification": item.verification,
            "evidence_ids": list(item.evidence_ids),
            "target_url": item.target_url,
            "metadata": dict(item.metadata),
            "source": {
                "registered": bool(item.source_uri),
                "display_uri": item.source_uri,
                "host_path_accepted_from_browser": False,
            },
            "preview": None,
        }
        if item.artifact_type == "generated_feature":
            payload["preview"] = {
                "kind": "metadata",
                "content": dict(item.metadata),
                "truncated": False,
            }
            return payload
        source = self._allowed_source(item.source_uri)
        if source is None or not source.is_file():
            payload["preview"] = {
                "kind": "unavailable",
                "reason": "registered source is unavailable or outside configured report roots",
                "truncated": False,
            }
            return payload
        try:
            size = source.stat().st_size
            with source.open("rb") as handle:
                data = handle.read(self._max_preview_bytes + 1)
        except OSError as exc:
            payload["preview"] = {
                "kind": "unavailable",
                "reason": f"{type(exc).__name__}: source preview failed",
                "truncated": False,
            }
            return payload
        truncated = len(data) > self._max_preview_bytes
        preview = data[: self._max_preview_bytes]
        try:
            text = preview.decode("utf-8")
        except UnicodeDecodeError:
            payload["preview"] = {
                "kind": "binary",
                "size_bytes": size,
                "truncated": truncated,
            }
            return payload
        payload["preview"] = {
            "kind": "text",
            "content": text,
            "size_bytes": size,
            "truncated": truncated,
        }
        return payload


class ReadOnlyCommandRunProjection:
    """GET-only projection over the durable V3-2 CommandRun SQLite store."""

    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path).expanduser() if path else None

    @property
    def configured(self) -> bool:
        return self.path is not None

    @property
    def available(self) -> bool:
        return bool(self.path and self.path.is_file())

    def _connect(self) -> sqlite3.Connection:
        if self.path is None or not self.path.is_file():
            raise FileNotFoundError(self.path or "command store is not configured")
        uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @staticmethod
    def _row_payload(row: sqlite3.Row) -> dict[str, object]:
        context = _json_object(row["context_json"])
        evidence_ids = _json_strings(row["evidence_ids_json"])
        return {
            "schema_version": COMMAND_RUN_PROJECTION_SCHEMA,
            "read_only": True,
            "command_run_id": str(row["command_run_id"]),
            "intent_id": str(row["intent_id"]),
            "command_id": str(row["command_id"]),
            "state": str(row["state"]),
            "config_snapshot_id": (
                str(row["config_snapshot_id"]) if row["config_snapshot_id"] is not None else None
            ),
            "context": {str(key): str(value) for key, value in context.items()},
            "requested_by": str(row["requested_by"]),
            "started_at": str(row["started_at"]) if row["started_at"] is not None else None,
            "finished_at": str(row["finished_at"]) if row["finished_at"] is not None else None,
            "updated_at": str(row["updated_at"]),
            "result": (
                {
                    "status": str(row["result_status"]),
                    "evidence_ids": list(evidence_ids),
                    "message": str(row["result_message"] or ""),
                }
                if row["result_status"] is not None
                else None
            ),
        }

    @staticmethod
    def _base_query() -> str:
        return """
            SELECT
                runs.command_run_id,
                runs.intent_id,
                runs.command_id,
                runs.state,
                runs.started_at,
                runs.finished_at,
                runs.updated_at,
                intents.config_snapshot_id,
                intents.context_json,
                intents.requested_by,
                results.status AS result_status,
                results.evidence_ids_json,
                results.message AS result_message
            FROM command_runs AS runs
            JOIN command_intents AS intents ON intents.intent_id = runs.intent_id
            LEFT JOIN command_results AS results
                ON results.command_run_id = runs.command_run_id
        """

    def get(self, command_run_id: str) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                self._base_query() + " WHERE runs.command_run_id = ?",
                (command_run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(command_run_id)
        return self._row_payload(row)

    def list(self, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        bounded = max(1, min(int(limit), 500))
        with self._connect() as connection:
            rows = connection.execute(
                self._base_query()
                + " ORDER BY runs.updated_at DESC, runs.command_run_id DESC LIMIT ?",
                (bounded,),
            ).fetchall()
        return tuple(self._row_payload(row) for row in rows)

    def for_config_snapshot(self, snapshot_id: str) -> tuple[dict[str, object], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                self._base_query()
                + " WHERE intents.config_snapshot_id = ? "
                "ORDER BY runs.updated_at DESC, runs.command_run_id DESC LIMIT 50",
                (snapshot_id,),
            ).fetchall()
        return tuple(self._row_payload(row) for row in rows)


class WorkbenchLinkProjection:
    """Typed, fail-closed navigation graph over verified Workbench identities."""

    def __init__(
        self,
        *,
        catalog: WorkspaceEvidenceCatalog,
        v2: WorkspaceV2Projection,
        config_registry: ConfigRegistry,
        reserve_projection: ReserveWorkspaceProjection,
        report_paths: Sequence[str | Path],
        agent_audit_path: str | Path | None = None,
        command_store_path: str | Path | None = None,
    ) -> None:
        self.catalog = catalog
        self.v2 = v2
        self.config_registry = config_registry
        self.reserve_projection = reserve_projection
        self.agent_audit_path = Path(agent_audit_path).expanduser() if agent_audit_path else None
        self.command_runs = ReadOnlyCommandRunProjection(command_store_path)
        self.artifacts = WorkspaceArtifactCatalog(
            catalog.bundles(),
            report_paths=report_paths,
        )
        self._evidence_occurrences: dict[str, tuple[tuple[EvidenceBundle, EvidenceRef], ...]] = {}
        self._index_evidence()
        self._config_diffs = self._index_config_diffs()

    def _index_evidence(self) -> None:
        mutable: dict[str, list[tuple[EvidenceBundle, EvidenceRef]]] = {}
        for bundle in self.catalog.bundles():
            for ref in bundle.refs:
                mutable.setdefault(ref.evidence_id, []).append((bundle, ref))
        self._evidence_occurrences = {
            key: tuple(values) for key, values in mutable.items()
        }

    def _index_config_diffs(self) -> Mapping[str, object]:
        output: dict[str, object] = {}
        for descriptor in self.config_registry.projection.descriptors:
            ids = tuple(descriptor.snapshot_ids)
            for left_index, left in enumerate(ids):
                for right in ids[left_index + 1 :]:
                    diff = self.config_registry.diff(left, right)
                    existing = output.get(diff.diff_id)
                    if existing is not None and existing != diff:
                        raise EvidenceContractError(
                            f"conflicting ConfigDiff identity {diff.diff_id!r}"
                        )
                    output[diff.diff_id] = diff
        return MappingProxyType(output)

    @staticmethod
    def _summary(
        *,
        kind: ReferenceKind,
        identity: str,
        label: str,
        authority: str,
        verification: str = "workspace_projection",
        target_url: str = "",
        context: Mapping[str, str] | None = None,
    ) -> WorkbenchReferenceSummary:
        return WorkbenchReferenceSummary(
            kind=kind,
            identity=identity,
            label=label,
            authority=authority,
            verification=verification,
            detail_url=_reference_url(kind, identity),
            target_url=target_url,
            context=context or {},
        )

    @staticmethod
    def _dedupe_related(
        values: Sequence[WorkbenchReferenceSummary],
    ) -> tuple[WorkbenchReferenceSummary, ...]:
        output: dict[tuple[str, str], WorkbenchReferenceSummary] = {}
        for value in values:
            output.setdefault((value.kind, value.identity), value)
        return tuple(output[key] for key in sorted(output))

    def _reference(
        self,
        *,
        summary: WorkbenchReferenceSummary,
        metadata: Mapping[str, object],
        related: Sequence[WorkbenchReferenceSummary] = (),
    ) -> WorkbenchReference:
        return WorkbenchReference(
            kind=summary.kind,
            identity=summary.identity,
            label=summary.label,
            authority=summary.authority,
            verification=summary.verification,
            detail_url=summary.detail_url,
            target_url=summary.target_url,
            context=summary.context,
            metadata=metadata,
            related=self._dedupe_related(tuple(related)),
        )

    def _canonical_evidence_occurrence(self, evidence_id: str) -> tuple[EvidenceBundle, EvidenceRef]:
        occurrences = self._evidence_occurrences.get(evidence_id, ())
        if not occurrences:
            raise KeyError(evidence_id)
        roots = tuple(value for value in occurrences if value[0].root.evidence_id == evidence_id)
        if len(roots) == 1:
            return roots[0]
        if len(roots) > 1:
            raise EvidenceContractError(f"multiple canonical roots share evidence_id {evidence_id!r}")
        signatures = {
            (
                ref.evidence_type,
                ref.schema_version,
                ref.stage.value,
                ref.authority.value,
                ref.program_id,
                ref.spec_id,
                ref.data_version,
            )
            for _, ref in occurrences
        }
        if len(signatures) != 1:
            raise EvidenceContractError(
                f"ambiguous non-root evidence identity {evidence_id!r}"
            )
        return occurrences[0]

    def _evidence(self, evidence_id: str) -> WorkbenchReference:
        bundle, ref = self._canonical_evidence_occurrence(evidence_id)
        is_root = bundle.root.evidence_id == evidence_id
        target_root = bundle.root.evidence_id
        context: dict[str, str] = {}
        if ref.program_id:
            context["program_id"] = ref.program_id
        if ref.stage is EvidenceStage.A4_PORTFOLIO_VALIDATION and is_root:
            context["portfolio_validation_id"] = evidence_id
        related: list[WorkbenchReferenceSummary] = []
        if ref.program_id:
            related.append(
                self._summary(
                    kind="research_program",
                    identity=ref.program_id,
                    label="ResearchProgram",
                    authority="authoritative",
                    target_url=f"/program/{quote(ref.program_id, safe='')}",
                    context={"program_id": ref.program_id},
                )
            )
        if is_root:
            for factor in bundle.factors:
                related.append(
                    self._summary(
                        kind="factor",
                        identity=factor.feature_digest,
                        label=factor.feature_id,
                        authority=ref.authority.value,
                        target_url=f"/factor/{quote(factor.feature_digest, safe='')}",
                        context={
                            **({"program_id": ref.program_id} if ref.program_id else {}),
                            "factor_id": factor.feature_digest,
                        },
                    )
                )
            source_artifact = self.artifacts.source_artifact_id(bundle)
            related.append(
                self._summary(
                    kind="artifact",
                    identity=source_artifact,
                    label="Source report artifact",
                    authority=ref.authority.value,
                    target_url=f"/evidence/{quote(target_root, safe='')}",
                )
            )
            if ref.stage is EvidenceStage.A2P6_ROBUST_RESEARCH:
                for project in self.v2.projects().get("items", []):
                    if not isinstance(project, Mapping) or project.get("program_evidence_id") != evidence_id:
                        continue
                    validation_id = _text(project.get("a4_validation_id"))
                    if validation_id:
                        related.append(
                            self._summary(
                                kind="portfolio_validation",
                                identity=validation_id,
                                label="A4 portfolio validation",
                                authority="authoritative",
                                target_url=f"/portfolio/{quote(validation_id, safe='')}",
                                context={"portfolio_validation_id": validation_id},
                            )
                        )
                    reserve = project.get("reserve")
                    if isinstance(reserve, Mapping):
                        reserve_id = _text(reserve.get("reserve_id"))
                        if reserve_id:
                            related.append(
                                self._summary(
                                    kind="reserve",
                                    identity=reserve_id,
                                    label="A5 reserve lifecycle",
                                    authority="authoritative",
                                    target_url=f"/reserve/{quote(reserve_id, safe='')}",
                                    context={"reserve_id": reserve_id},
                                )
                            )
            if ref.stage is EvidenceStage.A4_PORTFOLIO_VALIDATION:
                for project in self.v2.projects().get("items", []):
                    if not isinstance(project, Mapping) or project.get("a4_validation_id") != evidence_id:
                        continue
                    program_id = _text(project.get("program_id"))
                    if program_id:
                        related.append(
                            self._summary(
                                kind="research_program",
                                identity=program_id,
                                label="Source ResearchProgram",
                                authority="authoritative",
                                target_url=f"/program/{quote(program_id, safe='')}",
                                context={"program_id": program_id},
                            )
                        )
                    reserve = project.get("reserve")
                    if isinstance(reserve, Mapping):
                        reserve_id = _text(reserve.get("reserve_id"))
                        if reserve_id:
                            related.append(
                                self._summary(
                                    kind="reserve",
                                    identity=reserve_id,
                                    label="A5 reserve lifecycle",
                                    authority="authoritative",
                                    target_url=f"/reserve/{quote(reserve_id, safe='')}",
                                    context={"reserve_id": reserve_id},
                                )
                            )
        summary = self._summary(
            kind="evidence",
            identity=evidence_id,
            label=_text(ref.metadata.get("label")) or ref.evidence_type,
            authority=ref.authority.value,
            verification="workspace_catalog_root" if is_root else "workspace_catalog_ref",
            target_url=f"/evidence/{quote(target_root, safe='')}",
            context=context,
        )
        return self._reference(
            summary=summary,
            metadata={
                **ref.to_dict(),
                "canonical_root_evidence_id": target_root,
                "is_root": is_root,
            },
            related=related,
        )

    def _factor(self, digest: str) -> WorkbenchReference:
        occurrences = self.catalog.factor_occurrences(digest)
        if not occurrences:
            raise KeyError(digest)
        first = occurrences[0]
        factor = first["factor"]
        if not isinstance(factor, Mapping):
            raise EvidenceContractError("factor occurrence payload is malformed")
        program_ids = tuple(
            dict.fromkeys(
                _text(item.get("program_id"))
                for item in occurrences
                if _text(item.get("program_id"))
            )
        )
        context = {"factor_id": digest}
        if len(program_ids) == 1:
            context["program_id"] = program_ids[0]
        related: list[WorkbenchReferenceSummary] = []
        for item in occurrences:
            parent_id = _text(item.get("parent_evidence_id"))
            if parent_id:
                related.append(
                    self._summary(
                        kind="evidence",
                        identity=parent_id,
                        label="Parent evidence",
                        authority="authoritative",
                        target_url=f"/evidence/{quote(parent_id, safe='')}",
                    )
                )
        for program_id in program_ids:
            related.append(
                self._summary(
                    kind="research_program",
                    identity=program_id,
                    label="ResearchProgram",
                    authority="authoritative",
                    target_url=f"/program/{quote(program_id, safe='')}",
                    context={"program_id": program_id},
                )
            )
        related.append(
            self._summary(
                kind="artifact",
                identity=digest,
                label="Generated feature artifact",
                authority="authoritative",
                target_url=f"/factor/{quote(digest, safe='')}",
                context=context,
            )
        )
        summary = self._summary(
            kind="factor",
            identity=digest,
            label=_text(factor.get("feature_id")) or "Factor",
            authority="authoritative",
            target_url=f"/factor/{quote(digest, safe='')}",
            context=context,
        )
        return self._reference(
            summary=summary,
            metadata={
                "occurrence_count": len(occurrences),
                "program_ids": list(program_ids),
                "factor": dict(factor),
            },
            related=related,
        )

    def _program(self, program_id: str) -> WorkbenchReference:
        bundle = self.catalog.program(program_id)
        related: list[WorkbenchReferenceSummary] = [
            self._summary(
                kind="evidence",
                identity=bundle.root.evidence_id,
                label="A2.6 root evidence",
                authority=bundle.root.authority.value,
                target_url=f"/evidence/{quote(bundle.root.evidence_id, safe='')}",
                context={"program_id": program_id},
            )
        ]
        for factor in bundle.factors:
            related.append(
                self._summary(
                    kind="factor",
                    identity=factor.feature_digest,
                    label=factor.feature_id,
                    authority=bundle.root.authority.value,
                    target_url=f"/factor/{quote(factor.feature_digest, safe='')}",
                    context={"program_id": program_id, "factor_id": factor.feature_digest},
                )
            )
        for project in self.v2.projects().get("items", []):
            if not isinstance(project, Mapping) or project.get("program_id") != program_id:
                continue
            validation_id = _text(project.get("a4_validation_id"))
            if validation_id:
                related.append(
                    self._summary(
                        kind="portfolio_validation",
                        identity=validation_id,
                        label="A4 portfolio validation",
                        authority="authoritative",
                        target_url=f"/portfolio/{quote(validation_id, safe='')}",
                        context={"program_id": program_id, "portfolio_validation_id": validation_id},
                    )
                )
            reserve = project.get("reserve")
            if isinstance(reserve, Mapping):
                reserve_id = _text(reserve.get("reserve_id"))
                if reserve_id:
                    related.append(
                        self._summary(
                            kind="reserve",
                            identity=reserve_id,
                            label="A5 reserve lifecycle",
                            authority="authoritative",
                            target_url=f"/reserve/{quote(reserve_id, safe='')}",
                            context={"program_id": program_id, "reserve_id": reserve_id},
                        )
                    )
        summary = self._summary(
            kind="research_program",
            identity=program_id,
            label="ResearchProgram",
            authority=bundle.root.authority.value,
            target_url=f"/program/{quote(program_id, safe='')}",
            context={"program_id": program_id},
        )
        return self._reference(
            summary=summary,
            metadata={
                "root_evidence_id": bundle.root.evidence_id,
                "spec_id": bundle.root.spec_id,
                "data_version": bundle.root.data_version,
                "research_status": bundle.research_status,
                "reserve_status": bundle.reserve_status,
                "factor_count": len(bundle.factors),
            },
            related=related,
        )

    def _portfolio_validation(self, validation_id: str) -> WorkbenchReference:
        bundle = self.catalog.bundle(validation_id)
        if bundle.root.stage is not EvidenceStage.A4_PORTFOLIO_VALIDATION:
            raise KeyError(validation_id)
        related: list[WorkbenchReferenceSummary] = [
            self._summary(
                kind="evidence",
                identity=validation_id,
                label="A4 root evidence",
                authority=bundle.root.authority.value,
                target_url=f"/evidence/{quote(validation_id, safe='')}",
                context={"portfolio_validation_id": validation_id},
            )
        ]
        program_id = ""
        reserve_id = ""
        for project in self.v2.projects().get("items", []):
            if not isinstance(project, Mapping) or project.get("a4_validation_id") != validation_id:
                continue
            program_id = _text(project.get("program_id"))
            if program_id:
                related.append(
                    self._summary(
                        kind="research_program",
                        identity=program_id,
                        label="Source ResearchProgram",
                        authority="authoritative",
                        target_url=f"/program/{quote(program_id, safe='')}",
                        context={"program_id": program_id},
                    )
                )
            reserve = project.get("reserve")
            if isinstance(reserve, Mapping):
                reserve_id = _text(reserve.get("reserve_id"))
                if reserve_id:
                    related.append(
                        self._summary(
                            kind="reserve",
                            identity=reserve_id,
                            label="A5 reserve lifecycle",
                            authority="authoritative",
                            target_url=f"/reserve/{quote(reserve_id, safe='')}",
                            context={"reserve_id": reserve_id},
                        )
                    )
        context = {"portfolio_validation_id": validation_id}
        if program_id:
            context["program_id"] = program_id
        if reserve_id:
            context["reserve_id"] = reserve_id
        summary = self._summary(
            kind="portfolio_validation",
            identity=validation_id,
            label="A4 PortfolioValidation",
            authority=bundle.root.authority.value,
            target_url=f"/portfolio/{quote(validation_id, safe='')}",
            context=context,
        )
        return self._reference(
            summary=summary,
            metadata={
                "spec_id": bundle.root.spec_id,
                "data_version": bundle.root.data_version,
                "research_status": bundle.research_status,
                "reserve_status": bundle.reserve_status,
                "has_portfolio": bundle.portfolio is not None,
                "has_execution": bundle.execution is not None,
            },
            related=related,
        )

    def _reserve(self, reserve_id: str) -> WorkbenchReference:
        payload = self.reserve_projection.get(reserve_id)
        related: list[WorkbenchReferenceSummary] = []
        validation_id = _text(payload.get("portfolio_validation_id"))
        if validation_id:
            related.append(
                self._summary(
                    kind="portfolio_validation",
                    identity=validation_id,
                    label="A4 portfolio validation",
                    authority="authoritative",
                    target_url=f"/portfolio/{quote(validation_id, safe='')}",
                    context={"portfolio_validation_id": validation_id},
                )
            )
        program_result_id = _text(payload.get("program_result_id"))
        if program_result_id:
            related.append(
                self._summary(
                    kind="evidence",
                    identity=program_result_id,
                    label="A2.6 program result evidence",
                    authority="authoritative",
                    target_url=f"/evidence/{quote(program_result_id, safe='')}",
                )
            )
        summary = self._summary(
            kind="reserve",
            identity=reserve_id,
            label="A5 Reserve lifecycle",
            authority="authoritative",
            target_url=f"/reserve/{quote(reserve_id, safe='')}",
            context={"reserve_id": reserve_id},
        )
        return self._reference(
            summary=summary,
            metadata={
                "state": payload.get("state"),
                "a5_status": payload.get("a5_status"),
                "integrity": payload.get("integrity"),
                "program_result_id": program_result_id,
                "portfolio_validation_id": validation_id,
                "automatic_retry_allowed": payload.get("automatic_retry_allowed"),
            },
            related=related,
        )

    def _agent_run(self, run_id: str) -> WorkbenchReference:
        if self.agent_audit_path is None:
            raise KeyError(run_id)
        index = load_agent_index(self.agent_audit_path)
        try:
            summary = index.run_summaries[run_id]
            run = index.runs[run_id]
        except KeyError as exc:
            raise KeyError(run_id) from exc
        related: list[WorkbenchReferenceSummary] = []
        for artifact_id in run.artifact_ids:
            if artifact_id in self._evidence_occurrences:
                related.append(
                    self._summary(
                        kind="evidence",
                        identity=artifact_id,
                        label="Agent-linked evidence",
                        authority="authoritative",
                    )
                )
            if self.catalog.factor_occurrences(artifact_id):
                related.append(
                    self._summary(
                        kind="factor",
                        identity=artifact_id,
                        label="Agent-linked factor",
                        authority="authoritative",
                        target_url=f"/factor/{quote(artifact_id, safe='')}",
                    )
                )
            try:
                self.config_registry.snapshot(artifact_id)
            except KeyError:
                pass
            else:
                related.append(
                    self._summary(
                        kind="config_snapshot",
                        identity=artifact_id,
                        label="Agent-linked ConfigSnapshot",
                        authority="derived",
                    )
                )
            if artifact_id in self._config_diffs:
                related.append(
                    self._summary(
                        kind="config_diff",
                        identity=artifact_id,
                        label="Agent-linked ConfigDiff",
                        authority="derived",
                    )
                )
        summary_ref = self._summary(
            kind="agent_run",
            identity=run_id,
            label=summary.objective,
            authority="authoritative",
            verification="canonical_agent_audit",
            target_url=f"/agent?run={quote(run_id, safe='')}",
            context={
                "project_id": summary.project_id,
                "thread_id": summary.thread_id,
                "run_id": run_id,
            },
        )
        return self._reference(
            summary=summary_ref,
            metadata={
                "task_id": summary.task_id,
                "actor": summary.actor,
                "trigger_type": summary.trigger_type,
                "status": summary.status,
                "started_at": summary.started_at.isoformat(),
                "finished_at": summary.finished_at.isoformat() if summary.finished_at else None,
                "item_count": summary.item_count,
                "unresolved_artifact_count": summary.unresolved_artifact_count,
                "hidden_reasoning": "not_persisted_not_projected",
            },
            related=related,
        )

    def _config_snapshot(self, snapshot_id: str) -> WorkbenchReference:
        snapshot = self.config_registry.snapshot(snapshot_id)
        related: list[WorkbenchReferenceSummary] = []
        for diff in self._config_diffs.values():
            left = _text(getattr(diff, "left_snapshot_id", ""))
            right = _text(getattr(diff, "right_snapshot_id", ""))
            if snapshot_id not in {left, right}:
                continue
            diff_id = _text(getattr(diff, "diff_id", ""))
            if diff_id:
                related.append(
                    self._summary(
                        kind="config_diff",
                        identity=diff_id,
                        label="ConfigDiff",
                        authority="derived",
                    )
                )
        if self.command_runs.available:
            for command in self.command_runs.for_config_snapshot(snapshot_id):
                command_run_id = _text(command.get("command_run_id"))
                if command_run_id:
                    related.append(
                        self._summary(
                            kind="command_run",
                            identity=command_run_id,
                            label=f"CommandRun · {_text(command.get('command_id'))}",
                            authority="authoritative",
                        )
                    )
        summary = self._summary(
            kind="config_snapshot",
            identity=snapshot_id,
            label=f"ConfigSnapshot · {snapshot.descriptor_id}",
            authority="derived",
            verification="redacted_public_config_registry",
            target_url="/widgets?surface=configs",
        )
        return self._reference(
            summary=summary,
            metadata=snapshot.to_dict(),
            related=related,
        )

    def _config_diff(self, diff_id: str) -> WorkbenchReference:
        try:
            diff = self._config_diffs[diff_id]
        except KeyError as exc:
            raise KeyError(diff_id) from exc
        left = _text(getattr(diff, "left_snapshot_id", ""))
        right = _text(getattr(diff, "right_snapshot_id", ""))
        related = [
            self._summary(
                kind="config_snapshot",
                identity=value,
                label="ConfigSnapshot",
                authority="derived",
                target_url="/widgets?surface=configs",
            )
            for value in (left, right)
            if value
        ]
        summary = self._summary(
            kind="config_diff",
            identity=diff_id,
            label="ConfigDiff",
            authority="derived",
            verification="deterministic_config_projection",
            target_url="/widgets?surface=configs",
        )
        return self._reference(
            summary=summary,
            metadata=getattr(diff, "to_dict")(),
            related=related,
        )

    def _command_run(self, command_run_id: str) -> WorkbenchReference:
        payload = self.command_runs.get(command_run_id)
        related: list[WorkbenchReferenceSummary] = []
        snapshot_id = _text(payload.get("config_snapshot_id"))
        if snapshot_id:
            related.append(
                self._summary(
                    kind="config_snapshot",
                    identity=snapshot_id,
                    label="Bound ConfigSnapshot",
                    authority="derived",
                    target_url="/widgets?surface=configs",
                )
            )
        result = payload.get("result")
        if isinstance(result, Mapping):
            for evidence_id in result.get("evidence_ids", []):
                text = _text(evidence_id)
                if not text:
                    continue
                try:
                    self._canonical_evidence_occurrence(text)
                except (KeyError, EvidenceContractError):
                    related.append(
                        self._summary(
                            kind="evidence",
                            identity=text,
                            label="Produced evidence · unresolved in current catalog",
                            authority="diagnostic",
                            verification="command_result_unresolved",
                        )
                    )
                else:
                    related.append(
                        self._summary(
                            kind="evidence",
                            identity=text,
                            label="Produced evidence",
                            authority="authoritative",
                        )
                    )
        context = payload.get("context")
        if isinstance(context, Mapping):
            program_id = _text(context.get("program_id"))
            if program_id:
                related.append(
                    self._summary(
                        kind="research_program",
                        identity=program_id,
                        label="Command context ResearchProgram",
                        authority="derived",
                        target_url=f"/program/{quote(program_id, safe='')}",
                        context={"program_id": program_id},
                    )
                )
            validation_id = _text(context.get("portfolio_validation_id"))
            if validation_id:
                related.append(
                    self._summary(
                        kind="portfolio_validation",
                        identity=validation_id,
                        label="Command context A4 validation",
                        authority="derived",
                        target_url=f"/portfolio/{quote(validation_id, safe='')}",
                        context={"portfolio_validation_id": validation_id},
                    )
                )
        summary = self._summary(
            kind="command_run",
            identity=command_run_id,
            label=f"CommandRun · {_text(payload.get('command_id'))}",
            authority="authoritative",
            verification="durable_command_store_read_only",
        )
        return self._reference(summary=summary, metadata=payload, related=related)

    def _artifact(self, artifact_id: str) -> WorkbenchReference:
        item = self.artifacts.descriptor(artifact_id)
        related = [
            self._summary(
                kind="evidence",
                identity=evidence_id,
                label="Artifact evidence",
                authority=item.authority,
            )
            for evidence_id in item.evidence_ids
        ]
        if item.artifact_type == "generated_feature":
            related.append(
                self._summary(
                    kind="factor",
                    identity=item.artifact_id,
                    label=_text(item.metadata.get("feature_id")) or "Factor",
                    authority=item.authority,
                    target_url=item.target_url,
                    context={"factor_id": item.artifact_id},
                )
            )
        summary = self._summary(
            kind="artifact",
            identity=artifact_id,
            label=item.label,
            authority=item.authority,
            verification=item.verification,
            target_url=item.target_url,
        )
        return self._reference(
            summary=summary,
            metadata={
                "artifact_type": item.artifact_type,
                "source_uri": item.source_uri,
                "evidence_ids": list(item.evidence_ids),
                **dict(item.metadata),
            },
            related=related,
        )

    def resolve(self, kind: str, identity: str) -> WorkbenchReference:
        normalized_kind = kind.strip()
        normalized_id = identity.strip()
        if normalized_kind not in _REFERENCE_KINDS or not normalized_id:
            raise ValueError("unsupported or empty Workbench reference")
        if normalized_kind == "evidence":
            return self._evidence(normalized_id)
        if normalized_kind == "artifact":
            return self._artifact(normalized_id)
        if normalized_kind == "factor":
            return self._factor(normalized_id)
        if normalized_kind == "research_program":
            return self._program(normalized_id)
        if normalized_kind == "portfolio_validation":
            return self._portfolio_validation(normalized_id)
        if normalized_kind == "reserve":
            return self._reserve(normalized_id)
        if normalized_kind == "agent_run":
            return self._agent_run(normalized_id)
        if normalized_kind == "config_snapshot":
            return self._config_snapshot(normalized_id)
        if normalized_kind == "config_diff":
            return self._config_diff(normalized_id)
        if normalized_kind == "command_run":
            return self._command_run(normalized_id)
        raise ValueError("unsupported Workbench reference")

    def command_run_list(self, *, limit: int = 100) -> dict[str, object]:
        if not self.command_runs.configured:
            return {
                "schema_version": "finagent.workbench.command-run-list.v1",
                "read_only": True,
                "configured": False,
                "available": False,
                "items": [],
            }
        if not self.command_runs.available:
            return {
                "schema_version": "finagent.workbench.command-run-list.v1",
                "read_only": True,
                "configured": True,
                "available": False,
                "items": [],
            }
        return {
            "schema_version": "finagent.workbench.command-run-list.v1",
            "read_only": True,
            "configured": True,
            "available": True,
            "items": list(self.command_runs.list(limit=limit)),
        }

    def status(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.workbench.deep-link-status.v1",
            "read_only": True,
            "reference_kinds": sorted(_REFERENCE_KINDS),
            "artifact_count": len(self.artifacts.descriptors()),
            "config_diff_count": len(self._config_diffs),
            "agent_audit_configured": self.agent_audit_path is not None,
            "command_store_configured": self.command_runs.configured,
            "command_store_available": self.command_runs.available,
            "hidden_reasoning": "not_persisted_not_projected",
            "phoenix_role": "diagnostic_only_not_product_identity",
        }

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

INITIAL_REQUIREMENT_COMPLIANCE_SCHEMA = (
    "finagent.initial-requirement-compliance-audit.v1"
)

ALLOWED_REQUIREMENT_STATUSES = frozenset({"PASS", "PARTIAL", "DEFERRED", "N/A"})

REQUIRED_REQUIREMENT_IDS = (
    "pit_data_adapter_research_dataset",
    "agent_research_framework",
    "robust_factor_a2p6",
    "a3_ashare_execution_semantics",
    "a4_execution_aware_portfolio",
    "immutable_evidence_identity_replay",
    "a5_one_shot_infrastructure",
    "evidence_governance",
    "workbench_foundation",
    "strategy_analytics",
    "factor_analytics",
    "portfolio_execution_analytics",
    "v4_linked_acceptance",
    "historical_workbench_control",
    "ohlc_evidence",
    "benchmark_evidence",
    "corporate_actions",
    "capacity_impact",
    "advanced_risk",
    "internal_paper",
    "realtime_gateway",
    "qmt",
)

_REQUIREMENT_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{1,127}")


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _non_empty(value: object, name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} must be non-empty")
    return text


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    output = tuple(_non_empty(item, name) for item in value)
    if len(set(output)) != len(output):
        raise ValueError(f"{name} must contain unique values")
    return output


def _reference_path(reference: str) -> str:
    value = reference.split("::", 1)[0].split("#", 1)[0].strip()
    if not value:
        raise ValueError(f"invalid empty repository reference: {reference!r}")
    return value


def _validate_reference(repository_root: Path, reference: str) -> None:
    raw = _reference_path(reference)
    relative = Path(raw)
    if relative.is_absolute():
        raise ValueError(f"repository reference must be relative: {reference!r}")
    root = repository_root.resolve()
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"repository reference escapes root: {reference!r}")
    if not resolved.is_file():
        raise FileNotFoundError(f"repository reference does not exist: {reference!r}")


def _resolve_git_sha(repository_root: Path, explicit: str | None) -> str:
    if explicit is not None:
        value = explicit.strip()
        if not value:
            raise ValueError("git_sha must be non-empty when supplied")
        return value
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "unable to resolve git SHA for A-C4 audit: "
            + (result.stderr.strip() or result.stdout.strip())
        )
    value = result.stdout.strip()
    if not value:
        raise RuntimeError("git rev-parse returned an empty SHA")
    return value


@dataclass(frozen=True, slots=True)
class RequirementComplianceEntry:
    requirement_id: str
    requirement: str
    source_plans: tuple[str, ...]
    implementation_refs: tuple[str, ...]
    test_evidence_refs: tuple[str, ...]
    status: str
    disposition: str
    rationale: str

    def __post_init__(self) -> None:
        requirement_id = _non_empty(self.requirement_id, "requirement_id")
        if _REQUIREMENT_ID_RE.fullmatch(requirement_id) is None:
            raise ValueError(f"unsupported requirement_id: {requirement_id!r}")
        object.__setattr__(self, "requirement_id", requirement_id)
        object.__setattr__(self, "requirement", _non_empty(self.requirement, "requirement"))
        object.__setattr__(self, "disposition", _non_empty(self.disposition, "disposition"))
        object.__setattr__(self, "rationale", _non_empty(self.rationale, "rationale"))
        if self.status not in ALLOWED_REQUIREMENT_STATUSES:
            raise ValueError(f"unsupported requirement status: {self.status!r}")
        if not self.source_plans:
            raise ValueError("every requirement must reference a source plan")
        if self.status == "PASS" and (
            not self.implementation_refs or not self.test_evidence_refs
        ):
            raise ValueError(
                "PASS requirements require implementation and test/evidence references"
            )
        if self.status == "PARTIAL" and not self.implementation_refs:
            raise ValueError("PARTIAL requirements require implementation references")

    def to_dict(self) -> dict[str, object]:
        return {
            "requirement_id": self.requirement_id,
            "requirement": self.requirement,
            "source_plan": list(self.source_plans),
            "implementation": list(self.implementation_refs),
            "test_evidence": list(self.test_evidence_refs),
            "status": self.status,
            "disposition": self.disposition,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class InitialRequirementComplianceAudit:
    audit_name: str
    git_sha: str
    manifest_path: str
    manifest_sha256: str
    entries: tuple[RequirementComplianceEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "audit_name", _non_empty(self.audit_name, "audit_name"))
        object.__setattr__(self, "git_sha", _non_empty(self.git_sha, "git_sha"))
        object.__setattr__(
            self,
            "manifest_path",
            _non_empty(self.manifest_path, "manifest_path"),
        )
        object.__setattr__(
            self,
            "manifest_sha256",
            _non_empty(self.manifest_sha256, "manifest_sha256"),
        )
        if not self.entries:
            raise ValueError("A-C4 audit requires requirement entries")
        ids = tuple(entry.requirement_id for entry in self.entries)
        if len(set(ids)) != len(ids):
            raise ValueError("A-C4 requirement ids must be unique")
        if set(ids) != set(REQUIRED_REQUIREMENT_IDS):
            missing = sorted(set(REQUIRED_REQUIREMENT_IDS) - set(ids))
            unexpected = sorted(set(ids) - set(REQUIRED_REQUIREMENT_IDS))
            raise ValueError(
                "A-C4 requirement denominator differs from frozen minimum; "
                f"missing={missing}, unexpected={unexpected}"
            )

    @property
    def status_counts(self) -> Mapping[str, int]:
        counts = Counter(entry.status for entry in self.entries)
        return MappingProxyType(
            {
                status: int(counts.get(status, 0))
                for status in sorted(ALLOWED_REQUIREMENT_STATUSES)
            }
        )

    @property
    def audit_complete(self) -> bool:
        return len(self.entries) == len(REQUIRED_REQUIREMENT_IDS)

    @property
    def historical_freeze_ready(self) -> bool:
        return self.audit_complete and all(
            entry.status != "PARTIAL" for entry in self.entries
        )

    @property
    def audit_id(self) -> str:
        payload = {
            "schema_version": INITIAL_REQUIREMENT_COMPLIANCE_SCHEMA,
            "audit_name": self.audit_name,
            "git_sha": self.git_sha,
            "manifest_sha256": self.manifest_sha256,
            "requirements": [entry.to_dict() for entry in self.entries],
        }
        return f"ac4-audit-{_sha256_text(_canonical_json(payload))[:24]}"

    def to_dict(self) -> dict[str, object]:
        deferred = [
            entry.requirement_id
            for entry in self.entries
            if entry.status == "DEFERRED"
        ]
        return {
            "schema_version": INITIAL_REQUIREMENT_COMPLIANCE_SCHEMA,
            "audit_id": self.audit_id,
            "audit_name": self.audit_name,
            "git_sha": self.git_sha,
            "manifest": {
                "path": self.manifest_path,
                "sha256": self.manifest_sha256,
            },
            "authority": "read_only_compliance_audit_no_financial_or_operational_authority",
            "production_reserve_authority": False,
            "reserve_accessed_by_audit": False,
            "audit_complete": self.audit_complete,
            "historical_freeze_ready": self.historical_freeze_ready,
            "required_requirement_ids": list(REQUIRED_REQUIREMENT_IDS),
            "summary": dict(self.status_counts),
            "deferred_capabilities": deferred,
            "requirements": [entry.to_dict() for entry in self.entries],
        }

    def to_markdown(self) -> str:
        lines = [
            "# FinAgent A-C4 Initial Requirement Compliance Audit",
            "",
            f"- Audit ID: `{self.audit_id}`",
            f"- Git SHA: `{self.git_sha}`",
            f"- Manifest SHA-256: `{self.manifest_sha256}`",
            f"- Audit complete: `{str(self.audit_complete).lower()}`",
            f"- Historical freeze ready: `{str(self.historical_freeze_ready).lower()}`",
            "- Authority: read-only compliance audit; no reserve/PAPER/broker/live authority",
            "",
            "| ID | Requirement | Source plan | Implementation | Test / evidence | Status | Disposition |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for entry in self.entries:
            source = "<br>".join(f"`{value}`" for value in entry.source_plans)
            implementation = "<br>".join(
                f"`{value}`" for value in entry.implementation_refs
            ) or "—"
            evidence = "<br>".join(
                f"`{value}`" for value in entry.test_evidence_refs
            ) or "—"
            lines.append(
                "| "
                + " | ".join(
                    (
                        f"`{entry.requirement_id}`",
                        entry.requirement.replace("|", "\\|"),
                        source,
                        implementation,
                        evidence,
                        entry.status,
                        entry.disposition.replace("|", "\\|"),
                    )
                )
                + " |"
            )
        lines.extend(("", "## Rationale / follow-up", ""))
        for entry in self.entries:
            lines.append(
                f"- **{entry.requirement_id} ({entry.status})** — {entry.rationale}"
            )
        lines.append("")
        return "\n".join(lines)

    def write_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        return target

    def write_markdown(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.to_markdown(), encoding="utf-8")
        return target


def _entry(payload: Mapping[str, object]) -> RequirementComplianceEntry:
    return RequirementComplianceEntry(
        requirement_id=_non_empty(payload.get("id"), "requirements.id"),
        requirement=_non_empty(payload.get("requirement"), "requirements.requirement"),
        source_plans=_strings(payload.get("source_plan"), "requirements.source_plan"),
        implementation_refs=_strings(
            payload.get("implementation", []), "requirements.implementation"
        ),
        test_evidence_refs=_strings(
            payload.get("test_evidence", []), "requirements.test_evidence"
        ),
        status=_non_empty(payload.get("status"), "requirements.status"),
        disposition=_non_empty(payload.get("disposition"), "requirements.disposition"),
        rationale=_non_empty(payload.get("rationale"), "requirements.rationale"),
    )


def load_initial_requirement_manifest(
    path: str | Path,
) -> tuple[str, tuple[RequirementComplianceEntry, ...]]:
    manifest = Path(path)
    with manifest.open("rb") as handle:
        payload = tomllib.load(handle)
    audit = payload.get("audit")
    if not isinstance(audit, Mapping):
        raise TypeError("A-C4 manifest must contain an [audit] table")
    raw_requirements = payload.get("requirements")
    if not isinstance(raw_requirements, list):
        raise TypeError("A-C4 manifest must contain [[requirements]] entries")
    entries = tuple(
        _entry(item)
        for item in raw_requirements
        if isinstance(item, Mapping)
    )
    if len(entries) != len(raw_requirements):
        raise TypeError("every A-C4 requirement entry must be a table")
    return _non_empty(audit.get("name"), "audit.name"), entries


def run_initial_requirement_compliance_audit(
    manifest_path: str | Path,
    *,
    repository_root: str | Path = ".",
    git_sha: str | None = None,
) -> InitialRequirementComplianceAudit:
    root = Path(repository_root).resolve()
    manifest = Path(manifest_path)
    if not manifest.is_absolute():
        manifest = root / manifest
    manifest = manifest.resolve()
    if root not in manifest.parents:
        raise ValueError("A-C4 manifest must live under repository_root")
    if not manifest.is_file():
        raise FileNotFoundError(manifest)

    audit_name, entries = load_initial_requirement_manifest(manifest)
    for entry in entries:
        for reference in (
            *entry.source_plans,
            *entry.implementation_refs,
            *entry.test_evidence_refs,
        ):
            _validate_reference(root, reference)

    relative_manifest = manifest.relative_to(root).as_posix()
    manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return InitialRequirementComplianceAudit(
        audit_name=audit_name,
        git_sha=_resolve_git_sha(root, git_sha),
        manifest_path=relative_manifest,
        manifest_sha256=manifest_sha256,
        entries=entries,
    )

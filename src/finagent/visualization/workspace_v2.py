from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import sqlite3
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from finagent.runtime import DEFAULT_PARALLEL_POLICY, ParallelPlan

from .semantic import (
    EvidenceAuthority,
    EvidenceBundle,
    EvidenceContractError,
    EvidenceStage,
    LineageEdge,
    LineageGraph,
    LineageNode,
)


WORKSPACE_V2_SCHEMA = "finagent.workspace.v2"
CATALOG_SCHEMA = "finagent.workspace.evidence-catalog.v2"
PROTOCOL_DIFF_SCHEMA = "finagent.workspace.protocol-diff.v2"
REVIEW_BUNDLE_SCHEMA = "finagent.workspace.review-bundle.v2"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(prefix: str, value: object, length: int = 64) -> str:
    raw = hashlib.sha256(_canonical_json(value).encode()).hexdigest()[:length]
    return f"{prefix}-{raw}"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return ()


def _number(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        result = float(cast(Any, value))
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _integer(value: object, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return default


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(child) for key, child in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_jsonable(child) for child in value]
    return value


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise EvidenceContractError(f"{path}: JSON root must be an object")
    return value


def _read_jsonl(path: Path) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise EvidenceContractError(
                    f"{path}:{line_number}: invalid JSONL row"
                ) from exc
            if not isinstance(value, Mapping):
                raise EvidenceContractError(
                    f"{path}:{line_number}: JSONL row must be an object"
                )
            rows.append(value)
    if not rows:
        raise EvidenceContractError(f"{path}: execution ledger is empty")
    return tuple(rows)


def _file_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
    except OSError:
        return ""


def _flatten(value: object, prefix: str = "") -> dict[str, object]:
    output: dict[str, object] = {}
    if isinstance(value, Mapping):
        for key, child in sorted(value.items(), key=lambda item: str(item[0])):
            name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(child, Mapping):
                output.update(_flatten(child, name))
            else:
                output[name] = _jsonable(child)
        return output
    output[prefix or "value"] = _jsonable(value)
    return output


def _reason_category(reason: str) -> str:
    upper = reason.upper()
    if upper.startswith("MODEL_ERROR") or "MODEL_" in upper or "ALPHA" in upper or "RISK" in upper:
        return "model/cash fallback"
    if "T1_" in upper or "SELLABLE" in upper:
        return "T+1"
    if "LOT" in upper or "QUANTITY" in upper or "NOTIONAL" in upper:
        return "lot / quantity"
    if "SUSPEND" in upper:
        return "suspension"
    if "LIMIT_UP" in upper or "LIMIT_DOWN" in upper or "PRICE_LIMIT" in upper:
        return "price limit"
    if "CASH" in upper:
        return "cash scaling"
    if "SESSION" in upper or "DATA" in upper:
        return "session / data"
    if upper in {"ACCEPTED", "MODEL_TARGET", "NOT_REBALANCE_SESSION", "NO_TARGET_DELTA"}:
        return "normal / no action"
    return "other"


@dataclass(frozen=True, slots=True)
class LedgerArtifact:
    path: Path
    digest: str
    rows: tuple[Mapping[str, Any], ...]

    def summary(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "path": str(self.path),
            "row_count": len(self.rows),
            "authority": EvidenceAuthority.AUTHORITATIVE.value,
        }


class WorkspaceV2Projection:
    """Read-only V2 product projection over immutable V0/V1 evidence.

    This class may rebuild a disposable SQLite catalog and may create an export ZIP
    when explicitly requested by a GET download/CLI. It never writes research reports,
    Agent audit stores, reserve state, promotion state, or broker state.
    """

    def __init__(
        self,
        bundles: Sequence[EvidenceBundle],
        *,
        report_paths: Sequence[str | Path] = ("reports",),
        catalog_db_path: str | Path | None = None,
        git_sha: str = "",
    ) -> None:
        self.bundles = tuple(bundles)
        self.report_paths = tuple(Path(value).expanduser() for value in report_paths)
        self.git_sha = git_sha.strip()
        self.catalog_db_path = Path(catalog_db_path).expanduser() if catalog_db_path else None
        self._by_root_id = {bundle.root.evidence_id: bundle for bundle in self.bundles}
        self._raw: dict[str, Mapping[str, Any]] = {}
        self._warnings: list[str] = []
        self._parallel_plans: dict[str, ParallelPlan] = {}
        self._load_raw_reports()
        self._ledgers = self._scan_ledgers()
        self._catalog_rows = self._build_catalog_rows()
        if self.catalog_db_path is not None:
            self._write_catalog(self.catalog_db_path)

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(self._warnings)

    def parallel_diagnostics(self) -> dict[str, object]:
        return {name: plan.to_dict() for name, plan in sorted(self._parallel_plans.items())}

    @staticmethod
    def _candidate_roots(paths: Iterable[Path]) -> tuple[Path, ...]:
        roots: set[Path] = set()
        for value in paths:
            if value.is_file():
                roots.add(value.parent.resolve())
            elif value.is_dir():
                roots.add(value.resolve())
        return tuple(sorted(roots, key=lambda item: item.as_posix()))

    def _load_raw_reports(self) -> None:
        entries = tuple(
            (bundle.root.evidence_id, Path(bundle.root.source_uri).expanduser())
            for bundle in self.bundles
        )
        plan = DEFAULT_PARALLEL_POLICY.resolve(
            len(entries), workload="io", per_worker_memory_mb=64
        )
        self._parallel_plans["v2_raw_reports"] = plan

        def load(entry: tuple[str, Path]):
            evidence_id, source = entry
            if not source.is_file():
                return evidence_id, source, None, FileNotFoundError(source)
            try:
                return evidence_id, source, _read_json(source), None
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                return evidence_id, source, None, exc

        if plan.workers > 1 and len(entries) > 1:
            with ThreadPoolExecutor(
                max_workers=plan.workers,
                thread_name_prefix="finagent-v2-raw",
            ) as executor:
                loaded = tuple(executor.map(load, entries))
        else:
            loaded = tuple(load(entry) for entry in entries)

        for evidence_id, source, payload, error in loaded:
            if error is not None:
                if isinstance(error, FileNotFoundError):
                    self._warnings.append(
                        f"{evidence_id}: source report is unavailable for V2 raw projection"
                    )
                else:
                    self._warnings.append(
                        f"{source}: V2 raw projection failed: {type(error).__name__}: {error}"
                    )
                continue
            assert payload is not None
            self._raw[evidence_id] = payload

    def _scan_ledgers(self) -> dict[str, LedgerArtifact]:
        expected = {
            _text(_mapping(raw).get("ledger_digest"))
            for raw in self._raw.values()
            if _text(_mapping(raw).get("schema_version"))
            == "finagent.ashare-portfolio-validation.v1"
        }
        expected.discard("")
        paths = tuple(
            sorted(
                {
                    path.resolve()
                    for root in self._candidate_roots(self.report_paths)
                    for path in root.rglob("*.jsonl")
                    if path.is_file()
                },
                key=lambda value: value.as_posix(),
            )
        )
        plan = DEFAULT_PARALLEL_POLICY.resolve(
            len(paths), workload="io", per_worker_memory_mb=128
        )
        self._parallel_plans["v2_ledgers"] = plan
        if not expected:
            return {}

        def inspect(path: Path):
            try:
                rows = _read_jsonl(path)
                digest = _digest("a4-execution-ledger", rows, 64)
                return path, digest, rows, None
            except (
                OSError,
                ValueError,
                TypeError,
                json.JSONDecodeError,
                EvidenceContractError,
            ) as exc:
                return path, "", (), exc

        if plan.workers > 1 and len(paths) > 1:
            with ThreadPoolExecutor(
                max_workers=plan.workers,
                thread_name_prefix="finagent-v2-ledger",
            ) as executor:
                inspected = tuple(executor.map(inspect, paths))
        else:
            inspected = tuple(inspect(path) for path in paths)

        output: dict[str, LedgerArtifact] = {}
        for path, digest, rows, error in inspected:
            if error is not None:
                self._warnings.append(
                    f"{path}: ledger scan skipped: {type(error).__name__}: {error}"
                )
                continue
            if digest not in expected:
                continue
            artifact = LedgerArtifact(path=path, digest=digest, rows=rows)
            existing = output.get(digest)
            if existing is not None and existing.rows != rows:
                self._warnings.append(
                    f"{path}: conflicting execution ledgers share digest {digest!r}; omitted"
                )
                output.pop(digest, None)
                expected.discard(digest)
                continue
            output[digest] = artifact
        missing = sorted(expected - set(output))
        for digest in missing:
            self._warnings.append(
                f"execution ledger {digest!r} is referenced by A4 but no matching JSONL was found"
            )
        return output

    def _selection_id(self, bundle: EvidenceBundle, raw: Mapping[str, Any]) -> str:
        if bundle.root.stage is EvidenceStage.A2P6_ROBUST_RESEARCH:
            return _text(_mapping(raw.get("frozen_selection")).get("selection_id"))
        if bundle.root.stage is EvidenceStage.A4_PORTFOLIO_VALIDATION:
            return _text(_mapping(raw.get("validation_spec")).get("source_selection_id"))
        return ""

    def _build_catalog_rows(self) -> tuple[dict[str, object], ...]:
        rows: dict[str, dict[str, object]] = {}
        conflicts: set[str] = set()
        for bundle in self.bundles:
            raw = self._raw.get(bundle.root.evidence_id, {})
            selection_id = self._selection_id(bundle, raw)
            root_source = Path(bundle.root.source_uri).expanduser()
            status_by_id = {
                bundle.root.evidence_id: bundle.research_status,
                **{
                    ref.evidence_id: _text(ref.metadata.get("status"))
                    for ref in bundle.refs
                },
            }
            for ref in bundle.refs:
                if ref.evidence_id in conflicts:
                    continue
                row: dict[str, object] = {
                    "evidence_id": ref.evidence_id,
                    "schema_version": ref.schema_version,
                    "evidence_type": ref.evidence_type,
                    "stage": ref.stage.value,
                    "authority": ref.authority.value,
                    "source_uri": ref.source_uri,
                    "artifact_digest": ref.artifact_digest,
                    "program_id": ref.program_id or bundle.root.program_id,
                    "spec_id": ref.spec_id or bundle.root.spec_id,
                    "selection_id": selection_id,
                    "parent_ids": list(ref.parent_ids),
                    "status": status_by_id.get(ref.evidence_id, ""),
                    "reserve_status": bundle.reserve_status,
                    "modified_at": _file_mtime(root_source),
                    "is_root": ref.evidence_id == bundle.root.evidence_id,
                }
                existing = rows.get(ref.evidence_id)
                if existing is None:
                    rows[ref.evidence_id] = row
                    continue
                comparable = dict(existing)
                comparable.pop("source_uri", None)
                comparable.pop("modified_at", None)
                comparable.pop("is_root", None)
                incoming = dict(row)
                incoming.pop("source_uri", None)
                incoming.pop("modified_at", None)
                incoming.pop("is_root", None)
                if comparable != incoming:
                    rows.pop(ref.evidence_id, None)
                    conflicts.add(ref.evidence_id)
                    self._warnings.append(
                        f"V2 catalog conflict: evidence_id {ref.evidence_id!r} has incompatible projections"
                    )
                elif bool(row["is_root"]):
                    rows[ref.evidence_id] = row
        return tuple(rows[key] for key in sorted(rows))

    def _write_catalog(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        os.close(fd)
        temp = Path(temp_name)
        try:
            connection = sqlite3.connect(temp)
            try:
                connection.execute(
                    """
                    CREATE TABLE evidence_catalog (
                        evidence_id TEXT PRIMARY KEY,
                        schema_version TEXT NOT NULL,
                        evidence_type TEXT NOT NULL,
                        stage TEXT NOT NULL,
                        authority TEXT NOT NULL,
                        source_uri TEXT NOT NULL,
                        artifact_digest TEXT NOT NULL,
                        program_id TEXT NOT NULL,
                        spec_id TEXT NOT NULL,
                        selection_id TEXT NOT NULL,
                        parent_ids_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        reserve_status TEXT NOT NULL,
                        modified_at TEXT NOT NULL,
                        is_root INTEGER NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                for row in self._catalog_rows:
                    connection.execute(
                        "INSERT INTO evidence_catalog VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            row["evidence_id"],
                            row["schema_version"],
                            row["evidence_type"],
                            row["stage"],
                            row["authority"],
                            row["source_uri"],
                            row["artifact_digest"],
                            row["program_id"],
                            row["spec_id"],
                            row["selection_id"],
                            _canonical_json(row["parent_ids"]),
                            row["status"],
                            row["reserve_status"],
                            row["modified_at"],
                            1 if row["is_root"] else 0,
                        ),
                    )
                metadata = {
                    "schema_version": CATALOG_SCHEMA,
                    "read_only_product_surface": "true",
                    "source_count": str(len(self.bundles)),
                    "git_sha": self.git_sha,
                }
                connection.executemany(
                    "INSERT INTO metadata VALUES (?, ?)", tuple(metadata.items())
                )
                connection.commit()
            finally:
                connection.close()
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def catalog(self) -> dict[str, object]:
        return {
            "schema_version": CATALOG_SCHEMA,
            "read_only": True,
            "derived": True,
            "db_path": str(self.catalog_db_path) if self.catalog_db_path else None,
            "items": [dict(row) for row in self._catalog_rows],
            "warnings": list(self.warnings),
        }

    def bundle(self, evidence_id: str) -> EvidenceBundle:
        try:
            return self._by_root_id[evidence_id]
        except KeyError as exc:
            raise KeyError(evidence_id) from exc

    def raw_evidence(self, evidence_id: str) -> dict[str, object]:
        bundle = self.bundle(evidence_id)
        raw = self._raw.get(evidence_id)
        if raw is None:
            raise KeyError(evidence_id)
        return {
            "schema_version": "finagent.workspace.raw-evidence.v2",
            "read_only": True,
            "evidence_id": evidence_id,
            "authority": bundle.root.authority.value,
            "source_schema": _text(raw.get("schema_version")),
            "artifact_digest": bundle.root.artifact_digest,
            "payload": _jsonable(raw),
        }

    def _program_bundle(self, program_id: str) -> EvidenceBundle:
        matches = [
            bundle
            for bundle in self.bundles
            if bundle.root.stage is EvidenceStage.A2P6_ROBUST_RESEARCH
            and bundle.root.program_id == program_id
        ]
        if len(matches) != 1:
            raise KeyError(program_id)
        return matches[0]

    def _a4_bundle(self, validation_id: str) -> EvidenceBundle:
        bundle = self.bundle(validation_id)
        if bundle.root.stage is not EvidenceStage.A4_PORTFOLIO_VALIDATION:
            raise KeyError(validation_id)
        return bundle

    def _a4_for_source(self, source_program_result_id: str) -> tuple[EvidenceBundle, ...]:
        values: list[EvidenceBundle] = []
        for bundle in self.bundles:
            if bundle.root.stage is not EvidenceStage.A4_PORTFOLIO_VALIDATION:
                continue
            raw = self._raw.get(bundle.root.evidence_id, {})
            spec = _mapping(raw.get("validation_spec"))
            if _text(spec.get("source_program_result_id")) == source_program_result_id:
                values.append(bundle)
        return tuple(sorted(values, key=lambda item: item.root.evidence_id))

    @staticmethod
    def _reserve(raw: Mapping[str, Any], fallback: str) -> dict[str, object]:
        reserve = _mapping(raw.get("reserve"))
        return {
            "reserve_id": _text(reserve.get("reserve_id")),
            "start": _text(reserve.get("start")),
            "end": _text(reserve.get("end")),
            "status": _text(reserve.get("status")) or fallback,
            "authority": EvidenceAuthority.AUTHORITATIVE.value,
        }

    def projects(self) -> dict[str, object]:
        items: list[dict[str, object]] = []
        consumed_a4: set[str] = set()
        programs = [
            bundle
            for bundle in self.bundles
            if bundle.root.stage is EvidenceStage.A2P6_ROBUST_RESEARCH
        ]
        for program in sorted(programs, key=lambda value: value.root.program_id):
            raw = self._raw.get(program.root.evidence_id, {})
            selection = _mapping(raw.get("frozen_selection"))
            a4_values = self._a4_for_source(program.root.evidence_id)
            a4 = a4_values[-1] if a4_values else None
            if a4 is not None:
                consumed_a4.add(a4.root.evidence_id)
            a4_raw = self._raw.get(a4.root.evidence_id, {}) if a4 else {}
            a4_spec = _mapping(a4_raw.get("validation_spec"))
            reserve = self._reserve(a4_raw or raw, program.reserve_status)
            frozen = (
                _text(raw.get("program_status")) == "frozen"
                and _text(selection.get("status")) == "ROBUST_FACTOR_FAMILY_FROZEN"
            )
            a4_passed = bool(
                _mapping(a4_raw.get("research_outcome")).get("execution_validation_passed")
            ) if a4 else False
            items.append(
                {
                    "project_id": program.root.program_id,
                    "program_id": program.root.program_id,
                    "program_evidence_id": program.root.evidence_id,
                    "program_spec_id": program.root.spec_id,
                    "selection_id": _text(selection.get("selection_id")),
                    "data_version": program.root.data_version,
                    "git_sha": program.root.git_sha,
                    "system_status": program.system_status,
                    "research_status": program.research_status,
                    "protocol_frozen": frozen,
                    "a3_status": "BOUND_IN_A4_PROTOCOL" if a4 else "AWAITING_A4_BINDING",
                    "a3_authority": EvidenceAuthority.DERIVED.value,
                    "a4_validation_id": a4.root.evidence_id if a4 else "",
                    "a4_spec_id": _text(a4_spec.get("spec_id")),
                    "a4_status": a4.research_status if a4 else "NOT_AVAILABLE",
                    "a4_execution_validation_passed": a4_passed,
                    "reserve": reserve,
                    "promotion_eligible": bool(a4.promotion_eligible if a4 else program.promotion_eligible),
                    "a5_status": (
                        "LOCKED_NOT_CONSUMED"
                        if a4 and reserve["status"] == "untouched"
                        else "NOT_READY"
                    ),
                    "lifecycle": [
                        {
                            "stage": "A2.6",
                            "label": "Research frozen",
                            "status": "complete" if frozen else "incomplete",
                            "authority": EvidenceAuthority.AUTHORITATIVE.value,
                        },
                        {
                            "stage": "A3",
                            "label": "Execution protocol bound",
                            "status": "complete" if a4 else "pending",
                            "authority": EvidenceAuthority.DERIVED.value,
                        },
                        {
                            "stage": "A4",
                            "label": "Internal validation",
                            "status": "complete" if a4 else "pending",
                            "authority": EvidenceAuthority.AUTHORITATIVE.value if a4 else EvidenceAuthority.DERIVED.value,
                        },
                        {
                            "stage": "A5",
                            "label": "One-shot reserve",
                            "status": "locked" if reserve["status"] == "untouched" else _text(reserve["status"]),
                            "authority": EvidenceAuthority.AUTHORITATIVE.value,
                        },
                    ],
                }
            )
        # Preserve orphan A4 evidence in the product catalog rather than silently hiding it.
        for a4 in sorted(
            (
                bundle
                for bundle in self.bundles
                if bundle.root.stage is EvidenceStage.A4_PORTFOLIO_VALIDATION
                and bundle.root.evidence_id not in consumed_a4
            ),
            key=lambda value: value.root.evidence_id,
        ):
            raw = self._raw.get(a4.root.evidence_id, {})
            spec = _mapping(raw.get("validation_spec"))
            source = _text(spec.get("source_program_result_id"))
            items.append(
                {
                    "project_id": source or a4.root.evidence_id,
                    "program_id": "",
                    "program_evidence_id": source,
                    "program_spec_id": _text(spec.get("source_program_spec_id")),
                    "selection_id": _text(spec.get("source_selection_id")),
                    "data_version": a4.root.data_version,
                    "git_sha": a4.root.git_sha,
                    "system_status": a4.system_status,
                    "research_status": _text(raw.get("source_research_status")) or "SOURCE_NOT_CATALOGED",
                    "protocol_frozen": True,
                    "a3_status": "BOUND_IN_A4_PROTOCOL",
                    "a3_authority": EvidenceAuthority.DERIVED.value,
                    "a4_validation_id": a4.root.evidence_id,
                    "a4_spec_id": a4.root.spec_id,
                    "a4_status": a4.research_status,
                    "a4_execution_validation_passed": bool(
                        _mapping(raw.get("research_outcome")).get("execution_validation_passed")
                    ),
                    "reserve": self._reserve(raw, a4.reserve_status),
                    "promotion_eligible": a4.promotion_eligible,
                    "a5_status": "LOCKED_NOT_CONSUMED" if a4.reserve_status == "untouched" else "NOT_READY",
                    "lifecycle": [],
                    "warning": "source A2.6 evidence is not present in the configured catalog",
                }
            )
        return {
            "schema_version": "finagent.workspace.projects.v2",
            "read_only": True,
            "items": items,
            "warnings": list(self.warnings),
        }

    @staticmethod
    def _candidate_by_digest(raw: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        walk = _mapping(raw.get("walk_forward_report"))
        return {
            _text(_mapping(value).get("feature_digest")): _mapping(value)
            for value in _sequence(walk.get("candidates"))
            if _text(_mapping(value).get("feature_digest"))
        }

    @staticmethod
    def _gate_by_digest(raw: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        gate = _mapping(raw.get("gate_report"))
        return {
            _text(_mapping(value).get("feature_digest")): _mapping(value)
            for value in _sequence(gate.get("candidates"))
            if _text(_mapping(value).get("feature_digest"))
        }

    @staticmethod
    def _candidate_metric(candidate: Mapping[str, Any], key: str) -> float:
        if key == "raw_hac_pvalue":
            return _number(_mapping(candidate.get("hac")).get("raw_pvalue"), 1.0)
        if key == "bh_qvalue":
            return _number(_mapping(candidate.get("hac")).get("bh_qvalue"), 1.0)
        return _number(candidate.get(key))

    def program_gates(self, program_id: str) -> dict[str, object]:
        bundle = self._program_bundle(program_id)
        raw = self._raw.get(bundle.root.evidence_id)
        if raw is None:
            raise KeyError(program_id)
        gate = _mapping(raw.get("gate_report"))
        config = _mapping(gate.get("config"))
        candidates = self._candidate_by_digest(raw)
        evaluations = self._gate_by_digest(raw)
        criteria_spec = (
            ("Positive folds", "positive_fold_ratio", "min_positive_fold_ratio", ">="),
            ("Direction consistency", "direction_consistency", "min_direction_consistency", ">="),
            ("Pooled RankICIR", "pooled_rank_icir", "min_pooled_rank_icir", ">="),
            ("Mean-fold RankICIR", "mean_fold_rank_icir", "min_mean_fold_rank_icir", ">="),
            ("Worst-fold RankICIR", "worst_fold_rank_icir", "min_worst_fold_rank_icir", ">="),
            (
                "Mean-fold long/short Sharpe",
                "mean_fold_long_short_sharpe",
                "min_mean_fold_long_short_sharpe",
                ">=",
            ),
            ("Coverage", "coverage_min", "min_coverage", ">="),
            ("Quantile monotonicity", "quantile_monotonicity", "min_quantile_monotonicity", ">="),
            (
                "Horizon sign consistency",
                "horizon_sign_consistency",
                "min_horizon_sign_consistency",
                ">=",
            ),
            ("HAC p-value", "raw_hac_pvalue", "max_hac_pvalue", "<="),
            ("BH q-value", "bh_qvalue", "max_bh_qvalue", "<="),
            ("Turnover", "mean_one_way_turnover", "max_mean_one_way_turnover", "<="),
        )
        rows: list[dict[str, object]] = []
        for digest, candidate in sorted(candidates.items()):
            evaluation = evaluations.get(digest, {})
            checks: list[dict[str, object]] = []
            for label, metric_key, threshold_key, operator in criteria_spec:
                metric = self._candidate_metric(candidate, metric_key)
                threshold_raw = config.get(threshold_key)
                if threshold_raw is None:
                    passed: bool | None = None
                    threshold: float | None = None
                else:
                    threshold = _number(threshold_raw)
                    passed = metric >= threshold if operator == ">=" else metric <= threshold
                checks.append(
                    {
                        "criterion": label,
                        "metric": metric,
                        "metric_key": metric_key,
                        "operator": operator,
                        "threshold": threshold,
                        "threshold_key": threshold_key,
                        "passed": passed,
                        "authority": EvidenceAuthority.DERIVED.value,
                    }
                )
            rows.append(
                {
                    "feature_id": _text(candidate.get("feature_id")),
                    "feature_digest": digest,
                    "passed": bool(evaluation.get("passed")),
                    "reason_codes": [str(value) for value in _sequence(evaluation.get("reason_codes"))],
                    "robust_score": _number(evaluation.get("robust_score")),
                    "checks": checks,
                }
            )
        return {
            "schema_version": "finagent.workspace.factor-gates.v2",
            "read_only": True,
            "program_id": program_id,
            "evidence_id": bundle.root.evidence_id,
            "gate_report_id": _text(gate.get("gate_report_id")),
            "gate_config": _jsonable(config),
            "overall_authority": EvidenceAuthority.AUTHORITATIVE.value,
            "criterion_cell_authority": EvidenceAuthority.DERIVED.value,
            "items": rows,
        }

    def program_statistics(self, program_id: str) -> dict[str, object]:
        bundle = self._program_bundle(program_id)
        raw = self._raw.get(bundle.root.evidence_id)
        if raw is None:
            raise KeyError(program_id)
        candidates = self._candidate_by_digest(raw)
        evaluations = self._gate_by_digest(raw)
        items: list[dict[str, object]] = []
        for digest, candidate in sorted(candidates.items()):
            hac = _mapping(candidate.get("hac"))
            bootstrap = _mapping(candidate.get("block_bootstrap"))
            evaluation = evaluations.get(digest, {})
            items.append(
                {
                    "feature_id": _text(candidate.get("feature_id")),
                    "feature_digest": digest,
                    "passed": bool(evaluation.get("passed")),
                    "effect": _number(candidate.get("pooled_rank_ic")),
                    "effect_metric": "pooled_rank_ic",
                    "bootstrap_ci_lower": _number(bootstrap.get("ci_lower")),
                    "bootstrap_ci_upper": _number(bootstrap.get("ci_upper")),
                    "hac_tstat": _number(hac.get("tstat")),
                    "hac_pvalue": _number(hac.get("raw_pvalue"), 1.0),
                    "bootstrap_pvalue": _number(bootstrap.get("pvalue"), 1.0),
                    "holm_pvalue": _number(hac.get("holm_adjusted_pvalue"), 1.0),
                    "bh_qvalue": _number(hac.get("bh_qvalue"), 1.0),
                    "authority": EvidenceAuthority.AUTHORITATIVE.value,
                }
            )
        return {
            "schema_version": "finagent.workspace.factor-statistics.v2",
            "read_only": True,
            "program_id": program_id,
            "items": items,
        }

    def program_cockpit(self, program_id: str) -> dict[str, object]:
        bundle = self._program_bundle(program_id)
        raw = self._raw.get(bundle.root.evidence_id)
        if raw is None:
            raise KeyError(program_id)
        program = _mapping(raw.get("program_spec"))
        selection = _mapping(raw.get("frozen_selection"))
        walk = _mapping(raw.get("walk_forward_report"))
        gates = self.program_gates(program_id)
        statistics = self.program_statistics(program_id)
        fold_ids = sorted(
            {
                _text(_mapping(fold).get("fold_id"))
                for candidate in _sequence(walk.get("candidates"))
                for fold in _sequence(_mapping(candidate).get("folds"))
                if _text(_mapping(fold).get("fold_id"))
            }
        )
        heatmap: list[dict[str, object]] = []
        for candidate in _sequence(walk.get("candidates")):
            value = _mapping(candidate)
            for fold in _sequence(value.get("folds")):
                fold_value = _mapping(fold)
                heatmap.append(
                    {
                        "feature_id": _text(value.get("feature_id")),
                        "feature_digest": _text(value.get("feature_digest")),
                        "fold_id": _text(fold_value.get("fold_id")),
                        "train_direction": _integer(fold_value.get("train_direction")),
                        "train_rank_icir": _number(fold_value.get("train_rank_icir")),
                        "test_rank_icir": _number(fold_value.get("test_rank_icir")),
                        "test_raw_rank_icir": _number(fold_value.get("test_raw_rank_icir")),
                        "coverage": _number(fold_value.get("coverage")),
                        "turnover": _number(fold_value.get("mean_one_way_turnover")),
                        "authority": EvidenceAuthority.AUTHORITATIVE.value,
                    }
                )
        return {
            "schema_version": "finagent.workspace.program-cockpit.v2",
            "read_only": True,
            "program_id": program_id,
            "evidence_id": bundle.root.evidence_id,
            "system_status": bundle.system_status,
            "research_status": bundle.research_status,
            "reserve": self._reserve(raw, bundle.reserve_status),
            "promotion_eligible": bundle.promotion_eligible,
            "identity": {
                "program_spec_id": _text(program.get("spec_id")),
                "plan_id": _text(_mapping(program.get("walk_forward_plan")).get("plan_id")),
                "gate_report_id": _text(_mapping(raw.get("gate_report")).get("gate_report_id")),
                "selection_id": _text(selection.get("selection_id")),
                "data_version": bundle.root.data_version,
                "git_sha": bundle.root.git_sha,
                "protocol_frozen": _text(raw.get("program_status")) == "frozen",
            },
            "gate_matrix": gates,
            "statistics": statistics,
            "fold_evidence": {
                "fold_ids": fold_ids,
                "items": heatmap,
                "authority": EvidenceAuthority.AUTHORITATIVE.value,
            },
            "frozen_components": _jsonable(_sequence(selection.get("components"))),
        }

    def _protocol_snapshot(self, evidence_id: str) -> dict[str, object]:
        bundle = self.bundle(evidence_id)
        raw = self._raw.get(evidence_id)
        if raw is None:
            raise KeyError(evidence_id)
        if bundle.root.stage is EvidenceStage.A2P6_ROBUST_RESEARCH:
            program = _mapping(raw.get("program_spec"))
            selection = _mapping(raw.get("frozen_selection"))
            denominator = [
                {
                    "feature_id": _text(_mapping(item).get("feature_id")),
                    "feature_digest": _text(_mapping(item).get("feature_digest")),
                }
                for item in _sequence(raw.get("candidate_denominator"))
            ]
            return {
                "protocol_kind": "A2.6 ResearchProgram",
                "program_id": _text(program.get("program_id")),
                "program_spec_id": _text(program.get("spec_id")),
                "data_version": _text(raw.get("data_version")),
                "candidate_selection_id": _text(program.get("candidate_selection_id")),
                "universe_policy_version": _text(program.get("universe_policy_version")),
                "walk_forward_plan": _jsonable(_mapping(program.get("walk_forward_plan"))),
                "factor_denominator": denominator,
                "factor_quant_config": _jsonable(_mapping(program.get("factor_quant_config"))),
                "gate_config": _jsonable(_mapping(program.get("gate_config"))),
                "selector_config": _jsonable(_mapping(program.get("selector_config"))),
                "generation_config": _jsonable(_mapping(program.get("generation_config"))),
                "frozen_factor_family": _jsonable(_sequence(selection.get("components"))),
                "selection_id": _text(selection.get("selection_id")),
                "reserve_id": _text(program.get("reserve_id")),
            }
        if bundle.root.stage is EvidenceStage.A4_PORTFOLIO_VALIDATION:
            spec = _mapping(raw.get("validation_spec"))
            validation = _mapping(spec.get("validation_config"))
            policy = _mapping(validation.get("policy"))
            risk_keys = (
                "risk_lookback",
                "risk_min_observations",
                "risk_aversion",
                "target_cash_weight",
                "max_asset_weight",
            )
            optimizer_keys = (
                "minimum_expected_return",
                "optimizer_turnover_penalty",
                "active_asset_count",
                "min_active_assets",
                "rebalance_every",
            )
            alpha_keys = (
                "alpha_ridge",
                "alpha_min_observations",
                "winsor_lower_quantile",
                "winsor_upper_quantile",
            )
            return {
                "protocol_kind": "A4 execution-aware validation",
                "source_program_result_id": _text(spec.get("source_program_result_id")),
                "source_program_spec_id": _text(spec.get("source_program_spec_id")),
                "source_selection_id": _text(spec.get("source_selection_id")),
                "a4_spec_id": _text(spec.get("spec_id")),
                "data_version": _text(spec.get("data_version")),
                "plan_id": _text(spec.get("plan_id")),
                "selected_factor_family": {
                    "feature_digests": list(_sequence(spec.get("selected_feature_digests"))),
                    "weights": list(_sequence(spec.get("selected_weights"))),
                    "directions": list(_sequence(spec.get("selected_directions"))),
                },
                "alpha_calibration_config": {key: _jsonable(validation.get(key)) for key in alpha_keys if key in validation},
                "risk_config": {key: _jsonable(validation.get(key)) for key in risk_keys if key in validation},
                "optimizer_config": {key: _jsonable(validation.get(key)) for key in optimizer_keys if key in validation},
                "execution_config": {
                    "net": _jsonable(_mapping(spec.get("net_execution_config"))),
                    "gross": _jsonable(_mapping(spec.get("gross_execution_config"))),
                },
                "fee_schedule_id": _text(spec.get("fee_schedule_id")),
                "economic_policy": _jsonable(policy),
                "reserve_id": _text(spec.get("reserve_id")),
            }
        raise KeyError(evidence_id)

    def protocol_diff(self, left_id: str, right_id: str) -> dict[str, object]:
        left = self._protocol_snapshot(left_id)
        right = self._protocol_snapshot(right_id)
        left_flat = _flatten(left)
        right_flat = _flatten(right)
        fields = sorted(set(left_flat) | set(right_flat))
        changes = [
            {
                "field": field,
                "left": left_flat.get(field),
                "right": right_flat.get(field),
                "changed": left_flat.get(field) != right_flat.get(field),
            }
            for field in fields
        ]
        return {
            "schema_version": PROTOCOL_DIFF_SCHEMA,
            "read_only": True,
            "authority": EvidenceAuthority.DERIVED.value,
            "left_evidence_id": left_id,
            "right_evidence_id": right_id,
            "left_protocol": left,
            "right_protocol": right,
            "changed_count": sum(bool(value["changed"]) for value in changes),
            "changes": changes,
        }

    @staticmethod
    def _combine_lineage(graphs: Sequence[LineageGraph]) -> LineageGraph:
        nodes: dict[str, LineageNode] = {}
        edges: dict[tuple[str, str, str], LineageEdge] = {}
        for graph in graphs:
            for node in graph.nodes:
                existing = nodes.get(node.evidence_id)
                if existing is None:
                    nodes[node.evidence_id] = node
                    continue
                # Prefer the non-external/full projection when the same immutable ID appears.
                if existing.evidence_type != node.evidence_type:
                    raise EvidenceContractError(
                        f"lineage node {node.evidence_id!r} has conflicting evidence types"
                    )
            for edge in graph.edges:
                edges[(edge.parent_id, edge.child_id, edge.relation)] = edge
        return LineageGraph(
            nodes=tuple(nodes[key] for key in sorted(nodes)),
            edges=tuple(edges[key] for key in sorted(edges)),
        )

    def governance(self, evidence_id: str) -> dict[str, object]:
        bundle = self.bundle(evidence_id)
        graphs = [bundle.lineage()]
        source_program_id = ""
        a4_binding: dict[str, object] | None = None
        if bundle.root.stage is EvidenceStage.A4_PORTFOLIO_VALIDATION:
            raw = self._raw.get(evidence_id, {})
            spec = _mapping(raw.get("validation_spec"))
            source_program_id = _text(spec.get("source_program_result_id"))
            source_bundle = self._by_root_id.get(source_program_id)
            if source_bundle is not None:
                graphs.insert(0, source_bundle.lineage())
            a3_payload = {
                "net_execution_config": _jsonable(_mapping(spec.get("net_execution_config"))),
                "gross_execution_config": _jsonable(_mapping(spec.get("gross_execution_config"))),
                "fee_schedule_id": _text(spec.get("fee_schedule_id")),
            }
            a4_binding = {
                "binding_id": _digest("a3-protocol-binding", a3_payload, 24),
                "authority": EvidenceAuthority.DERIVED.value,
                "label": "A3 execution protocol binding inferred from immutable A4 spec",
                "payload": a3_payload,
                "note": "No standalone authoritative A3 certification evidence ID is persisted; this binding is not inserted into the lineage DAG.",
            }
        graph = self._combine_lineage(graphs)
        return {
            "schema_version": "finagent.workspace.governance.v2",
            "read_only": True,
            "evidence_id": evidence_id,
            "source_program_evidence_id": source_program_id,
            "lineage": graph.to_dict(),
            "reserve_status": bundle.reserve_status,
            "promotion_eligible": bundle.promotion_eligible,
            "protocol": self._protocol_snapshot(evidence_id),
            "a3_protocol_binding": a4_binding,
            "authority_legend": {
                "authoritative": "identity-bound FinAgent core evidence",
                "derived": "deterministic presentation/review projection",
                "diagnostic": "debug/observability evidence",
            },
        }

    @staticmethod
    def _rolling(points: Sequence[Mapping[str, Any]], annualization: float, window: int = 20) -> list[dict[str, object]]:
        returns = [_number(point.get("net_return")) for point in points]
        output: list[dict[str, object]] = []
        for index, point in enumerate(points):
            start = max(0, index - window + 1)
            values = returns[start : index + 1]
            if not values:
                continue
            curve = math.prod(1.0 + value for value in values)
            rolling_return = curve - 1.0
            if len(values) > 1:
                mean = math.fsum(values) / len(values)
                variance = math.fsum((value - mean) ** 2 for value in values) / (len(values) - 1)
                std = math.sqrt(max(variance, 0.0))
                volatility = std * math.sqrt(annualization)
                sharpe = mean / std * math.sqrt(annualization) if std > 1e-15 else 0.0
            else:
                volatility = 0.0
                sharpe = 0.0
            output.append(
                {
                    "session_date": _text(point.get("session_date")),
                    "window_periods": len(values),
                    "rolling_return": rolling_return,
                    "rolling_volatility": volatility,
                    "rolling_sharpe": sharpe,
                }
            )
        return output

    def portfolio_cockpit(self, validation_id: str) -> dict[str, object]:
        bundle = self._a4_bundle(validation_id)
        raw = self._raw.get(validation_id)
        if raw is None:
            raise KeyError(validation_id)
        aggregate = _mapping(raw.get("aggregate"))
        if not aggregate:
            return {
                "schema_version": "finagent.workspace.a4-cockpit.v2",
                "read_only": True,
                "validation_id": validation_id,
                "status": bundle.research_status,
                "reserve": self._reserve(raw, bundle.reserve_status),
                "no_portfolio": True,
            }
        net = _mapping(aggregate.get("net_metrics"))
        gross = _mapping(aggregate.get("gross_metrics"))
        points = [
            dict(_mapping(point))
            for fold in _sequence(raw.get("folds"))
            for point in _sequence(_mapping(fold).get("points"))
        ]
        annualization = _number(
            _mapping(_mapping(raw.get("validation_spec")).get("validation_config")).get("annualization"),
            252.0,
        )
        fold_metrics = [
            {
                "fold_id": _text(_mapping(fold).get("fold_id")),
                "train_range": list(_sequence(_mapping(fold).get("train_range"))),
                "test_range": list(_sequence(_mapping(fold).get("test_range"))),
                "net_metrics": _jsonable(_mapping(_mapping(fold).get("net_metrics"))),
                "gross_metrics": _jsonable(_mapping(_mapping(fold).get("gross_metrics"))),
                "fees": _number(_mapping(fold).get("total_fees")),
                "slippage": _number(_mapping(fold).get("total_slippage")),
                "one_way_turnover": _number(_mapping(fold).get("total_one_way_turnover")),
                "implementation_shortfall": _number(_mapping(fold).get("average_implementation_shortfall")),
                "ledger_digest": _text(_mapping(fold).get("ledger_digest")),
                "authority": EvidenceAuthority.AUTHORITATIVE.value,
            }
            for fold in _sequence(raw.get("folds"))
        ]
        return {
            "schema_version": "finagent.workspace.a4-cockpit.v2",
            "read_only": True,
            "validation_id": validation_id,
            "status": bundle.research_status,
            "system_status": bundle.system_status,
            "reserve": self._reserve(raw, bundle.reserve_status),
            "promotion_eligible": bundle.promotion_eligible,
            "metrics": {
                "gross_return": _number(gross.get("total_return")),
                "net_return": _number(net.get("total_return")),
                "gross_annualized_return": _number(gross.get("annualized_return")),
                "net_annualized_return": _number(net.get("annualized_return")),
                "gross_sharpe": _number(gross.get("sharpe")),
                "net_sharpe": _number(net.get("sharpe")),
                "max_drawdown": _number(net.get("max_drawdown")),
                "gross_to_net_drag": _number(aggregate.get("gross_to_net_return_drag")),
                "one_way_turnover": _number(aggregate.get("total_one_way_turnover")),
                "implementation_shortfall": _number(aggregate.get("average_implementation_shortfall")),
                "cash_fallback_ratio": _number(aggregate.get("cash_fallback_ratio")),
                "rejected_order_ratio": _number(aggregate.get("rejected_order_ratio")),
                "maximum_ex_post_participation": _number(aggregate.get("maximum_ex_post_participation")),
                "authority": EvidenceAuthority.AUTHORITATIVE.value,
            },
            "nav_series": [
                {
                    "session_date": _text(point.get("session_date")),
                    "net_nav": _number(point.get("net_nav")),
                    "gross_nav": _number(point.get("gross_nav")),
                    "net_return": _number(point.get("net_return")),
                    "gross_return": _number(point.get("gross_return")),
                    "fold_id": next(
                        (
                            _text(_mapping(fold).get("fold_id"))
                            for fold in _sequence(raw.get("folds"))
                            if point in _sequence(_mapping(fold).get("points"))
                        ),
                        "",
                    ),
                }
                for point in points
            ],
            "derived_rolling": {
                "authority": EvidenceAuthority.DERIVED.value,
                "window": 20,
                "annualization": annualization,
                "items": self._rolling(points, annualization, 20),
            },
            "folds": fold_metrics,
            "economic_evidence": {
                "positive_fold_ratio": _number(aggregate.get("positive_fold_ratio")),
                "worst_fold_net_sharpe": _number(aggregate.get("worst_fold_net_sharpe")),
                "hac_tstat": _number(aggregate.get("hac_tstat")),
                "hac_pvalue": _number(aggregate.get("hac_pvalue"), 1.0),
                "bootstrap_pvalue": _number(aggregate.get("bootstrap_pvalue"), 1.0),
                "bootstrap_ci_lower": _number(aggregate.get("bootstrap_ci_lower")),
                "bootstrap_ci_upper": _number(aggregate.get("bootstrap_ci_upper")),
                "authority": EvidenceAuthority.AUTHORITATIVE.value,
            },
        }

    @staticmethod
    def _realized_weights(state: Mapping[str, Any]) -> dict[str, float]:
        nav = _number(state.get("nav"))
        if nav <= 0:
            return {}
        positions = _mapping(state.get("positions"))
        marks = _mapping(state.get("marks"))
        output: dict[str, float] = {}
        for asset, raw_position in positions.items():
            position = _mapping(raw_position)
            quantity = _number(position.get("total_quantity"))
            mark = _number(marks.get(asset))
            if quantity > 0 and mark > 0:
                output[str(asset)] = quantity * mark / nav
        return output

    def _ledger_for_validation(self, raw: Mapping[str, Any]) -> LedgerArtifact | None:
        return self._ledgers.get(_text(raw.get("ledger_digest")))

    def execution_cockpit(self, validation_id: str) -> dict[str, object]:
        bundle = self._a4_bundle(validation_id)
        raw = self._raw.get(validation_id)
        if raw is None:
            raise KeyError(validation_id)
        aggregate = _mapping(raw.get("aggregate"))
        ledger = self._ledger_for_validation(raw)
        status_counts: Counter[str] = Counter()
        reason_counts: Counter[str] = Counter(
            {str(key): int(value) for key, value in _mapping(aggregate.get("reason_counts")).items()}
        )
        fee_totals: dict[str, float] = {}
        session_items: list[dict[str, object]] = []
        target_realized: list[dict[str, object]] = []
        if ledger is not None:
            reason_counts = Counter()
            for row in ledger.rows:
                point = _mapping(row.get("point"))
                cycle = _mapping(row.get("net_cycle"))
                compilation = _mapping(cycle.get("compilation"))
                execution = _mapping(cycle.get("execution"))
                decisions = [_mapping(value) for value in _sequence(compilation.get("decisions"))]
                fills = [_mapping(value) for value in _sequence(execution.get("fills"))]
                local_reasons: Counter[str] = Counter()
                for decision in decisions:
                    status_counts[_text(decision.get("status")) or "unknown"] += 1
                    for reason in _sequence(decision.get("reason_codes")):
                        local_reasons[str(reason)] += 1
                        reason_counts[str(reason)] += 1
                for rejection in _mapping(execution.get("rejections")).values():
                    local_reasons[str(rejection)] += 1
                    reason_counts[str(rejection)] += 1
                for fill in fills:
                    fees = _mapping(fill.get("fees"))
                    for key in (
                        "broker_commission",
                        "stamp_duty",
                        "transfer_fee",
                        "exchange_handling_fee",
                        "regulatory_fee",
                    ):
                        fee_totals[key] = fee_totals.get(key, 0.0) + _number(fees.get(key))
                    fee_totals["slippage"] = fee_totals.get("slippage", 0.0) + _number(fill.get("slippage"))
                session_items.append(
                    {
                        "fold_id": _text(row.get("fold_id")),
                        "session_date": _text(point.get("session_date")),
                        "desired": len(decisions),
                        "accepted": sum(_text(value.get("status")) == "accepted" for value in decisions),
                        "adjusted": sum(_text(value.get("status")) == "adjusted" for value in decisions),
                        "rejected": sum(_text(value.get("status")) == "rejected" for value in decisions),
                        "no_action": sum(_text(value.get("status")) == "no_action" for value in decisions),
                        "executable": len(_sequence(execution.get("orders"))),
                        "filled": len(fills),
                        "reason_counts": dict(local_reasons),
                        "implementation_shortfall": _number(point.get("implementation_shortfall")),
                        "participation": _number(point.get("maximum_ex_post_participation")),
                        "cash_fallback": bool(point.get("cash_fallback", False)),
                    }
                )
                target = _mapping(row.get("target"))
                state = _mapping(row.get("net_close_state"))
                if target:
                    target_weights = {
                        str(key): _number(value)
                        for key, value in _mapping(target.get("weights")).items()
                    }
                    realized = self._realized_weights(state)
                    assets = sorted(set(target_weights) | set(realized))
                    nav = _number(state.get("nav"))
                    cash_weight = _number(state.get("cash")) / nav if nav > 0 else 0.0
                    target_cash = _number(target.get("cash_weight"))
                    for asset in assets:
                        target_realized.append(
                            {
                                "fold_id": _text(row.get("fold_id")),
                                "session_date": _text(point.get("session_date")),
                                "asset": asset,
                                "target_weight": target_weights.get(asset, 0.0),
                                "realized_weight": realized.get(asset, 0.0),
                                "drift": realized.get(asset, 0.0) - target_weights.get(asset, 0.0),
                                "authority": EvidenceAuthority.DERIVED.value,
                            }
                        )
                    target_realized.append(
                        {
                            "fold_id": _text(row.get("fold_id")),
                            "session_date": _text(point.get("session_date")),
                            "asset": "CASH",
                            "target_weight": target_cash,
                            "realized_weight": cash_weight,
                            "drift": cash_weight - target_cash,
                            "authority": EvidenceAuthority.DERIVED.value,
                        }
                    )
        if not fee_totals:
            fee_totals["aggregate_fees"] = _number(aggregate.get("total_fees"))
            fee_totals["slippage"] = _number(aggregate.get("total_slippage"))
        categories: Counter[str] = Counter()
        for reason, count in reason_counts.items():
            categories[_reason_category(reason)] += count
        desired = _integer(aggregate.get("desired_order_count"))
        executable = _integer(aggregate.get("order_count"))
        filled = _integer(aggregate.get("fill_count"))
        compiled_adjusted: int | None = None
        if ledger is not None:
            compiled_adjusted = status_counts["accepted"] + status_counts["adjusted"]
        return {
            "schema_version": "finagent.workspace.execution-cockpit.v2",
            "read_only": True,
            "validation_id": validation_id,
            "reserve_status": bundle.reserve_status,
            "ledger": ledger.summary() if ledger is not None else {
                "digest": _text(raw.get("ledger_digest")),
                "available": False,
                "authority": EvidenceAuthority.AUTHORITATIVE.value,
            },
            "funnel": {
                "desired": desired,
                "compiled_adjusted": compiled_adjusted,
                "executable": executable,
                "filled": filled,
                "authority": EvidenceAuthority.AUTHORITATIVE.value,
                "note": (
                    "compiled/adjusted requires the immutable A4 JSONL ledger"
                    if ledger is None
                    else "counts use canonical A3 compilation and execution records"
                ),
            },
            "decision_status_counts": dict(status_counts),
            "reason_counts": dict(reason_counts),
            "reason_categories": dict(categories),
            "costs": {
                "components": dict(fee_totals),
                "gross_to_net_return_drag": _number(aggregate.get("gross_to_net_return_drag")),
                "authority": EvidenceAuthority.AUTHORITATIVE.value,
                "component_detail_available": ledger is not None,
            },
            "sessions": session_items,
            "target_vs_realized": {
                "authority": EvidenceAuthority.DERIVED.value,
                "definition": "realized close weights derived deterministically from authoritative close state; target weights are authoritative ledger inputs",
                "items": target_realized,
            },
        }

    def _source_program_for_a4(self, validation_id: str) -> EvidenceBundle | None:
        raw = self._raw.get(validation_id, {})
        source_id = _text(_mapping(raw.get("validation_spec")).get("source_program_result_id"))
        bundle = self._by_root_id.get(source_id)
        if bundle is not None and bundle.root.stage is EvidenceStage.A2P6_ROBUST_RESEARCH:
            return bundle
        return None

    def _csv_bytes(self, fieldnames: Sequence[str], rows: Sequence[Mapping[str, object]]) -> bytes:
        text = io.StringIO(newline="")
        writer = csv.DictWriter(text, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
        return text.getvalue().encode("utf-8-sig")

    def review_bundle(self, validation_id: str) -> bytes:
        a4 = self._a4_bundle(validation_id)
        a4_raw = self._raw.get(validation_id)
        if a4_raw is None:
            raise KeyError(validation_id)
        source = self._source_program_for_a4(validation_id)
        source_raw = self._raw.get(source.root.evidence_id, {}) if source else {}
        portfolio = self.portfolio_cockpit(validation_id)
        execution = self.execution_cockpit(validation_id)
        governance = self.governance(validation_id)
        diff = (
            self.protocol_diff(source.root.evidence_id, validation_id)
            if source is not None
            else {
                "schema_version": PROTOCOL_DIFF_SCHEMA,
                "read_only": True,
                "warning": "source A2.6 report is not present in configured report roots",
            }
        )
        gate_rows = (
            _sequence(self.program_gates(source.root.program_id).get("items"))
            if source
            else ()
        )
        factor_summary: list[dict[str, object]] = []
        for raw_item in gate_rows:
            item = _mapping(raw_item)
            factor_summary.append(
                {
                    "feature_id": item.get("feature_id", ""),
                    "feature_digest": item.get("feature_digest", ""),
                    "passed": item.get("passed", False),
                    "robust_score": item.get("robust_score", 0.0),
                    "reason_codes": ";".join(
                        str(value) for value in _sequence(item.get("reason_codes"))
                    ),
                }
            )
        fold_summary: list[dict[str, object]] = []
        if source:
            program = self.program_cockpit(source.root.program_id)
            for item in _sequence(_mapping(program.get("fold_evidence")).get("items")):
                value = _mapping(item)
                fold_summary.append(
                    {
                        "kind": "factor",
                        "fold_id": value.get("fold_id", ""),
                        "feature_id": value.get("feature_id", ""),
                        "test_rank_icir": value.get("test_rank_icir", ""),
                        "net_return": "",
                        "net_sharpe": "",
                        "fees": "",
                        "implementation_shortfall": "",
                    }
                )
        for fold in _sequence(portfolio.get("folds")):
            value = _mapping(fold)
            net_metrics = _mapping(value.get("net_metrics"))
            fold_summary.append(
                {
                    "kind": "portfolio",
                    "fold_id": value.get("fold_id", ""),
                    "feature_id": "",
                    "test_rank_icir": "",
                    "net_return": net_metrics.get("total_return", ""),
                    "net_sharpe": net_metrics.get("sharpe", ""),
                    "fees": value.get("fees", ""),
                    "implementation_shortfall": value.get("implementation_shortfall", ""),
                }
            )
        portfolio_rows = [
            dict(value) for value in _sequence(portfolio.get("nav_series"))
        ]
        execution_rows = [
            dict(value) for value in _sequence(execution.get("sessions"))
        ]
        raw_ledger = self._ledger_for_validation(a4_raw)
        manifest = {
            "schema_version": REVIEW_BUNDLE_SCHEMA,
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "review_only": True,
            "signed": False,
            "source_evidence_ids": [
                value
                for value in (
                    source.root.evidence_id if source else "",
                    a4.root.evidence_id,
                )
                if value
            ],
            "source_artifact_digests": [
                value
                for value in (
                    source.root.artifact_digest if source else "",
                    a4.root.artifact_digest,
                )
                if value
            ],
            "program_id": source.root.program_id if source else "",
            "selection_id": _text(_mapping(a4_raw.get("validation_spec")).get("source_selection_id")),
            "a4_spec_id": a4.root.spec_id,
            "ledger_digest": _text(a4_raw.get("ledger_digest")),
            "data_version": a4.root.data_version,
            "git_sha": a4.root.git_sha,
            "reserve_status": a4.reserve_status,
            "promotion_eligible": a4.promotion_eligible,
            "authority_boundary": "read-only evidence review; no reserve/promotion/order authority",
        }
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
            archive.writestr("lineage.json", json.dumps(governance["lineage"], indent=2, ensure_ascii=False, sort_keys=True) + "\n")
            archive.writestr("protocol_diff.json", json.dumps(diff, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
            archive.writestr(
                "factor_summary.csv",
                self._csv_bytes(
                    ("feature_id", "feature_digest", "passed", "robust_score", "reason_codes"),
                    factor_summary,
                ),
            )
            archive.writestr(
                "fold_summary.csv",
                self._csv_bytes(
                    (
                        "kind",
                        "fold_id",
                        "feature_id",
                        "test_rank_icir",
                        "net_return",
                        "net_sharpe",
                        "fees",
                        "implementation_shortfall",
                    ),
                    fold_summary,
                ),
            )
            archive.writestr(
                "portfolio_summary.csv",
                self._csv_bytes(
                    ("session_date", "fold_id", "net_nav", "gross_nav", "net_return", "gross_return"),
                    portfolio_rows,
                ),
            )
            execution_flat = [
                {
                    **row,
                    "reason_counts": _canonical_json(row.get("reason_counts", {})),
                }
                for row in execution_rows
            ]
            archive.writestr(
                "execution_summary.csv",
                self._csv_bytes(
                    (
                        "fold_id",
                        "session_date",
                        "desired",
                        "accepted",
                        "adjusted",
                        "rejected",
                        "no_action",
                        "executable",
                        "filled",
                        "implementation_shortfall",
                        "participation",
                        "cash_fallback",
                        "reason_counts",
                    ),
                    execution_flat,
                ),
            )
            if source_raw:
                archive.writestr(
                    "report_a26.json",
                    json.dumps(source_raw, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                )
            archive.writestr(
                "report_a4.json",
                json.dumps(a4_raw, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            )
            if raw_ledger is not None:
                ledger_text = "\n".join(_canonical_json(row) for row in raw_ledger.rows) + "\n"
                archive.writestr("execution_ledger.jsonl", ledger_text)
            archive.writestr(
                "figures/README.txt",
                "Figures are rendered from the included semantic evidence by the Workspace. "
                "Browser-derived charts do not replace authoritative FinAgent evidence.\n",
            )
        return memory.getvalue()

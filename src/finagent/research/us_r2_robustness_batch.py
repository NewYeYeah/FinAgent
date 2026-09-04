from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from finagent.research.us_r2_frozen_protocol import (
    FROZEN_CALENDAR_ID,
    canonical_us_r2_frozen_protocol,
)
from finagent.research.us_r2_robustness_base import (
    ROBUSTNESS_BASE_EVIDENCE_FILENAME,
    ROBUSTNESS_BASE_FILENAME,
    ROBUSTNESS_BASE_OUTPUT_COLUMNS,
    ROBUSTNESS_BASE_PLAN_FILENAME,
    ROBUSTNESS_FIRST_YEAR,
    ROBUSTNESS_LAST_YEAR,
    canonical_us_r2_robustness_materialization_policy,
    canonical_us_r2_robustness_slices,
)

ROBUSTNESS_BATCH_EVIDENCE_FILENAME = "us_r2_robustness_base_batch_evidence.json"


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return cast(Mapping[str, object], value)


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise TypeError(f"{field_name} must be integer")


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _read_mapping(path: Path) -> Mapping[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(value, str(path))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_us_r2_robustness_years() -> tuple[int, ...]:
    return tuple(range(ROBUSTNESS_FIRST_YEAR, ROBUSTNESS_LAST_YEAR + 1))


def normalize_us_r2_robustness_years(years: Sequence[int]) -> tuple[int, ...]:
    allowed = set(canonical_us_r2_robustness_years())
    normalized: set[int] = set()
    for year in years:
        if isinstance(year, bool) or not isinstance(year, int):
            raise TypeError("US-R2 robustness years must be integers")
        if year not in allowed:
            raise ValueError(f"US-R2 robustness year outside 2006-2026: {year}")
        normalized.add(year)
    if not normalized:
        raise ValueError("US-R2 robustness batch requires at least one year")
    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True)
class USR2AnnualRobustnessPaths:
    year: int
    data_path: Path
    plan_path: Path
    evidence_path: Path


def us_r2_annual_robustness_paths(
    *,
    year: int,
    data_root: Path,
    report_root: Path,
) -> USR2AnnualRobustnessPaths:
    normalize_us_r2_robustness_years((year,))
    return USR2AnnualRobustnessPaths(
        year=year,
        data_path=data_root / f"year={year:04d}" / ROBUSTNESS_BASE_FILENAME,
        plan_path=report_root / f"year_{year:04d}" / ROBUSTNESS_BASE_PLAN_FILENAME,
        evidence_path=report_root / f"year_{year:04d}" / ROBUSTNESS_BASE_EVIDENCE_FILENAME,
    )


def _recompute_plan_id(plan: Mapping[str, object]) -> str:
    payload = {
        "schema_version": _text(plan.get("schema_version"), "plan.schema_version"),
        "policy_id": _text(plan.get("policy_id"), "plan.policy_id"),
        "frozen_protocol_id": _text(plan.get("frozen_protocol_id"), "plan.frozen_protocol_id"),
        "year": _integer(plan.get("year"), "plan.year"),
        "source_plan_id": _text(plan.get("source_plan_id"), "plan.source_plan_id"),
        "sessionization_evidence_id": _text(
            plan.get("sessionization_evidence_id"), "plan.sessionization_evidence_id"
        ),
        "calendar_id": _text(plan.get("calendar_id"), "plan.calendar_id"),
        "source_data_version": _text(plan.get("source_data_version"), "plan.source_data_version"),
        "data_version": _text(plan.get("data_version"), "plan.data_version"),
        "partition_months": list(_sequence(plan.get("partition_months"), "plan.partition_months")),
        "output_columns": list(_sequence(plan.get("output_columns"), "plan.output_columns")),
        "source_execution_strategy": "one_materialized_sessionized_1m_cte_per_year",
    }
    return _canonical_hash(payload, prefix="us-r2-robustness-base-plan")


def _recompute_evidence_id(evidence: Mapping[str, object]) -> str:
    payload = dict(evidence)
    claimed = _text(payload.pop("evidence_id", None), "evidence.evidence_id")
    expected = _canonical_hash(payload, prefix="us-r2-robustness-base")
    if claimed != expected:
        raise ValueError("US-R2 robustness annual evidence content-addressed ID mismatch")
    return claimed


def _recompute_materialization_id(
    *,
    plan_id: str,
    data_version: str,
    row_count: int,
    content_sha256: str,
) -> str:
    return _canonical_hash(
        {
            "schema_version": "finagent.minute-materialization.v2",
            "plan_id": plan_id,
            "data_version": data_version,
            "row_count": row_count,
            "content_sha256": content_sha256,
        },
        prefix="minute-materialization",
    )


@dataclass(frozen=True, slots=True)
class USR2CompletedAnnualRobustnessBase:
    year: int
    plan_id: str
    evidence_id: str
    materialization_id: str
    data_version: str
    row_count: int
    slice_ids: tuple[str, ...]
    content_sha256: str
    data_size_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "year": self.year,
            "plan_id": self.plan_id,
            "evidence_id": self.evidence_id,
            "materialization_id": self.materialization_id,
            "data_version": self.data_version,
            "row_count": self.row_count,
            "slice_ids": list(self.slice_ids),
            "content_sha256": self.content_sha256,
            "data_size_bytes": self.data_size_bytes,
        }


def inspect_completed_us_r2_annual_robustness_base(
    paths: USR2AnnualRobustnessPaths,
) -> USR2CompletedAnnualRobustnessBase | None:
    existence = (
        paths.data_path.is_file(),
        paths.plan_path.is_file(),
        paths.evidence_path.is_file(),
    )
    if existence == (False, False, False):
        return None
    if existence != (True, True, True):
        raise ValueError(
            f"US-R2 robustness annual triplet is partial for {paths.year}: "
            f"data={existence[0]} plan={existence[1]} evidence={existence[2]}"
        )
    if paths.data_path.stat().st_size <= 0:
        raise ValueError(f"US-R2 robustness annual Parquet is empty for {paths.year}")

    plan = _read_mapping(paths.plan_path)
    evidence = _read_mapping(paths.evidence_path)
    policy = canonical_us_r2_robustness_materialization_policy()
    frozen = canonical_us_r2_frozen_protocol()
    if _text(plan.get("schema_version"), "plan.schema_version") != (
        "finagent.us-r2-annual-robustness-base-plan.v1"
    ):
        raise ValueError(f"US-R2 robustness annual plan schema mismatch for {paths.year}")
    if _integer(plan.get("year"), "plan.year") != paths.year:
        raise ValueError(f"US-R2 robustness annual plan year mismatch for {paths.year}")
    if _text(plan.get("policy_id"), "plan.policy_id") != policy.policy_id:
        raise ValueError(f"US-R2 robustness annual policy mismatch for {paths.year}")
    if _text(plan.get("frozen_protocol_id"), "plan.frozen_protocol_id") != frozen.freeze_id:
        raise ValueError(f"US-R2 robustness annual frozen protocol mismatch for {paths.year}")
    if _text(plan.get("calendar_id"), "plan.calendar_id") != FROZEN_CALENDAR_ID:
        raise ValueError(f"US-R2 robustness annual calendar mismatch for {paths.year}")
    if tuple(_text(item, "plan.output_columns[]") for item in _sequence(
        plan.get("output_columns"), "plan.output_columns"
    )) != ROBUSTNESS_BASE_OUTPUT_COLUMNS:
        raise ValueError(f"US-R2 robustness annual output schema mismatch for {paths.year}")
    if _integer(plan.get("source_scan_relation_count"), "source_scan_relation_count") != 1:
        raise ValueError(f"US-R2 robustness source-scan count mismatch for {paths.year}")
    for field_name in (
        "candidate_dependent_scan",
        "candidate_performance_read",
        "candidate_selection_applied",
        "alpha_gate_evaluated",
        "terminal_authority",
        "stage_exit_authority",
        "alpha_authority",
        "execution_authority",
    ):
        if _boolean(plan.get(field_name), f"plan.{field_name}"):
            raise ValueError(f"US-R2 robustness annual plan unexpectedly enables {field_name}")
    plan_id = _text(plan.get("plan_id"), "plan.plan_id")
    if plan_id != _recompute_plan_id(plan):
        raise ValueError(f"US-R2 robustness annual plan ID mismatch for {paths.year}")

    if _text(evidence.get("schema_version"), "evidence.schema_version") != (
        "finagent.us-r2-annual-robustness-base-evidence.v1"
    ):
        raise ValueError(f"US-R2 robustness annual evidence schema mismatch for {paths.year}")
    if _integer(evidence.get("year"), "evidence.year") != paths.year:
        raise ValueError(f"US-R2 robustness annual evidence year mismatch for {paths.year}")
    if _text(evidence.get("plan_id"), "evidence.plan_id") != plan_id:
        raise ValueError(f"US-R2 robustness annual evidence/plan mismatch for {paths.year}")
    if _text(evidence.get("policy_id"), "evidence.policy_id") != policy.policy_id:
        raise ValueError(f"US-R2 robustness annual evidence/policy mismatch for {paths.year}")
    if evidence.get("passed") is not True or evidence.get("blockers") != []:
        raise ValueError(f"US-R2 robustness annual evidence is blocked for {paths.year}")
    for field_name in (
        "candidate_dependent_scan",
        "candidate_performance_read",
        "candidate_selection_applied",
        "alpha_gate_evaluated",
        "terminal_authority",
        "stage_exit_authority",
        "alpha_authority",
        "execution_authority",
    ):
        if _boolean(evidence.get(field_name), f"evidence.{field_name}"):
            raise ValueError(f"US-R2 robustness annual evidence unexpectedly enables {field_name}")
    evidence_id = _recompute_evidence_id(evidence)
    rows = _integer(evidence.get("row_count"), "evidence.row_count")
    raw_slices = _sequence(evidence.get("slices"), "evidence.slices")
    slice_ids = tuple(sorted(
        _text(_mapping(item, "evidence.slices[]").get("slice_id"), "slice_id")
        for item in raw_slices
    ))
    expected_slices = tuple(sorted(item.slice_id for item in canonical_us_r2_robustness_slices()))
    if slice_ids != expected_slices:
        raise ValueError(f"US-R2 robustness annual slice denominator mismatch for {paths.year}")

    content_sha256 = _sha256_file(paths.data_path)
    materialization_id = _recompute_materialization_id(
        plan_id=plan_id,
        data_version=_text(plan.get("data_version"), "plan.data_version"),
        row_count=rows,
        content_sha256=content_sha256,
    )
    if materialization_id != _text(
        evidence.get("materialization_id"), "evidence.materialization_id"
    ):
        raise ValueError(f"US-R2 robustness annual Parquet identity mismatch for {paths.year}")
    return USR2CompletedAnnualRobustnessBase(
        year=paths.year,
        plan_id=plan_id,
        evidence_id=evidence_id,
        materialization_id=materialization_id,
        data_version=_text(plan.get("data_version"), "plan.data_version"),
        row_count=rows,
        slice_ids=slice_ids,
        content_sha256=content_sha256,
        data_size_bytes=paths.data_path.stat().st_size,
    )


@dataclass(frozen=True, slots=True)
class USR2RobustnessBaseBatchEvidence:
    policy_id: str
    requested_years: tuple[int, ...]
    annual_evidence_ids: tuple[str, ...]
    annual_materialization_ids: tuple[str, ...]
    total_row_count: int
    schema_version: str = "finagent.us-r2-robustness-base-batch-evidence.v1"

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-robustness-base-batch")

    @property
    def passed(self) -> bool:
        return (
            self.requested_years == canonical_us_r2_robustness_years()
            and len(self.annual_evidence_ids) == len(self.requested_years)
            and len(self.annual_materialization_ids) == len(self.requested_years)
            and self.total_row_count > 0
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "requested_years": list(self.requested_years),
            "annual_evidence_ids": list(self.annual_evidence_ids),
            "annual_materialization_ids": list(self.annual_materialization_ids),
            "total_row_count": self.total_row_count,
            "candidate_count": 37,
            "slice_ids": [item.slice_id for item in canonical_us_r2_robustness_slices()],
            "source_execution_strategy": "one_materialized_sessionized_1m_cte_per_missing_year",
            "candidate_dependent_scan": False,
            "candidate_performance_read": False,
            "candidate_selection_applied": False,
            "alpha_gate_evaluated": False,
            "terminal_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "passed": self.passed,
            "blockers": [] if self.passed else ["robustness_base_batch_incomplete"],
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


def materialize_us_r2_robustness_batch(
    *,
    years: Sequence[int],
    data_root: Path,
    report_root: Path,
    materialize_year: Callable[[int], None],
) -> tuple[
    USR2RobustnessBaseBatchEvidence,
    tuple[int, ...],
    tuple[int, ...],
]:
    normalized = normalize_us_r2_robustness_years(years)
    completed: list[USR2CompletedAnnualRobustnessBase] = []
    preexisting: list[int] = []
    materialized: list[int] = []
    for year in normalized:
        paths = us_r2_annual_robustness_paths(
            year=year,
            data_root=data_root,
            report_root=report_root,
        )
        existing = inspect_completed_us_r2_annual_robustness_base(paths)
        if existing is None:
            materialize_year(year)
            materialized.append(year)
            existing = inspect_completed_us_r2_annual_robustness_base(paths)
            if existing is None:
                raise ValueError(f"US-R2 robustness materializer produced no triplet for {year}")
        else:
            preexisting.append(year)
        completed.append(existing)
    evidence = USR2RobustnessBaseBatchEvidence(
        policy_id=canonical_us_r2_robustness_materialization_policy().policy_id,
        requested_years=normalized,
        annual_evidence_ids=tuple(item.evidence_id for item in completed),
        annual_materialization_ids=tuple(item.materialization_id for item in completed),
        total_row_count=sum(item.row_count for item in completed),
    )
    return evidence, tuple(preexisting), tuple(materialized)

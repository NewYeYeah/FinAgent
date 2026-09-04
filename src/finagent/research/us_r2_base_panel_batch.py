from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from finagent.research.us_r2_base_panel import FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID
from finagent.research.us_r2_frozen_protocol import (
    FROZEN_ASSETS,
    FROZEN_CALENDAR_ID,
    FROZEN_FIRST_RESEARCH_YEAR,
    FROZEN_LAST_RESEARCH_YEAR,
    canonical_us_r2_frozen_protocol,
)

ANNUAL_DATA_FILENAME = "us_r2_15m60m_base.parquet"
ANNUAL_PLAN_FILENAME = "us_r2_base_panel_plan.json"
ANNUAL_EVIDENCE_FILENAME = "us_r2_base_panel_evidence.json"


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


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise TypeError(f"{field_name} must be an integer")


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list")
    rendered = [_text(item, f"{field_name}[{index}]") for index, item in enumerate(value)]
    return rendered


def _read_mapping(path: Path) -> Mapping[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(value, str(path))


def canonical_us_r2_base_panel_years() -> tuple[int, ...]:
    return tuple(range(FROZEN_FIRST_RESEARCH_YEAR, FROZEN_LAST_RESEARCH_YEAR + 1))


def normalize_us_r2_base_panel_years(years: Sequence[int]) -> tuple[int, ...]:
    canonical = set(canonical_us_r2_base_panel_years())
    normalized: set[int] = set()
    for raw in years:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise TypeError("US-R2 base-panel years must be integers")
        if raw not in canonical:
            raise ValueError(f"US-R2 base-panel year outside frozen range: {raw}")
        normalized.add(raw)
    if not normalized:
        raise ValueError("US-R2 base-panel batch requires at least one year")
    return tuple(sorted(normalized))


@dataclass(frozen=True, slots=True)
class USR2AnnualBasePanelPaths:
    year: int
    data_path: Path
    plan_path: Path
    evidence_path: Path


def us_r2_annual_base_panel_paths(
    *,
    year: int,
    data_root: Path,
    report_root: Path,
) -> USR2AnnualBasePanelPaths:
    normalize_us_r2_base_panel_years((year,))
    return USR2AnnualBasePanelPaths(
        year=year,
        data_path=data_root / f"year={year:04d}" / ANNUAL_DATA_FILENAME,
        plan_path=report_root / f"year_{year:04d}" / ANNUAL_PLAN_FILENAME,
        evidence_path=report_root / f"year_{year:04d}" / ANNUAL_EVIDENCE_FILENAME,
    )


def recompute_us_r2_annual_base_panel_plan_id(document: Mapping[str, object]) -> str:
    payload = {
        "schema_version": _text(document.get("schema_version"), "plan.schema_version"),
        "frozen_protocol_id": _text(document.get("frozen_protocol_id"), "plan.frozen_protocol_id"),
        "regime_projection_evidence_id": _text(
            document.get("regime_projection_evidence_id"),
            "plan.regime_projection_evidence_id",
        ),
        "year": _integer(document.get("year"), "plan.year"),
        "source_plan_id": _text(document.get("source_plan_id"), "plan.source_plan_id"),
        "sessionization_evidence_id": _text(
            document.get("sessionization_evidence_id"),
            "plan.sessionization_evidence_id",
        ),
        "calendar_id": _text(document.get("calendar_id"), "plan.calendar_id"),
        "source_data_version": _text(
            document.get("source_data_version"),
            "plan.source_data_version",
        ),
        "data_version": _text(document.get("data_version"), "plan.data_version"),
        "partition_months": _string_list(document.get("partition_months"), "plan.partition_months"),
        "output_columns": _string_list(document.get("output_columns"), "plan.output_columns"),
        "source_execution_strategy": "single_materialized_source_cte_for_bars_and_labels",
    }
    return _canonical_hash(payload, prefix="us-r2-base-panel-plan")


def recompute_us_r2_annual_base_panel_evidence_id(document: Mapping[str, object]) -> str:
    payload = {
        "schema_version": _text(document.get("schema_version"), "evidence.schema_version"),
        "plan_id": _text(document.get("plan_id"), "evidence.plan_id"),
        "regime_projection_evidence_id": _text(
            document.get("regime_projection_evidence_id"),
            "evidence.regime_projection_evidence_id",
        ),
        "year": _integer(document.get("year"), "evidence.year"),
        "materialization_id": _text(
            document.get("materialization_id"),
            "evidence.materialization_id",
        ),
        "row_count": _integer(document.get("row_count"), "evidence.row_count"),
        "asset_count": _integer(document.get("asset_count"), "evidence.asset_count"),
        "complete_bar_count": _integer(
            document.get("complete_bar_count"),
            "evidence.complete_bar_count",
        ),
        "label_available_count": _integer(
            document.get("label_available_count"),
            "evidence.label_available_count",
        ),
        "joint_available_count": _integer(
            document.get("joint_available_count"),
            "evidence.joint_available_count",
        ),
        "formation_count": _integer(document.get("formation_count"), "evidence.formation_count"),
        "formation_count_at_minimum_cross_section": _integer(
            document.get("formation_count_at_minimum_cross_section"),
            "evidence.formation_count_at_minimum_cross_section",
        ),
        "minimum_joint_breadth": _integer(
            document.get("minimum_joint_breadth"),
            "evidence.minimum_joint_breadth",
        ),
        "maximum_joint_breadth": _integer(
            document.get("maximum_joint_breadth"),
            "evidence.maximum_joint_breadth",
        ),
        "first_session_date": document.get("first_session_date"),
        "last_session_date": document.get("last_session_date"),
        "blockers": document.get("blockers"),
        "passed": document.get("passed"),
        "candidate_dependent_scan": document.get("candidate_dependent_scan"),
        "candidate_performance_read": document.get("candidate_performance_read"),
        "stage_exit_authority": document.get("stage_exit_authority"),
        "alpha_authority": document.get("alpha_authority"),
        "execution_authority": document.get("execution_authority"),
        "order_authority": document.get("order_authority"),
    }
    return _canonical_hash(payload, prefix="us-r2-base-panel")


@dataclass(frozen=True, slots=True)
class USR2CompletedAnnualBasePanel:
    year: int
    plan_id: str
    evidence_id: str
    materialization_id: str
    data_version: str
    row_count: int
    asset_count: int
    formation_count: int
    formation_count_at_minimum_cross_section: int
    minimum_joint_breadth: int
    maximum_joint_breadth: int
    data_size_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "year": self.year,
            "plan_id": self.plan_id,
            "evidence_id": self.evidence_id,
            "materialization_id": self.materialization_id,
            "data_version": self.data_version,
            "row_count": self.row_count,
            "asset_count": self.asset_count,
            "formation_count": self.formation_count,
            "formation_count_at_minimum_cross_section": self.formation_count_at_minimum_cross_section,
            "minimum_joint_breadth": self.minimum_joint_breadth,
            "maximum_joint_breadth": self.maximum_joint_breadth,
            "data_size_bytes": self.data_size_bytes,
        }


def inspect_completed_us_r2_annual_base_panel(
    paths: USR2AnnualBasePanelPaths,
) -> USR2CompletedAnnualBasePanel | None:
    existence = (
        paths.data_path.is_file(),
        paths.plan_path.is_file(),
        paths.evidence_path.is_file(),
    )
    if existence == (False, False, False):
        return None
    if existence != (True, True, True):
        raise ValueError(
            f"US-R2 annual base-panel triplet is partial for {paths.year}: "
            f"data={existence[0]} plan={existence[1]} evidence={existence[2]}"
        )
    data_size_bytes = paths.data_path.stat().st_size
    if data_size_bytes <= 0:
        raise ValueError(f"US-R2 annual base-panel Parquet is empty for {paths.year}")

    plan = _read_mapping(paths.plan_path)
    evidence = _read_mapping(paths.evidence_path)
    expected_freeze = canonical_us_r2_frozen_protocol().freeze_id
    if _text(plan.get("schema_version"), "plan.schema_version") != (
        "finagent.us-r2-annual-base-panel-plan.v1"
    ):
        raise ValueError(f"US-R2 annual plan schema mismatch for {paths.year}")
    if _integer(plan.get("year"), "plan.year") != paths.year:
        raise ValueError(f"US-R2 annual plan year mismatch for {paths.year}")
    if _text(plan.get("frozen_protocol_id"), "plan.frozen_protocol_id") != expected_freeze:
        raise ValueError(f"US-R2 annual plan frozen protocol mismatch for {paths.year}")
    if _text(plan.get("calendar_id"), "plan.calendar_id") != FROZEN_CALENDAR_ID:
        raise ValueError(f"US-R2 annual plan calendar mismatch for {paths.year}")
    if _text(plan.get("regime_projection_evidence_id"), "plan.regime_projection_evidence_id") != (
        FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID
    ):
        raise ValueError(f"US-R2 annual plan regime evidence mismatch for {paths.year}")
    plan_id = _text(plan.get("plan_id"), "plan.plan_id")
    if plan_id != recompute_us_r2_annual_base_panel_plan_id(plan):
        raise ValueError(f"US-R2 annual plan content-addressed ID mismatch for {paths.year}")
    if _integer(plan.get("source_scan_relation_count"), "plan.source_scan_relation_count") != 1:
        raise ValueError(f"US-R2 annual plan source-scan count mismatch for {paths.year}")
    if _boolean(plan.get("candidate_dependent_scan"), "plan.candidate_dependent_scan"):
        raise ValueError(f"US-R2 annual plan became candidate dependent for {paths.year}")
    if _boolean(plan.get("candidate_performance_read"), "plan.candidate_performance_read"):
        raise ValueError(f"US-R2 annual plan read candidate performance for {paths.year}")

    if _text(evidence.get("schema_version"), "evidence.schema_version") != (
        "finagent.us-r2-annual-base-panel-evidence.v1"
    ):
        raise ValueError(f"US-R2 annual evidence schema mismatch for {paths.year}")
    if _integer(evidence.get("year"), "evidence.year") != paths.year:
        raise ValueError(f"US-R2 annual evidence year mismatch for {paths.year}")
    if _text(evidence.get("plan_id"), "evidence.plan_id") != plan_id:
        raise ValueError(f"US-R2 annual evidence/plan identity mismatch for {paths.year}")
    if _text(
        evidence.get("regime_projection_evidence_id"),
        "evidence.regime_projection_evidence_id",
    ) != FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID:
        raise ValueError(f"US-R2 annual evidence regime identity mismatch for {paths.year}")
    blockers = evidence.get("blockers")
    if blockers != [] or evidence.get("passed") is not True:
        raise ValueError(f"US-R2 annual evidence is not passed/blocker-free for {paths.year}")
    for field_name in (
        "candidate_dependent_scan",
        "candidate_performance_read",
        "stage_exit_authority",
        "alpha_authority",
        "execution_authority",
        "order_authority",
    ):
        if _boolean(evidence.get(field_name), f"evidence.{field_name}"):
            raise ValueError(f"US-R2 annual evidence unexpectedly grants {field_name} for {paths.year}")
    evidence_id = _text(evidence.get("evidence_id"), "evidence.evidence_id")
    if evidence_id != recompute_us_r2_annual_base_panel_evidence_id(evidence):
        raise ValueError(f"US-R2 annual evidence content-addressed ID mismatch for {paths.year}")

    row_count = _integer(evidence.get("row_count"), "evidence.row_count")
    asset_count = _integer(evidence.get("asset_count"), "evidence.asset_count")
    formation_count = _integer(evidence.get("formation_count"), "evidence.formation_count")
    formation_at_minimum = _integer(
        evidence.get("formation_count_at_minimum_cross_section"),
        "evidence.formation_count_at_minimum_cross_section",
    )
    minimum_joint_breadth = _integer(
        evidence.get("minimum_joint_breadth"),
        "evidence.minimum_joint_breadth",
    )
    maximum_joint_breadth = _integer(
        evidence.get("maximum_joint_breadth"),
        "evidence.maximum_joint_breadth",
    )
    if row_count <= 0 or formation_count <= 0 or formation_at_minimum <= 0:
        raise ValueError(f"US-R2 annual evidence lacks admitted formations for {paths.year}")
    if not 1 <= asset_count <= len(FROZEN_ASSETS):
        raise ValueError(f"US-R2 annual evidence asset count is invalid for {paths.year}")
    minimum_cross_section = canonical_us_r2_frozen_protocol().cross_section_policy.minimum_cross_section
    if maximum_joint_breadth < minimum_cross_section:
        raise ValueError(f"US-R2 annual evidence never reaches frozen breadth for {paths.year}")

    return USR2CompletedAnnualBasePanel(
        year=paths.year,
        plan_id=plan_id,
        evidence_id=evidence_id,
        materialization_id=_text(
            evidence.get("materialization_id"),
            "evidence.materialization_id",
        ),
        data_version=_text(plan.get("data_version"), "plan.data_version"),
        row_count=row_count,
        asset_count=asset_count,
        formation_count=formation_count,
        formation_count_at_minimum_cross_section=formation_at_minimum,
        minimum_joint_breadth=minimum_joint_breadth,
        maximum_joint_breadth=maximum_joint_breadth,
        data_size_bytes=data_size_bytes,
    )


@dataclass(frozen=True, slots=True)
class USR2BasePanelBatchEvidence:
    requested_years: tuple[int, ...]
    annual_panels: tuple[USR2CompletedAnnualBasePanel, ...]
    blockers: tuple[str, ...] = ()
    schema_version: str = "finagent.us-r2-base-panel-batch-evidence.v1"

    @property
    def passed(self) -> bool:
        return not self.blockers and tuple(item.year for item in self.annual_panels) == self.requested_years

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-base-panel-batch")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "requested_years": list(self.requested_years),
            "completed_years": [item.year for item in self.annual_panels],
            "annual_panels": [item.to_dict() for item in self.annual_panels],
            "blockers": list(self.blockers),
            "passed": self.passed,
            "regime_projection_evidence_id": FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID,
            "candidate_dependent_scan": False,
            "candidate_performance_read": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "order_authority": False,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


@dataclass(frozen=True, slots=True)
class USR2BasePanelBatchRun:
    evidence: USR2BasePanelBatchEvidence
    preexisting_years: tuple[int, ...]
    materialized_years: tuple[int, ...]

    @property
    def raw_source_invocation_count(self) -> int:
        return len(self.materialized_years)

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence.evidence_id,
            "passed": self.evidence.passed,
            "requested_years": list(self.evidence.requested_years),
            "preexisting_years": list(self.preexisting_years),
            "materialized_years": list(self.materialized_years),
            "raw_source_invocation_count": self.raw_source_invocation_count,
            "candidate_dependent_scan": False,
            "candidate_performance_read": False,
        }


def orchestrate_us_r2_base_panel_batch(
    *,
    years: Sequence[int],
    data_root: Path,
    report_root: Path,
    materialize_year: Callable[[int], None],
) -> USR2BasePanelBatchRun:
    requested = normalize_us_r2_base_panel_years(years)
    preexisting: list[int] = []
    materialized: list[int] = []
    completed: list[USR2CompletedAnnualBasePanel] = []

    for year in requested:
        paths = us_r2_annual_base_panel_paths(
            year=year,
            data_root=data_root,
            report_root=report_root,
        )
        record = inspect_completed_us_r2_annual_base_panel(paths)
        if record is None:
            materialize_year(year)
            materialized.append(year)
            record = inspect_completed_us_r2_annual_base_panel(paths)
            if record is None:
                raise RuntimeError(f"US-R2 annual materializer produced no output triplet for {year}")
        else:
            preexisting.append(year)
        completed.append(record)

    evidence = USR2BasePanelBatchEvidence(
        requested_years=requested,
        annual_panels=tuple(completed),
    )
    if not evidence.passed:
        raise RuntimeError("US-R2 base-panel batch evidence did not cover all requested years")
    return USR2BasePanelBatchRun(
        evidence=evidence,
        preexisting_years=tuple(preexisting),
        materialized_years=tuple(materialized),
    )

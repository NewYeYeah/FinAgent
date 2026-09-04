from __future__ import annotations

import json
from pathlib import Path

import pytest

from finagent.research.us_r2_base_panel import FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID
from finagent.research.us_r2_base_panel_batch import (
    USR2AnnualBasePanelPaths,
    inspect_completed_us_r2_annual_base_panel,
    normalize_us_r2_base_panel_years,
    orchestrate_us_r2_base_panel_batch,
    recompute_us_r2_annual_base_panel_evidence_id,
    recompute_us_r2_annual_base_panel_plan_id,
    us_r2_annual_base_panel_paths,
)
from finagent.research.us_r2_frozen_protocol import (
    FROZEN_CALENDAR_ID,
    canonical_us_r2_frozen_protocol,
)


def _write_json(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _valid_plan(year: int) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "finagent.us-r2-annual-base-panel-plan.v1",
        "frozen_protocol_id": canonical_us_r2_frozen_protocol().freeze_id,
        "regime_projection_evidence_id": FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID,
        "year": year,
        "source_plan_id": f"synthetic-source-plan-{year}",
        "sessionization_evidence_id": f"synthetic-sessionization-{year}",
        "calendar_id": FROZEN_CALENDAR_ID,
        "source_data_version": f"synthetic-source-data-{year}",
        "data_version": f"synthetic-base-data-{year}",
        "partition_months": [f"{year:04d}-01"],
        "selected_size_bytes": 1234,
        "bar_interval": "15m",
        "label_spec_id": "synthetic-label",
        "formation_policy_id": "synthetic-formation",
        "source_scan_relation_count": 1,
        "source_cte_materialized": True,
        "candidate_dependent_scan": False,
        "candidate_performance_read": False,
        "output_columns": ["research_asset_id", "available_at", "label_value"],
        "alpha_authority": False,
        "execution_authority": False,
    }
    document["plan_id"] = recompute_us_r2_annual_base_panel_plan_id(document)
    return document


def _valid_evidence(year: int, plan_id: str) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "finagent.us-r2-annual-base-panel-evidence.v1",
        "plan_id": plan_id,
        "regime_projection_evidence_id": FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID,
        "year": year,
        "materialization_id": f"synthetic-materialization-{year}",
        "row_count": 1000 + year,
        "asset_count": 25,
        "complete_bar_count": 900,
        "label_available_count": 850,
        "joint_available_count": 800,
        "formation_count": 50,
        "formation_count_at_minimum_cross_section": 40,
        "minimum_joint_breadth": 8,
        "maximum_joint_breadth": 25,
        "first_session_date": f"{year:04d}-01-02",
        "last_session_date": f"{year:04d}-12-30",
        "blockers": [],
        "passed": True,
        "candidate_dependent_scan": False,
        "candidate_performance_read": False,
        "stage_exit_authority": False,
        "alpha_authority": False,
        "execution_authority": False,
        "order_authority": False,
    }
    document["evidence_id"] = recompute_us_r2_annual_base_panel_evidence_id(document)
    return document


def _write_valid_triplet(
    *,
    data_root: Path,
    report_root: Path,
    year: int,
) -> USR2AnnualBasePanelPaths:
    paths = us_r2_annual_base_panel_paths(year=year, data_root=data_root, report_root=report_root)
    paths.data_path.parent.mkdir(parents=True, exist_ok=True)
    paths.data_path.write_bytes(b"PAR1synthetic-r2-base-panel")
    plan = _valid_plan(year)
    evidence = _valid_evidence(year, str(plan["plan_id"]))
    _write_json(paths.plan_path, plan)
    _write_json(paths.evidence_path, evidence)
    return paths


def test_valid_existing_year_is_verified_without_materializer_invocation(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    report_root = tmp_path / "reports"
    _write_valid_triplet(data_root=data_root, report_root=report_root, year=2001)
    calls: list[int] = []

    run = orchestrate_us_r2_base_panel_batch(
        years=(2001,),
        data_root=data_root,
        report_root=report_root,
        materialize_year=calls.append,
    )

    assert calls == []
    assert run.preexisting_years == (2001,)
    assert run.materialized_years == ()
    assert run.raw_source_invocation_count == 0
    assert run.evidence.passed is True


def test_missing_year_invokes_materializer_once_then_verifies_triplet(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    report_root = tmp_path / "reports"
    calls: list[int] = []

    def materialize(year: int) -> None:
        calls.append(year)
        _write_valid_triplet(data_root=data_root, report_root=report_root, year=year)

    run = orchestrate_us_r2_base_panel_batch(
        years=(2006,),
        data_root=data_root,
        report_root=report_root,
        materialize_year=materialize,
    )

    assert calls == [2006]
    assert run.preexisting_years == ()
    assert run.materialized_years == (2006,)
    assert run.raw_source_invocation_count == 1
    assert run.evidence.passed is True


def test_partial_triplet_fails_closed_without_materializing(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    report_root = tmp_path / "reports"
    paths = us_r2_annual_base_panel_paths(year=2022, data_root=data_root, report_root=report_root)
    paths.data_path.parent.mkdir(parents=True, exist_ok=True)
    paths.data_path.write_bytes(b"PAR1partial")
    calls: list[int] = []

    with pytest.raises(ValueError, match="triplet is partial"):
        orchestrate_us_r2_base_panel_batch(
            years=(2022,),
            data_root=data_root,
            report_root=report_root,
            materialize_year=calls.append,
        )

    assert calls == []


def test_tampered_content_addressed_plan_id_fails_closed(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    report_root = tmp_path / "reports"
    paths = _write_valid_triplet(data_root=data_root, report_root=report_root, year=2026)
    plan = json.loads(paths.plan_path.read_text(encoding="utf-8"))
    assert isinstance(plan, dict)
    plan["source_plan_id"] = "tampered-source-plan"
    _write_json(paths.plan_path, plan)

    with pytest.raises(ValueError, match="plan content-addressed ID mismatch"):
        inspect_completed_us_r2_annual_base_panel(paths)


def test_failed_evidence_fails_closed_even_with_rehashed_document(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    report_root = tmp_path / "reports"
    paths = _write_valid_triplet(data_root=data_root, report_root=report_root, year=2006)
    evidence = json.loads(paths.evidence_path.read_text(encoding="utf-8"))
    assert isinstance(evidence, dict)
    evidence["passed"] = False
    evidence["blockers"] = ["synthetic_blocker"]
    evidence["evidence_id"] = recompute_us_r2_annual_base_panel_evidence_id(evidence)
    _write_json(paths.evidence_path, evidence)

    with pytest.raises(ValueError, match="not passed/blocker-free"):
        inspect_completed_us_r2_annual_base_panel(paths)


def test_batch_identity_is_independent_of_requested_year_order_and_replay_route(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    report_root = tmp_path / "reports"
    _write_valid_triplet(data_root=data_root, report_root=report_root, year=2001)
    _write_valid_triplet(data_root=data_root, report_root=report_root, year=2006)

    first = orchestrate_us_r2_base_panel_batch(
        years=(2006, 2001, 2006),
        data_root=data_root,
        report_root=report_root,
        materialize_year=lambda _year: pytest.fail("existing years must not materialize"),
    )
    second = orchestrate_us_r2_base_panel_batch(
        years=(2001, 2006),
        data_root=data_root,
        report_root=report_root,
        materialize_year=lambda _year: pytest.fail("existing years must not materialize"),
    )

    assert first.evidence.requested_years == (2001, 2006)
    assert first.evidence.evidence_id == second.evidence.evidence_id
    assert first.evidence.to_dict() == second.evidence.to_dict()


def test_materializer_must_produce_complete_triplet(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="produced no output triplet"):
        orchestrate_us_r2_base_panel_batch(
            years=(2001,),
            data_root=tmp_path / "data",
            report_root=tmp_path / "reports",
            materialize_year=lambda _year: None,
        )


def test_year_normalization_is_frozen_sorted_and_nonempty() -> None:
    assert normalize_us_r2_base_panel_years((2026, 2001, 2022, 2001)) == (2001, 2022, 2026)
    with pytest.raises(ValueError, match="at least one year"):
        normalize_us_r2_base_panel_years(())
    with pytest.raises(ValueError, match="outside frozen range"):
        normalize_us_r2_base_panel_years((2000,))

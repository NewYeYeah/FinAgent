from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from finagent.research.us_baseline_evaluation import (
    USBaselineCandidateEvidence,
    USBaselineEvaluationReport,
    USBaselineRunSpec,
)
from finagent.research.us_baseline_walkforward import (
    bind_us_b0_fold_execution_specs,
    canonical_us_b0_pilot_walk_forward,
)
from finagent.research.us_baseline_walkforward_evidence import (
    assemble_us_b0_walk_forward_evidence,
    build_us_b0_fold_run_manifest,
    parse_us_baseline_evaluation_report,
    validate_canonical_us_b0_protocol_document,
)
from finagent.research.us_baselines import canonical_us_baseline_denominator


def _hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _run_spec() -> USBaselineRunSpec:
    denominator = canonical_us_baseline_denominator()
    return USBaselineRunSpec(
        certification_report_id="us-minute-research-cert-test",
        certification_outcome="CERTIFIED_FOR_ENGINEERING_RESEARCH",
        engineering_universe_id="engineering-universe-test",
        denominator_id=denominator.denominator_id,
    )


def _evaluation(
    fold_index: int,
    *,
    invalid_feature: str | None = None,
) -> USBaselineEvaluationReport:
    denominator = canonical_us_baseline_denominator()
    run_spec = _run_spec()
    candidates = tuple(
        USBaselineCandidateEvidence(
            feature_id=spec.feature_id,
            feature_spec_id=spec.spec_id,
            run_spec_id=run_spec.spec_id,
            observation_count=100,
            eligible_cell_count=100,
            valid_feature_cell_count=95,
            evaluated_periods=30,
            ic_periods=30,
            boundary_unrealized_periods=2,
            mean_rank_ic=(-0.04 + 0.01 * fold_index if index == 0 else 0.02 + index * 0.001),
            mean_gross_return=(-0.001 + 0.0004 * fold_index if index == 0 else 0.001),
            mean_one_way_turnover=0.10 + 0.01 * fold_index,
            mean_gross_traded_weight=0.20 + 0.02 * fold_index,
            feature_coverage=0.95,
            blockers=("insufficient_ic_periods",) if spec.feature_id == invalid_feature else (),
        )
        for index, spec in enumerate(denominator.candidates)
    )
    return USBaselineEvaluationReport(
        run_spec=run_spec,
        denominator_id=denominator.denominator_id,
        candidates=candidates,
    )


def _input_plan_document(run_spec: USBaselineRunSpec, fold_index: int) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "finagent.us-baseline-input-plan.v1",
        "run_spec_id": run_spec.spec_id,
        "resampled_plan_id": f"resampled-plan-{fold_index}",
        "label_plan_id": f"label-plan-{fold_index}",
        "resampling_evidence_id": f"resampling-evidence-{fold_index}",
        "label_evidence_id": f"label-evidence-{fold_index}",
        "source_data_version": "minute-data-version-test",
        "data_version": f"baseline-data-version-{fold_index}",
        "partition_months": ["2026-02", "2026-03"],
        "selected_size_bytes": 1234,
        "output_columns": ["research_asset_id", "available_at", "label_value"],
    }
    identity_payload = {
        key: payload[key]
        for key in (
            "schema_version",
            "run_spec_id",
            "resampled_plan_id",
            "label_plan_id",
            "resampling_evidence_id",
            "label_evidence_id",
            "source_data_version",
            "data_version",
            "partition_months",
            "output_columns",
        )
    }
    payload["plan_id"] = _hash(identity_payload, prefix="us-baseline-input-plan")
    return payload


def _observation_artifact_document(
    run_spec: USBaselineRunSpec,
    fold_index: int,
) -> dict[str, object]:
    digest = hashlib.sha256(f"fold-{fold_index}".encode()).hexdigest()
    payload: dict[str, object] = {
        "schema_version": "finagent.us-baseline-observation-artifact.v1",
        "run_spec_id": run_spec.spec_id,
        "denominator_id": run_spec.denominator_id,
        "row_count": 800,
        "content_sha256": digest,
        "output_filename": "us_b0_baseline_observations.jsonl",
    }
    identity_payload = {
        key: payload[key]
        for key in (
            "schema_version",
            "run_spec_id",
            "denominator_id",
            "row_count",
            "content_sha256",
        )
    }
    payload["artifact_id"] = _hash(identity_payload, prefix="us-baseline-observations")
    return payload


def _materialization_document(
    evaluation: USBaselineEvaluationReport,
    fold_index: int,
) -> dict[str, object]:
    run_spec = evaluation.run_spec
    input_plan = _input_plan_document(run_spec, fold_index)
    observation_artifact = _observation_artifact_document(run_spec, fold_index)
    evaluation_blockers = tuple(f"evaluation:{item}" for item in evaluation.blockers)
    diagnostics: dict[str, object] = {
        "schema_version": "finagent.us-baseline-materialization-diagnostics.v1",
        "passed": not evaluation_blockers,
        "input_row_count": 2000,
        "expected_asset_count": 20,
        "observed_asset_count": 20,
        "missing_assets": [],
        "assets_without_complete_bar": [],
        "complete_bar_count": 1900,
        "incomplete_bar_count": 100,
        "label_anchor_missing_count": 0,
        "close_anchor_mismatch_count": 0,
        "label_available_count": 1500,
        "target_crosses_session_count": 400,
        "target_minute_missing_count": 0,
        "candidate_checks": [],
        "blockers": list(evaluation_blockers),
    }
    engineering_assets = [f"T{index:02d}" for index in range(20)]
    input_materialization: dict[str, object] = {
        "schema_version": "finagent.minute-materialization.v1",
        "materialization_id": f"minute-materialization-fold-{fold_index}",
        "plan_id": input_plan["plan_id"],
        "data_version": input_plan["data_version"],
        "row_count": 2000,
        "output_path": f"fold_{fold_index:02d}/inputs.parquet",
    }
    document: dict[str, object] = {
        "schema_version": "finagent.us-baseline-materialization-report.v1",
        "passed": not evaluation_blockers,
        "blockers": list(evaluation_blockers),
        "run_spec": run_spec.to_dict(),
        "input_plan": input_plan,
        "input_materialization": input_materialization,
        "observation_artifact": observation_artifact,
        "diagnostics": diagnostics,
        "evaluation_report_id": evaluation.report_id,
        "engineering_assets": engineering_assets,
        "engineering_asset_count": len(engineering_assets),
        "scope": "cost_free_diagnostic_pre_agent_baseline_materialization",
        "stage_exit_authority": False,
        "factor_selection_authority": False,
        "alpha_authority": False,
        "limitations": [],
    }
    identity_payload = {
        "schema_version": document["schema_version"],
        "run_spec_id": run_spec.spec_id,
        "input_plan_id": input_plan["plan_id"],
        "input_materialization_id": input_materialization["materialization_id"],
        "observation_artifact_id": observation_artifact["artifact_id"],
        "diagnostics": diagnostics,
        "evaluation_report_id": evaluation.report_id,
        "engineering_assets": engineering_assets,
    }
    document["report_id"] = _hash(identity_payload, prefix="us-baseline-materialization")
    return document


def test_protocol_document_must_equal_exact_preregistered_artifact() -> None:
    protocol = canonical_us_b0_pilot_walk_forward()
    assert validate_canonical_us_b0_protocol_document(protocol.to_dict()) == protocol

    drifted = deepcopy(protocol.to_dict())
    folds = drifted["folds"]
    assert isinstance(folds, list)
    first = folds[0]
    assert isinstance(first, dict)
    first["evaluation_end"] = "2026-03-03T00:00:00+00:00"
    with pytest.raises(ValueError, match="exact canonical preregistered"):
        validate_canonical_us_b0_protocol_document(drifted)


def test_evaluation_parser_rehashes_report_and_candidate_evidence() -> None:
    evaluation = _evaluation(0)
    parsed = parse_us_baseline_evaluation_report(evaluation.to_dict())
    assert parsed.report_id == evaluation.report_id

    drifted = deepcopy(evaluation.to_dict())
    candidates = drifted["candidates"]
    assert isinstance(candidates, list)
    first = candidates[0]
    assert isinstance(first, dict)
    first["mean_rank_ic"] = 0.99
    with pytest.raises(ValueError, match="candidate evidence content identity mismatch"):
        parse_us_baseline_evaluation_report(drifted)


def test_fold_manifest_rejects_materialization_identity_tampering() -> None:
    protocol = canonical_us_b0_pilot_walk_forward()
    evaluation = _evaluation(0)
    execution = bind_us_b0_fold_execution_specs(protocol, evaluation.run_spec)[0]
    document = _materialization_document(evaluation, 1)

    manifest = build_us_b0_fold_run_manifest(execution, document, evaluation)
    assert manifest.passed
    assert manifest.execution_spec.execution_spec_id == execution.execution_spec_id

    drifted = deepcopy(document)
    drifted["engineering_assets"] = list(reversed(drifted["engineering_assets"]))
    with pytest.raises(ValueError, match="materialization report content identity mismatch"):
        build_us_b0_fold_run_manifest(execution, drifted, evaluation)


def test_walk_forward_evidence_graph_binds_all_folds_without_factor_selection() -> None:
    protocol = canonical_us_b0_pilot_walk_forward()
    evaluations = tuple(_evaluation(index) for index in range(3))
    materializations = tuple(
        _materialization_document(evaluation, index + 1)
        for index, evaluation in enumerate(evaluations)
    )

    manifests, aggregate, graph = assemble_us_b0_walk_forward_evidence(
        protocol,
        materializations,
        tuple(item.to_dict() for item in evaluations),
    )

    assert len(manifests) == 3
    assert aggregate.passed
    assert graph.passed
    assert graph.ready_for_us_a0_candidate
    assert graph.aggregate_candidate_count == 8
    assert graph.aggregate_valid_candidate_count == 8
    assert aggregate.candidates[0].worst_fold_rank_ic == -0.04
    assert aggregate.candidates[0].blockers == ()
    payload = graph.to_dict()
    assert payload["stage_exit_authority"] is False
    assert payload["factor_selection_authority"] is False
    assert payload["alpha_authority"] is False


def test_invalid_fold_remains_in_graph_and_blocks_us_a0_readiness() -> None:
    protocol = canonical_us_b0_pilot_walk_forward()
    invalid_feature = canonical_us_baseline_denominator().candidates[0].feature_id
    evaluations = (
        _evaluation(0),
        _evaluation(1, invalid_feature=invalid_feature),
        _evaluation(2),
    )
    materializations = tuple(
        _materialization_document(evaluation, index + 1)
        for index, evaluation in enumerate(evaluations)
    )

    _manifests, aggregate, graph = assemble_us_b0_walk_forward_evidence(
        protocol,
        materializations,
        tuple(item.to_dict() for item in evaluations),
    )

    assert not aggregate.passed
    assert not graph.passed
    assert not graph.ready_for_us_a0_candidate
    assert any(item.startswith("fold:2:") for item in graph.blockers)
    assert any(item.startswith("aggregate:candidate:") for item in graph.blockers)

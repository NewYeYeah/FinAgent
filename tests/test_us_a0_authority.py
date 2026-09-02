from __future__ import annotations

import hashlib
import json

import pytest

from finagent.research.us_agent_value_authority import (
    bind_authorized_us_a0_predecessor,
    require_us_a0_stage_authority,
)
from finagent.research.us_agent_value_protocol import (
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
)
from finagent.research.us_baseline_walkforward import canonical_us_b0_pilot_walk_forward
from finagent.research.us_baselines import canonical_us_baseline_denominator


def _hash(payload: object, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _graph() -> dict[str, object]:
    manifest_ids = ["fold-1", "fold-2", "fold-3"]
    execution_ids = ["exec-1", "exec-2", "exec-3"]
    materialization_ids = ["mat-1", "mat-2", "mat-3"]
    evaluation_ids = ["eval-1", "eval-2", "eval-3"]
    manifests = [
        {
            "manifest_id": manifest_ids[index],
            "execution_spec": {"execution_spec_id": execution_ids[index]},
            "materialization_report_id": materialization_ids[index],
            "evaluation_report_id": evaluation_ids[index],
        }
        for index in range(3)
    ]
    payload: dict[str, object] = {
        "schema_version": "finagent.us-baseline-walk-forward-evidence-graph.v1",
        "protocol_id": canonical_us_b0_pilot_walk_forward().protocol_id,
        "run_spec_id": "us-baseline-run-spec-test",
        "denominator_id": canonical_us_baseline_denominator().denominator_id,
        "fold_count": 3,
        "fold_manifests": manifests,
        "fold_manifest_ids": manifest_ids,
        "fold_execution_spec_ids": execution_ids,
        "fold_materialization_report_ids": materialization_ids,
        "fold_evaluation_report_ids": evaluation_ids,
        "aggregate_report_id": "us-baseline-walk-forward-aggregate-test",
        "aggregate_candidate_count": 8,
        "aggregate_valid_candidate_count": 8,
        "passed": True,
        "ready_for_us_a0_candidate": True,
        "blockers": [],
        "scope": "split_bound_manual_baseline_evidence_graph",
        "status_authority": False,
        "stage_exit_authority": False,
        "factor_selection_authority": False,
        "alpha_authority": False,
    }
    payload["graph_id"] = _hash(payload, "us-baseline-walk-forward-evidence")
    return payload


def _status(graph: dict[str, object]) -> dict[str, object]:
    return {
        "current_stage": "US-A0",
        "stage": {
            "us_b0": {
                "status": "accepted",
                "stage_exit_gate_passed": True,
                "walk_forward_evidence_graph_id": graph["graph_id"],
                "walk_forward_aggregate_report_id": graph["aggregate_report_id"],
            }
        },
    }


def test_formal_a0_predecessor_requires_status_recorded_graph_identity() -> None:
    graph = _graph()
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)

    binding = bind_authorized_us_a0_predecessor(_status(graph), graph, protocol)

    assert binding.us_b0_evidence_graph_id == graph["graph_id"]
    drifted_status = _status(graph)
    stage = drifted_status["stage"]
    assert isinstance(stage, dict)
    us_b0 = stage["us_b0"]
    assert isinstance(us_b0, dict)
    us_b0["walk_forward_evidence_graph_id"] = "different-reviewed-graph"
    with pytest.raises(ValueError, match="project-stage authority"):
        bind_authorized_us_a0_predecessor(drifted_status, graph, protocol)


def test_authorized_binding_rejects_incomplete_three_fold_shape() -> None:
    graph = _graph()
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    status = _status(graph)
    broken = dict(graph)
    broken["fold_manifest_ids"] = ["fold-1", "fold-2"]
    broken_without_id = dict(broken)
    del broken_without_id["graph_id"]
    broken["graph_id"] = _hash(broken_without_id, "us-baseline-walk-forward-evidence")
    stage = status["stage"]
    assert isinstance(stage, dict)
    us_b0 = stage["us_b0"]
    assert isinstance(us_b0, dict)
    us_b0["walk_forward_evidence_graph_id"] = broken["graph_id"]

    with pytest.raises(ValueError, match="three unique fold_manifest_ids"):
        bind_authorized_us_a0_predecessor(status, broken, protocol)


def test_a0_stage_authority_fails_closed_before_project_stage_advances() -> None:
    graph = _graph()
    status = _status(graph)
    status["current_stage"] = "US-B0"

    with pytest.raises(ValueError, match="current_stage=US-A0"):
        require_us_a0_stage_authority(status)

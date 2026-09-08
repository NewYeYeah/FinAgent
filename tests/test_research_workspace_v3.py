from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from finagent.agents.audit import SQLiteAgentAuditStore
from finagent.agents.domain import (
    AgentDecision,
    AgentDecisionStatus,
    AgentRunContext,
    AgentTask,
    PolicyDecision,
    PolicyOutcome,
    ToolCallRequest,
    ToolCallResult,
    ToolCallStatus,
)
from finagent.visualization.research_workspace import ResearchWorkspaceProjection
from finagent.visualization.workspace_api import create_workspace_app


def _research_call(
    store: SQLiteAgentAuditStore,
    *,
    run_id: str,
    call_id: str,
    tool: str,
    arguments: dict[str, object],
    result: dict[str, object],
    state: dict[str, object],
    now: datetime,
    status: ToolCallStatus = ToolCallStatus.SUCCEEDED,
) -> None:
    request = ToolCallRequest(call_id, tool, arguments, now)
    store.record_tool_request(run_id, request)
    policy = PolicyDecision(
        call_id + "-policy",
        run_id,
        call_id,
        tool,
        PolicyOutcome.DENY if status is ToolCallStatus.DENIED else PolicyOutcome.ALLOW,
        "fixture policy",
        now + timedelta(milliseconds=1),
        "r4-development-capabilities",
        "1",
    )
    store.record_policy_decision(policy)
    store.record_tool_result(
        ToolCallResult(
            call_id,
            run_id,
            tool,
            status,
            now + timedelta(milliseconds=2),
            policy.decision_id,
            {"research_result": result, "research_state": state},
            "fixture failure" if status is not ToolCallStatus.SUCCEEDED else "",
        )
    )


def _audit(path: Path, *, comparable: bool = True) -> Path:
    store = SQLiteAgentAuditStore(path)
    now = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
    task = AgentTask("task-r4", "Evaluate bounded factor-set evidence", now)
    context = AgentRunContext(
        "run-r4",
        task.task_id,
        "agent_controller",
        now,
        metadata={
            "project_id": "r4-research",
            "thread_id": "thread-run-r4",
            "controller": "r4",
            "provider_id": "scripted-offline",
            "model_id": "fixture-model",
        },
    )
    store.start_run(task, context)
    resources = {
        "resources": {
            "status": "ACTIVE",
            "attempts": 3,
            "evaluations": 1,
            "tokens": 1200,
            "cost_microusd": 2500,
            "remaining_tool_calls": 17,
            "remaining_evaluations": 2,
            "remaining_tokens": 8800,
            "remaining_cost_microusd": 97500,
        }
    }
    _research_call(
        store,
        run_id=context.run_id,
        call_id="call-set",
        tool="propose_factor_set",
        arguments={"factor_ids": ["factor-a", "factor-b"], "hypothesis_id": "hypothesis-a"},
        result={
            "outcome": "FACTOR_SET_PROPOSED",
            "factor_set": {
                "factor_set_id": "factor-set-a",
                "factor_ids": ["factor-a", "factor-b"],
                "hypothesis_id": "hypothesis-a",
            },
        },
        state=resources,
        now=now + timedelta(seconds=1),
    )
    _research_call(
        store,
        run_id=context.run_id,
        call_id="call-allocator",
        tool="propose_allocator",
        arguments={"allocator": "equal_weight"},
        result={
            "outcome": "ALLOCATOR_PROPOSED",
            "allocator_proposal": {
                "allocator_proposal_id": "allocator-a",
                "allocator": "equal_weight",
            },
        },
        state=resources,
        now=now + timedelta(seconds=2),
    )
    for index, (experiment_id, mean_return) in enumerate((("exp-a", 0.01), ("exp-b", 0.02)), start=3):
        snapshot = {
            "resources": {
                **resources["resources"],
                "attempts": index,
                "evaluations": index - 2,
                "tokens": 1200 + index * 100,
                "cost_microusd": 2500 + index * 100,
                "remaining_evaluations": max(0, 4 - index),
            }
        }
        _research_call(
            store,
            run_id=context.run_id,
            call_id=f"call-{experiment_id}",
            tool="evaluate_portfolio",
            arguments={
                "factor_set_id": "factor-set-a",
                "allocator_proposal_id": "allocator-a",
                "hypothesis_id": "hypothesis-a",
            },
            result={
                "outcome": "PORTFOLIO_EVALUATED",
                "experiment_id": experiment_id,
                "factor_set_id": "factor-set-a",
                "factor_ids": ["factor-a", "factor-b"],
                "allocator_proposal_id": "allocator-a",
                "preferred_allocator": "equal_weight",
                "compatibility_id": "compat-a" if comparable else f"compat-{experiment_id}",
                "evaluation_mode": "development_descriptive",
                "summary": {
                    "arms": {
                        "equal_weight": {
                            "mean_fold_return_5bp": mean_return,
                            "worst_fold_return_5bp": -0.01,
                            "evaluable_folds": 3,
                        }
                    }
                },
                "resource_cost": {"evaluation_slots": 1},
            },
            state=snapshot,
            now=now + timedelta(seconds=index),
        )
    compare_result = {
        "outcome": "EXPERIMENTS_COMPARED" if comparable else "NOT_COMPARABLE",
        "compatible_source_folds_cost_execution": comparable,
        "experiments": [
            {"experiment_id": "exp-a", "metrics_5bp": {"mean_fold_return_5bp": 0.01}},
            {"experiment_id": "exp-b", "metrics_5bp": {"mean_fold_return_5bp": 0.02}},
        ],
        "factor_set_overlap": [{"left": "exp-a", "right": "exp-b", "factor_overlap": 1.0}],
    }
    _research_call(
        store,
        run_id=context.run_id,
        call_id="call-compare",
        tool="compare_experiments",
        arguments={"experiment_ids": ["exp-a", "exp-b"]},
        result=compare_result,
        state=resources,
        now=now + timedelta(seconds=6),
    )
    _research_call(
        store,
        run_id=context.run_id,
        call_id="call-failed",
        tool="evaluate_portfolio",
        arguments={
            "factor_set_id": "missing-set",
            "allocator_proposal_id": "allocator-a",
            "hypothesis_id": "hypothesis-b",
        },
        result={"outcome": "TOOL_FAILED", "code": "unknown_run_local_proposal"},
        state=resources,
        now=now + timedelta(seconds=7),
        status=ToolCallStatus.FAILED,
    )
    _research_call(
        store,
        run_id=context.run_id,
        call_id="call-final",
        tool="finalize_candidate",
        arguments={
            "recommendation": "none",
            "factor_set_id": None,
            "allocator_proposal_id": None,
            "experiment_ids": ["exp-a", "exp-b"],
            "decision": "Reject: evidence remains incomplete.",
        },
        result={
            "outcome": "NO_CANDIDATE_RECOMMENDED",
            "decision": "Reject: evidence remains incomplete.",
            "factor_set": None,
            "allocator": None,
            "experiment_ids": ["exp-a", "exp-b"],
        },
        state={**resources, "resources": {**resources["resources"], "status": "NO_CANDIDATE_RECOMMENDED"}},
        now=now + timedelta(seconds=8),
    )
    store.finish_run(
        AgentDecision(
            context.run_id,
            AgentDecisionStatus.COMPLETED,
            "No candidate",
            now + timedelta(seconds=9),
            ("call-set", "call-allocator", "call-exp-a", "call-exp-b", "call-compare", "call-failed", "call-final"),
        )
    )
    return path


def _accepted_cycle(root: Path) -> Path:
    target = root / "r4-v3-result"
    target.mkdir(parents=True)
    (target / "campaign_result_attestation.json").write_text(
        json.dumps(
            {
                "schema_version": "finagent.r4-campaign-result-attestation.v1",
                "review_disposition": "R4_RESULT_ACCEPTED",
                "protocol_id": "protocol-a",
                "protocol_version": "r4-matched-v3",
                "campaign_result_id": "cycle-a",
                "candidate_decision": "NO_ADAPTIVE_CANDIDATE",
                "candidate_id": None,
                "agent_value": "INCONCLUSIVE",
                "economic_evidence": {
                    "deterministic_strategy_count": 20,
                    "complete_deterministic_strategy_count": 0,
                    "deterministic_evidence_complete": False,
                    "interpretation": "coverage/completeness-driven",
                },
                "agent_reliability": {"rejected_action_attempts": 62},
                "development_only": True,
                "alpha_authority": False,
                "paper_authority": False,
                "live_authority": False,
                "r5_eligible": False,
            }
        ),
        encoding="utf-8",
    )
    (target / "resource_summary.json").write_text(
        json.dumps({"schema_version": "finagent.r4-campaign-resource-summary.v1", "aggregate": {"charged_tokens": 100}}),
        encoding="utf-8",
    )
    return root


def test_experiment_list_detail_and_failed_attempt_are_persisted_only(tmp_path: Path) -> None:
    projection = ResearchWorkspaceProjection(_audit(tmp_path / "audit.sqlite"), cycle_paths=())
    payload = projection.experiments(run_id="run-r4")
    assert [item["status"] for item in payload["items"]] == ["completed", "completed", "failed"]
    completed = projection.experiment("exp-a")["item"]
    assert completed["authoritative_metrics"]["mean_fold_return_5bp"] == 0.01
    assert completed["metrics_source"] == "persisted_research_result"
    assert completed["provider_id"] == "scripted-offline"
    assert completed["model_id"] == "fixture-model"
    assert completed["tokens"] == 1500
    assert completed["agent_decision"]["recommendation"] == "reject"
    assert completed["browser_recomputation"] is False
    assert completed["hidden_reasoning"] == "not_persisted_not_projected"
    failed = projection.experiment("call-failed")["item"]
    assert failed["canonical_experiment_identity_available"] is False
    assert failed["error"] == "fixture failure"


def test_two_experiment_comparison_uses_persisted_result_and_never_ranks(tmp_path: Path) -> None:
    projection = ResearchWorkspaceProjection(_audit(tmp_path / "audit.sqlite"), cycle_paths=())
    comparison = projection.comparison(["exp-a", "exp-b"])
    assert comparison["comparable"] is True
    assert comparison["persisted_comparison"]["experiments"][1]["metrics_5bp"]["mean_fold_return_5bp"] == 0.02
    assert comparison["ranking"] is None
    assert comparison["browser_recomputation"] is False


def test_non_comparable_experiments_expose_persisted_compatibility_reason(tmp_path: Path) -> None:
    projection = ResearchWorkspaceProjection(_audit(tmp_path / "audit.sqlite", comparable=False), cycle_paths=())
    comparison = projection.comparison(["exp-a", "exp-b"])
    assert comparison["comparable"] is False
    assert comparison["persisted_comparison"]["outcome"] == "NOT_COMPARABLE"
    assert comparison["reason"] == "incompatible_source_folds_cost_execution"
    assert comparison["ranking"] is None


def test_graph_uses_canonical_ids_and_marks_unresolved_lineage(tmp_path: Path) -> None:
    audit = _audit(tmp_path / "audit.sqlite")
    cycles = _accepted_cycle(tmp_path / "cycles")
    projection = ResearchWorkspaceProjection(audit, cycle_paths=(cycles,))
    graph = projection.graph(run_id="run-r4")
    by_id = {item["node_id"]: item for item in graph["nodes"]}
    assert "hypothesis:hypothesis-a" in by_id
    assert "factor_set:factor-set-a" in by_id
    assert "experiment:exp-a" in by_id
    assert "evaluation:exp-a" in by_id
    assert "agent_decision:call-final" in by_id
    assert "research_cycle:cycle-a" in by_id
    assert by_id["terminal:cycle-a"]["label"] == "NO_ADAPTIVE_CANDIDATE"
    assert by_id["terminal:cycle-a"]["details"]["agent_value"] == "INCONCLUSIVE"
    assert by_id["evaluation:cycle-a"]["details"]["complete_deterministic_strategy_count"] == 0
    assert any(item["reason"] == "persisted_experiment_id_unavailable" for item in graph["unresolved"])
    assert any(item["reason"] == "accepted_attestation_does_not_embed_run_local_experiment_identities" for item in graph["unresolved"])
    assert graph["canonical_identity_only"] is True
    assert graph["hidden_reasoning"] == "not_persisted_not_projected"


def test_workspace_routes_are_get_only_and_do_not_create_financial_authority(tmp_path: Path) -> None:
    audit = _audit(tmp_path / "audit.sqlite")
    app = create_workspace_app(report_paths=(), agent_audit_path=audit, frontend_dir=None)
    with TestClient(app) as client:
        listed = client.get("/api/v3/research-experiments?run_id=run-r4")
        assert listed.status_code == 200
        assert listed.json()["browser_recomputation"] is False
        detail = client.get("/api/v3/research-experiments/exp-a")
        assert detail.status_code == 200
        compared = client.get("/api/v3/research-experiments/compare?experiment_id=exp-a&experiment_id=exp-b")
        assert compared.status_code == 200
        assert compared.json()["ranking"] is None
        graph = client.get("/api/v3/research-graph?run_id=run-r4")
        assert graph.status_code == 200
        assert graph.json()["browser_recomputation"] is False
        assert client.post("/api/v3/research-experiments", json={}).status_code == 405

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

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
from finagent.visualization.agent_projection import (
    AgentProjectionItemType,
    load_agent_run_projection,
)
from finagent.visualization.semantic import (
    EvidenceAuthority,
    EvidenceBundle,
    EvidenceContractError,
    EvidenceRef,
    EvidenceStage,
    LineageEdge,
    LineageGraph,
    LineageNode,
    parse_evidence_report,
)
from finagent.visualization.widgets import WidgetSurface, default_widget_specs


def _a2p6_report() -> dict[str, object]:
    digest = "a" * 64
    return {
        "schema_version": "finagent.ashare-robust-research-program.v1",
        "program_result_id": "ashare-robust-program-result-test",
        "mode": "agent",
        "system_acceptance": {"passed": True, "status": "PASS"},
        "research_outcome": {
            "status": "ROBUST_FACTOR_FAMILY_FROZEN",
            "robust_factor_count": 1,
            "promotion_eligible": False,
            "reason_codes": ["A_SHARE_EXECUTION_NOT_CERTIFIED"],
        },
        "program_status": "frozen",
        "data_version": "data-v1",
        "program_spec": {
            "schema_version": "finagent.ashare-research-program-spec.v1",
            "program_id": "program-a26",
            "spec_id": "ashare-research-program-spec-test",
            "data_version": "data-v1",
            "candidate_selection_id": "selection-universe",
            "universe_policy_version": "universe-policy-v1",
            "walk_forward_plan": {
                "schema_version": "finagent.ashare-expanding-walk-forward-plan.v1",
                "plan_id": "plan-v1",
                "folds": [],
                "reserve": [
                    "2025-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ],
                "reserve_status": "untouched",
            },
            "approved_input_fields": ["simple_return_20"],
            "primary_label": "forward_simple_return_1",
            "decay_labels": ["forward_simple_return_5"],
            "factor_quant_config": {},
            "gate_config": {},
            "selector_config": {},
            "generation_config": {},
            "reserve_id": "reserve-v1",
        },
        "candidate_universe": {
            "selection_id": "selection-universe",
            "size": 150,
        },
        "universe_policy": {
            "data_version": "universe-policy-v1",
        },
        "candidate_denominator": [
            {
                "feature_id": "momentum-20",
                "feature_digest": digest,
                "hypothesis": "medium-horizon continuation",
                "input_fields": ["simple_return_20"],
                "lookback": 1,
                "generator_id": "deepseek:test",
            }
        ],
        "walk_forward_report": {
            "schema_version": "finagent.ashare-walk-forward-factor-report.v1",
            "report_id": "walk-forward-v1",
            "program_spec_id": "ashare-research-program-spec-test",
            "data_version": "data-v1",
            "primary_label": "forward_simple_return_1",
            "plan_id": "plan-v1",
            "factor_value_correlations": {},
            "candidates": [
                {
                    "feature_id": "momentum-20",
                    "feature_digest": digest,
                    "folds": [
                        {
                            "fold_id": "wf-2024",
                            "train_direction": 1,
                            "train_rank_ic": 0.02,
                            "train_rank_icir": 0.15,
                            "test_raw_rank_ic": 0.01,
                            "test_raw_rank_icir": 0.09,
                            "test_rank_ic": 0.01,
                            "test_rank_icir": 0.09,
                            "test_raw_long_short_sharpe": 0.4,
                            "test_long_short_sharpe": 0.4,
                            "coverage": 0.97,
                            "quantile_monotonicity": 0.8,
                            "mean_one_way_turnover": 0.3,
                            "periods": 240,
                        }
                    ],
                    "dominant_direction": 1,
                    "direction_consistency": 1.0,
                    "pooled_rank_ic": 0.01,
                    "pooled_rank_icir": 0.09,
                    "mean_fold_rank_icir": 0.09,
                    "worst_fold_rank_icir": 0.09,
                    "positive_fold_ratio": 1.0,
                    "mean_fold_long_short_sharpe": 0.4,
                    "worst_fold_long_short_sharpe": 0.4,
                    "coverage_mean": 0.97,
                    "coverage_min": 0.97,
                    "quantile_monotonicity": 0.8,
                    "mean_one_way_turnover": 0.3,
                    "horizon_sign_consistency": 1.0,
                    "hac": {
                        "tstat": 2.0,
                        "raw_pvalue": 0.04,
                        "holm_adjusted_pvalue": 0.04,
                        "bh_qvalue": 0.04,
                    },
                    "block_bootstrap": {
                        "pvalue": 0.05,
                        "ci_lower": 0.001,
                        "ci_upper": 0.02,
                    },
                }
            ],
        },
        "gate_report": {
            "schema_version": "finagent.ashare-robust-candidate-gate.v1",
            "gate_report_id": "gate-v1",
            "walk_forward_report_id": "walk-forward-v1",
            "config": {},
            "candidates": [
                {
                    "feature_id": "momentum-20",
                    "feature_digest": digest,
                    "passed": True,
                    "reason_codes": [],
                    "robust_score": 0.2,
                }
            ],
        },
        "frozen_selection": {
            "schema_version": "finagent.ashare-robust-factor-selection.v1",
            "selection_id": "robust-selection-v1",
            "walk_forward_report_id": "walk-forward-v1",
            "gate_report_id": "gate-v1",
            "status": "ROBUST_FACTOR_FAMILY_FROZEN",
            "config": {},
            "components": [
                {
                    "feature_id": "momentum-20",
                    "feature_digest": digest,
                    "direction": 1,
                    "robust_score": 0.2,
                    "weight": 1.0,
                }
            ],
        },
        "reserve": {
            "reserve_id": "reserve-v1",
            "start": "2025-01-01T00:00:00+00:00",
            "end": "2026-01-01T00:00:00+00:00",
            "status": "untouched",
        },
    }


def _a4_report() -> dict[str, object]:
    return {
        "schema_version": "finagent.ashare-portfolio-validation.v1",
        "portfolio_validation_id": "a4-validation-v1",
        "mode": "agent",
        "system_acceptance": {"passed": True, "status": "PASS"},
        "source_research_status": "ROBUST_FACTOR_FAMILY_FROZEN",
        "validation_spec": {
            "schema_version": "finagent.ashare-portfolio-validation-spec.v1",
            "spec_id": "a4-spec-v1",
            "source_program_result_id": "ashare-robust-program-result-test",
            "source_report_digest": "source-report-digest",
            "source_program_spec_id": "ashare-research-program-spec-test",
            "source_selection_id": "robust-selection-v1",
            "data_version": "data-v1",
            "candidate_selection_id": "selection-universe",
            "universe_policy_version": "universe-policy-v1",
            "plan_id": "plan-v1",
            "reserve_id": "reserve-v1",
            "selected_feature_digests": ["a" * 64],
            "selected_weights": [1.0],
            "selected_directions": [1],
            "fee_schedule_id": "fees-v1",
            "net_execution_config": {},
            "gross_execution_config": {},
            "validation_config": {},
        },
        "folds": [
            {
                "fold_id": "wf-2024",
                "train_range": [
                    "2018-01-01T00:00:00+00:00",
                    "2024-01-01T00:00:00+00:00",
                ],
                "test_range": [
                    "2024-01-01T00:00:00+00:00",
                    "2025-01-01T00:00:00+00:00",
                ],
                "alpha_model_id": "alpha-v1",
                "alpha_calibration": {},
                "points": [
                    {
                        "session_date": "2024-01-02",
                        "signal_asof": "2024-01-02T01:29:59+00:00",
                        "rebalanced": True,
                        "cash_fallback": False,
                        "target_id": "target-v1",
                        "net_nav": 1_001_000.0,
                        "gross_nav": 1_002_000.0,
                        "net_return": 0.001,
                        "gross_return": 0.002,
                        "fees": 100.0,
                        "slippage": 50.0,
                        "gross_traded_weight": 0.2,
                        "one_way_turnover": 0.1,
                        "target_turnover": 0.11,
                        "implementation_shortfall": 0.02,
                        "desired_order_count": 10,
                        "order_count": 8,
                        "fill_count": 7,
                        "rejected_order_count": 2,
                        "maximum_ex_post_participation": 0.03,
                        "reason_counts": {"T1_SELLABLE_QUANTITY_CLIPPED": 2},
                    }
                ],
                "net_metrics": {
                    "periods": 1,
                    "total_return": 0.001,
                    "annualized_return": 0.1,
                    "annualized_volatility": 0.2,
                    "sharpe": 0.5,
                    "max_drawdown": -0.05,
                },
                "gross_metrics": {
                    "periods": 1,
                    "total_return": 0.002,
                    "annualized_return": 0.15,
                    "annualized_volatility": 0.2,
                    "sharpe": 0.8,
                    "max_drawdown": -0.04,
                },
                "total_fees": 100.0,
                "total_slippage": 50.0,
                "total_gross_traded_weight": 0.2,
                "total_one_way_turnover": 0.1,
                "average_implementation_shortfall": 0.02,
                "maximum_ex_post_participation": 0.03,
                "reason_counts": {"T1_SELLABLE_QUANTITY_CLIPPED": 2},
                "ledger_digest": "fold-ledger-v1",
            }
        ],
        "aggregate": {
            "net_metrics": {
                "periods": 1,
                "total_return": 0.001,
                "annualized_return": 0.1,
                "annualized_volatility": 0.2,
                "sharpe": 0.5,
                "max_drawdown": -0.05,
            },
            "gross_metrics": {
                "periods": 1,
                "total_return": 0.002,
                "annualized_return": 0.15,
                "annualized_volatility": 0.2,
                "sharpe": 0.8,
                "max_drawdown": -0.04,
            },
            "gross_to_net_return_drag": 0.001,
            "total_fees": 100.0,
            "total_slippage": 50.0,
            "total_gross_traded_weight": 0.2,
            "total_one_way_turnover": 0.1,
            "average_implementation_shortfall": 0.02,
            "maximum_ex_post_participation": 0.03,
            "positive_fold_ratio": 1.0,
            "worst_fold_net_sharpe": 0.5,
            "desired_order_count": 10,
            "order_count": 8,
            "fill_count": 7,
            "rejected_order_count": 2,
            "rejected_order_ratio": 0.2,
            "rebalance_count": 1,
            "cash_fallback_count": 0,
            "cash_fallback_ratio": 0.0,
            "hac_tstat": 2.0,
            "hac_pvalue": 0.04,
            "bootstrap_pvalue": 0.05,
            "bootstrap_ci_lower": 0.0,
            "bootstrap_ci_upper": 0.002,
            "reason_counts": {"T1_SELLABLE_QUANTITY_CLIPPED": 2},
        },
        "research_outcome": {
            "status": "EXECUTION_VALIDATION_PASSED_INTERNAL",
            "execution_validation_passed": True,
            "promotion_eligible": False,
            "reason_codes": ["RESERVE_UNTOUCHED"],
            "policy": {},
        },
        "ledger_digest": "a4-execution-ledger-v1",
        "reserve": {
            "reserve_id": "reserve-v1",
            "start": "2025-01-01T00:00:00+00:00",
            "end": "2026-01-01T00:00:00+00:00",
            "status": "untouched",
        },
    }


def test_a2p6_report_projects_into_stable_bundle_and_lineage() -> None:
    bundle = parse_evidence_report(_a2p6_report(), source_uri="reports/a26.json")
    assert bundle.root.stage is EvidenceStage.A2P6_ROBUST_RESEARCH
    assert bundle.root.program_id == "program-a26"
    assert bundle.research_status == "ROBUST_FACTOR_FAMILY_FROZEN"
    assert bundle.reserve_status == "untouched"
    assert bundle.promotion_eligible is False
    assert len(bundle.factors) == 1
    factor = bundle.factors[0]
    assert factor.selected is True
    assert factor.status == "PASS"
    assert factor.metrics["pooled_rank_icir"] == pytest.approx(0.09)
    assert factor.folds[0].metrics["test_rank_icir"] == pytest.approx(0.09)
    lineage = bundle.lineage()
    assert len(lineage.nodes) == 5
    assert {(edge.parent_id, edge.child_id) for edge in lineage.edges} == {
        ("ashare-research-program-spec-test", "walk-forward-v1"),
        ("walk-forward-v1", "gate-v1"),
        ("gate-v1", "robust-selection-v1"),
        ("robust-selection-v1", "ashare-robust-program-result-test"),
    }


def test_a4_report_projects_portfolio_execution_and_a26_parent() -> None:
    bundle = parse_evidence_report(_a4_report(), source_uri="reports/a4.json")
    assert bundle.root.stage is EvidenceStage.A4_PORTFOLIO_VALIDATION
    assert bundle.research_status == "EXECUTION_VALIDATION_PASSED_INTERNAL"
    assert bundle.reserve_status == "untouched"
    assert bundle.portfolio is not None
    assert bundle.execution is not None
    assert bundle.portfolio.metrics["net_sharpe"] == pytest.approx(0.5)
    assert bundle.portfolio.points[0].gross_nav == pytest.approx(1_002_000.0)
    assert bundle.execution.desired_order_count == 10
    assert bundle.execution.rejected_order_count == 2
    assert bundle.execution.reason_counts["T1_SELLABLE_QUANTITY_CLIPPED"] == 2
    assert bundle.execution.costs["fees"] == pytest.approx(100.0)
    lineage = bundle.lineage()
    assert {(edge.parent_id, edge.child_id) for edge in lineage.edges} == {
        ("ashare-robust-program-result-test", "a4-spec-v1"),
        ("a4-spec-v1", "a4-execution-ledger-v1"),
        ("a4-execution-ledger-v1", "a4-validation-v1"),
    }


def test_lineage_rejects_cycles_and_unknown_parents() -> None:
    nodes = (
        LineageNode("a", "type", EvidenceStage.UNKNOWN, EvidenceAuthority.AUTHORITATIVE),
        LineageNode("b", "type", EvidenceStage.UNKNOWN, EvidenceAuthority.AUTHORITATIVE),
    )
    with pytest.raises(EvidenceContractError, match="acyclic"):
        LineageGraph(nodes=nodes, edges=(LineageEdge("a", "b"), LineageEdge("b", "a")))
    with pytest.raises(EvidenceContractError, match="unknown node"):
        LineageGraph(nodes=nodes, edges=(LineageEdge("a", "missing"),))


def test_bundle_rejects_unresolved_parent_reference() -> None:
    root = EvidenceRef(
        evidence_id="root",
        evidence_type="root",
        schema_version="v1",
        stage=EvidenceStage.UNKNOWN,
        authority=EvidenceAuthority.AUTHORITATIVE,
        artifact_digest="digest",
        parent_ids=("missing",),
    )
    with pytest.raises(EvidenceContractError, match="unknown node"):
        EvidenceBundle(
            root=root,
            refs=(root,),
            system_status="PASS",
            research_status="PASS",
            reserve_status="untouched",
            promotion_eligible=False,
        )


def test_unsupported_report_schema_fails_closed() -> None:
    with pytest.raises(EvidenceContractError, match="unsupported evidence schema"):
        parse_evidence_report({"schema_version": "other.v1"})


def test_default_widget_contract_is_unique_linkable_and_read_only_oriented() -> None:
    specs = default_widget_specs()
    assert len({spec.widget_id for spec in specs}) == len(specs)
    assert {spec.surface for spec in specs} == {WidgetSurface.RESEARCH, WidgetSurface.AGENT}
    assert any(spec.widget_id == "a4.portfolio.gross_net_nav" for spec in specs)
    assert any(spec.widget_id == "a4.execution.order_funnel" for spec in specs)
    assert any(spec.widget_id == "agent.run.activity" for spec in specs)
    for spec in specs:
        parameter_names = {value.name for value in spec.parameters}
        assert set(spec.link_keys).issubset(parameter_names)
        assert spec.data_endpoint.startswith(("/api/v1/", "/api/v2/"))
        assert not spec.data_endpoint.lower().startswith("post ")


def test_agent_audit_projects_to_ui_semantics_without_hidden_reasoning(tmp_path) -> None:
    database = tmp_path / "agent.sqlite"
    store = SQLiteAgentAuditStore(database, event_id_factory=iter(
        ("evt-1", "evt-2", "evt-3", "evt-4", "evt-5")
    ).__next__)
    now = datetime(2026, 8, 28, 8, 0, tzinfo=UTC)
    task = AgentTask(
        task_id="task-1",
        objective="Evaluate factor evidence",
        created_at=now,
        metadata={},
    )
    context = AgentRunContext(
        run_id="run-1",
        task_id="task-1",
        actor="research-agent",
        started_at=now,
        max_tool_calls=5,
        tool_allowlist=("inspect_factor",),
        metadata={
            "trigger_type": "research_program",
            "project_id": "program-a26",
            "thread_id": "thread-1",
        },
    )
    store.start_run(task, context)
    request = ToolCallRequest(
        call_id="call-1",
        tool_name="inspect_factor",
        arguments={"feature_digest": "a" * 64},
        requested_at=now + timedelta(seconds=1),
    )
    store.record_tool_request("run-1", request)
    policy = PolicyDecision(
        decision_id="policy-1",
        run_id="run-1",
        call_id="call-1",
        tool_name="inspect_factor",
        outcome=PolicyOutcome.ALLOW,
        reason="read-only inspection",
        decided_at=now + timedelta(seconds=2),
        policy_name="research-readonly",
        policy_version="v1",
    )
    store.record_policy_decision(policy)
    store.record_tool_result(
        ToolCallResult(
            call_id="call-1",
            run_id="run-1",
            tool_name="inspect_factor",
            status=ToolCallStatus.SUCCEEDED,
            finished_at=now + timedelta(seconds=3),
            policy_decision_id="policy-1",
            output={"report_id": "factor-report-v1"},
        )
    )
    store.finish_run(
        AgentDecision(
            run_id="run-1",
            status=AgentDecisionStatus.COMPLETED,
            summary="Factor evidence inspected",
            finished_at=now + timedelta(seconds=4),
            tool_call_ids=("call-1",),
        )
    )
    before = database.stat().st_mtime_ns
    projection = load_agent_run_projection(database, "run-1")
    after = database.stat().st_mtime_ns
    assert before == after
    assert projection.project_id == "program-a26"
    assert projection.thread_id == "thread-1"
    assert projection.trigger_type == "research_program"
    assert projection.status == "completed"
    assert projection.latency_ms == pytest.approx(4000.0)
    assert projection.governance["tool_call_count"] == 1
    item_types = {item.item_type for item in projection.items}
    assert AgentProjectionItemType.PLAN in item_types
    assert AgentProjectionItemType.TOOL in item_types
    assert AgentProjectionItemType.GUARDRAIL in item_types
    assert AgentProjectionItemType.RESULT in item_types
    rendered = projection.to_dict()
    assert rendered["hidden_reasoning"] == "not_persisted_not_projected"
    assert "reasoning_content" not in json_like_text(rendered)


def json_like_text(value: object) -> str:
    return str(value).lower()

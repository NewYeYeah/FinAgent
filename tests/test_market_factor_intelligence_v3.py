from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from finagent.domain.research import TimeRange
from finagent.research.market_state import MarketFeatureConfig, MarketStateSource
from finagent.research.market_state_gmm import GMMConfig, MarketStateModel
from finagent.visualization.market_factor_intelligence import MarketFactorIntelligenceProjection
from finagent.visualization.research_workspace import ResearchWorkspaceProjection
from finagent.visualization.workspace_api import create_workspace_app


class _ResearchLinks:
    def experiments(self):
        return {"items": [{"identity": "exp-a", "experiment_id": "exp-a", "attempt_id": "call-a", "run_id": "run-a", "status": "completed", "factor_ids": ["factor-a"]}]}

    def graph(self):
        return {"nodes": [{"node_id": "agent_decision:decision-a", "kind": "agent_decision", "status": "recorded", "context": {"run_id": "run-a"}, "details": {"factor_id": "factor-a", "reason": "persisted decision"}}]}


def _model() -> MarketStateModel:
    source = MarketStateSource("source-a", "rev-a", "data-a", "admission-a", "calendar-a")
    return MarketStateModel(
        source,
        MarketFeatureConfig("IWM", 4),
        GMMConfig(n_components=2, min_train_rows=2),
        TimeRange(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 3, tzinfo=UTC)),
        datetime(2026, 1, 3, tzinfo=UTC),
        "train-digest",
        4,
        "implementation-a",
        (("numpy", "1"),),
        (0.0, 0.0),
        (1.0, 1.0),
        (0.5, 0.5),
        ((-1.0, 0.5), (1.0, 1.5)),
        ((1.0, 1.0), (1.0, 1.0)),
        3,
    )


def _library(path: Path, model_id: str) -> None:
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE factors (factor_id TEXT PRIMARY KEY, definition TEXT NOT NULL);
        CREATE TABLE lifecycle (factor_id TEXT NOT NULL, sequence INTEGER NOT NULL, status TEXT NOT NULL, available_at TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, evaluation_id TEXT, PRIMARY KEY (factor_id, sequence));
        CREATE TABLE evaluations (evaluation_id TEXT PRIMARY KEY, factor_id TEXT NOT NULL, model_id TEXT NOT NULL, available_at TEXT NOT NULL, payload TEXT NOT NULL);
    """)
    for factor_id, status, origin in (("factor-a", "ACTIVE", "agent"), ("factor-b", "DORMANT", "programmatic"), ("factor-c", "REJECTED", "manual")):
        definition = {"version": "finagent.factor-registration.v1", "factor_id": factor_id, "graph": {}, "family": "flow", "mechanism": "causal mechanism", "hypothesis": f"hypothesis {factor_id}", "origin": origin, "provenance": {"source": "fixture"}, "created_at": "2026-01-01T00:00:00+00:00", "activation_scope": "research_only_no_alpha_paper_or_live_authority"}
        connection.execute("INSERT INTO factors VALUES (?, ?)", (factor_id, json.dumps(definition, sort_keys=True, separators=(",", ":"))))
        connection.execute("INSERT INTO lifecycle VALUES (?, 0, 'PROPOSED', '2026-01-01T00:00:00+00:00', ?, 'registered hypothesis', NULL)", (factor_id, origin))
        connection.execute("INSERT INTO lifecycle VALUES (?, 1, ?, '2026-01-05T00:00:00+00:00', 'deterministic_core', 'fixture lifecycle', ?)", (factor_id, status, "eval-" + factor_id if status != "REJECTED" else None))
        if status != "REJECTED":
            report = {"version": "finagent.factor-evaluation.v1", "evaluation_id": "eval-" + factor_id, "factor_id": factor_id, "model_id": model_id, "source_id": "source-a", "implementation_id": "impl-eval", "window": {"start": "2026-01-03T00:00:00+00:00", "end": "2026-01-05T00:00:00+00:00"}, "available_at": "2026-01-05T00:00:00+00:00", "compiled_batch_id": "batch-a", "global": {"coverage": 0.8, "turnover": 0.2, "decay_rank_ic": {"15": 0.03}, "rank_similarity": {"factor-c": 0.1}, "economic_scenarios": {"5.0": {"compounded_return": 0.01}}}, "by_market_state": {"state_0": {"coverage": 0.9, "turnover": 0.1, "decay_rank_ic": {"15": 0.04}}, "state_1": {"coverage": 0.7, "turnover": 0.3, "decay_rank_ic": {"15": -0.01}}}, "conditioning": "soft_probability_weighted_IC_coverage_decay_similarity", "alpha_authority": False, "paper_authority": False, "live_authority": False}
            connection.execute("INSERT INTO evaluations VALUES (?, ?, ?, ?, ?)", (report["evaluation_id"], factor_id, model_id, report["available_at"], json.dumps(report, sort_keys=True, separators=(",", ":"))))
    connection.commit()
    connection.close()


def _artifacts(root: Path) -> tuple[Path, str]:
    target = root / "adaptive"
    target.mkdir(parents=True)
    model = _model()
    (target / "market_state_model.json").write_text(json.dumps(model.to_dict()), encoding="utf-8")
    states = [
        {"model_id": model.model_id, "event_time": "2026-01-03T10:00:00+00:00", "available_at": "2026-01-03T10:15:00+00:00", "session_id": "s1", "probabilities": [0.8, 0.2], "state": 0, "unavailable_reason": None},
        {"model_id": model.model_id, "event_time": "2026-01-03T10:15:00+00:00", "available_at": "2026-01-03T10:30:00+00:00", "session_id": "s1", "probabilities": [0.2, 0.8], "state": 1, "unavailable_reason": None},
        {"model_id": model.model_id, "event_time": "2026-01-03T10:30:00+00:00", "available_at": "2026-01-03T10:45:00+00:00", "session_id": "s1", "probabilities": None, "state": None, "unavailable_reason": "OBSERVATION_NOT_AVAILABLE"},
    ]
    (target / "result.json").write_text(json.dumps({"run_id": "slice-a", "terminal": "DEVELOPMENT_SLICE_COMPLETE", "evaluation_data_status": "EVALUABLE", "model_id": model.model_id, "states": states, "interpretation": "development diagnostics", "alpha_authority": False, "paper_authority": False, "live_authority": False}), encoding="utf-8")
    _library(target / "factor_library.sqlite", model.model_id)
    portfolio = root / "portfolio"
    portfolio.mkdir()
    (portfolio / "result.json").write_text(json.dumps({"version": "finagent.deterministic-adaptive-result.v1", "run_id": "portfolio-a", "folds": [{"fold": {"name": "fold-a"}, "factor_ids": ["factor-a", "factor-b"], "state_model": {"model_id": model.model_id}, "arms": {"regime_conditional": {"factor_weight_series": [{"allocator_id": "allocator-a", "as_of": "2026-01-04T10:15:00+00:00", "session_id": "s2", "weights": {"factor-a": 0.7, "factor-b": 0.3}, "market_state_model_id": model.model_id, "state_probabilities": [0.75, 0.25], "fallback_reason": None, "history_id": "history-a"}]}}}], "overall": {}, "alpha_authority": False, "paper_authority": False, "live_authority": False}), encoding="utf-8")
    return root, model.model_id


def test_market_state_projection_is_persisted_causal_and_unavailable_explicit(tmp_path: Path) -> None:
    root, model_id = _artifacts(tmp_path)
    projection = MarketFactorIntelligenceProjection((root,), research_workspace=_ResearchLinks())  # type: ignore[arg-type]
    market = projection.market(model_id)["item"]
    assert market["current_snapshot"]["unavailable_reason"] == "OBSERVATION_NOT_AVAILABLE"
    assert market["historical_states"][0]["probabilities"] == [0.8, 0.2]
    assert market["transitions"][0]["from_state"] == 0
    assert market["transitions"][0]["to_state"] == 1
    assert market["transitions"][0]["semantics"] == "adjacent_persisted_available_snapshots_no_smoothing"
    assert market["causal"]["browser_refit"] is False
    assert market["causal"]["future_fill"] is False
    assert market["feature_identity_status"] == "unavailable_not_persisted"
    assert market["factor_state_evidence"][0]["factor_id"] == "factor-a"
    assert market["linked_experiment_ids"] == ["exp-a"]


def test_factor_intelligence_lifecycle_state_metrics_provenance_and_weights(tmp_path: Path) -> None:
    root, model_id = _artifacts(tmp_path)
    projection = MarketFactorIntelligenceProjection((root,), research_workspace=_ResearchLinks())  # type: ignore[arg-type]
    index = {item["factor_id"]: item for item in projection.factors()["items"]}
    assert index["factor-a"]["status"] == "ACTIVE"
    assert index["factor-b"]["status"] == "DORMANT"
    assert index["factor-c"]["status"] == "REJECTED"
    factor = projection.factor("factor-a")["item"]
    assert factor["origin"] == "agent"
    assert factor["provenance"] == {"source": "fixture"}
    assert factor["global_metrics"]["coverage"] == 0.8
    assert factor["state_metrics"]["state_0"]["coverage"] == 0.9
    assert factor["cost_sensitive_economics"]["5.0"]["compounded_return"] == 0.01
    assert factor["similarity"]["factor-c"] == 0.1
    assert factor["novelty"] is None
    assert factor["novelty_status"] == "unavailable_not_persisted"
    assert factor["allocator_weights"][0]["weight"] == 0.7
    assert factor["allocator_weights"][0]["market_state_model_id"] == model_id
    assert factor["linked_experiments"][0]["experiment_id"] == "exp-a"
    assert factor["agent_decision_history"][0]["run_id"] == "run-a"


def test_market_factor_routes_are_get_only_and_never_grant_browser_authority(tmp_path: Path) -> None:
    root, model_id = _artifacts(tmp_path)
    app = create_workspace_app(report_paths=(root,), frontend_dir=None)
    with TestClient(app) as client:
        market = client.get(f"/api/v3/market-state/{model_id}")
        assert market.status_code == 200
        assert market.json()["browser_recomputation"] is False
        assert market.json()["causal_projection"] is True
        factor = client.get("/api/v3/factor-intelligence/factor-a")
        assert factor.status_code == 200
        assert factor.json()["browser_recomputation"] is False
        assert factor.json()["hidden_reasoning"] == "not_persisted_not_projected"
        assert client.post("/api/v3/market-state", json={}).status_code == 405
        assert client.post("/api/v3/factor-intelligence", json={}).status_code == 405


def test_cycle_projection_fails_closed_without_explicit_accepted_disposition(tmp_path: Path) -> None:
    root = tmp_path / "cycles"
    target = root / "cycle"
    target.mkdir(parents=True)
    (target / "campaign_result_attestation.json").write_text(json.dumps({"schema_version": "finagent.r4-campaign-result-attestation.v1", "campaign_result_id": "cycle-unreviewed", "candidate_decision": "NO_ADAPTIVE_CANDIDATE", "agent_value": "INCONCLUSIVE", "economic_evidence": {}, "agent_reliability": {}, "development_only": True, "alpha_authority": False, "paper_authority": False, "live_authority": False, "r5_eligible": False}), encoding="utf-8")
    projection = ResearchWorkspaceProjection(None, cycle_paths=(root,))
    cycle = projection.cycles()["items"][0]
    assert cycle["accepted"] is False
    assert cycle["review_status"] == "not_accepted"
    assert projection.cycles()["unresolved"][0]["reason"] == "accepted_review_disposition_missing_or_unrecognized"
    graph = projection.graph()
    assert not any(node["node_id"] == "terminal:cycle-unreviewed" for node in graph["nodes"])
    assert any(item["reason"] == "cycle_not_explicitly_accepted" for item in graph["unresolved"])



def test_experiment_attempt_order_is_persisted_not_lexical_and_repair_is_explicit(
    tmp_path: Path,
) -> None:
    database = tmp_path / "attempts.sqlite"
    connection = sqlite3.connect(database)
    connection.executescript("""
        CREATE TABLE agent_runs (
            run_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, decision_json TEXT
        );
        CREATE TABLE agent_tool_calls (
            run_id TEXT NOT NULL, sequence INTEGER NOT NULL, call_id TEXT NOT NULL,
            request_json TEXT NOT NULL, result_json TEXT
        );
    """)

    def add(run_id: str, started_at: str, call_id: str, repaired: str | None) -> None:
        payload = {
            "task": {"objective": "Attempt-order fixture"},
            "context": {
                "started_at": started_at,
                "metadata": {
                    "controller": "r4",
                    "project_id": "r4-research",
                    "thread_id": "thread-" + run_id,
                },
            },
        }
        connection.execute(
            "INSERT INTO agent_runs VALUES (?, ?, NULL)",
            (run_id, json.dumps(payload)),
        )
        result = {
            "outcome": "PORTFOLIO_EVALUATED",
            "experiment_id": "exp-shared",
            "factor_ids": ["factor-a", "factor-b"],
            "preferred_allocator": "equal_weight",
            "summary": {"arms": {"equal_weight": {"mean_fold_return_5bp": 0.01}}},
        }
        if repaired is not None:
            result["repaired_attempt_id"] = repaired
        connection.execute(
            "INSERT INTO agent_tool_calls VALUES (?, 1, ?, ?, ?)",
            (
                run_id,
                call_id,
                json.dumps(
                    {
                        "tool_name": "evaluate_portfolio",
                        "arguments": {
                            "factor_set_id": "set-a",
                            "allocator_proposal_id": "alloc-a",
                            "hypothesis_id": "hyp-a",
                        },
                    }
                ),
                json.dumps(
                    {
                        "status": "succeeded",
                        "error": "",
                        "output": {
                            "research_result": result,
                            "research_state": {"resources": {}},
                        },
                    }
                ),
            ),
        )

    add("z-run-earlier", "2026-09-08T05:00:00+00:00", "z-call", None)
    add("a-run-later", "2026-09-08T06:00:00+00:00", "a-call", "z-call")
    connection.commit()
    connection.close()

    detail = ResearchWorkspaceProjection(database, cycle_paths=()).experiment("exp-shared")
    assert detail["selection_semantics"] == "persisted_agent_audit_run_ordinal_then_tool_sequence"
    assert detail["attempt_count"] == 2
    assert [item["run_id"] for item in detail["attempts"]] == [
        "z-run-earlier",
        "a-run-later",
    ]
    assert detail["item"]["run_id"] == "a-run-later"
    assert detail["item"]["status"] == "repaired"
    assert detail["item"]["attempt_order"]["run_ordinal"] > detail["attempts"][0][
        "attempt_order"
    ]["run_ordinal"]

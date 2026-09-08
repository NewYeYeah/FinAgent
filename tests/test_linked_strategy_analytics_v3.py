from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from finagent.visualization.linked_strategy_analytics import LinkedStrategyAnalyticsProjection
from finagent.visualization.linked_strategy_analytics_routes import (
    attach_linked_strategy_analytics_routes,
)
from finagent.visualization.research_workspace import ResearchWorkspaceProjection


class _ResearchFixture(ResearchWorkspaceProjection):
    def experiments(self, *, run_id: str | None = None) -> dict[str, object]:
        item = {
            "identity": "exp-a",
            "experiment_id": "exp-a",
            "attempt_id": "call-exp-a",
            "run_id": "run-r4",
            "factor_ids": ["factor-a"],
            "status": "completed",
        }
        return {
            "schema_version": "fixture",
            "configured": True,
            "items": [item] if not run_id or run_id == "run-r4" else [],
            "read_only": True,
            "browser_recomputation": False,
            "hidden_reasoning": "not_persisted_not_projected",
        }


class _MarketFactorFixture:
    def markets(self) -> dict[str, object]:
        return {"items": [{"model_id": "market-model-a"}]}

    def factors(self) -> dict[str, object]:
        return {"items": [{"factor_id": "factor-a", "status": "ACTIVE"}]}


class _StrategyFixture:
    def catalog(self) -> dict[str, object]:
        return {
            "items": [
                {
                    "series_id": "strategy-series-a",
                    "portfolio_validation_id": "portfolio-a",
                    "source_program_result_id": "program-a",
                    "selected_feature_digests": ["factor-a"],
                    "alpha_model_ids": ["alpha-model-a"],
                }
            ]
        }


class _PortfolioItem:
    def to_dict(self) -> dict[str, object]:
        return {
            "portfolio_validation_id": "portfolio-a",
            "strategy_series_id": "strategy-series-a",
        }


class _PortfolioFixture:
    def item(self, validation_id: str) -> _PortfolioItem:
        if validation_id != "portfolio-a":
            raise KeyError(validation_id)
        return _PortfolioItem()


def _candidate_cycle(root: Path, *, candidate: bool = True, binding: bool = True) -> Path:
    target = root / "cycle"
    target.mkdir(parents=True)
    candidate_id = "candidate-a" if candidate else None
    (target / "campaign_result_attestation.json").write_text(
        json.dumps(
            {
                "schema_version": "finagent.r4-campaign-result-attestation.v1",
                "review_disposition": "R4_RESULT_ACCEPTED",
                "protocol_id": "protocol-a",
                "protocol_version": "r4-future-v1",
                "campaign_result_id": "cycle-candidate" if candidate else "cycle-no-candidate",
                "candidate_decision": (
                    "DEVELOPMENT_CANDIDATE_PROPOSED"
                    if candidate
                    else "NO_ADAPTIVE_CANDIDATE"
                ),
                "candidate_id": candidate_id,
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
                "r5_eligible": candidate,
            }
        ),
        encoding="utf-8",
    )
    if binding:
        (target / "linked_strategy_binding.json").write_text(
            json.dumps(
                {
                    "schema_version": "finagent.workbench-linked-strategy-binding.v1",
                    "binding_id": "binding-a",
                    "cycle_id": "cycle-candidate" if candidate else "cycle-no-candidate",
                    "candidate_id": "candidate-a",
                    "strategy_series_id": "strategy-series-a",
                    "portfolio_validation_id": "portfolio-a",
                    "market_state_model_id": "market-model-a",
                    "factor_ids": ["factor-a"],
                    "experiment_ids": ["exp-a"],
                    "agent_run_id": "run-r4",
                    "evidence_ids": ["evidence-a"],
                }
            ),
            encoding="utf-8",
        )
    return root


def _projection(root: Path) -> LinkedStrategyAnalyticsProjection:
    research = _ResearchFixture(None, cycle_paths=(root,))
    return LinkedStrategyAnalyticsProjection(
        research,
        _MarketFactorFixture(),  # type: ignore[arg-type]
        _StrategyFixture(),  # type: ignore[arg-type]
        _PortfolioFixture(),  # type: ignore[arg-type]
        evidence_ids=("evidence-a",),
    )


def test_candidate_binding_resolves_existing_strategy_portfolio_execution(tmp_path: Path) -> None:
    projection = _projection(_candidate_cycle(tmp_path))
    detail = projection.cycle("cycle-candidate")

    assert detail["mode"] == "candidate"
    assert detail["browser_recomputation"] is False
    assert detail["hidden_reasoning"] == "not_persisted_not_projected"
    assert detail["strategy_binding"]["status"] == "resolved"  # type: ignore[index]
    assert detail["combined_strategy_evidence"]["available"] is True  # type: ignore[index]
    assert detail["target_portfolio"]["available"] is True  # type: ignore[index]
    assert detail["execution_pnl"]["available"] is True  # type: ignore[index]
    assert detail["attribution"] == {  # type: ignore[index]
        "available": False,
        "evidence_id": None,
        "reason": "unavailable_not_persisted",
    }
    assert detail["candidate"]["factor_ids"] == ["factor-a"]  # type: ignore[index]
    assert detail["candidate"]["experiment_ids"] == ["exp-a"]  # type: ignore[index]
    links = detail["links"]  # type: ignore[assignment]
    assert "market_model=market-model-a" in links["market"]
    assert "factor=factor-a" in links["factors"][0]
    assert "experiment=exp-a" in links["experiments"][0]
    assert links["portfolio"].startswith("/portfolio/portfolio-a")
    assert links["execution"].startswith("/execution/portfolio-a")

    graph = projection.research_workspace.graph()
    kinds = {node["kind"] for node in graph["nodes"]}  # type: ignore[index]
    assert {"strategy_candidate", "strategy", "portfolio", "execution"} <= kinds
    relations = {edge["relation"] for edge in graph["edges"]}  # type: ignore[index]
    assert "explicit_persisted_binding" in relations
    assert "targets_portfolio" in relations
    assert "historical_execution" in relations


def test_current_real_no_candidate_cycle_is_first_class_and_unbound() -> None:
    research = _ResearchFixture(None, cycle_paths=("configs/research",))
    projection = LinkedStrategyAnalyticsProjection(
        research,
        _MarketFactorFixture(),  # type: ignore[arg-type]
        _StrategyFixture(),  # type: ignore[arg-type]
        _PortfolioFixture(),  # type: ignore[arg-type]
        evidence_ids=("evidence-a",),
    )
    detail = projection.cycle("r4-campaign-result-d32ec253d62eb4f9349896b0")

    assert detail["mode"] == "no_candidate"
    assert detail["cycle"]["terminal"] == "NO_ADAPTIVE_CANDIDATE"  # type: ignore[index]
    assert detail["cycle"]["agent_value"] == "INCONCLUSIVE"  # type: ignore[index]
    economic = detail["cycle"]["economic_evidence"]  # type: ignore[index]
    assert economic["deterministic_strategy_count"] == 20
    assert economic["complete_deterministic_strategy_count"] == 0
    assert detail["strategy_binding"]["status"] == "unavailable"  # type: ignore[index]
    assert detail["combined_strategy_evidence"]["available"] is False  # type: ignore[index]
    assert detail["target_portfolio"]["available"] is False  # type: ignore[index]
    assert detail["execution_pnl"]["available"] is False  # type: ignore[index]
    assert detail["r5"] == {"status": "not_started_not_eligible", "eligible": False}
    claims = detail["explanation"]["claims_not_supported"]  # type: ignore[index]
    assert "all_strategies_lost_money" in claims
    assert "market_state_failed" in claims
    assert "agent_proved_ineffective" in claims
    historical = detail["available_evidence"]["historical_strategy_series"]  # type: ignore[index]
    assert historical[0]["relation_to_cycle"] == "unbound_historical_evidence"


def test_no_candidate_cycle_ignores_candidate_binding(tmp_path: Path) -> None:
    root = _candidate_cycle(tmp_path, candidate=False, binding=True)
    research = _ResearchFixture(None, cycle_paths=(root,))
    cycles = research.cycles()
    item = cycles["items"][0]  # type: ignore[index]
    assert item["candidate_id"] is None
    assert item["strategy_binding"] is None
    assert any(
        value.get("reason") == "binding_ignored_for_accepted_no_candidate_cycle"
        for value in cycles["unresolved"]  # type: ignore[union-attr]
    )


def test_linked_strategy_routes_are_get_only(tmp_path: Path) -> None:
    projection = _projection(_candidate_cycle(tmp_path))
    app = FastAPI()
    attach_linked_strategy_analytics_routes(app, projection)
    client = TestClient(app)

    index = client.get("/api/v3/linked-strategy")
    assert index.status_code == 200
    assert index.json()["canonical_identity_only"] is True
    detail = client.get("/api/v3/linked-strategy/cycles/cycle-candidate")
    assert detail.status_code == 200
    assert detail.json()["browser_recomputation"] is False
    assert detail.json()["hidden_reasoning"] == "not_persisted_not_projected"
    assert client.post("/api/v3/linked-strategy", json={}).status_code == 405

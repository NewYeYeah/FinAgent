from __future__ import annotations

import json
from dataclasses import replace

import pytest

from finagent.agents.audit import SQLiteAgentAuditStore
from finagent.agents.r3_ledger import Reservation
from finagent.agents.r4_controller import proposal_context
from finagent.application.research_controller import open_research_session, run_research_session
from finagent.research.factor_library import FactorLibrary, FactorRegistration
from finagent.visualization.agent_projection import load_agent_run_projection
from tests.r4_controller_fixture import (
    Clock,
    ScriptedProvider,
    admission_fixture,
    comparison_steps,
    factor_steps,
    fixture_policy,
)


@pytest.fixture(scope="module")
def admitted(tmp_path_factory):
    root = tmp_path_factory.mktemp("r4-controller")
    admission, inputs = admission_fixture(root / "inputs")
    return root, admission, inputs


@pytest.mark.parametrize("scenario", ["selection", "proposal"])
def test_offline_provider_runtime_core_ledger_audit_loop(admitted, scenario):
    root, admission, inputs = admitted
    ids = [f.factor_id for f in inputs["factors"]]
    steps = comparison_steps(ids) if scenario == "selection" else factor_steps(admission, ids)
    provider = ScriptedProvider(steps)
    audit = SQLiteAgentAuditStore(root / f"{scenario}-audit.sqlite")
    runtime = open_research_session(
        admission,
        root / scenario,
        run_id=scenario,
        objective="Inspect controlled development hypotheses",
        provider=provider,
        provider_id="scripted-offline",
        model_id="fixture",
        audit=audit,
        policy=fixture_policy(),
        clock=Clock(),
    )
    result = run_research_session(runtime)
    assert result["terminal"] == (
        "DEVELOPMENT_CANDIDATE_PROPOSED" if scenario == "selection" else "NO_CANDIDATE_RECOMMENDED"
    ), runtime.ledger.journal()
    assert len(provider.requests) == len(steps)
    assert runtime.ledger.snapshot()["evaluation_calls"] == 2
    events = audit.list_events(scenario)
    assert len(events) == 2 + len(steps) * 3
    projection = load_agent_run_projection(audit.path, scenario)
    assert projection.status == "completed"
    journal = runtime.ledger.journal()
    portfolios = [r["result"] for r in journal if r["state"] == "PORTFOLIO_EVALUATED"]
    assert len(portfolios) == (2 if scenario == "selection" else 1), journal
    assert len(portfolios[0]["summary"]["arms"]) == 5
    assert portfolios[0]["evaluation_mode"] == "adaptive_development_retrospective"
    assert portfolios[0]["factor_was_known_at_historical_market_time"] is False
    assert all(
        portfolios[0][k] is False
        for k in (
            "independent_confirmation",
            "alpha_authority",
            "paper_authority",
            "live_authority",
        )
    )
    assert result["result"]["r5_eligible"] is False
    if scenario == "selection":
        assert len([r for r in journal if r["state"] == "DUPLICATE_EXPERIMENT"]) == 1
        assert result["result"]["allocator"]["allocator"] == "rolling_net_return"
        assert all(p["preferred_allocator"] == "regime_conditional" for p in portfolios)
    assert portfolios[0]["resource_cost"] == {
        "evaluation_slots": 1,
        "tokens": 100,
        "cost_microusd": 10,
    }
    from fastapi.testclient import TestClient

    from finagent.visualization.workbench_api import create_workspace_app

    client = TestClient(
        create_workspace_app(
            report_paths=(root / "empty-reports",), agent_audit_path=audit.path, frontend_dir=None
        )
    )
    before = audit.path.read_bytes()
    detail = client.get(f"/api/v3/agent/runs/{scenario}").json()
    assert detail["run"]["research"]["candidate"]["outcome"] == result["terminal"]
    stream = client.get(f"/api/v3/streams/agent/runs/{scenario}?once=true")
    envelope = json.loads(
        next(line[6:] for line in stream.text.splitlines() if line.startswith("data: "))
    )
    ag_events = envelope["projection"]["ag_ui_events"]
    assert ag_events[0]["type"] == "RUN_STARTED" and ag_events[-1]["type"] == "RUN_FINISHED"
    assert len([e for e in ag_events if e["type"] == "TOOL_CALL_RESULT"]) == len(steps)
    assert (
        next(e for e in ag_events if e["type"] == "STATE_SNAPSHOT")["snapshot"]["resources"][
            "evaluations"
        ]
        == 2
    )
    assert not any("REASONING" in e["type"] or e["type"] == "RAW" for e in ag_events)
    assert client.post(f"/api/v3/agent/runs/{scenario}").status_code == 405
    assert audit.path.read_bytes() == before
    if scenario == "proposal":
        proposed = next(r["result"]["proposal"] for r in journal if r["state"] == "VALIDATED")
        library = FactorLibrary(root / scenario / "factor_library.sqlite", read_only=True)
        factor = library.get(proposed["factor_id"])
        library.close()
        assert factor["status"] == "TESTING"
        assert factor["created_at"] == proposed["proposed_at"]
        assert proposed["proposed_at"] > inputs["folds"][-1].evaluation.end.isoformat()
        assert proposed["proposal_context_id"]
        assert json.loads(factor["provenance"]["proposal_envelope"]) == proposed
        assert proposed["visible_history_id"] == proposed["proposal_context_id"]
        assert proposed["proposal_id"] and proposed["factor_definition_digest"]
        assert proposed["factor_id"] in portfolios[0]["factor_ids"]
        report = json.loads((root / scenario / portfolios[0]["artifact_ref"]).read_text())
        assert (
            report["historically_predeclared"] is False
            and report["adaptive_search_exposed"] is True
        )
        assert report["admission_semantics"] == "ADAPTIVE_RETROSPECTIVE"
        row = next(r for r in journal if r["state"] == "VALIDATED")
        visible = proposal_context(
            runtime.ledger, Reservation(row["request_id"], row["slot"], row["ordinal"], None)
        )
        assert visible["visible_history_id"] == proposed["visible_history_id"]
        assert portfolios[0]["experiment_id"] not in proposed["visible_experiment_ids"]
        assert "PORTFOLIO_EVALUATED" not in row["context_json"]
        library = FactorLibrary(root / scenario / "factor_library.sqlite")
        try:
            with pytest.raises(ValueError):
                library.register(
                    replace(
                        FactorRegistration.from_dict(factor), hypothesis="Changed after evaluation"
                    )
                )
            with pytest.raises(ValueError):
                library.record_evaluation(
                    {
                        **library.evaluations(proposed["factor_id"])[0],
                        "independent_confirmation": True,
                    }
                )
        finally:
            library.close()

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from finagent.agents.r3_contracts import decode_action
from finagent.agents.r3_runtime import ResearchReply
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.research import us_r3_completion as completion
from finagent.research.us_r3_economic_campaign import freeze_campaign
from finagent.research.us_r3_economics import EconomicPolicy
from tests.test_us_r3_economic_campaign import fixture_inputs


def completion_fixture(root: Path) -> Path:
    source, calendar_path, plan_path, evidence_path = fixture_inputs(
        root / "inputs", five_minute=True
    )
    expanded = root / "expanded.parquet"
    with duckdb.connect() as connection:
        connection.execute(
            """CREATE TABLE expanded AS
            SELECT * EXCLUDE (d, a) REPLACE (
                session_date + CAST(d AS INTEGER) AS session_date,
                'XNYS:' || CAST(session_date + CAST(d AS INTEGER) AS VARCHAR) AS session_id,
                research_asset_id || CAST(a AS VARCHAR) AS research_asset_id,
                event_time + d * INTERVAL '1 day' AS event_time,
                available_at + d * INTERVAL '1 day' AS available_at,
                source_available_at + d * INTERVAL '1 day' AS source_available_at)
            FROM read_parquet(?) CROSS JOIN range(24) AS days(d)
            CROSS JOIN range(6) AS assets(a) WHERE session_date = DATE '2025-01-02'
        """,
            [str(source)],
        )
        connection.execute("COPY expanded TO ? (FORMAT PARQUET)", [str(expanded)])
        count = connection.execute(
            "SELECT count(*) FROM read_parquet(?)", [str(expanded)]
        ).fetchone()[0]
    sessions = tuple(
        TradingSession(
            date(2025, 1, 2) + timedelta(days=d),
            datetime(2025, 1, 2, 14, 30, tzinfo=UTC) + timedelta(days=d),
            datetime(2025, 1, 2, 21, tzinfo=UTC) + timedelta(days=d),
        )
        for d in range(24)
    )
    calendar = TradingCalendarEvidence("XNYS", "America/New_York", "synthetic", "v1", sessions)
    calendar_path.write_text(json.dumps({"passed": True, "evidence": calendar.to_dict()}))
    plan = json.loads(plan_path.read_text())
    plan["calendar_id"] = calendar.calendar_id
    plan_path.write_text(json.dumps(plan))
    evidence = json.loads(evidence_path.read_text())
    evidence["row_count"] = count
    evidence_path.write_text(json.dumps(evidence))
    economic = root / "economic.json"
    freeze_campaign(
        expanded,
        calendar_path,
        plan_path,
        evidence_path,
        economic,
        start=sessions[0].session_date,
        end=sessions[-1].session_date,
        policy=EconomicPolicy(execution_profile="pending_exit_5m"),
    )
    config = root / "llm.toml"
    config.write_text(
        '[llm]\ndefault_profile="test"\n[llm.profiles.test]\nprovider="deepseek"\nmodel="deepseek-v4-pro"\nbase_url="https://api.deepseek.com"\nsecret_id="unused"\n'
    )
    protocol = root / "completion.json"
    completion.freeze_completion(economic, config, protocol)
    return protocol


class ScriptedProvider:
    def __init__(self, feedback=False):
        self.calls = 0
        self.feedback = feedback

    def respond(self, request):
        context = json.loads(request.context_json)
        action = json.loads(completion.baseline_action("manual", 0, context["slot"]))
        if self.feedback and context["attempt"] == 1:
            action["tool"] = "validate_factor"
        elif self.feedback and context["attempt"] == 2:
            action = {
                "schema_version": "finagent.us-r3-agent-action.v2",
                "tool": "evaluate_development",
                "arguments": {"candidate_id": context["feedback"][-1]["candidate_id"]},
            }
        elif self.feedback:
            assert any(r["outcome"] == "DEVELOPMENT_EVALUATED" for r in context["feedback"])
        self.calls += 1
        return ResearchReply(json.dumps(action), 100, 100)


def test_complete_synthetic_pilot_freezes_all_runs_and_resumes_without_calls(tmp_path, monkeypatch):
    protocol = completion_fixture(tmp_path)
    providers = []

    def factory(method, run):
        provider = ScriptedProvider(feedback=method == "feedback_agent")
        providers.append(provider)
        return provider

    result = completion.run_completion(protocol, tmp_path / "out", provider_factory=factory)
    assert result["slot_denominator"] == 36
    assert result["valid_slots"] == 36
    assert result["external_model_called"] is False
    assert result["confirmation_terminal"] == "INSUFFICIENT_INDEPENDENT_EVIDENCE"
    assert len(result["assessments"]) == 24
    assert all(len(m["all_run_outer_returns"]) == 3 for m in result["method_comparisons"])
    assert all(result[k] is False for k in completion.AUTHORITY)
    assert sum(p.calls for p in providers) == 36
    for i in range(3):
        run = json.loads((tmp_path / f"out/runs/feedback_agent-{i}.json").read_text())
        assert run["ledger"]["evaluation_calls"] == 3
    model = json.loads((tmp_path / "out/frozen_model.json").read_text())
    assert len(model["members"]) == 12
    monkeypatch.setattr(completion.AdmittedEvaluator, "_frames", lambda self: pytest.fail("rescan"))
    resumed = completion.run_completion(
        protocol, tmp_path / "out", provider_factory=lambda *a: pytest.fail("recall")
    )
    assert resumed["resumed"] is True
    assert resumed["evidence_id"] == result["evidence_id"]
    run_path = tmp_path / "out/runs/manual-0.json"
    run_path.write_text(run_path.read_text().replace('"manual"', '"corrupted"'))
    with pytest.raises(ValueError):
        completion.run_completion(protocol, tmp_path / "out", provider_factory=factory)


def test_development_queries_only_admitted_dates_and_cache_rejects_tampering(tmp_path):
    protocol = json.loads(completion_fixture(tmp_path).read_text())
    economic = json.loads(Path(protocol["economic_protocol"]["path"]).read_text())
    evaluator = completion.AdmittedEvaluator(
        economic, protocol["splits"]["development"], tmp_path / "cache", "test"
    )
    action = decode_action(completion.baseline_action("manual", 0, 0))
    result = evaluator.calculate(action.proposal.graph)
    assert [d[0] for d in evaluator.frames] == protocol["splits"]["development"]
    assert len(evaluator.frames[0][1]) == 24
    assert result["summary"]["full_period_evaluable"] is True
    assert evaluator.calculate(action.proposal.graph)["evidence_id"] == result["evidence_id"]
    cache = next((tmp_path / "cache").glob("*.json"))
    corrupted = json.loads(cache.read_text())
    corrupted["cost_bps"] = 0
    cache.write_text(json.dumps(corrupted))
    with pytest.raises(ValueError):
        evaluator.calculate(action.proposal.graph)

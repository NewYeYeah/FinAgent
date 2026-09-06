from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from finagent.agents.audit import SQLiteAgentAuditStore
from finagent.agents.r3_ledger import Reservation
from finagent.agents.r3_runtime import RequiredAuditFailure
from finagent.agents.r4_controller import proposal_context
from finagent.application.adaptive_portfolio import run_adaptive_portfolio
from finagent.application.research_controller import open_research_session, run_research_session
from finagent.application.research_controller_host import R4ResearchHost
from finagent.research.adaptive_walkforward import validate_walkforward
from finagent.research.factor_library import FactorLibrary, FactorRegistration, FactorStatus
from finagent.research.r4_feedback import compare_feedback
from tests.r4_controller_fixture import (
    Clock,
    ScriptedProvider,
    action,
    admission_fixture,
    factor_steps,
    fixture_policy,
    selection_steps,
)


@pytest.fixture(scope="module")
def admission(tmp_path_factory):
    return admission_fixture(tmp_path_factory.mktemp("controller-boundary") / "input")[0]


def session(tmp_path, admission, steps, policy=None, clock=None):
    provider = ScriptedProvider(steps)
    audit = SQLiteAgentAuditStore(tmp_path / "audit.sqlite")
    runtime = open_research_session(
        admission,
        tmp_path / "run",
        run_id="test-run",
        objective="Bounded development engineering test",
        provider=provider,
        provider_id="scripted-offline",
        model_id="fixture",
        audit=audit,
        policy=policy or fixture_policy(),
        clock=clock or Clock(),
    )
    return runtime, provider, audit


def ids(admission):
    library = FactorLibrary(admission.seed_library, read_only=True)
    try:
        return [f["factor_id"] for f in library.list_factors()]
    finally:
        library.close()


def step(runtime, index):
    return runtime.step(f"research-step-{index:04d}", 0)


@pytest.mark.parametrize(
    "wire",
    [
        "{invalid JSON: private_scratchpad}",
        action("shell", command="echo forbidden"),
        action("propose_allocator", allocator="equal_weight", lookback_sessions=137),
        action("propose_allocator", allocator="arbitrary"),
        action(
            "evaluate_portfolio",
            factor_set_id="x",
            allocator_proposal_id="y",
            hypothesis_id="h",
            cost_grid=[2.3],
        ),
        action(
            "evaluate_portfolio",
            factor_set_id="x",
            allocator_proposal_id="y",
            hypothesis_id="h",
            holding_bars=17,
        ),
        action("allocate_budget", hypothesis_id="h", maximum_evaluations=100),
        action("propose_factor_set", factor_ids=["unknown-a", "unknown-b"], hypothesis_id="h"),
        action(
            "finalize_candidate",
            recommendation="candidate",
            factor_set_id="unknown",
            allocator_proposal_id="unknown",
            experiment_ids=[],
            decision="Claim success",
        ),
        action(
            "finalize_candidate",
            recommendation="none",
            factor_set_id=None,
            allocator_proposal_id=None,
            experiment_ids=[],
            decision="No candidate",
            alpha_authority=True,
        ),
        action(
            "record_decision",
            critique="explicit",
            next_action="stop",
            hidden_reasoning="private_scratchpad",
        ),
    ],
)
def test_adversarial_actions_fail_closed_and_remain_in_history(tmp_path, admission, wire):
    runtime, provider, audit = session(
        tmp_path, admission, [wire, action("inspect_experiment_history", offset=0)]
    )
    rejected = step(runtime, 0)
    assert rejected["outcome"] == "REJECTED"
    history = step(runtime, 1)
    assert history["attempt_counts"] == {"REJECTED": 1}
    assert history["attempts"][0]["tokens"] == 100
    assert runtime.ledger.snapshot()["evaluation_calls"] == 0
    assert len(audit.list_events("test-run")) == 7
    assert "private_scratchpad" not in json.dumps(runtime.ledger.journal())
    assert "private_scratchpad" not in repr(audit.list_events("test-run"))
    assert len(provider.requests) == 2


def test_static_admission_still_rejects_post_train_proposals(tmp_path, admission):
    library = FactorLibrary(admission.seed_library, read_only=True)
    factors = tuple(FactorRegistration.from_dict(f) for f in library.list_factors())
    library.close()
    validate_walkforward(factors, admission.folds, admission.economics)
    current = (replace(factors[0], created_at=admission.admitted_at), *factors[1:])
    with pytest.raises(ValueError, match="before.*train|preexist|TRAIN|training"):
        run_adaptive_portfolio(
            admission.source,
            current,
            admission.folds,
            tmp_path / "static",
            economics=admission.economics,
        )
    assert not (tmp_path / "static" / "request.json").exists()


def test_proposal_context_is_frozen_visible_history_not_future_actions(tmp_path, admission):
    proposal_wire = factor_steps(admission, ids(admission))[1]
    runtime, provider, _audit = session(
        tmp_path,
        admission,
        [
            action("inspect_market_state"),
            proposal_wire,
            action(
                "record_decision",
                critique="Future explicit critique",
                next_action="Future experiment",
            ),
            proposal_wire,
        ],
    )
    step(runtime, 0)
    proposed = step(runtime, 1)["proposal"]
    reservation = Reservation("research-step-0001", 0, 2, None)
    frozen = proposal_context(runtime.ledger, reservation)
    assert proposed["proposal_context_id"] == frozen["proposal_context_id"]
    step(runtime, 2)
    assert proposal_context(runtime.ledger, reservation) == frozen
    assert step(runtime, 3)["outcome"] == "DUPLICATE_PROPOSAL"
    assert step(runtime, 1)["proposal"] == proposed
    assert len(provider.requests) == 4
    host = runtime._capabilities.host
    factor = FactorRegistration.from_dict(host.factor(proposed["factor_id"]))
    at = datetime.fromtimestamp(runtime._clock(), UTC)
    adaptive = host.development_admission((factor,), at)
    adaptive.validate((factor,), admission.folds[-1].evaluation.end)
    assert adaptive.to_dict()["factor_was_known_at_historical_market_time"] is False
    assert factor.created_at == datetime.fromisoformat(proposed["proposed_at"])
    assert factor.created_at > admission.folds[-1].evaluation.end
    changed = dict(proposed, proposed_at=admission.folds[0].train.start.isoformat())
    with pytest.raises(ValueError, match="provenance"):
        replace(adaptive, proposal_envelopes_json=json.dumps({factor.factor_id: changed})).validate(
            (factor,), admission.folds[-1].evaluation.end
        )
    assert frozen["history_cutoff"] == "research-step-0000"
    assert frozen["visible_experiment_ids"] == []
    assert all(len(r.context_json.encode()) <= 16384 for r in provider.requests)


def test_repaired_factor_and_retired_selection_are_accounted(tmp_path, admission):
    proposal = json.loads(factor_steps(admission, ids(admission))[1])
    bad = json.loads(json.dumps(proposal))
    bad["arguments"]["nodes"][0]["operator"] = "ARBITRARY_PYTHON"
    proposal["arguments"]["repairs_request_id"] = "research-step-0000"
    runtime, _, _ = session(
        tmp_path,
        admission,
        [
            json.dumps(bad),
            json.dumps(proposal),
            lambda c: action(
                "propose_factor_set", factor_ids=ids(admission)[:2], hypothesis_id="h"
            ),
        ],
    )
    assert step(runtime, 0)["outcome"] == "REJECTED"
    assert step(runtime, 1)["repaired_attempt_id"] == "research-step-0000"
    host = runtime._capabilities.host
    lib = FactorLibrary(host.library_path)
    factor_id = ids(admission)[0]
    status = lib.get(factor_id)["status"]
    if status == "PROPOSED":
        lib.transition(
            factor_id,
            FactorStatus.TESTING,
            at=admission.admitted_at,
            actor="fixture",
            reason="fixture",
        )
    lib.transition(
        factor_id, FactorStatus.RETIRED, at=admission.admitted_at, actor="fixture", reason="fixture"
    )
    lib.close()
    assert step(runtime, 2)["code"] == "terminal_factor_selection_denied"


def test_negative_hypothesis_requires_explicit_graph_direction(tmp_path, admission):
    wire = json.loads(factor_steps(admission, ids(admission))[1])
    wire["arguments"]["hypothesis"]["direction"] = "NEGATIVE"
    runtime, _, _ = session(tmp_path, admission, [json.dumps(wire)])
    assert step(runtime, 0)["code"] == "positive_graph_direction_required_use_explicit_NEGATE"
    assert runtime.ledger.snapshot()["evaluation_calls"] == 0
    assert len(runtime._capabilities.host.factors()) == len(ids(admission))


def test_evaluation_failure_duplicate_and_budget_are_durable(tmp_path, admission, monkeypatch):
    steps = selection_steps(ids(admission))[:5]
    steps += [
        steps[4],
        action("inspect_experiment_history", offset=0),
        action("allocate_budget", hypothesis_id="next"),
    ]
    calls = []

    def fail(*args):
        calls.append(1)
        raise RuntimeError("untrusted provider secret")

    monkeypatch.setattr(R4ResearchHost, "evaluate_portfolio", fail)
    runtime, _, audit = session(tmp_path, admission, steps, fixture_policy(maximum_evaluations=1))
    for i in range(4):
        step(runtime, i)
    assert step(runtime, 4)["outcome"] == "TOOL_FAILED"
    assert step(runtime, 5)["outcome"] == "DUPLICATE_EXPERIMENT"
    history = step(runtime, 6)
    assert history["attempt_counts"]["TOOL_FAILED"] == 1
    assert history["attempt_counts"]["DUPLICATE_EXPERIMENT"] == 1
    assert step(runtime, 7)["code"] == "evaluation_budget_exhausted"
    assert runtime.ledger.snapshot()["evaluation_calls"] == len(calls) == 1
    assert "untrusted provider secret" not in json.dumps(runtime.ledger.journal())
    assert len(audit.replay_requests("test-run")) == len(steps)


def test_no_result_visible_until_evaluation_completion(tmp_path, admission, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    steps = selection_steps(ids(admission))[:5]

    def wait_then_fail(*args):
        entered.set()
        assert release.wait(5)
        raise ValueError("controlled failure")

    monkeypatch.setattr(R4ResearchHost, "evaluate_portfolio", wait_then_fail)
    runtime, provider, audit = session(tmp_path, admission, steps)
    for i in range(4):
        step(runtime, i)
    result = []
    worker = threading.Thread(target=lambda: result.append(step(runtime, 4)))
    worker.start()
    assert entered.wait(5)
    try:
        row = runtime.ledger.journal()[-1]
        assert row["state"] == "PENDING" and row["result"] is None
        assert runtime._capabilities.context(runtime.ledger)["latest_experiment"] is None
        assert not any(
            e.event_type.value == "tool_finished"
            and e.call_id == audit.replay_requests("test-run")[-1].call_id
            for e in audit.list_events("test-run")
        )
        assert len(provider.requests) == 5
    finally:
        release.set()
        worker.join(5)
    assert result[0]["outcome"] == "TOOL_FAILED"
    assert result[0]["completed_at"] > row["action_time"]


@pytest.mark.parametrize(
    "failure", [RuntimeError("private provider failure"), TimeoutError("provider deadline")]
)
def test_provider_uncertainty_stops_and_keeps_worst_case_accounting(tmp_path, admission, failure):
    runtime, provider, audit = session(tmp_path, admission, [failure])
    result = step(runtime, 0)
    assert result["outcome"] == "PROVIDER_FAILED_UNCERTAIN"
    assert runtime.ledger.snapshot()["charged_tokens"] == runtime.policy.tokens_per_call
    assert step(runtime, 0) == result
    assert len(provider.requests) == 1
    assert audit.list_events("test-run")[-1].event_type.value == "run_finished"


def test_actual_evaluator_timeout_does_not_admit_late_result(tmp_path, admission, monkeypatch):
    release = threading.Event()

    def slow(*args):
        release.wait(3)
        return {"late": True}

    monkeypatch.setattr(R4ResearchHost, "evaluate_portfolio", slow)
    runtime, provider, _ = session(
        tmp_path,
        admission,
        selection_steps(ids(admission)),
        fixture_policy(call_timeout_seconds=0.2),
    )
    try:
        for i in range(4):
            step(runtime, i)
        result = step(runtime, 4)
        assert result["outcome"] == "EVALUATOR_TIMEOUT"
        assert runtime.ledger.snapshot()["evaluation_calls"] == 1
    finally:
        release.set()
    assert runtime._capabilities.context(runtime.ledger)["latest_experiment"] is None
    assert step(runtime, 4) == result
    assert len(provider.requests) == 5


def test_resume_is_idempotent_and_detects_audit_drift(tmp_path, admission):
    clock = Clock()
    steps = [action("inspect_market_state"), selection_steps(ids(admission))[-1]]
    runtime, provider, audit = session(tmp_path, admission, steps, clock=clock)
    original = step(runtime, 0)
    resumed, second, _ = session(tmp_path, admission, steps, clock=clock)
    assert step(resumed, 0) == original
    assert second.requests == []
    assert run_research_session(resumed)["terminal"] == "NO_CANDIDATE_RECOMMENDED"
    assert len(second.requests) == 1
    assert run_research_session(resumed)["result"]["outcome"] == "NO_CANDIDATE_RECOMMENDED"
    assert len(provider.requests) == 1
    before = resumed.ledger.journal(), audit.list_events("test-run")
    assert step(resumed, 99)["outcome"] == "NO_CANDIDATE_RECOMMENDED"
    assert before == (resumed.ledger.journal(), audit.list_events("test-run"))
    assert len(second.requests) == 1
    with sqlite3.connect(audit.path) as db:
        db.execute("DELETE FROM agent_audit_events WHERE event_type='tool_finished'")
    with pytest.raises(RequiredAuditFailure):
        step(resumed, 0)
    assert resumed.ledger.snapshot()["status"] == "AUDIT_FAILED"


@pytest.mark.parametrize(
    "method", ["record_tool_request", "record_policy_decision", "record_tool_result"]
)
def test_required_audit_failure_stops_later_actions(tmp_path, admission, monkeypatch, method):
    runtime, provider, audit = session(
        tmp_path, admission, [action("inspect_market_state"), action("inspect_market_state")]
    )

    def fail(*args, **kwargs):
        raise OSError("disk write failed")

    monkeypatch.setattr(audit, method, fail)
    try:
        first = step(runtime, 0)
        assert first["outcome"] == "AUDIT_FAILED"
    except RequiredAuditFailure:
        pass
    with pytest.raises(RequiredAuditFailure):
        step(runtime, 1)
    assert len(provider.requests) == 1
    assert runtime.ledger.snapshot()["status"] == "AUDIT_FAILED"


def test_tool_budget_denial_is_audited_without_provider_call(tmp_path, admission):
    runtime, provider, audit = session(
        tmp_path,
        admission,
        [action("inspect_market_state")],
        fixture_policy(maximum_attempts=1, maximum_attempts_per_slot=1),
    )
    result = run_research_session(runtime)
    assert result["terminal"] == "SLOT_ATTEMPTS_EXHAUSTED"
    assert len(runtime.ledger.journal()) == 2 and len(provider.requests) == 1
    assert runtime.ledger.journal()[-1]["charged_tokens"] == 0
    assert audit.list_events("test-run")[-1].event_type.value == "run_finished"


def test_incompatible_experiments_never_receive_financial_ranking():
    common = {
        "factor_ids": ["a", "b"],
        "preferred_allocator": "equal_weight",
        "resource_cost": {"evaluation_slots": 1},
    }
    result = compare_feedback(
        [
            {**common, "experiment_id": "a", "compatibility_id": "source-a"},
            {**common, "experiment_id": "b", "compatibility_id": "source-b"},
        ]
    )
    assert result["outcome"] == "NOT_COMPARABLE"
    assert all(e["metrics_5bp"] is None for e in result["experiments"])


def test_lifecycle_decisions_use_library_transitions_and_keep_actor_evidence(tmp_path, admission):
    factor_id = ids(admission)[0]
    runtime, provider, audit = session(
        tmp_path,
        admission,
        [
            action(
                "retire_hypothesis",
                factor_id=factor_id,
                status=status,
                reason="Pause and reconsider the admitted development hypothesis",
                experiment_ids=[],
            )
            for status in ("DORMANT", "TESTING")
        ],
    )
    host = runtime._capabilities.host
    library = FactorLibrary(host.library_path)
    try:
        library.transition(
            factor_id,
            FactorStatus.TESTING,
            at=admission.admitted_at,
            actor="fixture",
            reason="Admitted development factor",
        )
    finally:
        library.close()
    for index, status in enumerate(("DORMANT", "TESTING")):
        assert step(runtime, index)["outcome"] == "LIFECYCLE_DECIDED"
        row = host.factor(factor_id)
        assert row["status"] == status
        transition = row["lifecycle"][-1]
        assert transition["actor"] == "agent_controller"
        assert json.loads(transition["reason"])["run_id"] == "test-run"
        assert json.loads(transition["reason"])["experiment_ids"] == []
    assert len(provider.requests) == len(audit.replay_requests("test-run")) == 2
    assert runtime.ledger.snapshot()["evaluation_calls"] == 0


def test_resume_rejects_explicit_state_drift_and_uncertain_pending_work(tmp_path, admission):
    runtime, provider, audit = session(
        tmp_path / "drift", admission, [action("inspect_market_state")]
    )
    step(runtime, 0)
    with sqlite3.connect(audit.path) as db:
        call_id, raw = db.execute("SELECT call_id,result_json FROM agent_tool_calls").fetchone()
        payload = json.loads(raw)
        payload["output"]["research_state"]["resources"]["remaining_evaluations"] = 999
        db.execute(
            "UPDATE agent_tool_calls SET result_json=? WHERE call_id=?",
            (json.dumps(payload), call_id),
        )
    with pytest.raises(RequiredAuditFailure):
        step(runtime, 1)
    assert len(provider.requests) == 1
    clock = Clock()
    pending, _, _ = session(tmp_path / "pending", admission, [], clock=clock)
    pending._observer.before_step(pending.ledger)
    pending.ledger.reserve("uncertain-request", 0, now=clock())
    resumed, provider, _ = session(tmp_path / "pending", admission, [], clock=clock)
    with pytest.raises(RequiredAuditFailure):
        step(resumed, 0)
    assert not provider.requests
    assert resumed.ledger.snapshot()["charged_tokens"] == resumed.policy.tokens_per_call

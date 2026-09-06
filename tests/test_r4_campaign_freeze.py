"""Freeze -> verify -> existing runtime/core, exclusively synthetic financial data."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from finagent.agents.audit import SQLiteAgentAuditStore
from finagent.agents.r3_contracts import canonical_json
from finagent.agents.r4_contracts import AUTHORITY
from finagent.agents.r4_provider_admission import ProviderAdmission, provider_binding
from finagent.application.r4_campaign import (
    freeze_campaign,
    run_campaign,
    runtime_policy,
    verify_campaign,
)
from finagent.application.research_controller import open_research_session
from finagent.research.r4_campaign_protocol import (
    AdaptiveStrategySpec,
    R4MatchedComparisonProtocol,
    assess_campaign,
    matched_protocol,
)
from tests.r4_controller_fixture import (
    Clock,
    ScriptedProvider,
    admission_fixture,
    factor_steps,
    selection_steps,
)


def provider_fixture():
    binding = provider_binding(Path("configs/llm.toml"))
    return ProviderAdmission(
        canonical_json(
            {
                "status": "ACCEPTED",
                "fixture_only": True,
                "binding": binding,
                "admitted_at": "2026-09-06T00:00:00+00:00",
                "probe_scope": "non_research_no_market_no_objective",
                "admission_evidence_id": "synthetic-probe",
                "receipt": {
                    "model_id": "deepseek-v4-pro",
                    "response_id": "fixture-response",
                    "system_fingerprint": "fixture",
                    "quota_available": True,
                    "cost_microusd": math.ceil(100 * 1.32 + 20 * 3.96),
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "total_tokens": 120,
                        "prompt_cache_hit_tokens": 0,
                        "prompt_cache_miss_tokens": 100,
                    },
                },
                **AUTHORITY,
            }
        )
    )


def current_clock():
    clock = Clock()
    clock.value = datetime.now(UTC).timestamp()
    return clock


@pytest.fixture(scope="module")
def admitted(tmp_path_factory):
    admission, inputs = admission_fixture(tmp_path_factory.mktemp("campaign-inputs") / "inputs")
    return admission, inputs, provider_fixture()


def test_fixture_campaign_full_path_and_idempotence(admitted, tmp_path):
    admission, inputs, provider = admitted
    output = tmp_path / "campaign"
    frozen = freeze_campaign(admission, provider, output, fixture=True)
    ids = [f.factor_id for f in inputs["factors"]]
    instances = []

    def factory(run_id):
        steps = (
            selection_steps(ids) if run_id.startswith("selection") else factor_steps(admission, ids)
        )
        instance = ScriptedProvider(steps)
        instances.append(instance)
        return instance

    result = run_campaign(
        output,
        admission,
        provider,
        accepted_freeze_id=frozen.freeze_id,
        fixture_provider_factory=factory,
        clock=current_clock(),
    )
    assert result["completed_runs"] == [
        "deterministic",
        "selection-01",
        "selection-02",
        "selection-03",
        "discovery-01",
        "discovery-02",
        "discovery-03",
    ]
    assert result["assessment"]["candidate_decision"] != "SYSTEM_FAILURE"
    assert len(instances) == 6
    assert result["resources"]["deterministic"]["charged_tokens"] == 0
    assert result["resources"]["deterministic"]["charged_cost_microusd"] == 0
    assert len([c for c in result["candidates"] if c["run_id"] == "deterministic"]) == 20
    assert all(c["runtime_agent_dependence"] == 0 for c in result["candidates"])
    assert result["alpha_authority"] is False
    before = (output / "campaign_result.json").read_bytes()
    resumed = run_campaign(
        output,
        admission,
        provider,
        accepted_freeze_id=frozen.freeze_id,
        fixture_provider_factory=lambda _: pytest.fail("idempotent replay must not call provider"),
        clock=current_clock(),
    )
    assert resumed == result
    assert (output / "campaign_result.json").read_bytes() == before
    for run in result["completed_runs"][1:]:
        assert (output / run / "audit.sqlite").is_file()
        assert (output / run / "research.sqlite").is_file()


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "deepseek-v4-flash"),
        ("base_url", "https://example.invalid"),
        ("thinking", True),
        ("max_attempts", 2),
        ("name", "wrong-profile"),
    ],
)
def test_provider_profile_mismatch(monkeypatch, field, value):
    from finagent.agents.providers.config import load_llm_profile

    p = load_llm_profile(Path("configs/llm.toml"), profile_name="r4_deepseek_v4_pro")
    monkeypatch.setattr(
        "finagent.agents.r4_provider_admission.load_llm_profile",
        lambda *a, **k: replace(p, **{field: value}),
    )
    with pytest.raises(ValueError, match="PROVIDER_ADMISSION_FAILED"):
        provider_binding(Path("configs/llm.toml"))


@pytest.mark.parametrize(
    "change", ["missing_usage", "wrong_total", "wrong_model", "wrong_cost", "quota", "not_accepted"]
)
def test_provider_receipt_must_be_verified(change):
    row = provider_fixture().to_dict()
    if change == "missing_usage":
        del row["receipt"]["usage"]["prompt_tokens"]
    elif change == "wrong_total":
        row["receipt"]["usage"]["total_tokens"] += 1
    elif change == "wrong_model":
        row["receipt"]["model_id"] = "other"
    elif change == "wrong_cost":
        row["receipt"]["cost_microusd"] = 0
    elif change == "quota":
        row["receipt"]["quota_available"] = False
    else:
        row["status"] = "PROVIDER_ADMISSION_FAILED"
    with pytest.raises(ValueError):
        ProviderAdmission(canonical_json(row)).verify(row["binding"], fixture=True)


def test_artifact_never_contains_secret(monkeypatch):
    monkeypatch.setattr(
        "finagent.agents.providers.config._read_api_key",
        lambda **k: pytest.fail("public binding cannot read credentials"),
    )
    text = canonical_json(provider_binding(Path("configs/llm.toml")))
    assert all(
        s not in text for s in ("api_key", "secret_id", "secrets_file", "Authorization", "Bearer")
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "calendar",
        "library",
        "fold",
        "implementation",
        "provider",
        "freeze",
        "missing_freeze",
    ],
)
def test_verify_refuses_drift(admitted, tmp_path, monkeypatch, mutation):
    admission, inputs, provider = admitted
    output = tmp_path / "campaign"
    frozen = freeze_campaign(admission, provider, output, fixture=True)
    original = None
    changed_path = None
    if mutation in {"source", "calendar", "library"}:
        path = (
            inputs["paths"][0 if mutation == "source" else 1]
            if mutation != "library"
            else inputs["library"]
        )
        original = path.read_bytes()
        changed_path = path
        with path.open("ab") as f:
            f.write(b"changed")
    elif mutation == "fold":
        admission = replace(
            admission, folds=(replace(admission.folds[0], name="changed"), *admission.folds[1:])
        )
    elif mutation == "implementation":
        monkeypatch.setattr(
            "finagent.application.r4_campaign.campaign_implementation",
            lambda: {"changed": "digest"},
        )
    elif mutation == "provider":
        row = provider.to_dict()
        row["binding"]["endpoint"] = "changed"
        provider = ProviderAdmission(canonical_json(row))
    elif mutation == "freeze":
        row = json.loads((output / "campaign_freeze.json").read_text())
        row["protocol"]["primary"]["budgets"]["portfolio_evaluations"] = 999
        (output / "campaign_freeze.json").write_text(json.dumps(row))
    else:
        (output / "campaign_freeze.json").unlink()
    try:
        with pytest.raises(ValueError):
            verify_campaign(
                output, admission, provider, accepted_freeze_id=frozen.freeze_id, fixture=True
            )
    finally:
        if changed_path is not None:
            changed_path.write_bytes(original)


@pytest.mark.parametrize(
    "name",
    [
        "result.json",
        "trial_result.json",
        "portfolio/result.json",
        "provider_research_response.json",
    ],
)
def test_outputs_cannot_predate_freeze(admitted, tmp_path, name):
    admission, _, provider = admitted
    path = tmp_path / "campaign" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
    with pytest.raises(ValueError, match="fresh directory"):
        freeze_campaign(admission, provider, tmp_path / "campaign", fixture=True)


def test_protocol_changes_identity_and_fixture_not_real(admitted, tmp_path):
    admission, _, provider = admitted
    freeze = freeze_campaign(admission, provider, tmp_path / "c", fixture=True)
    row = freeze.protocol.to_dict()
    row["candidate_rule"]["worst_fold_return_5bp_at_least"] = -0.02
    assert (
        R4MatchedComparisonProtocol(canonical_json(row)).protocol_id != freeze.protocol.protocol_id
    )
    with pytest.raises(ValueError):
        verify_campaign(
            tmp_path / "c",
            admission,
            provider,
            accepted_freeze_id=freeze.freeze_id,
            config=Path("configs/llm.toml"),
        )


def test_primary_tools_and_discovery_budget_enforced_through_runtime(admitted, tmp_path):
    admission, inputs, _ = admitted
    ids = [f.factor_id for f in inputs["factors"]]
    protocol = matched_protocol(
        version="v1",
        frozen_at="2026-09-06T00:00:00Z",
        provider_admission_id="provider",
        research_admission_id="scope",
        initial_factor_ids=ids,
        folds=[f.to_dict() for f in admission.folds],
    ).to_dict()
    for kind in ("primary", "discovery"):
        proposal = factor_steps(admission, ids)[1]
        steps = [proposal] * 5
        arm = {
            "kind": kind,
            "freeze_id": "fixture-freeze",
            "initial_factor_ids": ids,
            "tools": protocol[kind]["tools"],
            "budgets": protocol[kind]["budgets"],
        }
        runtime = open_research_session(
            admission,
            tmp_path / kind,
            run_id=kind,
            objective="fixture",
            provider=ScriptedProvider(steps),
            provider_id="scripted",
            model_id="fixture",
            audit=SQLiteAgentAuditStore(tmp_path / kind / "audit.sqlite"),
            policy=runtime_policy(arm["budgets"]),
            clock=Clock(),
            campaign_arm=arm,
        )
        results = [runtime.step(f"step-{i}", 0) for i in range(5)]
        if kind == "primary":
            assert all(r["code"] == "campaign_arm_tool_forbidden" for r in results)
        else:
            assert results[-1]["code"] == "campaign_proposal_budget_denied"
        assert len(runtime.ledger.journal()) == 5


def candidate(run, mean=0.01, worst=0.0, cost10=0.001):
    return {
        "candidate_id": run,
        "run_id": run,
        "agent_selected": True,
        "arm": "deterministic_selection" if run == "deterministic" else "agent_selection",
        "factor_ids": ["a", "b"],
        "allocator": "equal_weight",
        "experiment_id": "experiment",
        "runtime_agent_dependence": 0,
        "metrics": {
            "mean_fold_return_5bp": mean,
            "worst_fold_return_5bp": worst,
            "drawdown_5bp": 0.01,
            "turnover_5bp": 1,
            "factor_concentration": 0.5,
            "evaluable_folds": 3,
            "unavailable_sessions": 0,
            "cost_sensitivity": {
                str(float(c)): {"mean_fold_return": cost10} for c in (0, 1, 5, 10)
            },
        },
    }


def test_host_candidate_and_agent_value_are_separate(admitted):
    admission, inputs, provider = admitted
    p = matched_protocol(
        version="v1",
        frozen_at="now",
        provider_admission_id=provider.admission_id,
        research_admission_id="scope",
        initial_factor_ids=[f.factor_id for f in inputs["factors"]],
        folds=[f.to_dict() for f in admission.folds],
    )
    runs = ["deterministic", "selection-01", "selection-02", "selection-03"]
    candidates = [candidate(r) for r in runs]
    assessment = assess_campaign(p, candidates, completed_runs=runs, system_failure=False)
    assert assessment["agent_value"] == "NOT_SUPPORTED"
    assert assessment["candidate_decision"] == "ADAPTIVE_CANDIDATE"
    assert (
        assess_campaign(p, candidates, completed_runs=runs, system_failure=True)[
            "candidate_decision"
        ]
        == "SYSTEM_FAILURE"
    )
    for r in candidates:
        r["metrics"]["mean_fold_return_5bp"] = -0.1
    assert (
        assess_campaign(p, candidates, completed_runs=runs, system_failure=False)[
            "candidate_decision"
        ]
        == "NO_ADAPTIVE_CANDIDATE"
    )
    with pytest.raises(ValueError):
        AdaptiveStrategySpec.build(
            research_manifest={},
            protocol_id=p.protocol_id,
            campaign_result_id="result",
            candidate=candidates[0],
            assessment={**assessment, "decision_authority": "agent_finalize_candidate"},
            factor_definitions=[],
        )


def test_gate_repeatability_and_authority(admitted):
    admission, inputs, _ = admitted
    p = matched_protocol(
        version="v1",
        frozen_at="now",
        provider_admission_id="provider",
        research_admission_id="scope",
        initial_factor_ids=[f.factor_id for f in inputs["factors"]],
        folds=[f.to_dict() for f in admission.folds],
    )
    rows = [
        candidate("deterministic"),
        *[candidate(f"selection-0{i}", mean=0.02) for i in range(1, 4)],
    ]
    assessment = assess_campaign(
        p, rows, completed_runs=[r["run_id"] for r in rows], system_failure=False
    )
    assert assessment["agent_value"] == "SUPPORTED"
    assert all(assessment[k] == v for k, v in AUTHORITY.items())
    rows[1]["metrics"]["unavailable_sessions"] = 1
    assert (
        assess_campaign(p, rows, completed_runs=[r["run_id"] for r in rows], system_failure=False)[
            "agent_value"
        ]
        == "INCONCLUSIVE"
    )


def test_failed_evaluation_is_charged_and_never_retried(admitted, tmp_path, monkeypatch):
    import sqlite3

    admission, _, provider = admitted
    frozen = freeze_campaign(admission, provider, tmp_path / "c", fixture=True)
    calls = []

    def fail(*args, **kwargs):
        calls.append(True)
        raise RuntimeError("fixture evaluator infrastructure failure")

    monkeypatch.setattr(
        "finagent.application.research_controller_host.R4ResearchHost.evaluate_portfolio", fail
    )
    result = run_campaign(
        tmp_path / "c",
        admission,
        provider,
        accepted_freeze_id=frozen.freeze_id,
        fixture_provider_factory=lambda _: pytest.fail("system failure must stop campaign"),
        clock=current_clock(),
    )
    assert result["assessment"]["candidate_decision"] == "SYSTEM_FAILURE"
    with sqlite3.connect(tmp_path / "c/deterministic/research.sqlite") as db:
        assert db.execute(
            "SELECT state,evaluation_reserved,charged_tokens,charged_cost FROM attempts"
        ).fetchall() == [("TOOL_FAILED", 1, 0, 0)]
    run_campaign(
        tmp_path / "c",
        admission,
        provider,
        accepted_freeze_id=frozen.freeze_id,
        fixture_provider_factory=lambda _: pytest.fail("failure replay must not call"),
        clock=current_clock(),
    )
    assert calls == [True]


def test_clock_cannot_predate_freeze(admitted, tmp_path):
    admission, _, provider = admitted
    frozen = freeze_campaign(admission, provider, tmp_path / "c", fixture=True)
    with pytest.raises(ValueError, match="clock cannot predate freeze"):
        run_campaign(
            tmp_path / "c",
            admission,
            provider,
            accepted_freeze_id=frozen.freeze_id,
            fixture_provider_factory=lambda _: pytest.fail("no call"),
            clock=lambda: 0,
        )


def test_mandatory_comparators_and_candidate_schema(admitted):
    from finagent.application.r4_campaign import _candidates

    admission, inputs, _ = admitted
    with pytest.raises(ValueError, match="all five"):
        _candidates({"summary": {"arms": {"equal_weight": {}}}}, "agent_selection", "selection-01")
    c = candidate("deterministic")
    c["factor_ids"] = [f.factor_id for f in inputs["factors"][:2]]
    assessment = {
        "decision_authority": "deterministic_host",
        "candidate_decision": "ADAPTIVE_CANDIDATE",
        "candidate_id": c["candidate_id"],
        "protocol_id": "protocol",
    }
    spec = AdaptiveStrategySpec.build(
        research_manifest=admission.manifest(),
        protocol_id="protocol",
        campaign_result_id="result",
        candidate=c,
        assessment=assessment,
        factor_definitions=[f.to_dict() for f in inputs["factors"][:2]],
    )
    assert all(json.loads(spec.payload_json)[k] == v for k, v in AUTHORITY.items())
    assert (
        json.loads(spec.payload_json)["agent_role"] == "research_development_only; no_intraday_LLM"
    )


def test_provider_timeout_preserves_runtime_accounting(admitted, tmp_path, monkeypatch):
    admission, _, provider = admitted
    frozen = freeze_campaign(admission, provider, tmp_path / "c", fixture=True)
    # Unit test the provider failure boundary; the full fixture above exercises
    # actual deterministic evaluation, so no extra financial work is needed here.
    monkeypatch.setattr("finagent.application.r4_campaign._deterministic", lambda *a: ([], {}))
    instance = ScriptedProvider([TimeoutError("fixture")])
    result = run_campaign(
        tmp_path / "c",
        admission,
        provider,
        accepted_freeze_id=frozen.freeze_id,
        fixture_provider_factory=lambda _: instance,
        clock=current_clock(),
    )
    assert result["assessment"]["candidate_decision"] == "SYSTEM_FAILURE"
    assert len(instance.requests) == 1
    usage = result["resources"]["selection-01"]
    assert usage["charged_tokens"] == 32768
    assert usage["charged_cost_microusd"] == 50000


def test_unknown_provider_artifact_fields_rejected():
    row = provider_fixture().to_dict()
    row["api_key"] = "do-not-persist"
    with pytest.raises(ValueError, match="artifact fields"):
        ProviderAdmission(canonical_json(row)).verify(row["binding"], fixture=True)


def test_blocked_freeze_is_content_addressed_but_never_executable(admitted, tmp_path):
    from finagent.application.r4_campaign import R4CampaignFreeze, record_blocked_freeze

    admission, _, provider = admitted
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "failure.json").write_text(
        canonical_json(
            {"status": "PROVIDER_ADMISSION_FAILED", "reason": "probe_verification_failed"}
        )
    )
    (probe / "probe_request.json").write_text(
        canonical_json({"research_history": False, "binding": provider.to_dict()["binding"]})
    )
    blocked = record_blocked_freeze(
        admission, probe, tmp_path / "blocked", config=Path("configs/llm.toml")
    )
    assert blocked.to_dict()["status"] == "BLOCKED_PROVIDER_ADMISSION"
    row = blocked.to_dict()
    row["provider_blocker"]["probe_count"] += 1
    assert R4CampaignFreeze(canonical_json(row)).freeze_id != blocked.freeze_id
    with pytest.raises(ValueError, match="not accepted"):
        verify_campaign(
            tmp_path / "blocked",
            admission,
            provider,
            accepted_freeze_id=blocked.freeze_id,
            config=Path("configs/llm.toml"),
        )


def test_probe_offline_contract_and_single_attempt(monkeypatch, tmp_path):
    from finagent.agents.r3_runtime import ResearchReply
    from finagent.agents.r4_provider_admission import PROBE_ACTION, probe_provider

    calls = []

    class ProbeTransport:
        def __init__(self, *a, **k):
            self.last_receipt = provider_fixture().to_dict()["receipt"]

        def respond(self, request):
            calls.append(request)
            return ResearchReply(canonical_json(PROBE_ACTION), 120, 212)

    monkeypatch.setattr(
        "finagent.agents.r4_provider_admission.StrictDeepSeekProvider", ProbeTransport
    )
    admitted_probe = probe_provider(Path("configs/llm.toml"), tmp_path / "probe")
    assert admitted_probe.to_dict()["probe_scope"] == "non_research_no_market_no_objective"
    assert not any(
        s in calls[0].context_json for s in ("factor_ids", "market_state", "objective", "OHLCV")
    )
    with pytest.raises(ValueError, match="already attempted"):
        probe_provider(Path("configs/llm.toml"), tmp_path / "probe")
    assert len(calls) == 1


def test_probe_failure_keeps_sanitized_phase_not_error_text(monkeypatch, tmp_path):
    from finagent.agents.r4_provider_admission import probe_provider

    class BadTransport:
        last_receipt = None

        def __init__(self, *a, **k):
            pass

        def respond(self, request):
            raise RuntimeError("Authorization: Bearer secret-sentinel")

    monkeypatch.setattr(
        "finagent.agents.r4_provider_admission.StrictDeepSeekProvider", BadTransport
    )
    with pytest.raises(ValueError, match="PROVIDER_ADMISSION_FAILED"):
        probe_provider(Path("configs/llm.toml"), tmp_path / "probe")
    text = (tmp_path / "probe/failure.json").read_text()
    assert "secret-sentinel" not in text
    assert json.loads(text)["phase"] == "transport"

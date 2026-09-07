"""Guarded R4 campaign execution operator acceptance, entirely synthetic/offline."""

from __future__ import annotations

import json
import math
import runpy
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from finagent.agents.r3_contracts import DevelopmentScope, canonical_json, identity
from finagent.agents.r4_contracts import AUTHORITY
from finagent.agents.r4_provider_admission import ProviderAdmission, provider_binding
from finagent.application.r4_campaign import (
    R4CampaignFreeze,
    campaign_implementation,
    freeze_campaign,
    record_blocked_freeze,
    run_campaign,
    verify_campaign,
)
from finagent.application.r4_campaign_admission import load_research_admission
from finagent.research.r4_campaign_protocol import matched_protocol
from finagent.research.us_r3_economic_campaign import file_digest
from tests.r4_controller_fixture import Clock, ScriptedProvider, admission_fixture, selection_steps

EXPECTED_SUMMARY_KEYS = {
    "campaign_result_id",
    "campaign_freeze_id",
    "protocol_id",
    "completed_runs",
    "agent_value",
    "candidate_decision",
    "candidate_id",
    "fixture_only",
    "development_only",
    "alpha_authority",
    "paper_authority",
    "live_authority",
    "result_path",
}


def _provider(*, fixture: bool) -> ProviderAdmission:
    binding = provider_binding(Path("configs/llm.toml"))
    return ProviderAdmission(
        canonical_json(
            {
                "status": "ACCEPTED",
                "fixture_only": fixture,
                "binding": binding,
                "admitted_at": "2026-09-07T00:00:00+00:00",
                "probe_scope": "non_research_no_market_no_objective",
                "admission_evidence_id": "synthetic-operator-probe",
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


def _clock() -> Clock:
    clock = Clock()
    clock.value = datetime.now(UTC).timestamp()
    return clock


@pytest.fixture(scope="module")
def operator_fixture(tmp_path_factory):
    root = tmp_path_factory.mktemp("r4-campaign-operator")
    admission, inputs = admission_fixture(root / "inputs")
    admission = replace(
        admission,
        scope=DevelopmentScope(
            "r4-operator-fixture",
            (),
            admission.source.identity.identity,
            admission.scope.evaluator_id,
        ),
    )
    research = root / "research-admission"
    research.mkdir()
    seed = research / "seed_factor_library.sqlite"
    shutil.copy2(inputs["library"], seed)
    admission = replace(admission, seed_library=seed)
    config = {
        "source": str(inputs["paths"][0]),
        "calendar": str(inputs["paths"][1]),
        "base_plan": str(inputs["paths"][2]),
        "evidence": str(inputs["paths"][3]),
        "source_id": "synthetic-walkforward",
        "source_revision": "v1",
        "universe": ["A0", "A1", "A2", "A3"],
    }
    (research / "research_admission.json").write_text(
        canonical_json(
            {
                "config": config,
                "manifest": admission.manifest(),
                "seed_library_name": seed.name,
                "seed_library_digest": file_digest(seed),
                "scope_name": admission.scope.scope_id,
            }
        )
    )
    loaded = load_research_admission(research)
    fixture_provider = _provider(fixture=True)
    provider_path = root / "fixture-provider.json"
    provider_path.write_text(canonical_json(fixture_provider.to_dict()))
    return {
        "root": root,
        "research": research,
        "admission": loaded,
        "inputs": inputs,
        "provider": fixture_provider,
        "provider_path": provider_path,
    }


def _cli():
    namespace = runpy.run_path("scripts/r4_campaign.py", run_name="r4_campaign_operator_test")
    return namespace, namespace["build_parser"]()


def _argv(operator_fixture, output: Path, freeze_id: str, provider_path: Path | None = None):
    return [
        "run",
        "--output",
        str(output),
        "--research-admission",
        str(operator_fixture["research"]),
        "--provider-admission",
        str(provider_path or operator_fixture["provider_path"]),
        "--accepted-freeze-id",
        freeze_id,
        "--config",
        "configs/llm.toml",
    ]


def _promote_fixture_freeze(
    frozen: R4CampaignFreeze,
    output: Path,
    provider: ProviderAdmission,
) -> R4CampaignFreeze:
    """Create a real-shaped test artifact without granting production fixture authority."""
    row = frozen.to_dict()
    row["status"] = "ACCEPTED"
    row["fixture_only"] = False
    row["provider_admission"] = provider.to_dict()
    row["provider_admission_id"] = provider.admission_id
    protocol = matched_protocol(
        version=row["protocol"]["protocol_version"],
        frozen_at=row["frozen_at"],
        provider_admission_id=provider.admission_id,
        research_admission_id=row["research_admission_id"],
        initial_factor_ids=row["protocol"]["initial_factor_ids"],
        folds=row["research_admission"]["folds"],
    )
    row["protocol"] = protocol.to_dict()
    row["protocol_id"] = protocol.protocol_id
    promoted = R4CampaignFreeze(canonical_json(row))
    (output / "campaign_freeze.json").write_text(
        canonical_json({"campaign_freeze_id": promoted.freeze_id, **promoted.to_dict()})
    )
    return promoted


def _real_shaped_operator(operator_fixture, tmp_path: Path):
    output = tmp_path / "campaign"
    fixture_freeze = freeze_campaign(
        operator_fixture["admission"], operator_fixture["provider"], output, fixture=True
    )
    provider = _provider(fixture=False)
    provider_path = tmp_path / "provider.json"
    provider_path.write_text(canonical_json(provider.to_dict()))
    frozen = _promote_fixture_freeze(fixture_freeze, output, provider)
    namespace, parser = _cli()
    args = parser.parse_args(_argv(operator_fixture, output, frozen.freeze_id, provider_path))
    return namespace, args, frozen, provider_path


def test_run_parser_exists_and_requires_explicit_operator_authority(operator_fixture, tmp_path):
    _, parser = _cli()
    base = _argv(operator_fixture, tmp_path / "campaign", "freeze-id")
    args = parser.parse_args(base)
    assert args.command == "run"
    required = {
        "--output",
        "--research-admission",
        "--provider-admission",
        "--accepted-freeze-id",
        "--config",
    }
    for flag in required:
        index = base.index(flag)
        missing = base[:index] + base[index + 2 :]
        with pytest.raises(SystemExit):
            parser.parse_args(missing)


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--campaign-version", "r4-matched-v1"),
        ("--budget", "999"),
        ("--factor-ids", "a,b"),
        ("--cost-bps", "0"),
        ("--provider", "fallback"),
        ("--model", "other"),
        ("--force", "true"),
        ("--retry", "1"),
        ("--reset", "true"),
    ],
)
def test_run_parser_exposes_no_research_or_retry_override(
    operator_fixture, tmp_path, flag, value
):
    _, parser = _cli()
    with pytest.raises(SystemExit):
        parser.parse_args(_argv(operator_fixture, tmp_path / "campaign", "freeze-id") + [flag, value])


def test_real_cli_rejects_blocked_freeze_before_runner(operator_fixture, tmp_path):
    probe = tmp_path / "probe"
    probe.mkdir()
    (probe / "failure.json").write_text(
        canonical_json(
            {
                "status": "PROVIDER_ADMISSION_FAILED",
                "reason": "probe_verification_failed",
                "phase": "transport",
            }
        )
    )
    (probe / "probe_request.json").write_text(
        canonical_json(
            {
                "research_history": False,
                "binding": operator_fixture["provider"].to_dict()["binding"],
            }
        )
    )
    output = tmp_path / "blocked"
    blocked = record_blocked_freeze(
        operator_fixture["admission"], probe, output, config=Path("configs/llm.toml")
    )
    namespace, parser = _cli()
    args = parser.parse_args(_argv(operator_fixture, output, blocked.freeze_id))
    with pytest.raises(ValueError, match="not accepted"):
        namespace["_run_command"](
            args, runner=lambda *a, **k: pytest.fail("blocked freeze must not reach runner")
        )


def test_real_cli_rejects_fixture_freeze_before_runner(operator_fixture, tmp_path):
    output = tmp_path / "fixture"
    frozen = freeze_campaign(
        operator_fixture["admission"], operator_fixture["provider"], output, fixture=True
    )
    namespace, parser = _cli()
    args = parser.parse_args(_argv(operator_fixture, output, frozen.freeze_id))
    with pytest.raises(ValueError, match="not accepted"):
        namespace["_run_command"](
            args, runner=lambda *a, **k: pytest.fail("fixture authority must not reach real runner")
        )


def test_real_cli_rejects_mismatched_or_missing_freeze_before_runner(
    operator_fixture, tmp_path
):
    output = tmp_path / "fixture"
    frozen = freeze_campaign(
        operator_fixture["admission"], operator_fixture["provider"], output, fixture=True
    )
    namespace, parser = _cli()
    args = parser.parse_args(_argv(operator_fixture, output, "wrong-freeze-id"))
    with pytest.raises(ValueError, match="freeze identity mismatch"):
        namespace["_run_command"](
            args, runner=lambda *a, **k: pytest.fail("mismatched freeze must not reach runner")
        )
    missing = tmp_path / "missing"
    args = parser.parse_args(_argv(operator_fixture, missing, frozen.freeze_id))
    with pytest.raises(ValueError, match="accepted campaign freeze required"):
        namespace["_run_command"](
            args, runner=lambda *a, **k: pytest.fail("missing freeze must not reach runner")
        )


def test_provider_artifact_and_config_drift_fail_before_runner(
    operator_fixture, tmp_path, monkeypatch
):
    namespace, args, _, provider_path = _real_shaped_operator(operator_fixture, tmp_path)
    drifted = json.loads(provider_path.read_text())
    drifted["admitted_at"] = "2026-09-07T00:00:01+00:00"
    provider_path.write_text(canonical_json(drifted))
    with pytest.raises(ValueError, match="drift"):
        namespace["_run_command"](
            args, runner=lambda *a, **k: pytest.fail("provider drift must fail before runner")
        )

    provider_path.write_text(canonical_json(_provider(fixture=False).to_dict()))
    binding = provider_binding(Path("configs/llm.toml"))
    monkeypatch.setattr(
        "finagent.application.r4_campaign.provider_binding",
        lambda _: {**binding, "endpoint": "https://example.invalid"},
    )
    with pytest.raises(ValueError, match="PROVIDER_ADMISSION_FAILED"):
        namespace["_run_command"](
            args, runner=lambda *a, **k: pytest.fail("config drift must fail before runner")
        )


@pytest.mark.parametrize("mutation", ["source", "library", "fold", "implementation"])
def test_operator_fails_closed_on_research_or_implementation_drift(
    operator_fixture, tmp_path, monkeypatch, mutation
):
    output = tmp_path / "fixture"
    frozen = freeze_campaign(
        operator_fixture["admission"], operator_fixture["provider"], output, fixture=True
    )
    namespace, parser = _cli()
    args = parser.parse_args(_argv(operator_fixture, output, frozen.freeze_id))

    def fixture_verify(output, admission, provider, **kwargs):
        return verify_campaign(
            output,
            admission,
            provider,
            accepted_freeze_id=kwargs["accepted_freeze_id"],
            fixture=True,
        )

    restore_path = None
    restore_bytes = None
    restore_text = None
    if mutation == "source":
        restore_path = operator_fixture["inputs"]["paths"][0]
        restore_bytes = restore_path.read_bytes()
        with restore_path.open("ab") as handle:
            handle.write(b"operator-drift")
    elif mutation == "library":
        restore_path = operator_fixture["research"] / "seed_factor_library.sqlite"
        restore_bytes = restore_path.read_bytes()
        with restore_path.open("ab") as handle:
            handle.write(b"operator-drift")
    elif mutation == "fold":
        restore_path = operator_fixture["research"] / "research_admission.json"
        restore_text = restore_path.read_text()
        bundle = json.loads(restore_text)
        bundle["manifest"]["folds"][0]["name"] = "mutated-fold"
        restore_path.write_text(canonical_json(bundle))
    else:
        monkeypatch.setattr(
            "finagent.application.r4_campaign.campaign_implementation",
            lambda: {"changed": "digest"},
        )
    try:
        with pytest.raises(ValueError):
            namespace["_run_command"](
                args,
                verifier=fixture_verify,
                runner=lambda *a, **k: pytest.fail("drift must fail before runner"),
            )
    finally:
        if restore_path is not None and restore_bytes is not None:
            restore_path.write_bytes(restore_bytes)
        elif restore_path is not None and restore_text is not None:
            restore_path.write_text(restore_text)


def test_fixture_cli_boundary_runs_full_campaign_and_replays_without_provider(
    operator_fixture, tmp_path, capsys
):
    output = tmp_path / "campaign"
    frozen = freeze_campaign(
        operator_fixture["admission"], operator_fixture["provider"], output, fixture=True
    )
    namespace, parser = _cli()
    args = parser.parse_args(_argv(operator_fixture, output, frozen.freeze_id))
    factor_ids = [row["factor_id"] for row in operator_fixture["admission"].manifest()["initial_factors"]]
    providers = []

    def fixture_verify(output, admission, provider, **kwargs):
        return verify_campaign(
            output,
            admission,
            provider,
            accepted_freeze_id=kwargs["accepted_freeze_id"],
            fixture=True,
        )

    def factory(_run_id):
        provider = ScriptedProvider(selection_steps(factor_ids))
        providers.append(provider)
        return provider

    clock = _clock()

    def fixture_run(output, admission, provider, **kwargs):
        return run_campaign(
            output,
            admission,
            provider,
            accepted_freeze_id=kwargs["accepted_freeze_id"],
            fixture_provider_factory=factory,
            clock=clock,
        )

    result = namespace["_run_command"](
        args, verifier=fixture_verify, runner=fixture_run
    )
    first_output = capsys.readouterr().out.strip()
    summary = json.loads(first_output)
    assert set(summary) == EXPECTED_SUMMARY_KEYS
    assert summary["campaign_result_id"] == result["campaign_result_id"]
    assert summary["campaign_freeze_id"] == frozen.freeze_id
    assert summary["completed_runs"] == result["completed_runs"]
    assert summary["agent_value"] == result["assessment"]["agent_value"]
    assert summary["candidate_decision"] == result["assessment"]["candidate_decision"]
    assert summary["fixture_only"] is True
    assert summary["development_only"] is True
    assert summary["alpha_authority"] is False
    assert summary["paper_authority"] is False
    assert summary["live_authority"] is False
    assert summary["result_path"] == str(output / "campaign_result.json")
    assert len(providers) == 6
    assert "resources" not in first_output
    assert "candidates" not in first_output
    assert all(
        secret not in first_output
        for secret in ("Authorization", "Bearer", "api_key", "prompt_tokens", "action_json")
    )
    before = (output / "campaign_result.json").read_bytes()

    def replay_run(output, admission, provider, **kwargs):
        return run_campaign(
            output,
            admission,
            provider,
            accepted_freeze_id=kwargs["accepted_freeze_id"],
            fixture_provider_factory=lambda _: pytest.fail(
                "committed campaign replay must not call provider"
            ),
            clock=_clock(),
        )

    replayed = namespace["_run_command"](
        args, verifier=fixture_verify, runner=replay_run
    )
    second_output = capsys.readouterr().out.strip()
    assert replayed == result
    assert json.loads(second_output) == summary
    assert (output / "campaign_result.json").read_bytes() == before
    assert result["assessment"]["candidate_decision"] in {
        "ADAPTIVE_CANDIDATE",
        "NO_ADAPTIVE_CANDIDATE",
        "SYSTEM_FAILURE",
    }
    assert result["alpha_authority"] is False
    assert result["paper_authority"] is False
    assert result["live_authority"] is False


def test_campaign_implementation_binds_operator_content():
    implementation = campaign_implementation()
    operator = Path("scripts/r4_campaign.py")
    assert "scripts/r4_campaign.py" in implementation
    assert implementation["scripts/r4_campaign.py"] == file_digest(operator)
    changed = {**implementation, "scripts/r4_campaign.py": "0" * 64}
    assert identity(implementation, "campaign-implementation") != identity(
        changed, "campaign-implementation"
    )

"""Offline acceptance for the guarded R4 provider-admission probe contract."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from finagent.agents import r4_provider_admission as admission
from finagent.agents.r3_contracts import canonical_json
from finagent.agents.r3_runtime import ResearchReply
from finagent.agents.r4_contracts import r4_manifest


def _receipt() -> dict[str, object]:
    return {
        "model_id": "deepseek-v4-pro",
        "response_id": "fixture-response-id",
        "system_fingerprint": "fixture-fingerprint",
        "quota_available": True,
        "cost_microusd": math.ceil(100 * 1.32 + 20 * 3.96),
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 100,
        },
    }


def _probe_transport(monkeypatch, *, action_json: str, receipt=None, error=None):
    calls = []

    class ProbeTransport:
        def __init__(self, *args, **kwargs):
            self.last_receipt = _receipt() if receipt is None else receipt

        def respond(self, request):
            calls.append(request)
            if error is not None:
                raise error
            return ResearchReply(action_json, 120, 212)

    monkeypatch.setattr(admission, "StrictDeepSeekProvider", ProbeTransport)
    return calls


def test_probe_context_matches_real_r4_manifest_and_contains_no_research_evidence(
    monkeypatch, tmp_path
):
    calls = _probe_transport(
        monkeypatch,
        action_json=canonical_json(admission.PROBE_ACTION),
    )
    accepted = admission.probe_provider(Path("configs/llm.toml"), tmp_path / "probe")
    context = json.loads(calls[0].context_json)
    assert context["schema_version"] == admission.PROBE_CONTEXT_SCHEMA
    assert context["capability_set"] == r4_manifest()
    assert context["research_history"] is False
    assert context["probe_scope"] == admission.PROBE_SCOPE
    assert context["required_action"] == admission.PROBE_ACTION
    assert context["state"] == {}
    assert context["resources"] == []
    assert context["feedback"] == []
    assert "objective" not in context
    assert "market_data" not in context
    assert "pnl" not in context
    assert "campaign_result" not in context
    assert accepted.to_dict()["status"] == "ACCEPTED"


def test_successful_offline_fixture_probe_creates_verified_admission(monkeypatch, tmp_path):
    calls = _probe_transport(
        monkeypatch,
        action_json=canonical_json(admission.PROBE_ACTION),
    )
    output = tmp_path / "probe"
    accepted = admission.probe_provider(Path("configs/llm.toml"), output)
    binding = admission.provider_binding(Path("configs/llm.toml"))
    accepted.verify(binding)
    artifact = json.loads((output / "provider_admission.json").read_text())
    assert artifact == accepted.to_dict()
    assert artifact["binding"]["probe_contract_digest"] == admission.probe_contract_digest()
    assert artifact["probe_scope"] == admission.PROBE_SCOPE
    assert len(calls) == 1


def test_valid_but_different_action_is_explicit_contract_mismatch(monkeypatch, tmp_path):
    different = {
        "schema_version": "finagent.r4-action.v1",
        "tool": "record_decision",
        "arguments": {
            "critique": "raw-action-sentinel",
            "next_action": "Stop.",
        },
    }
    receipt = _receipt()
    calls = _probe_transport(
        monkeypatch,
        action_json=canonical_json(different),
        receipt=receipt,
    )
    output = tmp_path / "probe"
    with pytest.raises(ValueError, match="PROVIDER_ADMISSION_FAILED"):
        admission.probe_provider(Path("configs/llm.toml"), output)
    failure = json.loads((output / "failure.json").read_text())
    assert failure["phase"] == "strict_action"
    assert failure["reason"] == "probe_contract_mismatch"
    assert "strict_action_error_code" not in failure
    assert failure["verified_transport_receipt"] == receipt
    assert "raw-action-sentinel" not in (output / "failure.json").read_text()
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("raw", "expected_code"),
    [
        (
            canonical_json(
                {
                    "schema_version": "finagent.r4-action.v0",
                    "tool": "record_decision",
                    "arguments": {"critique": "x", "next_action": "Stop."},
                }
            ),
            "action_schema_mismatch",
        ),
        (
            canonical_json(
                {
                    "schema_version": "finagent.r4-action.v1",
                    "tool": "not_a_real_tool",
                    "arguments": {},
                }
            ),
            "unknown_r4_tool",
        ),
        (
            canonical_json(
                {
                    "schema_version": "finagent.r4-action.v1",
                    "tool": "record_decision",
                    "arguments": {
                        "critique": "raw-invalid-action-sentinel",
                        "next_action": "Stop.",
                        "extra": "not admitted",
                    },
                }
            ),
            "invalid_object_fields",
        ),
    ],
)
def test_invalid_strict_action_keeps_only_safe_decoder_code(
    monkeypatch, tmp_path, raw, expected_code
):
    receipt = _receipt()
    _probe_transport(monkeypatch, action_json=raw, receipt=receipt)
    output = tmp_path / "probe"
    with pytest.raises(ValueError, match="PROVIDER_ADMISSION_FAILED"):
        admission.probe_provider(Path("configs/llm.toml"), output)
    failure = json.loads((output / "failure.json").read_text())
    assert failure == {
        "status": "PROVIDER_ADMISSION_FAILED",
        "research_history": False,
        "reason": "probe_action_contract_failed",
        "phase": "strict_action",
        "strict_action_error_code": expected_code,
        "verified_transport_receipt": receipt,
    }
    text = (output / "failure.json").read_text()
    assert raw not in text
    assert "raw-invalid-action-sentinel" not in text


def test_unknown_contract_exception_text_is_closed_to_generic_safe_code(monkeypatch, tmp_path):
    class UnsafeContractError(admission.ContractError):
        pass

    monkeypatch.setattr(
        admission,
        "decode_r4_action",
        lambda raw: (_ for _ in ()).throw(UnsafeContractError("raw-decoder-secret-sentinel")),
    )
    _probe_transport(monkeypatch, action_json="{}", receipt=_receipt())
    output = tmp_path / "probe"
    with pytest.raises(ValueError, match="PROVIDER_ADMISSION_FAILED"):
        admission.probe_provider(Path("configs/llm.toml"), output)
    failure = json.loads((output / "failure.json").read_text())
    assert failure["reason"] == "probe_action_contract_failed"
    assert failure["strict_action_error_code"] == "r4_action_contract_invalid"
    assert "raw-decoder-secret-sentinel" not in (output / "failure.json").read_text()


def test_raw_provider_exception_is_never_persisted(monkeypatch, tmp_path):
    calls = _probe_transport(
        monkeypatch,
        action_json="{}",
        receipt=None,
        error=RuntimeError("Authorization: Bearer raw-provider-secret-sentinel"),
    )
    output = tmp_path / "probe"
    with pytest.raises(ValueError, match="PROVIDER_ADMISSION_FAILED"):
        admission.probe_provider(Path("configs/llm.toml"), output)
    failure = json.loads((output / "failure.json").read_text())
    assert failure["phase"] == "transport"
    assert failure["reason"] == "probe_verification_failed"
    text = (output / "failure.json").read_text()
    assert "raw-provider-secret-sentinel" not in text
    assert "Authorization" not in text
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["manifest", "action", "context"])
def test_probe_contract_digest_changes_with_frozen_contract(monkeypatch, change):
    before = admission.provider_binding(Path("configs/llm.toml"))["probe_contract_digest"]
    if change == "manifest":
        original = r4_manifest()
        monkeypatch.setattr(
            admission,
            "r4_manifest",
            lambda: {**original, "rules": original["rules"] + " probe-test-change"},
        )
    elif change == "action":
        monkeypatch.setattr(
            admission,
            "PROBE_ACTION",
            {
                **admission.PROBE_ACTION,
                "arguments": {
                    "critique": "Transport admission only.",
                    "next_action": "Stop changed.",
                },
            },
        )
    else:
        monkeypatch.setattr(
            admission,
            "PROBE_CONTEXT_INSTRUCTION",
            admission.PROBE_CONTEXT_INSTRUCTION + " Changed.",
        )
    after = admission.provider_binding(Path("configs/llm.toml"))["probe_contract_digest"]
    assert after != before


def test_provider_binding_is_secret_free_and_single_attempt(monkeypatch):
    monkeypatch.setattr(
        "finagent.agents.providers.config._read_api_key",
        lambda **kwargs: pytest.fail("public provider binding must not read credentials"),
    )
    binding = admission.provider_binding(Path("configs/llm.toml"))
    text = canonical_json(binding)
    assert binding["transport_attempts"] == 1
    assert binding["fallback"] == "PROVIDER_ADMISSION_FAILED; never_switch"
    assert binding["probe_contract_digest"].startswith("r4-provider-probe-contract-")
    assert all(
        value not in text
        for value in ("api_key", "secret_id", "secrets_file", "Authorization", "Bearer")
    )


def test_probe_directory_permits_exactly_one_transport_attempt(monkeypatch, tmp_path):
    calls = _probe_transport(
        monkeypatch,
        action_json=canonical_json(
            {
                "schema_version": "finagent.r4-action.v1",
                "tool": "inspect_market_state",
                "arguments": {},
            }
        ),
        receipt=_receipt(),
    )
    output = tmp_path / "probe"
    with pytest.raises(ValueError, match="PROVIDER_ADMISSION_FAILED"):
        admission.probe_provider(Path("configs/llm.toml"), output)
    with pytest.raises(ValueError, match="already attempted"):
        admission.probe_provider(Path("configs/llm.toml"), output)
    assert len(calls) == 1
    assert not (output / "provider_admission.json").exists()

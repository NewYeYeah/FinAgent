"""Non-research admission of the existing single-attempt ResearchProvider."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from finagent.agents.providers.config import load_llm_profile
from finagent.agents.r3_contracts import canonical_json, identity
from finagent.agents.r3_provider import TARIFF, StrictDeepSeekProvider, parse_reply
from finagent.agents.r3_runtime import ResearchReply, ResearchRequest
from finagent.agents.r4_contracts import AUTHORITY, decode_r4_action
from finagent.research.us_r3_economic_campaign import file_digest
from finagent.research.us_r3_usability import write_immutable_json

PROFILE = "r4_deepseek_v4_pro"
INSTRUCTION = (
    "Return exactly one JSON action matching the provided finagent.r4-action.v1 manifest. "
    "Use only admitted tools and IDs. Persist explicit actions and decisions only. "
    "Never return hidden reasoning or a scratchpad. All evidence is exposed development."
)
PROBE_ACTION = {
    "schema_version": "finagent.r4-action.v1",
    "tool": "record_decision",
    "arguments": {"critique": "Transport admission only.", "next_action": "Stop."},
}
PROBE_CONTEXT = canonical_json(
    {
        "transport_check": "Return the supplied JSON action exactly; no research is requested.",
        "action": PROBE_ACTION,
    }
)


def provider_binding(config: Path) -> dict[str, Any]:
    profile = load_llm_profile(config, profile_name=PROFILE)
    if (
        profile.name != PROFILE
        or profile.provider != "deepseek"
        or profile.model != "deepseek-v4-pro"
        or profile.base_url != "https://api.deepseek.com"
        or profile.thinking is not False
        or profile.reasoning_effort is not None
        or profile.max_attempts != 1
        or profile.timeout_seconds != 120
        or profile.retry_backoff_seconds != 0
    ):
        raise ValueError("PROVIDER_ADMISSION_FAILED: profile/model/endpoint/config mismatch")
    root = Path(__file__).parents[1]
    return {
        "provider_type": "deepseek",
        "profile_name": PROFILE,
        "provider_id": "strict-deepseek-r4",
        "model_id": profile.model,
        "endpoint": profile.base_url,
        "thinking": "disabled",
        "reasoning_effort": None,
        "temperature": 0.7,
        "response_format": "json_object",
        "stream": False,
        "contract": "finagent.r4-action.v1",
        "instruction_digest": identity(INSTRUCTION, "prompt"),
        "timeout_seconds": 120,
        "maximum_input_tokens": 28672,
        "maximum_output_tokens": 3000,
        "maximum_total_tokens": 32768,
        "maximum_cost_microusd_per_call": 50000,
        "transport_attempts": 1,
        "usage_semantics": "required_integer_prompt_completion_total_hit_miss; exact_sums; positive_total",
        "cost_semantics": "ceil(cache_hit*0.044 + cache_miss*1.32 + output*3.96) microusd; peak_upper_bound_not_invoice",
        "tariff": TARIFF,
        "fallback": "PROVIDER_ADMISSION_FAILED; never_switch",
        "adapter_implementation": {
            n: file_digest(root / n)
            for n in (
                "agents/r3_provider.py",
                "agents/providers/config.py",
                "agents/r4_provider_admission.py",
            )
        },
        "dependencies": {"httpx": version("httpx")},
    }


@dataclass(frozen=True)
class ProviderAdmission:
    """Canonical JSON owns the immutable value; no credentials or config paths."""

    payload_json: str

    @property
    def admission_id(self) -> str:
        return identity(self.to_dict(), "r4-provider-admission")

    def to_dict(self) -> dict[str, Any]:
        return dict(json.loads(self.payload_json))

    def verify(self, binding: dict[str, Any], *, fixture: bool = False) -> None:
        row = self.to_dict()
        if set(row) != {
            "status",
            "fixture_only",
            "binding",
            "admitted_at",
            "probe_scope",
            "admission_evidence_id",
            "receipt",
            *AUTHORITY,
        } or any(row[k] != v for k, v in AUTHORITY.items()):
            raise ValueError("PROVIDER_ADMISSION_FAILED: artifact fields/authority")
        if row["binding"] != binding or row["fixture_only"] != fixture:
            raise ValueError("PROVIDER_ADMISSION_FAILED: binding mismatch")
        if (
            row["status"] != "ACCEPTED"
            or row["probe_scope"] != "non_research_no_market_no_objective"
        ):
            raise ValueError("PROVIDER_ADMISSION_FAILED: probe not accepted")
        receipt = row["receipt"]
        if set(receipt.get("usage", {})) != {
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
        }:
            raise ValueError("PROVIDER_ADMISSION_FAILED: usage fields")
        if (
            set(receipt)
            != {
                "model_id",
                "response_id",
                "system_fingerprint",
                "usage",
                "cost_microusd",
                "quota_available",
            }
            or not isinstance(receipt["response_id"], str)
            or not receipt["response_id"]
            or not isinstance(receipt["system_fingerprint"], str)
            or not receipt["system_fingerprint"]
        ):
            raise ValueError("PROVIDER_ADMISSION_FAILED: response/fingerprint unavailable")
        if receipt["model_id"] != binding["model_id"] or receipt["quota_available"] is not True:
            raise ValueError("PROVIDER_ADMISSION_FAILED: response identity/quota")
        reply = parse_reply(
            {
                "usage": receipt["usage"],
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": canonical_json(PROBE_ACTION)},
                    }
                ],
            },
            token_cap=32768,
            input_cap=28672,
            output_cap=3000,
        )
        if reply.cost_microusd != receipt["cost_microusd"]:
            raise ValueError("PROVIDER_ADMISSION_FAILED: cost unverified")


def probe_provider(config: Path, output: Path) -> ProviderAdmission:
    """Exactly one non-research request. An existing attempt is never retried."""
    binding = provider_binding(config)
    requested_at = datetime.now(UTC).isoformat()
    if output.exists() and any(output.iterdir()):
        raise ValueError("probe already attempted; retain original evidence")
    write_immutable_json(
        output / "probe_request.json",
        {
            "binding": binding,
            "requested_at": requested_at,
            "context": json.loads(PROBE_CONTEXT),
            "research_history": False,
        },
    )
    provider = StrictDeepSeekProvider(config, INSTRUCTION, profile_name=PROFILE)
    phase = "transport"
    try:
        reply = provider.respond(
            ResearchRequest("r4-non-research-probe", PROBE_CONTEXT, 32768, 50000, 120)
        )
        phase = "strict_action"
        if decode_r4_action(reply.action_json) != PROBE_ACTION or provider.last_receipt is None:
            raise ValueError("probe_contract_mismatch")
        admission = ProviderAdmission(
            canonical_json(
                {
                    "status": "ACCEPTED",
                    "fixture_only": False,
                    "binding": binding,
                    "admitted_at": datetime.now(UTC).isoformat(),
                    "probe_scope": "non_research_no_market_no_objective",
                    "admission_evidence_id": identity(
                        {"requested_at": requested_at, "receipt": provider.last_receipt},
                        "provider-probe",
                    ),
                    "receipt": provider.last_receipt,
                    **AUTHORITY,
                }
            )
        )
        phase = "receipt_admission"
        admission.verify(binding)
        write_immutable_json(output / "provider_admission.json", admission.to_dict())
        return admission
    except Exception as error:  # noqa: BLE001 -- only allowlisted error codes, never transport text.
        code = (
            str(error)
            if str(error)
            in {
                "credential_unavailable",
                "provider_profile_mismatch",
                "transport_uncertain",
                "provider_quota",
                "transport_deadline",
                "probe_contract_mismatch",
                "provider_response_identity_mismatch",
                "provider_usage_unverified",
                "provider_usage_breach",
            }
            else "probe_verification_failed"
        )
        write_immutable_json(
            output / "failure.json",
            {
                "status": "PROVIDER_ADMISSION_FAILED",
                "research_history": False,
                "reason": code,
                "phase": phase,
                "verified_transport_receipt": provider.last_receipt,
            },
        )
        raise ValueError("PROVIDER_ADMISSION_FAILED; sanitized probe failure retained") from None


class AdmittedDeepSeekProvider:
    """Thin binding check around the existing transport; no retries or provider loop."""

    def __init__(self, config: Path, admission: ProviderAdmission) -> None:
        self.config, self.admission = config, admission
        admission.verify(provider_binding(config))
        self.transport = StrictDeepSeekProvider(config, INSTRUCTION, profile_name=PROFILE)

    def respond(self, request: ResearchRequest) -> ResearchReply:
        self.admission.verify(provider_binding(self.config))
        if (
            request.maximum_total_tokens > 32768
            or request.maximum_cost_microusd > 50000
            or request.timeout_seconds > 120
            or len((request.context_json + INSTRUCTION).encode()) + 1024 > 28672
        ):
            raise ValueError("PROVIDER_ADMISSION_FAILED: request bounds")
        reply = self.transport.respond(request)
        receipt = self.transport.last_receipt
        frozen = self.admission.to_dict()["receipt"]
        if receipt is None or receipt["system_fingerprint"] != frozen["system_fingerprint"]:
            raise ValueError("PROVIDER_ADMISSION_FAILED: backend fingerprint changed")
        return reply

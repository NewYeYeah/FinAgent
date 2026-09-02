from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from finagent.agents.providers import (
    ConfiguredLLM,
    LLMProfile,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    SQLiteLLMCallStore,
    load_llm_profile,
)
from finagent.research.us_agent_value_deepseek import (
    US_A0_STRUCTURED_PROMPT_TEMPLATE_ID,
    DeepSeekStructuredAgentSlotProvider,
    deepseek_v4_token_rates,
    estimate_deepseek_v4_cost_usd,
)
from finagent.research.us_agent_value_execution import build_us_a0_execution_plan
from finagent.research.us_agent_value_protocol import (
    USAgentValueArm,
    USAgentValuePhase,
    canonical_us_a0_experiment_protocol,
    canonical_us_a0_primitive_vocabulary,
)
from finagent.research.us_agent_value_provider import build_authorized_agent_generation_run

_FIXED_AT = datetime(2026, 9, 2, 0, 0, tzinfo=UTC)


class _QueueProvider:
    def __init__(self, outputs: list[str], *, model: str = "deepseek-v4-flash") -> None:
        self.outputs = list(outputs)
        self.model = model
        self.requests: list[LLMRequest] = []

    @property
    def provider_name(self) -> str:
        return "deepseek"

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if not self.outputs:
            raise AssertionError("fake provider output queue exhausted")
        output = self.outputs.pop(0)
        return LLMResponse(
            request_id=request.request_id,
            response_id=f"deepseek-test-{len(self.requests)}",
            provider="deepseek",
            model=self.model,
            output_text=output,
            usage=LLMUsage(
                input_tokens=100,
                output_tokens=20,
                total_tokens=120,
                cached_input_tokens=10,
            ),
            latency_ms=25.0,
            status="stop",
            metadata={"provider_attempts": "1", "reasoning_tokens": "5"},
        )


def _configured(outputs: list[str], *, model: str = "deepseek-v4-flash") -> tuple[ConfiguredLLM, _QueueProvider]:
    provider = _QueueProvider(outputs, model=model)
    profile = LLMProfile(
        name="deepseek-test",
        provider="deepseek",
        model=model,
        secret_id="deepseek_official",
        base_url="https://api.deepseek.com",
        thinking=True,
        reasoning_effort="high",
    )
    return ConfiguredLLM(profile=profile, provider=provider), provider


def _pilot_plan(*, model: str = "deepseek-v4-flash"):
    protocol = canonical_us_a0_experiment_protocol(USAgentValuePhase.PILOT)
    plan = build_us_a0_execution_plan(
        protocol,
        preregistration_bundle_id="us-a0-test-bundle",
        programmatic_seeds=(1729,),
        agent_provider_id="deepseek",
        agent_model_id=model,
        agent_prompt_template_id=US_A0_STRUCTURED_PROMPT_TEMPLATE_ID,
    )
    spec = next(item for item in plan.run_specs if item.arm is USAgentValueArm.AGENT)
    return protocol, plan, spec


def _candidate_json(index: int) -> str:
    candidate = canonical_us_a0_primitive_vocabulary().all_candidates()[index]
    return json.dumps(
        {
            "kind": candidate.kind.value,
            "window_bars": candidate.window_bars,
            "hypothesis_summary": f"Synthetic structured hypothesis {index + 1}.",
        }
    )


def test_shared_llm_config_defaults_to_official_v4_flash_and_retains_pro() -> None:
    config = Path("configs/llm.toml")

    default = load_llm_profile(config)
    pro = load_llm_profile(config, "deepseek_official_v4_pro")

    assert default.name == "deepseek_official_v4_flash"
    assert default.provider == "deepseek"
    assert default.model == "deepseek-v4-flash"
    assert default.secret_id == "deepseek_official"
    assert default.base_url == "https://api.deepseek.com"
    assert default.thinking is True
    assert default.reasoning_effort == "high"
    assert pro.model == "deepseek-v4-pro"
    assert pro.secret_id == default.secret_id


def test_deepseek_v4_pricing_uses_daily_peak_windows_including_weekends() -> None:
    saturday_peak = datetime(2026, 8, 22, 2, 0, tzinfo=UTC)
    saturday_offpeak = datetime(2026, 8, 22, 5, 0, tzinfo=UTC)

    flash_peak = deepseek_v4_token_rates("deepseek-v4-flash", saturday_peak)
    flash_offpeak = deepseek_v4_token_rates("deepseek-v4-flash", saturday_offpeak)
    pro_peak = deepseek_v4_token_rates("deepseek-v4-pro", saturday_peak)

    assert flash_peak.cached_input_per_million_usd == 0.014
    assert flash_peak.uncached_input_per_million_usd == 0.44
    assert flash_peak.output_per_million_usd == 1.32
    assert flash_offpeak.cached_input_per_million_usd == 0.007
    assert flash_offpeak.uncached_input_per_million_usd == 0.22
    assert flash_offpeak.output_per_million_usd == 0.66
    assert pro_peak.cached_input_per_million_usd == 0.044
    assert pro_peak.uncached_input_per_million_usd == 1.32
    assert pro_peak.output_per_million_usd == 3.96


def test_deepseek_v4_cost_uses_cached_uncached_and_output_tokens() -> None:
    response = LLMResponse(
        request_id="r",
        response_id="x",
        provider="deepseek",
        model="deepseek-v4-flash",
        output_text="{}",
        usage=LLMUsage(
            input_tokens=100,
            cached_input_tokens=20,
            output_tokens=30,
            total_tokens=130,
        ),
    )

    cost = estimate_deepseek_v4_cost_usd(
        "deepseek-v4-flash",
        response,
        priced_at=datetime(2026, 8, 22, 2, 0, tzinfo=UTC),
    )

    assert cost == pytest.approx((20 * 0.014 + 80 * 0.44 + 30 * 1.32) / 1_000_000)


def test_a0_adapter_reuses_shared_provider_for_exact_pilot_budget() -> None:
    outputs = [_candidate_json(index) for index in range(16)]
    configured, queue = _configured(outputs)
    protocol, plan, spec = _pilot_plan()
    provider = DeepSeekStructuredAgentSlotProvider(configured, clock=lambda: _FIXED_AT)

    run = build_authorized_agent_generation_run(
        protocol,
        plan,
        spec.run_spec_id,
        provider,
    )

    assert len(queue.requests) == 16
    assert len(run.accepted_candidates) == 16
    assert run.invalid_slot_count == 0
    assert run.duplicate_slot_count == 0
    assert run.repair_count == 0
    assert run.usage.llm_calls == 16
    assert run.usage.input_tokens == 1600
    assert run.usage.output_tokens == 320
    assert run.usage.cost_usd > 0
    assert all(request.model == "deepseek-v4-flash" for request in queue.requests)
    assert all(request.metadata["prompt_template_id"] == US_A0_STRUCTURED_PROMPT_TEMPLATE_ID for request in queue.requests)


def test_invalid_provider_json_consumes_slot_then_gets_one_repair(tmp_path: Path) -> None:
    outputs = ["not-json", _candidate_json(0)] + [
        _candidate_json(index) for index in range(1, 16)
    ]
    configured, queue = _configured(outputs)
    protocol, plan, spec = _pilot_plan()
    call_store = SQLiteLLMCallStore(tmp_path / "llm_calls.db")
    provider = DeepSeekStructuredAgentSlotProvider(
        configured,
        call_store=call_store,
        clock=lambda: _FIXED_AT,
    )

    run = build_authorized_agent_generation_run(
        protocol,
        plan,
        spec.run_spec_id,
        provider,
    )

    assert len(queue.requests) == 17
    assert len(run.accepted_candidates) == 16
    assert run.repair_count == 1
    assert run.usage.llm_calls == 17
    initial_record = call_store.get(queue.requests[0].request_id)
    repair_record = call_store.get(queue.requests[1].request_id)
    assert initial_record.planning_valid is False
    assert "invalid_json" in initial_record.validation_error
    assert repair_record.planning_valid is True


def test_execution_plan_model_identity_blocks_profile_drift_before_generation() -> None:
    configured, queue = _configured([_candidate_json(0)], model="deepseek-v4-pro")
    protocol, plan, spec = _pilot_plan(model="deepseek-v4-flash")
    provider = DeepSeekStructuredAgentSlotProvider(configured, clock=lambda: _FIXED_AT)

    with pytest.raises(ValueError, match="model_id"):
        build_authorized_agent_generation_run(
            protocol,
            plan,
            spec.run_spec_id,
            provider,
        )

    assert queue.requests == []

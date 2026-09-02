# US-A0 DeepSeek provider integration and A-share reuse boundary

US-A0 does not introduce a second independent LLM platform. The earlier A-share Agent work remains the shared host/provider/runtime layer; US-A0 adds a market- and experiment-specific research-governance layer on top of it.

## Reuse boundary

### Reused directly from the earlier Agent/A-share work

The following remain shared code and are consumed by US-A0 rather than reimplemented:

```text
src/finagent/agents/providers/base.py
  LLMRequest
  LLMResponse
  LLMUsage
  LLMProvider

src/finagent/agents/providers/config.py
  LLMProfile
  ConfiguredLLM
  load_llm_profile
  load_configured_llm
  external secret-file handling

src/finagent/agents/providers/openai_compatible.py
  OpenAICompatibleChatProvider
  DeepSeekChatProvider
  transport retry/backoff
  JSON response mode
  thinking / reasoning-effort request parameters
  cached/input/output/reasoning token extraction

src/finagent/agents/providers/store.py
  LLMCallStore
  SQLiteLLMCallStore
```

US-A0 therefore does not own API keys, HTTP clients, provider retries, credential files, or a second DeepSeek SDK wrapper. The A0-specific adapter receives a `ConfiguredLLM` and translates its structured response into the frozen `ProposalSlot` contract.

The same existing external secret remains valid:

```toml
[api_keys]
deepseek_official = "..."
```

No second U.S.-market API key configuration is required.

### A0-specific by design

The following are intentionally not inherited from the historical A-share factor-generation semantics:

```text
62-formula shared primitive vocabulary
MANUAL / PROGRAMMATIC / AGENT equal candidate budgets
CandidateGenerationRun / event identities
invalid + duplicate slot consumption
maximum one in-slot repair
no replacement slots
ExecutionPlan provider/model/run preregistration
shared US-B0 three-fold evaluator binding
Agent-value experiment evidence graph
Agent Value Gate policy and independent review
```

These contracts exist because US-A0 is a controlled causal comparison of search methods rather than a general-purpose factor-generation workflow.

### Not reused directly

The earlier `LLMFeatureGenerator` can emit bounded sandboxed Python feature programs. That behavior is useful for broad A-share discovery but would give the A0 AGENT arm a larger search space than the fixed MANUAL and PROGRAMMATIC controls. US-A0 therefore does **not** call that generator or its generated-Python sandbox during the controlled Agent-value experiment.

Likewise, A-share-specific market validation, holdout, reserve and promotion contracts are not silently applied to the U.S. intraday experiment. US-A0 uses its own certified XNYS 15m / same-session 60m RAW evidence path and later hands research candidates to US-R1 rather than importing A-share acceptance semantics.

This is intentional separation of research authority, not duplication of provider/runtime infrastructure.

## DeepSeek V4 profiles

The shared `configs/llm.toml` now keeps both official DeepSeek models:

```text
deepseek_official_v4_flash  -> deepseek-v4-flash
deepseek_official_v4_pro    -> deepseek-v4-pro
```

`deepseek_official_v4_flash` is the default engineering/test profile. V4-Pro remains an explicit profile and can be frozen into a different future ExecutionPlan when that choice is made before result inspection.

Changing model identity after an ExecutionPlan is frozen is forbidden: model/provider/prompt identity is part of each AGENT `CandidateGenerationRunSpec` and therefore changes the run-spec and plan identities.

## Current engineering smoke

The API/provider path may be tested before US-A0 stage authority because the smoke has no research authority:

```powershell
python scripts\smoke_llm_profile.py `
  --profile deepseek_official_v4_flash `
  --output reports\llm\deepseek_v4_flash_smoke.json
```

The report records provider/model, JSON capability, tokens, cached-input tokens, latency and a pricing-policy-bound diagnostic cost estimate. It explicitly carries:

```text
research_authority = false
stage_exit_authority = false
agent_value_gate_authority = false
alpha_authority = false
```

If the OpenAI SDK transport extra is not installed in the current environment, install the repository's existing shared LLM extra rather than a U.S.-specific dependency:

```powershell
pip install -e ".[llm]"
```

## Freeze an A0 ExecutionPlan from the shared public profile

No secret is read while freezing provider/model identity:

```powershell
python scripts\freeze_us_a0_execution_plan.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --llm-profile deepseek_official_v4_flash `
  --output reports\us_a0\us_a0_pilot_execution_plan.json
```

The public profile determines:

```text
provider_id = deepseek
model_id = deepseek-v4-flash
prompt_template_id = us-a0-structured-candidate-v1
```

An explicit `--agent-provider` or `--agent-model`, if supplied, must match the selected shared profile.

To intentionally freeze Pro instead:

```powershell
--llm-profile deepseek_official_v4_pro
```

That creates a different ExecutionPlan identity and is a different preregistered experiment execution.

## Real A0 Agent generation

`prepare_us_a0_agent_run.py` is the research-evidence path. It checks the public profile against the exact ExecutionPlan and then requires `docs/status.toml current_stage=US-A0` with accepted US-B0 predecessor authority **before** reading the API secret or constructing the external provider.

Only after that future authority exists may it be run:

```powershell
python scripts\prepare_us_a0_agent_run.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --execution-plan reports\us_a0\us_a0_pilot_execution_plan.json `
  --run-ordinal 1 `
  --llm-profile deepseek_official_v4_flash `
  --output reports\us_a0\generation\pilot_agent_01.json
```

At the present US-D3 project stage this command must fail before any external model call. Use `smoke_llm_profile.py` for current connectivity testing instead.

## Structured generation semantics

The DeepSeek adapter makes one initial structured request per frozen candidate slot. The response may contain only:

```json
{
  "kind": "momentum",
  "window_bars": 4,
  "hypothesis_summary": "short economic intuition"
}
```

The model never receives financial evaluation results during generation. It sees the frozen grammar and structures already accepted earlier in the same run. An invalid/duplicate initial response consumes its slot and receives at most one engineering-conformance repair. The existing `build_candidate_generation_run()` remains authoritative for final vocabulary, duplicate, repair and no-replacement semantics.

Provider/transport retries are separate from candidate repairs: retries address network/provider failures and do not expand the research trial budget.

## Cost evidence

The A0 adapter retains shared token telemetry and attaches a diagnostic USD estimate under the versioned policy:

```text
deepseek-v4-pricing-2026-08-17-v1
```

The policy freezes the official peak/off-peak schedule and V4-Flash/V4-Pro token rates effective from 2026-08-17. Cost remains diagnostic in Agent Value Gate v1; it is not a provider-independent pass/fail threshold.

If DeepSeek changes pricing, a new pricing-policy identity must be introduced rather than rewriting historical generation evidence.

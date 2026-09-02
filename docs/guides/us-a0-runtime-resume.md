# US-A0 DeepSeek runtime budget and resume-safe PILOT execution

This increment fixes the DeepSeek thinking-mode completion budget without rewriting already-frozen PILOT experiment identities.

## Why the V4-Flash smoke exhausted 256 tokens

DeepSeek V4 thinking mode emits `reasoning_content` before the final `content`. Both consume the completion/output-token budget. A tiny `max_output_tokens=256` request can therefore terminate with `finish_reason=length`, `reasoning_tokens=256` and empty final content even though API connectivity and reasoning are working.

FinAgent now uses a 65,536-token default ceiling for the DeepSeek V4 engineering smoke and the PILOT structured-generation runtime policy. The current provider maximum is frozen as 384,000 tokens. The ceiling is a limit, not a prepaid or automatically consumed amount.

The smoke can still be overridden explicitly:

```powershell
python scripts\smoke_llm_profile.py `
  --profile deepseek_official_v4_flash `
  --max-output-tokens 65536 `
  --output reports\llm\deepseek_v4_flash_smoke.json `
  --overwrite
```

The smoke remains engineering-only and never becomes Agent-value evidence.

## Existing frozen PILOT identities remain valid

Do not regenerate the already-frozen preregistration, V4-Flash ExecutionPlan, Gate policy or PILOT Launch Bundle just because the completion ceiling changed. `max_output_tokens` and reasoning effort are now frozen in a separate runtime-policy artifact so the existing experiment identities remain stable.

Current operator-frozen PILOT lineage includes:

```text
ExecutionPlan
us-agent-value-execution-plan-4312941b91abba09a44c34cb

Gate policy
us-agent-value-gate-policy-3c5c42ff29892af134773010

Launch Bundle
us-agent-value-pilot-launch-bundle-0b5d0e37cc62681d70f95901

MANUAL generation run
us-agent-value-generation-run-cf34df9b22107cbc37405849

PROGRAMMATIC generation run
us-agent-value-generation-run-94037a514ac060f3383c0b03

AGENT run spec
us-agent-value-generation-run-spec-90d98b3925764c799c35e08c
```

The runtime policy is intentionally layered on top of this lineage.

## Freeze the Agent runtime policy

This reads only the public LLM profile and existing frozen JSON. It does not load the API key or call DeepSeek:

```powershell
python scripts\freeze_us_a0_agent_runtime_policy.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --execution-plan reports\us_a0\us_a0_pilot_execution_plan.json `
  --gate-policy reports\us_a0\us_a0_pilot_gate_policy.json `
  --launch-bundle reports\us_a0\pilot_launch\us_a0_pilot_launch_bundle.json `
  --llm-profile deepseek_official_v4_flash `
  --max-output-tokens 65536 `
  --output reports\us_a0\pilot_launch\us_a0_agent_runtime_policy.json
```

The content-addressed policy binds:

```text
provider/model/prompt identity
thinking=true
reasoning_effort=high
max_output_tokens=65536
temperature=null
Chat Completions JSON-object API surface
transport retry/backoff/timeout values
pricing policy identity
ExecutionPlan ID
Launch Bundle ID
```

This prevents the same frozen Agent run spec from being executed later with a silently different reasoning budget.

## Prepare resume-safe orchestration

After the runtime policy is frozen, create the initial append-only checkpoint:

```powershell
python scripts\prepare_us_a0_pilot_orchestration.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --execution-plan reports\us_a0\us_a0_pilot_execution_plan.json `
  --gate-policy reports\us_a0\us_a0_pilot_gate_policy.json `
  --launch-bundle reports\us_a0\pilot_launch\us_a0_pilot_launch_bundle.json `
  --runtime-policy reports\us_a0\pilot_launch\us_a0_agent_runtime_policy.json `
  --output reports\us_a0\pilot_launch\checkpoint_00_prepared.json
```

At the current US-D3 stage it should report `ready_for_external_agent_generation=false` with `us_a0_stage_authority_not_ready`. That is the expected state.

The checkpoint chain is append-only:

```text
PREPARED
  -> AGENT_GENERATED
  -> RUN_EVIDENCE_COMPLETE
  -> EXPERIMENT_ASSEMBLED
  -> GATE_REVIEWED
```

Each checkpoint binds the prior checkpoint ID. Once an Agent generation-run ID, run-evidence manifest set, experiment graph or Gate review is recorded, later checkpoints cannot replace it.

## Resume semantics for the real Agent call

Future stage-authorized PILOT generation must supply the runtime policy and PREPARED checkpoint. The runner no longer supports overwriting research evidence.

If the Agent generation JSON already exists but the next checkpoint does not, the runner parses and reuses that exact generation run and writes the checkpoint without calling DeepSeek again. If the completed checkpoint already exists, the runner validates both artifacts and returns a resume/no-op result.

A damaged or identity-mismatched existing evidence file fails closed rather than triggering a fresh model call. This prevents repeated runs followed by cherry-picking.

The engineering smoke, runtime policy, research generation evidence and financial evidence remain separate authority surfaces.

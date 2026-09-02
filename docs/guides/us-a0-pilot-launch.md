# US-A0 PILOT launch bundle

The PILOT preregistration and ExecutionPlan answer different questions:

- preregistration freezes the shared search grammar, arm budgets and experiment semantics;
- ExecutionPlan freezes the exact MANUAL/PROGRAMMATIC/AGENT run specs, including PROGRAMMATIC seed and AGENT provider/model/prompt identity;
- the PILOT launch bundle freezes the deterministic control generation evidence before any real AGENT candidate or financial result exists.

The launch bundle exists because MANUAL/PROGRAMMATIC generation proposals carry `generated_at`, which participates in their content-addressed run identities even though it does not alter their structural candidate sets or financial evaluation. Freezing both control runs once avoids needless lineage drift between operator retries.

## Canonical frozen PILOT ExecutionPlan

For the currently preregistered PILOT bundle and the official DeepSeek V4-Flash testing profile, the canonical identities are:

```text
preregistration_bundle_id
us-agent-value-preregistration-9d592189de4ed0edf16e23c6

protocol_id
us-agent-value-experiment-protocol-d8b568d76dfa994b2711aa03

execution_plan_id
us-agent-value-execution-plan-4312941b91abba09a44c34cb

run specs
MANUAL        us-agent-value-generation-run-spec-9ec81b3df00991810108275e
PROGRAMMATIC  us-agent-value-generation-run-spec-18eb9cec17aa2b88a2af935e
AGENT         us-agent-value-generation-run-spec-90d98b3925764c799c35e08c

PROGRAMMATIC seed
1729

AGENT identity
deepseek / deepseek-v4-flash / us-a0-structured-candidate-v1
```

These values are now golden regression identities. If provider/model/prompt, seed, budget, vocabulary or preregistration semantics change, the plan/run-spec identities must change rather than silently reusing the frozen PILOT identity.

## Freeze the Gate policy first

The launch bundle requires the exact canonical PILOT Agent Value Gate policy, so freeze it before preparing launch evidence if it has not already been written:

```powershell
python scripts\freeze_us_a0_agent_value_gate_policy.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --output reports\us_a0\us_a0_pilot_gate_policy.json
```

This does not inspect Agent results.

## Prepare the PILOT launch bundle

```powershell
python scripts\prepare_us_a0_pilot_launch.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --execution-plan reports\us_a0\us_a0_pilot_execution_plan.json `
  --gate-policy reports\us_a0\us_a0_pilot_gate_policy.json `
  --output-root reports\us_a0\pilot_launch
```

The command does not read an API key, call DeepSeek, read market data or inspect any financial result. It writes:

```text
reports/us_a0/pilot_launch/
  pilot_manual_01.json
  pilot_programmatic_01.json
  us_a0_pilot_launch_bundle.json
```

The bundle binds:

```text
exact preregistration bundle ID
exact ExecutionPlan ID
exact Gate policy ID
one shared control-generated-at timestamp
exact MANUAL generation-run ID
exact PROGRAMMATIC generation-run ID
exact AGENT run-spec ID
DeepSeek provider/model/prompt identity
```

The real AGENT generation-run ID is deliberately absent because it cannot exist before the future external model call.

## Current-stage readiness check

The frozen launch/control evidence can be fully validated now without secrets or market data:

```powershell
python scripts\check_us_a0_pilot_launch.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --execution-plan reports\us_a0\us_a0_pilot_execution_plan.json `
  --gate-policy reports\us_a0\us_a0_pilot_gate_policy.json `
  --launch-bundle reports\us_a0\pilot_launch\us_a0_pilot_launch_bundle.json `
  --manual-run reports\us_a0\pilot_launch\pilot_manual_01.json `
  --programmatic-run reports\us_a0\pilot_launch\pilot_programmatic_01.json
```

At the current US-D3 project stage, the expected result is:

```text
ready_for_external_agent_generation = false
blockers = ["us_a0_stage_authority_not_ready"]
```

That is a correct preflight outcome. The command has no research or stage authority and does not prove DeepSeek connectivity. Provider connectivity remains the separate engineering smoke:

```powershell
python scripts\smoke_llm_profile.py `
  --profile deepseek_official_v4_flash `
  --output reports\llm\deepseek_v4_flash_smoke.json
```

## Future real AGENT generation

Once `docs/status.toml` has actually moved to `current_stage="US-A0"` with accepted US-B0 predecessor authority, the real PILOT Agent call must also consume the frozen launch bundle:

```powershell
python scripts\prepare_us_a0_agent_run.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --execution-plan reports\us_a0\us_a0_pilot_execution_plan.json `
  --gate-policy reports\us_a0\us_a0_pilot_gate_policy.json `
  --launch-bundle reports\us_a0\pilot_launch\us_a0_pilot_launch_bundle.json `
  --run-ordinal 1 `
  --llm-profile deepseek_official_v4_flash `
  --output reports\us_a0\generation\pilot_agent_01.json
```

For PILOT, omitting the Gate policy or launch bundle is fail-closed. The launch bundle does not authorize project-stage progression; `docs/status.toml` remains the sole stage authority.

## Authority boundary

The launch bundle and readiness report always retain:

```text
status_authority = false
stage_exit_authority = false
agent_value_gate_authority = false
alpha_authority = false
```

They freeze operator/evidence lineage only. Real Agent-value conclusions remain downstream of stage-authorized generation, the shared US-B0 evaluator, three-arm assembly and independent Agent Value Gate review.

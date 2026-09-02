# US-A0 PILOT run-evidence orchestration

This stage follows a successful `AGENT_GENERATED` checkpoint. It does not change the frozen candidate-generation trial budget or permit a second Agent draw.

## Ordered execution

PILOT has exactly three generation runs in the frozen ExecutionPlan order:

```text
1 MANUAL
2 PROGRAMMATIC
3 AGENT
```

`orchestrate_us_a0_pilot_run_evidence.py` validates the existing Launch Bundle, DeepSeek Runtime Policy, AGENT_GENERATED checkpoint, two frozen control runs and the exact Agent generation run before touching market data. It then delegates each run to the already authoritative `materialize_us_a0_run.py` three-fold evaluator.

The wrapper does not add another feature implementation or statistic implementation. Every run still uses the same US-B0-derived XNYS 15m / same-session 60m RAW feature, label and candidate evaluator.

## Two-phase run commit

Each run is first written below non-authoritative staging:

```text
data/us_a0/orchestration_work/<generation_run_id>/
```

The staged report is parsed with `parse_us_a0_run_evidence_bundle`. Only technically passing, content-addressed run evidence can produce a `promotion_intent.json`.

After that intent exists, the canonical run data/report directories are promoted. If the process crashes during promotion, the next invocation completes the same promotion and verifies the exact manifest identity. It does not rerun the run.

If staging exists without a promotion intent, no authoritative run evidence has been committed. That staging may be discarded and the deterministic financial materialization may be recomputed. This is distinct from Agent generation: the frozen Agent generation-run ID is never replaced or regenerated.

Canonical committed evidence is never overwritten.

## Append-only run progress

After each canonical run commit, the orchestrator writes:

```text
reports/us_a0/pilot_launch/run_progress/
  run_progress_01_manual.json
  run_progress_02_programmatic.json
  run_progress_03_agent.json
```

Each progress document contains the entire ordered committed prefix and binds the previous progress ID. A later run cannot be committed before an earlier run and an existing run manifest cannot be replaced.

Once all three run manifests are committed, the existing major orchestration chain advances exactly once:

```text
AGENT_GENERATED
  -> RUN_EVIDENCE_COMPLETE
```

with the exact ordered three run-evidence manifest IDs.

## Future command

This command is intentionally blocked until `docs/status.toml` authorizes US-A0 and the accepted US-B0 predecessor exists:

```powershell
python scripts\orchestrate_us_a0_pilot_run_evidence.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --execution-plan reports\us_a0\us_a0_pilot_execution_plan.json `
  --gate-policy reports\us_a0\us_a0_pilot_gate_policy.json `
  --launch-bundle reports\us_a0\pilot_launch\us_a0_pilot_launch_bundle.json `
  --runtime-policy reports\us_a0\pilot_launch\us_a0_agent_runtime_policy.json `
  --agent-generated-checkpoint reports\us_a0\pilot_launch\checkpoint_01_agent_generated.json `
  --manual-run reports\us_a0\pilot_launch\pilot_manual_01.json `
  --programmatic-run reports\us_a0\pilot_launch\pilot_programmatic_01.json `
  --agent-run reports\us_a0\generation\pilot_agent_01.json
```

At the current US-D3 stage, the command must fail before market-data execution. No existing preregistration, ExecutionPlan, Gate, Launch, Runtime Policy or PREPARED checkpoint should be regenerated merely to prepare this orchestration layer.

## Authority boundary

Run progress, promotion intent and `RUN_EVIDENCE_COMPLETE` checkpoint all carry no project-stage, Agent Value Gate or Alpha authority. They establish evidence completeness only. Experiment assembly and the separately preregistered Agent Value Gate review remain later steps.

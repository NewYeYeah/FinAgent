# US-A0 PILOT Experiment + Gate Orchestration

This guide covers the post-run US-A0 PILOT path after `checkpoint_02_run_evidence_complete.json` exists.

## Authority boundary

The post-run orchestrators do not read row-level market data and do not recompute RankIC, returns, turnover, coverage, or any other financial statistic. They strictly re-parse the already committed MANUAL / PROGRAMMATIC / AGENT run evidence and reuse the existing experiment assembler and preregistered Agent Value Gate implementation.

`EXPERIMENT_ASSEMBLED` and `GATE_REVIEWED` remain orchestration states only. They do not change `docs/status.toml`, do not create Alpha authority, and do not by themselves advance the project stage.

## Required predecessor state

Before this path can execute, the following chain must already exist:

```text
PREPARED
  -> AGENT_GENERATED
  -> RUN_EVIDENCE_COMPLETE
```

The final run-progress artifact must contain the exact committed prefix `MANUAL -> PROGRAMMATIC -> AGENT`, and its run-manifest IDs must equal the IDs frozen in the `RUN_EVIDENCE_COMPLETE` checkpoint.

## Stage 1: deterministic experiment assembly

Run only after the project is legitimately in US-A0 and the accepted US-B0 predecessor is recorded in `docs/status.toml`.

```powershell
python scripts\orchestrate_us_a0_pilot_experiment.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --execution-plan reports\us_a0\us_a0_pilot_execution_plan.json `
  --gate-policy reports\us_a0\us_a0_pilot_gate_policy.json `
  --launch-bundle reports\us_a0\pilot_launch\us_a0_pilot_launch_bundle.json `
  --runtime-policy reports\us_a0\pilot_launch\us_a0_agent_runtime_policy.json `
  --run-evidence-checkpoint reports\us_a0\pilot_launch\checkpoint_02_run_evidence_complete.json `
  --run-progress reports\us_a0\pilot_launch\run_progress\run_progress_03_agent.json `
  --manual-run reports\us_a0\pilot_launch\pilot_manual_01.json `
  --programmatic-run reports\us_a0\pilot_launch\pilot_programmatic_01.json `
  --agent-run reports\us_a0\generation\pilot_agent_01.json
```

The command deterministically writes or validates:

- three `SearchArmResult` artifacts;
- `us_a0_agent_value_experiment.json`;
- `us_a0_agent_value_comparison.json`;
- `us_a0_agent_value_evidence_graph.json`;
- `us_a0_pilot_gate_assessment.json`;
- `us_a0_pilot_experiment_assembly_manifest.json`;
- `checkpoint_03_experiment_assembled.json`.

Existing files are never overwritten. A rerun only succeeds when every existing artifact exactly equals deterministic reconstruction from the committed run evidence.

The assembly manifest binds:

```text
checkpoint_02
final run_progress
accepted US-B0 predecessor
Gate policy
three arm results
experiment
comparison snapshot
evidence graph
deterministic Gate assessment
```

The machine assessment is only a preregistered recommendation. It has no reviewer, project-stage, or Alpha authority.

## Stage 2: independent Gate review

The independent reviewer must use the exact `EXPERIMENT_ASSEMBLED` evidence. The review may accept the deterministic recommendation or conservatively downgrade it to `INCONCLUSIVE`; it may never upgrade the machine decision.

```powershell
python scripts\orchestrate_us_a0_pilot_gate_review.py `
  --preregistration reports\us_a0\us_a0_pilot_preregistration.json `
  --execution-plan reports\us_a0\us_a0_pilot_execution_plan.json `
  --gate-policy reports\us_a0\us_a0_pilot_gate_policy.json `
  --launch-bundle reports\us_a0\pilot_launch\us_a0_pilot_launch_bundle.json `
  --runtime-policy reports\us_a0\pilot_launch\us_a0_agent_runtime_policy.json `
  --run-evidence-checkpoint reports\us_a0\pilot_launch\checkpoint_02_run_evidence_complete.json `
  --run-progress reports\us_a0\pilot_launch\run_progress\run_progress_03_agent.json `
  --experiment-checkpoint reports\us_a0\pilot_launch\checkpoint_03_experiment_assembled.json `
  --manual-run reports\us_a0\pilot_launch\pilot_manual_01.json `
  --programmatic-run reports\us_a0\pilot_launch\pilot_programmatic_01.json `
  --agent-run reports\us_a0\generation\pilot_agent_01.json `
  --reviewer-id <REVIEWER_ID> `
  --review-notes "<SUBSTANTIVE_REVIEW_NOTES>" `
  --attest-thresholds-unchanged `
  --attest-evidence-lineage `
  --ack-alpha-gate-separate `
  --ack-stage-authority-separate
```

The script reconstructs the experiment and machine assessment before consuming reviewer authority. It then writes exactly one review plus `checkpoint_04_gate_reviewed.json`.

If the review JSON was written before a crash but the checkpoint was not, rerunning with the exact same reviewer input validates and reuses the existing review ID, then writes the missing checkpoint. Different reviewer identity, notes, decision, or attestations are rejected rather than replacing the previous review.

## PILOT interpretation

A positive PILOT review can only authorize consideration of FORMAL A0 after its exact review ID is explicitly accepted in `docs/status.toml`. PILOT never claims final Agent Value Gate authority.

A negative or inconclusive PILOT review cannot be upgraded by the orchestration layer. Agent Value Gate remains separate from the later US-R1 Alpha Gate.

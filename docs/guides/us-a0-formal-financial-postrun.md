# US-A0 FORMAL financial and post-run orchestration

This guide describes the FORMAL continuation after `checkpoint_01_agent_generation_complete.json`.
It does not authorize FORMAL execution by itself. `docs/status.toml` remains the sole project-stage
authority, and the exact accepted `PILOT_PROCEED_TO_FORMAL` review remains a required predecessor.

## Scope

The FORMAL ExecutionPlan is fixed at seven independent generation runs:

1. MANUAL × 1
2. PROGRAMMATIC × 3 (seeds 1729 / 2718 / 3141)
3. AGENT × 3

Each run uses the same frozen 32-slot candidate budget. Financial evaluation reuses
`materialize_us_a0_run.py`, which in turn reuses the existing US-B0 feature/label/evaluation
implementation. The orchestration layer never recomputes RankIC, returns, turnover or coverage.

## Financial evidence

`orchestrate_us_a0_formal_run_evidence.py` accepts exactly seven `--generation-run` files. Caller
ordering is ignored; files are rebound to the exact ExecutionPlan run specs. The final commit order
is always MANUAL, PROGRAMMATIC 1..3, AGENT 1..3.

Each run uses the same two-phase semantics as PILOT:

1. materialize in non-authoritative staging;
2. strictly parse the completed run evidence;
3. write a content-addressed promotion intent;
4. promote staged data/reports to canonical locations;
5. append one immutable FORMAL run-progress document.

If staging fails before a promotion intent exists, deterministic financial work may be recomputed.
After a promotion intent or canonical run manifest exists, recovery validates/reuses the exact
stored evidence and never overwrites it.

After all seven runs are committed, the orchestrator writes:

`reports/us_a0/formal_launch/checkpoint_02_run_evidence_complete.json`

The checkpoint binds all seven run-evidence manifest IDs and preserves the three Agent generation
run IDs frozen by checkpoint 01.

## FORMAL experiment assembly

`orchestrate_us_a0_formal_experiment.py` reconstructs the seven committed run evidence bundles and
calls the existing three-arm assembler and the existing Agent Value Gate assessment. It writes:

- FORMAL MANUAL / PROGRAMMATIC / AGENT SearchArmResult artifacts;
- AgentValueExperiment;
- structural comparison snapshot;
- experiment evidence graph;
- deterministic FORMAL Gate assessment;
- FORMAL Experiment Assembly Manifest;
- `checkpoint_03_experiment_assembled.json`.

The FORMAL Gate policy remains the preregistered policy: practical RankIC margin 0.01 and at least
2 of 3 independent Agent runs satisfying the paired quality-win rule, plus the frozen efficiency
and structural-novelty requirements.

## Independent review

`orchestrate_us_a0_formal_gate_review.py` reconstructs the experiment and machine assessment again
before accepting reviewer attestations. A reviewer may accept the machine decision or downgrade it
to INCONCLUSIVE, never upgrade it.

The review artifact may carry final Agent Value Gate authority because it is FORMAL. It never
carries Alpha authority, stage-exit authority or project-status authority. The orchestration
checkpoint itself also remains authority-free and only binds the immutable review ID.

A completed review writes:

`reports/us_a0/formal_launch/checkpoint_04_gate_reviewed.json`

## Current project state

Do not run the FORMAL commands while `docs/status.toml` remains before US-A0. FORMAL launch,
DeepSeek generation, financial materialization, experiment assembly and Gate review all require the
exact status-accepted PILOT review and the accepted US-B0 predecessor chain.

# US-A0 FORMAL orchestration

US-A0 FORMAL is intentionally conditional on a reviewed PILOT. It must not be prepared or executed merely because the code exists.

## Authority prerequisite

Before any FORMAL launch or external model call, `docs/status.toml` must still be the sole project-stage authority and must record:

- `current_stage = "US-A0"`;
- `stage.us_a0.pilot_gate_review_status = "accepted"`;
- the exact `pilot_gate_review_id`;
- `pilot_formal_progression_approved = true`.

The supplied review must rehash to that exact ID and must have decision `PILOT_PROCEED_TO_FORMAL`. The review has experiment-progression authority only; it does not create Alpha, order, stage-exit or project-stage authority.

## Frozen FORMAL shape

The existing FORMAL preregistration remains authoritative:

- 32 candidate slots per independent run;
- one MANUAL run;
- three PROGRAMMATIC runs using seeds `1729`, `2718`, `3141` unless the pre-result ExecutionPlan explicitly froze another valid set;
- three independent AGENT runs;
- identical candidate vocabulary and financial evaluator across all arms;
- FORMAL Gate repeatability requirement remains the separately frozen 2/3 rule.

`prepare_us_a0_formal_launch.py` may run only after the accepted PILOT review. It freezes one shared control timestamp, the exact MANUAL generation-run ID, three exact PROGRAMMATIC generation-run IDs, and the three AGENT run-spec IDs. Real Agent generation-run IDs remain pending.

## Runtime policy

`freeze_us_a0_formal_runtime_policy.py` binds the three AGENT runs to one content-addressed DeepSeek runtime policy. V1 keeps:

- `thinking=true`;
- the selected `reasoning_effort`;
- default `max_output_tokens=65536` with maximum 384000;
- `temperature=null`;
- API/schema surface;
- transport retries/backoff/timeout;
- the FORMAL ExecutionPlan, Launch Bundle and accepted PILOT review identities.

Sharing the runtime policy does not share prompt context: each AGENT run starts with an empty within-run accepted-candidate set and never receives candidates or evaluation results from another run.

## Slot-level resume semantics

FORMAL generation uses `orchestrate_us_a0_formal_agent_generation.py`, not the legacy single-run command.

Each of the three AGENT runs is processed in ordinal order. Each run consumes exactly slots 1..32. Every slot persists:

1. initial attempt evidence;
2. at most one repair attempt;
3. the final slot evidence;
4. an append-only slot-prefix progress document.

The request ID is deterministic for `(run_spec_id, slot_index, attempt_index)`. The shared SQLite call store therefore acts as an ambiguity detector. If provider telemetry proves a request already happened but the immutable attempt JSON is missing, orchestration fails closed instead of calling the model again. This prevents a crash from silently expanding the trial budget.

Once all 32 slots are complete, the slot proposals are passed through the existing `build_candidate_generation_run()` implementation. Slot evidence is an orchestration/audit layer only; it does not replace the authoritative A0 candidate-generation semantics.

After all three independent AGENT runs are complete, an append-only `AGENT_GENERATION_COMPLETE` checkpoint freezes the three run IDs. Later orchestration may not replace them.

## Direct-runner boundary

`prepare_us_a0_agent_run.py` remains the PILOT single-run path. Supplying a FORMAL preregistration now requires the accepted PILOT review and then fails with an instruction to use the FORMAL slot-resume-safe orchestrator. This closes the former bypass where FORMAL generation could reach a provider without the PILOT progression gate.

## Future continuation

This increment stops at `AGENT_GENERATION_COMPLETE`. The existing FORMAL-capable single-run financial materializer, experiment assembler and Gate reviewer remain reusable. A later increment should connect seven-run financial evidence, experiment assembly and final FORMAL Gate review to the FORMAL checkpoint chain without introducing a second financial/statistical implementation.

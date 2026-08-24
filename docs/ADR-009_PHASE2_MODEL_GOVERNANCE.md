# ADR-009 — Phase 2 Experiment and Model Governance Lifecycle

- Status: Accepted
- Date: 2026-08-24

## Context

Phase 1 persisted experiments and artifacts but did not own the lifecycle of an experiment run or a deployable model. A future Research Agent needs durable state, but permitting the Agent to mutate model status or infer success from conversational memory would make research decisions unauditable.

## Decision

### ExperimentRunner owns run state transitions

`ExperimentRunner` is ordinary deterministic Python. It performs:

```text
register spec/artifacts
    -> RUNNING
    -> evaluator
    -> ExperimentResult
    -> SUCCEEDED / FAILED
```

The evaluator supplies numerical metrics and produced artifacts. The runner supplies run identity, environment metadata, timestamps and terminal status.

Failures are persisted before the exception is re-raised.

### Model registry uses an explicit promotion state machine

A model artifact is wrapped by `RegisteredModel` and assigned a `ModelStage`:

```text
CANDIDATE
 -> VALIDATED
 -> PAPER
 -> SHADOW
 -> LIVE
 -> RETIRED
```

Retirement is permitted from any non-retired stage. Forward stage skipping is rejected.

All stage transitions create `ModelStageEvent` audit records containing:

```text
from_stage
to_stage
changed_at
reason
actor
```

A model cannot be moved to another stage by overwriting `register_model`; stage changes must call `promote_model`.

### SQLite registry remains the durable source of truth

`SQLiteResearchRegistry` now stores:

- artifacts;
- experiment specs;
- experiment runs;
- experiment results;
- registered models;
- model-stage events.

The registry is the machine-readable research memory layer. Chat history is not authoritative state.

## Important implementation correction

Phase 2 replaces `INSERT OR REPLACE` for run-state updates with SQLite UPSERT semantics.

SQLite `REPLACE` deletes the old row before inserting the replacement. Because `results.run_id` has a foreign key with `ON DELETE CASCADE`, replacing a run after registering its result could silently delete the result. The Phase 2 runner test exposed this behavior.

Run updates now use:

```sql
INSERT ...
ON CONFLICT(run_id) DO UPDATE ...
```

so terminal status updates preserve dependent results.

## Consequences

- a future Agent can propose experiments and promotion actions but cannot bypass lifecycle policy;
- failed runs are visible and queryable instead of disappearing from conversational context;
- model promotion is separate from numerical model fitting;
- live eligibility can later be guarded by deterministic validation policies without changing model implementations.

## Deferred

- binary model serialization and loading;
- metric-threshold policy engine for automatic validation;
- human approval tokens/signatures;
- shadow/live broker deployment;
- Agent tool wrappers around experiment/promotion operations.

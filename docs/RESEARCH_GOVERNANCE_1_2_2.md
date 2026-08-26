# FinAgent 1.2.2 — Research Program Lifecycle Governance

FinAgent 1.2.2 begins the post-1.2.1 research-governance hardening work. The first change is deliberately narrow: make the existing `ResearchProgram` budget ledger enforce an explicit lifecycle before sealed-holdout access.

## Why this change exists

Before 1.2.2, `ResearchProgramStatus` contained `OPEN` and `FROZEN`, but the persistent store had no transition API. The registered program payload was immutable, so an `OPEN` program could not actually become `FROZEN` through the public store. At the same time, `consume_sealed_holdout()` allowed access while a program was still open.

That combination weakened the intended statistical boundary:

```text
adaptive search
    ↓
freeze search space
    ↓
one-time sealed holdout
    ↓
final decision
```

The 1.2.2 lifecycle layer makes those states executable rather than documentary.

## State machine

```text
OPEN
  │
  │ freeze_program()
  ▼
FROZEN
  │
  │ optional one-time sealed holdout access
  │
  │ close_program()
  ▼
CLOSED
```

Allowed transitions are only:

```text
OPEN   -> FROZEN
FROZEN -> CLOSED
```

There is no reopen transition. Lifecycle events are append-only.

## Core invariants

### New research requires `OPEN`

A new `(program_id, family_id)` reservation is rejected once the program is frozen or closed.

### Exact replay remains possible after freezing

FinAgent 1.2.1 introduced deterministic frozen-family replay. Research governance must not break that capability.

Therefore an already-reserved plan with the exact same family ID and fingerprint remains idempotently reservable after freeze/close. A different fingerprint under the same family ID still fails, and a new family cannot be added.

This distinction is intentional:

```text
FROZEN
  existing exact plan replay -> allowed
  new hypothesis/family      -> denied
  changed existing family    -> denied
```

### Sealed holdout requires `FROZEN`

`consume_sealed_holdout()` fails while the program is `OPEN`. The search space must be frozen before the one-time holdout token can be consumed.

### Holdout access remains one-time

The existing `research_program_holdout_access` uniqueness contract remains in force. A second access attempt fails closed.

### Programs with a configured holdout cannot close before consuming it

If `sealed_holdout_id` is non-empty, `close_program()` requires the holdout-access record to exist. Programs without a configured sealed holdout may close directly after freezing.

## Persistence model

The immutable `research_programs.payload_json` row is retained for backward compatibility. Lifecycle is stored separately in:

```text
research_program_lifecycle_events
```

Each transition records:

```text
program_id
from_status
to_status
actor
reason
occurred_at
```

The effective program status is the latest lifecycle target status, falling back to the immutable registered status when no lifecycle event exists.

This preserves older databases without rewriting their registration payloads.

## New public contracts

```text
ResearchProgramStatus.CLOSED
ProgramLifecycleEvent
ProgramLifecycleSnapshot
SQLiteResearchProgramStore.freeze_program(...)
SQLiteResearchProgramStore.close_program(...)
SQLiteResearchProgramStore.lifecycle_events(...)
SQLiteResearchProgramStore.lifecycle_snapshot(...)
```

## Verification targets

The 1.2.2 lifecycle tests cover:

```text
OPEN holdout access fails
OPEN -> FROZEN works
new research after freeze fails
exact existing reservation replay after freeze succeeds
changed existing family fails
close before configured holdout consumption fails
holdout can be consumed only once
FROZEN -> CLOSED works
lifecycle transitions are append-only and idempotent
closed programs reject new research
programs without a holdout can close after freeze
```

The older quant-core sealed-holdout regression is updated to freeze the program before consuming its holdout.

## Deliberate boundary

This first 1.2.2 PR does **not** yet solve the full post-1.2.1 governance roadmap. In particular it does not yet add:

```text
ResearchMemory visibility classes
sealed-holdout dataset evaluation runner
promotion gate integrating DSR/PBO/Reality Check
holdout evidence isolation from adaptive Agent memory
provider capability v2 / runtime entitlement snapshots
```

Those changes should build on this lifecycle contract rather than be mixed into the same PR.

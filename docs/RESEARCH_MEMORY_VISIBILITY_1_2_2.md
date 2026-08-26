# FinAgent 1.2.2 — Research Memory Visibility and OOS Isolation

This governance slice adds a program-scoped read boundary between structured evidence memory and adaptive research Agents.

## Code-level problem

Phase 5.5 memory intentionally preserves a complete evidence graph. Before this change, the Agent memory tools called the raw `ResearchMemoryService` / `SQLiteResearchMemoryStore` queries directly. Therefore every stored `RESULT`, `FAILURE`, operational outcome and lineage node was potentially visible to the Agent regardless of whether the evidence came from development, validation or a sealed holdout.

That is incompatible with a promotion-grade protocol:

```text
adaptive development
      ↓
freeze ResearchProgram
      ↓
one-time sealed holdout
      ↓
final decision
```

If the holdout result is written to normal memory and later returned through `inspect_research_hypothesis`, lineage, failure or budget tools, a later adaptive search can indirectly condition on OOS evidence.

## Architecture

The underlying memory store remains complete and audit-readable. Agent visibility is a separate immutable classification layer:

```text
SQLiteResearchMemoryStore
        │
        ├── full audit / deterministic evaluator reads
        │
        └── SQLiteMemoryVisibilityStore
                    ↓
             AgentResearchMemoryView
                    ↓
             Agent memory tools
```

The read boundary does not delete, redact or rewrite the underlying evidence.

## Visibility classes

```text
SHARED
DEVELOPMENT
VALIDATION
SEALED_HOLDOUT
OPERATIONAL
```

Rules for adaptive research Agents:

```text
unbound legacy node     -> readable (backward compatibility)
SHARED                  -> readable by every program
DEVELOPMENT             -> readable only by owning program
VALIDATION              -> readable only by owning program
SEALED_HOLDOUT          -> never readable
OPERATIONAL             -> never readable as adaptive research evidence
```

Development, validation and sealed-holdout bindings require a `program_id`. A SHARED node cannot be owned by a specific program.

Bindings are immutable. Result-dependent code cannot relabel one classified node from `SEALED_HOLDOUT` to `SHARED` after observing its metrics.

## Program identity propagation

No new global state is introduced. `AgentRunCoordinator` already writes `plan.program_id` into `AgentRunContext.metadata`.

`ResearchMemoryToolDependencies` derives `AgentResearchMemoryView` from that run context, so every Agent memory tool uses the active research-program identity automatically.

The scoped view covers:

```text
list hypotheses
inspect hypothesis summary
find similar hypotheses
inspect lineage
inspect failures
recommend research budget
```

Direct raw-store access remains unrestricted for deterministic audit and promotion code.

## Leakage controls

A hidden node is removed from the Agent graph together with incident edges. If the Agent requests a hidden node directly by key, the view fails closed with `PermissionError` rather than confirming its contents.

Budget recommendation is recomputed from the visible graph. A sealed-holdout passing result therefore cannot increase `supporting_result_count`; a sealed-holdout failure cannot increase the Agent-visible prior-failure count.

## Compatibility boundary

Existing Phase 5.5 nodes have no visibility binding. They remain readable as legacy/shared evidence so this change does not silently erase the historical memory corpus.

This means classification is mandatory for new sensitive evidence. The visibility layer alone does not magically infer that a raw `register_result()` call came from a sealed holdout.

The next sealed-holdout evaluation slice must therefore use a governed writer/evaluator that records the OOS result and its `SEALED_HOLDOUT` binding as one controlled workflow. Calling the legacy raw writer and omitting classification is not a certified holdout path.

## Verification targets

Regression tests prove that:

```text
sealed result remains in raw audit memory
sealed result disappears from Agent hypothesis summary
sealed result cannot be inspected directly by Agent lineage tool
sealed result does not influence Agent budget supporting-result count
program A development/validation evidence is hidden from program B
sealed failures are hidden from Agent failure and budget queries
Agent tools derive program scope from AgentRunContext.metadata
visibility bindings are immutable
unknown memory-node bindings fail closed
legacy and explicit SHARED nodes remain readable
```

## Deliberate remaining work

This slice does not yet implement:

```text
sealed-holdout dataset runner
atomic scoped evidence writer
promotion gate combining DSR / PBO / Reality Check
visibility classification for hypothesis revisions themselves
cross-program publication workflow for approved prior evidence
```

The important invariant for subsequent work is that **sealed numeric evidence must never be supplied to an adaptive research Agent through the memory tools**.

# ADR-012 — Phase 3B Deterministic Scripted Research Agent

Status: **Accepted**

## Context

Phase 3A froze the governed Agent control surface but intentionally supplied no runtime implementation. Before an LLM planner is connected, FinAgent needs to prove that the Agent contracts, ToolRegistry, policy layer, research lifecycle, family-level anti-overfitting controls and audit trail can support a complete autonomous workflow deterministically.

## Decision 1 — Phase 3B adds a deterministic `ScriptedResearchAgent`

The runtime implements the existing `AgentRuntime` protocol and receives only:

```text
AgentTask
ToolRegistry
AgentRunContext
```

It is constructed with a frozen `ResearchPlan`, an approved `ExperimentTemplateRegistry`, and an Agent plan/audit store. It receives no direct `SQLiteResearchRegistry`, `ExperimentRunner`, portfolio service, risk gate, execution adapter or broker interface.

Canonical orchestration:

```text
inspect state
 -> create family
 -> register approved variants
 -> run variants
 -> compare persisted metrics
 -> seal deterministic winner
 -> freeze family
 -> validate complete frozen family
 -> optional promotion request
 -> terminal AgentDecision
```

## Decision 2 — research search budgets are immutable plan inputs

`ResearchBudget` freezes:

```text
max_tool_calls
max_experiments
max_family_size
max_failed_experiments
allow_new_family
allow_promotion_request
```

`ResearchPlan` rejects itself if its declared maximum tool calls or variant count exceed the budget. Poor results cannot cause the scripted Agent to silently extend the search.

## Decision 3 — plans and variants are typed and fingerprinted

`ResearchPlan`, `ExperimentVariant` and `PromotionIntent` are typed, immutable objects. The plan SHA-256 fingerprint includes task id, planner version, family definition, approved template id, ordered variants, parameters, research budget and promotion intent.

`AgentRunCoordinator` writes the fingerprint into immutable `AgentRunContext.metadata`, and `ScriptedResearchAgent` rejects execution when the runtime plan, persisted plan and registered run context disagree.

## Decision 4 — experiment construction comes from an approved template registry

`ExperimentTemplateRegistry` maps a finite `template_id` to:

```text
approved evaluator id
dataset artifact
code artifact
universe
parameter allowlist
seed
```

A variant can only supply the parameters declared by that template. Phase 3B still does not permit arbitrary Agent-generated Python.

## Decision 5 — winner selection is deterministic and sealed before family validation

The reference policy is:

```text
primary metric descending
 -> tie-break metric ascending
 -> experiment_id lexicographic
```

Only experiments with a persisted primary metric and no failed result flag are eligible. The selected experiment is persisted as a `selection_sealed` plan event before the family is frozen and validated.

The Agent does not receive outer-test data or statistical threshold controls through this selection path.

## Decision 6 — failed trials remain part of the research record

Evaluator failures persist through the existing `ExperimentRunner` lifecycle. The scripted Agent may stop when `max_failed_experiments` is exceeded, but it does not remove failed experiments from family membership. This preserves the Phase 2.5 multiplicity denominator.

## Decision 7 — run lifecycle belongs to `AgentRunCoordinator`

The coordinator owns:

```text
create immutable run context
 -> audit.start_run
 -> persist ResearchPlan
 -> runtime.run
 -> audit.finish_run
```

Unexpected runtime exceptions are converted into a terminal FAILED `AgentDecision` and persisted. This lifecycle can be reused unchanged by Phase 3C provider-backed runtimes.

## Decision 8 — replay compares governed actions, not generated prose

`AgentReplayEngine` reconstructs the ordered audited sequence:

```text
tool name
arguments
tool result status
policy outcome
sealed selection
```

A dry replay never re-runs mutating handlers. Two isolated deterministic runs can be normalized and compared while ignoring run ids and timestamps.

## Consequences

Positive:

- FinAgent now has a complete Agent loop without LLM nondeterminism.
- Search budgets and plans are auditable and fingerprinted.
- The same ToolRegistry/policy surface can be reused by Phase 3C.
- Failed trials cannot be silently removed after observing results.
- Replay provides a reference oracle for later LLM orchestration testing.

Trade-offs:

- The scripted planner is intentionally narrow.
- Approved experiment templates must be registered ahead of time.
- Resume/checkpoint semantics remain limited to new immutable Agent runs rather than in-place mutation.
- Phase 3B still does not generate hypotheses or Python code dynamically.

These constraints are intentional. Phase 3C may add an LLM planner, but it must emit actions through the same typed plan/tool boundary.

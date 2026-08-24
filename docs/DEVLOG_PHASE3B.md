# FinAgent Development Log — Phase 3B

Date: 2026-08-24

## Goal

Implement the first complete Agent orchestration loop without introducing an LLM. Phase 3B is a deterministic reference runtime used to validate planning, policy, budgeting, audit and replay before Phase 3C adds model-provider nondeterminism.

## Implemented

### Planning and budgets

Added `ResearchBudget`, `ExperimentVariant`, `PromotionIntent`, `ResearchPlan`, `ResearchRunSummary` and `SQLiteAgentPlanStore`.

`ResearchPlan` is immutable and receives a task-scoped SHA-256 fingerprint. Declared variants and maximum tool calls must fit the immutable research budget before execution starts.

### Approved experiment templates

Added `ExperimentTemplate` and `ExperimentTemplateRegistry`. A template owns its evaluator id, data/code artifacts, universe, allowed parameter names and seed. Scripted variants cannot add arbitrary parameters.

### Deterministic runtime

Added `ScriptedResearchAgent`, implementing the existing Phase 3A `AgentRuntime` protocol. It uses only `ToolRegistry` and does not receive direct research-registry, portfolio, risk or execution mutation services.

Reference workflow:

```text
list families
 -> create family
 -> register variants
 -> run variants
 -> compare primary metric
 -> compare tie-break metric
 -> seal deterministic winner
 -> freeze family
 -> validate family
 -> optional promotion request
```

The winner rule is primary metric descending, tie-break metric ascending, then experiment id.

### Failure semantics

Evaluator failures remain durable through `ExperimentRunner`; failed experiments remain family members. The scripted Agent stops when its immutable `max_failed_experiments` budget is exceeded rather than silently extending the search.

### Run lifecycle

Added `AgentRunCoordinator`. It creates the immutable `AgentRunContext`, starts Agent audit, persists the research plan, invokes the runtime and always writes a terminal `AgentDecision`. Unexpected runtime exceptions are converted to durable FAILED decisions.

### Replay

Added `AgentReplayEngine`. Dry replay reconstructs tool name, arguments, tool status, policy outcome and sealed selection without re-running mutating handlers. Two isolated deterministic runs can be normalized and compared.

## Validation

The first Phase 3B PR CI run passed Python 3.11, 3.12 and 3.13 with the complete suite:

```text
90 passed
```

New integration tests cover plan fingerprinting, budget rejection, complete scripted workflow, deterministic winner selection, failed-trial preservation, append-only plan registration and isolated replay equivalence.

## Dependencies

No new runtime dependency was added. Phase 3B still requires no OpenAI/Anthropic SDK, LangGraph, AutoGen, broker SDK or arbitrary code sandbox.

## Next step

Phase 3C should introduce a provider-agnostic LLM planner while preserving the same `ResearchPlan` / `ToolRegistry` / policy / audit contracts. The LLM must not gain portfolio-weight authority, risk-gate bypasses, fill-price control, direct model-stage mutation or arbitrary Python execution.

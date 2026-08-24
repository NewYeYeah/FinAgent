# Phase 3B — Deterministic Scripted Research Agent

## Status

Phase 3B implements the first complete Agent orchestration loop without an LLM. The purpose is to validate the Agent architecture before provider/network/model nondeterminism is introduced.

## Runtime path

```text
AgentTask
  -> AgentRunCoordinator
  -> immutable AgentRunContext + ResearchPlan
  -> ScriptedResearchAgent
  -> ToolCallRequest[]
  -> ToolRegistry
  -> AgentPolicyEngine
  -> Research Control Plane
  -> ToolCallResult[]
  -> AgentDecision
  -> SQLiteAgentAuditStore + SQLiteAgentPlanStore
```

The scripted runtime receives no direct research-registry, portfolio, risk or execution mutation interface.

## Implemented components

### Typed research planning

```text
ResearchBudget
ExperimentVariant
PromotionIntent
ResearchPlan
ResearchRunSummary
```

The plan is SHA-256 fingerprinted using the task id, planner version, family definition, template id, ordered variants/parameters, budget and optional promotion intent.

`ResearchBudget` limits tool calls, experiment count, family size and tolerated failed experiments. A plan that exceeds those limits is rejected before execution.

### Approved template registry

```text
ExperimentTemplate
ExperimentTemplateRegistry
```

Templates own approved evaluator ids, dataset/code artifacts, universe, parameter allowlists and seed. Variants cannot add undeclared parameters.

### Deterministic runtime

`ScriptedResearchAgent` currently executes:

```text
list families
 -> create family
 -> register variants
 -> run variants
 -> compare primary metric
 -> compare tie-break metric
 -> seal winner
 -> freeze family
 -> validate family
 -> optional model-promotion request
```

Winner policy:

```text
primary metric descending
 -> tie-break metric ascending
 -> experiment_id
```

The winner is sealed before family validation.

### Run coordinator

`AgentRunCoordinator` owns run creation and terminal persistence. Unexpected runtime exceptions become a terminal FAILED `AgentDecision` rather than leaving an open audit run.

### Replay

`AgentReplayEngine.dry_replay` reconstructs tool order, arguments, policy outcome, tool status and sealed selection without invoking mutations. Normalized traces from isolated deterministic runs can be compared for equality.

## Failure semantics

- `DENIED` tool call -> terminal BLOCKED Agent run.
- `FAILED` tool call -> terminal FAILED by default.
- model promotion requiring human approval -> terminal BLOCKED with explicit `waiting_for_approval=true` metadata; no model mutation occurs.
- evaluator failure -> existing ExperimentRunner persists FAILED run state.
- failed experiments remain registered family members.
- search budgets are not expanded after poor results.

## Current vertical slice

The integration test uses an approved AR-order research template with three deterministic variants:

```text
AR(1)
AR(2)
AR(3)
```

The test evaluator is deliberately synthetic: Phase 3B validates orchestration, governance and replay rather than claiming investment performance. The production template registry is generic and can later bind approved templates to the existing Phase 1/2 numerical stack.

## Test coverage

Phase 3B adds coverage for:

- task-scoped stable plan fingerprints;
- plan-vs-budget rejection;
- template parameter allowlists;
- complete scripted research workflow;
- deterministic winner selection;
- failed-trial preservation;
- append-only plan registration;
- dry replay equivalence across isolated runs.

The first Phase 3B CI validation passed on Python 3.11, 3.12 and 3.13. The complete suite contains 90 tests before the final documentation/version commit.

## Explicitly deferred to Phase 3C+

Phase 3B does not include:

```text
LLM inference
natural-language planning
provider retries/token accounting
free-form hypothesis generation
arbitrary Python generation
sandbox execution
LangGraph
broker access
portfolio-weight decisions
```

Phase 3C should replace only the deterministic planning/orchestration intelligence. The ToolRegistry, policy, research budgets, validation, risk and execution boundaries remain deterministic.

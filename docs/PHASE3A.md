# Phase 3A — Governed Agent Control Surface

## Objective

Phase 3A implements the framework-independent boundary between a future Research Agent and FinAgent's deterministic Research Control Plane. No LLM is introduced in this phase.

The canonical path is:

```text
AgentTask + AgentRunContext
        -> ToolCallRequest
        -> ToolRegistry
        -> ToolSpec / budget / argument schema
        -> DefaultResearchAgentPolicy
        -> deterministic research tool
        -> Research Control Plane
        -> ToolCallResult
        -> SQLiteAgentAuditStore
```

The Agent never receives a direct portfolio/execution mutation API.

## Agent domain

Added `finagent.agents.domain`:

```text
AgentAction
AgentTask
AgentRunContext
ToolCallRequest
ToolCallResult
PolicyDecision
AgentDecision
AgentAuditEvent
```

All timestamps are timezone-aware. Public mappings are defensively copied and read-only. Tool-call budgets and optional per-run tool allowlists are part of `AgentRunContext` rather than informal prompt instructions.

`AgentRuntime` is a Protocol only. Phase 3A therefore freezes the runtime interface without committing FinAgent to LangGraph or a particular model provider.

## Governed ToolRegistry

`ToolRegistry` is the only intended action surface for an Agent runtime. It provides a finite set of `ToolSpec` definitions and governed invocation.

Invocation order:

```text
persist request
 -> enforce run budget
 -> resolve registered tool
 -> validate exact arguments
 -> evaluate deterministic policy
 -> execute admissible handler
 -> persist result
```

Unknown tools, unexpected arguments and exhausted budgets are denied and auditable.

Phase 3A registers fourteen research actions:

```text
inspect_data_contract
list_experiment_families
inspect_experiment_family
list_experiments
inspect_experiment
compare_experiment_results
inspect_model_registry
inspect_model_history
create_experiment_family
register_experiment
run_experiment
freeze_experiment_family
validate_experiment_family
request_model_promotion
```

No portfolio-weight, risk-bypass, fill-price, experiment-deletion, direct model-promotion or broker-order action is registered.

## Research tools

### Read path

`SQLiteResearchQueryService` provides a typed read-only facade for families, experiments, runs/results, models and model history. Tool handlers do not depend on private registry SQL helpers.

### Experiment execution

`ExperimentEvaluatorRegistry` is a finite registry of approved deterministic evaluator/template ids.

A new experiment must name an approved `evaluator_id`; `run_experiment` resolves the persisted identifier and delegates lifecycle handling to the existing `ExperimentRunner`.

Arbitrary generated Python remains out of scope until Phase 3D.

### Family validation

The Agent-facing validation tool accepts only:

```text
family_id
selected_experiment_id
```

Returns and p-values are loaded through a trusted `FamilyValidationInputProvider`. DSR/PBO/bootstrap settings are supplied by fixed `FamilyValidationPolicy`. Therefore the Agent cannot weaken Phase 2.5 validation by changing thresholds in a tool call.

### Model promotion

`request_model_promotion` is non-mutating. It validates the requested domain transition and returns a review payload with:

```text
mutation_performed = false
```

Requests to `SHADOW` or `LIVE` require human approval under the default policy. A human-required REQUEST tool may materialize its non-mutating request payload before approval; ordinary mutating tools do not run while approval is pending.

## Policy-as-code

`DefaultResearchAgentPolicy` currently enforces:

- optional run-specific allowlists;
- finite registered action surface;
- promotion-request stage policy;
- human approval for `SHADOW` and `LIVE` requests.

Existing domain services continue to enforce family lifecycle, experiment lifecycle and legal model transitions. Policy does not duplicate those invariants.

## Audit subsystem

`SQLiteAgentAuditStore` persists:

```text
agent_runs
agent_tool_calls
agent_policy_decisions
agent_audit_events
```

The audit trail records denied actions as well as successful actions and can replay the original tool request sequence. It may share a database file with the research registry while keeping a separate table namespace and responsibility boundary.

## Tests

Phase 3A adds deterministic coverage for:

- timezone/budget/allowlist validation;
- defensive Agent request mappings;
- denial and audit of unregistered tools;
- per-run allowlists;
- exact argument schemas;
- tool-call budgets;
- exact research tool surface;
- create/register/run/inspect experiment workflow;
- frozen-family membership protection;
- non-mutating model-promotion requests;
- human approval materialization for legal SHADOW requests;
- rejection of illegal stage skipping before human approval;
- trusted family-validation input sourcing;
- prevention of Agent-supplied validation-threshold overrides.

The first Phase 3A pull-request CI run passed on Python 3.11, 3.12 and 3.13 with the complete suite. A final CI run is required after the Phase 3A documentation/refinement commit before `main` is advanced.

## Explicitly deferred

Phase 3A does not implement:

- an LLM provider;
- a scripted planner/runtime implementation;
- natural-language tool selection;
- generated Python features;
- sandbox execution;
- LangGraph/checkpointing;
- human approval UI;
- live broker actions;
- direct Agent model promotion.

## Next step — Phase 3B

Phase 3B will implement `ScriptedResearchAgent`, a deterministic planner that uses exactly the same `AgentRuntime` and `ToolRegistry` contracts intended for Phase 3C.

The first end-to-end scripted workflow should be:

```text
Research question
 -> start Agent run
 -> inspect existing families
 -> create OPEN family
 -> register approved variants
 -> run experiments
 -> compare persisted results
 -> freeze family
 -> validate frozen family
 -> create promotion request when appropriate
 -> finish Agent run
```

This proves orchestration, replay, budgets, policy and audit semantics independently of LLM variability.

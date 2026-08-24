# ADR-011 — Phase 3A Governed Agent Control Surface

Status: **Accepted**

## Context

Phase 0.5–2.5 established a framework-independent Quant Engine and a deterministic Research Control Plane. Phase 3A introduces the first Agent-facing API, but intentionally does **not** introduce an LLM runtime. The purpose is to freeze what an Agent may ask the system to do before any stochastic planner is connected.

The central risk is privilege inversion: if an Agent receives direct Python objects or unrestricted functions, a future LLM could bypass experiment-family multiplicity controls, mutate model stages, select portfolio weights, alter fills, or change validation thresholds after seeing results.

## Decision 1 — Agent actions are a finite domain enum

`AgentAction` is the canonical action vocabulary. Phase 3A registers exactly fourteen actions:

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

`ToolSpec.name` must equal the corresponding `AgentAction.value`. Arbitrary function names cannot become Agent capabilities accidentally.

Explicitly absent from the registry are actions such as:

```text
set_portfolio_weights
bypass_risk_gate
set_fill_price
edit_backtest_result
delete_failed_experiment
remove_family_member
promote_model
execute_broker_order
```

Absence is the primary authorization boundary: an unregistered action is denied and audited before any handler can run.

## Decision 2 — tool invocation is always governed

The canonical invocation path is:

```text
ToolCallRequest
    -> durable request audit
    -> tool-call budget
    -> registered ToolSpec
    -> argument schema
    -> AgentPolicyEngine
    -> ALLOW / DENY / REQUIRE_HUMAN
    -> deterministic handler when admissible
    -> durable ToolCallResult audit
```

`ToolRegistry` keeps handlers private and exposes only names/specifications plus governed `invoke`. A runtime is never given the underlying research registry or raw handlers as its normal action surface.

Unknown tools, invalid arguments and exhausted budgets produce explicit policy decisions rather than untracked exceptions.

## Decision 3 — policy is ordinary deterministic code

`DefaultResearchAgentPolicy` is independent of any LLM provider. It supports per-run allowlists and a fixed model-promotion request policy.

For model promotion:

```text
VALIDATED / PAPER -> Agent may create a request
SHADOW / LIVE     -> request requires human approval
RETIRED           -> Agent promotion request is denied
```

Existing `validate_model_transition` rules still determine whether the requested transition is legal from the model's current stage.

A `REQUIRE_HUMAN` action executes a handler only when its `ToolMode` is `REQUEST`. REQUEST tools are contractually non-mutating; execution is used only to validate domain legality and materialize the exact review payload. Ordinary READ/WRITE handlers do not execute before approval.

## Decision 4 — model promotion remains request-only

`request_model_promotion` deliberately does not call `SQLiteResearchRegistry.promote_model`.

It returns:

```text
model_id
from_stage
to_stage
reason
requested_by
requested_at
mutation_performed = false
```

Therefore an Agent cannot change model stage through Phase 3A. Human/policy approval and an explicit deterministic promotion service remain a separate future step.

## Decision 5 — statistical policy cannot be supplied by the Agent

`validate_experiment_family` accepts only:

```text
family_id
selected_experiment_id
```

The Agent cannot supply trial returns, p-values, DSR thresholds, PBO thresholds, bootstrap configuration, or random seed.

Family returns/p-values come from a trusted `FamilyValidationInputProvider`. Statistical thresholds come from immutable `FamilyValidationPolicy` configuration. The existing Phase 2.5 `ExperimentFamilyValidator` still enforces exact pre-registered family membership.

This prevents result-dependent calls such as:

```text
validate_experiment_family(..., pbo_threshold=0.99)
```

from weakening the research gate.

## Decision 6 — experiment execution uses an approved evaluator registry

`ExperimentEvaluatorRegistry` is a finite allowlist of deterministic evaluator/template identifiers. `register_experiment` requires an approved `evaluator_id`, which becomes part of the persisted experiment metadata. `run_experiment` resolves that identifier and delegates lifecycle handling to the existing `ExperimentRunner`.

Phase 3A does not permit arbitrary Agent-supplied Python code.

## Decision 7 — Agent audit state is separate from numerical research state

`SQLiteAgentAuditStore` owns only `agent_*` tables:

```text
agent_runs
agent_tool_calls
agent_policy_decisions
agent_audit_events
```

It may share the same SQLite file with `SQLiteResearchRegistry`, but it does not replace research tables as the source of truth.

The audit sequence records at least:

```text
RUN_STARTED
TOOL_REQUESTED
POLICY_DECIDED
TOOL_FINISHED
RUN_FINISHED
```

Requests are replayable in original sequence. Agent audit tables use restrictive foreign keys rather than delete cascades from ordinary research operations.

## Decision 8 — query access uses a read-only facade

`SQLiteResearchQueryService` provides typed list/inspection methods over the existing registry. Agent tools do not reach into `SQLiteResearchRegistry._connect()` directly.

This creates a stable read surface for Phase 3B/3C and keeps SQL/storage details outside Agent tool handlers.

## Decision 9 — no Agent framework dependency

Phase 3A adds no OpenAI, Anthropic, LangGraph, AutoGen or other Agent/LLM dependency.

`AgentRuntime` is only a Protocol:

```python
run(task, tools, context) -> AgentDecision
```

Phase 3B will first implement a deterministic scripted runtime against exactly the same ToolRegistry. Phase 3C may then attach an LLM-backed runtime without modifying the Quant Engine contracts.

## Consequences

Positive:

- Agent privilege is finite and testable.
- Every attempted action is auditable, including denied actions.
- Statistical thresholds and family denominators remain outside Agent control.
- A future LLM provider can be replaced without changing Quant Core.
- Removing `finagent.agents` leaves the quantitative system operational.

Trade-offs:

- Phase 3A cannot autonomously invent experiment code.
- Evaluators must be pre-registered.
- Human approval is represented as a governed request, not yet as an interactive approval workflow.
- Tool argument validation is deliberately narrow and domain-specific rather than a general JSON Schema framework.

These constraints are intentional. General code generation and graph/checkpoint orchestration are deferred until the deterministic control surface has been exercised by Phase 3B.

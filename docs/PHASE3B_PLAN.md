# Phase 3B Plan — Deterministic Scripted Research Agent

## Objective

Phase 3B implements the first complete Agent orchestration loop without an LLM. The purpose is to prove that FinAgent's Phase 3A contracts, policy layer, tools, audit store and Phase 2/2.5 research controls can support an autonomous workflow before model-provider nondeterminism is introduced.

The canonical path is:

```text
AgentTask
    -> ScriptedResearchAgent
    -> deterministic ResearchPlan
    -> ToolCallRequest[]
    -> ToolRegistry
    -> AgentPolicyEngine
    -> Research Control Plane
    -> ToolCallResult[]
    -> AgentDecision
    -> SQLiteAgentAuditStore
```

`ScriptedResearchAgent` must use exactly the same `AgentRuntime` and `ToolRegistry` surface intended for Phase 3C. It receives no direct reference to `SQLiteResearchRegistry`, `ExperimentRunner`, portfolio services, risk gates or execution adapters.

---

## 1. New domain objects

Phase 3B should add typed planning objects rather than encoding plans as free-form dictionaries:

```text
ResearchPlan
ResearchPlanStep
PlanStepStatus
ResearchBudget
ResearchRunSummary
```

Suggested semantics:

```python
ResearchBudget(
    max_tool_calls: int,
    max_experiments: int,
    max_family_size: int,
    allow_promotion_request: bool,
)
```

A plan step contains a declared tool name and a deterministic argument builder. The stored plan is immutable after the Agent run starts.

The plan fingerprint should include at least:

```text
task id
planner version
ordered step kinds
approved variant/template ids
research budget
policy version
```

so replay can prove which plan was executed.

---

## 2. ScriptedResearchAgent runtime

Add:

```text
src/finagent/agents/scripted.py
```

with an implementation of the existing protocol:

```python
class ScriptedResearchAgent:
    def run(
        self,
        task: AgentTask,
        tools: ToolRegistry,
        context: AgentRunContext,
    ) -> AgentDecision:
        ...
```

The runtime owns orchestration only. It must not instantiate quant models or read SQLite directly.

Initial state machine:

```text
START
  -> INSPECT_STATE
  -> CREATE_OR_SELECT_FAMILY
  -> REGISTER_VARIANTS
  -> RUN_VARIANTS
  -> COMPARE_RESULTS
  -> FREEZE_FAMILY
  -> VALIDATE_FAMILY
  -> REQUEST_PROMOTION?   (conditional)
  -> FINISH
```

Every transition is determined from typed tool results and predeclared plan rules.

---

## 3. Approved experiment templates

Phase 3A already uses `ExperimentEvaluatorRegistry`. Phase 3B should add a higher-level template registry so the scripted Agent can specify an experiment variant without constructing arbitrary `ExperimentSpec` payloads.

Proposed types:

```text
ExperimentTemplate
ExperimentVariant
ExperimentTemplateRegistry
```

Example first built-in research task:

```text
family: ar-order-search
variants:
  - AR(1)
  - AR(2)
  - AR(3)
  - AR(5)
primary metric: validation_sharpe
```

The template registry maps a small declarative variant to the frozen Phase 1/2 numerical APIs. No generated Python is allowed.

The first vertical slice should use synthetic/fixture data in tests and one deterministic evaluator that emits reproducible returns and p-values for family validation.

---

## 4. Run coordinator

Add a small deterministic coordinator:

```text
AgentRunCoordinator
```

Responsibilities:

1. create `AgentTask` and immutable `AgentRunContext`;
2. persist the run with `SQLiteAgentAuditStore.start_run`;
3. invoke the selected `AgentRuntime`;
4. persist `AgentDecision` with `finish_run`;
5. on runtime failure, persist a terminal failed/aborted decision before re-raising or returning an error object;
6. never mutate research state outside tool calls.

This removes run-lifecycle boilerplate from both Phase 3B scripted and Phase 3C LLM runtimes.

---

## 5. Deterministic selection policy

The scripted Agent needs a deterministic winner-selection rule before family validation.

Recommended first rule:

```text
primary metric descending
then lower turnover
then lexicographic experiment_id
```

Selection is based only on allowed inner-validation/persisted comparison fields. Outer-test results must not be exposed by a selection tool before the selection action is sealed.

The selected `experiment_id` becomes an explicit audit event or Agent decision metadata item before `validate_experiment_family` is called.

Do not allow the scripted planner to alter:

```text
family alpha
multiple-testing method
DSR threshold
PBO threshold
bootstrap configuration
outer-test data window
```

---

## 6. Replay engine

Phase 3A already persists tool requests. Phase 3B should turn this into an explicit replay capability:

```text
AgentReplayEngine
```

Two replay modes:

### Dry replay

Reconstruct and validate the ordered request sequence without invoking mutating handlers. Used to compare plan fingerprints and policy outcomes.

### Isolated deterministic replay

Run the same requests against a fresh registry/database fixture and compare normalized results.

Replay equality should ignore runtime-generated ids/timestamps where configured, while comparing:

```text
tool order
tool names
arguments
policy outcomes
terminal statuses
research artifacts/experiment fingerprints
family membership
selected experiment
validation pass/fail
promotion-request payload
```

---

## 7. Failure and resume semantics

Phase 3B must define failure behavior before Phase 3C adds provider/network failures.

Required behavior:

```text
Tool DENIED
    -> planner treats it as a terminal policy violation unless the plan explicitly marks the step optional

Tool FAILED
    -> terminal AgentDecision(FAILED) by default

REQUIRES_APPROVAL
    -> terminal AgentDecision(WAITING_FOR_APPROVAL) or equivalent explicit status

Experiment evaluator failure
    -> experiment run remains FAILED in ResearchRegistry
    -> family membership remains present
    -> failed trial is never deleted from multiplicity denominator
```

A later resume implementation must create a new Agent run linked to the prior run rather than mutating historical tool-call records.

---

## 8. Research budget enforcement

Phase 3A enforces `max_tool_calls`. Phase 3B should add research-semantic budgets:

```text
max_experiments
max_family_size
max_failed_experiments
allow_new_family
allow_promotion_request
```

These limits belong in deterministic planner/configuration and may also be checked by policy-as-code where security relevant.

The Agent must not respond to poor results by silently extending the search budget.

---

## 9. Audit and metrics

Persist or derive at least:

```text
plan fingerprint
planner version
planned steps
executed steps
tool success/denial/failure counts
family id
registered trial count
successful/failed trial count
selected experiment
family validation components
promotion request outcome
run duration
replay status
```

Agent quality in Phase 3B is evaluated as orchestration correctness, not PnL.

---

## 10. File-level landing plan

Proposed additions:

```text
src/finagent/agents/
├── scripted.py
├── coordinator.py
├── planning.py
├── replay.py
└── templates/
    ├── __init__.py
    └── research.py

tests/
├── test_scripted_agent_phase3b.py
├── test_agent_coordinator_phase3b.py
├── test_agent_replay_phase3b.py
├── test_agent_budget_phase3b.py
└── test_agent_failure_semantics_phase3b.py

docs/
├── ADR-012_PHASE3B_SCRIPTED_AGENT.md
└── PHASE3B.md
```

No new runtime dependency is required.

---

## 11. First end-to-end acceptance scenario

The first Phase 3B vertical slice should deterministically execute:

```text
Task: compare approved AR-order variants

1 inspect_experiment_families
2 create_experiment_family(ar-order-search)
3 register_experiment(AR1)
4 register_experiment(AR2)
5 register_experiment(AR3)
6 run_experiment(AR1)
7 run_experiment(AR2)
8 run_experiment(AR3)
9 compare_experiment_results
10 freeze_experiment_family
11 validate_experiment_family(selected winner)
12 request_model_promotion if validation passed and model is eligible
13 finish run
```

The exact number of calls is known before execution and must fit the immutable `AgentRunContext.max_tool_calls`.

Acceptance assertions:

1. no direct registry mutation occurs outside tools;
2. all tool requests/results/policy decisions are durable;
3. repeated execution with the same fixture and plan yields the same normalized result;
4. a failed experiment remains part of the frozen family;
5. forged run context is rejected;
6. budget exhaustion stops the workflow deterministically;
7. an illegal promotion request cannot reach human-review state;
8. SHADOW/LIVE requests remain non-mutating and require human approval;
9. removing the scripted runtime does not affect Quant Engine tests;
10. full Python 3.11/3.12/3.13 CI remains green.

---

## 12. Explicitly deferred to Phase 3C+

Phase 3B does not include:

```text
LLM inference
natural-language plan generation
provider retries/token accounting
semantic memory
free-form hypothesis generation
arbitrary Python generation
sandbox execution
LangGraph
broker access
portfolio-weight decisions
```

Phase 3C may replace the deterministic planner with an LLM-backed planner, but it must emit the same typed plan/tool requests and remain subject to the same policy, budget and audit contracts.

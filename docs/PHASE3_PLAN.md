# Phase 3 Plan — Research Agent Control Plane

## Objective

Phase 3 introduces the first LLM/Agent capability into FinAgent without moving stochastic language-model decisions into the numerical trading hot path.

The target architecture is:

```text
Research Agent
    -> typed research tools
    -> Agent Policy Guard
    -> Research Control Plane
        -> ExperimentFamily Registry
        -> Nested Validation
        -> ExperimentRunner
        -> Family Statistics
        -> Model Registry
    -> Quant Engine
        -> Data / Alpha / Risk / Portfolio / RiskGate / Execution
```

The Agent coordinates approved research actions. It does not calculate portfolio weights, alter fills, bypass risk controls or mutate model stages directly.

---

## Phase 3.0 — freeze the Agent tool contract

### Function

Create framework-independent typed request/response objects before choosing LangGraph or any provider SDK.

Proposed domain objects:

```text
AgentTask
AgentRunContext
ToolCallRequest
ToolCallResult
AgentDecision
AgentAuditEvent
PolicyDecision
```

Proposed `AgentRuntime` protocol:

```python
class AgentRuntime(Protocol):
    def run(
        self,
        task: AgentTask,
        tools: ToolRegistry,
        context: AgentRunContext,
    ) -> AgentDecision: ...
```

### Landing strategy

Add:

```text
src/finagent/agents/domain.py
src/finagent/agents/runtime.py
src/finagent/agents/tools/base.py
src/finagent/agents/policy.py
```

No LangGraph type may appear in these domain files.

---

## Phase 3.1 — deterministic research tool surface

### Initial read tools

```text
inspect_data_contract
list_experiment_families
inspect_experiment_family
list_experiments
inspect_experiment
compare_experiment_results
inspect_model_registry
inspect_model_history
```

### Initial write/action tools

```text
create_experiment_family
register_experiment
run_experiment
freeze_experiment_family
validate_experiment_family
request_model_promotion
```

`request_model_promotion` is deliberately not `promote_model`. It returns a governed request that the deterministic policy layer may approve or reject.

### Explicitly forbidden tools

```text
set_portfolio_weights
bypass_risk_gate
set_fill_price
edit_backtest_result
delete_failed_experiment
remove_family_member
promote_directly_to_live
execute_broker_order
```

### Landing strategy

Every tool wraps an existing typed FinAgent service. The tool layer performs schema translation and authorization only; it must not reimplement quant logic.

---

## Phase 3.2 — policy-as-code and permission boundaries

### Function

Introduce an `AgentPolicyEngine` with a finite action set.

Policy examples:

```text
Research Agent may:
  create OPEN family
  add experiments to OPEN family
  run registered experiments
  freeze a non-empty family
  request validation

Research Agent may not:
  reopen FROZEN/CLOSED family
  omit failed trials from validation
  view outer test before selection action is sealed
  change statistical thresholds outside approved config
  move a model beyond VALIDATED/PAPER without human policy
```

### Landing strategy

Policy rules are ordinary deterministic Python/configuration. LLM output is parsed into a requested action, then the policy engine decides whether the action is admissible.

---

## Phase 3.3 — single Research Agent orchestrator

### Function

Implement one orchestrator before any multi-agent system.

Initial loop:

```text
ResearchQuestion
    -> inspect previous families / experiments
    -> propose hypothesis
    -> create or extend OPEN family
    -> choose from approved experiment templates
    -> run experiment
    -> inspect result
    -> repeat within research budget
    -> freeze family
    -> family validation
    -> summarize result
    -> optionally request model promotion
```

### Why single-agent first

Multi-agent debate adds cost and nondeterminism before there is evidence it improves the research process. Phase 3 should first make tool use, auditability and statistical governance measurable.

---

## Phase 3.4 — structured memory, not chat memory

### Primary memory

SQLite/PostgreSQL remains canonical for:

```text
families
experiments
runs
results
models
stage events
agent runs
tool calls
policy decisions
```

### Optional semantic memory

A vector store is deferred to documents that genuinely require semantic retrieval:

```text
papers
filings
research notes
text reflections
```

It must not become the canonical store for numerical experiment state.

---

## Phase 3.5 — sandboxed code-generation capability

This is the first point at which Agent-generated Python should be considered.

### Workspace contract

```text
SandboxWorkspace
GeneratedArtifact
SandboxRunRequest
SandboxRunResult
```

### Mandatory controls

```text
isolated working directory
explicit dependency allowlist
CPU/time/memory limits
no broker credentials
network disabled by default
read-only research data mounts
captured stdout/stderr
code SHA-256
reproducible seed/config
static checks before execution
```

### Rollout

Start with generated feature functions only. Model classes, portfolio optimizers and execution code remain template/registry based until the feature-code path is demonstrably safe and reproducible.

---

## Phase 3.6 — Agent observability and evaluation

Agent quality must be measured independently of portfolio PnL.

Persist at least:

```text
agent/model/provider version
prompt/config hash
tool calls
tool success rate
invalid-action rate
policy violations
experiment acceptance rate
family size / research budget
latency
token/cost estimate
reproducibility on replay
```

Research outcomes should additionally track:

```text
number of attempted hypotheses
multiple-testing denominator
inner-vs-outer performance gap
DSR
PBO
reality-check p-value
promotion rate
post-promotion decay
```

---

## Phase 3.7 — optional LangGraph adapter

Only after the domain/runtime/tool contracts are stable should a LangGraph adapter be introduced:

```text
src/finagent/adapters/langgraph/
```

LangGraph may provide:

```text
state graph
checkpointing
retry routing
human approval nodes
```

but it must not define FinAgent's domain objects or numerical interfaces.

---

## Phase 3 delivery milestones

### Phase 3A — Agent contracts and tools

Deliver:

- typed Agent domain objects;
- ToolRegistry;
- read/write research tools;
- policy engine;
- audit log;
- deterministic tests.

No LLM required yet.

### Phase 3B — local scripted Agent emulator

Use a deterministic planner to execute the same tool interface. This validates orchestration independently from language-model variability.

### Phase 3C — LLM Research Agent

Attach one provider-agnostic `AgentRuntime` implementation. The Agent can propose experiments and call tools but only within the Phase 3 policy surface.

### Phase 3D — sandboxed feature generation

Enable constrained code generation for feature artifacts and run them through the existing experiment-family and validation pipeline.

### Phase 3E — optional graph/checkpoint adapter

Add LangGraph only if long-running research workflows, checkpoint/resume or human approval routing justify the dependency.

---

## Phase 3 acceptance criteria

Phase 3 should not be considered complete until all of the following are testable:

1. An Agent cannot call an unregistered tool.
2. A tool cannot bypass the Phase 2/2.5 domain contracts.
3. An Agent cannot remove a failed/poor experiment from a frozen family.
4. Outer test data cannot be queried by a model-selection tool before selection is sealed.
5. A model cannot reach LIVE through Agent action alone.
6. Every Agent action has an auditable run id and tool-call record.
7. The same approved deterministic tool sequence can be replayed without an LLM.
8. Agent failure does not corrupt experiment/model registries.
9. LLM provider/framework can be replaced without changing Quant Core contracts.
10. Removing the entire `agents/` package leaves the Quant Engine fully functional.

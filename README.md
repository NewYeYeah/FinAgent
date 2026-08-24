# FinAgent

FinAgent is a typed, auditable quantitative-research and portfolio infrastructure in which an Agent may orchestrate approved research actions without entering the numerical trading hot path.

Current status: **Phase 3A — Governed Agent Control Surface**.

The architectural rule is:

```text
Agent / future LLM:
  plans research and requests registered tools.

Deterministic code:
  owns point-in-time data, numerical models, statistical validation,
  portfolio weights, risk approval, execution semantics and model lifecycle.
```

No LLM or Agent framework is required by the package at Phase 3A.

## Architecture

### Quant Engine

```text
DataAdapter
    -> ResearchDataset / ResearchSplit
    -> FeatureWindow
    -> AlphaModel / RiskModel
    -> AlphaForecast / RiskForecast
    -> PortfolioOptimizer
    -> PortfolioTarget
    -> RiskGate
    -> RiskDecision
    -> OrderIntent
    -> TimedExecutionVenue
    -> Fill / ExecutionReport
    -> PortfolioState
```

### Research Control Plane

```text
ExperimentFamily(OPEN)
    -> ExperimentSpec[]
    -> nested inner validation
    -> ExperimentRunner
    -> ExperimentResult[]
    -> ExperimentFamily(FROZEN)
    -> multiplicity / DSR / PBO / reality check
    -> outer holdout evaluation
    -> RegisteredModel
    -> candidate -> validated -> paper -> shadow -> live -> retired
```

### Phase 3A Agent Control Plane

```text
AgentTask + AgentRunContext
        -> ToolCallRequest
        -> ToolRegistry
        -> exact ToolSpec / budget / argument schema
        -> AgentPolicyEngine
        -> approved deterministic research tool
        -> Research Control Plane
        -> ToolCallResult
        -> SQLiteAgentAuditStore
```

The Agent does not receive raw portfolio, risk-gate, fill-price, model-stage mutation or broker-order functions.

## Phase 1 numerical contract

See [`docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md`](docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md).

Canonical numerical layouts:

```text
ResearchSplit.feature_values.shape = (time, asset, feature)
ResearchSplit.label_values.shape   = (time, asset, label)
FeatureWindow.values.shape         = (time, asset, feature)
```

The public data path remains:

```python
build_dataset(request) -> ResearchDataset
feature_window(asof, universe, features, lookback) -> FeatureWindow
market_snapshot(asof, universe) -> MarketSnapshot
calendar(start, end, universe) -> tuple[datetime, ...]
```

Important invariants:

- `TimeRange` is half-open `[start, end)`;
- public numerical arrays are `float64`, defensive-copy and read-only;
- missing numerical values use `NaN`; infinity is rejected;
- `available_at` is the research point-in-time clock;
- forward labels cannot cross split boundaries;
- pandas/Qlib/vendor schemas remain behind adapters rather than becoming public contracts.

## Quant Kernel

### Data

Implemented:

- `InMemoryPriceDataAdapter`
- `CSVPriceDataAdapter`
- `SQLitePriceDataAdapter`
- `SQLitePriceStore`
- deterministic dataset SHA-256 digests
- PIT-safe feature windows
- split-isolated forward labels

Built-in research fields include:

```text
close
volume
log_return_N
simple_return_N
squared_log_return_N
log_volume_change_N
forward_log_return_N
forward_simple_return_N
```

### Alpha

- `RandomWalkAlphaModel`
- `RandomWalkDiagnostics` with ACF / Ljung-Box
- `ARAlphaModel(order=p)`
- `ARMA11AlphaModel`

### Risk

- `GARCH11Estimator`
- `GARCH11RiskModel`
- `EWMACovarianceEstimator`
- PSD-validated `RiskForecast`

The multivariate reference risk construction is:

```text
GARCH marginal volatility
    +
EWMA/shrunk correlation
    ->
PSD covariance forecast
```

### Portfolio / hard risk

`MeanVarianceOptimizer` supports risk aversion, cash allocation, long-only/long-short bounds, maximum absolute weight and turnover penalty.

The accounting identity remains:

```text
sum(asset_weights) + cash_weight = 1
```

Gross and net exposure are tracked separately. `StaticRiskGate` is deterministic and non-mutating.

## Execution timing

See [`docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md`](docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md).

Research information and executable prices use separate clocks. The execution boundary exposes only the executable field through:

```python
ExecutionDataAdapter.execution_calendar(...)
ExecutionDataAdapter.execution_snapshot(...)
```

For the built-in bar adapter:

```text
open  -> executable at PriceBar.event_time
close -> executable at PriceBar.available_at
```

`TimedEventDrivenBacktestEngine` enforces:

```text
execution_at > information_at
```

and defaults to a later executable event instead of filling a newly generated signal at an already-observed price.

## Experiment and model governance

See [`docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md`](docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md).

`ExperimentRunner` owns the durable lifecycle:

```text
register inputs
 -> RUNNING
 -> evaluator
 -> result/artifacts
 -> SUCCEEDED or FAILED
```

`SQLiteResearchRegistry` persists artifacts, experiment specs/runs/results, experiment families, family memberships, registered models and model-stage events.

Model lifecycle:

```text
CANDIDATE
 -> VALIDATED
 -> PAPER
 -> SHADOW
 -> LIVE
 -> RETIRED
```

Stage skipping is rejected. A model cannot change stage by overwriting its registration record.

## Nested validation and anti-overfitting controls

See [`docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md`](docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md) and [`docs/PHASE2_5.md`](docs/PHASE2_5.md).

Nested chronological validation is explicit:

```text
outer train
    -> inner train | purge | embargo | validation
    -> model/config selection
outer purge | outer embargo | outer test
```

Related trials are pre-registered as an `ExperimentFamily`:

```text
OPEN -> FROZEN -> CLOSED
```

Only OPEN families accept new trials. Family-level inference requires FROZEN status and the exact registered family denominator.

Implemented statistical controls:

- Bonferroni, Holm and Benjamini-Hochberg p-value correction;
- Deflated Sharpe Ratio probability;
- CSCV Probability of Backtest Overfitting;
- White-style reality check with circular moving-block bootstrap;
- deterministic decomposed family-validation gate.

## Phase 3A governed Agent surface

See [`docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md`](docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md) and [`docs/PHASE3A.md`](docs/PHASE3A.md).

### Typed Agent contracts

`finagent.agents.domain` defines:

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

`AgentRuntime` is only a framework-independent Protocol. There is still no LLM runtime in the package.

### Finite tool surface

Phase 3A registers exactly these research actions:

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

Explicitly unavailable to an Agent include:

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

Unknown or malformed tool calls are denied and audited.

### Deterministic policy-as-code

`DefaultResearchAgentPolicy` applies:

- per-run tool allowlists;
- tool-call budgets;
- finite action authorization;
- model-promotion request policy;
- mandatory human approval for SHADOW/LIVE promotion requests.

`request_model_promotion` never mutates the model registry. It only materializes a legal request with `mutation_performed=false`.

### Statistical policy cannot be changed by Agent arguments

The Agent-facing `validate_experiment_family` accepts only:

```text
family_id
selected_experiment_id
```

Returns/p-values are supplied through trusted `FamilyValidationInputProvider`; DSR/PBO/bootstrap thresholds come from fixed `FamilyValidationPolicy`. Agent attempts to inject alternative thresholds are rejected by the exact tool schema.

### Approved evaluator registry

`ExperimentEvaluatorRegistry` limits Phase 3A experiment execution to pre-registered deterministic evaluator/templates. Arbitrary generated Python is deferred to Phase 3D.

### Audit

`SQLiteAgentAuditStore` maintains a separate Agent audit namespace:

```text
agent_runs
agent_tool_calls
agent_policy_decisions
agent_audit_events
```

Denied actions are recorded as first-class events. Tool request sequences are replayable for Phase 3B deterministic orchestration tests.

## Repository layout

```text
FinAgent/
├── src/finagent/
│   ├── agents/
│   │   ├── domain.py
│   │   ├── runtime.py
│   │   ├── policy.py
│   │   ├── audit.py
│   │   └── tools/
│   │       ├── base.py
│   │       └── research.py
│   ├── analysis/
│   ├── backtest/
│   │   ├── engine.py
│   │   ├── timed.py
│   │   └── walk_forward.py
│   ├── data/
│   ├── domain/
│   ├── models/
│   ├── portfolio/
│   ├── research/
│   │   ├── family_validation.py
│   │   ├── query.py
│   │   ├── registry.py
│   │   ├── runner.py
│   │   └── validation.py
│   ├── services/
│   └── ports.py
├── tests/
├── docs/
│   ├── ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md
│   ├── ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md
│   ├── ADR-009_PHASE2_MODEL_GOVERNANCE.md
│   ├── ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md
│   ├── ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md
│   ├── PHASE1.md
│   ├── PHASE2.md
│   ├── PHASE2_5.md
│   ├── PHASE3_PLAN.md
│   ├── PHASE3A.md
│   └── DEVLOG.md
├── pyproject.toml
└── README.md
```

## Development setup

Python 3.11+ is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
pytest -q
```

## Test status

Before the final documentation/refinement commit, the first Phase 3A pull-request tree passed the complete **83-test** suite under Python 3.11, 3.12 and 3.13 in GitHub Actions. The final Phase 3A commit adds one further governance regression test and is revalidated through the same matrix before `main` is advanced.

Coverage now includes the Phase 0.5–2.5 numerical/research controls plus Agent-domain validation, unknown-tool denial, exact argument schemas, run budgets, allowlists, research-tool composition, frozen-family protection, trusted family-validation inputs, non-mutating promotion requests and human-approval routing.

## Next engineering layer

The next milestone is **Phase 3B — deterministic scripted Agent emulator**.

It will implement a local `ScriptedResearchAgent` using exactly the same `AgentRuntime`, `ToolRegistry`, policy and audit contracts:

```text
Research question
 -> inspect research state
 -> create/open family
 -> register approved variants
 -> run experiments
 -> compare results
 -> freeze family
 -> validate family
 -> request promotion when policy permits
 -> finish/audit run
```

Only after this workflow is deterministic and replayable will Phase 3C attach a provider-agnostic LLM runtime. Phase 3D then considers sandboxed feature-code generation; LangGraph remains an optional Phase 3E adapter rather than a domain dependency.

## Design documentation

- [`docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md`](docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md)
- [`docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md`](docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md)
- [`docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md`](docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md)
- [`docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md`](docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md)
- [`docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md`](docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md)
- [`docs/PHASE1.md`](docs/PHASE1.md)
- [`docs/PHASE2.md`](docs/PHASE2.md)
- [`docs/PHASE2_5.md`](docs/PHASE2_5.md)
- [`docs/PHASE3_PLAN.md`](docs/PHASE3_PLAN.md)
- [`docs/PHASE3A.md`](docs/PHASE3A.md)
- [`docs/DEVLOG.md`](docs/DEVLOG.md)

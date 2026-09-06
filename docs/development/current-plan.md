# FinAgent current development plan

Planning revision: **5.0**  
Current-stage authority: [`../status.toml`](../status.toml)

## 1. Product objective

FinAgent is being developed toward an **Agent-driven adaptive quantitative research and trading workstation**.

The intended division of responsibility is:

```text
Human
  defines objectives, budgets and high-authority approvals
        ↓
Research Agent
  proposes hypotheses, chooses research direction, manages factor lifecycle,
  selects factor sets/allocators and allocates development experiment budget
        ↓
Deterministic Core
  owns data chronology, calculations, statistical gates, portfolio/account truth,
  execution state, reconciliation and safety
        ↓
Workbench
  exposes Agent activity, experiments, market state, factors, strategy and operations
        ↓
PAPER / Live
  only after separate evidence and authority gates
```

The project is **not** targeting HFT or order-book microstructure research while authoritative Tick/LOB history is unavailable.

## 2. Baseline that must be reused

The repository already contains substantial capability. The roadmap assumes reuse rather than replacement:

- certified/local U.S. minute OHLCV research path with a current 25-name EngineeringUniverse;
- bounded research contracts and causal time semantics;
- typed FactorGraph DSL and shared-DAG numerical execution;
- deterministic factor/statistical evaluation, portfolio and historical execution;
- bounded Agent research runtime with typed tools, SQLite trial/budget ledger and development feedback;
- React/Vite Workbench with ECharts, React Flow, TanStack Table, WorkbenchContext, Evidence/Control separation and SSE;
- Strategy, Factor, Portfolio and Execution historical analytical surfaces;
- provider-neutral realtime events, replay/database sources, streaming transforms and state projections;
- MT5 read-only/realtime adapter work;
- PAPER/approval/reconciliation/safety/store modules.

These are implementation assets, not proof of profitable Alpha or PAPER readiness.

## 3. Roadmap

The route is intentionally **conditional**, not a conveyor belt that forces every research cycle toward trading:

```text
R3-CLOSE
   ↓
R4-AGENT-ADAPTIVE
   ├── NO_ADAPTIVE_CANDIDATE ──→ new versioned R4 cycle
   │                         └──→ WORKBENCH-2 productization is still allowed
   │
   └── frozen AdaptiveStrategy candidate
             ↓
R5-INDEPENDENT-CONFIRMATION
   ├── REJECTED / INSUFFICIENT ─→ new versioned R4 cycle
   │                         └──→ WORKBENCH-2 productization is still allowed
   │
   └── CONFIRMED ───────────────→ PAPER eligibility

After the first complete R4 research semantics are stable:
WORKBENCH-2
   ↓ only when a strategy is R5 CONFIRMED
PAPER-TRADING
   ↓
PAPER-ACCEPTED
   ↓
LIVE-CAPITAL
```

Workbench 2.0 is therefore **not conditional on profitable Alpha**. It is the product surface for subsequent research cycles as well as confirmed strategies. PAPER and Live remain conditional on strategy evidence.

Detailed stage plans are kept in [`stages/`](stages/).

## 4. Stage summary

| Stage | Purpose | Main output | Stage plan |
| --- | --- | --- | --- |
| R3-CLOSE | stop expanding the current R3 experiment and preserve reusable capability without claiming Alpha | clean R3 terminal + reusable runtime/evaluator | [`stages/r3-close.md`](stages/r3-close.md) |
| R4-AGENT-ADAPTIVE | make Agent responsible for research decisions and adaptive factor allocation under development-only evidence | MarketState + FactorLibrary + Allocator + Research Controller, plus candidate or no-candidate terminal | [`stages/r4-agent-adaptive.md`](stages/r4-agent-adaptive.md) |
| R5-INDEPENDENT-CONFIRMATION | when R4 produces a candidate, freeze the complete adaptive algorithm and test it on genuinely independent evidence | `AdaptiveStrategySpec` + CONFIRMED/REJECTED/INSUFFICIENT result | [`stages/r5-independent-confirmation.md`](stages/r5-independent-confirmation.md) |
| WORKBENCH-2 | turn the existing evidence-heavy Workbench into an Agent/research-first product after R4 interaction semantics stabilize | interactive Research Workbench 2.0 | [`stages/workbench-2.md`](stages/workbench-2.md) |
| PAPER-TRADING | only for an R5-confirmed strategy, integrate existing realtime/MT5/PAPER/safety modules and build live-like UI from canonical state | end-to-end demo/PAPER system | [`stages/paper-trading.md`](stages/paper-trading.md) |
| LIVE-CAPITAL | separately admit a specific broker/account/capital/risk operating envelope | human-governed live-capital acceptance | [`stages/live-capital.md`](stages/live-capital.md) |

## 5. Research strategy

### 5.1 R4 changes the role of the Agent

The primary Agent-value question becomes:

> Does an Agent improve the quality or efficiency of **research selection and adaptive factor allocation**, not merely generate more formulas?

Agent authority may expand over development research decisions, but final statistical thresholds, final holdout access, broker/account truth and safety controls remain deterministic/human governed.

### 5.2 Factor discovery is not the whole strategy

The target research structure is:

```text
causal OHLCV features
      ↓
MarketState probability
      +
FactorLibrary
      ↓
Factor selection / weighting
      ↓
AdaptiveStrategy
```

The project should prefer a small economically interpretable factor library plus adaptive weighting over unbounded formula search.

### 5.3 Market state and stock selection are separate layers

Market/regime information may control:

- factor weights;
- gross exposure/cash;
- factor activation;
- research priority.

It should not be forced through a cross-sectional RankIC gate when the mechanism is genuinely market-timing or allocation-level.

## 6. Evidence intensity by stage

FinAgent previously applied production-grade evidence machinery too early in exploration. Revision 5.0 deliberately separates three levels.

### Explore — R4

Required:

- causal data boundaries;
- reproducible trial/config identity;
- complete trial ledger including failed/duplicate attempts;
- development-only feedback boundaries;
- focused numerical and leakage tests.

Not required for every exploratory increment:

- content-addressing every intermediate cache;
- independent reviewer receipt;
- separate PR/stage for every materialization/statistical substep.

### Confirm — R5

Required when an R4 candidate exists:

- frozen complete algorithm;
- independent/prospective evidence;
- preregistered endpoints/costs/stopping rule;
- robust inference and multiplicity accounting;
- immutable confirmation result.

### Operate — PAPER/LIVE

Required:

- broker/account identity;
- durable state/recovery;
- reconciliation;
- stale-data and loss/exposure gates;
- kill switch;
- incident evidence;
- explicit human authority transition.

## 7. Open-source and reuse policy

Before adding a subsystem, evaluate in this order:

1. existing FinAgent implementation;
2. mature open-source library with strong maintenance/community;
3. thin FinAgent adapter around that library;
4. custom implementation only when the project has an authority/semantic requirement the library cannot own.

Current preferred reuse directions:

- scikit-learn GMM for the first adaptive market-state baseline;
- Optuna for deterministic parameter/search baselines where search is needed;
- existing FactorGraph/Agent runtime/evaluator rather than a new Agent framework;
- Apache ECharts, React Flow and TanStack Table for existing analytical/graph/table UI;
- TanStack Query during Workbench 2.0 instead of extending the custom query client;
- AG-UI as the first protocol candidate for Agent↔Workbench streaming/tool events;
- CopilotKit only if a bounded integration spike shows it can reuse FinAgent authority rather than replace it;
- TradingView Lightweight Charts only for price/order/fill panels once PAPER state is real;
- DuckDB/Parquet remain the historical data plane.

A framework migration is itself a feature cost and requires a demonstrated benefit.

## 8. PR policy

PR count is a planning aid, not an acceptance criterion.

Prefer a **vertical slice** that can be reviewed and demonstrated end to end. Split when:

- an independent authority boundary changes;
- a prerequisite can be accepted separately and materially reduces risk;
- the combined diff is too large to reason about safely;
- rollback needs to be independent.

Do not create long chains of contract-only/cache-only/orchestration-only PRs when one bounded capability can be reviewed coherently. Conversely, do not recreate a R3-scale mega-PR that mixes unrelated research, runtime and UI work.

Stage files contain suggested PR slices, but quality and reviewability take precedence over a fixed count.

## 9. Visualization timing

Visualization is a first-class product goal and has two development levels:

1. **R4 thin Research Console:** implemented early so Agent objective → tool → experiment → decision behavior can be observed and corrected while research semantics are still being built.
2. **Workbench 2.0:** begins after the first complete R4 interaction/FactorLibrary/MarketState semantics are stable. If an R4 candidate exists, R5's frozen identities/results feed the product; if no candidate exists, Workbench 2.0 still proceeds as the interface for the next research cycle.

Realtime trading panels are developed together with PAPER vertical slices. No standalone fake Live dashboard is built first.

## 10. Data limits that shape the roadmap

- no authoritative historical Tick/LOB dataset is currently available;
- the 25-name U.S. EngineeringUniverse is present-symbol/survivorship conditioned and does not support unrestricted market-wide PIT claims;
- U.S. minute source publication/redistribution rights remain limited;
- historical equity data and broker CFD instruments are not identical economic instruments;
- transaction-cost realism and source/feed entitlement must be revalidated before PAPER.

These are explicit limitations, not reasons to invent substitute data.

## 11. Final success definition

A mature FinAgent should be able to:

1. receive a research objective;
2. let the Agent inspect literature, market state, factor history and prior experiments;
3. let the Agent propose/test/retire factors and choose factor-allocation experiments within a bounded budget;
4. produce a frozen adaptive strategy only through deterministic evaluation, or explicitly terminate with no candidate;
5. confirm or reject any candidate complete algorithm on independent evidence;
6. expose the full research path through an interactive Workbench even when the current research cycle has no confirmed Alpha;
7. run only an R5-confirmed strategy through replay and MT5 demo/PAPER with reconciled, recoverable and safety-bounded state;
8. keep live capital behind a separate explicit human-governed gate.

A valid terminal may still be `NO_CONFIRMED_ALPHA`. Product quality does not require fabricating a deployable strategy.

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

```text
R3-CLOSE
   ↓
R4-AGENT-ADAPTIVE
   ↓
R5-INDEPENDENT-CONFIRMATION
   ├── rejected/insufficient ──→ new versioned R4 research cycle
   │
   └── confirmed ──────────────→ PAPER eligibility
             │
             └──────────────┐
                            ↓
                  WORKBENCH-2
                  (may proceed after R5 even when Alpha is rejected,
                   because the research workstation is useful independently)
                            │
                            ↓ when Alpha is confirmed
                      PAPER-TRADING
                            │
                            ↓
                      PAPER-ACCEPTED
                            │
                            ↓
                       LIVE-CAPITAL
```

Detailed stage plans are kept in [`stages/`](stages/).

## 4. Stage summary

| Stage | Purpose | Main output | Stage plan |
| --- | --- | --- | --- |
| R3-CLOSE | stop expanding the current R3 experiment and preserve reusable capability without claiming Alpha | clean R3 terminal + reusable runtime/evaluator | [`stages/r3-close.md`](stages/r3-close.md) |
| R4-AGENT-ADAPTIVE | make Agent responsible for research decisions and adaptive factor allocation under development-only evidence | MarketState + FactorLibrary + Allocator + Research Controller | [`stages/r4-agent-adaptive.md`](stages/r4-agent-adaptive.md) |
| R5-INDEPENDENT-CONFIRMATION | freeze the complete adaptive algorithm and test it on genuinely independent evidence | `AdaptiveStrategySpec` + CONFIRMED/REJECTED/INSUFFICIENT result | [`stages/r5-independent-confirmation.md`](stages/r5-independent-confirmation.md) |
| WORKBENCH-2 | turn the existing evidence-heavy Workbench into an Agent/research-first product | interactive Research Workbench 2.0 | [`stages/workbench-2.md`](stages/workbench-2.md) |
| PAPER-TRADING | integrate confirmed strategy with existing realtime/MT5/PAPER/safety modules and build the live-like UI from canonical state | end-to-end demo/PAPER system | [`stages/paper-trading.md`](stages/paper-trading.md) |
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

FinAgent previously applied production-grade evidence machinery too early in exploration. Revision 5.0 deliberately separates three levels:

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

Required:
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

Visualization is a first-class product goal, but it follows two rules:

1. R4 gets a **thin Research Console** early so the Agent research loop can be observed and interacted with while semantics are being validated.
2. Full Workbench 2.0 follows the R5 research freeze so product work does not repeatedly chase unstable model semantics.

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
4. produce a frozen adaptive strategy only through deterministic evaluation;
5. confirm or reject that complete algorithm on independent evidence;
6. expose the full research path through an interactive Workbench;
7. run a confirmed strategy through replay and MT5 demo/PAPER with reconciled, recoverable and safety-bounded state;
8. keep live capital behind a separate explicit human-governed gate.

A valid terminal may still be `NO_CONFIRMED_ALPHA`. Product quality does not require fabricating a deployable strategy.

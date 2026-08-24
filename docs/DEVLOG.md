# FinAgent Development Log

## 2026-08-24 — Phase 2: Validation, Execution Timing + Model Governance

### Goal

Strengthen the research protocol and lifecycle before introducing any Agent/LLM orchestration. Phase 2 implements the three controls identified after Phase 1: purged/embargoed walk-forward validation, strict information/execution-time separation, and durable experiment/model governance.

### Architecture decisions

Added:

- `ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md`;
- `ADR-009_PHASE2_MODEL_GOVERNANCE.md`;
- `PHASE2.md`.

The Phase 1 `DataAdapter` remains frozen. Field-level execution is additive through `ExecutionDataAdapter`.

### Purged walk-forward validation

Implemented `WalkForwardConfig`, `WalkForwardFold` and `PurgedWalkForwardSplitter`. Canonical forward-return labels are parsed for their horizon and, by default, `purge_bars` must be at least that horizon. Rolling and expanding train windows are supported.

The strict chronological layout is:

```text
train | purge | embargo | test
```

Because FinAgent Phase 2 never trains on observations after the test block, embargo is represented as an additional pre-test exclusion zone rather than symmetric purged cross-validation.

### Execution clock separation

Added `ExecutionQuote` and `ExecutionSnapshot`. The built-in adapter exposes `open` at `event_time` and `close` at `available_at`; high/low are rejected as executable fields because their intrabar availability is undefined.

Added `TimedEventDrivenBacktestEngine` and `TimedSimulatedExchange`. The hard invariant is:

```text
execution_at > information_at
```

The default is one executable-event lag at the next open. Signal generation/risk approval uses the PIT decision snapshot; fills use a later execution snapshot containing only executable prices.

### Experiment lifecycle

Added `ExperimentRunner` and `ExperimentEvaluation`. The runner persists RUNNING before evaluator execution and terminal SUCCEEDED/FAILED status afterwards. Produced artifacts are registered automatically. Failures remain durable and are then re-raised.

### Model governance

Added:

```text
ModelStage
RegisteredModel
ModelStageEvent
```

with governed transitions:

```text
candidate -> validated -> paper -> shadow -> live -> retired
```

Retirement is available from each active stage. Direct stage overwrite is rejected; transitions must use `promote_model`, which records actor/reason/time.

### SQLite lifecycle bug fixed

Phase 2 tests exposed that `INSERT OR REPLACE` on `runs` can delete the existing parent row before inserting its replacement. Because `results.run_id` has `ON DELETE CASCADE`, a terminal run update could silently delete an already registered result.

Run updates now use `INSERT ... ON CONFLICT DO UPDATE`, preserving dependent results.

### Dependencies

No new runtime dependency was added. Phase 2 still uses only NumPy and SciPy in the numerical core. No pandas/Qlib/LangGraph/LLM framework is required.

### Tests

Total suite after Phase 2:

```text
55 passed
```

New coverage includes label-horizon purge, rolling/expanding fold construction, fold dataset materialization, field-level open/close availability, same-instant execution prevention, timed end-to-end backtesting, experiment terminal-state persistence, model-stage governance and the SQLite cascade regression.

### Next step

The next engineering layer should address statistical selection risk: nested walk-forward tuning, experiment-family/multiple-hypothesis controls, Deflated Sharpe/PBO and benchmark reality checks. The first Agent tool surface should be introduced only after those deterministic controls exist.

---

## 2026-08-24 — Phase 1: Numerical Data Contract + Quant Kernel

### Goal

Freeze the actual numerical interface from `DataAdapter` through `ResearchDataset` into `AlphaModel` / `RiskModel`, then implement the first complete quantitative vertical slice without introducing Agent/LLM dependencies.

### Architecture decision

Added `docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md` and froze the following public path:

```text
DataAdapter
 -> ResearchDataset / ResearchSplit
 -> FeatureWindow
 -> AlphaModel / RiskModel
```

Canonical numerical array order is:

```text
(time, asset, feature)
```

for features and inference windows, and `(time, asset, label)` for labels. Arrays are `float64`, defensively copied, read-only, allow `NaN` for missing data and reject infinity.

`TimeRange` semantics are now explicitly half-open `[start, end)`. Forward labels crossing a split boundary are invalidated rather than leaking into the preceding split.

The Phase 0.5 schema-level `ResearchDataset` contract remains backward compatible and is extended with immutable materialized `ResearchSplit` panels.

### Data subsystem

Implemented:

- `DataAdapter` protocol;
- `DatasetRequest`;
- `ResearchSplit`;
- `FeatureWindow`;
- `InMemoryPriceDataAdapter`;
- `CSVPriceDataAdapter`;
- `SQLitePriceStore`;
- `SQLitePriceDataAdapter`.

`available_at` is the hard research clock. `feature_window(asof)` never uses observations with `available_at > asof`.

Dataset artifacts receive deterministic SHA-256 digests over manifest + materialized numerical panels.

### Alpha subsystem

Implemented:

- `RandomWalkAlphaModel`;
- `RandomWalkDiagnostics` with ACF and Ljung-Box statistics;
- `ARAlphaModel(order=p)` using OLS;
- `ARMA11AlphaModel` using conditional sum-of-squares estimation.

AR prediction uses the explicit PIT `FeatureWindow`. ARMA reconstructs residual history from the supplied feature window, avoiding hidden online mutable state.

### Risk subsystem

Implemented:

- `GARCH11Estimator`;
- `GARCH11RiskModel`;
- `EWMACovarianceEstimator`.

GARCH enforces `omega > 0`, non-negative ARCH/GARCH coefficients and `alpha + beta < 1`. Returns are internally rescaled for optimization and converted back to decimal-return variance.

EWMA covariance supports diagonal shrinkage and explicit PSD projection. `GARCH11RiskModel` combines GARCH marginal volatility with EWMA correlation.

`RiskForecast` now validates positive semidefiniteness at the domain boundary.

### Portfolio subsystem

Implemented `MeanVarianceOptimizer` with:

- configurable risk aversion;
- fixed cash weight;
- long-only or symmetric long/short bounds;
- maximum absolute asset weight;
- optional turnover penalty.

The optimizer emits only `PortfolioTarget`; it cannot place orders or bypass risk.

### Execution subsystem

Retained the deterministic `SimulatedExchange` and added `VolumeAwareSimulatedExchange` with:

- maximum participation-rate clipping;
- partial fills;
- commission;
- fixed adverse slippage;
- participation-dependent impact.

This remains a research cost model, not a limit-order-book simulator.

### Backtest subsystem

Implemented `EventDrivenBacktestEngine`.

The engine:

1. fits alpha/risk models on the train split only;
2. iterates test timestamps sequentially;
3. requests PIT feature windows;
4. marks the account;
5. obtains alpha and risk forecasts;
6. solves the portfolio target;
7. executes the hard risk gate;
8. translates approved targets to orders;
9. simulates fills and updates the account;
10. reports return/risk/cost metrics.

The Phase 1 timing convention is explicitly idealised close-on-close. Separate quote/open/close availability and next-bar execution are deferred.

### Research persistence

Implemented `SQLiteResearchRegistry` for round-trip persistence of:

- `ArtifactRef`;
- `ExperimentSpec`;
- `ExperimentRun`;
- `ExperimentResult`.

This is the first durable memory layer intended for the future Research Agent.

### Dependencies

Phase 1 intentionally adds only numerical dependencies:

```text
numpy
scipy
```

No pandas, Qlib, bt, LangGraph, broker SDK or LLM framework is required by the core package.

### Tests

Phase 0.5 + Phase 1 total:

```text
45 passed
```

The Phase 1 tests cover numerical immutability, PIT feature windows, label split isolation, SQLite price storage, random-walk diagnostics, AR/ARMA estimation, GARCH, covariance PSD behavior, optimizer constraints, volume-aware execution, SQLite research registry and the complete numerical backtest path.

### Third-party migration decision

No external project source was copied in Phase 1. The architecture review remains useful, but no Qlib/bt/RD-Agent/TradingAgents code currently fills a capability gap large enough to justify coupling or source migration. Future adapters may wrap those frameworks behind the frozen FinAgent contracts.

### Explicitly deferred after Phase 1

- rolling/expanding walk-forward refitting;
- purge/embargo and nested validation;
- multiple-hypothesis correction and backtest-overfitting controls;
- historical universe/corporate-action handling;
- multi-currency accounting;
- short-borrow constraints;
- intraday quote/order-book semantics;
- persistent model binary storage;
- live broker connectivity;
- Agent orchestration.

---

## 2026-08-24 — Phase 0.5: Domain Kernel + Test Harness

### Goal

Freeze the first stable internal contracts before implementing forecasting models or agent orchestration. The implementation follows the Phase 0 architecture review: keep the quantitative core framework-independent and use adapters for Qlib, bt, LangGraph and broker-specific systems later.

### Implemented

#### 1. Typed asset and market contracts

Added `AssetId` with deterministic symbol/venue/type/currency identity.

Added `PriceBar` and `MarketSnapshot` with explicit point-in-time semantics. `event_time` and `available_at` are separate timestamps and snapshots reject observations that were not available at `asof`.

#### 2. Research dataset contract

Added `ResearchDataset` and `TimeRange`.

The dataset object is a schema/artifact contract, not a DataFrame. It carries universe, feature names, labels, split ranges, PIT status and an immutable dataset artifact reference.

#### 3. Forecast contracts

Added:

- `ModelRef`
- `AlphaForecast`
- `RiskForecast`

`RiskForecast` validates a complete covariance matrix, symmetry, non-negative diagonal values and consistency between diagonal variance and supplied volatility. Positive-semidefinite checks are deferred to Phase 1, where a numerical linear-algebra dependency will be introduced deliberately.

#### 4. Portfolio and risk contracts

Added `PortfolioState` and `PortfolioTarget`.

`PortfolioTarget` enforces the accounting identity:

```text
sum(weights) + cash_weight = 1
```

This supports long/short and levered portfolios without the long-only normalization behavior observed in some external backtest implementations.

Added explicit risk objects:

- `RiskDecision`
- `RiskStatus`
- `RiskViolation`

Risk controls are non-mutating. A failed risk check reports violations instead of silently changing weights.

#### 5. Orders and execution contracts

Added:

- `OrderIntent`
- `Fill`
- `OrderRejection`
- `ExecutionReport`

These establish the required boundary between target weights and actual fills.

#### 6. Research reproducibility and lineage primitives

Added:

- `ArtifactRef`
- `ExperimentSpec`
- `ExperimentRun`
- `ExperimentResult`

`ExperimentSpec.fingerprint` uses SHA-256 over the research hypothesis plus dataset/code artifact digests, universe, parameters, seed and parent artifacts. This is intentionally stronger than a factor-name/expression-only key.

#### 7. Framework-independent ports

Added protocols for:

- `AlphaModel`
- `RiskModel`
- `PortfolioOptimizer`
- `RiskGate`
- `ExecutionVenue`

No Qlib, RD-Agent, LangGraph, bt or broker SDK type appears in these contracts.

#### 8. Deterministic reference services

Added minimal services solely to exercise the contracts:

```text
EqualWeightTargetBuilder
    -> StaticRiskGate
    -> OrderPlanner
    -> SimulatedExchange
    -> AccountLedger
```

`OrderPlanner` requires an explicit `APPROVE` risk decision. `SimulatedExchange` supports deterministic adverse slippage and commission in basis points. `AccountLedger` applies fills to a new immutable `PortfolioState` without mutating the prior state.

### Tests

Added 26 tests. Local result on 2026-08-24:

```text
26 passed
```

Coverage areas include domain validation, PIT rejection, immutable mappings, forecast matrix validation, portfolio accounting, long/short semantics, risk gating, order planning, simulated fills, ledger accounting, experiment fingerprints and an end-to-end equal-weight smoke test.

### Canonical smoke path validated

The following closed loop is executable and tested without pandas, LLMs or external trading libraries:

```text
MarketSnapshot
    -> EqualWeightTargetBuilder
    -> PortfolioTarget
    -> StaticRiskGate
    -> RiskDecision(APPROVE)
    -> OrderPlanner
    -> OrderIntent[]
    -> SimulatedExchange
    -> Fill[]
    -> AccountLedger
    -> PortfolioState
```

Test scenario:

- initial cash: USD 1,000;
- two assets priced at USD 100 and USD 50;
- target: 50% / 50%;
- generated positions: 5 and 10 units;
- ending cash: USD 0;
- ending NAV: USD 1,000;
- resulting weights: 50% / 50%.

### Explicitly deferred

The following are intentionally not part of Phase 0.5:

- AR/ARMA/ARIMA models;
- ARCH/GARCH models;
- covariance estimation algorithms;
- optimized portfolio construction;
- production transaction-cost modeling;
- exchange calendars and event-driven clocks;
- partial fills and liquidity limits;
- multi-currency FX translation;
- broker connectivity;
- LLM/agent graph orchestration;
- persistent experiment registry;
- pandas/Qlib/bt/LangGraph adapters.

Deferring these prevents external frameworks or numerical implementation details from changing the domain contracts prematurely.

### Design decisions to preserve

1. No raw DataFrame is a public cross-module contract.
2. Point-in-time availability must be explicit.
3. Portfolio targets and fills are separate objects.
4. Risk decisions are explicit and non-mutating.
5. Research code/data/parameters/seed are part of experiment identity.
6. Third-party frameworks connect through adapters rather than defining FinAgent domain objects.
7. Direct source migration requires license and behavior audit before inclusion.

### Next step

Phase 1 should implement the first numerical vertical slice behind these interfaces:

```text
PIT data
 -> random-walk benchmark
 -> AR alpha forecast
 -> GARCH volatility forecast
 -> covariance forecast
 -> portfolio optimizer
 -> risk gate
 -> event-driven backtest
```

The Phase 0.5 contracts should only be changed if Phase 1 reveals a concrete incompatibility, and any such change should be recorded as an architecture decision rather than made implicitly.

# FinAgent Development Log

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

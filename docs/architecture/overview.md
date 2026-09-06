# FinAgent architecture overview

This document describes the architecture **implemented in the repository now**. Planned changes remain in stage plans until code lands.

## 1. System model

```text
Historical / broker data sources
          ↓
Data adapters + source identity
          ↓
Data Plane
  Parquet / DuckDB / calendars / actions / bounded queries
          ↓
Research materialization
  ResearchDataset / ResearchSplit / minute panels
          ↓
Research Core
  factors / FactorGraph / statistical and economic evaluation
          ↕
Agent Runtime
  typed research actions / budget ledger / development feedback
          ↓
Models / Portfolio / Historical Execution
          ↓
Evidence / application services
          ↓
Workbench projections + React UI

parallel operational path already present:

Replay / MT5 source
          ↓
Canonical realtime events
          ↓
Streaming features / algorithm path
          ↓
Realtime projections
          ↓
PAPER controller / broker adapter
          ↓
Reconciliation / safety / durable stores
          ↓
future accepted PAPER Workbench
```

## 2. Ownership by package

### `src/finagent/data` and `src/finagent/domain`

Own data/provider contracts, causal clock semantics, bounded datasets and source adapters. Large historical corpora remain out-of-core; `ResearchDataset` is a compute contract, not the physical storage layer for the whole minute archive.

### `src/finagent/research`

Owns factor/research calculations, FactorGraph execution, U.S. research programs and statistical/economic evaluation. Research results must remain reproducible from admitted data/config/code identities.

### `src/finagent/agents`

Owns LLM/provider interaction and bounded Agent research capabilities. The current R3 runtime uses typed actions and a durable SQLite budget/trial ledger. It is an application boundary, not an operating-system sandbox.

### `src/finagent/models`, `portfolio`, `backtest`

Own Alpha/Risk abstractions, portfolio construction/constraints and deterministic historical execution/evidence. Historical execution is not the broker state machine.

### `src/finagent/application`

Owns typed application/control-service boundaries used by CLI/Agent/Workbench rather than allowing UI code to call arbitrary Python/shell operations.

### `src/finagent/realtime`

Already owns canonical realtime events, database replay, MT5 streaming source, streaming transforms and idempotent projections. It must be reused for PAPER rather than replaced by another event framework.

### `src/finagent/operations`

Already owns approval, PAPER strategy/controller pieces, reconciliation, safety and durable stores. These modules are not yet accepted end to end for the target MT5 PAPER strategy.

### `src/finagent/brokers`

Owns broker-specific adapter semantics. Research instruments and broker instruments remain separate identities.

### `src/finagent/visualization` + `workspace/`

The Python visualization layer exposes projections/APIs; the React/Vite Workbench renders them. Browser code is not financial/statistical authority.

## 3. Agent versus deterministic authority

FinAgent deliberately gives the Agent substantial **research agency** while keeping final truth deterministic.

Agent may, inside a development policy:

- inspect admitted literature, market-state summaries, factor history and prior experiments;
- propose FactorGraphs/hypotheses;
- choose factor sets and allocator experiments;
- request deterministic evaluation;
- compare results;
- allocate remaining development experiment budget;
- retire or continue hypotheses.

Deterministic/human-owned boundaries:

- data chronology and source identity;
- factor/statistical/economic calculations;
- fixed experiment budgets and final gates;
- sealed/independent R5 evidence access;
- portfolio/account/broker truth;
- reconciliation and safety;
- PAPER/live authority and capital/risk ceilings.

The Agent's explicit decisions are product artifacts. Hidden chain-of-thought is not stored.

## 4. Time and information semantics

`event_time` and `available_at` remain distinct where applicable. Realtime events additionally preserve `received_at` and provider sequence/source identity.

Rules:

- forward labels are outcomes, never input features;
- bar interval/timestamp convention/session calendar are part of identity;
- market-state fitting/transforms are causal;
- replay may change delivery pacing but not market chronology;
- stale/delayed/frozen/disconnected sources are distinct conditions.

## 5. U.S. research data boundary

The active historical source is a local admitted snapshot of `mito0o852/OHLCV-1m` at revision `776328445b7ac6e7815ef3a483e9c8ded1eb6d56`.

The current 25-name EngineeringUniverse is suitable for the stated bounded research/integration program but is survivorship conditioned. It is not a PIT security-master universe and therefore does not support unrestricted market-wide historical claims.

No authoritative historical Tick/LOB source is part of the active architecture.

## 6. Factor architecture

Current typed FactorGraph provides bounded declarative factor representation and shared-DAG execution. R4 adds **research-level** MarketState, FactorLibrary and allocator concepts around this implementation; it does not replace the graph engine.

Intended R4 relationship:

```text
FactorGraph candidates ──→ FactorLibrary
                              │
MarketState probabilities ────┤
                              ↓
                         FactorAllocator
                              ↓
                        AdaptiveStrategy
```

Market-state or exposure-timing logic is not required to masquerade as a cross-sectional stock-selection factor.

## 7. Evidence model

Different stages need different evidence intensity:

- R4 development: causal/reproducible trials and complete adaptive search ledger;
- R5 confirmation: frozen spec + independent/prospective evidence + preregistered terminal;
- PAPER/LIVE: broker/account state, reconciliation, recovery, safety and incident evidence.

A successful software test or workflow run is not automatically financial Alpha evidence.

## 8. Workbench architecture

The existing Workbench has two conceptual planes:

```text
Evidence Plane
  read-only verified projections

Control Plane
  explicitly enabled typed application services
```

WorkbenchContext links identities/selections across analytical surfaces. Existing ECharts, React Flow and TanStack Table remain the default analytical/graph/table stack.

Workbench 2.0 will make Agent/experiment/market-state interaction the primary research workflow, but it remains a projection/control client over FinAgent core rather than a browser research engine.

## 9. Realtime/PAPER architecture

The canonical path is:

```text
source/replay
→ canonical event
→ projection/state
→ frozen strategy decision
→ safety/approval
→ broker command/event
→ reconciliation
→ canonical portfolio/account/health state
→ Workbench
```

React never calls MetaTrader5 directly. Unknown reconciliation or stale data must remain explicit and block mutation where policy requires.

## 10. Authority ladder

```text
Research platform capability
        ≠
Confirmed Alpha
        ≠
Historical economic acceptance
        ≠
MT5 demo/PAPER acceptance
        ≠
Live-capital authority
```

`NO_CONFIRMED_ALPHA` is a valid research terminal.

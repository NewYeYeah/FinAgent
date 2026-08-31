# Architecture overview

FinAgent separates **adaptive research** from **deterministic financial state and authority**.

## 1. Layered model

```text
Data / broker sources
        ↓
Provider adapters
  provider semantics, entitlement/capability declarations, source identity
        ↓
Historical Data Plane
  immutable source evidence, Parquet/DuckDB bounded scans, calendars/actions
        ↓
Bounded materialization
  ResearchDataset / ResearchSplit
        ↓
Research
  manual/programmatic/Agent candidate generation, Factor Quant, robust gates
        ↓
Models
  AlphaModel / RiskModel
        ↓
Portfolio and historical execution
  constraints, optimizer, market-specific execution semantics, cost accounting
        ↓
Immutable evidence
  reports, manifests, Parquet/SQLite/JSONL, exact identity and replay
        ↓
Workbench
  read-only Evidence projections + separately governed local Control
```

The future realtime/broker path is additive rather than a rewrite:

```text
Provider-neutral realtime events
        ↓
ReplayGateway / canonical state projections
        ↓
Broker gateway and queries
        ↓
Demo/PAPER order lifecycle
        ↓
Reconciliation / recovery / risk controls
        ↓
Live Workbench projections
```

## 2. Authority boundaries

The Agent may propose hypotheses, generate bounded feature code and consume development-only evidence. It may not mutate positions/fills, change final risk or acceptance thresholds after observing evidence, repeatedly consume sealed evaluation data, self-promote a strategy or directly submit broker/live-capital orders.

Browser code is presentation-only for authoritative financial facts. It can filter, select and visualize verified evidence; it does not recreate missing research, portfolio, execution or statistical truth.

## 3. Historical data boundary

`ResearchDataset` remains the bounded numerical compute contract. It is **not** the storage abstraction for a multi-billion-row minute corpus.

The U.S. minute architecture therefore inserts an out-of-core query layer below it:

```text
partitioned Parquet
        ↓
MarketDataQuery / DuckDB bounded scan
        ↓
MarketDataView
        ↓
bounded feature/label materialization
        ↓
ResearchDataset
```

Provider capability and FinAgent adapter capability are different concepts. An external provider may expose M1/realtime data while the installed FinAgent adapter implements only daily ingestion; the adapter must not advertise provider-level capability as implemented functionality.

## 4. Time and market semantics

Information and market clocks remain separate:

- `event_time`: market event represented by an observation;
- `available_at`: earliest time FinAgent may consume the observation;
- bar interval and timestamp convention are part of data identity;
- trading calendars are materialized/versioned evidence, not inferred from wall-clock rules in UI code;
- intraday labels use typed horizon semantics rather than ambiguous names such as `forward_return_4`.

For U.S. minute research, DST, holidays, half-days, extended hours, corporate actions and symbol lifecycle must be explicit before robust research can become authoritative.

## 5. Research identity and multiplicity

Evidence identity binds the exact dataset/source, universe policy, feature/code artifact, candidate denominator, program parameters, validation windows and strategy/execution protocol.

Every searched candidate remains in the effective multiplicity denominator, including Agent-generated candidates, failed candidates and alternative search arms where the experiment contract defines them as one family.

## 6. Historical versus broker execution

The existing synchronous `ExecutionVenue` abstraction remains a deterministic historical simulator. Broker execution is asynchronous and uses separate ports/events:

```text
OrderIntent
  → submit command
  → broker acknowledgement
  → accepted / rejected
  → partial fills
  → filled / cancelled / expired
  → deal/history reconciliation
```

Research instruments and broker instruments are separate identities. A listed U.S. equity and a broker stock CFD are not the same asset merely because their ticker text matches.

## 7. Workbench architecture

The Workbench keeps two independent authority planes:

```text
Evidence Plane
  GET-only verified projections

Control Plane
  explicit local opt-in
  allowlisted L0/L1 application services only
```

Realtime panels will consume canonical state projections, never MT5/QMT/vendor SDK calls directly from React.

## 8. Release meaning

FinAgent distinguishes:

```text
Research Platform Acceptance
≠ Alpha Acceptance
≠ Historical Portfolio Acceptance
≠ Demo/PAPER Acceptance
≠ Live-capital Acceptance
```

A valid no-alpha terminal is a successful research-platform outcome, not a profitable strategy claim.

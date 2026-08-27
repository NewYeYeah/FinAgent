# Architecture Overview

FinAgent separates adaptive research from deterministic financial state.

## Layered model

```text
Data sources
  local Parquet / market providers
        ↓
Data adapters
  PIT clocks, units, identity, ResearchDataset
        ↓
Research
  Agent hypotheses, generated features, Factor Quant, experiment families
        ↓
Models
  AlphaModel / RiskModel
        ↓
Portfolio
  constraints, optimizer, stress, RiskGate
        ↓
Validation
  nested walk-forward, multiplicity, DSR, PBO, Reality Check, sealed holdout
        ↓
Operations
  model registry, human approval, paper/shadow, reconciliation, kill switch
```

## Authority boundary

The Agent may:

- propose hypotheses;
- generate bounded feature code;
- read development-only structured evidence;
- propose new research candidates within a frozen budget.

The Agent may not:

- write positions or fills;
- set final portfolio weights;
- alter risk/acceptance thresholds after observing evidence;
- consume sealed holdout repeatedly;
- self-promote a model to PAPER/LIVE;
- bypass human approval.

## Data contract

`ResearchSplit` arrays use:

```text
feature_values[time, asset, feature]
label_values[time, asset, label]
eligibility_mask[time, asset]
```

`event_time` describes the market event represented by an observation. `available_at` is when the system may use it. Feature windows contain no observation with `available_at > asof`.

Forward labels are evaluation data and are clipped at split boundaries.

## Research identity

Evidence is bound to explicit immutable identity:

```text
data version / digest
universe
feature/code artifact
experiment family
parameters / seed
validation windows
strategy specification
```

Changing a provider, candidate family, dataset digest or strategy protocol creates different evidence.

## Factor research

Development path:

```text
Agent → candidate feature
      ↓
Factor Quant diagnostics
      ↓
structured development feedback
      ↺
complete candidate family
```

Formal validation is separate from Agent-visible feedback. Multi-factor selections are deterministic and frozen before independent validation.

## Historical execution clock

The reference historical backtest uses information at time `t` to create a target that executes no earlier than the configured next executable event. Market/execution snapshots expose only prices whose field-level availability is valid at `asof`.

## A-share data model

Local A-share raw data remains external and immutable. `LocalAshareParquetDataAdapter` normalizes vendor units and time semantics while preserving raw OHLC for market/execution use and adjusted research prices for return features/labels.

The current security master is candidate-only because source delisting/list-status history is incomplete. Supplemental status data is a separate identity and must not be silently merged into raw vendor files.

## Operational model

Research promotion and operational execution are deliberately separate. Human approval binds immutable requests to stage transitions or rebalance applications. `PaperStrategyRuntime` prepares a deterministic plan but does not own broker mutation.

## Persistence

Typed SQLite stores are used for generated features, research programs, experiment/result evidence, memory visibility, model registry and paper operations. Chat history is not a source of truth.

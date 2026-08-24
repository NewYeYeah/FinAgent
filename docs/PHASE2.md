# Phase 2 — Validation, Execution Timing, and Model Governance

Phase 2 strengthens the Quant Core before any LLM/Agent orchestration is introduced.

## Objectives

Phase 2 implements three previously deferred controls:

1. purged/embargoed chronological walk-forward validation;
2. explicit separation of information time and execution time;
3. durable experiment/model lifecycle management.

## Validation subsystem

Implemented:

```text
WalkForwardConfig
WalkForwardFold
PurgedWalkForwardSplitter
minimum_purge_bars
```

Canonical fold structure:

```text
rolling:   [train] [purge] [embargo] [test]
expanding: [----------- train -----------] [purge] [embargo] [test]
```

For canonical `forward_*_N` labels, `purge_bars >= N` is enforced by default.

Each fold is materialized by the normal frozen `DataAdapter -> DatasetRequest -> ResearchDataset` path. The splitter does not construct raw model arrays itself.

## Execution-time subsystem

Implemented:

```text
ExecutionQuote
ExecutionSnapshot
ExecutionDataAdapter
TimedExecutionVenue
TimedSimulatedExchange
TimedBacktestConfig
TimedBacktestPoint
TimedBacktestResult
TimedEventDrivenBacktestEngine
```

The main invariant is:

```text
execution_at > information_at
```

The default Phase 2 simulation is next executable open. `ExecutionSnapshot` deliberately exposes one price per asset rather than an OHLC bar.

The legacy `EventDrivenBacktestEngine` remains available as the Phase 1 close-on-close benchmark. Existing tests remain unchanged.

## Experiment lifecycle

Implemented:

```text
ExperimentEvaluation
ExperimentRunner
```

The runner persists RUNNING and terminal states and registers produced artifacts. Evaluator failure produces a durable FAILED run before the exception is propagated.

## Model governance

Implemented:

```text
ModelStage
RegisteredModel
ModelStageEvent
SQLiteResearchRegistry.register_model
SQLiteResearchRegistry.promote_model
SQLiteResearchRegistry.model_history
```

The current promotion sequence is:

```text
candidate -> validated -> paper -> shadow -> live -> retired
```

A future Agent may request a transition, but it will call this deterministic state machine and cannot jump directly from candidate to live.

## Compatibility

Phase 2 is additive:

- the Phase 1 `DataAdapter` protocol is unchanged;
- `ResearchDataset`, `ResearchSplit`, `FeatureWindow`, `AlphaModel`, `RiskModel`, `PortfolioOptimizer` and `RiskGate` retain their Phase 1 contracts;
- legacy execution/backtest classes remain available;
- no LLM framework dependency is introduced.

## Test coverage

Phase 2 adds tests for:

- label-horizon purge enforcement;
- rolling/expanding fold generation;
- fold dataset materialization;
- open-vs-close field-level availability;
- same-instant execution prevention;
- timed end-to-end numerical backtest;
- experiment success/failure lifecycle;
- model stage transition policy;
- SQLite result preservation during run-state updates.

Total local suite after Phase 2:

```text
55 passed
```

## Remaining research-hardening work

The next technical layer should focus on statistical selection risk rather than adding more forecasting models:

- nested walk-forward hyperparameter selection;
- White Reality Check / SPA-style benchmark comparison;
- Deflated Sharpe Ratio / Probability of Backtest Overfitting;
- multiple-hypothesis correction and experiment-family tracking;
- point-in-time universe membership and corporate actions;
- exchange calendars and session-aware clocks;
- model serialization / reproducible loading.

Only after those controls should the first Research Agent tool surface be introduced.

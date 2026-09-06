# Active data and source boundaries

This guide describes the data sources and authority boundaries that matter to the active roadmap. Historical one-off materialization procedures belong in Git/PR history.

## 1. U.S. historical minute research source

Current admitted source:

```text
repository: mito0o852/OHLCV-1m
revision: 776328445b7ac6e7815ef3a483e9c8ded1eb6d56
scope: local, non-redistributed research
```

The local corpus uses Parquet/DuckDB out-of-core access below bounded `ResearchDataset`/minute-panel materialization.

The source is treated as raw/split-unadjusted intraday history under the accepted cleaning/corporate-action policies. Do not assume a continuous adjusted price series across corporate actions.

The source does not publish a complete redistribution/license chain. Do not redistribute or make a stronger public provenance claim without a separate rights review.

## 2. Time semantics

Preserve:

```text
event_time / market timestamp
available_at where the research contract exposes information timing
explicit XNYS session/calendar semantics
bar interval and timestamp convention
same-session label/execution policy
```

DST, holidays and half-days come from the calendar/data contract, not UI/local-clock guesses.

## 3. Current EngineeringUniverse

The active 25-name engineering/research universe is:

```text
AAPL AMD AMZN AVGO COIN EEM GLD GOOG GOOGL INTC
IWM JPM META MSFT MSTR MU NFLX NVDA ORCL PLTR SNDK
TSLA TSM XLE XOM
```

This is a current-symbol/survivorship-conditioned universe selected partly for broker integration. It is **not** a point-in-time historical security master.

Use it for the currently stated bounded research problem. Do not generalize results to the entire historical U.S. equity market without lifecycle/PIT evidence.

## 4. Research data versus broker data

Historical listed-equity observations and MT5 broker CFDs are separate authorities.

```text
historical source
  research chronology / factor development

MT5 source
  broker symbol/contract/feed/account/execution semantics
```

A broker bar does not silently replace research history, and a research ticker does not prove a broker contract mapping.

## 5. Realtime/replay source roles

Use a single canonical realtime interface with different source roles:

```text
Database replay
  deterministic algorithm/replay development

connected non-target source (for example FX)
  transport/clock/reconnect plumbing only when market-invariant

MT5 target demo/PAPER source
  final source/account/order/reconciliation acceptance
```

Explicitly preserve source delay/freshness. Delayed data is not relabeled as current.

## 6. Tick/LOB limitation

No authoritative historical Tick/LOB dataset is currently admitted.

Therefore the active research program does not implement:

- order-flow imbalance;
- queue-position signals;
- Level-2/Level-3 book factors;
- historical market-impact learning.

Do not manufacture these from OHLCV proxies. Revisit only after an authoritative source exists.

## 7. A-share data

A-share Historical v1.0 is a frozen historical release. It is retained for release reproduction, Workbench artifacts and compatibility—not as the active research target. See [`../releases/ashare-historical-v1.md`](../releases/ashare-historical-v1.md).

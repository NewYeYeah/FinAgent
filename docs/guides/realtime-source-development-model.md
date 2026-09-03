# Realtime source development model

This guide defines the source strategy used to develop FinAgent algorithms and realtime infrastructure while preserving delayed-feed failure semantics and reserving target U.S. CFD for final broker/source freeze.

`docs/status.toml` remains the only current-stage authority. This guide does not advance US-D3 or any broker/PAPER/live gate.

## 1. Decision

FinAgent adopts one canonical streaming architecture with three primary development/freeze roles plus an explicit degraded timing profile:

```text
DEV-REPLAY
  certified/local U.S. historical database
  -> DatabaseReplaySource
  -> canonical BarEvent stream
  -> algorithm/feature/portfolio development

DEV-LIVE
  EURUSD / GBPUSD / USDJPY via MT5
  -> MT5 realtime adapter
  -> canonical QuoteEvent/BarEvent/ConnectionEvent
  -> real connected transport/runtime validation

DEGRADED
  MetaQuotes delayed U.S. reference or any future delayed-only broker API
  -> same canonical event contract
  -> explicit source-delay/freshness classification
  -> delay-budget and fail-closed validation

FINAL-FREEZE
  target broker U.S. CFD
  -> exact broker/server/account/symbol/contract/feed binding
  -> source timing classification + execution/reconciliation acceptance
```

The algorithm never chooses between these sources. Source selection is runtime/application configuration outside strategy logic.

## 2. Why the delayed path is retained

A progressing delayed feed is structurally different from both a current feed and a broken feed. The current MetaQuotes-Demo observation—roughly 900 seconds behind retrieval while ticks continue progressing—is useful precisely because a future broker may expose only delayed or polling market data.

The system must distinguish:

```text
CURRENT    source satisfies the frozen current/freshness policy
DELAYED    source progresses but effective source delay exceeds current policy
REPLAY     controlled historical delivery under a replay clock
UNKNOWN    timing capability cannot be proven
```

A delayed source can prove interface compatibility without proving current-market strategy authority.

If a strategy requires a 60-second freshness budget and the admitted source is 900 seconds delayed:

```text
transport healthy            = true
canonical interface healthy  = true
source timing class           = DELAYED
strategy data admissible      = false
current-market authority      = false
```

This is the expected fail-closed result.

## 3. Canonical source contract

The next implementation increment should introduce a provider-neutral subscription surface, for example:

```text
RealtimeMarketDataSource / MarketEventSource
subscribe(subscription) -> stream[CanonicalRealtimeEvent]

MarketDataSubscription
  symbols
  event_types
  interval
  start/end?                 # replay only when applicable
  pacing_mode

FeedTimingProfile
  source_id
  timing_class               # CURRENT / DELAYED / REPLAY / UNKNOWN
  observed_delay_seconds?
  latency/jitter diagnostics?
  freshness_policy_id
```

Provider implementations:

```text
DatabaseReplaySource
MT5RealtimeSource
```

Do not build separate strategy APIs such as `on_mt5_tick()` and `on_database_bar()`.

## 4. Database replay semantics

The local U.S. minute database is the main algorithm-development source because it preserves the target market’s historical cross-section and session structure.

For 1m OHLCV source rows, replay emits truthful `BarEvent` records only. It must not synthesize authoritative bid/ask, tick-by-tick trade paths or order-book state.

Chronology rule:

```text
historical event_time = preserved source market time
replay received_at    = replay delivery time
```

Pacing:

```text
1x       integration/soak
60x      normal algorithm development
FAST     deterministic CI/regression
STEP     debugger/manual inspection
DELAYED  delivery profile with explicit additional source/delivery delay
```

A representative replay mapping is:

```text
emit_wall_time = replay_wall_start + (event_time - replay_event_start) / speed
```

The replay clock never rewrites historical market chronology.

## 5. FX live semantics

FX is the default connected engineering source during normal development because it is readily observable and exercises real MT5 transport.

FX may validate:

```text
initialize/shutdown
server/account connectivity
polling loop
broker-clock normalization
time/time_msc parsing
received_at capture
quote progression/freshness
reconnect/error handling
event bus/backpressure
projection updates
algorithm runner/runtime stability
```

FX does not validate:

```text
U.S. cross-sectional Alpha
XNYS session microstructure
stock/CFD volume semantics
U.S. spread/liquidity
CFD contract/margin/fill semantics
U.S. research authority
```

## 6. Delayed-feed structural tests

Delay must be represented explicitly, not hidden inside an adapter.

Required tests include:

```text
progressing delayed quote             -> DELAYED, not STALE/FROZEN
frozen old quote                      -> stale/non-progressing failure
delayed quote inside strategy budget  -> admissible only if policy allows
delayed quote beyond strategy budget  -> fail closed
current -> delayed regime transition  -> source capability identity changes
delayed -> current transition         -> new timing evidence; no silent promotion
reconnect with retained delay          -> remains DELAYED
```

Retain the observed ~900-second MetaQuotes-Demo case as a canonical degraded-profile fixture where practical.

## 7. Algorithm boundary

The runtime path should be:

```text
MarketDataSource
    -> CanonicalRealtimeEvent
    -> RealtimeProjector / MarketState
    -> streaming resampler / FeatureEngine
    -> FeatureSnapshot
    -> AlgorithmRunner
    -> SignalIntent
    -> portfolio/execution ports
```

The algorithm may depend on canonical feature/market/state contracts, not provider implementation classes.

This means final CFD migration should normally replace only source/broker adapters and frozen capability identities, not algorithm code.

## 8. Final target-CFD freeze

The final broker campaign rebinds and freezes:

```text
broker/server/account
broker symbols and ResearchInstrument mapping
source timing class and delay/freshness distribution
contract size / point / tick size/value
volume min/max/step
spread/liquidity
session/trade/fill modes
margin/swap semantics
MT5-M1 canonical market events
MT5-E1 order lifecycle
MT5-O1 reconciliation/recovery/safety
```

If the broker supplies current data, freeze `CURRENT` evidence. If it supplies delayed-only data, freeze `DELAYED` evidence and keep current-market strategy authority false unless a separate admitted current source is introduced.

## 9. Relationship to current US-D3 evidence

The current US-D3 stage authority and Issue/evidence chain are not retroactively rewritten by this development model. Lane B remains the existing governed delayed-reference path until an explicit later governance change closes or redefines that gate.

However, normal implementation work should proceed using DEV-REPLAY and DEV-LIVE rather than waiting for Lane B capture. Lane B is retained because its delay semantics are useful and may match a future production constraint, not because every algorithm commit requires a U.S. active-session run.

## 10. Next implementation increment

The next coherent PR should implement **Streaming Source Harness v1**:

1. freeze `MarketDataSource` / `MarketDataSubscription` / `FeedTimingProfile` contracts;
2. implement `DatabaseReplaySource` on the existing DuckDB/Parquet U.S. minute plane;
3. support `1x`, accelerated, FAST and STEP pacing plus an explicit delayed-delivery profile;
4. feed replay output into the existing canonical realtime projector;
5. introduce an `AlgorithmRunner`/subscription boundary so algorithms cannot read DuckDB/MT5 provider objects directly;
6. wrap the existing MT5-M1 adapter as the live implementation of the same source boundary;
7. run differential contract tests showing DB replay and FX live reach the same downstream event/state API;
8. add delayed-profile tests that distinguish progressing-delay from stale/frozen data and enforce a strategy freshness budget;
9. preserve source-supported event types only—no synthetic bid/ask from OHLCV;
10. keep all outputs implementation/engineering-only until the existing stage and final target-broker gates are separately satisfied.

Acceptance for this increment is architectural and deterministic: source swapping must require configuration changes only, not algorithm changes.

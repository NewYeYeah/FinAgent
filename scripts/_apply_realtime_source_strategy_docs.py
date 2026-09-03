from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "development" / "current-plan.md"
SKILL = ROOT / "skills" / "finagent-project" / "SKILL.md"
GUIDE = ROOT / "docs" / "guides" / "realtime-source-development-model.md"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


plan = PLAN.read_text(encoding="utf-8")
plan = replace_once(
    plan,
    "### 2.12 Live Workbench is last\nDo not build live dashboards before the canonical event/state/reconciliation semantics they would display are accepted.\n\n---",
    """### 2.12 Live Workbench is last
Do not build live dashboards before the canonical event/state/reconciliation semantics they would display are accepted.

### 2.13 Three-source realtime development model; delayed feeds are a first-class degraded mode
FinAgent development uses three complementary market-data roles rather than treating one temporary broker feed as the universal development source:

```text
DEV-REPLAY   certified/local U.S. historical database -> paced canonical BarEvent stream
             purpose: algorithm, feature, portfolio and stateful streaming development

DEV-LIVE     FX (EURUSD / GBPUSD / USDJPY) -> real connected MT5 QuoteEvent stream
             purpose: transport, clock, polling, reconnect, freshness and runtime integration

FINAL-FREEZE target-broker U.S. CFD -> broker-specific current/delayed source + execution evidence
             purpose: final symbol/contract/feed/execution/reconciliation freeze
```

The observed MetaQuotes-Demo delayed U.S. equity feed remains a required **degraded/delayed-feed compatibility profile**, not a discarded anomaly. FinAgent must preserve and test structural delay behavior because a future target broker may expose only polling or delayed market-data APIs.

A source capability is therefore classified explicitly rather than inferred from ticker shape:

```text
CURRENT
DELAYED
REPLAY
UNKNOWN
```

Rules:
- algorithms consume provider-neutral canonical events/state, never MT5/DuckDB objects directly;
- `event_time` remains source/market time and `received_at` remains delivery time; replay may pace delivery but must not rewrite market chronology;
- delay/freshness is data, not a hidden adapter assumption: measured/declared source delay propagates into health/state and strategy admissibility;
- a delayed source may pass transport/interface compatibility while failing a strategy freshness budget; this is an intentional terminal, not a reason to relabel the quote as current;
- 1m OHLCV may generate truthful `BarEvent` replay only; it must not synthesize authoritative bid/ask/tick/order-book history that the source never contained;
- FX validates only asset/feed-invariant runtime behavior. It does not become U.S. research or CFD microstructure evidence;
- the current Lane B delayed U.S. evidence chain remains governed by its frozen policies/Issue until an explicit later governance change; normal implementation work must not be blocked on collecting it;
- final target-broker U.S. CFD acceptance rebinds broker/server/account/symbol/contract/source identities. If that broker is delayed-only, the previously tested degraded mode is used and current-market strategy authority remains unavailable unless another admitted current source exists.

This is a source-substitution architecture, not a market-substitution claim.

---""",
    label="plan strategic source model",
)
plan = replace_once(
    plan,
    """## Outcomes
```text
CERTIFIED_FOR_ENGINEERING_RESEARCH
CERTIFIED_FOR_RESEARCH_UNDER_LIMITATIONS
REJECTED
```""",
    """## Development/source boundary
US-D3 research certification and normal implementation progress are separated from the temporary availability of one current U.S. broker API:

- certified local U.S. history may be emitted through a paced database replay source to validate the exact streaming path used by algorithms;
- FX may validate connected source-invariant MT5 plumbing, but cannot itself satisfy U.S. research/reconciliation authority;
- the existing delayed U.S. Lane B path remains a governed structural-delay/degraded-feed evidence chain and is not weakened or silently replaced;
- no delayed source is promoted to current market-data authority merely because the algorithm interface works;
- final U.S. CFD broker/source semantics remain a later broker-specific freeze.

The current formal US-D3 evidence requirements remain whatever `docs/status.toml`, the frozen policies and their active issue/evidence chain require; this planning clarification changes the development dependency model, not accepted evidence retroactively.

## Outcomes
```text
CERTIFIED_FOR_ENGINEERING_RESEARCH
CERTIFIED_FOR_RESEARCH_UNDER_LIMITATIONS
REJECTED
```""",
    label="US-D3 source boundary",
)
plan = replace_once(
    plan,
    """Replay fixtures are authoritative for contract tests, not evidence of broker readiness.

---

# 21. RT-R2""",
    """Replay fixtures are authoritative for contract tests, not evidence of broker readiness.

## Streaming-source development extension
The next implementation increment turns replay from a pre-built event tuple into the same subscription surface used by live sources:

```text
RealtimeMarketDataSource / MarketEventSource
FeedTimingProfile
DatabaseReplaySource        # DuckDB/Parquet -> paced BarEvent
MT5RealtimeSource           # FX during development; U.S. CFD at final freeze
AlgorithmSubscription
AlgorithmRunner
```

Required replay modes:

```text
1x realtime pace
accelerated pace (for example 60x)
as-fast-as-possible deterministic regression
step/debug mode
explicit delayed delivery profile
```

The database source preserves historical `event_time` and assigns delivery/`received_at` according to the replay clock/profile. The same algorithm runner must be able to consume database replay, FX live and target-CFD live/delayed streams without provider-specific strategy branches.

Delay is tested structurally through a `FeedTimingProfile`/equivalent contract. A strategy declares or derives a maximum admissible freshness/decision budget; a source whose effective delay exceeds that budget is rejected/degraded even if connectivity is healthy.

---

# 21. RT-R2""",
    label="RT-R1 streaming source extension",
)
plan = replace_once(
    plan,
    """## Goal
Normalize official MT5 historical/realtime bar/tick data into realtime contracts and persist differences from the historical research source.

Do not select “the better source” silently. Reconciliation records timestamp/session/OHLC/volume/instrument differences and classifies expected CFD-vs-equity differences separately from data-quality failures.""",
    """## Goal
Normalize official MT5 historical/realtime bar/tick data into realtime contracts, classify the observed feed timing capability, and persist differences from the historical research source.

Do not select “the better source” silently. Reconciliation records timestamp/session/OHLC/volume/instrument differences and classifies expected CFD-vs-equity differences separately from data-quality failures.

Final source admission records whether the bound target source is `CURRENT`, `DELAYED` or `UNKNOWN` under a frozen timing/freshness policy. A delayed-only target may prove adapter/runtime compatibility but does not create current-market authority. Strategy activation must compare the measured source delay/freshness against the strategy decision budget and fail closed when the source is too old.

Development should first prove the identical canonical interface with FX live and database replay; target U.S. CFD is reserved for the smallest broker/source-specific freeze surface.""",
    label="MT5-M1 timing capability",
)
plan = replace_once(
    plan,
    "RT-R0/R1/R2\nMT5-M1/E1/O1",
    "RT-R0/R1/R2 + streaming-source harness (database replay / FX live / delayed profile)\nMT5-M1/E1/O1",
    label="recommended PR sequence",
)
PLAN.write_text(plan, encoding="utf-8")

skill = SKILL.read_text(encoding="utf-8")
skill = replace_once(
    skill,
    "| Which realtime tasks actually require the U.S. session, and how should an active-session run be prepared? | `guides/realtime-development-validation.md` → relevant stage guide/source |",
    "| Which realtime tasks actually require the U.S. session, and how should an active-session run be prepared? | `guides/realtime-development-validation.md` → relevant stage guide/source |\n| Which source should algorithms/realtime development use, and how must delayed feeds be handled? | `guides/realtime-source-development-model.md` → RT/MT5 source + algorithm-runner tests |",
    label="skill task routing",
)
skill = replace_once(
    skill,
    "11. **Realtime development is replay-first, broker-last.** Do not wait for a live interface to implement/test provider-neutral contracts, ReplayGateway, deterministic projections, restart behavior or evidence validators; reserve real-session/broker interaction for the smallest acceptance surface that actually requires it.",
    """11. **Realtime development is replay-first, broker-last.** Do not wait for a live interface to implement/test provider-neutral contracts, ReplayGateway, deterministic projections, restart behavior or evidence validators; reserve real-session/broker interaction for the smallest acceptance surface that actually requires it.
12. **Source substitution is by canonical contract, not by market identity.** Algorithms must consume canonical events/state through a provider-neutral source/subscription boundary. Use local U.S. database replay for market/algorithm semantics, FX live for connected transport/runtime semantics, and target U.S. CFD only for final broker/source freeze.
13. **Delayed feeds are a supported degraded mode, not “bad current data.”** Preserve measured/declared delay through `event_time`/`received_at` and health/freshness state. If delay exceeds a strategy decision budget, fail closed or downgrade the strategy; never relabel delayed observations as current.""",
    label="skill source rules",
)
skill = replace_once(
    skill,
    """Lane C — future target-broker current U.S. equity/CFD feed
    authority: separately admitted broker-specific PAPER/live-current evidence
```""",
    """Lane C — future target-broker U.S. equity/CFD feed
    authority: separately admitted broker-specific source/PAPER evidence
    timing class: CURRENT, DELAYED or UNKNOWN must be measured/frozen; never assumed
```

Development source roles are orthogonal to those authority lanes:

```text
DEV-REPLAY — certified/local U.S. historical DB -> paced canonical BarEvent stream
DEV-LIVE   — FX live -> real MT5 transport/runtime stream
DEGRADED   — delayed U.S./future delayed broker source -> structural delay/freshness tests
FINAL      — target U.S. CFD -> broker/server/account/source/execution freeze
```""",
    label="skill lane model",
)
skill = replace_once(
    skill,
    "- future broker/server/account evidence is a new admission chain; never auto-promote Lane A or Lane B identities into Lane C;",
    "- future broker/server/account evidence is a new admission chain; never auto-promote Lane A or Lane B identities into Lane C;\n- do not discard Lane B because development can proceed with FX/replay: keep it as the canonical structural delayed-feed/degraded-mode case; a future delayed-only broker should reuse the same semantics, not a special workaround;\n- a target broker may be admitted as interface-compatible while still classified delayed-only; current-market strategy authority remains false when the measured delay exceeds its freshness/decision budget;\n- never manufacture QuoteEvent bid/ask/tick history from OHLCV-only database rows; database replay emits only source-supported event types;",
    label="skill lane rules",
)
skill = replace_once(
    skill,
    "Use `docs/guides/realtime-development-validation.md` as the operator checklist for pre-session preparation, active-session capture and post-capture offline certification.",
    """Use `docs/guides/realtime-development-validation.md` as the operator checklist for pre-session preparation, active-session capture and post-capture offline certification.

### 5.3 Algorithm streaming-source protocol

Normal algorithm/runtime development should use one subscription contract with interchangeable sources:

```text
DatabaseReplaySource  -> canonical BarEvent / source-supported events
MT5 FX live source    -> canonical QuoteEvent / BarEvent / ConnectionEvent
MT5 delayed source    -> same canonical events + explicit delay/freshness state
MT5 target CFD source -> same canonical events + broker/source freeze identity
```

Rules:

1. The algorithm must not import/use DuckDB or MetaTrader5 provider objects directly.
2. Preserve market chronology: historical replay changes delivery pacing, not `event_time`.
3. Provide 1x, accelerated, as-fast-as-possible and step replay modes; deterministic mode must reproduce event/state identities.
4. Maintain a feed timing profile with measured/declared delay, latency/jitter/freshness metadata and source identity.
5. Test delayed delivery separately from stale/frozen data. A progressing 900-second delayed feed is structurally different from a disconnected or non-progressing feed.
6. Compare effective source delay with the strategy’s decision/freshness budget before allowing signal/execution use.
7. Use FX to validate live transport/runtime only; use U.S. historical replay for U.S. algorithm/cross-sectional behavior; use target U.S. CFD for final broker/source semantics.
8. Keep final source capability honest: `CURRENT`, `DELAYED`, `REPLAY` or `UNKNOWN` are distinct states.
9. Provider/source switching must happen outside algorithm logic. The same `AlgorithmRunner`/feature/state path should process replay and live sources.
10. Final CFD freeze should be a differential acceptance: compare canonical contract/state behavior between replay/FX-hardened implementation and the target broker, then freeze only broker/source-specific differences.

See `docs/guides/realtime-source-development-model.md` for the development model and next implementation increment.""",
    label="skill streaming source protocol",
)
skill = replace_once(
    skill,
    "- [ ] delayed U.S. simulation evidence is not described as current executable-spread or target-broker authority;",
    "- [ ] delayed U.S. simulation evidence is not described as current executable-spread or target-broker authority;\n- [ ] delayed-feed compatibility is not removed merely because FX/database replay are the normal development sources;\n- [ ] database replay does not invent bid/ask/tick/order-book data absent from the historical source;\n- [ ] algorithms are provider-neutral and do not branch on DuckDB/MT5 source implementations;",
    label="skill review checklist",
)
skill = replace_once(
    skill,
    "Realtime development / active-session workflow: `docs/guides/realtime-development-validation.md`.\n\nCurrent stage: `docs/status.toml`.",
    "Realtime development / active-session workflow: `docs/guides/realtime-development-validation.md`.\n\nRealtime source / database replay / delayed-feed model: `docs/guides/realtime-source-development-model.md`.\n\nCurrent stage: `docs/status.toml`.",
    label="skill entry point",
)
SKILL.write_text(skill, encoding="utf-8")

guide = """# Realtime source development model

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
"""
GUIDE.write_text(guide, encoding="utf-8")

print("realtime source strategy docs patched")

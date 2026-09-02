# MT5 continuous smoke, delayed-reference simulation and live broker admission

This guide separates three different purposes that must not be conflated:

```text
continuous/near-continuous MT5 instruments
        -> engineering transport/clock smoke only

MetaQuotes-Demo U.S. equities without paid/community market-data subscription
        -> 15-minute delayed simulation/reference evidence only

future broker demo/real account with current quotes
        -> broker-specific live-current / execution evidence
```

The distinction is an authority boundary, not merely a configuration choice. A delayed simulation quote can be useful for integration, mapping and historical research plumbing while remaining explicitly invalid as evidence of live executable price freshness.

## 1. Continuous-market engineering smoke

Default symbols are:

```text
EURUSD
GBPUSD
USDJPY
```

These are used because the current MetaQuotes-Demo connection has demonstrated continuously updating weekday quotes and a stable broker-clock offset. They are not members of the U.S. research universe and are not used as substitute U.S. assets.

Run:

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent

python scripts\smoke_mt5_continuous_quotes.py `
  --symbols EURUSD GBPUSD USDJPY `
  --reference-symbols EURUSD GBPUSD USDJPY `
  --minimum-symbol-count 3 `
  --maximum-quote-age-seconds 60 `
  --maximum-future-quote-skew-seconds 5 `
  --expected-package-version 5.0.6147 `
  --output reports\mt5\mt5_continuous_quote_smoke.json
```

Expected engineering result while those markets are actively quoting:

```text
passed = true
passed_symbol_count = 3
clock_evidence.passed = true
stage_exit_authority = false
research_universe_authority = false
execution_authority = false
```

The smoke validates read-only transport, broker-server identity, broker-clock normalization, current quote freshness for the chosen continuous instruments, positive bid/ask and diagnostic spread calculation. It deliberately does not call `symbol_select`, `order_check`, `order_send` or any account/position mutation API.

## 2. Observed MetaQuotes-Demo U.S. quote regime

The active-session September 2026 probe established a stable and reproducible source behavior:

```text
broker clock normalization      passed
broker clock offset             +10800 seconds
U.S. seed ticks                 continuously progressing
U.S. seed normalized quote age  approximately 900 seconds
```

AMD, INTC, MSFT and NVDA changed `time_msc`, bid, ask and last on repeated five-second samples, so the feed was not frozen. After the accepted +3-hour broker-clock normalization, the source was approximately fifteen minutes behind retrieval time.

The existing `finagent.us-candidate-quote-probe-report.v2` remains unchanged. It continues to ask whether a quote is current under the original live/current freshness semantics and therefore correctly records a quote slightly older than 900 seconds as `stale_quote`.

FinAgent does **not** change the existing 900-second v2 current-quote threshold to 901/905/1200 seconds merely to obtain a pass.

## 3. Simulation regime without a broker account

The simulation phase intentionally does not require a broker account and does not purchase/subscribe to the MetaQuotes community real-time equity feed. Instead it introduces a separate, content-addressed delayed-reference timing policy:

```text
source_regime = metaquotes_demo_delayed_reference_without_broker_account
expected_broker_server = MetaQuotes-Demo
broker_account_required = false
expected_source_delay_seconds = 900
maximum_anchor_age_seconds = 60
maximum_future_anchor_skew_seconds = 60
```

The simulation validation anchor is:

```text
validation_anchor_at_utc = retrieved_at_utc - 900 seconds
anchor_age = validation_anchor_at_utc - normalized_sampled_at_utc
```

A quote is timing-valid for this regime only when:

```text
-60 seconds <= anchor_age <= +60 seconds
```

This is materially different from increasing the raw quote-age limit. The raw v2 report remains the upstream provenance and may still contain `stale_quote`. The delayed-reference report independently asks whether that same progressing quote is consistent with the preregistered 15-minute source regime.

A quote with approximately zero delay is deliberately **not** admitted under this policy: it is about 900 seconds ahead of the delayed-reference anchor. If MetaQuotes-Demo changes from delayed to current equity quotes, a new source regime/policy must be frozen rather than silently inheriting the delayed policy.

Freeze the policy:

```powershell
python scripts\freeze_us_i0_simulation_quote_policy.py `
  --output reports\us_instruments\us_i0_simulation_quote_policy.json
```

Assess an immutable raw quote-probe artifact:

```powershell
python scripts\assess_us_i0_delayed_reference_quotes.py `
  --quote-probe reports\us_instruments\us_i0_candidate_quotes.json `
  --policy reports\us_instruments\us_i0_simulation_quote_policy.json `
  --output reports\us_instruments\us_i0_delayed_reference_quotes_<raw-report-id>.json
```

The output path is intentionally immutable. If a new raw quote-probe identity is collected, use a new delayed-reference output path rather than overwriting an older evidence artifact.

### Authority of delayed-reference evidence

A passing delayed-reference report may claim only limited simulation/engineering reference authority:

```text
simulation_reference_authority = true
engineering_reference_authority = true
broker_account_required = false

live_market_data_authority = false
live_executable_spread_authority = false
broker_account_authority = false
execution_authority = false
order_authority = false
live_capital_authority = false
status_authority = false
stage_exit_authority = false
```

The first implementation stage stops here. It does not feed the existing v3 live/current EngineeringUniverse finalizer and does not advance `docs/status.toml`.

## 4. Why the delayed simulation anchor is acceptable

The design is reasonable for the simulation phase because the questions being answered are integration and research questions rather than live execution questions:

- can ResearchInstrument and MT5 reference symbols be mapped reproducibly;
- does the MT5 read-only transport progress and preserve source timestamps;
- are source clocks normalized correctly;
- can delayed spread/quote observations be retained as diagnostic simulation references;
- can historical B0/A0/R1 research and provider-neutral replay/runtime components be developed without broker-account side effects.

It is **not** reasonable to use the same evidence to claim:

- current executable spread;
- current liquidity or slippage;
- broker contract/account readiness;
- PAPER order readiness;
- live-capital readiness.

For that reason the simulation regime receives a separate policy/report identity rather than modifying the live-current policy.

## 5. Revised development arrangement

The work is split into two evidence regimes and five implementation blocks.

### S1 — delayed-reference timing/evidence contract — current increment

Deliverables:

```text
canonical delayed-reference timing policy
raw-v2 -> delayed-reference assessment
content-addressed report/parser
regime-separation tests
operator guide
```

S1 has no universe-finalization or stage-exit authority.

### S2 — simulation-specific EngineeringUniverse admission

After the intended U.S. symbols are manually visible in Market Watch, build a simulation-specific finalizer that consumes:

```text
candidate selection
+ raw v2 quote provenance
+ delayed-reference assessment
+ fresh read-only symbol inventory
```

It may use delayed bid/ask spread only as a simulation engineering-universe diagnostic. It must carry `live_executable_spread_authority=false` and must not reuse the existing live/current v3 finalizer identity.

A simulation-specific US-D3 acceptance path, if introduced, must preserve the same limitation and must never imply broker/live readiness.

### S3 — historical research and Agent execution

Once the simulation research environment is explicitly admitted, execute the already implemented historical evidence line:

```text
US-B0 deterministic baselines
        -> US-A0 Agent Value PILOT/FORMAL
        -> US-R1 robust intraday Alpha Gate
```

These stages use the certified historical data plane. Delayed MT5 reference quotes do not become labels or authoritative historical prices.

### S4 — provider-neutral realtime/replay engineering

Provider-neutral work may continue without a broker account:

```text
RT-R0 event contracts
RT-R1 ReplayGateway
RT-R2 append-only projections/state
```

Replay evidence remains engineering authority only.

### L1 — future live broker re-admission

Before MT5-M1/MT5-E1 or any live-current claim, bind the actual target broker/server/account and repeat broker-specific admission. Simulation evidence does not auto-promote.

The minimum re-admission work is:

```text
fresh MT5-P0 capability probe against target broker
broker/server/account identity binding
broker symbol inventory and ResearchInstrument <-> BrokerInstrument mapping
current quote freshness and spread/liquidity evidence
contract/tick/volume min/max/step semantics
margin/swap/session/order/fill-mode evidence
M1/tick source reconciliation
broker-specific historical execution/cost acceptance where required
MT5-M1 realtime gateway acceptance
MT5-E1 target-broker demo/PAPER execution
MT5-O1 reconciliation/recovery/safety
RT-R3 live Workbench acceptance
MT5-L0 separate human-governed live-capital gate
```

### Expected live-transition development workload

The live transition is a **broker-admission and execution integration increment**, not a rewrite of the research stack.

Mostly reusable without redesign:

```text
US-D1/D2 historical data plane and calendar/label semantics
US-B0 deterministic baseline engine
US-A0 Agent/DeepSeek controlled experiment
US-R1 robust inference and Alpha Gate
provider-neutral RT-R0/R1/R2 contracts/replay/projections
deterministic historical execution architecture where broker-independent
```

Broker-specific work that must be repeated or completed for live:

```text
MT5-P0 / US-I0 broker evidence
current quote and executable spread authority
BrokerInstrument contract properties
historical CFD friction calibration in US-X0/X1
MT5-M1 market gateway
MT5-E1 order lifecycle
MT5-O1 recovery/reconciliation/safety
live Workbench acceptance and separate capital gate
```

The expected engineering effort is therefore moderate rather than architectural: the provider-neutral research/replay layers are retained, while broker-facing evidence and adapters are re-bound and re-tested.

## 6. Market Watch remains an operator boundary

FinAgent still does not call `symbol_select()` in the governed US-I0 path. The intended candidate symbols must be manually exposed in MT5 Market Watch.

A `not_visible` raw issue cannot be reinterpreted as delayed. Only a raw quote with no issue or with the delay-only `stale_quote` issue is eligible for delayed-reference timing assessment; all other raw issues remain fail-closed.

## 7. US-B0 preimplementation while US-D3 is pending

The formal baseline runner remains fail-closed until `docs/status.toml` actually advances to `US-B0`. Development can nevertheless continue on contracts and synthetic/fixture regressions.

The pilot walk-forward design remains frozen as the existing three expanding folds, with actual observations filtered by the accepted XNYS regular-session calendar. The simulation quote regime does not modify B0 fold geometry, labels or research-price semantics.

## Authority boundary

Until a later simulation-specific admission increment is reviewed:

```text
current project stage                  US-D3
raw live/current v2 quote Gate         unchanged
MetaQuotes-Demo U.S. quote behavior    progressing, approximately 15m delayed
S1 delayed-reference evidence          simulation/reference only
formal live-current US-I0 v3 universe  still not accepted
broker account authority               none
order/live-capital authority           none
US-B0 real-data evidence                forbidden until stage authority advances
```

This separation permits a no-account simulation program without converting delayed market data into live broker authority, and it preserves a clean re-admission boundary for the eventual real broker/account implementation.

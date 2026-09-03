# MT5 continuous smoke, delayed-reference simulation and live broker admission

This guide separates three MT5 feed/evidence lanes that must not be conflated:

```text
Lane A — FX continuous/near-continuous engineering fixture
        -> transport / broker clock / current bid-ask health only

Lane B — MetaQuotes-Demo U.S. equity delayed reference
        -> simulation EngineeringUniverse / delayed-reference evidence only

Lane C — future target-broker current U.S. equity/CFD feed
        -> broker-specific PAPER/live-current/execution admission
```

The distinction is an authority boundary, not merely a symbol-selection convenience. Switching between FX and U.S. equity symbols during development is allowed only when the test is explicitly asset/feed-invariant. Evidence never auto-promotes from one lane to another.

## 1. What the approximately 15-minute delay means

The observed roughly 900-second U.S. equity delay is **not** treated as an intrinsic delay of the `MetaTrader5` Python API and is **not** assumed to apply to every stock or stock CFD. It is a property of the bound server/feed/subscription regime observed for the relevant symbols.

FinAgent therefore distinguishes:

```text
API transport latency
broker/server clock offset
quote timestamp age
market-data subscription/feed delay
exchange/session state
```

These are separate measurements. A future server or account may expose the same ticker with different timing, contract, execution or subscription semantics and therefore requires a different evidence identity.

`MT5FeedRegimeEvidence` preserves the feed/symbol fingerprint fields exposed by the existing read-only `symbols_get()` inventory:

```text
subscription_delay
chart_mode
trade_exemode
ticks_bookdepth
```

The evidence is bound to the existing MT5 capability-probe identity, broker server, symbol and unchanged `MT5SymbolSpec.spec_id`. It deliberately does not add these fields to `MT5SymbolSpec` v1, so accepted MT5-P0/S2 identities do not drift merely because diagnostic feed metadata was added.

Missing fields remain `None` with explicit `unavailable_not_inferred` limitations. When a symbol is not visible, `subscription_delay` is deliberately treated as unknown rather than inferred or trusted outside the governed Market Watch boundary. Existing quote-age, delayed-anchor, spread, universe, reconciliation and stage thresholds remain unchanged.

### Read-only feed-regime fingerprint

The lane is explicit input; FinAgent never auto-detects Lane A/B/C from ticker shape, quote age or contract fields.

Lane A example:

```powershell
python scripts\probe_mt5_feed_regime.py `
  --feed-lane fx_continuous_engineering_fixture `
  --symbol EURUSD `
  --symbol GBPUSD `
  --symbol USDJPY `
  --expected-package-version 5.0.6147 `
  --output reports\mt5\mt5_feed_regime_fx.json
```

Lane B example, after the U.S. symbols have been manually exposed in Market Watch:

```powershell
python scripts\probe_mt5_feed_regime.py `
  --feed-lane metaquotes_demo_delayed_us_equity_reference `
  --symbol AMD `
  --symbol INTC `
  --symbol MSFT `
  --symbol NVDA `
  --expected-package-version 5.0.6147 `
  --output reports\mt5\mt5_feed_regime_us_delayed.json
```

The script uses only the MT5-P0 read-only client and does not call `symbol_select()` or a market-book subscription/mutation API. Its report is permanently diagnostic-only:

```text
scope = mt5_feed_regime_diagnostic_only
research_universe_authority = false
us_i0_authority = false
mt5_d0_authority = false
us_d3_authority = false
paper_authority = false
execution_authority = false
live_market_data_authority = false
live_executable_spread_authority = false
stage_exit_authority = false
```

A complete diagnostic report means only that all requested symbols resolved to a bound fingerprint without inventory/identity errors. It is not an admission Gate.

## 2. Lane A — FX engineering fixture

Default engineering symbols are:

```text
EURUSD
GBPUSD
USDJPY
```

They are useful because the current MetaQuotes-Demo connection has demonstrated continuously updating weekday quotes and a stable broker-clock offset. They are **not** members of the U.S. research universe and are never substitutes for U.S. research assets.

Run the engineering smoke:

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

Expected authority:

```text
passed = true                 # when the selected FX feed is actively quoting
stage_exit_authority = false
research_universe_authority = false
execution_authority = false
```

### What FX may validate

FX may be used to exercise MT5 behavior that is intentionally independent of the U.S. asset/feed regime:

```text
initialize / shutdown / reconnect
terminal_info / account_info
server identity
symbols_get / symbol_info plumbing
symbol_info_tick plumbing
broker-clock offset and normalization
time/time_msc parsing
current bid/ask numeric validation
quote timestamp progression and freshness
read-only inventory serialization
content-addressed report construction
error / timeout / retry handling
```

This is the permanent purpose of the continuous-product smoke introduced by the simulation-limited US-D3 bridge.

### What FX may not validate

A passing FX smoke must never be used to satisfy or imply:

```text
US-I0 candidate admission
U.S. Market Watch candidate visibility
U.S. delayed-reference timing admission
U.S. stock/CFD session behavior
U.S. stock trade/Last tick behavior
U.S. stock volume semantics
U.S. spread/liquidity Gate
U.S. MT5-D0 reconciliation
US-D3 U.S. research certification
BrokerInstrument stock/CFD margin/fill/session semantics
PAPER/live target-broker admission
```

The FX preflight is deliberately absent from the U.S. certification denominator.

## 3. FX and regularly-opened U.S. equities are not microstructure-equivalent

The two lanes share the MT5 transport but not the market semantics.

| Dimension | FX engineering fixture | U.S. equity / equity-CFD reference |
| --- | --- | --- |
| Trading schedule | near-continuous weekday quoting, broker maintenance possible | exchange/session bounded, holidays/half-days/DST material |
| Primary plumbing check | current bid/ask quote progression | quote progression plus stock-specific feed/session semantics |
| `last` / trade ticks | may be absent or non-authoritative for the fixture | may carry material trade-price semantics depending on feed |
| Volume | broker/feed-specific tick volume semantics | stock/equity feed semantics can differ materially |
| Spread evidence | useful current engineering diagnostic | delayed feed spread is reference-only; target broker must re-admit executable spread |
| Contract/margin/fill | FX-specific | CFD/exchange-stock configuration may differ |
| Corporate actions | not a primary concern | splits/dividends/lifecycle matter for research/history |

Do not write a generic test whose hidden assumption is “all symbols behave like EURUSD.” Asset/feed-specific behavior must remain behind explicit policy/evidence boundaries.

## 4. Lane B — observed MetaQuotes-Demo U.S. delayed-reference regime

The active-session September 2026 probe established:

```text
broker clock normalization      passed
broker clock offset             +10800 seconds
U.S. seed ticks                 continuously progressing
U.S. seed normalized quote age  approximately 900 seconds
```

AMD, INTC, MSFT and NVDA changed `time_msc`, bid, ask and last on repeated samples, so the feed was not frozen. After accepted broker-clock normalization, the source remained approximately fifteen minutes behind retrieval time.

The existing `finagent.us-candidate-quote-probe-report.v2` remains a live/current freshness probe. It correctly preserves raw provenance and may mark a roughly 900-second quote as `stale_quote`. FinAgent does **not** widen the v2 freshness threshold merely to force acceptance.

The separate delayed-reference policy asks a different question:

```text
source_regime = metaquotes_demo_delayed_reference_without_broker_account
expected_broker_server = MetaQuotes-Demo
broker_account_required = false
expected_source_delay_seconds = 900
maximum_anchor_age_seconds = 60
maximum_future_anchor_skew_seconds = 60
```

with:

```text
validation_anchor_at_utc = retrieved_at_utc - 900 seconds
anchor_age = validation_anchor_at_utc - normalized_sampled_at_utc

-60 seconds <= anchor_age <= +60 seconds
```

A nearly current quote is intentionally **not** admitted under this delayed policy. If the source changes to current U.S. quotes, freeze a new regime/policy rather than silently reusing the delayed one.

### Session timing consequence

For a roughly 15-minute delayed U.S. feed, the observable regular-session window is effectively shifted relative to wall-clock retrieval time. Near the exchange open, a delayed anchor may still point to pre-open time; after the exchange close, delayed updates may continue for approximately the source-delay interval.

Authoritative U.S. research sessions remain governed by the accepted XNYS calendar evidence. MT5 quote timing is diagnostic/source evidence and must not replace the materialized trading calendar.

## 5. Lane B operator flow and Market Watch boundary

FinAgent does not call `symbol_select()` in the governed US-I0 path. The intended U.S. candidates must be manually exposed in MT5 Market Watch before active-session evidence collection.

A `not_visible` raw issue cannot be reinterpreted as delayed. Only raw provenance compatible with the delayed-reference assessment may continue; unrelated raw failures remain fail-closed.

Freeze the delayed timing policy:

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

The S2 simulation-universe implementation is present on `main`. Its frozen policy remains:

```text
target selected names = 25
minimum valid names   = 20
maximum selected      = 30
delayed diagnostic spread threshold = 50 bps
fresh inventory bound = 900 seconds
required seed retention = AMD, INTC, MSFT, NVDA
```

The operator evidence run must still use the intended U.S. candidate set, a fresh read-only inventory and the exact frozen S2 identities. Do not lower the minimum count, widen the 50-bps diagnostic threshold or remove seed retention to obtain a pass.

The simulation-limited US-D3 bridge is also implemented on `main`. It may consume accepted S2 and U.S. MT5-D0 evidence while preserving delayed/no-target-broker/no-executable-spread limitations. Its existence does not itself advance `docs/status.toml`; stage advancement still requires the actual governed evidence chain and later status update.

## 6. Authority of delayed-reference evidence

Passing Lane B evidence may support only the authority explicitly carried by the simulation contracts. It does not create current executable-market authority.

```text
simulation/engineering reference authority   allowed when the governed report passes
live market-data authority                    false
live executable-spread authority              false
target broker/account authority               false
order authority                               false
live-capital authority                        false
automatic status authority                    false
```

Delayed MT5 quotes do not become historical labels or authoritative research prices. US-B0/A0/R1 continue to use the certified historical data plane and their own frozen research protocols.

## 7. Lane C — future target-broker re-admission

Before MT5-M1/MT5-E1, PAPER or any live-current claim, bind the actual target broker/server/account and repeat broker-specific admission. Simulation evidence does not auto-promote.

The re-admission surface includes, as applicable:

```text
fresh MT5-P0 capability probe
broker/server/account identity
actual broker symbol inventory
ResearchInstrument <-> BrokerInstrument mapping
current quote freshness
current executable spread / liquidity evidence
contract/tick/volume min/max/step semantics
margin / swap semantics
session / execution / filling modes
M1/tick source reconciliation
MT5-M1 realtime market gateway acceptance
MT5-E1 demo/PAPER order lifecycle
MT5-O1 reconciliation/recovery/safety
separate human-governed live-capital gate
```

A successful Lane A or Lane B run cannot satisfy this list by inheritance.

## 8. Validation substitution matrix

Use this matrix when deciding whether a daytime FX run can replace a U.S.-equity active-session run.

| Validation target | FX fixture may substitute? | Reason |
| --- | --- | --- |
| MT5 Python connectivity | yes | transport invariant |
| broker-clock normalization | yes, as engineering smoke | clock plumbing invariant; U.S. evidence still binds its own report identity |
| tick timestamp parsing | yes | transport/schema plumbing |
| positive current bid/ask | yes, engineering only | does not prove U.S. feed semantics |
| reconnect/error handling | yes | transport invariant |
| U.S. candidate visibility | no | symbol/operator-specific |
| 15-minute delayed-reference admission | no | feed-regime-specific |
| U.S. session/open-close behavior | no | exchange/calendar-specific |
| stock trade/Last tick semantics | no | asset/feed-specific |
| U.S. spread Gate | no | feed/symbol-specific |
| MT5-D0 U.S. reconciliation | no | accepted U.S. universe identity required |
| US-D3 certification | no | U.S. evidence denominator excludes FX fixture |
| stock/CFD margin/fill/order semantics | no | broker-instrument-specific |
| PAPER/live admission | no | target broker/server/account must be bound |

## 9. Current authority boundary

Always read `docs/status.toml` for current stage authority. This guide does not maintain a second stage value.

The permanent invariant is:

```text
FX fixture evidence
    != delayed U.S. simulation evidence
    != future target-broker current/execution evidence
```

This separation allows daytime MT5 feature development without waiting for the U.S. cash session, while preventing a convenient FX pass from becoming a false proof of U.S. equity, CFD, reconciliation, PAPER or live behavior.

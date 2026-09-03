# Realtime development and active-session validation workflow

This guide defines how FinAgent should use scarce live-market windows efficiently while preserving the project's evidence boundaries. It is an operator/development workflow; `docs/status.toml` remains the only current-stage authority and `docs/development/current-plan.md` remains the stage-order/Exit-Gate authority.

The core rule is:

```text
use live market windows only for evidence that cannot be reproduced offline
capture immutable evidence once
replay / validate / certify from captured artifacts outside the live window
```

FinAgent does **not** require every development step to wait for a realtime U.S. market-data interface. Some stage exits do require bounded real-session evidence, but most implementation, replay, identity validation, certification and research work does not.

## 1. Four dependency classes

Classify every realtime-related task before running it.

```text
D0 — offline / deterministic
     no broker or realtime interface required

D1 — connected engineering
     MT5 connection required, but U.S. active-session data is not required
     Lane A FX may substitute only for asset/feed-invariant transport checks

D2 — U.S. active-session evidence capture
     real U.S. source behavior is part of the evidence identity
     Lane A FX may not substitute

D3 — broker mutation / execution acceptance
     demo/PAPER or live target-broker interaction is required
     replay can prepare the code but cannot satisfy final broker authority
```

A development task should move to the lowest dependency class that can prove the behavior under test. Do not spend a U.S. active-session window on work that can be completed in D0 or D1.

## 2. Current simulation US-D3 dependency boundary

The simulation path uses three already-separated MT5 evidence lanes:

```text
Lane A — EURUSD / GBPUSD / USDJPY
         continuous/near-continuous engineering fixture

Lane B — MetaQuotes-Demo U.S. equities
         approximately 15-minute delayed simulation/reference feed

Lane C — future target-broker U.S. equity/CFD feed
         separately admitted current/PAPER/live authority
```

For the simulation-limited US-D3 path, the scarce active-session dependency is narrower than the whole certification workflow.

| Work item | Dependency class | Must U.S. market be actively updating? | FX may substitute? | Can continue from captured artifacts? |
| --- | --- | --- | --- | --- |
| unit/type/static/CI work | D0 | no | n/a | yes |
| policy/content-ID validation | D0 | no | n/a | yes |
| replay/state-machine tests | D0 | no | n/a | yes |
| MT5 initialize/reconnect/server/clock/timestamp plumbing | D1 | no | yes, Lane A only | yes for diagnostics |
| Market Watch preparation for governed U.S. symbols | D1/manual | no active tick required | no | n/a |
| raw US-I0 quote-probe v2 provenance | D2 | **yes** | **no** | the resulting raw report is reusable |
| delayed-reference assessment from the raw report | D0 after capture | no | no | **yes** |
| fresh MT5 inventory + S2 finalization | D1 immediately after D2 | no current-tick proof, but same server/Market Watch state and fresh inventory are required | no | partially; inventory freshness remains bounded |
| U.S.-specific MT5-D0 minute reconciliation | D1 | **no active session required**; it reads bound historical M1 ranges from MT5 | no | yes once S2 identity exists |
| S3 simulation US-D3 certification | D0 | no | no | **yes** |
| independent S3 review | D0 | no | no | **yes** |
| US-B0 / US-A0 / US-R1 historical research | D0 after accepted US-D3 | no | n/a | yes |

Therefore the current project does **not** strictly depend on a continuously available realtime U.S. interface for normal development. However, the US-D3 stage exit remains blocked until the required Lane B active-session evidence is captured and accepted. The two statements are both true:

```text
code/development progress     != strictly realtime-dependent
US-D3 authority progression   == requires bounded real U.S. session evidence
```

## 3. What must be done before the U.S. session

Complete as much as possible before the live window.

### 3.1 Repository and deterministic gates

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent

git pull --ff-only
python scripts\check_docs.py
pytest -q tests\test_us_i0_delayed_reference.py `
          tests\test_us_i0_simulation_universe.py `
          tests\test_us_d3_simulation_admission.py
```

Run additional focused tests for any code changed since the previous accepted evidence. Do not discover basic import/type/test failures after the exchange opens.

### 3.2 Freeze/verify policies before observing the new result

Freeze the canonical simulation policies before the new active-session result is inspected:

```powershell
python scripts\freeze_us_i0_simulation_quote_policy.py `
  --output reports\us_instruments\us_i0_simulation_quote_policy.json

python scripts\freeze_us_i0_simulation_universe_policy.py `
  --output reports\us_instruments\us_i0_simulation_universe_policy.json
```

Do not change quote-age, delayed-anchor, universe-size, 50-bps diagnostic-spread or seed-retention thresholds after observing a weak result merely to obtain acceptance.

### 3.3 Run Lane A engineering preflight

Use FX to prove that the MT5 plumbing is healthy before consuming the U.S. window:

```powershell
python scripts\smoke_mt5_simulation_all_day_preflight.py `
  --symbols EURUSD GBPUSD USDJPY `
  --expected-package-version 5.0.6147 `
  --output reports\mt5\mt5_simulation_all_day_preflight.json
```

Optionally preserve explicit feed-regime fingerprints:

```powershell
python scripts\probe_mt5_feed_regime.py `
  --feed-lane fx_continuous_engineering_fixture `
  --symbol EURUSD `
  --symbol GBPUSD `
  --symbol USDJPY `
  --expected-package-version 5.0.6147 `
  --output reports\mt5\mt5_feed_regime_fx.json
```

If Lane A fails, fix transport/terminal/clock problems before attempting Lane B. A Lane A pass still has no U.S. universe, MT5-D0 or US-D3 authority.

### 3.4 Prepare Market Watch manually

Before the active-session probe:

- expose the intended 40 U.S. candidate symbols manually in MT5 Market Watch;
- verify the four required seeds AMD, INTC, MSFT and NVDA are visible;
- do not add `symbol_select()` to the governed US-I0 code path;
- keep the exact candidate-selection artifact that the raw quote probe will consume.

This preparation is an operator boundary and should not consume the active-session evidence window.

## 4. Active-session capture window

The MetaQuotes-Demo U.S. simulation source has been observed at approximately 900 seconds behind retrieval time. The delayed-reference policy validates against:

```text
validation_anchor = retrieved_at_utc - expected_source_delay
```

Therefore, immediately at the XNYS regular-session open, the delayed anchor can still point into pre-open time. For a roughly 900-second delayed source, begin the governed regular-session capture only after the delayed anchor itself has entered the XNYS regular session. Operationally this is approximately:

```text
XNYS regular open + expected source delay + small observation buffer
```

Use the accepted XNYS calendar rather than hard-coding a local wall-clock time; DST, holidays and half-days remain calendar concerns.

### 4.1 Capture raw v2 provenance

Run the raw current/live quote probe against the exact candidate artifact:

```powershell
python scripts\probe_us_i0_candidate_quotes.py `
  --candidate-report reports\us_instruments\us_i0_universe_candidates.json `
  --mt5-p0-probe reports\mt5\mt5_p0_capability_probe.json `
  --expected-package-version 5.0.6147 `
  --clock-output reports\mt5\mt5_broker_clock_evidence.json `
  --output reports\us_instruments\us_i0_candidate_quotes.json
```

The raw v2 report may correctly mark approximately 15-minute U.S. quotes as `stale_quote` under current/live semantics. Preserve the raw report unchanged. Do **not** widen the current/live freshness Gate.

This raw report is the principal irreplaceable D2 capture for the current simulation admission path.

### 4.2 Derive delayed-reference evidence immediately

The delayed assessment itself is deterministic once the raw report exists:

```powershell
python scripts\assess_us_i0_delayed_reference_quotes.py `
  --quote-probe reports\us_instruments\us_i0_candidate_quotes.json `
  --policy reports\us_instruments\us_i0_simulation_quote_policy.json `
  --output reports\us_instruments\us_i0_delayed_reference_quotes_<new-raw-report-id>.json
```

Acceptance target:

```text
valid delayed references >= 20
AMD retained
INTC retained
MSFT retained
NVDA retained
```

If the delayed assessment still has fewer than 20 valid names because the upstream source did not expose enough valid U.S. observations, preserve the failure as evidence. Do not repair the result in place.

### 4.3 Collect fresh inventory and finalize S2

Collect a fresh read-only inventory promptly after the accepted delayed-reference report:

```powershell
python scripts\probe_mt5_readonly.py `
  --expected-package-version 5.0.6147 `
  --output reports\mt5\mt5_us_i0_simulation_inventory.json
```

Then finalize S2:

```powershell
python scripts\finalize_us_i0_simulation_engineering_universe.py `
  --candidate-report reports\us_instruments\us_i0_universe_candidates.json `
  --quote-probe reports\us_instruments\us_i0_candidate_quotes.json `
  --delayed-reference-report reports\us_instruments\us_i0_delayed_reference_quotes_<new-raw-report-id>.json `
  --simulation-universe-policy reports\us_instruments\us_i0_simulation_universe_policy.json `
  --mt5-inventory-probe reports\mt5\mt5_us_i0_simulation_inventory.json `
  --attest-selected-exact-matches `
  --output reports\us_instruments\us_i0_simulation_engineering_universe.json
```

Frozen S2 acceptance shape:

```text
minimum valid names              = 20
target selected names            = 25
maximum selected names           = 30
maximum delayed diagnostic spread = 50 bps
all four seeds retained          = true
```

The S2 inventory is freshness-bounded, so do not deliberately postpone this step after a successful D2 capture.

## 5. What can move out of the live window

Once a valid S2 universe has been captured, the remainder of the simulation US-D3 path should normally be moved out of the active-session window.

### 5.1 U.S.-specific MT5-D0 reconciliation

The current reconciliation command compares the certified research source against MT5 historical M1 bars for a bound historical window. It requires the accepted U.S. S2 mappings and the correct MT5 server, but not currently progressing U.S. ticks.

```powershell
python scripts\reconcile_us_minute_mt5.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --calendar reports\us_calendar\xnys_1992_2026.json `
  --engineering-universe reports\us_instruments\us_i0_simulation_engineering_universe.json `
  --mt5-p0-probe reports\mt5\mt5_p0_capability_probe.json `
  --expected-package-version 5.0.6147 `
  --reference-symbol-count 4 `
  --minimum-overlap-ratio 0.80 `
  --maximum-abs-offset-minutes 360 `
  --output reports\mt5\mt5_d0_simulation_reference_reconciliation.json
```

Lane A FX symbols may not satisfy this reconciliation. The important optimization is different: the command can be run after the scarce active-session quote capture instead of competing with it.

### 5.2 Freeze and run S3 certification

```powershell
python scripts\freeze_us_d3_simulation_certification_policy.py `
  --output reports\us_d3\us_d3_simulation_certification_policy.json

python scripts\certify_us_d3_simulation_research.py `
  --source-certification <accepted-US-S0-certification.json> `
  --d1-smoke <accepted-US-D1-smoke.json> `
  --d2-smoke <accepted-US-D2-smoke.json> `
  --simulation-engineering-universe reports\us_instruments\us_i0_simulation_engineering_universe.json `
  --reconciliation reports\mt5\mt5_d0_simulation_reference_reconciliation.json `
  --policy reports\us_d3\us_d3_simulation_certification_policy.json `
  --output reports\us_d3\us_d3_simulation_research_certification.json
```

Certification is deterministic over already captured artifacts and should not consume a market window.

### 5.3 Independent review

```powershell
python scripts\review_us_d3_simulation_certification.py `
  --source-certification <accepted-US-S0-certification.json> `
  --d1-smoke <accepted-US-D1-smoke.json> `
  --d2-smoke <accepted-US-D2-smoke.json> `
  --simulation-engineering-universe reports\us_instruments\us_i0_simulation_engineering_universe.json `
  --reconciliation reports\mt5\mt5_d0_simulation_reference_reconciliation.json `
  --policy reports\us_d3\us_d3_simulation_certification_policy.json `
  --certification reports\us_d3\us_d3_simulation_research_certification.json `
  --reviewer-id <reviewer> `
  --decision ACCEPT `
  --notes "simulation-limited US-D3 evidence reviewed" `
  --output reports\us_d3\us_d3_simulation_research_review.json
```

A review may preserve or downgrade a machine outcome; it may never upgrade a machine failure.

## 6. Evidence-reuse and invalidation rules

The purpose of capture/replay is to avoid rerunning live collection unnecessarily, not to keep stale evidence after authoritative code changes.

After a D2 capture, classify every subsequent change:

| Change | Reuse raw active-session artifact? | Required action |
| --- | --- | --- |
| documentation only | yes | rerun docs checks only |
| presentation/diagnostic formatting that does not alter authoritative content IDs | normally yes | focused regression |
| replay wrapper/orchestrator that only verifies existing identities | yes if exact inputs remain unchanged | rerun deterministic downstream validation |
| delayed-reference policy/computation change | raw provenance may remain reusable, but delayed assessment and all descendants are invalidated | refreeze policy and rebuild descendants |
| candidate set / Market Watch governed set change | no for the new candidate identity | new D2 capture required |
| raw quote sampling/timestamp/clock normalization semantics change | no | new D2 capture required |
| S2 finalization policy/computation change | raw/delayed artifacts may remain inputs only if identities still satisfy the new frozen policy; previous S2 is invalid | rebuild S2 and descendants |
| broker server/account/feed lane change | no authority inheritance | new admission chain |

When in doubt, fail closed and rerun the smallest upstream evidence whose semantics actually changed.

## 7. Later realtime stages: what really requires a live interface

The roadmap intentionally delays real broker dependency.

| Stage | Final acceptance depends on realtime/broker interface? | Preferred development method before final acceptance |
| --- | --- | --- |
| US-B0 deterministic baselines | no | historical certified data |
| US-A0 Agent incremental-value experiment | no | historical certified data |
| US-R1 robust Alpha Gate | no | historical certified data |
| US-X0/X1 historical execution/economic gate | no | deterministic historical execution |
| RT-R0 realtime event contracts | **no** | typed synthetic events and property/regression tests |
| RT-R1 ReplayGateway | **no** | replay fixtures: stale, duplicate, out-of-order, disconnect, reject, partial-fill, cancel/expire, restart |
| RT-R2 projection/state store | **no** | deterministic event replay and restart reconstruction |
| MT5-M1 read-only market gateway | **yes for final gateway/source acceptance** | build normalization/ports against replay and Lane A first; validate U.S. current feed only when available |
| MT5-E1 demo/PAPER execution | **yes for final execution acceptance** | develop command/event lifecycle with ReplayGateway first, then bind demo broker |
| MT5-O1 reconciliation/recovery/safety | **yes for final broker-state acceptance** | deterministic restart/reconciliation fixtures first, then demo/PAPER evidence |
| RT-R3 Live Workbench | replay is sufficient for most UI development; final accepted live view depends on accepted M1/E1/O1 projections | browser consumes canonical projections only |
| MT5-L0 live-capital gate | **yes, separately and explicitly** | no simulation/replay/PAPER artifact auto-promotes |

The intended architecture is therefore **replay-first, broker-last**. Realtime API availability is a final acceptance dependency for broker-facing stages, not a reason to block provider-neutral development.

## 8. Recommended U.S.-session operator schedule

Use one active-session attempt as an evidence-capture operation, not an open-ended debugging session.

```text
T-60m or earlier
  pull/freeze/test
  run focused regressions
  run Lane A FX preflight
  manually prepare 40 U.S. Market Watch symbols

before XNYS open
  verify candidate artifact / policy IDs / output paths
  verify four seeds visible
  stop changing authoritative policies

XNYS open + expected delayed-source interval + buffer
  run raw v2 U.S. quote probe
  preserve raw report and broker-clock evidence

immediately after raw capture
  run delayed-reference assessment
  require >=20 valid + four seeds
  collect fresh read-only inventory
  finalize S2 while inventory is within its freshness bound

after S2 is secured
  leave the scarce current-tick window
  run MT5-D0 historical M1 reconciliation
  run deterministic S3 certification
  run independent review
  run CI/docs/governance checks
```

If a failure is clearly D0/D1 engineering, fix it outside the next active window. If a failure is genuinely D2 feed/session evidence, preserve it and schedule only the smallest necessary recapture.

## 9. Session-window success criteria

A high-efficiency active-session run is successful when it leaves behind immutable artifacts sufficient to continue offline. For the current simulation path, the target capture set is:

```text
raw v2 U.S. quote-probe report
broker-clock evidence bound to that raw report
immutable delayed-reference report with >=20 valid names
fresh MT5 inventory
accepted S2 simulation EngineeringUniverse with target 25 / min 20 / max 30
four required seeds retained
```

MT5-D0, S3 certification and independent review are important US-D3 evidence, but they should not be treated as reasons to keep the active quote window occupied.

## 10. Permanent authority rules

```text
FX fixture evidence
    != U.S. delayed-reference evidence
    != target-broker current evidence
    != demo/PAPER execution evidence
    != live-capital authority
```

```text
replay acceptance
    proves deterministic contract/state behavior
    does not prove broker readiness
```

```text
one successful U.S. active-session capture
    can feed many deterministic downstream validations
    only while its exact policy/input identities remain valid
```

Related guides:

- `docs/guides/mt5-continuous-smoke-and-deferred-us-i0.md`
- `docs/guides/us-i0-simulation-universe.md`
- `docs/guides/us-d3-simulation-admission.md`

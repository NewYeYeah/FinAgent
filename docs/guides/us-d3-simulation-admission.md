# US-D3 simulation-limited admission

This guide closes the no-paid-data / no-target-broker-account simulation path without promoting delayed MetaQuotes-Demo U.S. quotes to live broker authority.

## 1. Evidence regimes remain separate

FinAgent currently uses three MT5 evidence regimes:

```text
EURUSD / GBPUSD / USDJPY
    -> continuous/near-continuous engineering preflight only

MetaQuotes-Demo U.S. equities
    -> approximately 15-minute delayed simulation/reference evidence

future target broker account
    -> separate live-current / execution re-admission
```

The first regime exists so transport, broker-clock and quote-health tests can run during Asian daytime. It never enters the U.S. research-universe or US-D3 certification denominator.

The second regime supports the no-account simulation program. It remains explicitly non-live.

The third regime is deferred until a real target broker is selected and must repeat broker-specific admission rather than inherit simulation authority.

## 2. S2 status

S1 delayed-reference timing and S2 simulation EngineeringUniverse implementations are already complete.

Canonical identities:

```text
S1 timing policy
  us-simulation-quote-timing-policy-e88e0297965f263baa182ad5

S2 universe policy
  us-simulation-universe-final-policy-b75fd9c0bca9285e28d2ad9d
```

The current real S1 operator evidence still contains only four visible U.S. seed references. A real S2 universe therefore still requires manual Market Watch exposure and a new U.S. quote-probe/delayed-reference run with at least 20 valid delayed references and all four seeds retained.

## 3. All-day engineering preflight

Use the already proven continuous/near-continuous MetaQuotes-Demo fixture:

```text
EURUSD
GBPUSD
USDJPY
```

Run:

```powershell
python scripts\smoke_mt5_simulation_all_day_preflight.py `
  --symbols EURUSD GBPUSD USDJPY `
  --expected-package-version 5.0.6147 `
  --output reports\mt5\mt5_simulation_all_day_preflight.json
```

A pass means only:

```text
MT5 read-only transport is healthy
broker clock is measurable
all three fixture quotes are current under the continuous-market policy
```

It explicitly does not mean:

```text
U.S. research universe accepted
U.S. delayed-reference coverage >= 20
US-D3 certified
live market data accepted
broker account accepted
execution or order authority
```

The preflight report therefore carries:

```text
engineering_fixture_authority = true      # only when passed
us_research_universe_authority = false
us_d3_certification_authority = false
live_market_data_authority = false
execution_authority = false
stage_exit_authority = false
```

This report is deliberately absent from the simulation US-D3 certification hash denominator.

## 4. Real S2 evidence sequence

When the U.S. delayed source is available and the intended symbols are manually visible in Market Watch:

```powershell
python scripts\probe_us_i0_candidate_quotes.py `
  --candidate-report reports\us_instruments\us_i0_universe_candidates.json `
  --mt5-p0-probe reports\mt5\mt5_p0_capability_probe.json `
  --expected-package-version 5.0.6147 `
  --clock-output reports\mt5\mt5_broker_clock_evidence.json `
  --output reports\us_instruments\us_i0_candidate_quotes.json
```

The raw v2 report is expected to continue classifying approximately fifteen-minute U.S. quotes as stale under live/current semantics. Preserve the raw report.

Then derive delayed-reference evidence with the frozen S1 policy and collect a fresh read-only inventory. Finally run the S2 finalizer from `docs/guides/us-i0-simulation-universe.md`.

Required S2 result:

```text
accepted_for_simulation_engineering = true
simulation accepted mapping count   = 25 target, >=20 hard minimum
all four seeds retained             = true
live executable spread authority    = false
stage exit authority                = false
```

## 5. MT5-D0 remains U.S.-specific

After a real S2 universe passes, run the existing U.S. minute reconciliation against that S2 report:

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

The bridge verifies that every reconciled symbol pair belongs to the accepted S2 universe and that the MT5 probe/server identities match. EURUSD/GBPUSD/USDJPY cannot satisfy this U.S. reconciliation requirement.

## 6. Freeze the simulation US-D3 policy

```powershell
python scripts\freeze_us_d3_simulation_certification_policy.py `
  --output reports\us_d3\us_d3_simulation_certification_policy.json
```

The policy wraps the existing provider-neutral US-D3 certification policy rather than replacing its source/D1/D2/reconciliation rules.

## 7. Simulation-limited US-D3 certification

After S2 and U.S. MT5-D0 both pass:

```powershell
python scripts\certify_us_d3_simulation_research.py `
  --source-certification <accepted-US-S0-certification.json> `
  --d1-smoke <accepted-US-D1-smoke.json> `
  --d2-smoke <accepted-US-D2-smoke.json> `
  --simulation-engineering-universe reports\us_instruments\us_i0_simulation_engineering_universe.json `
  --reconciliation reports\mt5\mt5_d0_simulation_reference_reconciliation.json `
  --policy reports\us_d3\us_d3_simulation_certification_policy.json `
  --output reports\us_d3\us_d3_simulation_research_certification.json
```

The bridge validates the content-addressed S2 universe/materialization identities, converts only the accepted simulation-universe identity/count into an internal compatibility input for the existing US-D3 core, and permanently adds these limitations:

```text
market_data:metaquotes_demo_delayed_reference_without_broker_account
spread:delayed_reference_diagnostic_only
spread:not_live_executable_spread_authority
broker_account:simulation_without_target_broker_account
live_broker:requires_separate_re_admission
universe:simulation_engineering_integration_only
all_day_products:engineering_preflight_only_not_us_research_evidence
```

A passing certification may recommend B0 progression for the historical research program, but it never creates live-current, broker-account, execution, order or live-capital authority.

## 8. Independent review and stage transition

The machine certification does not update `docs/status.toml`. Independently rebuild and review it:

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

A reviewer can accept a passing machine certification or reject/downgrade it. A rejected machine certification cannot be upgraded.

Even an accepted review has:

```text
status_authority = false
stage_exit_authority = false
```

Only a later governance PR may record the exact certification/review IDs in `docs/status.toml` and advance `US-D3 -> US-B0`.

## 9. Future live re-admission

Nothing in this bridge reduces later live-broker work. Before live/PAPER execution, FinAgent must repeat broker-specific:

```text
MT5-P0 capability admission
broker/server/account identity
ResearchInstrument <-> BrokerInstrument mapping
current quote/executable spread evidence
contract/tick/volume/margin/swap/session/fill semantics
historical CFD friction calibration
MT5-M1 realtime gateway
MT5-E1 PAPER order lifecycle
MT5-O1 reconciliation/recovery/safety
RT-R3 Workbench acceptance
MT5-L0 human-governed live-capital gate
```

B0/A0/R1 and provider-neutral replay/projection layers remain reusable; delayed simulation evidence never auto-promotes to live authority.

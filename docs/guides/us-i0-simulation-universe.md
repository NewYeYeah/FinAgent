# US-I0 no-account simulation EngineeringUniverse

This guide is the S2 continuation of the MetaQuotes-Demo delayed-reference regime. It is intentionally separate from the existing live/current v3 EngineeringUniverse finalizer.

## 1. Accepted S1 operator evidence

The September 2026 no-subscription/no-broker-account run established the following immutable identities:

```text
simulation timing policy
  us-simulation-quote-timing-policy-e88e0297965f263baa182ad5

raw live/current quote provenance
  us-candidate-quote-probe-fbc3da92fc83e7cb86a04c9d

S1 delayed-reference assessment
  us-delayed-reference-quote-report-23beb1b407fa905dc5b0457a
```

The delayed-reference assessment preserved the raw live/current failure while admitting the four visible seed symbols under the separate 15-minute source regime:

```text
valid delayed-reference symbols = AMD, INTC, MSFT, NVDA
valid count                     = 4
required minimum                = 20
blocker                         = simulation_quote_probe:insufficient_valid_quotes:4<20
```

This is the expected S1 result. Clock/timing semantics are no longer the blocker; Market Watch visibility / universe coverage is.

## 2. S2 frozen policy

S2 introduces a separate content-addressed simulation-universe policy:

```text
target_count                         = 25
minimum_count                        = 20
maximum_count                        = 30
maximum_reference_spread_bps         = 50
maximum_inventory_age_seconds        = 900
maximum_inventory_future_skew_seconds = 60
```

The spread threshold is **not** a live executable-spread Gate. It is a delayed-reference engineering diagnostic used only to choose a compact integration universe.

The canonical v1 policy identity is:

```text
us-simulation-universe-final-policy-b75fd9c0bca9285e28d2ad9d
```

Freeze it with:

```powershell
python scripts\freeze_us_i0_simulation_universe_policy.py `
  --output reports\us_instruments\us_i0_simulation_universe_policy.json
```

Do not change the 50 bps threshold or the 25/20/30 counts to force an acceptance. A policy change requires a new code/policy identity.

## 3. S2 identity chain

The finalizer consumes four evidence artifacts:

```text
US-I0 candidate selection
        |
        +--> raw quote-probe v2 provenance
                    |
                    +--> delayed-reference assessment

fresh read-only MT5 inventory --------------------+
                                                   |
                                                   v
                              SimulationEngineeringUniverse
```

The finalizer verifies, fail-closed:

- candidate selection identity;
- candidate MT5-P0 probe identity against the raw quote-probe identity;
- exact candidate/requested-symbol set;
- exact seed set;
- raw quote-policy identity;
- delayed report -> raw report binding;
- delayed report -> broker-clock evidence binding;
- canonical 15-minute simulation quote-policy identity;
- broker-server equality across candidate/raw/delayed/fresh inventory;
- fresh inventory timestamp within the frozen 900-second bound;
- rank-preserving candidate selection;
- explicit operator attestation for exact RESEARCH=BROKER symbol identity;
- all selected broker symbols remain visible/tradable in the fresh inventory.

No artifact is repaired or silently rebound by the finalizer.

## 4. Why the existing v3 finalizer is not reused

`scripts/finalize_us_i0_engineering_universe.py` remains the live/current path. It expects current quote freshness and exposes the existing live/current finalizer identity.

S2 instead uses:

```text
scripts/finalize_us_i0_simulation_engineering_universe.py
```

The simulation report deliberately exposes:

```text
accepted_for_simulation_engineering
simulation_universe_id
simulation_accepted_mapping_count
```

and deliberately does **not** expose the generic live/current fields:

```text
accepted
universe_id
```

This makes the current US-D3 certification loader fail closed if someone accidentally supplies an S2 simulation report as though it were the existing live/current US-I0 finalization artifact. A later explicit simulation-limited US-D3 bridge is required before stage authority can advance.

## 5. Authority boundary

A successful S2 report may assert only:

```text
simulation_engineering_universe_authority = true
engineering_reference_authority           = true
```

It always keeps:

```text
broker_account_authority         = false
live_market_data_authority       = false
live_executable_spread_authority = false
execution_authority              = false
order_authority                  = false
live_capital_authority           = false
alpha_authority                  = false
status_authority                 = false
stage_exit_authority             = false
```

Therefore S2 acceptance does not by itself advance `docs/status.toml`, certify US-D3, start formal B0, authorize PAPER or imply a live broker/account.

## 6. Operator sequence for the next evidence run

First expose the intended 40 candidate U.S. symbols in MT5 Market Watch manually or through the separate add-only, allowlisted `ensure_mt5_market_watch.py` operator utility. The governed US-I0 probe and finalizer must not call `symbol_select()`.

During an active U.S. session rerun the raw quote probe:

```powershell
python scripts\probe_us_i0_candidate_quotes.py `
  --candidate-report reports\us_instruments\us_i0_universe_candidates.json `
  --mt5-p0-probe reports\mt5\mt5_p0_capability_probe.json `
  --expected-package-version 5.0.6147 `
  --clock-output reports\mt5\mt5_broker_clock_evidence.json `
  --output reports\us_instruments\us_i0_candidate_quotes.json
```

The raw v2 report may still correctly classify the approximately 15-minute U.S. quotes as `stale_quote`. Preserve that report unchanged.

Then derive a new immutable delayed-reference report using the already frozen S1 timing policy. Use a new output filename containing the new raw report identity rather than overwriting the prior S1 artifact:

```powershell
python scripts\assess_us_i0_delayed_reference_quotes.py `
  --quote-probe reports\us_instruments\us_i0_candidate_quotes.json `
  --policy reports\us_instruments\us_i0_simulation_quote_policy.json `
  --output reports\us_instruments\us_i0_delayed_reference_quotes_<new-raw-report-id>.json
```

Immediately collect a fresh read-only inventory:

```powershell
python scripts\probe_mt5_readonly.py `
  --expected-package-version 5.0.6147 `
  --output reports\mt5\mt5_us_i0_simulation_inventory.json
```

Finally run the S2 finalizer:

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

Expected successful S2 shape:

```text
accepted_for_simulation_engineering = true
selected symbol count                = 25
simulation accepted mapping count    = 25
all four seed symbols retained       = true
live executable spread authority     = false
stage exit authority                 = false
```

## 7. What follows S2

After real S2 evidence is accepted, the next code/evidence increment is not B0 directly. It is an explicit **simulation-limited US-D3 admission bridge** that must:

1. recognize only the S2 simulation-universe schema/identity;
2. preserve `market_data:delayed_reference` and `live_executable_spread_authority=false` as certification limitations;
3. bind the required MT5-D0/reference reconciliation evidence;
4. produce engineering-research authority only;
5. update `docs/status.toml` only after the exact reviewed identities are recorded.

Only after that reviewed bridge closes US-D3 may the already implemented formal US-B0 materialization run on the certified historical data plane.

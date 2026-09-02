# US-D3 minute-data certification

US-D3 is the deterministic data gate before U.S. factor discovery. It aggregates already-authoritative row-free evidence; it does not recompute or silently repair source statistics.

## Current certification ceiling

With the currently admitted `mito0o852/OHLCV-1m` snapshot, the strongest expected terminal result is:

```text
CERTIFIED_FOR_ENGINEERING_RESEARCH
```

The source publication authority remains `reference_only`, usage rights remain unresolved for redistribution, prices remain raw/split-unadjusted, and no point-in-time security master is available. Therefore this stage does not authorize survivorship-unbiased market-wide Alpha claims.

## Evidence chain

```text
US-S0 local admission
  + US-D1 bounded/replay smoke
  + US-D2 real transform smoke
  + final US-I0 20-30 EngineeringUniverse
      ├─ deterministic 40-name candidate set
      ├─ read-only MT5 broker-clock evidence
      ├─ clock-normalized current quote evidence
      └─ fresh read-only MT5 inventory
  + MT5-D0 row-free reference reconciliation
        ↓
US-D3 certification report
```

Broker-clock normalization is evidence-bound. FinAgent does not assume that a raw MT5 `time`/`time_msc` value is UTC merely because it is represented as an epoch. The observed broker clock is measured from multiple active reference ticks and preserved as separate evidence before current-quote freshness is assessed.

The broker-clock evidence is **not** an authority to rewrite historical research or MT5-D0 timestamps. MT5-D0 keeps its independent bounded clock-offset reconciliation.

## 1. Synchronize `main`

Use the existing Windows Conda environment:

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent

git fetch origin --prune
git checkout main
git merge --ff-only origin/main
```

## 2. Materialize the deterministic 40-name candidate set

```powershell
python scripts\select_us_i0_universe_candidates.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --calendar reports\us_calendar\xnys_1992_2026.json `
  --mt5-probe reports\mt5\mt5_p0_capability_probe.json `
  --start 2026-01-01T00:00:00+00:00 `
  --end 2026-04-01T00:00:00+00:00 `
  --top-n 40 `
  --minimum-selected 20 `
  --memory-limit 512MB `
  --threads 2 `
  --max-temp-directory-size 4GB `
  --temp-directory data\duckdb_temp\us_i0_candidates `
  --output reports\us_instruments\us_i0_universe_candidates.json
```

Required output:

```text
ready_for_spread_probe = true
blockers = []
selected_candidate_count >= 20
```

This is only a candidate set. Exact ticker equality is not a security-identity attestation.

## 3. Make candidate symbols visible manually

The accepted MT5-P0 inventory may contain only a small visible Market Watch subset. Candidate discovery intentionally does not call `symbol_select`, so inspect `spread_probe_symbols` and `manual_visibility_required_symbols` and add the intended candidate symbols to MetaTrader 5 Market Watch manually.

For the default 25-name final target, making all 40 candidates visible is preferred. It leaves room for stale, invalid or wider-than-50-bps quotes to be rejected without forcing a policy change.

Do not add a programmatic `symbol_select` path to FinAgent. Visibility is broker-terminal state and remains outside the read-only P0/US-I0 code surface.

## 4. Collect broker-clock evidence and current quote evidence

Run the quote probe while the broker is actively publishing the intended U.S. symbols, preferably during the U.S. regular session. The v2 probe performs two read-only measurements in one connected MT5 session:

1. infer the observed broker-clock offset from at least three active reference ticks;
2. collect candidate ticks and normalize their raw broker timestamps to UTC using that content-addressed clock evidence.

The default clock references are:

```text
EURUSD
GBPUSD
USDJPY
```

They are measurement references only; they are not added to the U.S. EngineeringUniverse.

```powershell
python scripts\probe_us_i0_candidate_quotes.py `
  --candidate-report reports\us_instruments\us_i0_universe_candidates.json `
  --mt5-p0-probe reports\mt5\mt5_p0_capability_probe.json `
  --expected-package-version 5.0.6147 `
  --clock-output reports\mt5\mt5_broker_clock_evidence.json `
  --output reports\us_instruments\us_i0_candidate_quotes.json
```

If one of the default references is unavailable at the connected broker, override the set with at least three active symbols:

```powershell
python scripts\probe_us_i0_candidate_quotes.py `
  --candidate-report reports\us_instruments\us_i0_universe_candidates.json `
  --mt5-p0-probe reports\mt5\mt5_p0_capability_probe.json `
  --clock-reference-symbol EURUSD `
  --clock-reference-symbol GBPUSD `
  --clock-reference-symbol USDJPY `
  --output reports\us_instruments\us_i0_candidate_quotes.json
```

There is no hard-coded `UTC+3` or other broker timezone. The v1 clock policy requires a common observed offset from at least three references, snaps the median offset to a 60-second clock quantum, and rejects references whose residual exceeds 15 seconds. Changing broker/server can therefore produce a different accepted offset without changing code.

Required broker-clock output:

```text
schema_version = finagent.mt5-broker-clock-evidence.v1
passed = true
blockers = []
reference_count >= 3
inferred_offset_seconds = <observed value>
maximum_abs_residual_seconds <= 15
```

The quote-probe v2 stores, per observed candidate:

```text
raw_broker_time_msc
raw_broker_wall_time
broker_clock_offset_seconds
normalized_sampled_at_utc
retrieved_at_utc
quote_age_at_retrieval_seconds
bid / ask / spread_bps
clock_evidence_id
```

It also preserves per-symbol failure reasons such as:

```text
not_visible
not_tradable
tick_unavailable
non_positive_bid
non_positive_ask
ask_below_bid
stale_quote
future_quote
broker_clock_unavailable
```

Required quote output:

```text
schema_version = finagent.us-candidate-quote-probe-report.v2
ready_for_finalization = true
blockers = []
valid_quote_count >= 20
broker_clock_evidence.passed = true
```

The frozen quote freshness thresholds remain:

```text
maximum_quote_age_seconds = 900
maximum_future_quote_skew_seconds = 60
```

Do not widen these thresholds to make a closed-market quote pass. A raw broker timestamp that appears ahead of local UTC is first normalized through broker-clock evidence; after normalization an old quote must be classified as `stale_quote`, not repaired or re-labelled as fresh.

Both clock and quote probes are read-only. FinAgent does not call `symbol_select`, `order_check`, `order_send` or position/account mutation APIs.

## 5. Immediately record fresh MT5 inventory

After the candidate Market Watch state is correct and quote evidence passes, record a fresh inventory back-to-back:

```powershell
python scripts\probe_mt5_readonly.py `
  --expected-package-version 5.0.6147 `
  --output reports\mt5\mt5_us_i0_final_inventory.json
```

The candidate report, quote report, clock evidence and final inventory must all bind the same accepted MT5-P0 identity/broker server where applicable.

## 6. Freeze the final 25-name EngineeringUniverse

After reviewing the selected exact-symbol mappings, explicitly attest them for bounded engineering integration.

Finalization v3 does **not** trust probe-time freshness forever. It reconstructs and verifies the content-addressed quote-probe v2 and embedded clock evidence, then re-assesses each `normalized_sampled_at_utc` against the finalization UTC clock.

```powershell
python scripts\finalize_us_i0_engineering_universe.py `
  --candidate-report reports\us_instruments\us_i0_universe_candidates.json `
  --quote-probe reports\us_instruments\us_i0_candidate_quotes.json `
  --mt5-inventory-probe reports\mt5\mt5_us_i0_final_inventory.json `
  --target-count 25 `
  --minimum-count 20 `
  --maximum-count 30 `
  --maximum-current-spread-bps 50 `
  --maximum-quote-age-seconds 900 `
  --maximum-future-quote-skew-seconds 60 `
  --attest-selected-exact-matches `
  --output reports\us_instruments\us_i0_final_engineering_universe.json
```

The v3 finalizer fails closed when:

- quote-probe v2 was not ready;
- broker-clock evidence did not pass;
- quote probe and finalizer freshness policies drift;
- candidate and quote evidence bind different accepted MT5-P0 probes;
- candidate/quote/clock/fresh-inventory broker servers disagree;
- fewer than 20 normalized quotes remain fresh at finalization time;
- any required seed is not fresh;
- the spread filter removes a required seed;
- the final exact-symbol mapping attestation is absent.

The 50-bps spread threshold remains unchanged. If a required seed has a wider current spread, re-measure in an appropriate liquid session; do not widen the gate merely to force acceptance.

Required output:

```text
schema_version = finagent.us-engineering-universe-finalization-report.v3
quote_evidence_passed = true
accepted = true
blockers = []
accepted_mapping_count = 25
clock_evidence_id = mt5-broker-clock-evidence-...
universe_id = engineering-universe-...
```

The attestation means only that each exact research/broker symbol pair may be used in this engineering universe. It does not prove listed venue, PIT lifecycle, corporate-action completeness or live-trading suitability.

## 7. Run MT5-D0 minute reconciliation

The reference report does not require CFD and source OHLCV prices to be identical. It measures overlap, searches a bounded integer-minute broker-to-research clock offset, and reports aligned close differences and volume semantics. No discovered offset rewrites either source clock.

The broker-clock evidence used for current quote freshness does not replace this reconciliation. Historical M1 availability and clock alignment remain independent MT5-D0 evidence.

```powershell
python scripts\reconcile_us_minute_mt5.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --calendar reports\us_calendar\xnys_1992_2026.json `
  --engineering-universe reports\us_instruments\us_i0_final_engineering_universe.json `
  --mt5-p0-probe reports\mt5\mt5_p0_capability_probe.json `
  --start 2026-03-09T13:30:00+00:00 `
  --end 2026-03-09T20:00:00+00:00 `
  --reference-symbol-count 4 `
  --minimum-overlap-ratio 0.80 `
  --maximum-abs-offset-minutes 360 `
  --memory-limit 512MB `
  --threads 2 `
  --max-temp-directory-size 4GB `
  --temp-directory data\duckdb_temp\mt5_d0 `
  --output reports\mt5\mt5_d0_minute_reconciliation.json
```

Required output:

```text
passed = true
blockers = []
```

If the connected MetaQuotes-Demo terminal does not retain the requested historical M1 bars, keep the failed row-free report. Do not weaken the overlap gate merely to force a pass; the reference window/policy must be reviewed explicitly.

## 8. Aggregate the final US-D3 certification

```powershell
python scripts\certify_us_minute_research.py `
  --source-certification reports\us_minute_local_certification.json `
  --d1-smoke reports\us_d1\us_d1_smoke_report.json `
  --d2-smoke reports\us_d2\us_d2_transform_smoke_report.json `
  --engineering-universe reports\us_instruments\us_i0_final_engineering_universe.json `
  --reconciliation reports\mt5\mt5_d0_minute_reconciliation.json `
  --output reports\us_d3\us_minute_research_certification.json
```

Do not pass `--point-in-time-security-master-available` unless independently certified PIT security-master evidence actually exists.

Expected result under the current source authority:

```text
outcome = CERTIFIED_FOR_ENGINEERING_RESEARCH
certified = true
blockers = []
```

Only after this report is reviewed and the real local report identities are recorded in `docs/status.toml` does the project advance to US-B0 deterministic baselines.

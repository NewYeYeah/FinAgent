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
  + MT5-D0 row-free reference reconciliation
        ↓
US-D3 certification report
```

The accepted US-D2 operator evidence is:

```text
report_id = us-d2-transform-smoke-4b47e2fe2525d7f599d6579f
policy_id = us-d2-transform-smoke-policy-1c20c683e20eb0b1a910c9bf
passed = true
blockers = []
```

It covers the frozen half-day, pre-DST and post-DST scenarios with the accepted XNYS calendar.

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

The accepted MT5-P0 inventory originally contains only a small visible Market Watch subset. Candidate discovery intentionally does not call `symbol_select`, so inspect `spread_probe_symbols` and `manual_visibility_required_symbols` in the candidate report and add the intended candidate symbols to MetaTrader 5 Market Watch manually.

Do not add a programmatic `symbol_select` path to FinAgent. Visibility is broker-terminal state and remains outside the read-only P0/US-I0 code surface.

## 4. Collect fresh quote evidence and immediately record fresh inventory

Run these commands back-to-back while the broker is publishing fresh stock quotes. The finalization Gate rejects stale quote timestamps, excessive future clock skew, a quote report bound to a different accepted P0 probe, or a broker-server mismatch between candidate/quote/fresh-inventory evidence.

```powershell
python scripts\probe_us_i0_candidate_quotes.py `
  --candidate-report reports\us_instruments\us_i0_universe_candidates.json `
  --mt5-p0-probe reports\mt5\mt5_p0_capability_probe.json `
  --expected-package-version 5.0.6147 `
  --output reports\us_instruments\us_i0_candidate_quotes.json

python scripts\probe_mt5_readonly.py `
  --expected-package-version 5.0.6147 `
  --output reports\mt5\mt5_us_i0_final_inventory.json
```

Both probes are read-only. FinAgent does not call `symbol_select`, `order_check`, `order_send` or position/account mutation APIs.

Required quote output:

```text
ready_for_finalization = true
blockers = []
valid_quote_count >= 20
```

The current quote/spread snapshot is an engineering filter only. It is not historical transaction-cost authority.

## 5. Freeze the final 25-name EngineeringUniverse

After reviewing the selected exact-symbol mappings, explicitly attest them for bounded engineering integration. The v2 finalization policy requires quote age <= 900 seconds by default and tolerates at most 60 seconds of future quote clock skew.

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

The attestation means only that each exact research/broker symbol pair may be used in this engineering universe. It does not prove listed venue, PIT lifecycle, corporate-action completeness or live-trading suitability. The accepted four-name seed set must remain in the final universe; if a seed is dropped by the quote/spread filter, finalization fails closed for review rather than silently changing the integration denominator.

Required output:

```text
quote_evidence_passed = true
accepted = true
blockers = []
accepted_mapping_count = 25
universe_id = engineering-universe-...
```

## 6. Run MT5-D0 minute reconciliation

The reference report does not require CFD and source OHLCV prices to be identical. It measures exact UTC overlap, searches a bounded integer-minute broker-to-research clock offset, and reports aligned close differences and volume semantics. No discovered offset rewrites either source clock.

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

If MetaQuotes-Demo does not retain March 2026 M1 bars, keep the failed row-free report. Do not weaken the overlap gate merely to force a pass; the reference window/policy must be reviewed explicitly.

## 7. Aggregate the final US-D3 certification

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

Only after this report is reviewed and recorded in `docs/status.toml` does the project advance to US-B0 deterministic baselines.

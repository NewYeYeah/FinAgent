# Testing and System Acceptance

This is the canonical test guide. Tests verify implementation and research invariants; they do not prove alpha persistence.

## 1. Release gate

Every merge must keep the following green:

```text
Ubuntu Python 3.11 / 3.12 / 3.13 pytest
Windows Python 3.11 pytest
critical Ruff checks
targeted mypy
coverage floor
package build
pip dependency consistency
```

## 2. Full regression

### Ubuntu

```bash
./scripts/finagent.sh python -m pytest -q
```

On a clean shell without ROS contamination:

```bash
python -m pytest -q
```

### Windows PowerShell

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONNOUSERSITE = "1"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q
```

## 3. Static and packaging checks

```bash
ruff check src tests scripts --select E9,F63,F7,F82
mypy src/finagent/data src/finagent/research
python -m pytest --cov=finagent --cov-report=term --cov-fail-under=50
python -m build
python -m pip check
```

## 4. Provider smoke tests

LLM connectivity:

```bash
python scripts/smoke_llm_provider.py configs/llm.toml --profile deepseek_official_v4_pro
```

US reference market data:

```bash
python scripts/pull_market_data.py configs/markets/us_etf_agent_data_alpaca.toml --show-capabilities
python scripts/validate_market_data.py data/market/us_etf_alpaca
```

For US historical research use Alpaca SIP. IEX is a smoke feed and may show single-exchange gaps.

## 5. Local A-share test sequence

The local A-share path has three different tests. Run them in order.

### T-A0 — source certification

Install:

```bash
python -m pip install -e ".[local-parquet]"
```

Ubuntu:

```bash
python scripts/certify_local_ashare_data.py \
  configs/local_ashare.example.toml \
  --root /data/A-Share \
  --sample-symbol 000001.SZ \
  --sample-date 2009-01-05
```

Windows:

```powershell
python scripts/certify_local_ashare_data.py `
  configs\local_ashare.example.toml `
  --root D:\Data\A-Share `
  --sample-symbol 000001.SZ `
  --sample-date 2009-01-05
```

Review the report rather than only the exit code. It should explicitly expose:

- basic/daily schema;
- duplicate securities/bars;
- invalid/placeholder listing dates;
- incomplete delisting/list-status coverage;
- non-canonical/legacy vendor codes quarantined from the canonical universe;
- OHLC validity;
- strict no-trade/suspension placeholder rows;
- positive adjustment factors;
- 241-row minute convention;
- daily/minute OHLC reconciliation;
- daily lots/thousand-CNY vs minute shares/CNY reconciliation.

The audited daily no-trade placeholder is narrowly defined as:

```text
open = high = low = 0
close = pre_close > 0
vol = amount = 0
```

Such rows are retained in the immutable vendor source, reported as `LA-DAILY-07` warnings and excluded from `PriceBar` construction. Any other non-positive or OHLC-inconsistent row remains `LA-DAILY-03/04` error and must not be silently repaired.

Warnings about incomplete security-master coverage are expected. Do not modify vendor Parquet to remove those warnings.

### T-A1 — freeze the source used by research

For the current daily research milestone:

```bash
python scripts/freeze_local_ashare_data.py \
  --root /data/A-Share \
  --frequency 1d \
  --output data/manifests/local_ashare_daily.json
```

Windows:

```powershell
python scripts/freeze_local_ashare_data.py `
  --root D:\Data\A-Share `
  --frequency 1d `
  --output data\manifests\local_ashare_daily.json
```

Default behavior computes content SHA-256 for `stock_basic_data.parquet` and `stock_daily.parquet`. Keep the generated manifest with the research run/evidence; the actual vendor data remains outside Git.

Use `--fast` only for diagnostics. A fast manifest is based on file metadata and is weaker than a content-hashed research freeze.

After freezing, this command should fail if a frozen file has been changed:

```powershell
python scripts/run_local_ashare_research_smoke.py `
  configs\research\local_ashare_research_smoke.example.toml `
  --verify-content
```

### T-A2 — supplemental reference data

Tracked templates live in:

```text
reference_data/a_share/
```

Validate them through the normal unit tests:

```bash
python -m pytest -q tests/test_ashare_freeze_supplemental_v127.py
```

Rules for adding a real row:

1. register/identify the source in `sources.toml`;
2. use canonical six-digit `ts_code` plus `.SH/.SZ/.BJ`;
3. record the exact announcement/reference URL;
4. record `observed_at` as timezone-aware ISO-8601;
5. never imply complete coverage when the source file is partial.

The supplemental `data_version` changes when any tracked source/data file changes.

### T-A3 — local A-share system smoke

Copy the example config and adjust paths/universe/windows:

```text
configs/research/local_ashare_research_smoke.example.toml
```

Run:

```bash
python scripts/run_local_ashare_research_smoke.py \
  configs/research/local_ashare_research_smoke.example.toml
```

Windows:

```powershell
python scripts/run_local_ashare_research_smoke.py `
  configs\research\local_ashare_research_smoke.example.toml
```

The test traverses:

```text
frozen Parquet identity
→ supplemental reference store
→ SupplementedAshareSecurityMaster
→ LocalAshareParquetDataAdapter (daily)
→ strict suspension/no-trade filtering
→ DatasetRequest
→ ResearchDataset / ResearchSplit
→ PIT eligibility_mask
→ lagged feature values
→ common-panel-session forward labels
→ deterministic cross-sectional RankIC diagnostic
```

For daily A-share panels, `forward_*_h` is defined on the common panel session clock. If an asset has no tradable bar on the h-th later panel session, its forward label is `NaN`; the label must not jump to the first post-suspension trade and silently lengthen the horizon.

The JSON report records:

- frozen dataset version;
- supplemental-data version and record counts;
- security-master limitations;
- research dataset digest;
- universe/features/labels;
- per-split timestamp count;
- eligible cells;
- primary feature/label coverage;
- RankIC period count and diagnostic mean.

Acceptance conditions:

- script exits 0;
- no `+/-inf` appears in features or labels;
- both splits satisfy configured minimum RankIC period count;
- development/validation windows do not overlap;
- `security_master.survivorship_certified == false` unless a future explicit certification mechanism changes that contract;
- adapter `data_version` equals the frozen manifest version;
- forward-label metadata records `common_panel_sessions`;
- no realtime API or execution path is invoked.

RankIC from this script is **not** promotion evidence. It only proves that the real local data adapter can drive a cross-sectional numerical research panel.

## 6. Local A-share CI coverage

CI uses synthetic Parquet data; it does not have access to the user's multi-GB local dataset. The synthetic integration suite checks:

- SSE/SZSE/BSE identity and leading zeros;
- legacy/non-canonical vendor-code quarantine;
- daily unit normalization;
- adjustment-aware returns/labels;
- strict suspension/no-trade placeholder classification;
- common-session forward-label horizons across suspensions;
- 241-row minute semantics;
- supplemental-data parsing/versioning;
- delisting overlay remains candidate-only;
- frozen-manifest mutation detection;
- full `run_local_ashare_research_smoke.py` execution against a temporary Parquet dataset;
- Windows compatibility.

Run focused tests:

```bash
python -m pytest -q \
  tests/test_local_ashare_data_layer_v126.py \
  tests/test_ashare_freeze_supplemental_v127.py \
  tests/test_ashare_legacy_anomaly_v127.py \
  tests/test_ashare_suspension_session_semantics_v127.py
```

Windows:

```powershell
python -m pytest -q `
  tests\test_local_ashare_data_layer_v126.py `
  tests\test_ashare_freeze_supplemental_v127.py `
  tests\test_ashare_legacy_anomaly_v127.py `
  tests\test_ashare_suspension_session_semantics_v127.py
```

## 7. Agent research acceptance

Before a full Agent run:

1. provider connectivity smoke passes;
2. dataset/frozen identity verification passes;
3. deterministic `ResearchDataset` construction passes;
4. generated-feature sandbox tests pass.

A frozen-family replay must be exact and must not call the LLM.

Formal ensemble validation must retain the complete search denominator:

```text
K searched single factors + 1 frozen ensemble
```

and use aligned outer windows for multiplicity/DSR/PBO/Reality Check evidence.

## 8. Current A-share boundary

The current acceptance explicitly does **not** require:

- realtime A-share feeds;
- external A-share broker;
- complete paid historical delisting/status products;
- 1-minute execution backtesting.

Those remain deferred. Daily historical research reproducibility and data identity are the current gate.

## 9. Failure severity

P0 — block the next research milestone:

- PIT/look-ahead violation;
- split leakage;
- frozen dataset identity mismatch;
- wrong price/volume/amount unit;
- wrong timezone/bar timestamp semantics;
- suspension placeholders treated as tradable price bars;
- forward label horizon stretching across a suspension;
- denominator mutation;
- replay failure;
- invalid finite-value handling.

P1 — record and continue when bounded:

- incomplete supplemental status coverage;
- provider/network instability on a secondary source;
- large-panel memory/performance limits;
- low-probability crash recovery windows.

P2 — deployment hardening:

- cryptographic/HSM-backed evidence sealing;
- physical data isolation;
- production external broker connectivity;
- high-availability realtime feed/reconciliation infrastructure.

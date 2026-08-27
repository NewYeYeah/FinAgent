# Testing and System Acceptance

This is the canonical test guide. Tests verify implementation, data contracts and research invariants; they do not prove that an alpha will persist.

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

Ubuntu:

```bash
./scripts/finagent.sh python -m pytest -q
```

Windows PowerShell:

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONNOUSERSITE = "1"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q
```

Static/package checks:

```bash
ruff check src tests scripts --select E9,F63,F7,F82
mypy src/finagent/data src/finagent/research
python -m pytest --cov=finagent --cov-report=term --cov-fail-under=50
python -m build
python -m pip check
```

## 2. Provider smoke tests

LLM connectivity:

```bash
python scripts/smoke_llm_provider.py configs/llm.toml --profile deepseek_official_v4_pro
```

US reference data:

```bash
python scripts/pull_market_data.py configs/markets/us_etf_agent_data_alpaca.toml --show-capabilities
python scripts/validate_market_data.py data/market/us_etf_alpaca
```

Use Alpaca SIP for US historical research. IEX is a single-exchange smoke feed and may have calendar gaps.

## 3. Local A-share test sequence

Install the local Parquet surface:

```bash
python -m pip install -e ".[local-parquet]"
```

Run T-A0 through T-A4 in order.

### T-A0 — source certification

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

Review the JSON, not only the exit code. It must expose schema, duplicates, invalid listing dates, incomplete status coverage, quarantined legacy codes, OHLC/adjustment quality, the 241-row minute convention and daily/minute unit reconciliation.

The audited no-trade placeholder is narrowly defined as:

```text
open = high = low = 0
close = pre_close > 0
vol = amount = 0
```

It remains in immutable vendor data, is reported as `LA-DAILY-07`, and is excluded from `PriceBar`. Any other non-positive or inconsistent OHLC remains an error.

### T-A1 — freeze the source identity

Ubuntu:

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

The default computes SHA-256 for `stock_basic_data.parquet` and `stock_daily.parquet`. Keep the manifest with every research report. Use `--fast` only for diagnostics.

### T-A2 — supplemental reference data

Tracked source-bound templates live under `reference_data/a_share/`.

```bash
python -m pytest -q tests/test_ashare_freeze_supplemental_v127.py
```

Every real row must use a registered source, canonical `ts_code`, exact URL and timezone-aware `observed_at`. Partial files must remain marked `coverage = "partial"`.

### T-A3 — adapter/system smoke

Copy and edit:

```text
configs/research/local_ashare_research_smoke.example.toml
```

Ubuntu:

```bash
python scripts/run_local_ashare_research_smoke.py \
  configs/research/local_ashare_research_smoke.local.toml \
  --verify-content
```

Windows:

```powershell
python scripts/run_local_ashare_research_smoke.py `
  configs\research\local_ashare_research_smoke.local.toml `
  --verify-content
```

This verifies:

```text
frozen identity
→ supplemental master
→ DuckDB local adapter
→ strict no-trade filtering
→ ResearchDataset / eligibility_mask
→ adjustment-aware lagged features
→ common-panel-session forward labels
→ deterministic RankIC diagnostic
```

`forward_*_h` uses the common panel session clock. If the asset is not tradable on the h-th later panel session, the label is `NaN`; it must not jump to the first post-suspension trade.

The RankIC here is a plumbing diagnostic, not promotion evidence.

### T-A4 — bounded Factor Quant acceptance (A2)

The A2 entry point is:

```text
scripts/run_local_ashare_factor_research.py
configs/research/local_ashare_factor_research.example.toml
```

It performs historical daily factor research only. It does not invoke A-share execution, promotion, sealed holdout, PAPER, realtime or broker code.

#### 3.4.1 Prepare a local config

Windows:

```powershell
Copy-Item `
  configs\research\local_ashare_factor_research.example.toml `
  configs\research\local_ashare_factor_research.local.toml
```

Ubuntu:

```bash
cp configs/research/local_ashare_factor_research.example.toml \
   configs/research/local_ashare_factor_research.local.toml
```

Edit at least:

```toml
root = "D:/Data/A-Share"
frozen_manifest = "data/manifests/local_ashare_daily.json"
supplement_root = "reference_data/a_share"
state_dir = ".finagent/local-ashare-factor-a2"
report_path = "reports/local_ashare_factor_research_a2.json"
```

The example fixes a candidate universe before development, uses 2018–2021 for development, 2022–2024 for validation, and leaves 2025 onward untouched.

#### 3.4.2 Deterministic baseline

Run the five predeclared factors first. This isolates the data/Factor Quant path from LLM availability.

Windows:

```powershell
python scripts/run_local_ashare_factor_research.py `
  configs\research\local_ashare_factor_research.local.toml `
  --mode deterministic `
  --verify-content
```

Ubuntu:

```bash
python scripts/run_local_ashare_factor_research.py \
  configs/research/local_ashare_factor_research.local.toml \
  --mode deterministic \
  --verify-content
```

The command traverses:

```text
content-verified frozen Parquet
→ fixed pre-development candidate universe
→ per-session PIT universe policy
→ panel-native generated-feature materialization
→ Factor Quant v2 development diagnostics
→ deterministic redundancy-aware factor selection
→ frozen weights and development directions
→ independent validation of every searched factor
→ validation of the frozen factor ensemble
→ untouched reserve record
```

The panel-native materializer reads each raw input panel once per candidate and slices causal windows in memory. It must not perform one DuckDB query per asset/session.

Acceptance checks:

- candidate universe meets configured minimum size;
- candidate selection date precedes development;
- development, validation and reserve do not overlap;
- reserve remains `untouched`;
- all generated factor digests are retained in both development and validation denominators;
- validation does not change factor weights or directions;
- Factor Quant reports contain finite IC/ICIR, quantile and turnover diagnostics;
- no execution-cost or broker claim appears in the report;
- report exits with `passed = true` even when factors have weak or negative performance.

#### 3.4.3 Exact replay

Replay uses the immutable generated-feature store and prior report. It does not call the LLM.

Windows:

```powershell
python scripts/run_local_ashare_factor_research.py `
  configs\research\local_ashare_factor_research.local.toml `
  --frozen-report reports\local_ashare_factor_research_a2.json `
  --assert-replay `
  --verify-content `
  --report reports\local_ashare_factor_research_a2_replay.json
```

Ubuntu:

```bash
python scripts/run_local_ashare_factor_research.py \
  configs/research/local_ashare_factor_research.local.toml \
  --frozen-report reports/local_ashare_factor_research_a2.json \
  --assert-replay \
  --verify-content \
  --report reports/local_ashare_factor_research_a2_replay.json
```

The `acceptance_id`, candidate denominator, development report, frozen ensemble and validation report must match exactly.

#### 3.4.4 Agent discovery

Only after deterministic baseline and replay pass:

```powershell
python scripts/smoke_llm_provider.py configs\llm.toml --profile deepseek_official_v4_pro
python scripts/run_local_ashare_factor_research.py `
  configs\research\local_ashare_factor_research.local.toml `
  --mode agent `
  --llm-profile deepseek_official_v4_pro `
  --verify-content `
  --report reports\local_ashare_factor_research_a2_agent.json
```

Ubuntu uses the same arguments with `/` and `\` line continuations.

Agent mode must satisfy:

- at least two discovery rounds;
- round 2 receives `DEVELOPMENT-ONLY FACTOR QUANT FEEDBACK V2`;
- candidate digests/feature IDs are unique across rounds;
- all adaptive candidates remain in the final denominator;
- Agent feedback contains development metrics only;
- validation, reserve, promotion, PAPER and live evidence are absent from Agent prompts;
- frozen replay succeeds without another LLM request.

#### 3.4.5 Focused CI tests

```bash
python -m pytest -q \
  tests/test_local_ashare_data_layer_v126.py \
  tests/test_ashare_freeze_supplemental_v127.py \
  tests/test_ashare_legacy_anomaly_v127.py \
  tests/test_ashare_suspension_session_semantics_v127.py \
  tests/test_ashare_factor_acceptance_a2.py
```

Windows:

```powershell
python -m pytest -q `
  tests\test_local_ashare_data_layer_v126.py `
  tests\test_ashare_freeze_supplemental_v127.py `
  tests\test_ashare_legacy_anomaly_v127.py `
  tests\test_ashare_suspension_session_semantics_v127.py `
  tests\test_ashare_factor_acceptance_a2.py
```

CI uses synthetic Parquet; the real multi-GB acceptance must still be run locally.

## 4. Interpretation boundary

A2 validates factor-level evidence:

```text
IC / RankIC / ICIR
horizon decay
quantile monotonicity and spread
turnover proxy
coverage
factor-value redundancy
frozen multi-factor ensemble
independent validation and replay
```

It does not certify portfolio execution returns because A-share T+1, lot size, price limits, asymmetric fees and minimum commissions are not yet modeled in the A2 path.

Do not send A2 results to sealed holdout, promotion or PAPER. A-share execution semantics are the next gate.

## 5. Failure severity

P0 — block the next milestone:

- PIT/look-ahead or split leakage;
- frozen identity mismatch;
- wrong units/timezone/timestamp semantics;
- suspension placeholder treated as tradable;
- forward horizon stretched across suspension;
- candidate denominator, direction or weight mutation;
- validation evidence entering Agent feedback;
- reserve access;
- replay failure;
- `+/-inf` in accepted evidence.

P1 — record and continue when bounded:

- incomplete supplemental status coverage;
- candidate-only, non-survivorship-certified universe;
- secondary provider instability;
- large-panel performance limits;
- low-probability crash-recovery windows.

P2 — deployment hardening:

- cryptographic/physical evidence isolation;
- production realtime feeds and broker connectivity;
- high-availability reconciliation infrastructure.

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

On a clean shell without ROS contamination this is also valid:

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

Market-data pull and validation:

```bash
python scripts/pull_market_data.py configs/markets/us_etf_agent_data_alpaca.toml --show-capabilities
python scripts/validate_market_data.py data/market/us_etf_alpaca
```

For US historical research use Alpaca SIP. IEX is a smoke feed and may have single-exchange calendar/volume gaps.

## 5. Local A-share data certification

Install:

```bash
python -m pip install -e ".[local-parquet]"
```

Ubuntu example:

```bash
python scripts/certify_local_ashare_data.py \
  configs/local_ashare.example.toml \
  --root /data/A-Share \
  --sample-symbol 000001.SZ \
  --sample-date 2009-01-05
```

Windows PowerShell:

```powershell
python scripts/certify_local_ashare_data.py `
  configs\local_ashare.example.toml `
  --root D:\Data\A-Share `
  --sample-symbol 000001.SZ `
  --sample-date 2009-01-05
```

The certification report must make the following explicit:

- basic/daily schema;
- invalid or placeholder listing dates;
- duplicate daily bars;
- OHLC validity;
- positive adjustment factors;
- 241-row minute convention;
- daily/minute OHLC reconciliation;
- daily lots/thousand-CNY vs minute shares/CNY reconciliation;
- limitations of the candidate security master.

Do not edit the vendor raw Parquet files to make certification pass.

## 6. Local A-share research-layer test

The local adapter must be exercised through the common `ResearchDataset` interface, not only through direct DuckDB queries. A system smoke should verify:

```text
LocalAshareSecurityMaster
→ LocalAshareParquetDataAdapter
→ DatasetRequest
→ ResearchDataset / ResearchSplit
→ eligibility_mask
→ lagged price/volume features
→ forward labels contained within split boundaries
```

Start with a bounded daily universe. Full-market/long-history materialization is intentionally avoided until chunked panel storage is implemented.

Recommended manual acceptance universe:

```text
20–100 equities
at least SSE + SZSE; include BSE when the requested period is after listing
2–5 years daily data
features: simple_return_1, simple_return_5, log_volume_change_1, turnover_rate, circ_mv
labels: forward_simple_return_1, forward_simple_return_5
```

Expected result:

- no `inf` values;
- missing cells represented as `NaN`, not fabricated prices;
- no forward label crosses a split boundary;
- `data_version` is stable for unchanged frozen source files;
- the dataset records that the universe is candidate-only unless supplemental history certifies otherwise.

## 7. Agent research acceptance

Before a full Agent run:

1. provider connectivity smoke passes;
2. dataset/manifest identity passes;
3. deterministic dataset construction passes;
4. generated feature sandbox tests pass.

A frozen-family replay must be exact and must not call the LLM.

Formal ensemble validation must retain the complete search denominator:

```text
K searched single factors + 1 frozen ensemble
```

and must use aligned outer windows for multiplicity/DSR/PBO/Reality Check evidence.

## 8. A-share boundary for the current milestone

The current acceptance does **not** require:

- realtime A-share feed;
- external A-share broker;
- complete historical suspension/ST/delisting coverage;
- 1-minute execution backtesting.

Those remain deferred. Historical daily research and data reproducibility are the current gate.

## 9. Failure severity

P0 — block the next research milestone:

- PIT/look-ahead violation;
- split leakage;
- dataset identity drift;
- wrong price/volume unit;
- wrong timezone/bar timestamp semantics;
- denominator mutation;
- replay failure;
- NaN/Inf incorrectly accepted as finite evidence.

P1 — record and continue when bounded:

- incomplete supplemental status coverage;
- provider/network instability on a secondary source;
- large-panel memory/performance limits;
- low-probability crash recovery windows.

P2 — deployment hardening:

- cryptographic/HSM sealing;
- physical data isolation;
- full realtime operational infrastructure.

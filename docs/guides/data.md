# Data guide

## Authority levels

FinAgent distinguishes:

```text
provider/API capability
FinAgent adapter capability
source provenance/publication authority
local research admission
normalized data quality
research certification
```

These are not interchangeable.

## U.S. minute source workflow

```text
DatasetSourceCandidate
  ↓ source review
DatasetAuthorityDecision
  ↓ exact local snapshot
LocalMinuteResearchCertification
  ↓ cleaning-policy-bound local admission
LocalMinuteResearchAdmission
  ↓ later US-C0 / US-D1
MarketDataQuery / DuckDB bounded scan
  ↓
MarketDataView
  ↓
bounded materialization
  ↓
ResearchDataset
```

The source/publication review and local research admission answer different questions. The former records what is publicly documented about origin, published semantics and usage rights. The latter answers whether one exact locally downloaded immutable snapshot is sufficiently identified and empirically checked for **local, non-redistributed research**.

A `REJECTED` source can never receive local admission. A `REFERENCE_ONLY` public source may receive local admission if the exact snapshot passes certification and unresolved source issues remain explicit limitations. This does not assert redistribution rights.

## Canonical OHLCV-1m candidate

FinAgent currently binds:

```text
mito0o852/OHLCV-1m
revision 776328445b7ac6e7815ef3a483e9c8ded1eb6d56
```

The dataset card reports:

```text
schema: timestamp/open/high/low/close/volume/ticker
timestamp timezone: UTC
timestamp convention: start of minute
partitioning: data/ohlcv_YYYY-MM.parquet
coverage: 1992-01 through 2026-03
upstream: Finnhub, declared by the dataset publisher
```

FinAgent treats the bound 1m snapshot as raw/split-unadjusted intraday history and keeps corporate-action handling explicit. The dataset contains historical ticker observations but no point-in-time security-master/lifecycle table. This limits broad survivorship-free claims but does not prevent bounded engineering research.

Regular-versus-extended-hours coverage is measured from the local files instead of inferred from the README.

## Local environment convention

The operator-facing Windows environment is managed with **Conda**. Run local commands from an activated environment such as:

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent
```

PowerShell examples use the backtick `` ` `` for multiline commands and Windows paths. `uv.lock` remains the CI/reproducibility resolution authority introduced by ENG-0, but normal workstation commands should not require replacing the user's Conda environment with `uv run`.

## Source-authority review

Source authority is represented by `finagent.data.provenance` and remains bound to the exact revision. From the activated Conda environment:

```powershell
python scripts\review_us_source_authority.py `
  configs\us_source_authority\mito0o852_ohlcv_1m.toml `
  --output reports\us_source_authority\mito0o852_ohlcv_1m.json
```

The publication layer remains `REFERENCE_ONLY` because the publisher-origin statement is not independently verified, the README declares no license, and historical session coverage is not globally specified. Those limitations do not automatically prevent local research admission.

## Local Hugging Face snapshot

Supported layout:

```text
<cache-root>/
  refs/main
  snapshots/<revision>/
    README.md
    data/
      ohlcv_YYYY-MM.parquet
```

The current workstation snapshot is:

```text
D:\Data\datasets--mito0o852--OHLCV-1m
```

Do not move or duplicate the 80+ GB corpus into the FinAgent repository.

## Cleaning policy

The first real certification found sparse data defects rather than structural corruption: isolated invalid OHLC rows and a small number of duplicate `(ticker,timestamp)` keys. FinAgent therefore separates **quarantinable defects** from **ambiguous defects**.

`MinuteDataCleaningPolicy` v1 uses:

```text
max invalid OHLC row rate:          1e-6
max exact-duplicate extra-row rate: 1e-4
invalid OHLC action:                drop
exact duplicate action:             collapse_full_row
conflicting duplicate keys:         reject
null/blank ticker or timestamp:      reject
negative/null volume:                reject
outside 04:00–20:00 ET:             diagnostic, not an automatic reject
```

The thresholds are part of `policy_id`; changing them changes certification identity. A passing certification therefore does not mean the raw files are perfect. It means observed sparse defects are bounded and the exact deterministic cleaning behavior is frozen.

`clean_month_select_sql()` is the canonical v1 read transformation for admitted local data. It removes invalid OHLC/identity/volume rows and collapses exact full-row duplicates. It does **not** choose between conflicting rows with the same `(ticker,timestamp)` key; certification must fail if such conflicts are observed.

## Local minute recertification

Run from the repository root in the active Conda environment:

```powershell
python scripts\certify_us_minute_snapshot.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --sample-month 1992-01 `
  --sample-month 2000-01 `
  --sample-month 2014-06 `
  --sample-month 2020-08 `
  --sample-month 2026-03 `
  --output reports\us_minute_local_certification.json
```

Certification performs:

- exact `refs/main` / snapshot revision verification;
- inventory of every `ohlcv_YYYY-MM.parquet` file using path and size identity;
- expected 1992-01 → 2026-03 coverage and missing-month detection;
- Parquet schema and timezone-aware timestamp validation;
- full scans of selected monthly partitions;
- duplicate-key classification into exact versus conflicting duplicates;
- invalid identity, OHLC and volume counts;
- sampled ticker counts and timestamp ranges;
- observed regular/extended-hours diagnostics in `America/New_York`;
- cleaning-policy-bound inventory/certification identities.

A successful v2 report may contain warning codes such as:

```text
quarantine:invalid_ohlc
collapse:exact_duplicate_rows
session:outside_0400_2000_observed
```

Warnings are evidence, not silent fixes. The corresponding deterministic action is recorded in the local research admission.

If certification passes, FinAgent emits a `LocalMinuteResearchAdmission` with scope:

```text
local_non_redistributed_research
```

The admission binds the exact source revision, inventory, certification and cleaning policy while carrying public-source limitations forward.

## Research and execution prices

The selected minute source is treated as raw/split-unadjusted for the bound local research workflow. Before research spans corporate-action discontinuities, later stages must either attach explicit split/action evidence and a versioned transform, or exclude/segment affected windows and narrow the claim.

Do not silently treat raw intraday OHLC as a continuous adjusted price series.

## Large-data rule

Do not load the full minute corpus into pandas or a dense `ResearchDataset`. Later Data Plane work queries bounded assets/time/columns with DuckDB and materializes only the computation slice.

## Broker reference data

MT5 broker M1/tick/spread samples are reconciliation/cost/reference evidence unless a later stage explicitly grants them historical research authority. Equity-source and CFD-source differences remain visible.

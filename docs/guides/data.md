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
LocalMinuteResearchCertification / LocalMinuteQuarantineCertification
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

## Cleaning and quarantine stack

The first real certifications found sparse defects rather than broad structural corruption. FinAgent therefore preserves raw anomaly evidence but materializes a deterministic admitted view.

Base cleaning v2:

```text
max invalid OHLC row rate:          1e-6
max exact-duplicate extra-row rate: 1e-4
invalid OHLC action:                drop
exact duplicate action:             collapse_full_row
null/blank ticker or timestamp:      reject
negative/null volume:                reject
outside 04:00–20:00 ET:             diagnostic
```

Conflict quarantine v1:

```text
max conflicting raw-row rate: 5e-5
conflicting duplicate action: drop_entire_key_group
```

A conflicting group means two or more distinct OHLCV variants share the same `(ticker,timestamp)`. The source carries no arrival/correction sequence that proves which variant is authoritative, so FinAgent does not choose a winner, average prices, take maximum volume, or use diagnostic row ordering as source precedence.

The whole group becomes an explicit missing minute in the admitted view. The 5e-5 raw-row ceiling prevents this mechanism from hiding structural data corruption. Policy thresholds/actions are identity-bound; changing them creates a new policy/certification identity.

`quarantined_clean_month_select_sql()` is the canonical admitted read transformation. It:

- removes invalid identity/OHLC/volume rows;
- collapses exact full-row duplicates;
- detects conflicting `(ticker,timestamp)` groups from the raw partition;
- removes **every raw row** in each conflicting group.

The raw Parquet snapshot is never modified.

## Evidence that motivated whole-group quarantine

The v2 certification is:

```text
certification_id: us-minute-certification-105aaf18a6ea908d9457c539
inventory_id:     us-minute-inventory-c2cbf682b456f97eb613ed65
cleaning_policy:  us-minute-cleaning-policy-aa9858b0a35545ea34c62cac
```

The blocking 2026-03 partition contained:

```text
row_count:                              34,379,927
duplicate_key_count:                           409
exact_duplicate_key_count:                      17
exact_duplicate_extra_row_count:                17
conflicting_duplicate_key_count:               392
conflicting_duplicate_extra_row_count:         407
conflicting raw rows:                          799
```

The follow-up diagnostic is:

```text
diagnostic_id: us-minute-conflict-diagnostic-798426d5f48a381d3608f40b
conflicting tickers: 333
conflicting keys with >2 rows: 11
conflict time range: 2026-03-31T13:30:00Z .. 2026-03-31T21:33:00Z
```

Field/pattern evidence showed that the ambiguity is not safely resolvable by one-column rules: 391/392 keys differed in volume, 378/392 differed in both price and volume, and only 13 were volume-only. The conflicting raw-row rate is approximately `799 / 34,379,927 = 2.324e-5`, below the frozen `5e-5` quarantine ceiling. The defect is therefore retained as an explicit gap rather than converted into invented market truth.

## Conflict diagnostics

To reproduce the read-only diagnostic in the active Conda environment:

```powershell
python scripts\diagnose_us_minute_conflicts.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --month 2026-03 `
  --examples 30 `
  --output reports\us_minute_conflict_diagnostic_2026-03.json `
  --rows-output reports\us_minute_conflicting_rows_2026-03.csv
```

`diagnostic_variant_rank` in the CSV is deterministic output ordering only. It is not source arrival order and must never be used as a winner rule.

## Local minute v3 recertification

After pulling the conflict-quarantine increment, run from the repository root in the active Conda environment:

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

The v3 report preserves the raw v2-style counts inside `base_certification` and adds:

```text
conflict_quarantine_policy
cleaning_identity
quarantined_conflicting_key_count
quarantined_conflicting_raw_row_count
post_clean_conflicting_duplicate_key_count
```

A valid US-S0 terminal requires:

```text
certification.schema_version = finagent.us-minute-local-certification.v3
certification.passed = true
local_research_admitted = true
post_clean_conflicting_duplicate_key_count = 0
```

A pass does not claim the raw source is defect-free. It proves that the exact revision, inventory, bounded cleaning stack and deterministic quarantine behavior are sufficient for the stated `local_non_redistributed_research` scope.

## Research and execution prices

The selected minute source is treated as raw/split-unadjusted for the bound local research workflow. Before research spans corporate-action discontinuities, later stages must either attach explicit split/action evidence and a versioned transform, or exclude/segment affected windows and narrow the claim.

Do not silently treat raw intraday OHLC as a continuous adjusted price series.

## Large-data rule

Do not load the full minute corpus into pandas or a dense `ResearchDataset`. Later Data Plane work queries bounded assets/time/columns with DuckDB and materializes only the computation slice.

## Broker reference data

MT5 broker M1/tick/spread samples are reconciliation/cost/reference evidence unless a later stage explicitly grants them historical research authority. Equity-source and CFD-source differences remain visible.

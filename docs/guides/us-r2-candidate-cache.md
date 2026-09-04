# US-R2-1c frozen candidate cache

US-R2-1c converts the completed candidate-independent annual 15m/60m base panels into a reusable cache for the frozen US-R1 candidate denominator. It is an infrastructure step only: it does not select factors, compute the R2 statistical terminal, advance `docs/status.toml`, or grant Alpha/execution/order/live-capital authority.

## Frozen inputs

The operator fails closed before opening DuckDB unless all of the following identities validate:

- base-panel batch evidence: `us-r2-base-panel-batch-4833b15a9cb49649948d7118`;
- US-R1 candidate denominator: `us-r1-denominator-be5184ac3883b0799c00c5dc`;
- denominator size: exactly 37 candidates;
- `performance_filter_applied=false`;
- reviewed regime-v2 evidence: `us-r2-regime-projection-v2-337a6ce4272376aa401d4f4b`;
- frozen US-R2 protocol, five folds, 15m signal clock, same-session 60m label semantics and minimum cross-section remain unchanged.

The regime evidence is an identity prerequisite at this stage. Candidate feature values remain regime-agnostic. Fold/regime projection is applied later by the statistical-evaluation layer so that feature computation cannot depend on evaluation regime or candidate performance.

## Runtime boundary

The raw 1m snapshot is not an input to this operator. For each missing candidate-cache year the only market-data relation is the already-materialized annual base Parquet:

```text
data/us_r2/base/year=YYYY/us_r2_15m60m_base.parquet
        ↓ one read_parquet() relation
asset-contiguous stream
        ↓
37 frozen R1 candidates → canonical A1 shared execution DAG
        ↓
annual wide candidate cache
```

There is no `manifest_from_huggingface_snapshot`, `DuckDBParquetMinuteStore`, sessionizer, raw-source revision argument, or raw-minute fallback in the candidate operator. Completed cache years are content-validated and skipped.

## Shared-DAG execution

Each frozen R1 candidate is mapped to the structurally equivalent A1 FactorGraph. The 37 graphs are compiled together with `compile_factor_graph_batch()`, which merges identical canonical subexpressions. Each unique node series is evaluated once per asset-year instead of evaluating every candidate as an independent expression tree.

A1-1 already maintains per-formation bitwise parity with `evaluate_us_baseline_feature()` for the complete 62-candidate A0 vocabulary. US-R2-1c adds a dedicated 37-candidate mapping/parity regression and preserves R1 availability precedence:

1. insufficient history;
2. cross-session window;
3. incomplete bar inside the lookback;
4. numeric unavailability, including zero reference volume.

An incomplete current bar is not emitted as a candidate formation, matching the accepted R1 materializer. Label-unavailable complete formations are retained with their label reason; they are not silently dropped.

## Cache layout

The cache deliberately avoids a long `formation × candidate` table. Each annual file stores one row per emitted asset/formation and two `N × 37` matrices:

- `candidate_values`: `float64`, with NaN for unavailable values;
- `candidate_reason_codes`: `uint8`.

Row metadata includes asset code, session date, event/availability clocks, 60m label value/availability clock and label reason. This keeps row cardinality equal to the base formation cardinality rather than multiplying it by 37.

The file is a deterministic NPZ container implemented as an uncompressed ZIP with fixed member ordering and timestamps. Annual evidence binds the file by SHA-256 and byte size. This is a local performance cache, not a Git-tracked research result.

Candidate reason codes:

| Code | Meaning |
|---:|---|
| 0 | available |
| 1 | insufficient history |
| 2 | cross-session window |
| 3 | incomplete bar in lookback |
| 4 | numeric unavailable |

Label reason codes:

| Code | Meaning |
|---:|---|
| 0 | available |
| 1 | target crosses session |
| 2 | target minute missing |

## Outputs

Global plan:

```text
reports/us_r2/candidates/us_r2_candidate_cache_plan.json
```

Per year:

```text
data/us_r2/candidates/year=YYYY/us_r2_candidate_cache.npz
reports/us_r2/candidates/year_YYYY/us_r2_candidate_cache_evidence.json
```

Completed batch:

```text
reports/us_r2/candidates/us_r2_candidate_cache_batch_evidence.json
```

The annual data/evidence pair is immutable. If only one side exists, or the evidence identity/file SHA/size differs, the operator fails closed instead of overwriting the year.

## Operator command

After pulling the merge containing US-R2-1c, run from the repository root:

```powershell
$sw = [System.Diagnostics.Stopwatch]::StartNew()

python scripts/materialize_us_r2_candidate_cache.py `
  --base-panel-batch-evidence reports/us_r2/base/us_r2_base_panel_batch_evidence.json `
  --candidate-denominator reports/us_r1/us_r1_candidate_denominator.json `
  --regime-evidence reports/us_r2/us_r2_regime_projection_evidence_v2.json `
  --base-data-root data/us_r2/base `
  --base-report-root reports/us_r2/base `
  --candidate-data-root data/us_r2/candidates `
  --candidate-report-root reports/us_r2/candidates `
  --memory-limit 4GB `
  --threads 4 `
  --max-temp-directory-size 20GB `
  --temp-directory data/duckdb_temp/us_r2_candidates

$exitCode = $LASTEXITCODE
$sw.Stop()
Write-Host ("US-R2 candidate cache exit={0} elapsed={1}" -f $exitCode, $sw.Elapsed)
```

First successful full run should report:

- the exact frozen denominator/base-batch/regime evidence IDs above;
- `candidate_count=37`;
- `unique_node_count < naive_node_count` and positive reuse;
- `requested_years` covering 2001-2026;
- `materialized_years` equal to years without a pre-existing valid candidate cache;
- `annual_base_parquet_scan_count == len(materialized_years)`;
- `raw_minute_source_invocation_count=0`;
- `raw_minute_source_access=false`;
- `candidate_dependent_scan=false`;
- `candidate_performance_read=false`;
- `passed=true`.

A second unchanged run should validate and skip all 26 annual candidate caches, report zero annual base-Parquet scans, and reproduce the same batch evidence ID.

## Authority boundary

US-R2-1c is only a deterministic feature-cache materialization layer. It does not change:

- the 37-candidate denominator;
- the five frozen walk-forward folds;
- regime definitions or TRAIN-only volatility threshold fitting;
- the 15m signal clock or same-session 60m label;
- `minimum_cross_section=10`;
- multiplicity, bootstrap, HAC, direction, robustness or Alpha thresholds.

It also does not establish a point-in-time research universe or remove the frozen survivorship-conditioning limitation of the current-symbol EngineeringUniverse. No US-X0, Alpha, execution, order, PAPER or live-capital authority follows from a successful cache run.

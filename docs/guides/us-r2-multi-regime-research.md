# US-R2 Multi-Regime Research — R2-0 Corpus Inventory and Preregistration

Issue: #158  
Authority on entry: `docs/status.toml` remains `US-R1 / accepted_no_robust_factor_family_terminal`, with `next_stage = "research iteration"`.

US-R2 does not begin by adding factors. R2-0 first establishes how much materially different historical evidence the admitted minute corpus can actually support for the current 25-name EngineeringUniverse and the frozen 37-candidate US-R1 denominator.

## 1. Research question isolation

The first R2 replication changes the **time/regime evidence only**.

Frozen predecessor boundaries:

```text
US-R1 candidate denominator: preserve exactly
performance filter:          false
new US-A1 candidates:         forbidden in first R2 replication
primary signal interval:      15m
robustness intervals:         5m / 30m
primary label:                same-session RAW 60 trading-minute return
purge / embargo:              preserve R1
HAC / block bootstrap:        preserve R1
Holm / BH multiplicity:       preserve R1
```

This prevents a positive or negative R2 result from being confounded by changing both historical regimes and the search space at the same time.

## 2. R2-0 coverage evidence

`src/finagent/research/us_r2_corpus.py` introduces:

```text
USRegimeCorpusInventoryPlan
USRegimeMonthCoverage
USRegimeAssetCoverage
USRegimeYearBreadth
USRegimeResearchCorpus
```

The inventory binds:

- admitted minute-store `manifest_id` / `data_version` / source revision / cleaning identity;
- accepted XNYS `calendar_id`;
- accepted EngineeringUniverse identity;
- accepted US-R1 candidate-denominator identity;
- every EngineeringUniverse asset, including assets with no historical rows;
- every admitted monthly partition.

It does **not** read candidate IC, PnL, p-values or any other candidate-performance result.

The report remains explicitly limited:

```text
EngineeringUniverse != PIT ResearchUniverse
current-symbol fixed universe is survivorship-conditioned
first/last observed row != listing/delisting authority
corpus inventory != Alpha authority
corpus inventory != execution authority
```

## 3. Runtime design

R2-0 is intentionally not implemented as:

```text
for candidate in 37 candidates:
    for asset in 25 assets:
        scan 34 years of minute data
```

That would turn a coverage question into a candidate-multiplied full-corpus scan.

The optimized path is:

```text
all admitted monthly Parquet files
        ↓
one DuckDB read_parquet relation
        ↓ ticker predicate pushdown for EngineeringUniverse only
XNYS calendar join + regular-session filter
        ↓
(ticker, timestamp) exact-duplicate/conflict aggregation
        ↓
asset-session aggregate
        ↓
asset-month aggregate
        ↓
small row-free Python evidence assembly
```

Properties:

- one `read_parquet()` relation for the inventory query;
- no source OHLCV rows leave DuckDB;
- regular-session filtering occurs before the expensive key aggregation;
- exact duplicates collapse deterministically;
- conflicting `(ticker, timestamp)` variants are quarantined before coverage is counted;
- extended-hours rows are excluded from the R2 regular-session coverage denominator;
- Python work scales with approximately `assets × months + assets × calendar sessions`, not `minute rows × candidates`;
- existing `DuckDBExecutionPolicy` keeps memory, threads and temporary spill bounded;
- `preserve_insertion_order=false` remains mandatory for the analytical scan.

The evidence identity does not depend on thread count, memory limit or local temporary-directory location. Those are operational execution controls, not research semantics.

## 4. Why session-membership hashes are stored

The portable report does not need to serialize every minute or even every session date. Each asset-month stores SHA-256 membership identities for observed and complete XNYS sessions plus counts and boundaries.

This keeps the report compact while making a silent date-set substitution detectable even when two months have the same session count.

## 5. Operator command

After pulling the R2-0 branch on the workstation that already contains the accepted local reports and minute snapshot:

```powershell
python scripts/inventory_us_r2_corpus.py `
  D:\path\to\OHLCV-1m-snapshot `
  --universe-report reports/us_instruments/us_i0_target_broker_final_engineering_universe.json `
  --candidate-denominator-report reports/us_r1/us_r1_candidate_denominator.json `
  --calendar-report reports/us_calendar/xnys_1992_2026.json `
  --memory-limit 512MB `
  --threads 2 `
  --max-temp-directory-size 4GB `
  --temp-directory data/duckdb_temp/us_r2_0 `
  --output reports/us_r2/us_r2_regime_corpus_inventory.json
```

The script verifies all three predecessor reports against `docs/status.toml` before scanning. A stale universe, calendar or denominator fails closed.

The normal console output is only a compact summary. Full row-free monthly coverage is written under `/reports/`, which remains gitignored.

## 6. Interpreting the inventory

The first questions are:

1. Does every current EngineeringUniverse name have historical regular-session coverage?
2. What are the first/last observed sessions for each asset?
3. How small is the strict all-25 common window?
4. By year, how many XNYS sessions have 0..25 observed names and 0..25 complete names?
5. Are there large within-observed-history gaps or low minute coverage?
6. Does the corpus support materially different historical states without silently dropping current names?

Do **not** choose a convenient number of years or folds before reading this inventory.

If the strict all-name history is short because current symbols have short histories, that is evidence about the limitation of the EngineeringUniverse. It is not permission to silently remove those assets from old folds. A later protocol may explicitly freeze a bounded cross-sectional rule, but the rule and every omitted asset/session must be visible before candidate results are inspected.

## 7. Regime and walk-forward contracts

`src/finagent/research/us_r2_protocol.py` introduces typed preregistration contracts without freezing data-dependent cut points prematurely:

```text
USRegimeFeatureSpec
USRegimeDefinitionPolicy
USMultiRegimeFold
USMultiRegimeWalkForwardProtocol
```

Allowed initial regime feature sources are ex-ante observables only:

```text
MARKET_ANCHOR_RETURN
MARKET_ANCHOR_REALIZED_VOLATILITY
CROSS_SECTIONAL_DISPERSION
CROSS_SECTIONAL_BREADTH
```

Every feature is lagged by at least one completed session. Regime thresholds must be fit on `TRAIN_ONLY` evidence and classification occurs at `PRIOR_SESSION_CLOSE`.

Explicitly forbidden:

```text
candidate RankIC
candidate return / PnL
candidate p-value
future label
future/evaluation-fold threshold fitting
```

The first multi-regime protocol also binds the accepted R1 research-protocol ID and records:

```text
candidate_denominator_preserved = true
performance_filter_applied = false
new_agent_candidates_admitted = false
```

## 8. Next R2-0 acceptance step

This implementation PR is an engineering preregistration increment, not the final R2-0 evidence closeout.

After the real corpus inventory is generated and reviewed:

1. determine whether the admitted source supports genuinely different historical regimes;
2. if not, close with `INSUFFICIENT_MULTI_REGIME_DATA` or acquire a better admitted source;
3. if yes, freeze the exact regime-feature definitions, thresholds/calibration rule and walk-forward folds;
4. record the frozen corpus/protocol identities;
5. only then start R2-1 candidate materialization.

`docs/status.toml` must remain at `research iteration` until that reviewed preregistration boundary is complete. No R2-0 artifact grants US-X0, PAPER, order or live-capital authority.

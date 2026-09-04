# US-R2 Frozen Multi-Regime Protocol — R2-0b

Issue: #158  
Predecessor: merged US-R2-0 corpus inventory infrastructure and reviewed local corpus inventory.  
Project authority remains `US-R1 / research iteration` until a later reviewed R2 terminal.

R2-0b converts the row-free corpus inventory into an inspectable preregistration. It does **not** run the 37 candidates, inspect candidate PnL/IC/p-values, change the Alpha Gate, or grant execution authority.

## 1. Reviewed local evidence binding

The reviewed inventory is bound by content-addressed identities rather than committed report rows:

```text
corpus_id
  us-r2-regime-corpus-1d49ef091a1781941820a67f

inventory_plan_id
  us-r2-corpus-inventory-plan-4d40742a4d0674431c4c247b

engineering_universe_id
  engineering-universe-259e3975a25856bef28442ff

candidate_denominator_id
  us-r1-denominator-be5184ac3883b0799c00c5dc
```

`reports/` remains gitignored. The operator output is local evidence; Git tracks the validation code, frozen identities, protocol contracts and tests, not the multi-megabyte report body.

The inventory itself records:

```text
candidate_performance_read = false
performance_filter_applied = false
point_in_time_security_master_available = false
survivorship_safe_market_claim = false
alpha_authority = false
execution_authority = false
```

## 2. Why the static 25-name intersection is rejected

The exact current 25-name EngineeringUniverse has only:

```text
common_all_asset_start         = 2025-02-24
common_all_asset_end           = 2026-03-31
common_all_asset_session_count = 277
```

That window cannot represent materially different market regimes. R2 therefore does **not** silently narrow the study to the 277-session common intersection and does not manufacture multiple pseudo-regimes inside it.

At the same time, the year-breadth inventory shows that source-observed cross-sectional breadth is materially larger over long history. From 2001 onward the minimum observed daily breadth remains above the already accepted R1 `minimum_cross_section=10` floor.

The R2 first replication therefore uses a bounded dynamic historical cross-section:

```text
allowed asset set = the complete frozen 25-name EngineeringUniverse
static asset exclusion = forbidden
formation eligibility = source/bar/feature/label availability only
minimum cross-section = 10 (inherited from R1)
partial non-boundary label = omit the entire formation cross-section
```

This is **not** a PIT ResearchUniverse. The current-symbol engineering set remains survivorship conditioned, and first/last source observations are not treated as listing/delisting authority.

## 3. Regime anchor and corporate-action boundary

IWM is the R2-v1 market anchor because it is a broad-market integration name already inside the frozen universe and the inventory shows source coverage from 2000-05-26 through 2026-03-31 with regular-minute coverage above 90% and only three missing sessions in its active span.

The regime classifier deliberately avoids close-to-close multi-session raw-price returns. The admitted historical source is raw/split-unadjusted and has no corporate-action authority; using cross-session price jumps as regime inputs would reintroduce a known authority violation.

Instead, the canonical anchor input is the same-session regular-session return:

```text
session_return = regular_session_close / regular_session_open - 1
price basis    = RAW_SAME_SESSION_ONLY
```

Two lagged market-state features are frozen:

```text
IWM 20-session direction
  arithmetic mean of 20 consecutive completed session returns

IWM 20-session volatility
  population standard deviation of the same 20 session returns
```

Both have `availability_lag_sessions=1`. A session may be classified only from information available by the prior completed session.

## 4. Four-state ex-ante classifier

The regime labels are:

```text
DOWN_LOW_VOL
DOWN_HIGH_VOL
UP_LOW_VOL
UP_HIGH_VOL
```

Direction uses a fixed zero threshold; equality maps to `UP`.

Volatility uses the median fitted on that fold's TRAIN window only; equality maps to `LOW_VOL`. Evaluation data, future labels and candidate results cannot fit the regime threshold.

This classifier is intentionally simple. R2 is testing temporal/regime stability of the already frozen denominator, not optimizing a regime model.

## 5. Frozen walk-forward windows

IWM source coverage begins during 2000, so 2001 is the first full research year. Five long folds are preregistered:

| Fold | TRAIN | Evaluation |
| --- | --- | --- |
| `us-r2-fold-01` | `[2001-01-01, 2006-01-01)` | `[2006-01-01, 2010-01-01)` |
| `us-r2-fold-02` | `[2005-01-01, 2010-01-01)` | `[2010-01-01, 2014-01-01)` |
| `us-r2-fold-03` | `[2009-01-01, 2014-01-01)` | `[2014-01-01, 2018-01-01)` |
| `us-r2-fold-04` | `[2013-01-01, 2018-01-01)` | `[2018-01-01, 2022-01-01)` |
| `us-r2-fold-05` | `[2017-01-01, 2022-01-01)` | `[2022-01-01, 2026-04-01)` |

Evaluation windows do not overlap. The final exclusive end is 2026-04-01 because the admitted snapshot ends on 2026-03-31.

Every fold declares all four regime labels as expected. A later materializer must fail closed if the required market-state evidence cannot be produced; R2-0b does not inspect candidate outcomes to repair the folds.

## 6. Candidate direction and statistical semantics remain R1

The first R2 replication preserves the complete 37-candidate R1 denominator:

```text
performance_filter_applied = false
new_agent_candidates_admitted = false
```

Factor sign/direction remains a one-time TRAIN decision from `us-r2-fold-01` using mean cross-sectional RankIC with the accepted positive zero tie-break, and the direction remains frozen across all evaluation folds.

R2 also inherits the accepted R1 research semantics, including:

- canonical 15m signal interval and 5m/30m robustness;
- same-session 60 trading-minute primary raw label and 30m/120m decay checks;
- same-session / intraday-flat boundary;
- purge and embargo;
- HAC settings;
- session-block bootstrap;
- Holm FWER and BH FDR multiplicity control;
- five-quantile diagnostics;
- `minimum_cross_section=10`.

No R1 Alpha Gate threshold is relaxed in this increment.

## 7. Runtime boundary

The expensive R2-0 inventory already performed one candidate-independent DuckDB scan over the admitted Parquet snapshot.

R2-0b must **not** repeat that scan. `freeze_us_r2_protocol_from_inventory()` reads only row-free summary fields needed to validate the freeze:

```text
inventory identities / authorities
25 asset coverage summaries
2001–2026 year-breadth summaries
```

It does not iterate or materialize source minute rows and does not evaluate the 37 candidates.

Operator:

```powershell
python scripts/freeze_us_r2_protocol.py `
  --inventory reports/us_r2/us_r2_regime_corpus_inventory.json `
  --output reports/us_r2/us_r2_frozen_protocol.json
```

The output remains under ignored `reports/` and prints the content-addressed freeze/policy IDs for review.

## 8. Authority ceiling and next increment

R2-0b grants no:

```text
Alpha authority
stage-exit authority
execution authority
order authority
PAPER authority
live-capital authority
```

After this PR merges, the next coherent increment is **US-R2-1 deterministic multi-regime materialization**. It should bind the R2 freeze ID, process the long history in bounded asset/session or partition chunks, preserve the 37-candidate denominator, and emit row-free/content-addressed evidence without recomputing the full corpus inventory.

# V4-3A Factor Tear Sheet Foundation

Date: 2026-08-30

V4-3A starts the active **V4-3 Factor Tear Sheet** stage without declaring the full V4-3 roadmap complete. It consumes immutable V4-1 `FactorSeriesEvidence` and the physically bound frozen A2.6 source report; it does not reconstruct authoritative statistics in React.

## Delivered evidence projection

`FactorTearSheetProjection` discovers `finagent.factor-series.manifest.v1` packages under configured Workspace report roots and opens each package through the existing fail-closed `FactorSeriesProjection` verification path. A factor series is visible only after its source A2.6 report and Parquet pass the V4-1 identity/SHA/schema/row checks.

Equivalent rematerializations are de-duplicated only when the V4-1 catalog identity **and** `rows_digest`, `quant_config_digest`, and `source_report_content_digest` agree. This is intentionally stricter than comparing `series_id` alone because the V4-1 series identity does not itself contain the frozen source-report content digest. Conflicting identities are omitted until resolved.

The Evidence Plane adds GET-only routes:

```text
GET /api/v4/factor-series
GET /api/v4/factor-series/by-program/{program_id}
GET /api/v4/factor-series/{series_id}
GET /api/v4/factor-series/{series_id}/dimensions
GET /api/v4/factor-series/{series_id}/summary
GET /api/v4/factor-series/{series_id}/rows
```

Row queries expose only semantic filters (`feature_digest`, `fold_id`, `series_kind`, `metric`, `label_name`, `quantile`, `start`, `end`, `offset`) and retain `limit <= 5000`. Browser-supplied host paths or executable inputs are not accepted.

## Authority boundary

V4-3A keeps three evidence classes explicit:

1. **V4-1 authoritative period rows** — primary/decay IC, period returns, one-way turnover and coverage remain `authority=authoritative`.
2. **V4-1 persisted derived rows** — rolling IC and cumulative NAV remain `authority=derived`; V4-3A does not roll or cumulate them again.
3. **Frozen A2.6 authoritative summary** — candidate/fold diagnostics, HAC t-statistics, bootstrap p-values/confidence bounds, Holm-adjusted p-values, BH q-values, gate/selection records and persisted factor correlations are copied from the source A2.6 report physically bound by V4-1. `statistics_recomputed=false` is part of the projection contract.

React may group, filter or pivot already-persisted values for presentation. It must not recalculate IC/ICIR, cumulative NAV, HAC/bootstrap statistics, multiple-testing corrections, gate decisions or replacement factor-correlation evidence.

## Workbench surface

The **Factors** module now routes to `/factors` and uses the existing URL-backed `WorkbenchContext` keys:

```text
program_id
factor_id
date_range
session_date
fold_id
```

The V4-3A page renders:

- authoritative RankIC together with persisted-derived rolling RankIC;
- authoritative primary/decay horizon RankIC;
- a frozen A2.6 fold RankICIR heatmap without period-row re-aggregation;
- persisted-derived quantile and long-short NAV;
- authoritative one-way turnover and coverage;
- frozen pooled RankICIR, long-short Sharpe, HAC, bootstrap CI/p, Holm p and BH q summaries;
- a selected-session inspector that binds `session_date` but creates no new statistic;
- immutable series/program/selection/data/rolling-window identity context.

The legacy `/factor/{digest}` evidence page remains available for compatibility and source-oriented inspection.

## Deliberately remaining in V4-3

V4-3A exposes enough frozen summary/correlation evidence to support later presentation work, but does not yet claim full V4-3 completion. Remaining increments are:

- richer HAC/bootstrap forest rendering;
- Holm/BH comparison matrix presentation;
- factor-correlation clustering/dendrogram presentation;
- Agent discovery-evolution projection and linked visualization.

These later surfaces must consume frozen evidence or dedicated immutable projections rather than introduce browser-side statistical authority.

## Acceptance

The Workspace gate is extended so Ubuntu and Windows run the V4-3A backend tests with `local-parquet`, compile the projection, and include it in Ruff/mypy checks. Frontend TypeScript/Vitest/build/Playwright gates include the new Factors route; focused Vitest coverage verifies authority labeling and that factor changes preserve fold/date filters through `WorkbenchContext`.

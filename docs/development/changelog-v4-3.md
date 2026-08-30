# V4-3 Factor Tear Sheet

V4-3 delivers the read-only **Factor Tear Sheet** over the immutable V4-1 `FactorSeriesEvidence` package and the frozen A2.6 statistical summaries that produced it.

## Scope

The stage adds presentation and bounded read projection only. It does not rewrite A2.6 or V4-1 evidence, rerun factor selection, choose factor direction from test data, access production reserve, promote a strategy, mutate PAPER state, submit broker orders, or add shell/Python execution authority.

The authoritative chain remains:

```text
frozen A2.6 ResearchProgram
        ↓
V4-1 FactorSeriesEvidence
        ↓ verified source-report / Parquet identity
V4-3 FactorTearSheetProjection
        ↓ GET-only bounded API
Factors Workbench
```

## Evidence sources and authority

V4-3 preserves the source authority instead of flattening all chart values into one class.

| Surface | Source | Authority |
| --- | --- | --- |
| primary/decay Pearson IC and RankIC | V4-1 period rows | authoritative |
| quantile / long-short period return | V4-1 period rows | authoritative |
| one-way turnover / coverage | V4-1 period rows | authoritative |
| rolling IC | V4-1 persisted transform | derived |
| quantile / long-short NAV | V4-1 persisted transform | derived |
| pooled/fold robust metrics | frozen A2.6 walk-forward report | authoritative |
| HAC t-stat / raw p-value | frozen A2.6 report | authoritative |
| block-bootstrap p-value / 95% CI | frozen A2.6 report | authoritative |
| Holm adjusted p-value / BH q-value | frozen A2.6 report | authoritative |
| gate result / reason codes / robust score | frozen A2.6 gate report | authoritative |
| selected component direction / score / weight | frozen A2.6 selection | authoritative |
| factor correlation values | frozen A2.6 walk-forward summary | authoritative |
| fold/year heatmap mean | server aggregation of V4-1 period rows | derived presentation |
| hierarchical correlation order | server clustering of frozen correlations | derived presentation |
| candidate identity / hypothesis / generator / lookback | frozen A2.6 candidate denominator | authoritative provenance |

No numerical factor statistic is reconstructed in React.

## Verified projection

`FactorTearSheetProjection` discovers `finagent.factor-series.manifest.v1` manifests only under configured report roots. Before exposure it instantiates the existing `FactorSeriesProjection`, which verifies:

- source A2.6 report SHA-256 and immutable report identities;
- manifest quant configuration and candidate denominator identities;
- Parquet SHA-256 and column contract;
- contiguous sequence and deterministic row IDs;
- complete row digest;
- factor denominator, fold count, session count and date bounds.

Equivalent deterministic rematerializations are de-duplicated by semantic series identity. Conflicting payloads that claim the same `series_id` fail closed and the identity is omitted from the catalog.

## Evidence Plane API

All V4-3 routes are GET-only:

```text
GET /api/v4/factor-series/status
GET /api/v4/factor-series
GET /api/v4/factor-series/by-program/{program_id}
GET /api/v4/factor-series/{series_id}
GET /api/v4/factor-series/{series_id}/dimensions
GET /api/v4/factor-series/{series_id}/summary
GET /api/v4/factor-series/{series_id}/correlations
GET /api/v4/factor-series/{series_id}/heatmap
GET /api/v4/factor-series/{series_id}/provenance
GET /api/v4/factor-series/{series_id}/rows
```

The row endpoint delegates to the V4-1 bounded projection and supports semantic filters only:

```text
feature_digest
fold_id
series_kind
metric
label_name
quantile
start
end
offset
limit
```

The hard query bound remains:

```text
1 <= limit <= 5000
```

No browser-provided host path, output path, shell command, Python source, broker target, reserve mutation or live-capital parameter is accepted.

## Factor Workbench

The Factors module is available at:

```text
/factors
/factors/{series_id}
```

The detail page includes:

- authoritative RankIC with persisted rolling RankIC;
- multi-horizon IC decay;
- Q1–Qn and long-short NAV;
- one-way turnover and coverage;
- derived fold/year RankIC heatmap;
- frozen HAC / block-bootstrap inference forest;
- frozen Holm/BH multiplicity matrix;
- frozen factor correlation matrix with derived hierarchical ordering;
- frozen candidate provenance, gate state and selected-component state.

Selection uses the existing URL-backed `WorkbenchContext`:

```text
program_id
factor_id
fold_id
date_range
```

Browser history/reload therefore preserves Factor Tear Sheet identity without introducing another page-local context contract.

## Agent chronology boundary

The frozen A2.6 candidate denominator records factor identity, hypothesis, generator ID, input fields and lookback, but it does **not** freeze an Agent generation timestamp or discovery-round chronology.

V4-3 therefore exposes:

```text
ordering_semantics = frozen_candidate_denominator_order_only
agent_chronology_available = false
```

The Factors page labels this explicitly and does not present denominator order as an Agent evolution timeline. A future chronology visualization requires a separately frozen Agent discovery-series contract.

## Control and governance boundary

V4-3 adds no Control Plane command and no write route. Existing generic Control authority remains limited to the previously approved typed L0 services. In particular V4-3 adds no path for:

```text
production reserve
strategy promotion
PAPER mutation
broker order
live capital
arbitrary shell
arbitrary Python
```

## Acceptance

Automated acceptance covers:

- verified V4-1 discovery and frozen A2.6 summary projection;
- period-row authority preservation;
- bounded semantic row queries;
- GET-only V4-3 routes;
- correlation and heatmap authority labels;
- explicit no-Agent-chronology contract;
- Factors panel registry and routes;
- TypeScript API types/client;
- WorkbenchContext factor/fold/date persistence;
- Vitest rendering/authority tests;
- production frontend build;
- Playwright Factor Tear Sheet navigation and reload smoke;
- Ubuntu Workspace API regression;
- repository Python and A2.6 / legacy Research UI regression.

Windows CI remains configured exactly as before and is not weakened. It may be completed asynchronously or reproduced manually on Windows.

### Windows manual acceptance

PowerShell from the repository root:

```powershell
py -3.11 -m pip install -e ".[dev,workspace,local-parquet]"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
py -3.11 -m pytest -q tests/test_factor_series_v41.py tests/test_factor_tearsheet_v43.py
py -3.11 -m py_compile src/finagent/visualization/factor_tearsheet.py src/finagent/visualization/factor_tearsheet_routes.py src/finagent/visualization/workbench_api.py
```

Full repository Windows regression when desired:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
py -3.11 -m pytest -q
```

Frontend acceptance on Windows:

```powershell
cd workspace
npm ci
npm run typecheck
npm run test
npm run build
npx playwright install chromium
npm run e2e -- factor-v4.spec.ts
```

## Completion semantics

V4-3 completion means the frozen factor evidence can be inspected interactively without creating a second statistical calculation path. It does **not** imply persistent alpha, reserve approval, strategy promotion or live readiness.

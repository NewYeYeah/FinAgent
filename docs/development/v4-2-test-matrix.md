# V4-2 acceptance matrix

V4-2 is accepted only when all of the following pass on the final pull-request head:

- backend projection discovery verifies V4-0 report/ledger/Parquet before catalog exposure;
- conflicting `series_id` manifests fail closed;
- optional DuckDB absence does not prevent unrelated Workspace startup;
- all `/api/v4/strategy-series*` routes remain GET-only;
- decision query remains bounded to `limit <= 5000`;
- Ubuntu and Windows Workspace API suites include V4-2 tests;
- Ruff/mypy cover the new projection and composed Evidence API;
- TypeScript typecheck and Vitest cover V4 types/API/page/registry;
- production frontend build succeeds;
- Playwright verifies Strategy navigation and WorkbenchContext persistence;
- repository-wide Python 3.11/3.12/3.13 and Windows pytest remain green;
- V4-0 series, A2.6, A5 reserve and legacy visualization regressions remain green when triggered by the final diff.

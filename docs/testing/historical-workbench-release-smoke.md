# Historical Workbench 1.0 Post-freeze Release Smoke

HW-1.0-RS is a product-level smoke over the already frozen A-C5 release. It does not rerun A2.6/A4 and does not consume production reserve.

## Focused CI contract

Blocking environment remains Ubuntu 24.04 / Python 3.11.

Backend:

```bash
PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q tests/test_historical_workbench_release_smoke.py

python -m py_compile \
  src/finagent/runtime/historical_workbench_release_smoke.py \
  src/finagent/runtime/historical_workbench_release_smoke_acceptance.py \
  scripts/run_historical_workbench_release_smoke.py

ruff check \
  src/finagent/runtime/historical_workbench_release_smoke.py \
  src/finagent/runtime/historical_workbench_release_smoke_acceptance.py \
  scripts/run_historical_workbench_release_smoke.py \
  tests/test_historical_workbench_release_smoke.py \
  --select E4,E7,E9,F

mypy --follow-imports=silent \
  src/finagent/runtime/historical_workbench_release_smoke.py \
  src/finagent/runtime/historical_workbench_release_smoke_acceptance.py \
  scripts/run_historical_workbench_release_smoke.py
```

Frontend contract:

```bash
cd workspace
npm ci
npm run typecheck
npm run build
npx playwright install --with-deps chromium
npx playwright test e2e/historical-release-smoke.spec.ts
```

The real frozen-evidence Playwright spec is present in the normal E2E directory but skips automatically unless `FINAGENT_HW_RS_*` identities are injected by the local orchestrator.

## Real local release smoke

Run from the repository checkout that contains the already accepted A-C5 artifacts.

Windows PowerShell:

```powershell
git checkout main
git pull --ff-only

cd workspace
npm ci
cd ..

python scripts\run_historical_workbench_release_smoke.py `
  configs\acceptance\historical_workbench_release_smoke.example.toml
```

The runner:

1. verifies the A-C5 freeze report and recomputes `freeze_id`;
2. verifies the deterministic A-C5 ZIP contains byte-equivalent canonical freeze/A-C3 records;
3. verifies the external A-C3 acceptance artifact against the A-C5 SHA-256/size descriptor;
4. verifies all original local A-C3 artifacts before Workbench projection;
5. rejects any protected Workbench product drift since A-C5;
6. composes the read-only Evidence Plane using the frozen local evidence identities;
7. runs `npm run build` over the production frontend;
8. serves that build from the same FastAPI Workbench application on loopback;
9. runs the real Chromium Playwright smoke;
10. records JSON/Markdown acceptance output.

If `workspace/node_modules` is absent, the runner deliberately fails with instructions to run `npm ci`; it does not modify frontend dependencies implicitly.

## Backend-only diagnostic

```powershell
python scripts\run_historical_workbench_release_smoke.py `
  configs\acceptance\historical_workbench_release_smoke.example.toml `
  --backend-only
```

This is useful for evidence/path diagnostics. In real mode the expected result is:

```text
contract_valid = true
browser_status = not_run
accepted = false
```

A backend-only run can never close HW-1.0-RS.

## Required real acceptance

```text
schema_version = finagent.historical-workbench-release-smoke.v1
stage = HW-1.0-RS
contract_valid = true
browser.status = passed
accepted = true
production_reserve_consumed = false
```

For the reviewed A-share no-alpha release:

```text
research_outcome = NO_ROBUST_FACTOR_FAMILY
market_bar_series_id = null
Strategy rows = 0
Portfolio/Execution = explicitly unavailable
FactorSeries = visible
```

These are valid product states, not missing-data workarounds.

## Fail-closed cases

The smoke rejects at least:

- invalid/tampered A-C5 `freeze_id`;
- non-frozen A-C5 evidence in real mode;
- A-C5 release SHA not ancestral to the smoke checkout;
- protected Workbench product changes after the A-C5 release;
- A-C3 acceptance artifact SHA/size different from A-C5;
- A-C5 ZIP whose embedded freeze/A-C3 record differs from the external canonical files;
- missing/tampered original A-C3 Factor/Strategy/robust/A4 evidence;
- Strategy/Factor/portfolio identity drift;
- browser financial recomputation becoming enabled;
- missing-evidence policy becoming inferential;
- no-alpha Strategy becoming populated or Portfolio/Execution evidence being fabricated;
- production frontend build failure;
- Chromium smoke failure.

If a Workbench product file actually changed after A-C5, do not weaken the drift check. Determine whether the change is a correctness hotfix that requires a new freeze package before accepting HW-1.0-RS.

# HW-1.0-RS — Historical Workbench 1.0 Post-freeze Release Smoke

Status: **implementation stage**

HW-1.0-RS is the final A-share Historical Workbench product smoke after the accepted A-C5 release freeze and before US-D0. It is deliberately not named A-C6: A-C5 remains the Historical v1.0 release identity, while this stage validates that the frozen evidence is still rendered correctly by the accepted Workbench product.

## Purpose

The stage validates this chain without rerunning financial research:

```text
A-C5 freeze_id + deterministic release ZIP
        ↓
exact embedded A-C3 acceptance identity
        ↓
verified original local A-C3 artifacts
        ↓
Workbench Evidence Plane projections
        ↓
production frontend build
        ↓
Chromium / Playwright release smoke
```

A-C5 ZIP remains an archival freeze package rather than a replacement data store. FactorSeries and StrategyDecisionSeries companion Parquet evidence stays in the original A-C3 evidence directory. HW-1.0-RS verifies those original paths against the SHA-256/size descriptors already frozen by A-C3/A-C5 before the Workbench may consume them.

## Authority boundary

HW-1.0-RS is read-only. It does not:

- rerun development research, A2.6 or A4;
- consume A5 production reserve;
- create or promote an Alpha strategy;
- enable PAPER;
- contact a broker;
- authorize live capital.

CI fixtures may establish `contract_valid=true`, but only a real frozen A-C5 release plus a passing production-build browser smoke can establish `accepted=true`.

`--backend-only` is diagnostic. In `real_frozen_release` mode it can never accept the product.

## Workbench product lineage

A-C5 `release_git_sha` is the product baseline. HW-1.0-RS may be implemented later without forcing a new freeze as long as the accepted Workbench product itself has not changed.

The protected product denominator includes:

```text
src/finagent/visualization
src/finagent/backtest/strategy_decision_series.py
src/finagent/research/factor_series.py
src/finagent/data/market_bar_series.py
src/finagent/domain/market_bars.py
workspace/src
workspace/package.json
workspace/package-lock.json
workspace/vite.config.ts
scripts/run_workspace.py
```

Changes to the HW-1.0-RS verifier, test specs or documentation do not alter that frozen product. A change to any protected Workbench product path after A-C5 fails closed and requires the release identity to be reconsidered rather than silently testing a different UI/product.

## Real no-alpha acceptance

The currently frozen A-share result is a reviewed `NO_ROBUST_FACTOR_FAMILY` terminal. HW-1.0-RS therefore treats no-alpha as the primary release UX rather than using a synthetic populated strategy to make the UI look complete.

Required backend state:

```text
StrategyDecisionSeries exists and binds exact A4/program/data identities
StrategyDecisionSeries rows/sessions/assets = 0
MarketBarSeries = unavailable
FactorSeries remains visible and nonempty
Portfolio cockpit = explicit no_portfolio
Portfolio/Execution V4 catalog does not fabricate validation evidence
linked analytics accepted
browser_recomputation = false
missing evidence policy = explicit_unavailable_not_inferred
```

Required browser behavior:

- Strategy renders a zero-row authoritative state rather than an error;
- Strategy says Market bars are unavailable and does not construct candles;
- Portfolio and Execution render explicit unavailable states;
- Factor Tear Sheet remains navigable and exposes rejected candidate/gate evidence;
- WorkbenchContext survives factor selection and page reload;
- Evidence catalog remains available;
- the embedded Evidence Plane does not expose command execution.

## Outputs

Default local outputs:

```text
reports/historical_workbench_release_smoke.json
reports/historical_workbench_release_smoke.md
```

A successful real result must end with:

```text
stage = HW-1.0-RS
contract_valid = true
browser.status = passed
accepted = true
production_reserve_consumed = false
```

After that result is recorded, the next development priority is US-D0 Dataset Provenance rather than another A-share-only feature stage.

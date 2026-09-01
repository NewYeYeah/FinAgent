# Testing and acceptance strategy

Tests establish software/data/contract correctness. They do **not** prove persistent Alpha or grant operational/live authority.

## 1. Test layers

### L0 — unit / property contracts
Pure domain/calculation behavior, identity, chronology, serialization, fail-closed validation and deterministic replay fixtures.

### L1 — component / adapter contracts
Provider adapters, Parquet/DuckDB query bounds, calendar/action semantics, application services, projections and optional-dependency behavior. External SDK/network behavior is mocked or fixture-driven in CI unless the stage explicitly defines a real local acceptance.

### L2 — subsystem acceptance
Historical research/program/portfolio pipelines, Workbench Evidence/Control boundaries, realtime replay/state transitions, broker-gateway contract behavior.

### L3 — real local evidence acceptance
Large/private/local datasets, real LLM providers, official MT5 terminal/broker data and other account/environment-specific evidence. These tests may not be reproducible in public CI; their reports/identities are persisted separately.

### L4 — release / operational gate
A release or authority transition binds the exact accepted Git/data/config/environment/evidence identities. Passing a lower layer never implies a higher authority.

## 2. Standard merge gate

Core merge gates normally include:

```text
pytest for changed core/subsystem scope
Ruff critical checks
focused mypy (strict for new modules)
compile/import smoke where relevant
package/dependency consistency
```

Frontend changes normally include:

```text
npm ci
npm run typecheck
npm run test
npm run build
npm run e2e  # when the changed surface has browser acceptance
```

The frontend developer/CI baseline is Node 22 unless a later explicit environment gate changes it.

## 3. Reproducibility gate

`.github/workflows/reproducibility.yml` is the canonical environment-reproduction gate. It is intentionally separate from broad compatibility CI.

**Ubuntu locked Python baseline**
- Python 3.11 from `.python-version`;
- uv 0.12.1, matching `[tool.uv].required-version`;
- `uv lock --check` against `pyproject.toml` + `uv.lock`;
- `uv sync --frozen --extra dev` from a fresh runner;
- installed dependency-graph check and core import smoke.

**Windows frontend / broker-prep baseline**
- the same locked Python 3.11 environment reproduced from `uv.lock`;
- Node 22 from `.nvmrc`;
- `npm ci` from `workspace/package-lock.json`;
- frontend typecheck, unit tests and production build.

The existing Python 3.11/3.12/3.13 matrix remains compatibility coverage over declared `pyproject.toml` ranges. It does not create a second resolution authority and does not replace the locked Python 3.11 baseline. Existing package CI continues to run `python -m pip check`; the reproducibility gate additionally checks the frozen uv environment.

ENG-0 does not install the official `MetaTrader5` SDK. SDK optional-dependency/import-safety and real terminal evidence are governed by `MT5-P0`.

## 4. Data-stage acceptance

US-S0/US-D3 tests must separate:
- source provenance/usage-rights decision;
- schema/identity verification;
- time/calendar/session certification;
- OHLC/gap/volume checks;
- corporate-action and symbol-lifecycle limitations;
- independent/broker reconciliation.

A source may be technically readable and still be `REFERENCE_ONLY` or `REJECTED`.

## 5. Agent experiment acceptance

Agent tests cover bounded tool/prompt/code behavior, repair/checkpoint/audit and hidden-reasoning privacy. Agent **value** is not a unit-test claim: US-A0 compares fixed manual/programmatic/Agent arms under a preregistered budget and records repeat-run evidence.

## 6. Statistical research acceptance

Formal intraday research must include overlap-aware chronology and inference. At minimum:
- purged/embargoed walk-forward where needed;
- HAC appropriate to horizon dependence;
- block/session bootstrap;
- frozen candidate denominator and multiplicity correction;
- training-frozen direction/selection;
- no evaluation feedback into the same adaptive search program.

Valid no-alpha terminals are accepted research outcomes.

## 7. MT5 / broker acceptance

CI tests the MT5 adapter contract and optional-platform behavior without credentials or live order authority. Real MT5 stages run locally on Windows against the exact terminal/server/account class defined by the stage.

Authority ladder:

```text
MT5-P0 read-only capability
MT5-D0 read-only market reference
MT5-M1 read-only/realtime gateway
MT5-E1 demo/PAPER mutation
MT5-O1 reconciliation/recovery/safety
MT5-L0 separate live-capital acceptance
```

A successful earlier stage cannot call a later mutation API as part of its acceptance.

## 8. Workbench acceptance

Browser code consumes verified evidence/state projections. Tests explicitly guard:
- Evidence Plane GET-only behavior;
- Control authority ceiling;
- no browser financial recomputation;
- unavailable evidence remains unavailable;
- URL-backed WorkbenchContext stability;
- bounded row reads and complete server-side aggregates;
- source/broker-specific logic stays out of React.

## 9. Historical A-share release reproduction

The historical A-C4/A-C5/HW-1.0-RS procedure is consolidated in [`../releases/ashare-historical-v1.md`](../releases/ashare-historical-v1.md). It is release history, not the global current test strategy.

## 10. Documentation gate

```bash
python scripts/check_docs.py
python tests/test_docs_governance.py
```

The active docs tree must contain one stage authority and one current plan, with no versioned roadmap/current-plan/stage-changelog sprawl.

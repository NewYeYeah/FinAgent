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

## 2. Standard merge gate and CI routing

FinAgent uses two CI lanes rather than making every pull request wait for every historical/compatibility surface.

### Pull-request fast lane

A PR must run checks that can directly invalidate the changed surface:

```text
Python 3.11 cross-layer core integration smoke
project-wide critical Ruff checks
stage/subsystem focused pytest
focused Ruff + strict mypy for new modules
compile/import smoke where relevant
docs/release/source gates only when their paths change
```

The generic PR smoke deliberately does **not** execute the entire repository. Changed subsystems own deeper validation through path-scoped focused workflows. For example, U.S. minute changes run the U.S. minute/source gates; A2.6 and historical Research UI changes run their own gates.

Historical focused workflows use PR path filters. A2.6 and the historical Research UI therefore do not block a U.S. minute/calendar PR unless their own code/test/dependency/workflow paths changed.

Pure documentation PRs may skip the generic Python package workflow when documentation governance owns the changed surface.

### Main integration / compatibility lane

After merge, every push to `main` retains the broader active-code safety net:

```text
Python 3.11 / 3.12 / 3.13 active-suite pytest matrix
Windows Python 3.11 active-suite pytest
historical A2.6 regression
historical Research UI regression
coverage floor over the active suite
historical targeted lint/mypy surfaces
package build + dependency consistency
```

This separation reduces PR queue/merge latency without deleting compatibility or currently relevant historical-surface regression coverage. A focused PR gate must not be removed merely because the main lane exists; the main regression is a backstop, not a substitute for changed-surface validation.

### Frozen Historical release reproduction is not the active suite

A-share Historical v1.0 has its own immutable release/tag/evidence boundary. The following tests reproduce historical A-C4/A-C5 assumptions and are intentionally excluded from the generic active-suite pytest/coverage lane:

```text
tests/test_initial_requirement_compliance_ac4.py
tests/test_ashare_historical_v1_freeze_ac5.py
tests/test_ashare_historical_v1_freeze_lineage.py
```

They depend on historical plan references and/or historical Git lineage that are no longer part of the active DOC-0 tree. They remain release-reproduction material and are exercised only by the dedicated Historical workflows/release procedure with the history depth and artifacts that those contracts require. Their failure under a shallow generic checkout is not treated as a current U.S./MT5 product regression.

Do not silently delete or rewrite frozen release evidence merely to make the active suite green. If the Historical release itself must be re-verified, use its dedicated release procedure and exact historical identities.

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

The Python 3.11/3.12/3.13 matrix remains compatibility coverage over declared `pyproject.toml` ranges, but it runs in the main integration lane rather than blocking every PR. It does not create a second resolution authority and does not replace the locked Python 3.11 baseline. Package/dependency consistency is likewise retained on main integration; the reproducibility gate additionally checks the frozen uv environment.

ENG-0 does not install the official `MetaTrader5` SDK. SDK optional-dependency/import-safety and real terminal evidence are governed by `MT5-P0`.

## 4. Data-stage acceptance

US-S0/US-D3 tests must separate:
- source provenance/usage-rights decision;
- schema/identity verification;
- time/calendar/session certification;
- OHLC/gap/volume checks;
- corporate-action and symbol-lifecycle limitations;
- independent/broker reconciliation.

A source may be technically readable and still be `REFERENCE_ONLY` or `REJECTED`. A locally admitted `REFERENCE_ONLY` source remains limited to the explicitly accepted scope and cleaning policy.

## 5. Agent experiment acceptance

Agent tests cover bounded tool/prompt/code behavior, repair/checkpoint/audit and hidden-reasoning privacy. Agent **value** is not a unit-test claim: US-A0 compares fixed manual/programmatic/Agent arms under a preregistered budget and records repeat-run evidence.

US-R3 expansion additionally requires stateful slot/attempt accounting, concurrent reservation and crash/resume tests, strict payload rejection, split-scoped tool dispatch and memory isolation, plus provider quota exhaustion without replacing candidate slots. Test enforcement using a fake provider and instrumented denied data/tool access, not only static flags or import scans. A data-blind LLM arm isolates the benefit of development feedback from the benefit of formula generation. Compare matched per-run evaluation budgets and report uncertainty; three runs are pilot evidence.

## 6. Statistical research acceptance

Formal intraday research must include overlap-aware chronology and inference. At minimum:
- purged/embargoed walk-forward where needed;
- HAC appropriate to horizon dependence;
- block/session bootstrap;
- frozen candidate denominator and multiplicity correction;
- training-frozen direction/selection;
- no evaluation feedback into the same adaptive search program.

Valid no-alpha terminals are accepted research outcomes.

US-R3 panel acceptance must include perturbation tests proving invalid asset values cannot influence valid peers, valid-input breadth enforcement, causal regime-mask lineage, no future mutation effect, missing-clock/session handling and partition/batch parity. These tests precede new financial evaluation.

For adaptive research, freeze search rules and trial budgets before development feedback; freeze realized candidates and the training/selection/portfolio rule before outer or final evaluation. Preserve the whole trial ledger and preregister the appropriate multiple-testing procedure; a count of final survivors alone does not correct adaptive search bias. Session/block resampling must preserve the relevant cross-asset dependence. Power and endpoint choices precede final outcomes, and broker-neutral costs include overlapping positions, delayed execution and stress assumptions.

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

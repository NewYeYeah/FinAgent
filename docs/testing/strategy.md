# Testing and acceptance strategy

Testing must prove the boundary that is actually changing. FinAgent distinguishes software correctness, research evidence, PAPER operations and live authority; a lower-level pass never implies a higher one.

## 1. Test layers

### T0 — unit / deterministic contract

Pure calculations, serialization, identity, chronology, FactorGraph validation, market-state transforms, allocator logic and fail-closed behavior.

### T1 — component / adapter

Data adapters, DuckDB/Parquet queries, LLM/provider adapters, application services, Workbench projections, realtime source/projection behavior and optional dependencies. External systems are fixture/mocked unless the stage requires a real local acceptance.

### T2 — vertical subsystem

A coherent research/product slice from its admitted input through the real internal interface:

```text
MarketState → Agent tool → evaluation → projection
FactorLibrary → allocator → historical economics
Agent runtime → tool/evaluator ledger → Research Console
replay → strategy → projection
```

### T3 — financial research acceptance

Development or independent statistical/economic evaluation over real admitted data. The protocol owns chronology, costs, multiplicity/search accounting and terminal meaning.

### T4 — product/browser acceptance

TypeScript/unit/build plus browser task flows against real or authoritative fixture projections. Workbench 2.0 additionally requires task-based human usability on real available artifacts.

### T5 — broker/PAPER acceptance

Real target demo/PAPER environment: broker/source identity, orders/deals/positions/account reconciliation, restart/recovery, stale data, safety and multi-session soak.

### T6 — live-capital acceptance

Separate human-governed checks for the exact account/capital/risk/operational envelope.

## 2. Stage-specific evidence policy

### R3-CLOSE

Run focused FactorGraph/evaluator/Agent runtime tests needed to prove reusable R3 capability. Do not keep R3 open merely to create another evidence artifact.

### R4 exploration

Required:

- causal feature/model tests;
- no-future-mutation tests for MarketState/allocators;
- development split/tool-scope enforcement;
- complete trial/budget ledger tests;
- matched deterministic/Agent experiment accounting;
- focused historical economics regression.

R4 is adaptive development. Its performance is not independent Alpha acceptance.

The first MarketState/FactorLibrary slice is exercised by
`tests/test_market_state.py`, `tests/test_factor_library.py` and
`tests/test_r4_research_slice.py`. These cover train-only normalization/mapping,
future OHLCV and label-column perturbations, probability/availability checks,
missing days, nonconvergence, JSON replay, real shared-DAG metrics, lifecycle,
provenance, deterministic persisted results and read-only CLI inspection.
`.github/workflows/r4-market-state-factor-library.yml` runs the slice on Linux
and Windows with strict focused typing/lint plus FactorGraph/economics/R2-regime
predecessors. Install with `uv sync --frozen --extra dev --extra adaptive-research`.

The first slice fits one declared historical window and evaluates complete later
sessions. Labels never train a model, and all diagnostic horizons/holdings stay
inside evaluation sessions, so no labels cross the train boundary. Its overlapping
intraday diagnostics have no significance claims.

The deterministic allocator slice is covered by `tests/test_factor_allocators.py`
and `tests/test_adaptive_walkforward.py`, with the existing R2 Parquet contract
extended to 33 controlled sessions in `tests/adaptive_allocator_fixture.py`.
Tests perturb future returns, later folds and unused label columns; verify exact
one-hot/soft-state mixtures, common-support normalization/rescaling invariance,
train-only Ridge coefficients, delayed releases, complete weight series, replay,
registry restoration and the standalone CLI. Missing sessions and failed later
folds preserve denominators/completed evidence.

Each fold fits GMM on a frozen TRAIN prefix, avoiding retrospective state labeling
of training decisions. Ridge features use only previously completed sessions and
its targets must mature by TRAIN end. All delayed IC labels/holdings stay within
complete sessions, with performance released at close before the next evaluation
session opens; explicit clock assertions prove this boundary without an extra
purge framework. Overlapping intraday IC is descriptive, not independent evidence.
`.github/workflows/r4-deterministic-allocators.yml` runs focused and relevant
MarketState/FactorGraph/R3-economics/R2-regime regressions on Linux and Windows,
plus lint, strict typing and documentation governance.

### R5 confirmation

Required:

- exact frozen `AdaptiveStrategySpec` identity;
- proof that confirmation inputs were not exposed to R4 under the accepted definition;
- preregistered primary endpoint/cost/stopping rule;
- chronology-aware HAC/block/session inference as required;
- correct multiplicity accounting for the frozen strategy family/endpoints;
- immutable terminal result.

### Workbench 2.0

Required:

```text
npm typecheck
Vitest
production build
Playwright for changed critical flows
Python projection/API focused tests
no browser financial recomputation tests
WorkbenchContext/deep-link tests
Agent stream reconnect/resume behavior
human task-based usability on real artifacts before final stage acceptance
```

Automated browser smoke alone is not sufficient for the new interaction goal.

### PAPER

Use deterministic replay for failure-mode coverage and real MT5 demo/PAPER for broker behaviors that require broker mutation.

Acceptance must exercise:

- normal signal/order/fill;
- no-signal/cash;
- stale/delayed source;
- disconnect/reconnect;
- restart/recovery;
- reject/cancel/expire where supported;
- duplicate/out-of-order events;
- partial-fill path via real environment or deterministic broker fixture;
- reconciliation drift;
- kill switch;
- end-of-session policy;
- multi-session soak.

## 3. CI philosophy

Do not make every PR run every historical workflow.

A PR runs:

1. documentation governance if docs/status/planning paths changed;
2. focused unit/component tests for changed modules;
3. the vertical subsystem test for the capability being changed;
4. strict typing/lint for new/touched code where practical;
5. frontend gates when frontend code changes;
6. broader compatibility/regression on main and on PRs that actually touch the shared boundary.

Frozen historical release reproduction remains separate from active research/product CI. The historical Workbench product-identity regression binds the documented accepted closure commit, not the moving R4 HEAD; isolated worktree tests continue to prove that real frozen-release smoke rejects product drift. Do not recreate obsolete active docs simply to satisfy an old release test.

## 4. Reproducible environment

Canonical developer baseline remains:

```text
Python 3.11
uv 0.12.1
uv.lock
Node 22
workspace/package-lock.json
```

Compatibility CI may exercise additional Python/platform combinations, but it does not create another dependency authority.

## 5. Agent tests

Agent tests must verify behavior, not declarations:

- strict typed action parsing;
- denied tool/data access;
- source/split/evaluator binding;
- trial and budget reservation;
- duplicate/repair retention;
- restart/idempotence;
- provider timeout/usage accounting appropriate to the admitted adapter;
- run-local memory scope;
- no hidden-reasoning persistence;
- no access to sealed R5 evidence.

Agent **value** is an experiment result, never a unit-test assertion.

R4 Controller acceptance runs `tests/test_r4_controller.py`, `tests/test_r4_controller_boundaries.py` and `tests/test_r4_research_control.py`. Scripted providers actually cross the existing runtime/provider/ledger boundary, run real FactorGraphs over Parquet and the shared numerical evaluator, and project every explicit action through AgentAuditStore and Workbench APIs/SSE. Regressions cover static rejection of post-TRAIN definitions, current-time retrospective proposals, frozen visible-history/definition identity, unavailable results, duplicates, failed/negative trials, budget denial, timeout, resume/audit mismatch and authority rejection. Existing R3 runtime and #176/#177 tests remain unchanged.

Console component acceptance is `cd workspace && npm test`; `npm run build` includes TypeScript validation. After building, `npx playwright test --config playwright.research.config.ts` starts the opt-in real scripted fixture server and checks objective, typed action sequence, new proposal provenance, all five economic arms, factor set, allocator, remaining budget and explicit no-candidate/authority display. The browser test makes no mocked API responses. The standard production Control Plane remains provider-unavailable until a host explicitly supplies an admitted service. These fixtures are not a financial campaign or independent evidence.

## 6. Statistical rules

Use methods appropriate to overlapping/serially dependent intraday outcomes. The exact R5 protocol is frozen per strategy, but normal tools include:

- purged/embargoed walk-forward where holdings/labels overlap boundaries;
- HAC/Newey-West where relevant;
- session/block bootstrap;
- multiplicity correction over the actual searched/frozen family;
- training-only direction/model/state fitting;
- cost/delay sensitivity.

Multiple-testing correction does not repair actual leakage.

## 7. Realtime rules

Replay should reproduce semantic state deterministically from the same canonical event sequence. Tests cover duplicate provider IDs, different-content conflicts, sequence regressions, stale/future timestamps and restart reconstruction.

A connected FX or delayed feed may test transport/runtime behavior only when the tested behavior is genuinely market-invariant. It does not substitute for target U.S. CFD broker/PAPER evidence.

## 8. Documentation governance

Run:

```bash
python scripts/check_docs.py
python -m pytest -q tests/test_docs_governance.py
```

The checker enforces one current plan, one compact status authority, required stage plans, a small active guide set, valid internal links and the canonical Agent onboarding entry.

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

Frozen historical release reproduction remains separate from active research/product CI. Do not recreate obsolete active docs simply to satisfy an old release test.

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

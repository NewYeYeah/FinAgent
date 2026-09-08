# Testing and acceptance strategy

Testing must prove the boundary that is actually changing. FinAgent distinguishes software correctness, research evidence, PAPER operations and live authority; a lower-level pass never implies a higher one.

## 1. Test layers

### T0 — unit / deterministic contract

Pure calculations, serialization, identity, chronology, FactorGraph validation, market-state transforms, allocator logic and fail-closed behavior.

### T1 — component / adapter

Data adapters, DuckDB/Parquet queries, LLM/provider adapters, application services, Workbench projections, realtime source/projection behavior and optional dependencies. External systems are fixture/mocked unless the stage requires a real local acceptance.

### T2 — vertical subsystem

A coherent research/product slice from its admitted input through the real internal interface.

### T3 — financial research acceptance

Development or independent statistical/economic evaluation over real admitted data. The protocol owns chronology, costs, multiplicity/search accounting and terminal meaning.

### T4 — product/browser acceptance

TypeScript/unit/build plus browser task flows against real or authoritative fixture projections. Workbench 2.0 additionally requires task-based human usability on real available artifacts.

### T5 — broker/PAPER acceptance

Real target demo/PAPER environment: broker/source identity, orders/deals/positions/account reconciliation, restart/recovery, stale data, safety and multi-session soak.

### T6 — live-capital acceptance

Separate human-governed checks for the exact account/capital/risk/operational envelope.

## 2. Stage-specific evidence policy

### R4 exploration

Required:

- causal feature/model tests;
- no-future-mutation tests for MarketState/allocators;
- development split/tool-scope enforcement;
- complete trial/budget ledger tests;
- matched deterministic/Agent experiment accounting;
- focused historical economics regression.

R4 is adaptive development. Its performance is not independent Alpha acceptance.

The MarketState/FactorLibrary slice is exercised by `tests/test_market_state.py`, `tests/test_factor_library.py` and `tests/test_r4_research_slice.py`. The deterministic allocator slice is covered by `tests/test_factor_allocators.py` and `tests/test_adaptive_walkforward.py`. The bounded Controller uses `tests/test_r4_controller.py`, `tests/test_r4_controller_boundaries.py` and `tests/test_r4_research_control.py`. These remain software/fixture acceptance, not real financial-campaign evidence.

R4 provider-admission acceptance is `python -m pytest tests/test_r4_provider_admission.py`. CI uses fixture transports only; development CI must never repeat a real provider probe.

R4 campaign admission/protocol acceptance is `python -m pytest tests/test_r4_campaign_freeze.py`; guarded execution-operator acceptance is `python -m pytest tests/test_r4_campaign_operator.py`. The suites prove the current `r4-matched-v3` version authority, exact four-factor-set/five-allocator Primary reachability, exhaustive-oracle contract, ResearchLedger resource authority, Candidate Gate independence, Discovery isolation, guarded execution bindings, immutable completed-result replay and no automatic retry/fallback/force/reset behavior. Synthetic tests may prove host semantics; they do not regenerate the accepted real campaign result.

### Accepted offline R4 matched-campaign evidence

The first real matched campaign has now completed in a separately governed Offline Testing Phase and was independently reviewed as `R4_RESULT_ACCEPTED`. The repository-safe [campaign result record](../../configs/research/r4_matched_v3_result/README.md) references CampaignResult `r4-campaign-result-d32ec253d62eb4f9349896b0`, SHA256 `5f9cb2b687f5b5750255c4d91e6db273fdf2577a8ce71f33365cddf19789c8ac`.

Accepted offline acceptance facts:

- exactly one real campaign invocation; no automatic retry or rerun;
- all seven required runs completed;
- CampaignResult identity/hash: PASS;
- 44/44 bound artifact digests: PASS, zero missing/mismatch;
- provider usage verification: PASS for all six real Agent runs;
- post-run freeze integrity: PASS;
- post-run exact verification: PASS;
- ResearchAdmission and Git/environment integrity: PASS;
- accepted host terminal: `NO_ADAPTIVE_CANDIDATE`;
- AgentValue: `INCONCLUSIVE`;
- `system_failure = false`.

The economic-completeness finding is part of acceptance, not a test failure. Deterministic search structurally contained all 20 Primary strategy keys, but 0/20 had complete required three-fold economic evidence: `evaluable_folds = 0/3` for every deterministic strategy and unavailable sessions ranged from 39 to 64. Therefore no deterministic economic oracle existed and Agent value remained `INCONCLUSIVE`. This cannot be restated as proof that all strategies lost money or that Agent economic performance was negative.

Discovery-03 ending `SLOT_ATTEMPTS_EXHAUSTED` is an admitted campaign-run terminal, not infrastructure `SYSTEM_FAILURE`. The accepted result also retains 62 rejected Agent actions overall, including 44 in discovery-03 and 43 `candidate_not_proposed_in_run` rejections there. That limitation belongs in research/operational evidence and backlog, not in a weakened CI contract.

### Separation of CI and offline evidence

GitHub CI validates implementation contracts, repository evidence packaging, JSON/documentation consistency and governance. It does **not** run the real provider or a live matched campaign. Offline campaign evidence validates the private-data/provider execution that cannot and must not be reproduced in CI.

No GitHub workflow should be added that calls the real provider, reads campaign credentials, recreates the accepted freeze, accesses private source artifacts or executes `r4_campaign.py run`. Evidence-only development checks identities/hashes and repository-safe records only.

### R5 confirmation

R5 is conditional on an R4 AdaptiveStrategy candidate. The accepted first R4 cycle produced `candidate_id = null`, so R5 is not started. If a future versioned R4 cycle produces a candidate, R5 requires exact frozen strategy identity, genuinely independent evidence, preregistered primary endpoint/cost/stopping rule, appropriate chronology-aware inference and immutable terminal result.

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

Use deterministic replay for failure-mode coverage and real MT5 demo/PAPER for broker behaviors that require broker mutation. Acceptance must cover normal/no-signal behavior, stale/disconnected sources, restart/recovery, broker rejects/cancels/expiry where supported, duplicate/out-of-order events, partial fills, reconciliation drift, kill switch, end-of-session policy and multi-session soak.

## 3. CI philosophy

Do not make every PR run every historical workflow.

A PR runs:

1. documentation governance if docs/status/planning paths changed;
2. focused unit/component tests for changed modules;
3. the vertical subsystem test for the capability being changed;
4. strict typing/lint for new/touched code where practical;
5. frontend gates when frontend code changes;
6. broader compatibility/regression on main and on PRs that actually touch the shared boundary.

Frozen historical release reproduction remains separate from active research/product CI. Evidence-only R4 result recording should trigger only the repository workflows selected by normal path filters; it must not add meaningless executable changes merely to trigger R4 workflows.

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

## 5. Agent tests and authority

Agent tests verify behavior, not declarations: strict typed action parsing, denied access, source/split/evaluator binding, trial/budget reservation, duplicate/repair retention, restart/idempotence, provider timeout/usage accounting, run-local memory scope, no hidden-reasoning persistence and no access to sealed R5 evidence.

Agent **value** is an experiment result, never a unit-test assertion about actual economic value. Unit tests prove the preregistered host gate is reachable, deterministic and uses authoritative evidence. The accepted real campaign supplies the result: `INCONCLUSIVE` under incomplete deterministic economic evidence, while the independent Candidate Gate validly emits `NO_ADAPTIVE_CANDIDATE`.

## 6. Statistical rules

Use methods appropriate to overlapping/serially dependent intraday outcomes. Normal tools include purged/embargoed walk-forward where required, HAC/Newey-West, session/block bootstrap, multiplicity correction over the actual searched family, training-only fitting and cost/delay sensitivity. Multiple-testing correction does not repair actual leakage.

## 7. Realtime rules

Replay should reproduce semantic state deterministically from the same canonical event sequence. Tests cover duplicate provider IDs, different-content conflicts, sequence regressions, stale/future timestamps and restart reconstruction. A connected feed may test only genuinely market-invariant transport/runtime behavior and does not substitute for target U.S. CFD broker/PAPER evidence.

## 8. Documentation governance

Run:

```bash
python scripts/check_docs.py
python -m pytest -q tests/test_docs_governance.py
```

The checker enforces one current plan, one compact status authority, required stage plans, a small active guide set, valid internal links and the canonical Agent onboarding entry.

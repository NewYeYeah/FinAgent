# FinAgent agent onboarding

This file is the canonical entry point for an AI or developer who has not worked on FinAgent before. It contains **how to recover project context**, not a second copy of project status.

## 1. Read order

Read these sources in order before planning or changing code:

1. `docs/status.toml` — current stage, current authority and compact accepted baseline.
2. `docs/development/current-plan.md` — end-to-end roadmap and stage ordering.
3. the current stage file named by `stage_plan` in `docs/status.toml`.
4. `docs/development/backlog.md` — unresolved limitations, debt and intentionally deferred work.
5. `docs/architecture/overview.md` and `docs/architecture/decisions.md` — current implementation boundaries.
6. source code and tests for the subsystem being changed.
7. `docs/development/history.md` only when predecessor decisions or prior negative results matter.
8. operator/user guides only for the workflow being executed.

Do not start by reading old pull requests, old stage guides or release history. Git/PR history explains *why* the repository arrived here; it does not override active status, plan or code.

## 2. Five-minute context reconstruction

Before producing a plan, record:

```text
branch / commit inspected
current_stage
current_stage_status
next_stage
stage_plan
Alpha authority
PAPER authority
live-capital authority
```

Then answer four questions from the current stage plan:

```text
What is the stage trying to prove or deliver?
What is already implemented and should be reused?
What remains open?
What exact condition ends the stage?
```

If docs and executable behavior disagree, report the mismatch. Source/tests own implementation truth; `docs/status.toml` owns project-stage truth.

## 3. Current architecture map

Route work to the existing subsystem before inventing a new one:

```text
src/finagent/data + domain       data contracts, clocks, adapters, bounded datasets
src/finagent/research            factors, research protocols, statistical evaluation
src/finagent/agents              LLM/Agent runtime and controlled research capabilities
src/finagent/models              Alpha/Risk model interfaces
src/finagent/portfolio           portfolio construction and constraints
src/finagent/backtest            deterministic historical strategy/execution evidence
src/finagent/application         typed application/control services
src/finagent/realtime            canonical events, replay, streaming sources/projections
src/finagent/operations          PAPER, approval, reconciliation, safety and stores
src/finagent/brokers             broker adapters including MT5 boundaries
src/finagent/visualization       Workbench projections/APIs
workspace                        React/Vite Workbench
```

A new abstraction is justified only when existing ownership cannot express the requirement cleanly.

## 4. Non-negotiable invariants

1. **Chronology is causal.** `event_time`, `available_at`, session boundaries and label horizons remain explicit. Future labels never become features.
2. **Agent and deterministic authority are different.** Agent may choose research directions, candidates, factor sets, allocators and experiment budget inside an admitted development scope. Deterministic code owns calculation, statistical gates, portfolio/account truth, safety and broker mutation.
3. **Adaptive development is not independent confirmation.** Any data exposed to Agent feedback is development data. R5/final evidence must remain independent under its frozen protocol.
4. **Research, Alpha, PAPER and live-capital acceptance are separate states.** Never infer one from another.
5. **Research instruments and broker instruments are separate identities.** Similar ticker text is not sufficient mapping evidence.
6. **No silent provider fallback.** Provider capability, account entitlement and FinAgent adapter capability are separate facts.
7. **No browser financial authority.** React may select, aggregate for presentation and visualize admitted rows; it may not invent missing financial/statistical facts.
8. **No hidden chain-of-thought persistence.** Persist explicit hypotheses, tool actions, experiment results and decisions, not hidden reasoning.
9. **No result-dependent threshold weakening.** A failed research result is a valid result.
10. **No Tick/LOB dependency in the active roadmap.** Current research is minute-OHLCV based; microstructure work is intentionally deferred until authoritative finer data exists.
11. **Reuse before rebuild.** Prefer mature open-source components and existing FinAgent modules over bespoke infrastructure. Migration itself must have measurable value.
12. **Realtime UI follows canonical PAPER state.** Do not build a mock trading terminal ahead of the underlying broker/reconciliation/safety state machine.

## 5. Development workflow

For a normal implementation task:

1. identify the stage deliverable affected;
2. inspect the existing implementation and tests;
3. list reusable internal and open-source components;
4. choose the smallest coherent **vertical slice** that changes real research/product capability;
5. implement calculation/authority in Python core before presentation-only code;
6. add focused tests that prove the slice, plus broader regression only where the changed boundary can invalidate it;
7. update the current stage plan only when scope/exit criteria changed;
8. update `docs/development/backlog.md` when a limitation is created/resolved;
9. update `docs/development/history.md` only when a durable milestone or negative research conclusion is established;
10. update `docs/status.toml` only when stage/authority/capability state actually changes.

Do not create a new roadmap, versioned current plan, per-PR stage guide or stage changelog.

## 6. Pull-request sizing

PR count is not a target. Prefer one inspectable vertical capability over either extreme:

```text
bad: contract-only -> cache-only -> statistics-only -> orchestration-only PR chain
bad: one mega-PR that changes unrelated research, runtime, UI and authority boundaries

good: MarketState model + projection + Agent tool + focused UI + tests
```

Split when there is a genuine independent risk/authority boundary, a reviewable dependency, or a change too large to verify as one unit. Do not split only to preserve old stage numbering.

## 7. Documentation ownership

| Question | Canonical source |
| --- | --- |
| What is current? | `docs/status.toml` |
| What is the overall route? | `docs/development/current-plan.md` |
| What exactly is planned for a stage? | `docs/development/stages/*.md` |
| What has already happened that still matters? | `docs/development/history.md` |
| What remains unresolved? | `docs/development/backlog.md` |
| How does the system work? | `docs/architecture/overview.md` |
| What design rules are active? | `docs/architecture/decisions.md` |
| How is acceptance tested? | `docs/testing/strategy.md` |
| How do I operate something? | `docs/guides/*.md` |
| What did a frozen release prove? | `docs/releases/*.md` |
| What changed in one implementation? | Git commit / PR |

Run `python scripts/check_docs.py` after documentation changes.

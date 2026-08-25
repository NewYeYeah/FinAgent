# FinAgent Roadmap Rebaseline — After Phase 5

Date: 2026-08-25

## Completed foundation

```text
Phase 0.5  Domain contracts
Phase 1    PIT numerical Quant Kernel
Phase 2    Validation/execution clocks/model governance
Phase 2.5  Nested validation and multiple-testing controls
Phase 3A   Governed Agent tool boundary
Phase 3B   Deterministic research Agent
Phase 3C   Provider-neutral LLM planning
Phase 3D   Restricted generated feature code
Phase 3.5  Real generated-feature PIT research
Phase 4    Alpha/risk/portfolio hardening
Phase 4.5  Low-permission Portfolio Supervisor
Phase 5    Durable paper/shadow operations and reconciliation
```

The project now spans research, deterministic portfolio construction and a non-live operational loop. Additional Agent-framework complexity is still not the critical path.

## Phase 5.5 — Structured Research Memory and Hypothesis Evolution

Goal: convert accumulated registries into usable structured research memory without allowing historical winners to silently expand current research budgets.

Priority work:

```text
feature/model lineage queries
hypothesis -> artifact -> experiment -> result graph
failure taxonomy
experiment/factor similarity
duplicate-hypothesis detection
bounded research summaries
evidence-aware experiment-budget recommendations
paper/shadow outcome linkage back to research artifacts
```

Vector retrieval should remain optional for unstructured papers/reports; structured experiment state should stay relational and auditable.

## Phase 6 — Operational Hardening, then Optional Graph Orchestration

The next major engineering question is not automatically “adopt LangGraph”. First measure Phase 5 operational gaps.

Potential deterministic operational hardening:

```text
richer exchange/security master
multi-currency cash and FX accounting
broker-neutral order state machine refinements
persistent approval expiry/revocation
session-level PnL and exposure journals
paper incident metrics / SLOs
more complete corporate actions
spread/impact calibration
shadow acceptance criteria
```

Graph orchestration becomes justified only if real workflows require:

```text
long-running resumable branches
parallel research tasks
multi-hour human checkpoints
complex provider retry/recovery
```

If adopted, it remains an adapter around frozen domain/control-plane contracts.

## Phase 7 — Optional Advanced Research

Possible later work:

```text
regime/change-point models
ML alpha models
Bayesian optimization inside fixed experiment families
text/news/filing features
RL/MPC portfolio research
multi-Agent review
```

Direct LLM or RL control of live portfolio weights remains outside the default objective.

## Live-capital gate

Phase 5 does not imply live readiness.

Before any live broker milestone, require at minimum:

```text
sustained paper/shadow runtime
documented reconciliation error rate
documented order-idempotency behavior
kill-switch drills
restart-recovery drills
corporate-action test coverage
cost-model calibration evidence
operational alerting/runbooks
explicit human sign-off
```

A future live adapter should implement the same broker-neutral operational contracts rather than bypassing them.

## Project success criterion

A novel hypothesis should be translated into reproducible PIT evidence, pass statistical governance, produce deterministic alpha/risk/portfolio targets, survive supervised paper execution and reconciliation, and remain auditable end-to-end.

The Agent is a research and supervision multiplier. Financial state remains owned by deterministic infrastructure.

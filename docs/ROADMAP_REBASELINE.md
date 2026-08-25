# FinAgent Roadmap Rebaseline — After Phase 5.5

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
Phase 5.5  Structured evidence memory and hypothesis evolution
```

The project now spans governed research, deterministic portfolio construction, paper/shadow operation and end-to-end structured lineage. Additional Agent-framework complexity is still not the critical path.

## Phase 6 — Operational Hardening Before Orchestration

Phase 5 and Phase 5.5 make the next priority clearer: harden the operational substrate and define measurable paper/shadow acceptance criteria before adding live brokers or more autonomous Agents.

Priority deterministic work:

```text
exchange/security master and richer session calendars
multi-currency cash and FX accounting
broker-neutral order state refinements
persistent approval expiry/revocation
session-level PnL/exposure journals
paper incident metrics, SLOs and alerts
more complete corporate actions
spread/nonlinear impact calibration
shadow acceptance statistics and promotion gates
memory linkage to operational incidents and acceptance evidence
```

### Phase 6A — operational journals and acceptance metrics

Recommended first slice:

```text
SessionJournal
ExposureJournal
OperationalMetricSnapshot
PaperAcceptancePolicy
PaperAcceptanceReport
```

The acceptance policy should consume durable evidence such as order-idempotency errors, reconciliation incidents, restart recovery, kill-switch drills, fill/cost stability and shadow divergence. It should not use a single PnL threshold as a live-readiness proxy.

### Phase 6B — accounting and market-master hardening

Add multi-currency ledger semantics, FX translation, security-master identities, corporate-action coverage and exchange-specific sessions before any live adapter.

### Phase 6C — orchestration only if measured pain justifies it

Graph orchestration is optional. It becomes justified only if actual workflows require:

```text
long-running resumable branches
parallel research tasks
multi-hour human checkpoints
complex provider retry/recovery
```

If adopted, LangGraph or another workflow engine remains an adapter around existing domain/control-plane contracts. It must not become the owner of portfolio or broker state.

## Phase 7 — Optional Advanced Research

Possible later work:

```text
regime/change-point models
ML alpha models
Bayesian optimization inside fixed experiment families
text/news/filing features
RL/MPC portfolio research
multi-Agent review
optional embedding retrieval for unstructured literature
```

Structured experiment state and evidence lineage remain relational even if vector retrieval is introduced for documents.

## Live-capital gate

Phase 5.5 does not imply live readiness.

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
paper acceptance report under pre-registered policy
explicit human sign-off
```

A future live adapter should implement the same broker-neutral operational contracts rather than bypassing them.

## Project success criterion

A novel hypothesis should be translated into reproducible PIT evidence, pass statistical governance, produce deterministic alpha/risk/portfolio targets, survive supervised paper execution and reconciliation, and remain auditable end-to-end through structured memory.

The Agent is a research and supervision multiplier. Financial state and evidence validity remain owned by deterministic infrastructure.

# FinAgent 1.0 Release Scope

Date: 2026-08-25

## Release objective

FinAgent 1.0 closes the initial architecture-building cycle. The stable scope is:

```text
governed quantitative research
+ deterministic portfolio construction
+ supervised paper/shadow operations
+ structured evidence lineage
+ measurable operational acceptance
```

Version 1.0 does **not** claim live-broker or live-capital readiness.

## Function-necessity decision

Before freezing 1.0, the remaining roadmap items were re-evaluated according to one question: does the missing function prevent the current paper/shadow system from being operated, tested, audited and judged against a pre-registered reliability policy?

### Required for 1.0 and implemented

1. **Operational journal** — required. Existing paper state was durable, but release evidence still needed a period-level summary of sessions, orders, fills, reconciliations, kill-switch events, drills and incidents.
2. **Paper acceptance gate** — required. A stable release needs an explicit answer to "what evidence is sufficient to call this paper/shadow deployment operationally acceptable?" The answer cannot be a single PnL or Sharpe threshold.
3. **Restart and kill-switch drill evidence** — required. Phase 5 implemented the mechanisms; 1.0 records drill outcomes and includes them in the acceptance policy.
4. **Incident/SLO evidence** — required. Idempotency failures and other critical incidents must be durable evidence, not comments in a runbook.
5. **Approval expiry and revocation** — required. Phase 5 bound human approval to an immutable snapshot, but a long-lived approval also needs a bounded lifetime and an explicit revocation path.
6. **Formal 1.0 documentation and test instructions** — required. The README now describes the architecture, supported workflows, installation, testing, safety invariants and operational acceptance procedure.

## Explicitly deferred from 1.0

The following items are useful but are not required for the stable paper/shadow scope:

```text
live broker adapters / credentials
multi-currency cash and FX ledger
full exchange/security-master feeds
full corporate-action accounting
broker-specific production order semantics
nonlinear institutional market-impact model
LangGraph or other graph orchestration
multi-Agent debate/review
vector database as evidence source of truth
advanced ML/RL/text alpha models
```

They should be introduced only when a concrete deployment or research requirement justifies the additional complexity.

## New 1.0 operational evidence components

```text
SQLiteOperationalEvidenceStore
ApprovalControl / ApprovalRevocation
OperationalSession
OperationalDrillResult
OperationalIncident
OperationalJournal
OperationalMetricSnapshot
PaperAcceptancePolicy
PaperAcceptanceEvaluator
PaperAcceptanceReport
```

The operational evidence store complements the paper broker store. It does not replace financial state.

### Approval lifecycle

When `OperationalApprovalService` is configured with an operational evidence store, an approval must have an immutable `ApprovalControl` before it can be applied.

```text
HumanApproval
   +
ApprovalControl(expires_at)
   |
   +---- revoked? ------> reject
   |
   +---- expired? ------> reject
   |
   +---- valid ----------> existing request/snapshot checks -> apply
```

This preserves the existing rule that Agent/Supervisor requests are non-mutating and human approval is applied outside the Agent runtime.

### Paper acceptance

The reference `PaperAcceptancePolicy` evaluates operational reliability, not investment performance. The default policy requires evidence for:

```text
minimum session count
minimum reconciliation count
bounded rejected-order rate
zero critical reconciliation rate
bounded kill-switch trips
restart-recovery drills with 100% pass
kill-switch drills with 100% pass
zero critical operational incidents
zero idempotency failures
```

Projects may instantiate a different deterministic policy, but the policy must be fixed before evaluating the target observation period.

A passing report means the configured paper/shadow deployment passed that policy over that period. It is **not** a live-capital certification.

## 1.0 stability boundary

The stable conceptual contracts are:

```text
PIT ResearchDataset / ExperimentFamily governance
finite Agent tool/policy boundary
generated-feature safety and PIT materialization
deterministic alpha/risk/portfolio ownership
non-mutating Supervisor request semantics
human approval before operational mutation
paper-order idempotency and durable financial state
reconciliation and durable kill switch
structured evidence memory
operational journal and acceptance report
```

Future releases may add adapters and research models around these contracts. They should not move financial-state ownership into an LLM or Agent runtime.

## Release verification

Before the 1.0 branch is promoted to `main`:

```bash
python -m pip install -e ".[dev]"
pytest -q
```

The GitHub Actions matrix must pass on Python 3.11, 3.12 and 3.13.

After release, meaningful deployment testing should also include repeated restart recovery, kill-switch drills, reconciliation exercises and a sustained paper/shadow observation window followed by `PaperAcceptanceEvaluator`.

# FinAgent Roadmap — Post 1.0

Date: 2026-08-26

## 1.0 completed scope

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
1.0        Operational journal, acceptance gate, approval lifetime and stable documentation
```

FinAgent 1.0 is a stable research + deterministic portfolio + supervised paper/shadow system. The default development strategy after 1.0 is **operate, measure and fix**, not automatic feature expansion.

## Active 1.2.2 research-governance hardening

The Agent-market path exposed several governance gaps that only became visible through code-level review. They are being closed before any sealed-holdout or promotion automation is added.

Current sequence:

```text
ResearchProgram lifecycle                         DONE / main
        ↓
Agent-facing memory / OOS visibility              DONE / main
        ↓
immutable ResearchRegistry identities             PR #22
        ↓
formal Agent ExperimentFamily denominator         PR #22
        ↓
governed Agent-market entrypoint                  PR #22
        ↓
formal-family DSR/PBO/Reality Check binding       NEXT
        ↓
FinalStrategySpec                                 NEXT
        ↓
atomic SEALED_HOLDOUT evidence writer             NEXT
        ↓
one-time sealed holdout evaluator                 NEXT
        ↓
deterministic ResearchPromotionGate               NEXT
```

Acceptance is code-path based. The 1.2.2 work is not complete until an end-to-end governed test proves:

```text
candidate generation
→ formal family freeze
→ development-only research
→ family statistical validation
→ final strategy freeze
→ ResearchProgram freeze
→ one-time sealed holdout
→ sealed evidence remains invisible to adaptive Agent reads
→ deterministic final promotion decision
```

Detailed current status is tracked in `DEVELOPMENT_PROGRESS_2026-08-26_1_2_2.md` and `RESEARCH_GOVERNANCE_1_2_2.md`.

## Immediate post-1.0 priority: sustained paper/shadow validation

Run the system for repeated sessions and collect:

```text
order/fill statistics
reconciliation counts and error rates
restart-recovery drills
kill-switch drills
idempotency incidents
approval expiry/revocation exercises
execution-cost calibration
shadow divergence
operational incidents
PaperAcceptanceReport history
```

Defects found during this period should take precedence over new Agent or modeling features.

## 1.x operational hardening — conditional priorities

These items become necessary only when the target deployment requires them.

### Market/security master

Add canonical instrument identity, venue metadata, tick/lot rules, lifecycle state and richer exchange calendars when paper/shadow testing moves beyond the current simplified asset contract.

### Multi-currency accounting

Add currency-specific cash ledgers, FX translation and base-currency NAV only when the deployment actually trades or settles multiple currencies. Do not add implicit FX conversion to the current ledger.

### Corporate actions

Expand beyond split/cash-dividend support when the target universe requires mergers, spinoffs, rights issues, symbol changes or tax treatment.

### Broker-neutral production order semantics

Before any live adapter, freeze a richer broker-neutral state machine such as:

```text
PENDING_SUBMIT
SUBMITTED / ACKNOWLEDGED
PARTIALLY_FILLED
PENDING_CANCEL
CANCELLED
FILLED
REJECTED
EXPIRED / REPLACED
```

Keep client, broker and exchange order identities distinct.

### Monitoring and alert delivery

The 1.0 journal stores measurable evidence. A deployment may later add external SLO dashboards, alert delivery and incident paging around these contracts.

## Live-capital gate

No live broker adapter should be treated as a default 1.x task. Before discussing live capital, require at minimum:

```text
sustained paper/shadow observation
pre-registered PaperAcceptancePolicy
passing PaperAcceptanceReport(s)
documented reconciliation error rate
zero unexplained idempotency failures
restart-recovery drills
kill-switch drills
approval expiry/revocation drills
corporate-action coverage for the target universe
cost-model calibration evidence
operational runbook and alerting
explicit human sign-off
```

A future live adapter must implement existing deterministic contracts rather than bypassing them.

## Optional orchestration

LangGraph or another workflow engine remains optional. Add graph orchestration only if measured workflow pain requires:

```text
long-running resumable branches
parallel research jobs
multi-hour human checkpoints
complex provider retry/recovery
```

It should be an adapter around `AgentRuntime`, tools and existing state stores; it must not own financial state.

## Optional advanced research

Possible future research work:

```text
regime/change-point models
ML alpha models
Bayesian optimization inside fixed ExperimentFamily budgets
text/news/filing features
RL/MPC portfolio research
multi-Agent review
embedding retrieval for unstructured literature
```

All new research methods must continue to use PIT data, fixed experiment-family governance and the existing statistical controls.

## Success criterion after 1.0

The main metric of project maturity is no longer the number of modules implemented. It is whether the system can repeatedly:

```text
produce reproducible research evidence
construct deterministic portfolios
operate in paper/shadow mode
survive restart and reconciliation exercises
preserve safety and approval boundaries
record incidents honestly
pass a pre-registered operational acceptance policy
```

Agent sophistication is secondary to measured reliability.

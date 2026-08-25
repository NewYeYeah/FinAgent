# FinAgent

**FinAgent 1.0** is a typed, auditable framework for agent-assisted quantitative research, deterministic portfolio construction, supervised paper/shadow trading, and end-to-end evidence lineage.

> **Release scope:** FinAgent 1.0 is a stable **research + portfolio + paper/shadow** release. It does not include live broker credentials and does not claim live-capital readiness.

## Why FinAgent exists

Many “trading Agent” demos optimize the visible Agent loop while leaving the difficult financial-engineering questions implicit: point-in-time data, repeated hypothesis testing, portfolio constraints, state recovery, duplicate orders, reconciliation, approval boundaries, and the distinction between a model proposing an action and financial state actually changing.

FinAgent treats those questions as first-class contracts.

```text
LLM / Agent
  hypothesis, bounded feature code, research plans,
  explanations, memory queries, supervision requests
                |
                v
Deterministic control plane
  PIT validation, experiment governance, policy checks,
  memory/lineage, health monitoring, human approval
                |
                v
Deterministic financial-state layer
  alpha, risk, constraints, portfolio weights,
  RiskGate, paper execution, reconciliation, kill switch
                |
                v
Operational evidence layer
  sessions, drills, incidents, acceptance reports
```

The central rule is:

```text
Agent proposes.
Deterministic code validates and calculates.
Human approval authorizes critical operational mutation.
Financial state is never owned by the LLM runtime.
```

---

## 1.0 feature map

### Quantitative research and statistical governance

FinAgent includes:

- point-in-time `ResearchDataset` / `ResearchSplit` contracts;
- explicit information and execution clocks;
- purged/embargoed walk-forward validation;
- nested purged walk-forward validation;
- immutable experiment specifications and fingerprints;
- `ExperimentFamily` lifecycle and fixed family denominator;
- Bonferroni, Holm and Benjamini-Hochberg multiple-testing correction;
- Deflated Sharpe Ratio;
- CSCV Probability of Backtest Overfitting;
- White-style Reality Check;
- model-stage governance from candidate through paper/shadow/live lifecycle states.

Failed trials remain part of the research record; they are not silently removed because their results were inconvenient.

### Governed Agent research

The Agent layer provides:

- typed `AgentTask`, `AgentRunContext`, tool requests and decisions;
- finite `ToolRegistry`;
- policy-as-code authorization;
- immutable run context and durable SQLite audit;
- deterministic `ResearchPlan` and experiment budgets;
- approved experiment-template registry;
- deterministic scripted research Agent and replay;
- provider-neutral LLM planning;
- optional OpenAI Responses provider;
- token/latency/provider telemetry;
- read-only structured memory tools.

An Agent cannot directly set portfolio weights, change validation thresholds, bypass `RiskGate`, select broker fills, erase failed experiments, or rewrite historical evidence.

### Generated-feature research

FinAgent can ask an LLM to propose bounded feature code, but generated code is not executed as arbitrary application code.

The generated feature path includes:

```text
LLMFeatureGenerator
 -> FeatureSpec
 -> AST validation
 -> restricted subprocess execution
 -> immutable GeneratedFeatureArtifact
 -> PIT materialization
 -> IC / ICIR / turnover / net-return evidence
 -> ExperimentFamily validation
```

Each feature value is materialized using an `asof` window, so syntactically safe Python is not mistaken for protection against look-ahead bias.

### Alpha, risk and portfolio construction

The deterministic portfolio layer includes:

- cross-sectional alpha calibration;
- deterministic alpha ensembles;
- OAS covariance estimation;
- PCA statistical factor risk;
- centralized `ConstraintCompiler`;
- asset, gross, turnover, group, benchmark-active, linear-factor and trade-size constraints;
- equal-weight portfolio benchmark;
- minimum-variance construction;
- risk-parity construction;
- constrained/cost-aware mean-variance construction;
- portfolio stress testing;
- explicit drift-based rebalance policy.

The LLM does not calculate or directly write target weights.

### Low-permission portfolio supervision

`PortfolioHealthMonitor` converts deterministic portfolio evidence into an immutable health snapshot. The Supervisor can inspect health, benchmark comparisons, stress results and rebalance decisions, then create bounded requests such as:

```text
request_operating_policy
request_rebalance
request_human_review
```

These requests return `mutation_performed=false`. Critical changes require human approval outside the Agent runtime.

### Durable paper/shadow operations

The paper operational layer includes:

- `TradingSessionCalendar`;
- persistent `PaperBroker` / `SQLitePaperBrokerStore`;
- `client_order_id` idempotency;
- partial fills;
- order/fill/account persistence;
- process restart recovery;
- `TradingSafetyController`;
- durable kill switch;
- explicit human approval binding;
- portfolio reconciliation;
- split and cash-dividend baseline corporate actions;
- shadow portfolio comparison;
- execution-cost calibration from paper fills.

Important invariants:

```text
retry != second trade
process restart != financial-state reset
request != application
reconciliation failure -> safety state
restart does not clear a halted kill switch
```

### Structured evidence memory

FinAgent 1.0 stores structured research memory rather than using free-form chat history as the source of truth.

The memory graph can connect:

```text
hypothesis
 -> generated feature
 -> experiment
 -> result
 -> model
 -> portfolio-health snapshot
 -> paper order/fill
 -> reconciliation/shadow outcome
```

It also records normalized research/operational failures and provides deterministic duplicate/similarity checks. Historical evidence may preserve or reduce a new research budget; it cannot automatically expand that budget.

### Operational journal and release acceptance

1.0 adds a dedicated operational evidence layer:

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

The reference acceptance policy checks sustained paper/shadow reliability rather than using PnL alone. It can require minimum sessions/reconciliations, zero idempotency failures, bounded order rejection, zero critical reconciliation rate, and successful restart/kill-switch drills.

A passing acceptance report means the selected paper/shadow observation period passed the configured deterministic policy. It is **not** a live-capital certification.

---

## Installation

### Requirements

- Python 3.11+
- NumPy
- SciPy

Clone the repository and create an isolated environment:

```bash
git clone https://github.com/NewYeYeah/FinAgent.git
cd FinAgent
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Windows PowerShell activation:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Optional OpenAI provider

The core package and test suite do not require an LLM SDK or API key.

To install the optional OpenAI adapter:

```bash
python -m pip install -e ".[llm-openai]"
```

Keep API credentials outside the repository. The LLM provider proposes structured research outputs; it does not receive direct financial-state mutation authority.

---

## Run the test suite

Run all tests:

```bash
pytest -q
```

Run one subsystem:

```bash
pytest -q tests/test_operations_phase5.py
pytest -q tests/test_research_memory_phase55.py
pytest -q tests/test_operations_release_v1.py
```

Run a named regression test:

```bash
pytest -q tests/test_operations_release_v1.py -k acceptance
```

GitHub Actions runs the complete suite on Python 3.11, 3.12 and 3.13 without external LLM calls.

For a release candidate, do not consider a green unit suite sufficient by itself. Also perform the paper/shadow operational drills described under **1.0 operational validation** below.

---

## Quick start: persistent paper account

The following example creates a durable paper account. Re-opening the same SQLite file restores financial state rather than reinitializing it.

```python
from datetime import datetime, timezone

from finagent.domain.portfolio import PortfolioState
from finagent.operations import PaperBroker, SQLitePaperBrokerStore

UTC = timezone.utc
store = SQLitePaperBrokerStore("runtime/paper.db")
broker = PaperBroker(store=store)

if not store.has_account():
    broker.initialize_account(
        PortfolioState(
            asof=datetime.now(UTC),
            base_currency="USD",
            cash=100_000.0,
        )
    )

account = broker.account()
print(account.cash, account.nav)
```

`PaperBroker` is intentionally paper-only. It is not a wrapper around a hidden live broker connection.

---

## Quick start: order submission and paper fills

Orders use stable `client_order_id` values. Reusing the same ID with different immutable order content is rejected.

```python
from datetime import datetime, timezone

from finagent.domain.assets import AssetId
from finagent.domain.orders import OrderIntent, OrderSide

UTC = timezone.utc
asset = AssetId("AAA")

intent = OrderIntent(
    asset=asset,
    side=OrderSide.BUY,
    quantity=10.0,
    created_at=datetime.now(UTC),
    client_order_id="rebalance-20260825-AAA-buy-001",
)

registered = broker.submit((intent,))
print(registered[0].status)
```

A later `ExecutionSnapshot` is passed to `broker.process(...)`. Participation limits may create partial fills; subsequent cycles continue from the persisted remaining quantity.

---

## Human approval with expiry and revocation

Phase 5 already required the exact approval ID for a portfolio-health snapshot. FinAgent 1.0 optionally adds a durable approval-validity envelope.

```python
from datetime import datetime, timedelta, timezone

from finagent.operations import (
    ApprovalControl,
    SQLiteOperationalEvidenceStore,
)

UTC = timezone.utc
now = datetime.now(UTC)
evidence = SQLiteOperationalEvidenceStore("runtime/operational_evidence.db")

evidence.register_approval_control(
    ApprovalControl(
        approval_id="approval-001",
        created_at=now,
        expires_at=now + timedelta(minutes=30),
    )
)
```

Configure `OperationalApprovalService` with this evidence store. When the evidence store is enabled, application requires a registered control and rejects expired or revoked approvals.

To revoke an unused approval:

```python
from finagent.operations import ApprovalRevocation

evidence.revoke_approval(
    ApprovalRevocation(
        approval_id="approval-001",
        revoked_at=datetime.now(UTC),
        revoked_by="operator",
        reason="portfolio snapshot superseded",
    )
)
```

Revocation does not undo an already-applied financial mutation. It prevents later application/reuse of the revoked approval.

---

## 1.0 operational validation

The stable 1.0 workflow is not “run one profitable backtest and deploy”. Build durable evidence across a paper/shadow observation window.

### Record completed sessions

```python
from datetime import datetime, timezone

from finagent.operations import OperationalSession

UTC = timezone.utc

evidence.register_session(
    OperationalSession(
        session_id="paper-2026-08-25",
        started_at=datetime(2026, 8, 25, 9, 30, tzinfo=UTC),
        ended_at=datetime(2026, 8, 25, 16, 0, tzinfo=UTC),
        start_nav=100_000.0,
        end_nav=100_320.0,
        metadata={"environment": "paper"},
    )
)
```

### Record restart and kill-switch drills

```python
from finagent.operations import OperationalDrillResult, OperationalDrillType

evidence.register_drill(
    OperationalDrillResult(
        drill_id="restart-drill-001",
        drill_type=OperationalDrillType.RESTART_RECOVERY,
        occurred_at=datetime.now(UTC),
        passed=True,
        actor="operator",
        notes="paper account/order/kill-switch state restored after process restart",
    )
)

evidence.register_drill(
    OperationalDrillResult(
        drill_id="kill-switch-drill-001",
        drill_type=OperationalDrillType.KILL_SWITCH,
        occurred_at=datetime.now(UTC),
        passed=True,
        actor="operator",
        notes="halt persisted through restart and required explicit reset",
    )
)
```

### Record incidents instead of hiding them

```python
from finagent.operations import (
    OperationalIncident,
    OperationalIncidentCategory,
    OperationalIncidentSeverity,
)

evidence.register_incident(
    OperationalIncident(
        incident_id="incident-001",
        category=OperationalIncidentCategory.EXECUTION,
        severity=OperationalIncidentSeverity.WARNING,
        occurred_at=datetime.now(UTC),
        summary="paper fill latency exceeded local target",
    )
)
```

If a duplicate-order/idempotency defect changes financial state, classify it as an idempotency incident. The default acceptance policy allows zero such failures.

### Build the operational snapshot

```python
from finagent.operations import OperationalJournal

journal = OperationalJournal(
    broker_store=store,
    evidence_store=evidence,
)

metrics = journal.snapshot(
    period_start=period_start,
    period_end=period_end,
)

print(metrics.session_count)
print(metrics.reconciliation_count)
print(metrics.critical_reconciliation_rate)
print(metrics.idempotency_failure_count)
```

### Evaluate the paper acceptance gate

```python
from finagent.operations import PaperAcceptanceEvaluator

evaluator = PaperAcceptanceEvaluator(
    journal=journal,
    evidence_store=evidence,
)

report = evaluator.evaluate(
    period_start=period_start,
    period_end=period_end,
    evaluated_at=datetime.now(UTC),
)

print("accepted:", report.accepted)
for check in report.checks:
    print(check.name, check.passed, check.actual, check.requirement)
```

The reference policy defaults are intentionally conservative and require sustained evidence, including multiple sessions/reconciliations and successful restart/kill-switch drills. For tests or a different deployment profile, create an explicit `PaperAcceptancePolicy` before the observation period and pass it to `PaperAcceptanceEvaluator`.

Do not tune the acceptance thresholds after looking at the target period simply to obtain a passing report.

---

## Research workflow

A typical governed research cycle is:

```text
1. create/revise hypothesis
2. query structured memory for duplicates/failures
3. create bounded ResearchPlan
4. optionally use an LLM to propose a feature
5. validate generated feature source
6. materialize feature point-in-time
7. register experiments in one ExperimentFamily
8. run nested validation
9. freeze family
10. run family-level multiplicity/overfitting controls
11. register/promote model through governed stages
12. calibrate alpha and risk
13. benchmark portfolio constructors
14. create PortfolioHealthSnapshot
15. Supervisor creates non-mutating request
16. human approval applies operational authorization
17. paper/shadow execution and reconciliation
18. write outcomes/failures back to structured evidence memory
```

The memory layer helps avoid repeating old work, but memory does not grant additional experiment budget because previous results looked good.

---

## Persistence layout

FinAgent intentionally keeps different state classes separate:

```text
SQLiteResearchRegistry
  experiments, runs, results, models

SQLiteAgentAuditStore
  Agent/Supervisor calls and policy decisions

SQLiteAgentPlanStore
  immutable research plans

SQLiteLLMCallStore
  provider/model/token/latency telemetry

SQLiteGeneratedFeatureStore
  generated feature source lineage

SQLiteGeneratedFeatureResearchStore
  IC/return evidence

SQLitePortfolioSupervisionStore
  portfolio-health evidence

SQLitePaperBrokerStore
  paper orders, fills, account snapshots, kill switch, applications

SQLiteResearchMemoryStore
  hypothesis revisions, lineage and failures

SQLiteOperationalEvidenceStore
  approval validity, sessions, drills, incidents, acceptance reports
```

This separation is deliberate. A memory table is not allowed to become the broker ledger, and a broker ledger is not used as the experiment registry.

---

## Safety and governance invariants

FinAgent 1.0 is designed around the following invariants:

1. **Point-in-time research:** generated and hand-written features must not receive future observations.
2. **Fixed research denominator:** failed/poor trials remain in experiment-family evidence.
3. **Finite Agent authority:** tools and policy determine capability; prompts are not authorization boundaries.
4. **Immutable run context:** an existing Agent run ID cannot be reused with a forged larger budget/allowlist.
5. **Deterministic financial calculations:** alpha/risk/constraints/weights remain outside the LLM.
6. **Request/apply separation:** Supervisor requests do not mutate financial state.
7. **Human approval binding:** operational application is tied to an immutable health snapshot and approval identity.
8. **Bounded approval lifetime:** the 1.0 controlled-approval path supports expiry and revocation.
9. **Idempotent paper orders:** duplicate retries do not create a second trade.
10. **Durable safety state:** process restart does not clear the paper account or halted kill switch.
11. **Reconciliation before trust:** critical account mismatch becomes safety evidence and trips the kill switch.
12. **Evidence instead of selective memory:** failures, drills and incidents are retained and queryable.

---

## Testing strategy

### Unit/regression tests

The repository test suite checks numerical contracts, research governance, Agent policy, generated-code safety, portfolio optimization, supervision, paper operations, structured memory and 1.0 operational evidence.

```bash
pytest -q
```

### Compatibility matrix

CI runs on:

```text
Python 3.11
Python 3.12
Python 3.13
```

### Tests that should remain mandatory before a release

```text
PIT/look-ahead regression tests
experiment-family denominator tests
multiple-testing/DSR/PBO tests
Agent permission and context-forgery tests
generated-feature AST/sandbox tests
portfolio constraint tests
paper order idempotency tests
partial-fill/restart tests
reconciliation -> kill-switch tests
approval identity/expiry/revocation tests
operational-journal aggregation tests
paper-acceptance-policy tests
```

### Deployment drills

For any sustained paper/shadow deployment, periodically perform and record:

```text
process restart recovery
kill-switch halt/restart/reset
reconciliation mismatch injection
order retry/idempotency exercise
corporate-action exercise for supported action types
approval expiration/revocation exercise
```

A green CI suite proves code regressions are controlled; it does not replace sustained operational evidence.

---

## Repository layout

```text
src/finagent/
  domain/        typed financial/research contracts
  data/          PIT data adapters and dataset construction
  alpha/         alpha models/calibration/ensemble
  risk/          covariance and risk models
  portfolio/     constraints, constructors, stress/rebalance
  research/      registries, validation and generated-feature evidence
  agents/        Agent contracts, planning, tools, LLM adapters, supervision
  sandbox/       restricted generated-feature execution
  operations/    paper broker, approvals, reconciliation, safety, evidence
  memory/        structured hypothesis/evidence lineage

tests/           full regression suite
docs/            ADRs, phase notes, runbooks, roadmap and release notes
```

---

## What 1.0 deliberately does not include

FinAgent 1.0 should not be interpreted as a production brokerage stack. The following remain outside the stable scope:

```text
live broker adapters and credentials
multi-currency cash/FX accounting
full exchange/security-master feeds
full corporate-action accounting
institutional nonlinear market-impact calibration
production monitoring/alert delivery infrastructure
LangGraph as a required runtime
multi-Agent trading authority
vector database as structured evidence source of truth
```

These are post-1.0 additions only when an actual deployment requirement justifies them.

---

## Recommended post-1.0 development direction

The default development mode after 1.0 should be **test, operate, measure, fix**, not continuous feature expansion.

Priority order:

```text
1. sustained paper/shadow observation
2. collect operational metrics and acceptance reports
3. fix observed reliability defects
4. improve market/security-master or accounting only when required
5. add broker adapters only after a separate live-readiness gate
6. add orchestration/advanced Agent features only when measured workflow pain justifies them
```

Advanced alpha research (ML, regime models, text features, Bayesian optimization, RL/MPC) can be added later, but should continue to pass through the existing experiment-family and statistical-governance contracts.

---

## Documentation

Key documents:

- `docs/DEVLOG.md` — chronological development history;
- `docs/ROADMAP_REBASELINE.md` — post-1.0 roadmap;
- `docs/RELEASE_1_0.md` — 1.0 scope and necessity decisions;
- `docs/RUNBOOK_PAPER_TRADING.md` — paper operational runbook;
- `docs/PHASE5_5.md` — structured evidence memory;
- ADR files under `docs/` — architectural decisions and invariants.

## License / disclaimer

FinAgent is quantitative research and software infrastructure. It is not investment advice, does not guarantee profitability, and the 1.0 paper/shadow acceptance report is not a certification that a strategy or system is safe for live capital.

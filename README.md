# FinAgent

**FinAgent 1.0.1** is the final hardening release of the 1.0 line: a typed, auditable framework for agent-assisted quantitative research, deterministic portfolio construction, supervised paper/shadow trading, and end-to-end evidence lineage.

> **Release scope:** FinAgent 1.0.1 is a stable **research + portfolio + paper/shadow** release. It does not include live broker credentials and does not claim live-capital readiness.

The 1.0.1 patch incorporates the expert-review hardening documented in [`docs/QUANT_CORE_HARDENING_1_0_1.md`](docs/QUANT_CORE_HARDENING_1_0_1.md). It tightens quantitative correctness and release governance without expanding Agent financial authority.

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
  PIT validation, experiment/program governance,
  policy checks, memory/lineage, human approval
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

## What changed in 1.0.1

The final 1.0 hardening pass addresses the main quantitative-core findings from expert review:

- **PIT formation is independent of future-label realization.** Generated-feature portfolios are formed from point-in-time eligibility and feature availability, never from whether a future return later happens to be finite.
- **Horizon boundary and data corruption are separated.** A fully unrealized formation cross-section is skipped as an unevaluable label-horizon boundary; partial missing realized returns for already-formed positions still fail closed by default.
- **Point-in-time universe membership is explicit.** `ResearchSplit.eligibility_mask`, `UniverseProvider` and `ScheduledUniverseProvider` support `(time, asset)` eligibility.
- **Research search is governable across families.** `ResearchProgram` adds durable family-count, experiment-count and alpha-spending budgets plus one-time sealed-holdout access.
- **Metric direction is explicit.** `MetricObjective.MAXIMIZE` / `MINIMIZE` is part of deterministic winner selection.
- **Turnover semantics are canonical.** `TradeActivity` distinguishes gross traded weight from one-way turnover; linear bps costs are charged on gross traded weight.
- **Generated-feature execution is cheaper without weakening PIT isolation.** Independent historical windows may be batched inside the restricted subprocess.
- **The generic execution boundary is explicit.** The 1.0 `OrderPlanner` supports only equity/ETF spot-like quantity semantics and fails closed for futures, FX, crypto, cash instruments and `OTHER` assets.
- **Research primitives are less skeletal.** Deterministic momentum, reversal, volatility, winsorization, z-score, neutralization and volatility-scaling primitives are included.
- **Release engineering has real gates.** CI combines a Python 3.11/3.12/3.13 test matrix with critical Ruff checks, hardened-surface lint, targeted mypy, coverage, package build and dependency consistency.

---

## Quantitative research and statistical governance

FinAgent includes:

- point-in-time `ResearchDataset` / `ResearchSplit` contracts;
- explicit information and execution clocks;
- `(time, asset)` eligibility masks and PIT universe providers;
- purged/embargoed walk-forward validation;
- nested purged walk-forward validation;
- immutable experiment specifications and fingerprints;
- `ExperimentFamily` lifecycle and fixed family denominator;
- `ResearchProgram` cross-family search and alpha-spending budget;
- Bonferroni, Holm and Benjamini-Hochberg multiple-testing correction;
- Deflated Sharpe Ratio;
- CSCV Probability of Backtest Overfitting;
- White-style Reality Check;
- model-stage governance from candidate through paper/shadow/live lifecycle states.

Failed trials remain part of the research record; they are not silently removed because their results were inconvenient.

### PIT formation contract

For generated-feature research, the formation set at time `t` is:

```text
formation_t = PIT_eligible_t AND finite(feature_t)
```

It is not allowed to depend on the future label:

```text
NOT: PIT_eligible_t AND finite(feature_t) AND finite(forward_return_t)
```

If **all** formed assets at a period have an unrealized forward label, the period is treated as a horizon boundary and omitted from realized-performance evidence. If only part of an already-formed portfolio is missing realized return, evaluation fails by default and requires explicit delisting/corporate-action semantics or PIT ineligibility known before formation.

---

## Governed Agent research

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

`ResearchProgram` adds a higher-level ledger for repeated autonomous search across multiple `ExperimentFamily` objects. Reservations are durable; a failed reserved attempt still consumes search/alpha budget because it was part of the effective hypothesis search.

---

## Generated-feature research

FinAgent can ask an LLM to propose bounded feature code, but generated code is not executed as arbitrary application code.

```text
LLMFeatureGenerator
 -> FeatureSpec
 -> AST validation
 -> restricted subprocess execution
 -> immutable GeneratedFeatureArtifact
 -> PIT materialization + eligibility
 -> IC / ICIR / turnover / net-return evidence
 -> ExperimentFamily validation
```

Each feature value is materialized using an `asof` historical window. `run_batch()` may process multiple independent PIT windows in one restricted subprocess to reduce startup overhead, but generated code does not receive a complete future panel.

---

## Alpha, risk and portfolio construction

The deterministic portfolio layer includes:

- canonical momentum and short-term reversal primitives;
- rolling volatility and volatility scaling;
- winsorization and cross-sectional z-score;
- deterministic linear neutralization;
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

### Turnover convention

For target-weight change `Δw`:

```text
gross_traded_weight = sum_i |Δw_i|
one_way_turnover    = 0.5 * gross_traded_weight
```

Linear cost at `c` basis points is:

```text
cost_fraction = gross_traded_weight * c / 10_000
```

The backward-compatible `mean_turnover` metric is explicitly one-way turnover; generated-feature evidence also reports `mean_gross_traded_weight`.

---

## Execution capability boundary

The domain model can represent `EQUITY`, `ETF`, `FUTURE`, `FX`, `CRYPTO`, `CASH` and `OTHER` assets. Representation is not execution support.

The generic 1.0 `OrderPlanner` intentionally supports only `EQUITY` and `ETF` spot-like quantity semantics. It fails closed for other asset types because correct execution may require contract multipliers, margin, settlement, quote/base-currency conversion, funding, lot rules and venue-specific behavior.

Dedicated instrument-aware planners are required before those asset classes can enter the execution path.

---

## Low-permission portfolio supervision

`PortfolioHealthMonitor` converts deterministic portfolio evidence into an immutable health snapshot. The Supervisor can inspect health, benchmark comparisons, stress results and rebalance decisions, then create bounded requests such as:

```text
request_operating_policy
request_rebalance
request_human_review
```

These requests return `mutation_performed=false`. Critical changes require human approval outside the Agent runtime.

---

## Durable paper/shadow operations

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

---

## Structured evidence memory

FinAgent stores structured research memory rather than using free-form chat history as the source of truth.

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

---

## Operational journal and paper acceptance

The operational evidence layer includes:

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

The reference acceptance policy checks sustained paper/shadow reliability rather than PnL alone. It can require minimum sessions/reconciliations, zero idempotency failures, bounded order rejection, zero critical reconciliation rate, and successful restart/kill-switch drills.

A passing acceptance report means the selected paper/shadow observation period passed the configured deterministic policy. It is **not** a live-capital certification.

---

## Installation

### Requirements

- Python 3.11+
- NumPy
- SciPy

```bash
git clone https://github.com/NewYeYeah/FinAgent.git
cd FinAgent
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Optional OpenAI provider

The core package and test suite do not require an LLM SDK or API key.

```bash
python -m pip install -e ".[llm-openai]"
```

Keep credentials outside the repository. The LLM provider proposes structured research outputs; it does not receive direct financial-state mutation authority.

---

## Environment-isolated command entrypoint

On Ubuntu systems that also use ROS 2, run FinAgent through the single environment wrapper:

```bash
./scripts/finagent.sh --check
./scripts/finagent.sh
```

The first command validates the interpreter and confirms that ROS paths are absent. The second opens a child shell in the `finagent` Conda environment. From that shell, ordinary commands can be used without a dedicated launcher for each one.

The same wrapper can execute any single command:

```bash
./scripts/finagent.sh python -m pytest -q
./scripts/finagent.sh ruff check src tests --select E9,F63,F7,F82
./scripts/finagent.sh python -m build
```

`./scripts/run_tests.sh` remains as a compatibility shortcut and delegates to this wrapper. See [the environment isolation guide](docs/ENVIRONMENT_ISOLATION.md) for the exact variables removed and reusable-script pattern.

---

## Tests and release-quality gates

Run the full regression suite:

```bash
./scripts/run_tests.sh -q
```

Useful focused suites:

```bash
./scripts/run_tests.sh -q tests/test_quant_core_hardening_v101.py
./scripts/run_tests.sh -q tests/test_generated_feature_research_phase35.py
./scripts/run_tests.sh -q tests/test_operations_phase5.py
./scripts/run_tests.sh -q tests/test_operations_release_v1.py
```

GitHub Actions runs tests on:

```text
Python 3.11
Python 3.12
Python 3.13
```

The quality job also runs:

```text
project-wide critical Ruff checks: E9/F63/F7/F82
hardened 1.0 release-surface E/F lint
targeted mypy baseline
pytest coverage floor
python -m build
python -m pip check
```

The project-wide Ruff gate is intentionally a critical-error baseline rather than a false claim that every historical style warning is already cleaned. The hardened 1.0 quantitative surface receives the stricter ratcheting gate. Legacy style debt can be reduced incrementally without weakening correctness checks.

A green CI suite controls software regressions; it does not replace sustained operational evidence.

---

## Quick start: persistent paper account

```python
from datetime import UTC, datetime

from finagent.domain.portfolio import PortfolioState
from finagent.operations import PaperBroker, SQLitePaperBrokerStore

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

## 1.0 operational validation

The stable workflow is not “run one profitable backtest and deploy”. Build durable evidence across a paper/shadow observation window:

```text
1. complete repeated paper/shadow sessions
2. reconcile broker/account state
3. record restart-recovery drills
4. record kill-switch drills
5. retain operational incidents
6. aggregate an OperationalMetricSnapshot
7. evaluate a pre-declared PaperAcceptancePolicy
```

Do not tune acceptance thresholds after looking at the target period simply to obtain a passing report.

---

## Research workflow

A typical governed research cycle is:

```text
1. create/revise hypothesis
2. query structured memory for duplicates/failures
3. reserve ResearchProgram budget when operating a multi-family program
4. create bounded ResearchPlan
5. optionally use an LLM to propose a feature
6. validate generated feature source
7. materialize feature point-in-time with PIT eligibility
8. register experiments in one ExperimentFamily
9. run nested validation
10. freeze family
11. run family-level multiplicity/overfitting controls
12. register/promote model through governed stages
13. calibrate alpha and risk
14. benchmark portfolio constructors
15. create PortfolioHealthSnapshot
16. Supervisor creates non-mutating request
17. human approval applies operational authorization
18. paper/shadow execution and reconciliation
19. write outcomes/failures back to structured evidence memory
```

The memory layer helps avoid repeating old work, but memory does not grant additional experiment budget because previous results looked good.

---

## Persistence layout

FinAgent intentionally keeps different state classes separate:

```text
SQLiteResearchRegistry
  experiments, runs, results, models

SQLiteResearchProgramStore
  cross-family research budgets and sealed holdout access

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

1. **Point-in-time research:** generated and hand-written features must not receive future observations.
2. **PIT universe membership:** future-return realization cannot define formation eligibility.
3. **Fixed research denominator:** failed/poor trials remain in experiment-family evidence.
4. **Cross-family search budget:** repeated research families can be charged to a durable `ResearchProgram` ledger.
5. **Finite Agent authority:** tools and policy determine capability; prompts are not authorization boundaries.
6. **Immutable run context:** an existing Agent run ID cannot be reused with a forged larger budget/allowlist.
7. **Deterministic financial calculations:** alpha/risk/constraints/weights remain outside the LLM.
8. **Explicit metric direction:** selection semantics do not depend on metric-name guessing.
9. **Canonical turnover:** gross trading and one-way turnover are distinct quantities.
10. **Request/apply separation:** Supervisor requests do not mutate financial state.
11. **Human approval binding:** operational application is tied to an immutable health snapshot and approval identity.
12. **Bounded approval lifetime:** the controlled-approval path supports expiry and revocation.
13. **Idempotent paper orders:** duplicate retries do not create a second trade.
14. **Durable safety state:** process restart does not clear the paper account or halted kill switch.
15. **Reconciliation before trust:** critical account mismatch becomes safety evidence and trips the kill switch.
16. **Execution capability is explicit:** the generic planner does not pretend derivatives/FX/crypto use equity order semantics.
17. **Evidence instead of selective memory:** failures, drills and incidents are retained and queryable.

---

## Repository layout

```text
src/finagent/
  domain/        typed financial/research contracts
  data/          PIT data adapters and dataset construction
  models/alpha/  alpha models and deterministic research primitives
  models/risk/   covariance and risk models
  portfolio/     constraints, constructors, stress/rebalance
  research/      registries, validation, programs and feature evidence
  agents/        Agent contracts, planning, tools, LLM adapters, supervision
  sandbox/       restricted generated-feature execution
  operations/    paper broker, approvals, reconciliation, safety, evidence
  memory/        structured hypothesis/evidence lineage
  services/      deterministic portfolio/order services

tests/           regression suite
docs/            ADRs, phase notes, runbooks, roadmap and release notes
```

---

## What 1.0 deliberately does not include

```text
live broker adapters and credentials
futures/FX/crypto execution planners
multi-currency cash/FX accounting
full exchange/security-master feeds
full corporate-action accounting
institutional nonlinear market-impact calibration
production monitoring/alert delivery infrastructure
LangGraph as a required runtime
multi-Agent trading authority
vector database as structured evidence source of truth
unrestricted autonomous code generation
```

These are post-1.0 additions only when an actual deployment requirement justifies them.

---

## Recommended post-1.0 direction

The default development mode after 1.0.1 should be **test, operate, measure, fix**, not continuous feature expansion:

```text
1. sustained paper/shadow observation
2. collect operational metrics and acceptance reports
3. fix observed reliability defects
4. reduce legacy static-analysis/style debt incrementally
5. improve security-master/accounting only when required
6. add instrument-specific execution only with dedicated semantics and tests
7. add live broker adapters only after a separate live-readiness gate
8. add advanced Agent orchestration only when measured workflow pain justifies it
```

Advanced alpha research can be added later, but it should continue to pass through the existing PIT, experiment-family and research-program governance contracts.

---

## Documentation

Key documents:

- `docs/QUANT_CORE_HARDENING_1_0_1.md` — expert-review findings, fixes and remaining boundaries;
- `docs/RELEASE_1_0.md` — final 1.0/1.0.1 scope and release criteria;
- `docs/DEVLOG.md` — chronological development history;
- `docs/ROADMAP_REBASELINE.md` — post-1.0 roadmap;
- `docs/RUNBOOK_PAPER_TRADING.md` — paper operational runbook;
- `docs/PHASE5_5.md` — structured evidence memory;
- ADR files under `docs/` — architectural decisions and invariants.

## License / disclaimer

FinAgent is quantitative research and software infrastructure. It is not investment advice, does not guarantee profitability, and a passing paper/shadow acceptance report is not a certification that a strategy or system is safe for live capital.

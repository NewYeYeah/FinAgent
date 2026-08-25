# FinAgent Development Log

This is the canonical chronological development log. Phase-specific design decisions are recorded in ADR, phase and release documents.

## 2026-08-25 — Reusable Environment Isolation Entrypoint

### Goal

Replace command-specific ROS 2 workarounds with one reusable FinAgent command
boundary for interactive development, tests and quality tools.

### Delivered

```text
scripts/finagent.sh interactive/command wrapper
scripts/lib/finagent_env.sh reusable initialization library
ROS/colcon/Python/shared-library environment cleanup
Conda interpreter and Python version verification
run_tests.sh delegation to the common wrapper
environment-script regression tests
executable-bit correction for shell launchers
environment.yml editable-install path correction
```

Key invariants:

- executing the launcher creates a child environment and never claims to mutate
  the caller's parent shell;
- all commands, not only pytest, run with ROS paths removed;
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` remains defense in depth;
- project scripts reuse the common initializer rather than copying cleanup logic;
- a missing or incorrect Conda environment fails with an actionable message.

---

## 2026-08-25 — Version 1.0.1: Expert-Review Quant-Core Hardening

### Goal

Close the final known correctness, governance and release-engineering gaps identified by expert review without widening the 1.0 paper/shadow scope.

### Delivered

```text
PIT eligibility separated from future-label realization
explicit fully-unrealized horizon-boundary handling
ResearchSplit eligibility_mask / PIT UniverseProvider contracts
cross-family ResearchProgram alpha/search budgets
one-time sealed holdout access
MetricObjective MAXIMIZE / MINIMIZE semantics
TradeActivity gross-traded-weight / one-way-turnover convention
batched restricted generated-feature PIT windows
canonical deterministic alpha primitives
generic OrderPlanner equity/ETF-only execution boundary
expanded CI quality/build gates
expert-review hardening release documentation
```

Key invariants:

- future-label availability never determines which assets enter the formation universe;
- a fully unrealized formation cross-section is an unevaluable horizon boundary, while partial missing realized returns for formed positions fail closed by default;
- PIT eligibility is a first-class `(time, asset)` contract rather than an inference from realized returns;
- research attempts across multiple `ExperimentFamily` objects can be charged to a durable `ResearchProgram` budget;
- failed/reserved attempts remain part of the effective search process and still consume research budget;
- winner selection follows explicit metric direction rather than assuming every primary metric is maximized;
- linear bps cost is applied to gross traded weight, with one-way turnover reported separately;
- sandbox batching does not expose a complete future panel to generated code;
- domain support for an `AssetType` does not imply generic execution support;
- the generic 1.0 `OrderPlanner` fails closed outside equity/ETF spot-like quantity semantics;
- CI now distinguishes a repository-wide critical static baseline from stricter hardened-surface checks, avoiding a false claim that all historical style debt has already been removed.

Documentation:

- `QUANT_CORE_HARDENING_1_0_1.md`
- `RELEASE_1_0.md` updated for final 1.0.1 delivery.

---

## 2026-08-25 — Version 1.0.0: Stable Paper/Shadow Release

### Goal

Close the architecture-building cycle and define a stable research + portfolio + supervised paper/shadow scope before moving to sustained operational testing.

### Necessity review

The remaining roadmap was split into release-blocking and post-1.0 work. The release-blocking gaps were operational evidence and bounded approval lifetime, not additional Agent frameworks or advanced alpha models.

### Delivered

```text
SQLiteOperationalEvidenceStore
ApprovalControl / ApprovalRevocation
OperationalSession
OperationalDrillResult
OperationalIncident
OperationalJournal / OperationalMetricSnapshot
PaperAcceptancePolicy / PaperAcceptanceEvaluator / PaperAcceptanceReport
controlled approval expiry/revocation enforcement
formal 1.0 README and release-scope document
```

Key invariants:

- operational acceptance is based on durable sessions, reconciliations, drills and incidents rather than PnL alone;
- default acceptance policy allows zero idempotency failures and zero critical operational incidents;
- restart-recovery and kill-switch drills are explicit evidence;
- when controlled approvals are enabled, every approval needs a durable validity envelope and expired/revoked approvals are rejected;
- approval revocation prevents later application but does not pretend to undo an already-applied financial mutation;
- operational evidence complements, but does not replace, paper-broker financial state;
- 1.0 remains paper/shadow only and is not a live-capital certification.

Documentation:

- `RELEASE_1_0.md`
- rewritten top-level `README.md`
- post-1.0 roadmap.

---

## 2026-08-25 — Phase 5.5: Structured Evidence and Research Memory

### Goal

Turn the separate research, portfolio-supervision and paper-operation registries into bounded, auditable memory without creating a free-form Agent memory channel or allowing historical winners to expand current research budgets.

### Delivered

```text
ResearchHypothesisRevision / append-only hypothesis evolution
MemoryNode / LineageEdge cross-registry graph
FailureRecord normalized failure taxonomy
SQLiteResearchMemoryStore
ResearchMemoryService
EvidenceAwareBudgetPolicy
deterministic hypothesis/experiment/feature similarity
bounded ResearchMemorySummary
six read-only Agent memory tools
```

Key invariants:

- hypothesis revisions are contiguous and immutable;
- memory nodes/edges are idempotent when identical and reject conflicting rewrites;
- source registries remain authoritative for experiments, models, portfolio health and paper financial state;
- failed research/operational outcomes remain queryable evidence;
- graph traversal and Agent summaries are explicitly bounded;
- duplicate detection is deterministic lexical/signature similarity, not claimed semantic equivalence;
- memory may reduce or preserve a caller-supplied experiment budget but can never expand it;
- historical successful results do not automatically grant more trials;
- Agent memory tools are read-only and cannot erase failures or mutate financial state.

Documentation:

- `ADR-019_PHASE55_EVIDENCE_MEMORY.md`
- `PHASE5_5.md`
- README/roadmap updated to `0.6.0b1`.

---

## 2026-08-25 — Phase 5: Paper/Shadow Operations and Reconciliation

### Goal

Move from a deterministic research/portfolio stack to a durable paper operational loop without widening Agent financial authority.

### Delivered

```text
TradingSessionCalendar
PaperOrder / BrokerOrderStatus
PaperBroker / PaperBrokerConfig
SQLitePaperBrokerStore
HumanApproval / OperationalApprovalService
TradingSafetyController / durable kill switch
PortfolioReconciler
ApprovedPaperTradingController
CorporateActionProcessor
ShadowPortfolioMonitor
ExecutionCostCalibrator
```

Key invariants:

- `client_order_id` is an idempotency key;
- duplicate IDs with different immutable order content are rejected;
- partial fills survive across snapshots;
- fill/order/account state is committed durably;
- restart does not reset account or kill-switch state;
- Phase 4.5 Supervisor requests remain non-mutating until explicit human approval;
- paper rebalances require the exact registered approval for the health snapshot;
- reconciliation-critical state trips the kill switch;
- implicit multi-currency conversion is still forbidden.

Phase 5 remains paper/shadow only.

Documentation:

- `ADR-018_PHASE5_PAPER_SHADOW_OPERATIONS.md`
- `PHASE5.md`
- `RUNBOOK_PAPER_TRADING.md`
- README/roadmap updated to `0.6.0a1`.

---

## 2026-08-25 — Phase 4.5: Low-Permission Portfolio Supervisor

Added immutable `PortfolioHealthSnapshot`, deterministic health thresholds, pre-registered operating policies, finite Supervisor inspection/request tools and a deterministic Supervisor acceptance runtime. Portfolio-policy and rebalance requests require human approval and return `mutation_performed=false`.

---

## 2026-08-25 — Phase 4: Alpha, Risk and Portfolio Research Hardening

Added cross-sectional alpha calibration and explicit ensembles; OAS and PCA statistical risk models; centralized asset/group/benchmark/factor/turnover constraints; equal-weight, minimum-variance, risk-parity and constrained mean-variance portfolio constructors; stress testing and explicit rebalance policy.

---

## 2026-08-25 — Phase 3.5: Real Generated-Feature Research

Connected generated feature artifacts to PIT `ResearchDataset` materialization, IC/ICIR, turnover, net-return evidence, immutable traces and the existing family-level statistical governance.

---

## 2026-08-25 — Phase 3D: Restricted Generated Feature Programs

Added bounded feature code generation, AST restrictions, isolated subprocess smoke execution and immutable generated-feature lineage.

---

## 2026-08-25 — Phase 3C: Provider-Agnostic LLM Planning

Added provider-neutral LLM contracts, structured research planning, optional OpenAI Responses adapter and durable provider telemetry while keeping execution deterministic.

---

## 2026-08-24 — Phase 3B: Deterministic Scripted Research Agent

Added `ResearchPlan`, budgets, approved experiment templates, deterministic Agent execution, plan storage and replay.

---

## 2026-08-24 — Phase 3A: Governed Agent Control Surface

Froze typed Agent contracts, finite `ToolRegistry`, policy-as-code, immutable run context and SQLite Agent audit.

---

## 2026-08-24 — Phase 2.5: Research Multiplicity Controls

Added nested purged walk-forward validation, experiment-family governance, Bonferroni/Holm/BH correction, Deflated Sharpe, CSCV PBO and White-style Reality Check.

---

## 2026-08-24 — Phase 2: Timing and Model Governance

Added purged walk-forward splitting, explicit information/execution clocks, timed execution and backtesting, experiment lifecycle and model-stage governance.

---

## 2026-08-24 — Phase 1: Numerical Quant Kernel

Froze the PIT numerical contract and implemented data adapters, alpha/risk baselines, optimizer, backtest, execution simulation and research persistence.

---

## 2026-08-24 — Phase 0.5: Domain Kernel

Established framework-independent contracts for assets, market data, research, forecasts, portfolios, risk decisions, orders/fills and experiment artifacts.

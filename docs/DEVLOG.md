# FinAgent Development Log

This is the canonical chronological development log. Phase-specific design decisions are recorded in ADR and `PHASE*.md` files.

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

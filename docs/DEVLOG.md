# FinAgent Development Log

This file is the canonical chronological development log. Phase-specific details remain in the corresponding ADR and `PHASE*.md` documents.

## 2026-08-25 — Phase 4.5: Low-Permission Portfolio Supervisor Agent

### Goal

Add Agent supervision over the deterministic Phase 4 portfolio engine without granting an Agent direct portfolio-weight, hard-risk, fill or broker-state authority.

### Delivered

```text
HealthLevel / HealthCheck
PortfolioBenchmarkSummary
PortfolioStressSummary
WeightDriftSummary
PortfolioHealthThresholds
PortfolioHealthSnapshot
PortfolioHealthMonitor
SQLitePortfolioSupervisionStore
OperatingMode / OperatingPolicy
OperatingPolicyRegistry
PortfolioSupervisorPolicy
ScriptedPortfolioSupervisorAgent
PortfolioSupervisorToolDependencies
build_portfolio_supervisor_tools
```

`PortfolioHealthMonitor` now converts Phase 4 alpha/risk/benchmark/stress/rebalance outputs into immutable supervision evidence. The monitor supports explicit deterministic freshness, expected-net-return, volatility, turnover and stress-loss thresholds. Threshold values are infrastructure configuration and are not Agent-generated.

The finite Supervisor tool surface is intentionally narrower than the research Agent surface. It supports read-only inspection plus non-mutating requests for a pre-registered operating policy, a deterministic rebalance, or human review. `REQUEST_OPERATING_POLICY` and `REQUEST_REBALANCE` require human approval and produce payloads with `mutation_performed=false`.

`ScriptedPortfolioSupervisorAgent` provides the acceptance workflow: CRITICAL health requests the pre-registered defensive policy plus human review; WARNING health can request a rebalance only when the deterministic rebalance policy has already triggered; OK health creates no financial-state request.

A separate `SQLitePortfolioSupervisionStore` persists snapshot evidence immutably while the existing `SQLiteAgentAuditStore` records every Supervisor action and policy result.

### Design conclusion

Phase 4.5 confirms that Agent supervision and financial-state ownership should remain separate. The next operational boundary is Phase 5, where approved requests can be applied by deterministic paper-trading controllers and reconciled against observed broker state.

### Documentation

- `ADR-017_PHASE45_PORTFOLIO_SUPERVISOR.md`
- `PHASE4_5.md`
- README updated to Phase 4.5 / `0.5.0b1`.

---

## 2026-08-25 — Phase 4: Alpha Calibration, Risk Hardening and Portfolio Research

Phase 4 added cross-sectional expected-return calibration, deterministic alpha ensembles, OAS covariance shrinkage, PCA statistical factor risk, centralized portfolio constraints, equal-weight/minimum-variance/risk-parity/cost-aware mean-variance constructors, common benchmark metrics, deterministic scenario stress testing and explicit drift/turnover rebalance policy.

The core architectural decision is that the LLM remains outside alpha calibration, covariance estimation, constraints and portfolio weights.

The complete CI suite passed Python 3.11/3.12/3.13 with 127 tests.

---

## 2026-08-25 — Phase 3.5: Real Generated-Feature Research Integration

Phase 3.5 connected generated feature artifacts to real point-in-time numerical data. Each feature value is evaluated only from a `FeatureWindow(asof=t)`, preventing a syntactically safe generated program from seeing future rows of a complete panel.

The reference evaluator produces rank IC/ICIR, turnover, gross/net return, cost-adjusted Sharpe, coverage and one-sided net-return p-values. Period-level evidence is persisted immutably and can feed the existing Holm/DSR/PBO/Reality-Check family validator.

---

## 2026-08-25 — Phase 3D: Restricted Generated Feature Programs

Phase 3D added bounded feature code generation, AST validation, restricted subprocess smoke execution, immutable generated-feature lineage and bridging into `ExperimentTemplate`. It explicitly does not claim container-grade isolation.

The project roadmap was rebalanced away from premature LangGraph/multi-Agent complexity toward real feature evaluation, portfolio hardening and paper trading.

---

## 2026-08-25 — Phase 3C: Provider-Agnostic LLM Research Planning

Phase 3C introduced provider-neutral LLM contracts, optional OpenAI Responses API integration, strict structured `ResearchPlan` generation, local deterministic validation, `LLMResearchAgent`, durable provider telemetry and Agent-quality metrics.

The LLM can choose approved experiment templates and bounded variants but cannot control validation thresholds, research budgets, portfolio weights, risk overrides, fill prices, broker actions or Python code.

The complete CI suite passed Python 3.11/3.12/3.13 with 95 tests.

---

## 2026-08-24 — Phase 3B: Deterministic Scripted Research Agent

Phase 3B implemented `ResearchPlan`, `ResearchBudget`, approved experiment templates, `ScriptedResearchAgent`, `AgentRunCoordinator`, append-only plan storage and dry replay. The complete CI suite passed Python 3.11/3.12/3.13 with 90 tests.

---

## 2026-08-24 — Phase 3A: Governed Agent Control Surface

Phase 3A froze typed Agent contracts, finite `AgentAction`, `ToolRegistry`, policy-as-code, immutable registered `AgentRunContext` and `SQLiteAgentAuditStore`.

---

## 2026-08-24 — Phase 2.5: Research Multiplicity and Anti-Overfitting

Phase 2.5 added nested purged walk-forward validation, `ExperimentFamily` governance, Bonferroni/Holm/BH correction, Deflated Sharpe Ratio, CSCV PBO and a White-style reality check.

---

## 2026-08-24 — Phase 2: Validation, Execution Timing and Model Governance

Delivered purged walk-forward splitting, explicit execution snapshots, timed simulated execution/backtesting, durable ExperimentRunner lifecycle and model-stage governance. The hard execution invariant is `execution_at > information_at`.

---

## 2026-08-24 — Phase 1: Numerical Data Contract and Quant Kernel

The frozen numerical contract is `DataAdapter -> ResearchDataset / ResearchSplit -> FeatureWindow -> AlphaModel / RiskModel`, with `(time, asset, feature)` numerical layout and `available_at` as the PIT clock.

---

## 2026-08-24 — Phase 0.5: Domain Kernel and Test Harness

Phase 0.5 froze framework-independent contracts for market data, research datasets, forecasts, portfolio targets/states, risk decisions, orders/fills and experiment artifacts.

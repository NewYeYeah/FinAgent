# FinAgent Development Log

This file is the canonical chronological development log. Phase-specific details remain in the corresponding ADR and `PHASE*.md` documents.

## 2026-08-25 — Phase 3.5: Real Generated-Feature Research Integration

### Goal

Connect Phase 3D generated feature artifacts to real point-in-time numerical data and the existing statistical-governance path.

### Delivered

```text
GeneratedFeatureMaterializer
GeneratedFeatureEvaluationConfig
GeneratedFeatureResearchTrace
GeneratedFeatureEvaluator
SQLiteGeneratedFeatureResearchStore
GeneratedFeatureFamilyValidationInputProvider
GeneratedFeatureNestedWalkForwardStudy
```

The critical design finding is that code-safety validation is not enough to prevent statistical leakage. A safe program can still use future values if it receives an entire panel. Materialization therefore executes each feature only on a `FeatureWindow(asof=t)` bounded by the declared lookback.

The reference evaluator now produces real rank-IC/ICIR, turnover, gross/net return, cost-adjusted Sharpe, coverage and one-sided net-return p-values. Period-level net-return and IC traces are persisted immutably and can feed the existing Holm/DSR/PBO/Reality-Check family validator.

`GeneratedFeatureNestedWalkForwardStudy` reuses the Phase 2.5 nested purged splitter so inner validation and outer held-out evaluation remain chronologically isolated.

The reference rank portfolio is intentionally a research diagnostic rather than the final allocation engine. The next critical path is Phase 4 portfolio/risk hardening.

### Documentation

- `ADR-015_PHASE35_REAL_FEATURE_RESEARCH.md`
- `PHASE3_5.md`
- README updated to Phase 3.5 / `0.4.0b1`.

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

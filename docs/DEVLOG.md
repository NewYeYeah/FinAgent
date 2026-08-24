# FinAgent Development Log

This file is the canonical chronological development log. Phase-specific implementation details remain in the corresponding ADR and `PHASE*.md` documents.

## 2026-08-25 — Phase 3C: Provider-Agnostic LLM Research Planning

### Goal

Introduce real language-model planning without relaxing the deterministic Agent, statistical validation, portfolio, hard-risk or execution boundaries.

### Delivered

```text
LLMRequest / LLMResponse / LLMUsage / LLMProvider
StaticLLMProvider
OpenAIResponsesProvider
SQLiteLLMCallStore
LLMPlanningPolicy
LLMResearchPlanner
LLMResearchAgent
AgentEvaluationMetrics
```

The final architecture is intentionally stricter than a free-form tool-calling Agent:

```text
Natural-language task
 -> LLMResearchPlanner
 -> strict structured ResearchPlan
 -> local deterministic validation
 -> ScriptedResearchAgent
 -> ToolRegistry / PolicyEngine
 -> Research Control Plane
```

The LLM may choose an approved experiment template, bounded variants and allowlisted selection metrics. It cannot set statistical thresholds, search budgets, promotion stages, portfolio weights, execution parameters, fill prices or Python code.

Provider-level structured output is not trusted by itself. FinAgent revalidates exact fields, template membership, parameter names, metric allowlists, identifier syntax and plan budgets.

`SQLiteLLMCallStore` adds durable prompt-hash, model/provider, token, cache, latency and planning-valid telemetry without storing API keys or hidden reasoning.

The OpenAI adapter is optional and lazy-loaded through `.[llm-openai]`; default CI remains offline and provider-independent.

### Documentation

- `ADR-013_PHASE3C_LLM_PLANNING_BOUNDARY.md`
- `PHASE3C.md`
- README updated for the LLM planning boundary and provider installation.

### Next

Phase 3D should introduce sandboxed feature/factor code generation while preserving the existing ToolRegistry and research-validation boundary.

---

## 2026-08-24 — Phase 3B: Deterministic Scripted Research Agent

Phase 3B implemented `ResearchPlan`, `ResearchBudget`, approved experiment templates, `ScriptedResearchAgent`, `AgentRunCoordinator`, append-only plan storage and dry replay. The first complete CI validation passed Python 3.11/3.12/3.13 with 90 tests.

The important invariant is that an autonomous research workflow can complete using only governed tools before any LLM is attached.

---

## 2026-08-24 — Phase 3A: Governed Agent Control Surface

Phase 3A froze typed Agent contracts, finite `AgentAction`, `ToolRegistry`, policy-as-code, immutable registered `AgentRunContext` and `SQLiteAgentAuditStore`.

Unknown tools, malformed arguments, exhausted budgets and illegal model-stage requests are denied and audited. Statistical thresholds and hard trading actions are not Agent capabilities.

---

## 2026-08-24 — Phase 2.5: Research Multiplicity and Anti-Overfitting

Phase 2.5 added nested purged walk-forward validation, `ExperimentFamily` governance, Bonferroni/Holm/BH correction, Deflated Sharpe Ratio, CSCV PBO and a White-style reality check. Family validation is bound to the complete frozen trial denominator.

---

## 2026-08-24 — Phase 2: Validation, Execution Timing and Model Governance

### Delivered

```text
PurgedWalkForwardSplitter
ExecutionQuote / ExecutionSnapshot
ExecutionDataAdapter
TimedSimulatedExchange
TimedEventDrivenBacktestEngine
ExperimentRunner
ModelStage / RegisteredModel / ModelStageEvent
```

The hard execution invariant is `execution_at > information_at`. Model lifecycle is `CANDIDATE -> VALIDATED -> PAPER -> SHADOW -> LIVE -> RETIRED`. Phase 2 also fixed a SQLite `INSERT OR REPLACE` cascade bug that could delete dependent experiment results.

Suite total after Phase 2: 55 tests.

---

## 2026-08-24 — Phase 1: Numerical Data Contract and Quant Kernel

The frozen numerical contract is:

```text
DataAdapter
 -> ResearchDataset / ResearchSplit
 -> FeatureWindow
 -> AlphaModel / RiskModel
```

Canonical feature arrays are `(time, asset, feature)` and labels are `(time, asset, label)`. `available_at` is the PIT research clock; `TimeRange` is half-open `[start, end)`.

Delivered PIT-safe data adapters, random-walk/AR/ARMA alpha models, GARCH/EWMA covariance risk models, mean-variance optimization, deterministic hard risk gates, volume-aware simulated execution, event-driven backtesting and the initial `SQLiteResearchRegistry`.

Suite total after Phase 1: 45 tests.

---

## 2026-08-24 — Phase 0.5: Domain Kernel and Test Harness

Phase 0.5 froze framework-independent contracts for assets/market data, research datasets, alpha/risk forecasts, portfolio targets/states, explicit risk decisions, orders/fills, experiment artifacts and core service protocols.

The initial smoke path was:

```text
MarketSnapshot
 -> EqualWeightTargetBuilder
 -> PortfolioTarget
 -> StaticRiskGate
 -> OrderPlanner
 -> SimulatedExchange
 -> AccountLedger
 -> PortfolioState
```

Design rules frozen at this stage remain active:

1. no raw DataFrame as a public cross-module contract;
2. point-in-time availability is explicit;
3. target weights and fills are separate;
4. hard risk decisions are explicit/non-mutating;
5. code/data/parameters/seed are part of experiment identity;
6. third-party frameworks connect through adapters;
7. source migration requires license and behavior audit.

Initial suite: 26 tests.

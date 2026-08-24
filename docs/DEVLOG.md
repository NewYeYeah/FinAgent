# FinAgent Development Log

This file is the canonical chronological development log. Phase-specific details remain in the corresponding ADR and `PHASE*.md` documents.

## 2026-08-25 — Phase 3D: Restricted Generated Feature Programs

### Goal

Allow the LLM to implement a new numeric feature without relaxing the deterministic research, portfolio, hard-risk or execution boundaries.

### Delivered

```text
FeatureSpec
FeatureCodePolicy
FeatureCodeValidator
FeatureValidationReport
GeneratedFeatureArtifact
SQLiteGeneratedFeatureStore
FeatureSandboxLimits
FeatureSandboxRequest
FeatureSandboxResult
LocalFeatureSandbox
LLMFeatureGenerationPolicy
LLMFeatureGenerationResult
LLMFeatureGenerator
generated_feature_template
```

The executable contract is deliberately narrow:

```python
def compute_feature(inputs):
    ...
```

Static validation rejects imports, dynamic execution, file access, general attribute traversal, dunder access, classes, async constructs, global/nonlocal state, context managers, exception machinery and while loops. Calls are restricted to a finite builtin set and selected `math` members.

Validated source is smoke-tested in a separate `python -I -S` subprocess using a reduced builtin namespace and strict JSON transport. POSIX CPU/address-space/file-size/file-descriptor limits are applied when available. This is explicitly not advertised as kernel/container isolation.

Accepted source becomes an immutable `GeneratedFeatureArtifact`, persisted with its source, spec, validator version, smoke-output digest and generator identity. It can be bridged into the existing `ExperimentTemplate` path and therefore cannot bypass ExperimentFamily/multiple-testing controls.

### Roadmap rebaseline

At this point further Agent-framework complexity is no longer the critical path. The roadmap is rebalanced toward quantitative realism:

```text
Phase 3.5  real generated-feature/PIT evaluator integration
Phase 4    portfolio construction/risk hardening
Phase 4.5  low-permission Portfolio Supervisor Agent
Phase 5    paper/shadow trading and reconciliation
Phase 5.5  structured research memory and lineage
Phase 6    optional graph orchestration
Phase 7    optional advanced ML/RL/text/multi-Agent work
```

LangGraph, multi-Agent debate and direct RL allocation are therefore deferred until concrete requirements justify them.

### Documentation

- `ADR-014_PHASE3D_SANDBOXED_FEATURE_CODE.md`
- `PHASE3D.md`
- `ROADMAP_REBASELINE.md`
- README updated to Phase 3D / `0.4.0a1`.

---

## 2026-08-25 — Phase 3C: Provider-Agnostic LLM Research Planning

Phase 3C introduced provider-neutral LLM contracts, optional OpenAI Responses API integration, strict structured `ResearchPlan` generation, local deterministic validation, `LLMResearchAgent`, durable provider telemetry and Agent-quality metrics.

The LLM can choose approved experiment templates and bounded variants but cannot control validation thresholds, research budgets, portfolio weights, risk overrides, fill prices, broker actions or Python code.

The complete CI suite passed Python 3.11/3.12/3.13 with 95 tests.

---

## 2026-08-24 — Phase 3B: Deterministic Scripted Research Agent

Phase 3B implemented `ResearchPlan`, `ResearchBudget`, approved experiment templates, `ScriptedResearchAgent`, `AgentRunCoordinator`, append-only plan storage and dry replay. The complete CI suite passed Python 3.11/3.12/3.13 with 90 tests.

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

Delivered purged walk-forward splitting, explicit execution snapshots, timed simulated execution/backtesting, durable ExperimentRunner lifecycle and model-stage governance.

The hard execution invariant is `execution_at > information_at`. Model lifecycle is `CANDIDATE -> VALIDATED -> PAPER -> SHADOW -> LIVE -> RETIRED`.

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

The canonical smoke path was validated without pandas, LLMs or external trading frameworks.

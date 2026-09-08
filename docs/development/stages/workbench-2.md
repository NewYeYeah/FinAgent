# WORKBENCH-2 — Agent/research-first productization

## Goal

Turn the existing evidence-heavy historical Workbench into the main interactive surface for **Agent-driven quantitative research**, while preserving the mature analytical components already built during the A-share line.

Workbench 2.0 is a product/interaction stage, not a second research engine.

## Current development slice

WORKBENCH-2 is now the active development stage. The first slice is the Agent Workspace only; this does **not** mean the stage or its exit gate is accepted.

This slice upgrades the Agent surface around the existing `ResearchCapabilityRuntime`, R4 Controller, persisted audit projection, AG-UI adapter, normalized SSE, WorkbenchContext and Evidence Plane. Touched Agent server-state uses `@tanstack/react-query`; untouched Workbench pages may still use the custom query client until they are naturally migrated.

The UI must retain the accepted R4 facts as first-class negative product state: terminal `NO_ADAPTIVE_CANDIDATE`, AgentValue `INCONCLUSIVE`, no AdaptiveStrategy, no R5 start, no confirmed Alpha, no accepted PAPER and no Live authorization. Rejected actions and `SLOT_ATTEMPTS_EXHAUSTED` remain observable reliability evidence. The accepted `r4-matched-v3` campaign is an evidence reference and must not be rerun by this stage.

## Existing baseline to reuse

Already present:

```text
React 19 + Vite
React Router
Apache ECharts
@xyflow/react / React Flow
TanStack Table
WorkbenchContext with URL-backed linked selection
Project → Thread → Run Agent index
normalized SSE projections
GET-only Evidence Plane
separately enabled typed local Control Plane
Strategy / Factor / Portfolio / Execution pages
Factor Tear Sheet statistics/heatmaps/correlation/provenance
historical Strategy Decision Explorer
Playwright/Vitest/typecheck/build coverage
```

Do not replace this shell unless a focused usability test proves a structural limitation.

## Product reorganization

Prefer a smaller information architecture:

```text
Research
├── Agent
├── Experiments
├── Factors
├── Market
└── Strategy

Trading
├── Portfolio
└── Execution

System
├── Evidence
├── Configuration
└── Operations
```

Risk information appears in the relevant Strategy/Portfolio/Operations surfaces until a separate Risk page has enough authoritative content to justify itself.

## Deliverables

### 1. Agent Workspace

The Agent becomes the primary research interaction surface rather than only a run audit viewer.

Target composition:

```text
Research session / objective
├── task/run navigation
├── Agent conversation / explicit decisions
├── typed tool/action cards
├── experiment results
├── current MarketState
├── current factor set / allocator
├── remaining research budget
└── inspector / evidence links
```

Do not render hidden chain-of-thought. Render explicit, reviewable artifacts:

```text
hypothesis
requested tool/action
input identity/scope
result summary
Agent critique/decision
next admitted action
```

### 2. Agent event protocol

Evaluate AG-UI as the first standardized protocol for Agent state/tool/event streaming.

Preferred architecture:

```text
FinAgent ResearchCapabilityRuntime
        ↓
thin AG-UI adapter
        ↓
Workbench Agent surface
```

Run a bounded CopilotKit integration spike only if it can consume this protocol without replacing FinAgent's runtime, ledger, evaluator or authority model. If integration forces a parallel Agent framework or large shell rewrite, keep only the protocol ideas and implement a thin client locally.

Do not create another bespoke SSE/event generation once a stable standardized contract is adopted.

### 3. Experiments surface

Make the experiment/trial ledger a first-class research product:

- objective/hypothesis;
- factor/allocator configuration;
- evaluation scope;
- result metrics;
- failed/duplicate/repaired status;
- model/token/cost/evaluator budget;
- comparison/ablation groups;
- final Agent keep/modify/reject decision.

Allow direct comparison of selected experiments without recomputing authoritative statistics in React.

### 4. Factor Intelligence

Extend the existing Factor Tear Sheet rather than replace it.

Add:

```text
FactorLibrary lifecycle
factor family / mechanism
MarketState-conditional performance
current/historical allocator weight
factor similarity/novelty
manual/programmatic/Agent provenance
Agent decision history
```

Preserve existing IC/decay/heatmap/bootstrap/multiplicity/correlation/provenance views where their evidence remains valid.

### 5. Market State surface

Show:

- current/historical state probabilities;
- causal state features;
- state transitions;
- factor performance by state;
- factor weights/exposure by state;
- explanation of why weights changed using persisted model/Agent decisions.

No UI-side clustering/refitting.

### 6. Adaptive Strategy Explorer

Link:

```text
MarketState
→ active factors
→ factor weights
→ combined alpha/rank
→ target portfolio
→ historical execution/cost
→ PnL
```

Use the existing Strategy/Portfolio/Execution evidence patterns. Missing per-factor attribution remains unavailable unless the core persists it.

### 7. Server-state modernization

The current custom `WorkbenchQueryClient` duplicates standard server-state behavior. Migrate surfaces touched by Workbench 2.0 to `@tanstack/react-query` instead of extending the custom client.

Rules:

- do not create a separate multi-PR migration campaign;
- new/touched pages use TanStack Query;
- old pages may remain temporarily on the custom wrapper if migration adds no immediate product value;
- remove the custom client after the last consumer is migrated.

### 8. Visual stack

Continue:

```text
ECharts       analytical/time-series/heatmap/statistical charts
React Flow    research/Agent/evidence graph
TanStack Table structured tables
```

TradingView Lightweight Charts is reserved primarily for PAPER price/order/fill panels. Historical strategy pages may adopt it only if interaction quality materially improves.

## Research graph

Use React Flow to expose the research process, not just evidence lineage:

```text
Literature / prior result
        ↓
Hypothesis
        ↓
Factor / factor set
        ↓
Experiment
        ↓
Evaluation
        ↓
Agent decision
        ↓
Allocator / Strategy candidate
```

Selecting a node should update WorkbenchContext and open the associated analytical/evidence inspector.

## Human usability acceptance

Automated browser acceptance is necessary but insufficient.

Before declaring Workbench 2.0 complete, execute task-based review using real available artifacts, including at least:

1. understand why an Agent rejected/kept a factor;
2. compare two experiments;
3. trace a factor from hypothesis to strategy weight;
4. identify the current MarketState and why allocation changed;
5. trace a historical strategy decision to cost/PnL/evidence;
6. recover the exact config/data/model identities behind the conclusion.

Record observed friction and fix material usability failures before final acceptance.

## Non-goals

- fake Live/PAPER dashboards;
- broker SDK calls from React;
- arbitrary shell/Python execution;
- a new financial-calculation engine in TypeScript;
- a new chart framework for each page;
- reimplementing R4/R5 research logic in the browser.

## Suggested PR slices

A likely decomposition:

1. Agent Workspace + AG-UI/CopilotKit decision + TanStack Query foundation on touched pages.
2. Experiments + Research Graph.
3. Market State + Factor Intelligence.
4. Adaptive Strategy linked analytics.
5. usability/real-artifact acceptance if not cleanly included in prior slices.

The exact count should follow reviewability and product coherence.

## Exit gate

Workbench 2.0 is accepted when:

```text
Agent interaction is the primary research workflow, not only an audit list
experiments/factor/market-state/strategy views are linked by canonical identity
existing historical analytical capabilities remain available or have explicit replacements
no browser financial authority is introduced
Agent stream/tool state is restart/reconnect safe at the product level
real-artifact task-based human usability passes
frontend type/unit/build/browser tests pass
```

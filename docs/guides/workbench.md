# Workbench guide

## 1. What exists now

FinAgent already has a React/Vite Workbench backed by Python projection APIs.

Current reusable capabilities include:

- Agent Project → Thread → Run browsing;
- URL-backed WorkbenchContext;
- Evidence and typed local Control separation;
- normalized SSE for active Agent/command state;
- Strategy historical analytics;
- Factor Tear Sheet;
- Portfolio/Execution analytics;
- evidence/artifact/config linking;
- ECharts, React Flow and TanStack Table rendering.

The current Agent page is primarily an audit/review surface. Workbench 2.0 will make active Agent research interaction first-class.

## 2. Start the Workbench

```bash
uv sync --frozen --extra dev --extra workspace --extra local-parquet
python scripts/run_workspace.py --reports reports --configs configs --open-browser
```

Optional typed local Control Plane:

```bash
python scripts/run_workbench_control.py --configs configs --reports reports
```

Do not expose arbitrary shell/Python or broker/live mutation through this interface.

## 3. Presentation authority

Workbench may:

- query bounded admitted rows;
- select/filter/date-range existing evidence;
- compute clearly presentation-only layout/order/downsampling;
- navigate related identities;
- submit allowlisted typed control intents where the backend permits them.

Workbench may not:

- recompute missing financial/statistical evidence and call it authoritative;
- infer broker/account truth;
- bypass research/PAPER/live gates;
- persist hidden model chain-of-thought.

## 4. Existing analytical assets

### Factors

The Factor Tear Sheet already exposes IC/rolling IC, decay, fold/year heatmaps, bootstrap/inference summaries, multiplicity views, correlation and provenance. Workbench 2.0 should extend this into Factor Intelligence rather than create a parallel factor application.

### Strategy / Portfolio / Execution

Existing linked analytical surfaces should be adapted to the future `AdaptiveStrategySpec`. Missing factor contribution or market-state evidence should remain unavailable until core evidence exists.

### Agent

The existing Agent index/Activity/Inspector should be reused as the audit foundation for an interactive Agent Workspace.

## 5. Workbench 2.0 direction

See [`../development/stages/workbench-2.md`](../development/stages/workbench-2.md).

Major changes:

- research-first navigation;
- objective→tool→experiment→decision workflow;
- Research Graph;
- MarketState and FactorLibrary integration;
- experiment comparison;
- Agent streaming protocol evaluation (AG-UI first);
- gradual TanStack Query adoption on touched pages;
- task-based human usability acceptance.

## 6. Realtime UI boundary

Do not add a mock Live terminal before PAPER. Market/Strategy/Portfolio/Execution/System Health live-like panels are developed with the actual canonical PAPER projections. See [`mt5-paper.md`](mt5-paper.md).

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

The Agent page includes a thin R4 Research Console: objective/start control, typed tool cards, factor set, allocator, admitted historical MarketState, remaining budget and explicit final decision. Provider absence is shown as `Provider unavailable / not admitted`.

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

R4 activity is grouped into tool cards with policy outcome/reason, bounded results and artifact references. Raw action details are collapsed. New factor cards show **Proposed now**; retrospective experiment cards explicitly say **Tested retrospectively on historical development data** and **Not historically known / not independent evidence**. These are development trials, including negative results, without Alpha/PAPER/live authority.

To run the explicit offline acceptance fixture (never a real provider campaign):

```bash
uv sync --frozen --extra dev --extra workspace --extra adaptive-research
cd workspace
npm ci
npm run build
cd ..
uv run --frozen python -m scripts.r4_console_fixture --output .finagent/r4-console-fixture --serve
```

Use a fresh output directory for a changed fixture/code binding. Open `http://127.0.0.1:8765/agent?run=offline-proposal`. The script explicitly admits `scripted-offline` on Control port 8766, creates a real Parquet→Controller→ledger→audit fixture, and permits another bounded scripted objective through the form. Stop the fixture servers with Ctrl+C. Normal Workbench startup does not install this provider. A real provider requires a separately reviewed host admission via `ResearchSessionService`; B-005 remains open. Cancellation is not exposed because the current trusted evaluator thread cannot be safely interrupted; runtime deadlines and fail-closed resume remain authoritative.

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

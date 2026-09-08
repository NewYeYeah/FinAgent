# Workbench guide

## 1. What exists now

FinAgent has a React/Vite Workbench backed by Python projection APIs.

Current reusable capabilities include:

- Agent Project → Thread → Run browsing;
- URL-backed WorkbenchContext;
- Evidence and typed local Control separation;
- normalized SSE for active Agent/command state;
- Experiments and Research Graph;
- Market State and Factor Intelligence;
- Strategy historical analytics;
- Factor Tear Sheet;
- Portfolio/Execution analytics;
- evidence/artifact/config linking;
- ECharts, React Flow and TanStack Table rendering;
- English / `zh-CN` UI selection persisted in browser local storage;
- a dark-first high-contrast presentation theme.

The Agent page includes the R4 Research Console: Research Objective → Start bounded research run → typed tool/result/decision cards, factor set, allocator, admitted historical MarketState, remaining budget and explicit final decision. Provider absence is shown explicitly; the page does not create a provider or research runtime by itself.

Canonical data values are not localized. IDs, SHA values, schema/status/error codes, terminal codes and model/data/protocol identities remain byte-for-byte visible as persisted. For example, the Chinese UI may present `无自适应候选策略 · NO_ADAPTIVE_CANDIDATE`, but `NO_ADAPTIVE_CANDIDATE` remains the persisted terminal value.

## 2. Start the normal Evidence Plane

```bash
uv sync --frozen --extra dev --extra workspace --extra local-parquet
python scripts/run_workspace.py --reports reports --configs configs --open-browser
```

The normal Evidence Plane is **GET-only**. It is sufficient for persisted-artifact Human Acceptance: browsing, tracing canonical identities, checking negative/unavailable states, inspecting accepted evidence and exercising deep links do not require a provider.

Optional historical Control Plane:

```bash
python scripts/run_workbench_control.py --configs configs --reports reports
```

`scripts/run_workbench_control.py` is a **historical-only Control Plane**. It is not a `ResearchSessionService` host and does not make the Agent Research Objective form provider-capable. Do not infer provider availability from the existence of this process.

Do not expose arbitrary shell/Python or broker/live mutation through either interface.

## 3. Presentation authority

Workbench may:

- query bounded admitted rows;
- select/filter/date-range existing evidence;
- compute clearly presentation-only layout/order/downsampling;
- navigate related canonical identities;
- submit allowlisted typed control intents where the backend permits them.

Workbench may not:

- recompute missing financial/statistical evidence and call it authoritative;
- infer broker/account truth;
- bypass research/PAPER/live gates;
- persist hidden model chain-of-thought.

Language/theme settings are presentation state only. Changing locale must not change WorkbenchContext, query selection, the current route, canonical values or financial evidence.

## 4. Existing analytical assets

### Factors

The Factor Tear Sheet exposes IC/rolling IC, decay, fold/year heatmaps, bootstrap/inference summaries, multiplicity views, correlation and provenance. Factor Intelligence extends that surface with persisted FactorLibrary lifecycle, MarketState-conditioned evidence, allocator weights and research lineage rather than creating a parallel factor application.

### Strategy / Portfolio / Execution

Linked Strategy Analytics connects accepted research terminals or explicitly persisted future candidates to existing Strategy/Portfolio/Execution evidence only through canonical identities. The current accepted `NO_ADAPTIVE_CANDIDATE` path is first-class: missing candidate strategy, target portfolio, execution, PnL or attribution remains unavailable and is never synthesized in React.

### Agent

R4 activity is grouped into tool cards with policy outcome/reason, bounded results and artifact references. Raw action details are collapsed. New factor cards show **Proposed now**; retrospective experiment cards explicitly say **Tested retrospectively on historical development data** and **Not historically known / not independent evidence**. These are development trials, including negative results, without Alpha/PAPER/live authority.

The Research Objective form can start a run **only** when the Control API has been constructed with an admitted `ResearchSessionService` and its status reports `provider_available=true`. The UI cannot create that service, bypass admission, or fall back to a provider.

## 5. Interactive Research Human Acceptance — scripted offline only

Interactive factor-proposal Human Acceptance uses the existing scripted-offline fixture. It is a product/usability test environment, **not** a real R4 campaign and **not** a real provider session.

Use a **fresh output directory for every acceptance attempt**. Do not point the fixture at the accepted `r4-matched-v3` result directory, and never rerun `r4-matched-v3` for Workbench acceptance.

Conda / PowerShell example:

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent

python -m pip install -e ".[dev,workspace,adaptive-research]"

cd workspace
npm ci
npm run build
cd ..

python -m scripts.r4_console_fixture `
  --output .finagent\r4-console-human-acceptance `
  --serve
```

Acceptance boundary:

- the CLI only starts the scripted-offline test environment;
- the admitted provider identity is `scripted-offline` only;
- no DeepSeek or other real provider call is allowed;
- this does not execute or regenerate the accepted R4 matched campaign/freeze;
- use a fresh output directory; do not reuse a completed acceptance directory;
- open the Workbench Agent page served by the fixture and enter the research objective there;
- observe factor proposal → validation → evaluation → decision through the typed UI cards and Inspector;
- verify negative/rejected/unavailable states remain explicit;
- verify canonical IDs and raw terminal/status codes remain unchanged while switching `en` / `zh-CN`;
- stop the fixture servers with Ctrl+C when the task is complete.

The fixture builds a real local Parquet → Controller → ledger → AgentAuditStore → Workbench projection path with a scripted provider transport. That makes it suitable for interactive UI acceptance without granting real-provider or financial authority.

A separately reviewed real provider host would require explicit `ResearchSessionService` admission. Human Acceptance in WORKBENCH-2 must not create one merely to test the UI.

## 6. WORKBENCH-2 Human Acceptance status

Automated frontend/browser checks prove software and presentation contracts, but they do not close WORKBENCH-2 usability acceptance.

The remaining stage task is **real-artifact task-based human usability acceptance**. Normal read-only Evidence Plane tasks should use persisted artifacts. The interactive factor-proposal task may use the scripted-offline fixture above. Neither path authorizes a real provider campaign, PAPER trading, MT5 mutation or Live capital.

Current authority remains:

- R4: `NO_ADAPTIVE_CANDIDATE`;
- AgentValue: `INCONCLUSIVE`;
- AdaptiveStrategy: `NONE`;
- R5: `NOT STARTED`;
- Alpha: `NOT CONFIRMED`;
- PAPER: `NOT ACCEPTED`;
- Live: `NOT AUTHORIZED`.

## 7. Workbench 2.0 direction

See [`../development/stages/workbench-2.md`](../development/stages/workbench-2.md).

The major product slices now cover:

- Agent Workspace;
- Experiments + Research Graph;
- Market State + Factor Intelligence;
- Linked Strategy / Portfolio / Execution analytics;
- bilingual/high-contrast UI hardening before Human Acceptance.

WORKBENCH-2 is still development in progress until the real-artifact task-based Human Acceptance exit gate is completed and reviewed.

## 8. Realtime UI boundary

Do not add a mock Live terminal before PAPER. Market/Strategy/Portfolio/Execution/System Health live-like panels are developed with the actual canonical PAPER projections. See [`mt5-paper.md`](mt5-paper.md).

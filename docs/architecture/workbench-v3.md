# FinAgent Workbench Architecture v3.1

This document freezes the product architecture introduced by `current-development-plan-v3.1.md`. It is additive to the existing Visualization V0/V1/V2 and A5-4 architecture.

## 1. Product boundary

The Workbench is the human-facing shell over FinAgent research, evidence and governed operations. It is not the owner of numerical truth and it is not a generic shell/terminal.

```text
                    FinAgent Workbench
                           │
          ┌────────────────┴────────────────┐
          │                                 │
     Evidence Plane                    Control Plane
     default / read-only               explicit opt-in
          │                                 │
  GET product projections           typed commands only
          │                                 │
          └──────────────┬──────────────────┘
                         ↓
                  FinAgent core/services
```

The Evidence Plane remains backward-compatible with current `/api/v1`, `/api/v2` and `/api/v3/agent/*` behavior.

The Control Plane is a future separate service boundary. It must not be enabled implicitly by launching the ordinary Workspace.

## 2. Workbench modules

```text
Command Center
Agent
Strategy
Factors
Portfolio
Execution
Risk
Operations
Evidence & Governance
Configuration
Live (future)
```

The current V3-1 Agent Project/Thread/Run projection belongs under the `Agent` module and remains canonical for Agent navigation.

## 3. WorkbenchContext

Shared presentation context:

```text
project_id
thread_id
run_id
program_id
factor_id
portfolio_validation_id
strategy_id
reserve_id
asset_id
date_range
session_date
fold_id
environment
```

Context is explicitly non-authoritative. It selects/filter/views existing evidence.

Component communication uses declared events:

```text
project_selected
thread_selected
run_selected
asset_selected
date_range_selected
session_selected
factor_selected
order_selected
evidence_selected
```

A chart/page must not directly mutate another chart/page's private state.

## 4. Frontend shell contract

V3-2A shell target:

```text
┌──────────────┬──────────────────────────────────────────────────┐
│ Navigation   │ Context Bar                                      │
│              ├──────────────────────────────────────────────────┤
│ Agent        │                                                  │
│ Strategy     │              Main Workspace                      │
│ Factors      │                                                  │
│ Portfolio    │                                                  │
│ Execution    ├──────────────────────────────┬───────────────────┤
│ Risk         │ Secondary panel / chart      │ Inspector         │
│ Operations   │                              │                   │
│ Evidence     │                              │                   │
│ Config       │                              │                   │
└──────────────┴──────────────────────────────┴───────────────────┘
```

Required extensibility slots from V3-2A:

```text
PanelRegistry
Context Bar
Inspector
Chart workspace
Config drawer
Command palette
```

The Config drawer and Command palette may exist as disabled/read-only surfaces before their contracts are implemented.

## 5. Server-state foundation

V3-2A should centralize server-state loading/caching with TanStack Query or an equivalent typed query layer.

Do not add another generation of page-local:

```text
useEffect → fetch → setLoading → setError → setState
```

for every Workbench resource.

Query keys should be identity-based, for example:

```text
['agent-project', project_id]
['agent-thread', thread_id]
['agent-run', run_id]
['evidence', evidence_id]
['config-snapshot', config_id]
['command-run', command_run_id]
```

## 6. Evidence Plane

Properties:

```text
GET/HEAD/OPTIONS only
read-only SQLite/file access
fail-closed identity conflicts
no hidden reasoning
no reserve execution
no promotion/order mutation
```

It owns projections, not authoritative calculations.

## 7. Control Plane

The Control Plane accepts only typed `CommandIntent` referencing a registered `CommandSpec`.

```text
CommandIntent
     ↓
authority / config / evidence validation
     ↓
registered Application Service
     ↓
CommandRun audit
     ↓
produced Evidence / Result
```

Forbidden:

```text
arbitrary shell command
arbitrary Python source execution from browser
browser-supplied module/function import
bypass of existing approval/safety services
reserve as generic command
```

Initial control implementation is limited to allowlisted L0/L1 historical research commands.

## 8. Configuration architecture

Config presentation is driven by typed server descriptors:

```text
ConfigDescriptor
├── ConfigFieldSpec[]
├── source identity
├── schema/version
└── current ConfigSnapshot
```

Editing protocol fields creates a diff/fork, never an in-place mutation of evidence history.

A JSON-Schema compatible representation may feed RJSF or an equivalent form renderer, while authoritative validation remains in Python/core.

Secrets are represented only by metadata such as:

```text
configured = true/false
provider/reference name
```

Never return credential values to the browser.

## 9. Chart architecture

Chart implementation follows:

```text
Core evidence
    ↓
Projection API
    ↓
FinWidgetSpec v3
    ↓
WorkbenchContext-aware renderer
```

Renderer split:

```text
Apache ECharts
  analytical/time-series/heatmap/forest/waterfall/funnel/correlation

TradingView Lightweight Charts (V4-2)
  candlestick/volume/price/order-fill marker views

React Flow
  Agent/evidence/research/strategy lineage

TanStack Table
  evidence/config/command/order tables
```

Large order/fill/realtime tables may evaluate FINOS Perspective during A6/QMT, not before profiling proves a need.

## 10. Linked chart behavior

A shared `LinkedEChart` abstraction should eventually standardize:

```text
data zoom
brush selection
cross-panel date-range selection
asset/session click events
tooltip identity display
WorkbenchContext binding
```

Charts must identify their evidence authority:

```text
authoritative
derived
diagnostic
```

Presentation downsampling is allowed only if the authoritative aggregate/value remains unchanged and the UI indicates that rendering was sampled when relevant.

## 11. StrategyDecisionSeriesEvidence

The Strategy module must not reconstruct strategy decisions from unrelated browser-side sources. V4-0 introduces a canonical series binding:

```text
Market
→ Alpha
→ Target
→ Desired order
→ Executable order
→ Fill
→ Position
→ PnL/cost
```

Recommended persistence:

```text
JSON manifest + Parquet series
```

This contract is the primary dependency of V4-2 Strategy Decision Explorer.

## 12. Operational integration

Existing governed services remain authoritative:

```text
OperationalApprovalService
ApprovedPaperTradingController
TradingSafetyController
PortfolioReconciler
SQLitePaperBrokerStore / operational evidence stores
```

When L2 operations reach the Workbench during A6, UI controls call typed adapters over these services. The UI never reimplements approval or safety logic.

## 13. Reserve boundary

A5 production reserve remains outside generic Control Plane commands.

The Workbench may inspect A5-4 evidence but may not provide a generic:

```text
Run reserve
Retry reserve
Reset consumed
```

command.

## 14. Live extension

QMT R3 should register future panels into the same Workbench shell:

```text
Market
Strategy
Portfolio
Execution
System Health
```

Realtime data uses its own event/projection contract and does not reuse historical `ResearchDataset` as a stream protocol.

## 15. Acceptance philosophy

Every new Workbench capability must preserve:

```text
identity correctness
chronology correctness
authority boundary
replayability
evidence provenance
cross-platform tests
```

Visual polish is a first-class product requirement, but it is never allowed to hide or replace evidence semantics.

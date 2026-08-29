# FinAgent Current Development Plan v3.1

Status: **active planning baseline after Visualization V3-1**

Planning anchor: `main @ 2909a65aa89f11e80c434414f7fe070d3aa72a0a`

The previous [`current-development-plan-v3.md`](current-development-plan-v3.md) remains the historical post-A5/V3-1 baseline. This v3.1 revision changes the product staging after V3-1 without invalidating or replacing any completed V0–V3-1, A2.6–A5-4 contract.

---

# 1. Why v3.1 exists

V3-1 successfully froze a deterministic read-only Agent `Project → Thread → Run` index. The next product step must now solve two requirements that the original V3 sequence treated too late or too narrowly:

1. the final Workbench must be able to expose selected configuration and execution commands through FinAgent's existing governed application layer rather than remain only an Agent viewer;
2. interactive financial charts must be planned from their authoritative data requirements first, instead of being added as disconnected presentation work after the core has already frozen incompatible report shapes.

Therefore the product target changes from:

```text
Visualization V3 — Agent Workbench
```

to:

```text
Visualization V3 — FinAgent Workbench Foundation
```

The Agent remains a first-class Workbench module. V3-1 remains unchanged and becomes the canonical Agent navigation substrate.

---

# 2. Compatibility invariants

The v3.1 plan is additive. The following completed behavior is frozen unless a later explicit migration contract is approved:

```text
V0 evidence / lineage / FinWidgetSpec contracts
V1 GET-only Evidence API
V2 A2.6 / A4 / execution / governance cockpit
A5-1 eligibility sealing
A5-2 one-shot reserve runner
A5-3 irreversible pre-access CONSUMED state
A5-4 reserve evidence Workspace projection
V3-1 Agent Project → Thread → Run index
```

Non-negotiable compatibility rules:

- `/api/v1`, `/api/v2`, and current `/api/v3/agent/*` read routes remain backward compatible;
- canonical Agent audit SQLite is not rewritten to create product Project/Thread state;
- A5 reserve state is never made mutable from generic Workbench controls;
- hidden chain-of-thought is never persisted or rendered;
- authoritative research/portfolio/risk values continue to come from FinAgent core, not from React;
- browser interaction may filter/select/project evidence but may not silently recompute a new research protocol;
- a config mutation that changes research or execution semantics creates a new identity/fork rather than overwriting frozen evidence;
- production reserve execution remains an independent human-governed OPS operation, not a Workbench command or CI side effect.

---

# 3. Final Workbench product model

The target product is a quantitative research and operations workstation, not a chat clone and not a Phoenix replacement.

```text
FinAgent Workbench
├── Command Center
├── Agent
├── Strategy
├── Factors
├── Portfolio
├── Execution
├── Risk
├── Operations
├── Evidence & Governance
├── Configuration
└── Live                    # only after QMT R3
```

The Workbench must answer four classes of questions:

```text
What did the Agent/research system do?
Why did a strategy produce this signal/order/fill?
What configuration/evidence identity produced this result?
Which governed actions are currently allowed, pending approval, blocked or completed?
```

---

# 4. Evidence Plane and Control Plane

The existing Workspace is intentionally read-only. v3.1 preserves that boundary instead of turning the Evidence API into a general mutation API.

## 4.1 Evidence Plane

```text
React Workbench
      ↓
Evidence API
GET / HEAD / OPTIONS
      ↓
Evidence / Agent / A4 / A5 / derived projections
```

Properties:

- enabled by default;
- safe for ordinary review/navigation;
- no research run, promotion, reserve, broker or lifecycle mutation authority;
- current `/api/v1`, `/api/v2`, `/api/v3/agent/*` remain here.

## 4.2 Control Plane

Future explicit opt-in service:

```text
React Workbench
      ↓
Typed Control API
      ↓
Command Registry / Config Registry
      ↓
FinAgent application services
      ↓
Research / governed operations
```

Recommended deployment boundary:

```text
Evidence API : 8765
Control API  : 8766
```

Default startup remains Evidence-only. Control must require explicit enablement such as:

```text
--enable-control
```

The exact launcher flag is an implementation detail to freeze in V3-2C, but the two-plane authority split is frozen here.

The Control Plane must never become an arbitrary shell executor.

---

# 5. WorkbenchContext — shared interaction contract

V3-2A introduces an additive browser/product context model so future Agent, Strategy, Factor, Portfolio and Execution panels can coordinate without ad-hoc cross-component state.

Proposed stable context keys:

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

Rules:

- context selection is presentation state, not authoritative evidence;
- every context value must preserve the canonical identifier supplied by its source projection;
- URL/deep-link representation should be deterministic where practical;
- a panel may ignore unsupported context keys but must not reinterpret their identity;
- linked charts must propagate explicit interaction events instead of mutating unrelated component state directly.

Initial interaction vocabulary:

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

V3-2A must implement the context bus before advanced linked financial charts are added.

---

# 6. Configuration contract

Configuration is not one homogeneous class of mutable settings. V3-2B must first project configuration into typed descriptors.

Required product contracts:

```text
ConfigDescriptor
ConfigSnapshot
ConfigFieldSpec
ConfigDiff
```

`ConfigFieldSpec` must expose at least:

```text
path
value_type
description
unit / enum if applicable
mutability_class
secret_classification
identity_effect
validation constraints
```

## 6.1 Mutability classes

| Class | Examples | Workbench behavior |
| --- | --- | --- |
| `presentation` | chart layout, default visible range | can change locally without research identity |
| `runtime_safe` | diagnostic logging, runtime worker cap | may change operational runtime only; never enters research evidence identity unless the core already defines otherwise |
| `research_protocol` | factor family, lookback, statistical Gate | edit means new ResearchProgram/protocol identity |
| `execution_protocol` | rebalance cadence, fees, slippage, optimizer/risk parameters | edit means new A4/strategy identity |
| `operational_guardrail` | order/batch notional limits, daily loss limit, kill-switch policy | requires governed operational flow / approval policy |
| `secret_reference` | API credentials | expose configured/not-configured metadata only; never expose secret material |

Existing A4 configuration such as `risk_aversion`, `target_cash_weight`, `max_asset_weight`, `optimizer_turnover_penalty`, fee/slippage assumptions and economic Gate thresholds are therefore **protocol fields**, not ordinary preferences.

PAPER continues to reconstruct research/portfolio parameters from the frozen `FinalStrategySpec`; the UI must not turn PAPER runtime into a new strategy by editing those values in place.

## 6.2 Config editing model

A protocol edit should produce:

```text
ConfigSnapshot(old)
      ↓
ConfigDiff
      ↓
new draft/fork identity
      ↓
validation
      ↓
explicit command to run a new protocol
```

It must never mutate the historical config behind existing evidence.

---

# 7. Command contract

V3-2B freezes a typed command catalog; V3-2C implements a bounded execution gateway for safe research commands.

Required contracts:

```text
CommandSpec
CommandIntent
CommandRun
CommandResult
```

`CommandSpec` should include:

```text
command_id
category
description
required_config
required_evidence
authority_level
side_effect_class
approval_policy
idempotency_policy
timeout / cancellation policy
produced_evidence
```

## 7.1 Authority levels

| Level | Meaning | Examples |
| --- | --- | --- |
| L0 | read/inspect | validate config shape, inspect evidence, preview diff |
| L1 | deterministic compute | certify data, run development research, run A4 validation, export review bundle |
| L2 | governed mutation | apply approved operational policy, PAPER rebalance, kill-switch reset |
| L3 | irreversible/external authority | production reserve, external broker/live-capital actions |

Rules:

- V3-2C may implement only allowlisted L0/L1 research commands;
- L2 is integrated only with existing human approval/application services during A6/Operational Workbench work;
- L3 never appears as a generic Command Palette action;
- production reserve remains outside the generic Control Plane even though A5 runner code exists;
- no endpoint accepts arbitrary executable text, shell command or Python code from the browser.

## 7.2 Application-service convergence

Short-term adapters may wrap existing allowlisted scripts, but the target architecture is:

```text
CLI adapter ───────┐
Agent adapter ─────┼──→ Application Service → Evidence
Workbench adapter ─┘
```

not:

```text
Workbench → arbitrary subprocess("python scripts/...")
```

Existing approval, safety, PAPER controller and reconciliation services remain authoritative for operational mutations.

---

# 8. FinWidgetSpec v3 additive extension

Existing `FinWidgetSpec` remains valid. V4-linked analytics will add optional fields rather than replace V0/V1 specs.

Proposed optional fields:

```text
context_keys
linked_parameters
config_refs
command_refs
evidence_requirements
interaction_events
```

Example semantic intent:

```text
widget_id: strategy.asset.decision
question: Why did the strategy trade this asset?
context_keys: [strategy_id, asset_id, date_range]
evidence_requirements:
  - StrategyDecisionSeriesEvidence
  - A4ExecutionLedger
interaction_events:
  - asset_selected
  - session_selected
  - order_selected
```

The widget layer still describes product questions and evidence requirements; it must not become a hidden research-computation engine.

---

# 9. Financial-series evidence required before advanced charts

## 9.1 StrategyDecisionSeriesEvidence — V4-0

The most important missing cross-domain series is the decision path from signal to realized execution.

Recommended storage:

```text
manifest JSON + Parquet long-form series
```

Minimum row-level fields:

```text
session_date
signal_asof
asset
alpha_score
alpha_rank
pre_trade_weight
target_weight
realized_weight
desired_quantity
executable_quantity
filled_quantity
fill_price
close_price
gross_pnl
fees
slippage
net_pnl
constraint_code
```

Factor contribution should use a separate long table when multiple factors exist:

```text
session_date
asset
factor_id
raw_signal
normalized_signal
weighted_contribution
```

Identity requirements:

- bind strategy/research/A4 identity;
- bind market/data version;
- bind source ledger/report digest where applicable;
- deterministic row ordering;
- exact schema version;
- no browser-side reconstruction of authoritative strategy decisions from unrelated reports.

## 9.2 FactorSeriesEvidence — V4-1

Required when current reports do not formally persist the full time series for:

```text
horizon IC
rolling IC
Q1–Q5 return/NAV
long-short return/NAV
daily turnover
daily coverage
```

The browser may aggregate display windows from authoritative rows, but may not invent missing financial series from summary statistics.

## 9.3 Benchmark / risk series

Before beta/active return/risk attribution charts are authoritative, core must persist or expose:

```text
benchmark return/NAV
realized portfolio exposure
covariance/correlation identity
industry/style exposure where supported
```

This remains Data Hardening / V5 work rather than being computed opportunistically in React.

---

# 10. Interactive chart target catalogue

The final Workbench should prioritize charts that explain the strategy, not only charts that decorate metrics.

| Surface | Interactive chart | Product question | Required data | Planned stage |
| --- | --- | --- | --- | --- |
| Strategy | candlestick + signal/order/fill markers | when and why did we trade? | OHLCV + StrategyDecisionSeriesEvidence + fills | V4-2 |
| Strategy | signal-strength heatmap | where was the strongest cross-sectional alpha? | date × asset alpha score/rank | V4-2 |
| Strategy | factor contribution stack | which factors created the signal? | factor contribution series | V4-2 |
| Strategy | target vs realized weight | did execution realize the intended portfolio? | target/realized weights | V2 data, V4-2 polish/linking |
| Portfolio | gross/net/benchmark NAV | does edge survive friction and benchmark? | gross/net NAV + benchmark | V2 + benchmark hardening |
| Portfolio | underwater drawdown | when did losses concentrate? | NAV/returns | existing derived view, V4-4 linked interaction |
| Portfolio | rolling Sharpe/vol/beta | is performance stable? | authoritative returns + benchmark for beta | V4-4/V5 |
| Portfolio | monthly return heatmap | is performance regime/month concentrated? | authoritative return series | V4-4 |
| Portfolio | return distribution / tail | how asymmetric/heavy-tailed are results? | authoritative return series | V4-4 |
| Factor | IC / rolling IC | does the factor predict consistently? | FactorSeriesEvidence | V4-3 |
| Factor | IC decay | how fast does signal decay? | horizon IC series | V4-3 |
| Factor | fold/year heatmap | does evidence survive time/fold changes? | fold/year IC | existing summaries + V4-3 |
| Factor | Q1–Q5 cumulative NAV | is the signal monotonic? | quantile return/NAV series | V4-1/V4-3 |
| Factor | turnover / coverage | is the factor implementable? | daily turnover/coverage | V4-1/V4-3 |
| Factor | HAC/bootstrap forest | is significance robust? | existing statistical evidence | V2 data, V4-3 polish |
| Factor | Holm/BH matrix | does evidence survive multiplicity correction? | existing multiplicity evidence | V2 data, V4-3 polish |
| Factor | correlation cluster | is the factor redundant? | authoritative correlation evidence | V4-3 |
| Execution | order lifecycle Sankey/funnel | where did intended orders disappear? | A4 ledger lifecycle | V2 data, V4-4 interaction |
| Execution | constraint attribution | why were orders reduced/rejected? | reason codes / decisions | V2 data, V4-4 interaction |
| Execution | cost waterfall | how did gross alpha become net return? | fee/slippage/gross/net | V2 data, V4-4 |
| Execution | participation/capacity | can the strategy scale? | notional/volume/lagged liquidity/impact | Data Hardening + V5 |
| Risk | exposure stack | what risks are we actually holding? | industry/style/factor exposures | V5 |
| Risk | risk contribution | which assets/factors contribute risk? | covariance + weights + risk contribution evidence | V5 |
| Operations | backtest vs PAPER | is live-like behavior drifting from research? | historical + PAPER series | A6/V5 |
| Operations | reconciliation drift | does internal state match broker state? | expected/actual account series | A6 |
| Live | latency/freshness/system health | is realtime state trustworthy? | realtime event timestamps/state | QMT R2-R4 |

---

# 11. Strategy Decision Explorer — primary V4-2 product

The first high-value advanced chart should be a linked strategy decision explorer, not another metric card.

Target composition:

```text
┌─────────────────────────────────────────────────────────┐
│ Asset price / candlestick                              │
│ BUY / SELL / desired / filled markers                  │
├─────────────────────────────────────────────────────────┤
│ Alpha score + factor contributions                     │
├─────────────────────────────────────────────────────────┤
│ Target weight vs realized weight                       │
├─────────────────────────────────────────────────────────┤
│ Gross PnL → fee/slippage → net PnL                     │
└─────────────────────────────────────────────────────────┘
```

Selecting an order/fill should populate the Inspector with:

```text
signal timestamp
alpha score / rank
factor contribution
target weight
desired quantity
compiled/executable quantity
filled quantity
fill price
fee/slippage
constraint/rejection reason
source evidence identities
```

This surface must make the full strategy path auditable:

```text
Market
 → factor signals
 → Alpha score
 → optimizer target
 → desired order
 → A3 executable order
 → fill
 → realized position
 → PnL/cost
```

---

# 12. Open-source implementation strategy

The goal is to reduce UI plumbing while preserving FinAgent's evidence authority.

## Continue using

### Apache ECharts

Primary analytical chart engine for:

```text
NAV / drawdown
heatmaps
IC / decay
correlation
forest/statistical views
waterfall/funnel/Sankey-style analytical views
```

Develop one shared `LinkedEChart` wrapper for WorkbenchContext synchronization, data zoom, brush/click selection and common tooltip behavior.

### React Flow

Continue for:

```text
Agent/evidence lineage
ResearchProgram lineage
Strategy lifecycle
```

### TanStack Table

Continue for structured evidence/config/command tables.

## Introduce in V3-2A

### TanStack Query

Use for server-state fetching, caching and invalidation across Project/Thread/Run, Evidence, Config and later CommandRun resources. Avoid further proliferation of page-local `useEffect + fetch + setState` state machines.

## Introduce in V3-2B

### react-jsonschema-form (RJSF) or equivalent JSON-Schema form renderer

Use only after ConfigDescriptor/ConfigFieldSpec can emit a stable schema. This accelerates typed configuration forms while keeping validation authoritative on the server/core side.

## Introduce in V4-2

### TradingView Lightweight Charts

Use specifically for financial price/candlestick/volume/order-marker surfaces. Do not use it as the general analytical chart engine.

## Evaluate later (A6/QMT)

### FINOS Perspective

Potentially useful for large/streaming order, fill, position and event tables. Defer until PAPER/QMT data volumes justify the dependency.

## Reference implementations only

Alphalens and QuantStats may be used as visual/metric regression references. FinAgent must continue producing its own authoritative evidence; these libraries must not become an alternate untracked calculation path for production evidence.

---

# 13. Revised V3 sequence

V3-1 is complete and unchanged.

## V3-2A — Workbench Shell + Context Bus

Suggested branch:

```text
feature/v3-workbench-shell-context
```

Deliver:

```text
WorkbenchContextProvider
PanelRegistry
Navigation shell
Context Bar
Agent Project/Thread/Run navigation using V3-1
Activity panel
Inspector slot
Chart workspace slot
Config drawer slot
Command palette slot (disabled/read-only catalogue until V3-2B/C)
TanStack Query server-state foundation
```

No write API yet.

Acceptance:

- V3-1 deep navigation works;
- URL/context identity is deterministic;
- context changes propagate only through declared events;
- existing Evidence/A5 pages continue to work;
- no new mutation route;
- TypeScript/Vitest/build/Playwright plus Workspace API regression green.

## V3-2B — Config Registry + Command Catalog

Suggested branch:

```text
feature/v3-config-command-contracts
```

Deliver contracts/projections only:

```text
ConfigDescriptor / ConfigSnapshot / ConfigFieldSpec / ConfigDiff
CommandSpec / CommandIntent / CommandRun / CommandResult
```

Also deliver read-only catalog APIs and Workbench Config/Command surfaces. Still no general execution endpoint.

## V3-2C — Safe Research Control Gateway

Suggested branch:

```text
feature/v3-research-control-gateway
```

Implement the separate opt-in Control Plane for allowlisted L0/L1 commands only.

Initial candidate commands:

```text
validate configuration
certify local A-share data
run development factor research
run A2.6 robust research
run A4 portfolio validation
export review bundle
rebuild derived evidence catalog
```

Every command must produce durable `CommandRun` audit state and preserve the exact config/evidence identities supplied to the application service.

No L2 operational mutation and no L3 reserve/broker command in this phase.

## V3-3 — Evidence / Artifact / Config Deep Link

Extend the existing V3-1 artifact refs into:

```text
Agent ↔ Factor ↔ ResearchProgram ↔ A4 ↔ A5
Run ↔ ConfigSnapshot / ConfigDiff
CommandRun ↔ produced Evidence
```

## V3-4 — Agent + CommandRun SSE

Stream stable product projections only:

```text
AgentActiveRunProjection
CommandRunProjection
        ↓
SSE
        ↓
Workbench
```

Never stream raw provider callbacks, OTLP spans or hidden reasoning as product events.

## V3-5 — Workbench Foundation Acceptance

Minimum gate:

```text
V3-1 project/thread/run navigation          PASS
WorkbenchContext linked navigation          PASS
read-only Config/Command catalogs           PASS
L0/L1 Control Plane authority tests         PASS
no L2/L3 generic execution path             PASS
Evidence Plane remains GET-only             PASS
hidden reasoning absent                     PASS
Windows / Ubuntu                            PASS
ruff / mypy                                 PASS
TypeScript / Vitest / build / Playwright    PASS
full repository pytest                      PASS
```

---

# 14. Revised V4 sequence — Linked Quant Analytics

## V4-0 — StrategyDecisionSeriesEvidence

Build the authoritative signal → target → order → fill → realized/PnL series before Strategy Decision Explorer UI.

## V4-1 — FactorSeriesEvidence

Persist missing authoritative factor time series.

V4-0 and V4-1 may be developed in parallel only if their source contracts remain independent.

## V4-2 — Strategy Decision Explorer

Price/candlestick + signals/orders/fills + contribution + target/realized + cost/PnL linked interaction.

## V4-3 — Factor Tear Sheet

```text
IC / rolling IC / decay
fold-year heatmap
Q1–Q5 / long-short
turnover / coverage
HAC/bootstrap
Holm/BH
correlation cluster
Agent discovery evolution
```

## V4-4 — Portfolio / Execution Interactive Pack

Upgrade existing V2 evidence into linked charts using WorkbenchContext:

```text
NAV / benchmark / drawdown
monthly returns / distributions
rolling metrics
order lifecycle
constraint attribution
cost waterfall
target vs realized
```

## V4-5 — Linked Analytics Acceptance

Gate:

- every chart declares evidence requirements;
- authoritative/derived status visible;
- asset/date/order selections propagate deterministically;
- no browser-side hidden financial model;
- large series endpoints support bounded range/filter access rather than loading all history unnecessarily;
- Windows/Ubuntu/API/frontend regression green.

---

# 15. Production Reserve remains an independent OPS gate

This revision does not move production reserve execution into the Control Plane.

Production execution still requires the previously frozen independent checklist and explicit human authorization. `RESERVE_PASS` remains the prerequisite for A6 strategy promotion/PAPER; `RESERVE_FAIL` remains a valid terminal state.

---

# 16. A6 / Operational Workbench integration

Only after `RESERVE_PASS`:

```text
A6-1 FinalStrategySpec
A6-2 registry/promotion + human approval
A6-3 internal PAPER
A6-4 reconciliation/recovery/kill switch/incident ledger
A6-5 operational acceptance
```

At that point the Control Plane may integrate L2 commands, but only by calling existing governed services such as operational approval, PAPER controller, reconciliation and safety controller.

Required operational Workbench surfaces later include:

```text
approval queue / validity
PAPER plan
orders / fills / partials / rejects
positions / cash / NAV
kill-switch state
reconciliation drift
incident replay
backtest vs PAPER drift
```

---

# 17. Data hardening dependencies

Raise before sustained PAPER / advanced risk charts:

```text
CorporateActionEvent / CashEvent ledger
benchmark series and identity
lagged-liquidity participation/capacity model
industry/style exposure where available
```

These are core evidence dependencies; Workbench must not synthesize them from incomplete display data.

---

# 18. QMT / Live Workbench staging

QMT remains separate from historical research datasets.

```text
R0 Event Contract
R1 QMT Gateway
R2 Projection / State Store
R3 Live Workbench
R4 External PAPER reconciliation
```

V3 WorkbenchContext and PanelRegistry should be designed so R3 can register Market/Strategy/Portfolio/Execution/System Health panels without replacing the existing shell.

Control authority for external PAPER/live must remain stricter than historical L1 research commands.

---

# 19. Performance / large-series policy

Continue the existing automatic CPU/RAM-aware worker policy for deterministic backend work.

For visualization data:

- use Parquet/columnar storage for large authoritative series;
- expose bounded date/asset filters in projection APIs;
- avoid embedding long time series in summary JSON reports;
- use server-side cached immutable projections where profiling shows value;
- chart downsampling may be presentation-only and must never change authoritative aggregates;
- worker count/cache strategy must not alter evidence identity.

---

# 20. PR sequence from this baseline

Recommended next bounded branches:

```text
docs/planning-baseline-v3.1               # this baseline
feature/v3-workbench-shell-context         # V3-2A
feature/v3-config-command-contracts        # V3-2B
feature/v3-research-control-gateway        # V3-2C
feature/v3-evidence-config-deeplink        # V3-3
feature/v3-agent-command-stream            # V3-4
feature/v3-workbench-acceptance             # V3-5

feature/v4-strategy-decision-series        # V4-0
feature/v4-factor-series-evidence           # V4-1
feature/v4-strategy-decision-explorer       # V4-2
feature/v4-factor-tearsheet                 # V4-3
feature/v4-portfolio-execution-interactive  # V4-4
feature/v4-linked-analytics-acceptance      # V4-5
```

Single-PR rule remains:

- one core contract or one bounded product capability;
- schema changes include tests/docs;
- control-plane changes include authority/adversarial tests;
- chart PRs must name their evidence dependencies;
- no unrelated factor tuning inside product PRs;
- merge only after all relevant CI is green.

---

# 21. Immediate next implementation

After this planning revision is merged, the next code branch is:

```text
feature/v3-workbench-shell-context
```

V3-2A must implement the shell and shared context foundation **without adding write APIs**. Its purpose is to ensure every later Config, Command and Quant chart feature has a stable place to plug into, while preserving the complete V3-1/A5-4 read-only baseline.

# FinAgent 当前版本后续开发规划 v2

> 状态：**当前冻结开发基线（Planning Baseline）**  
> 日期：2026-08-28  
> 对应仓库基线：`main @ 4fcc0c0141d9db584c301f7922484423a56eddbd`  
> 文档定位：本文件是详细开发规划；`docs/development/roadmap.md` 继续作为短版优先级索引。  
> 当前前提：A2.6 / A3 / A4 核心链、统一测试与 Visualization V0/V1 已完成；2025+ reserve 继续保持 untouched。

---

## 0.1 Implementation status addendum — 2026-08-29

下述条目继续作为冻结的 V2 验收基线。当前代码交付已实现 **V2-1～V2-6**：

- rebuildable SQLite Evidence Catalog 与 deterministic protocol comparison；
- Project / Governance cockpit；
- A2.6 Gate / statistical / fold review；
- A4 portfolio / economic review；
- immutable JSONL execution lifecycle、cost 与 target-realized projection；
- human-review ZIP export 与 V2 API/frontend acceptance coverage。

需要明确一个现有 core 约束：仓库当前没有持久化独立的 authoritative A3 certification evidence ID。因此 V2 只把 A3 execution semantics 作为 **`derived` protocol binding** 展示，不在 authoritative lineage DAG 中伪造 A3 节点。A5 仍以 V2 CI/acceptance 全绿、人工复核 exact frozen protocol 且 reserve=`untouched` 为前置条件。

---

## 0.2 A5-1 implementation status addendum — 2026-08-29

A5 已按 bounded-PR 原则进入第一步，但 **reserve 仍未消费**。当前代码实现 `ReserveEligibilitySeal`：

- bind exact A2.6 frozen ResearchProgram / factor family；
- bind exact A4 spec / execution assumptions / immutable ledger digest；
- require A2.6 与 A4 exact replay proof；
- require digest-matched V2 review bundle 与显式 human review attestation；
- freeze code/data identity 与 no-Agent-feedback / no-interactive-tuning authority boundary；
- append-only persistence one seal per reserve/program/A4 identity；
- sealing 本身不读取 reserve 数据、不产生 PASS/FAIL、不写 `CONSUMED`。

因此当前立即下一项收敛为 **A5-2 one-shot runner + terminal evidence**，但只有在真实生产 evidence 完成人工 review 并实际签发 A5-1 seal 后才允许执行。

---

## 1. 规划目标

FinAgent 当前已经从“研究原型”进入“可审计量化研究平台”的阶段。后续开发不再以简单增加 Agent 数量、数据源数量或图表数量为目标，而围绕以下主线推进：

```text
研究正确性
    ↓
执行正确性
    ↓
经济有效性
    ↓
证据可解释 / 可审计
    ↓
一次性独立 Reserve
    ↓
策略冻结 / Promotion
    ↓
PAPER / Shadow
    ↓
Realtime / External Paper
```

本规划的核心目标有四个：

1. 在消费 2025+ reserve 前完成足以支持人工审计的 Visualization V2；
2. 将 A5 one-shot reserve 变成真正不可回看、不可调参、不可重复使用的一次性证据协议；
3. 在 A5 后继续建设 Agent Workbench、Factor Tear Sheet 与 PAPER operational evidence，而不突破 authority boundary；
4. 将 QMT realtime 独立成事件流开发线，不污染历史 ResearchDataset / Evidence 语义。

---

## 2. 当前版本基线

### 2.1 已完成的研究与执行能力

当前核心链已经具备：

- PIT 数值数据契约、split isolation、frozen local A-share Parquet identity；
- bounded Agent-generated features、repair/checkpoint、JSONL/OTLP observability；
- Factor Quant、rolling/subperiod stability、HAC、block bootstrap、Holm/BH；
- A2.6 immutable ResearchProgram、expanding walk-forward、预注册 robust Gate、显式 no-alpha 路径与 exact replay；
- A3 exact-session tradeability、T+1 inventory、板块数量规则、停牌/涨跌停、非对称费用；
- A4 reserve-safe inference、train-only factor calibration、历史风险模型、组合优化、gross/net execution ledger、economic evidence 与 exact replay；
- 已有 sealed holdout、registry、promotion、PAPER/shadow、kill-switch 等底层 primitive。

### 2.2 已完成的可视化能力

Visualization V0 已冻结：

```text
EvidenceRef / EvidenceBundle
FactorEvidence / FoldEvidence
PortfolioEvidence / ExecutionEvidence
LineageGraph
AgentRunProjection
FinWidgetSpec
authoritative / derived / diagnostic authority
```

Visualization V1 已完成：

```text
FastAPI GET-only /api/v1
React + TypeScript + Vite
TanStack Table
ECharts
React Flow

Project / Research / Portfolio / Factor / Agent / Widget pages
A2/A2.5 + A2.6 + A4 semantic projection
A4 gross/net NAV / execution navigation
A2.6 factor / Gate / fold navigation
Agent audit read-only projection
Playwright / Vitest / Python API / Windows & Ubuntu validation
```

现有 Streamlit/Plotly UI 不删除，冻结为 legacy/debug/regression viewer；Phoenix 继续只负责底层 Agent trace。

### 2.3 当前 authority boundary

后续所有开发必须继续满足：

```text
Agent proposes
Deterministic code calculates / validates
Human authorizes critical operations
```

具体禁止项：

- UI 不重新计算 authoritative Sharpe / RankIC / Gate / p-value；
- UI 不修改 ResearchProgram；
- UI 不修改 factor、prompt、threshold、fee schedule 后继续沿用原 evidence identity；
- UI 不消费 reserve；
- Agent 不直接拥有 promotion / PAPER / live-capital 权限；
- hidden reasoning 不持久化、不展示；
- 任何改变研究假设、selector、risk、optimizer 或 execution protocol 的操作都必须 fork 新 identity。

---

## 3. 当前冻结的开发总路线

```text
A2.6 Robust Research         ✓
A3 A-share Execution         ✓
A4 Portfolio Validation      ✓
Visualization V0             ✓
Visualization V1             ✓
          │
          ▼
Visualization V2             ← 当前最高优先级
A4 + Governance Cockpit
          │
          ▼
A5 One-shot Reserve
          │
     ┌────┴────────┐
     ▼             ▼
Visualization V3  Visualization V4
Agent Workbench    Factor Tear Sheet
     └────┬────────┘
          ▼
A6 Strategy Freeze / Promotion / PAPER
          │
          ▼
Visualization V5 Risk / Attribution / Audit Bundle
          │
          ▼
R0 QMT Event Contract
          │
          ▼
R1-R4 QMT Shadow / External PAPER
```

原则：**V2 是 A5 前置 Gate；V3/V4 价值高，但不阻塞 A5。QMT 实现不阻塞历史 Reserve 验证。**

---

# 4. Phase V2 — A4 + Governance Cockpit

**优先级：P0.5 / 当前阶段**  
**目标：在消费 reserve 之前，让研究人员可以通过正式 Workspace 完成 A2.6 → A3 → A4 的人工证据审计。**

V2 不增加新的研究结论；它只组织已有 authoritative evidence，或显式标记 presentation-only derived evidence。

## 4.1 V2-1：Evidence Catalog 与 Protocol Comparison

### 目标

V1 已具备 in-memory disposable catalog。V2 需要支持多个 ResearchProgram / A4 protocol 的稳定导航和比较。

### 计划

新增可重建的 derived catalog：

```text
.finagent/visualization/evidence_catalog.sqlite
```

它只保存索引：

```text
evidence_id
schema_version
evidence_type
authority
source_uri
artifact_digest
program_id
spec_id
selection_id
parent_ids
status
reserve_status
modified_at
```

要求：

- catalog 不是 authoritative source；
- 删除 catalog 后必须可以从 JSON / JSONL / SQLite 重建；
- 不允许 catalog 覆盖冲突 evidence；
- 同 evidence_id + 不同 digest 必须 fail closed。

新增 `ProtocolDiffProjection`，只比较允许的配置字段，例如：

```text
ResearchProgram
walk-forward plan
factor denominator
Gate config
selector config
frozen factor family
risk config
optimizer config
execution config
fee schedule
A4 economic policy
```

禁止将经济结果差异伪装成 protocol diff。

### 验收

- 重建 catalog 后 identity 一致；
- conflicting evidence 被拒绝；
- protocol diff 完全确定性；
- 不写入任何研究数据库。

---

## 4.2 V2-2：Project Cockpit 与 Governance

### Project Cockpit

首页从“报告查看器”升级成生命周期控制面板：

```text
A2.6 Frozen  →  A3 Certified  →  A4 Internal Result  →  A5 Locked
     ●                ●                 ●                  ○
```

必须显示：

- System status；
- Research status；
- A4 execution-validation status；
- ResearchProgram ID；
- factor family / selection ID；
- A4 spec ID；
- data version；
- Git SHA（若 evidence 已持久化）；
- reserve ID / interval / status；
- promotion_eligible；
- 当前 protocol 是否已 freeze。

### Governance 页面

提供：

```text
A2.6 → A3 → A4 Lineage DAG
Protocol Identity Diff
Reserve State
Evidence Authority
Raw Evidence Inspector
```

React Flow 只渲染 semantic LineageGraph，不自行推断父子关系。

### 验收

- 每一个产品级指标均能 deep-link 到 evidence identity；
- reserve 状态在 Project/Research/A4/Governance 多入口可见；
- lineage missing parent / cycle / conflict 均 fail closed。

---

## 4.3 V2-3：A2.6 Candidate Evidence Cockpit

V2 只实现 Reserve 前必要的候选审计，不在本阶段完成完整 Factor Tear Sheet。

### Gate Matrix

```text
                         F1    F2    F3
Positive folds           ✓     ✓     ✗
Direction consistency    ✓     ✗     ✓
Pooled ICIR              ✓     ✓     ✗
Worst fold               ✓     ✗     ✗
Coverage                 ✓     ✓     ✓
HAC                      ✓     ✓     ✗
BH q                     ✓     ✗     ✗
Turnover                 ✓     ✓     ✓
-----------------------------------------
Final                   PASS  FAIL  FAIL
```

### Statistical Forest View

展示 authoritative：

- bootstrap CI；
- HAC p-value；
- bootstrap p-value；
- Holm adjusted p；
- BH q；
- Gate threshold；
- PASS/FAIL。

UI 不重新执行 bootstrap 或 multiple testing。

### Fold Evidence

提供：

- Fold × factor RankICIR heatmap；
- train-frozen direction；
- test oriented RankICIR；
- positive fold ratio；
- worst fold；
- coverage / turnover。

### 验收

- 与 A2.6 JSON 数值逐字段一致；
- sign/direction 不被图表自动绝对值化；
- Gate 原因可从 factor 页面反向跳转 Agent evidence（如存在）。

---

## 4.4 V2-4：A4 Portfolio Cockpit

这是 V2 价值最高的金融页面。

### 主视图

顶部 authoritative metrics：

```text
Gross Return
Net Return
Gross Sharpe
Net Sharpe
Max Drawdown
Gross-to-Net Drag
Turnover
Implementation Shortfall
Cash Fallback Ratio
Rejected Order Ratio
```

图表：

- Gross NAV / Net NAV；
- derived drawdown curve（必须标 `derived`）；
- rolling return / volatility / Sharpe（若前端派生则标 `derived`）；
- fold boundary；
- fold-level net/gross metrics；
- HAC / bootstrap economic evidence。

### 规则

若某指标当前 A4 core 未持久化为 authoritative evidence：

```text
先扩展 FinAgent core evidence schema
→ 再可视化
```

不能在前端临时“补算法”并包装成正式研究结果。

---

## 4.5 V2-5：Execution Cockpit

### Order Funnel

```text
Desired
   ↓
Compiled / Adjusted
   ↓
Executable
   ↓
Filled
```

展示数量与比率。

### Adjustment / Reject Attribution

按 A3/A4 reason codes 归类：

```text
T+1
lot / minimum quantity
suspension
limit-up / limit-down
cash scaling
no session data
other fail-closed rules
```

可视化：

- funnel；
- reason bar；
- Sankey（仅使用确定性的 order-decision flow）；
- date/fold filter。

### Cost Attribution

第一版只展示当前 ledger 已正式持久化的成本组件。

可包括：

```text
broker commission
minimum commission effect
stamp duty
transfer fee
exchange/regulatory pass-through（若启用并持久化）
slippage
```

若 ledger 目前只有 aggregate fee，则先扩展 authoritative fee breakdown，不能由 UI 推测分项。

### Target vs Realized

需要支持：

- target weight；
- realized weight；
- drift；
- implementation shortfall；
- cash fallback；
- participation diagnostics。

如果完整 weight time series 尚未进入 authoritative A4 ledger，应在 V2 中先补 A4 evidence schema，再做 heatmap/tornado。

---

## 4.6 V2-6：Evidence Bundle Export

为人工 Reserve review 生成只读 review bundle：

```text
evidence_bundle/
├── manifest.json
├── lineage.json
├── protocol_diff.json
├── factor_summary.csv
├── fold_summary.csv
├── portfolio_summary.csv
├── execution_summary.csv
├── report_a26.json
├── report_a4.json
└── figures/
```

`manifest.json` 至少记录：

```text
source evidence IDs
digests
program ID
selection ID
A4 spec ID
ledger digest
data version
Git SHA（如果来源提供）
reserve status
generated_at
```

V2 bundle 是“人工 review package”，不等同于 A5/A6 最终 signed audit package。

---

## 4.7 V2 前后端实施拆分

建议拆为 5–6 个 bounded PR：

```text
V2-1  Evidence catalog + immutable protocol diff
V2-2  Project Cockpit + Governance / Lineage
V2-3  A2.6 Gate matrix + statistical evidence
V2-4  A4 Portfolio cockpit
V2-5  Execution lifecycle + cost / target realization
V2-6  Evidence bundle + V2 acceptance
```

粗略工作量（仅用于规模控制，不作为进度承诺）：

```text
后端 / projection / API      2k–4k LOC
React / charts / tables       4k–7k LOC
测试 / fixtures / e2e         2k–4k LOC
```

整体属于 **L/XL 级产品阶段**，但研究算法新增量较少，主要风险在 identity、schema consistency、ledger interpretation 和 authority boundary。

---

# 5. Visualization V2 Acceptance Gate

A5 前必须满足以下全部条件：

| Gate | 要求 |
| --- | --- |
| V2 API | GET/HEAD/OPTIONS only |
| Evidence | A2/A2.6/A4 数值与 authority 保真 |
| Catalog | 可删除重建，冲突 fail closed |
| Protocol Diff | allowlisted + deterministic |
| Lineage | 无 missing parent / cycle / identity conflict |
| A2.6 | Gate matrix / fold evidence / statistical evidence 可审计 |
| A4 | gross/net NAV、fold、economic gate 可审计 |
| Execution | desired→decision→fill 和 reason attribution 可审计 |
| Reserve | 所有关键页面显示 `untouched` |
| UI Authority | 无 rerun / edit Gate / reserve / promotion / order write action |
| Streamlit | legacy regression 继续 green |
| API tests | PASS |
| Vitest | PASS |
| Vite build | PASS |
| Playwright | PASS |
| Windows / Ubuntu | PASS |

V2 通过不代表策略有效；只代表已经具备足够的人类证据审计界面。

---

# 6. Phase A5 — One-shot Reserve Protocol

**优先级：P1；V2 Acceptance 后启动。**

## 6.1 目标

第一次正式消费 2025+ untouched reserve，并保证：

```text
one identity
one protocol
one reserve
one execution
one terminal result
```

## 6.2 Freeze 输入

A5 运行前必须冻结：

```text
A2.6 ResearchProgram ID / spec
factor family / feature digests / weights / directions
A3 execution semantics
A4 validation spec
alpha calibration rule
risk model
optimizer
rebalance cadence
fee schedule
slippage assumptions
reserve interval
reserve pass/fail policy
code / data identity
```

生成：

```text
ReserveEligibilitySeal
```

Seal 必须证明：

- reserve 未被消费；
- A2.6/A4 protocol 已 frozen；
- exact replay 已通过；
- V2 minimum evidence cockpit 已通过 acceptance；
- 不存在 Agent feedback 或 threshold mutation 权限。

## 6.3 一次性执行

A5 期间禁止：

```text
Agent proposal feedback
factor replacement
weight refit based on reserve
threshold change
risk/optimizer change
fee/slippage change
rebalance change
UI interactive tuning
```

输出终态：

```text
RESERVE_PASS
RESERVE_FAIL
```

并把 reserve 状态标记为：

```text
CONSUMED
```

失败是合法终局。

## 6.4 失败后的治理

Reserve failure 后：

- 不得重新使用同一 interval 做新模型验证；
- 不得把 2025+ 重新命名为 development；
- 新 hypothesis/protocol 必须依赖未来未观察数据或 forward PAPER evidence；
- 同一失败结果继续保留在 lineage 中。

## 6.5 A5 预计拆分

```text
A5-1 Reserve eligibility / sealing
A5-2 One-shot runner + terminal evidence
A5-3 consumed-state persistence + replay/audit tests
A5-4 Workspace reserve evidence integration
```

---

# 7. Visualization V3 — Agent Workbench

**优先级：P1；可与 A5 后半段或 A5 后并行。**

目标不是复制 Phoenix，而是展示研究业务语义。

## 7.1 页面

```text
Projects / ResearchPrograms
Runs
Activity Timeline
Evidence Inspector
Artifacts / Code
Governance / Approval
```

Timeline 使用已经冻结的 `AgentRunProjection`：

```text
PLAN
LLM
TOOL
GUARDRAIL
EVIDENCE
DECISION
APPROVAL
RESULT
ERROR
```

## 7.2 Deep Link

必须形成：

```text
Agent Run
   ↕
Factor Evidence
   ↕
ResearchProgram
   ↕
A4 Portfolio
   ↕
Execution Evidence
```

## 7.3 Active Run

如果后续需要活动运行状态：

```text
canonical Agent projection
→ SSE
→ browser
```

不让 React 直接理解 OTLP/Phoenix span。

## 7.4 Phoenix

Phoenix 继续用于：

```text
LLM/provider
repair
sandbox
tokens
latency
exception
```

Workbench 只做 deep link，不复制完整 trace console。

---

# 8. Visualization V4 — Factor Tear Sheet V2

**优先级：P1；不阻塞 A5。**

目标：将 Factor Lab 从“统计字段查看”升级为可审计的 factor tear sheet。

## 8.1 计划内容

- fold/year IC heatmap；
- rolling IC；
- IC decay；
- quantile return；
- turnover / coverage time series；
- HAC/bootstrap forest；
- Holm/BH matrix；
- factor correlation cluster；
- discovery evolution；
- Agent round → candidate → frozen family lineage。

## 8.2 重要依赖

如果需要展示：

```text
Q1–Q5 cumulative NAV
long-short cumulative NAV
turnover daily series
coverage daily series
```

而 core 当前没有正式持久化这些 series，则应新增：

```text
FactorSeriesEvidence
```

由 research core 产生 authoritative series。

不得由浏览器从汇总指标推造累计曲线。

---

# 9. Phase A6 — Strategy Freeze / Promotion / PAPER

**前置：A5 RESERVE_PASS。**

## 9.1 FinalStrategySpec

创建不可变：

```text
FinalStrategySpec
```

至少绑定：

```text
A2.6 identity
A3 execution identity
A4 validation identity
A5 reserve evidence
AlphaModel
RiskModel
Optimizer
fee / slippage assumptions
risk limits
code/data identity
```

## 9.2 Registry / Promotion

- Strategy package 注册到 immutable registry；
- deterministic promotion gate；
- human approval 保留；
- Agent 不允许直接改变 promotion 状态。

## 9.3 Internal PAPER

重点不是收益，而是 operational correctness：

```text
desired order
broker-facing order
fill
fee
position
cash
NAV
```

持续 reconciliation。

必须实现/验证：

- idempotency；
- stale-data reject；
- position/exposure limits；
- kill switch；
- incident ledger；
- restart/recovery；
- manual approval boundary。

---

# 10. Visualization V5 — Risk / Attribution / Audit Package

**优先级：P1.5。**

原则仍是：先由 core 产生 authoritative evidence，再画图。

## 第一批

- covariance / correlation；
- concentration；
- realized exposure；
- drawdown attribution；
- ResearchProgram / protocol comparison；
- signed audit bundle。

## 后续

当 core 正式支持后再增加：

- marginal risk contribution；
- component risk contribution；
- factor exposure；
- stress scenario；
- benchmark/industry/style attribution；
- efficient frontier 等研究视图。

---

# 11. Research & Data Hardening

该工作线不抢占 V2/A5，但应在 A6/PAPER 前逐步推进。

## 11.1 Market / Risk Context

- benchmark evidence；
- industry exposure；
- style exposure；
- concentration constraints。

## 11.2 Security Master

继续改进：

- delisting；
- ST history；
- suspension history；
- source-bound supplemental records；
- 不修改 vendor Parquet。

## 11.3 Corporate Action

新增：

```text
CorporateActionEvent
CashEvent
```

明确验证：

```text
research adjusted-price return
vs
execution raw price + cash/event ledger
```

## 11.4 Capacity / Impact

当前 ex-post participation 仅用于诊断。

后续建立预注册的：

```text
lagged liquidity
participation cap
impact proxy
```

不能使用当日完整成交量决定当日成交。

## 11.5 Intraday

在认证以下语义前不进入正式分钟研究：

```text
5m / 15m / 30m / 60m timestamp convention
bar start/end semantics
auction handling
session boundary
```

---

# 12. QMT Realtime 独立开发线

QMT 不复用 `ResearchDataset` 作为实时 event protocol。

## R0 — Event Contract

先冻结：

```text
QuoteEvent
BarEvent
MarketStatusEvent
AccountStatusEvent
OrderEvent
TradeEvent
OrderErrorEvent
```

统一字段：

```text
event_id
event_time
received_at
available_at
provider
connection_id
subscription_id
sequence
asset
quality
staleness
```

## R1 — QMT Gateway

```text
MiniQMT callback
       ↓
queue.put_nowait(event)
       ↓
Async Event Queue
       ↓
Normalizer
```

Callback 内禁止执行：

```text
因子计算
组合优化
数据库重任务
前端推送阻塞
```

## R2 — Projection / State Store

第一版：

```text
Latest state → process memory / optional Redis
Event log    → append-only Parquet
Analysis     → DuckDB
```

暂不引入 Kafka / Flink / ClickHouse。

## R3 — Live Workspace

未来页面：

```text
Market
Strategy
Portfolio
Execution
System Health
```

浏览器通过 WebSocket 消费 projection，不直连 QMT。

## R4 — Shadow / External PAPER

- market data freshness；
- order/fill callback；
- latency；
- partial fill；
- reject；
- disconnect；
- account/position reconciliation；
- internal model vs broker state drift。

LIVE capital 不属于近期里程碑。

---

# 13. 测试与 CI 统一要求

每个后续阶段必须至少包含：

```text
unit
contract
integration
replay / identity
cross-platform where relevant
```

## Visualization

- Python semantic/API tests；
- unsupported schema fail-closed；
- read-only route inventory；
- TypeScript unit tests；
- ECharts data mapping tests；
- production Vite build；
- Playwright core navigation / deep-link / reserve visibility；
- legacy Streamlit regression。

## A5

- eligibility seal identity；
- reserve single-consumption；
- duplicate consumption blocked；
- frozen protocol mutation blocked；
- terminal pass/fail；
- consumed state persisted；
- no Agent feedback path；
- exact replay of allowed deterministic artifacts。

## A6/PAPER

- idempotent order submission；
- partial/reject handling；
- reconciliation；
- stale market data；
- restart/recovery；
- kill switch；
- human approval；
- incident replay。

---

# 14. PR / Branch 开发策略

保持 bounded PR，避免再次出现超大功能分支难以回归。

推荐：

```text
feature/v2-evidence-catalog
feature/v2-governance-cockpit
feature/v2-factor-gate-view
feature/v2-portfolio-cockpit
feature/v2-execution-cockpit
feature/v2-evidence-export

feature/a5-reserve-seal
feature/a5-reserve-runner
feature/a5-reserve-state

feature/v3-agent-workbench
feature/v4-factor-tearsheet
```

单 PR 原则：

- 一个核心 contract 或一个完整产品能力；
- 不混入无关 research tuning；
- schema 变化必须同时包含 tests/docs；
- 每次 merge 后 main CI green 才进入下一依赖阶段。

---

# 15. 粗略工作量评估

以下只用于控制阶段规模，不构成时间承诺。

| 阶段 | 难度 | 工作量 | 主要风险 |
| --- | --- | --- | --- |
| Visualization V2 | 高 | L/XL | schema/ledger/identity/前端信息密度 |
| A5 Reserve | 高 | M/L | 不可逆证据、single-consumption、governance |
| V3 Agent Workbench | 高 | L | Agent projection/deep link/SSE |
| V4 Factor Tear Sheet | 中高 | M/L | authoritative series 是否完整 |
| A6 PAPER | 很高 | XL | reconciliation/recovery/operational safety |
| V5 Risk/Attribution | 中高 | M/L | core evidence 先行 |
| QMT R0-R4 | 很高 | XL | realtime concurrency/state/reconciliation |

资源优先级不是按 LOC，而按证据不可逆性排序：

```text
Reserve correctness
> execution/accounting correctness
> evidence identity
> product visualization
> realtime breadth
```

---

# 16. 当前立即执行项

Visualization V2-1～V2-6 已完成代码交付，下一正式治理项冻结为：

## **A5 — One-shot Reserve Protocol**

进入 A5 前仍必须满足：

- V2 Python/API、TypeScript、Vitest、Vite build、Playwright 与质量检查全部通过；
- 人工核对 exact A2.6/A4 identity、Gate、execution ledger、protocol diff 与 reserve 状态；
- 2025+ reserve 仍为 `untouched`；
- 不因已观察的 A4/V2 结果修改同一 protocol 的 Gate/selection/execution/economic policy。

在 A5 完成前仍不开始 QMT live-capital 实现。

---

# 17. 变更控制

本规划作为当前开发冻结基线。发生以下变化时必须升级规划版本：

- ResearchProgram / A2.6 schema 实质变化；
- A3 execution semantics 实质变化；
- A4 economic protocol / evidence schema 实质变化；
- reserve interval 或 reserve policy 变化；
- Workspace authority 从 read-only 扩张；
- PAPER / broker authority 变化；
- QMT event contract 正式冻结。

只修改 UI 文案、布局或非权威图表，不要求升级研究 protocol identity；但若 UI 需要新增 authoritative 指标，必须先升级 core evidence schema。

---

# 18. 最终原则

```text
Dataset before model
Evidence before visualization
Core calculation before UI derivation
Immutable identity before comparison
Human-readable audit before reserve
Reserve once
Promotion only after explicit evidence
PAPER before external broker
Operational correctness before live capital
```

FinAgent 下一阶段的目标不再是“继续堆功能”，而是把已经形成的研究、执行和 Agent 证据组织成一个能够支持严谨人工审计、一次性验证和后续 PAPER 的完整工程体系。

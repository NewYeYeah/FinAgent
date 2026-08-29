# FinAgent 当前版本后续开发规划 v3

> 状态：**当前冻结开发基线（Planning Baseline）**  
> 日期：2026-08-29  
> 对应仓库基线：`main @ a197a04d6374b0caa605db9892f5c4ee20688067`  
> 上一详细基线：[`current-development-plan-v2.md`](current-development-plan-v2.md)  
> 文档定位：本文件从 Visualization V3 起作为新的详细开发规划；v2 保留为 V2/A5 历史设计与验收记录。

---

## 1. 当前冻结状态

### 1.1 已完成

```text
A2.6 Robust ResearchProgram                 COMPLETE
A3 A-share Execution Semantics              COMPLETE
A4 Execution-aware Portfolio Validation     COMPLETE
Visualization V0 Semantic Contract          COMPLETE
Visualization V1 Workspace Foundation       COMPLETE
Visualization V2 Governance/A4 Cockpit      COMPLETE
A5-1 ReserveEligibilitySeal                 COMPLETE
A5-2 One-shot Reserve Runner                COMPLETE
A5-3 Crash-safe CONSUMED + Replay/Audit     COMPLETE
A5-4 Reserve Evidence Workspace             COMPLETE
```

A5-1～A5-4 的“完成”指**开发、测试和审计基础设施完成**，不代表真实生产 reserve 已被执行。开发与 CI 不得因为本基线变化自动创建 production seal、读取 2025+ reserve、改变 reserve 状态或触发 promotion。

### 1.2 当前产品能力

当前主产品面为只读 FastAPI + React/TypeScript Workspace，已经能够审阅：

- ResearchProgram / Gate / fold / statistical evidence；
- A4 gross/net portfolio、cost、execution lifecycle、target-versus-realized；
- immutable evidence lineage 与 protocol diff；
- A5 eligibility → CONSUMED → terminal → ledger → replay audit；
- 现有 canonical Agent audit run projection；
- legacy Streamlit 与 Phoenix diagnostics。

### 1.3 当前 authority boundary

继续冻结：

```text
Agent proposes
Deterministic code calculates / validates
Human authorizes critical operations
```

禁止：

- UI 重新计算 authoritative financial/statistical evidence；
- UI 修改 ResearchProgram、Gate、factor、risk、optimizer、execution assumptions；
- UI/Agent 执行 reserve、promotion 或 broker order；
- Agent 直接拥有 PAPER/live-capital authority；
- hidden chain-of-thought 持久化或展示；
- 将被观察/消费的 reserve 重新标记为 development 数据。

---

## 2. 新的总路线

从本基线开始，开发不再是一条单线程流水线，而拆为四条相互约束的工作线：

```text
                 Product / Visualization
                 ┌───────────────────────────────────┐
A5-4 COMPLETE ──→ V3 Agent Workbench ──→ V5 Audit/Risk
                 └──────→ V4 Factor Tear Sheet ─────┘
       │
       │ independent human-governed operation
       ▼
Production Reserve Execution
       │
   ┌───┴────┐
   │        │
 PASS      FAIL
   │        │
   ▼        └──→ no promotion; new hypothesis or future forward evidence
  A6
   │
   ├── Data / execution hardening
   │
   └── Internal PAPER
            │
            └──→ QMT R0 → R1 → R2 → R3 → R4 External PAPER
```

优先级：

```text
P0    Planning Baseline v3
P1    Visualization V3 Agent Workbench
P1    Visualization V4 Factor Tear Sheet
OPS   Production Reserve Execution (independent human operation)
P1    A6 Strategy Freeze / Promotion / Internal PAPER — RESERVE_PASS only
P1    Corporate Action + Capacity hardening before sustained PAPER
P1.5  Visualization V5 Risk / Attribution / Signed Audit
P2    QMT R0-R4 realtime / external PAPER
```

资源排序原则不变：

```text
reserve correctness
> accounting/execution correctness
> evidence identity
> product interpretability
> realtime breadth
```

---

# 3. Visualization V3 — Agent Workbench

**当前产品主线 / P1**

V3 的目标不是复制 Phoenix，也不是复制聊天 UI；目标是把 canonical Agent audit 投影为类似 Codex 的**研究任务工作台**。

现有 `AgentRunProjection` 已冻结以下基础语义：

```text
run_id / task_id
project_id / thread_id
actor / trigger_type
status / objective
items[]
artifact_ids
token_usage / latency
governance / error
```

以及 item vocabulary：

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

V3 必须复用该 canonical projection，不允许 React 直接消费 Phoenix/OTLP span 作为产品语义。

## 3.1 V3-1 — Agent Index Contract

建议分支：

```text
feature/v3-agent-index
```

新增只读、derived 产品投影：

```text
AgentProjectProjection
AgentThreadProjection
AgentRunSummary
AgentArtifactRef
```

目标关系：

```text
Project
 └── Thread
      ├── Run
      ├── Run
      └── Run
```

要求：

- canonical source 仍为现有 Agent audit SQLite；
- `project_id` / `thread_id` 缺失时使用确定性 fallback，不修改 canonical store；
- project/thread/run 排序确定；
- conflicting identity fail closed；
- SQLite 只读打开；
- 不从 Phoenix 构造 project/thread identity；
- artifact refs 只指向可验证 evidence/source identity。

新增 GET-only API，建议：

```text
GET /api/v3/agent/projects
GET /api/v3/agent/projects/{project_id}
GET /api/v3/agent/threads/{thread_id}
GET /api/v3/agent/runs/{run_id}
```

验收：

- multi-run/multi-thread fixtures；
- deterministic fallback identity；
- empty/missing metadata；
- corrupted audit payload fail closed；
- Windows/Ubuntu API tests。

## 3.2 V3-2 — Workbench Shell

建议分支：

```text
feature/v3-agent-workbench-shell
```

产品布局冻结为 desktop-first 三栏：

```text
┌──────────────────┬──────────────────────────────┬───────────────────────┐
│ Projects/Threads │ Activity                     │ Inspector             │
│                  │                              │                       │
│ ResearchProgram  │ PLAN / TOOL / GUARDRAIL      │ Evidence              │
│  Thread           │ EVIDENCE / DECISION          │ Artifact              │
│   Run ●           │ RESULT / ERROR / APPROVAL    │ Governance            │
└──────────────────┴──────────────────────────────┴───────────────────────┘
```

输入框不是主界面要求；允许无输入运行来源：

```text
manual
research_program
schedule
system
market_event
```

第一版只做 persisted run review，不要求 active streaming。

## 3.3 V3-3 — Evidence / Artifact Deep Link

建议分支：

```text
feature/v3-agent-evidence-artifacts
```

必须形成：

```text
Agent Run
   ↕
Factor Evidence
   ↕
ResearchProgram
   ↕
A4 Portfolio / Execution
   ↕
A5 Reserve Evidence
```

要求：

- Agent timeline 的 evidence ID 可直接进入对应 Workspace evidence page；
- Factor / Research / A4 / Reserve 页面可反向展示 originating Agent run（只有存在可验证 identity 时）；
- source code / accepted generated feature 通过 artifact inspector 展示；
- code view 只展示已持久化 artifact，不展示隐藏 reasoning；
- Phoenix 只作为 low-level diagnostic deep link。

## 3.4 V3-4 — Active Run SSE

建议分支：

```text
feature/v3-agent-stream
```

前提：V3-1～V3-3 的 persisted projection 已稳定。

流式架构：

```text
canonical Agent audit/event source
        ↓
AgentActiveRunProjection
        ↓
SSE
        ↓
browser
```

禁止：

```text
React ← raw OTLP span
React ← provider-specific callback
React ← hidden reasoning token stream
```

SSE 只承载稳定产品 item vocabulary；Phoenix 继续承载 span-level diagnostics。

## 3.5 V3-5 — Acceptance

建议分支：

```text
feature/v3-agent-acceptance
```

最低 Gate：

```text
Project → Thread → Run navigation       PASS
Activity Timeline                       PASS
Evidence deep links                     PASS
Artifact Inspector                      PASS
Governance/Approval projection          PASS
Phoenix diagnostic deep link            PASS
Hidden reasoning absent                 PASS
GET-only product API                     PASS
No reserve/promotion/order authority    PASS
Windows API                              PASS
Ubuntu API                               PASS
ruff / mypy                              PASS
TypeScript / Vitest                      PASS
Vite production build                   PASS
Playwright                               PASS
full repository pytest                   PASS
```

V3 完成定义：用户能够在不理解 raw audit JSON/OTLP 的前提下，从业务语义上回答“Agent 正在/曾经做什么、产出了什么 evidence、为什么被 guardrail 阻断、结果落到了哪个金融研究对象”。

---

# 4. Visualization V4 — Factor Tear Sheet V2

**P1，可从 V3 中期并行。**

V4 的主要风险在 authoritative series，而不是前端图形库。

## 4.1 V4-1 — FactorSeriesEvidence

建议分支：

```text
feature/v4-factor-series-evidence
```

如果 core 当前未正式持久化以下序列：

```text
Q1–Q5 cumulative return/NAV
long-short cumulative return/NAV
daily turnover
daily coverage
horizon IC series
```

则新增 `FactorSeriesEvidence`，由 research core 生成 authoritative series。

浏览器禁止仅从汇总 metrics 推造这些累计曲线。

## 4.2 V4-2～V4-5

推荐拆分：

```text
V4-2 IC / rolling / fold-year heatmap / decay
V4-3 HAC / bootstrap forest + Holm/BH matrix
V4-4 quantile / long-short / turnover / coverage
V4-5 correlation cluster + Agent discovery evolution
```

最终 Factor Tear Sheet 至少回答：

```text
Does the factor predict?
Is it stable across folds/time?
Does the signal decay?
Is the quantile relation monotonic?
Does transaction turnover destroy the edge?
Is significance robust after multiplicity correction?
Is the factor redundant with the frozen family?
How did Agent discovery evolve toward this factor?
```

## 4.3 V4 Acceptance

- only authoritative/explicit derived data；
- no browser-side research rerun；
- factor identity preserved through every panel；
- Agent round → candidate → frozen family lineage available；
- cross-platform API/frontend CI green。

---

# 5. Production Reserve Execution — Independent OPS Gate

这不是 feature PR，也不是 CI task。

在真正执行前必须完成独立 checklist：

```text
clean working tree
exact reviewed Git SHA
exact data_version
A2.6 exact replay PASS
A4 exact replay PASS
V2 review bundle digest reviewed
production ReserveEligibilitySeal independently reviewed
A5-3 eligibility/consumption/terminal store locations archived
operator identity recorded
reserve interval and pass/fail policy rechecked
```

然后只允许：

```text
one seal
one execution identity
one reserve interval
one durable CONSUMED claim
one terminal PASS/FAIL
```

结果分支：

```text
RESERVE_PASS → A6 eligible
RESERVE_FAIL → no promotion; same reserve never reused for modified strategy validation
```

A5-4 Workspace 用于独立 post-execution audit，不提供执行/恢复按钮。

---

# 6. Phase A6 — Strategy Freeze / Promotion / Internal PAPER

**条件：仅 `RESERVE_PASS` 后启动。**

建议拆分：

```text
A6-1 FinalStrategySpec
A6-2 Immutable Registry + Promotion Gate
A6-3 Internal PAPER Runtime
A6-4 Reconciliation / Recovery / Kill Switch
A6-5 Operational Acceptance
```

## 6.1 A6-1 FinalStrategySpec

冻结至少：

```text
A2.6 ResearchProgram identity
A3 execution semantics
A4 portfolio validation identity
A5 terminal evidence identity
AlphaModel
RiskModel
Optimizer
rebalance policy
fee/slippage assumptions
risk/exposure limits
code/data identity
```

## 6.2 A6-2 Promotion

- deterministic gate；
- immutable registry；
- explicit human approval；
- Agent 无 promotion authority。

## 6.3 A6-3 PAPER

重复 session 的主要目标是 operational correctness，不是继续搜索 alpha。

必须形成：

```text
desired order
→ broker-facing order
→ fill/reject/partial
→ fee
→ position
→ cash
→ NAV
→ reconciliation
```

## 6.4 A6-4 Operational Safety

必须覆盖：

```text
idempotency
stale-data rejection
position/exposure limits
partial fill/reject
restart/recovery
kill switch
manual approval boundary
incident ledger
incident replay
```

## 6.5 A6 Acceptance

至少经过重复 PAPER session 后才能讨论 external broker integration。单次 PAPER PASS 不等同于 operational readiness。

---

# 7. Research / Data Hardening

本线不抢占 V3，但其中两项在 sustained PAPER 前提升为 P1。

## 7.1 DH-1 Corporate Action / Cash Event — P1

新增：

```text
CorporateActionEvent
CashEvent
```

正式验证：

```text
adjusted-price research return
vs
raw-price execution + cash/event accounting
```

目标：避免长期 PAPER 中 research PnL 与 broker/accounting PnL 无法解释。

## 7.2 DH-2 Capacity / Impact v1 — P1

从 ex-post participation diagnostics 升级为预注册：

```text
lagged liquidity
participation cap
impact proxy
```

禁止使用完整当日成交量决定当日成交。

## 7.3 DH-3 Security Master — P1.5

继续完善 delisting、ST history、suspension history、source-bound supplemental records，不修改 vendor Parquet。

## 7.4 DH-4 Intraday Certification — P1.5/P2

正式分钟研究前必须认证：

```text
5m / 15m / 30m / 60m timestamp convention
bar start/end semantics
auction handling
session boundary
```

---

# 8. Visualization V5 — Risk / Attribution / Signed Audit

**P1.5，core evidence 先行。**

第一批：

```text
covariance / correlation
concentration
realized exposure
drawdown attribution
ResearchProgram / protocol comparison
signed immutable audit package
```

后续仅在 core 正式生成 authoritative evidence 后增加：

```text
marginal/component risk contribution
factor exposure
stress scenario
benchmark / industry / style attribution
efficient frontier research views
```

前端不承担 risk math authority。

---

# 9. QMT Realtime 独立开发线

QMT 不复用历史 `ResearchDataset` 作为实时事件协议，也不阻塞 V3/V4 或历史研究。

## R0 — Event Contract

建议在 A6 internal order/fill semantics 稳定后启动。

冻结：

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

callback 禁止因子计算、组合优化、重数据库操作和阻塞式前端推送。

## R2 — Projection / State Store

第一版：

```text
Latest state → memory / optional Redis
Event log    → append-only Parquet
Analysis     → DuckDB
```

不预先引入 Kafka/Flink/ClickHouse。

## R3 — Live Workspace

页面：

```text
Market
Strategy
Portfolio
Execution
System Health
```

浏览器通过 WebSocket 消费 projection，不直连 QMT。

## R4 — External PAPER

重点：

```text
market data freshness
callback latency
partial fill / reject
disconnect/reconnect
account/position reconciliation
internal vs broker state drift
incident replay
```

Live capital 继续 deferred。

---

# 10. 并行计算与性能线

现有自动 CPU/RAM-aware parallel runtime 保留。后续性能工作遵循 profiling-first：

```text
profile representative workload
→ identify independent deterministic units
→ parallelize only stateless/isolated work
→ keep evidence identity independent of worker count
→ benchmark before/after
```

优先候选：

```text
cross-candidate evaluation
cross-fold deterministic statistics
bootstrap scenario batches
read-only evidence indexing
```

继续保持串行/事务化：

```text
governance mutation
reserve claim
promotion
registry mutation
broker/accounting mutation
shared evidence identity writes
```

---

# 11. CI / Acceptance 统一要求

每个 bounded PR 至少根据改动面包含：

```text
unit
contract
integration
identity/replay
cross-platform where relevant
```

## Visualization / V3 / V4 / V5

```text
Python semantic/API
GET-only route inventory
unsupported/corrupt schema fail closed
TypeScript unit tests
production build
Playwright navigation/deep-link
Windows + Ubuntu
legacy regression where touched
```

## A6/PAPER

```text
idempotency
partial/reject
reconciliation
stale market data
restart/recovery
kill switch
human approval
incident replay
```

## QMT

```text
event ordering/sequence
duplicate callback handling
staleness
connection lifecycle
partial/reject
disconnect/reconnect
projection replay
broker reconciliation
```

不得因为新产品 UI 通过就绕过数值/replay/accounting tests。

---

# 12. PR / Branch 策略

保持 bounded PR：一个核心 contract 或一个完整产品能力。

推荐：

```text
docs/planning-baseline-v3

feature/v3-agent-index
feature/v3-agent-workbench-shell
feature/v3-agent-evidence-artifacts
feature/v3-agent-stream
feature/v3-agent-acceptance

feature/v4-factor-series-evidence
feature/v4-factor-stability
feature/v4-factor-statistics
feature/v4-factor-performance
feature/v4-discovery-lineage
feature/v4-acceptance

feature/a6-final-strategy
feature/a6-promotion
feature/a6-paper-runtime
feature/a6-operational-safety
feature/a6-acceptance

feature/data-corporate-actions
feature/data-capacity-impact

feature/qmt-event-contract
feature/qmt-gateway
feature/qmt-projection
feature/qmt-live-workspace
feature/qmt-external-paper
```

单 PR 原则：

- 不混入无关 research tuning；
- schema/contract 变化必须包含 tests/docs；
- main CI green 后才进入依赖该 contract 的下一阶段；
- production reserve execution 不通过 feature PR/CI 自动触发；
- merge 采用 squash，避免运输/修复提交污染主线。

---

# 13. 当前立即执行顺序

本规划冻结后立即进入：

```text
V3-1 Agent Index Contract
      ↓
V3-2 Workbench Shell
      ↓
V3-3 Evidence / Artifact Deep Link
      ├────────→ V4-1 FactorSeriesEvidence
      ↓
V3-4 Active Run SSE
      ↓
V3-5 Acceptance
```

建议近期开发资源分配：

```text
V3 Agent Workbench        60%
V4 Factor Evidence        25%
tests/docs/refactor       15%
```

QMT R1+ 暂不作为主要开发工作。当前最有价值的增量是把已有 Agent、Factor、Portfolio、Execution、Reserve evidence 组织为可长期使用、可追溯的 Agent-driven Quant Research Workspace。

---

## 14. Planning Baseline v3 Exit Criteria

本规划可视为冻结仅当：

- `roadmap.md` 指向本 v3 文档；
- README 不再把 A5-4 描述为 future；
- A5 开发基础设施与 production reserve operation 被明确分离；
- V3-1～V3-5 的 contract/产品/stream/acceptance 边界明确；
- V4、A6、Data Hardening、QMT 的依赖顺序明确；
- 文档 PR 合并后 `main` CI 保持 green。

满足后，新的正式开发起点为 **V3-1 Agent Index Contract**。

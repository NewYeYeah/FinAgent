# Visualization Architecture V2

Status: **V0 semantic contract**

FinAgent visualization is an evidence-navigation surface. It does not own research, execution, promotion or capital authority.

## 1. Decision

The product direction is:

```text
                         FinAgent Core
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
       A2/A2.6 JSON          A4 JSON        Agent Audit SQLite
          │                   │                   │
          │              A4 Ledger JSONL          │
          │                   │                   │
          └─────────────┬─────┴─────────────┬─────┘
                        ▼                   ▼
                 Evidence Adapters    Agent Projection
                        │                   │
                        └─────────┬─────────┘
                                  ▼
                        Semantic Contract V1
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           ▼
             legacy Streamlit          future FastAPI API
             diagnostic UI                    │
                                               ▼
                                      React/TypeScript Workspace

Agent OTLP/JSONL ─────────────────────────────→ Phoenix
                                             diagnostic only
```

The current Streamlit application remains supported as a read-only diagnostic and regression viewer. It is not the long-term product contract. The future React/FastAPI Workspace must consume the semantic contract rather than internal A2.6/A4/Phoenix schemas directly.

## 2. Authority boundary

Four rules are mandatory.

### Visualization never computes authoritative evidence

Sharpe, IC, statistical gates, execution decisions, reserve state and promotion decisions remain owned by FinAgent core. A UI may format or derive non-authoritative presentation series such as drawdown from an authoritative NAV series, but that output must be marked `derived`.

### Visualization never mutates research state

V0/V1 expose no operation that:

- changes prompts or factor code;
- reruns Factor Quant;
- changes a gate or execution assumption;
- modifies ResearchProgram state;
- consumes a reserve;
- promotes a strategy;
- submits an order.

Any future research action must fork a new immutable ResearchProgram/protocol identity.

### Agent UI never exposes hidden reasoning

The canonical Agent workbench projection contains governed actions, evidence references, decisions, results, errors and approvals. Hidden model reasoning is neither persisted nor projected.

### Every product result is lineage-addressable

A visible result must be traceable to an immutable evidence identity. The semantic layer therefore treats lineage as a first-class contract rather than a display-only table.

## 3. Canonical evidence contract

`finagent.visualization.semantic` defines:

```text
EvidenceRef
EvidenceBundle
FactorEvidence
FoldEvidence
PortfolioEvidence
ExecutionEvidence
LineageNode
LineageEdge
LineageGraph
```

An `EvidenceRef` carries:

```text
evidence_id
evidence_type
schema_version
stage
authority
artifact_digest
source_uri
parent_ids
program_id
spec_id
data_version
git_sha
metadata
```

The authority values are:

```text
authoritative  produced by FinAgent core and identity-bound
derived        deterministic presentation projection from authoritative evidence
diagnostic     debugging/observability evidence such as low-level trace metadata
```

V0 adapters support:

- `finagent.ashare-factor-research-acceptance.v*`;
- `finagent.ashare-robust-research-program.v1`;
- `finagent.ashare-portfolio-validation.v1`.

Unsupported schemas fail closed.

## 4. Lineage semantics

`parent_ids` mean "this evidence depends on these immutable parents". The UI edge direction is parent → child.

A2.6 projects approximately as:

```text
ResearchProgramSpec
        ↓
WalkForwardReport
        ↓
PreregisteredGate
        ↓
FrozenFactorSelection
        ↓
ResearchProgramResult
```

A4 projects as:

```text
A2.6 ResearchProgramResult
        ↓
A4 ValidationSpec
        ↓
ExecutionLedger
        ↓
A4 PortfolioValidationResult
```

The semantic graph rejects missing parents, duplicate identities and cycles.

## 5. AgentRunProjection

The canonical UI projection is built from `SQLiteAgentAuditStore`, not from Phoenix spans.

```text
AgentRunProjection
├─ run_id / task_id
├─ project_id? / thread_id?
├─ trigger_type
├─ actor
├─ status
├─ started_at / finished_at
├─ objective
├─ items[]
├─ artifact_ids[]
├─ token_usage
├─ latency_ms
├─ governance
└─ error
```

Items use a stable product vocabulary:

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

The current Agent audit schema natively projects `RUN_STARTED`, `TOOL_REQUESTED`, `POLICY_DECIDED`, `TOOL_FINISHED` and `RUN_FINISHED`. Phoenix remains the low-level span inspector for model/provider/repair/sandbox latency and token diagnostics.

The audit SQLite file is opened in read-only/query-only mode by the projection layer.

## 6. FinWidgetSpec

`FinWidgetSpec` is the stable product-facing widget contract for V1+.

```text
widget_id
version
surface
question
evidence_types
data_endpoint
data_schema
renderer
parameters
link_keys
lineage_refs
authority
ai_visible
metadata
```

A widget is defined by the financial/research question it answers, not merely by chart type.

V0 freezes the first semantic widget catalog, including:

- ResearchProgram overview;
- factor evidence matrix;
- preregistered gate matrix;
- statistical forest view;
- A4 gross/net NAV;
- A4 drawdown;
- A4 order funnel;
- A4 rejection attribution;
- governance lineage;
- Agent run activity.

The `/api/v1/...` paths in the specs are logical V1 contracts. V0 does not start FastAPI and does not create write endpoints.

## 7. Product surfaces

The long-term information architecture is:

```text
FinAgent Workspace
│
├── Agent
│   ├── Projects
│   ├── Runs
│   ├── Activity
│   └── Artifacts
│
├── Research
│   ├── Overview
│   ├── Discovery
│   ├── Factor Lab
│   ├── Ensemble
│   ├── Portfolio
│   ├── Execution
│   ├── Risk
│   ├── Universe
│   └── Governance
│
└── Live
    ├── Market
    ├── Strategy
    ├── Portfolio
    ├── Execution
    └── System Health
```

V0/V1 focus on Agent + Research. `Live` is a separate future realtime projection and must not reuse historical report semantics as a stream protocol.

## 8. Implementation sequence

```text
V0  Semantic Contract             ← current
V1  FastAPI read-only API + React shell
V2  A4 Portfolio / Execution + Governance / Lineage
A5  One-shot reserve
V3  Codex-like Agent Workbench
V4  Factor Tear Sheet V2
A6  Strategy freeze / PAPER
V5  Risk / Attribution / evidence export
R0  QMT event contract
R1+ QMT shadow/PAPER surfaces
```

Streamlit remains available until the new Workspace has functional parity for diagnostic workflows.

## 9. Acceptance criteria for V0

V0 passes only if:

1. A2/A2.6/A4 reports project into stable evidence bundles;
2. A2.6 → A4 lineage preserves authoritative identities;
3. unsupported report schemas fail closed;
4. lineage rejects missing parents, duplicates and cycles;
5. Agent audit projection performs no SQLite writes;
6. hidden reasoning is absent from the public Agent projection;
7. widget IDs/link parameters are deterministic and validated;
8. all existing Streamlit and project-wide tests remain green;
9. no reserve, promotion or trading authority is added.

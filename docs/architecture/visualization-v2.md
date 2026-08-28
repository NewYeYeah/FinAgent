# Visualization Architecture V2

Status: **V1 read-only Workspace foundation**

FinAgent visualization is an evidence-navigation surface. It does not own research, execution, promotion or capital authority.

## 1. Decision

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
             legacy Streamlit          FastAPI GET-only API
             diagnostic UI                    │
                                               ▼
                                      React/TypeScript Workspace

Agent OTLP/JSONL ─────────────────────────────→ Phoenix
                                             diagnostic only
```

The Streamlit application remains supported as a read-only diagnostic/regression viewer. The React/FastAPI Workspace is the primary V1 product surface and consumes the semantic contract rather than internal A2.6/A4/Phoenix schemas directly.

## 2. Authority boundary

### Visualization never computes authoritative evidence

Sharpe, IC, statistical gates, execution decisions, reserve state and promotion decisions remain owned by FinAgent core. A UI may format or derive non-authoritative presentation series such as drawdown from an authoritative NAV series, but that output must be marked `derived`.

### Visualization never mutates research state

V0/V1 expose no operation that:

- changes prompts or factor code;
- reruns Factor Quant;
- changes a Gate or execution assumption;
- modifies ResearchProgram state;
- consumes a reserve;
- promotes a strategy;
- submits an order.

Any future research action must fork a new immutable ResearchProgram/protocol identity.

### Agent UI never exposes hidden reasoning

The canonical Agent projection contains governed actions, evidence references, decisions, results, errors and approvals. Hidden model reasoning is neither persisted nor projected.

### Every product result is lineage-addressable

A visible result must be traceable to an immutable evidence identity. Lineage is a first-class contract rather than a display-only table.

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

The authority values are:

```text
authoritative  produced by FinAgent core and identity-bound
derived        deterministic presentation projection from authoritative evidence
diagnostic     debugging/observability evidence such as low-level trace metadata
```

Supported adapters:

- `finagent.ashare-factor-research-acceptance.v*`;
- `finagent.ashare-robust-research-program.v1`;
- `finagent.ashare-portfolio-validation.v1`.

Unsupported schemas fail closed.

## 4. Lineage semantics

`parent_ids` mean “this evidence depends on these immutable parents”. UI edge direction is parent → child.

A2.6:

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

A4:

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

The canonical UI projection is built from `SQLiteAgentAuditStore`, not Phoenix spans.

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

Items use:

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

The audit SQLite file is opened in read-only/query-only mode. Phoenix remains the low-level span inspector for model/provider/repair/sandbox latency and token diagnostics.

## 6. FinWidgetSpec

`FinWidgetSpec` is the product-facing widget contract.

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

A widget is defined by the financial/research question it answers, not only chart type.

## 7. V1 Evidence API

`finagent.visualization.workspace_api` exposes GET-only routes:

```text
/api/v1/health
/api/v1/catalog
/api/v1/evidence/{evidence_id}
/api/v1/programs
/api/v1/programs/{program_id}
/api/v1/portfolio-validations
/api/v1/portfolio-validations/{validation_id}
/api/v1/factors/{feature_digest}
/api/v1/lineage/{evidence_id}
/api/v1/widgets
/api/v1/agent/runs
/api/v1/agent/runs/{run_id}
```

The API has no research, reserve, promotion, PAPER or trading write route. CORS permits local Vite development origins and GET/HEAD/OPTIONS only.

The in-memory catalog is disposable. Source JSON/JSONL/SQLite artifacts remain authoritative. Unsupported files become warnings; conflicting payloads sharing one evidence identity are omitted.

## 8. V1 React Workspace

The production frontend lives under `workspace/` and uses:

```text
React + TypeScript + Vite
TanStack Table
ECharts
React Flow
```

V1 pages:

```text
Project Cockpit
Research Programs
Portfolio Validations
Evidence Detail
Factor Evidence
Agent Runs
Widget Catalog
```

A4 pages render authoritative NAV and execution evidence. Browser-derived drawdown is explicitly labelled derived.

The backend serves the built SPA from `workspace/dist`; Vite development mode proxies `/api` to the read-only FastAPI service.

## 9. Product surfaces

```text
FinAgent Workspace
│
├── Agent
│   ├── Runs                    V1
│   ├── Activity                V1
│   ├── Projects                V3
│   └── Artifacts               V3
│
├── Research
│   ├── Overview                V1
│   ├── Factor Lab              V1 foundation / V4 expansion
│   ├── Portfolio               V1 foundation / V2 cockpit
│   ├── Execution               V1 foundation / V2 cockpit
│   ├── Governance              V1 lineage / V2 expansion
│   ├── Discovery               V3/V4
│   ├── Risk                    V5
│   └── Universe                V2+
│
└── Live                        future realtime projection
```

`Live` must not reuse historical report semantics as a stream protocol.

## 10. Implementation sequence

```text
V0  Semantic Contract                                  ✓
V1  FastAPI read-only API + React Workspace foundation ✓
V2  A4 Portfolio / Execution + Governance cockpit      ← next
A5  One-shot reserve
V3  Codex-like Agent Workbench
V4  Factor Tear Sheet V2
A6  Strategy freeze / PAPER
V5  Risk / Attribution / evidence export
R0  QMT event contract
R1+ QMT shadow/PAPER surfaces
```

## 11. V1 acceptance criteria

V1 passes only if:

1. API projects A2/A2.6/A4 through the V0 semantic contract;
2. only GET/HEAD/OPTIONS product operations exist;
3. unsupported/malformed/conflicting evidence is not silently rendered;
4. report files and Agent SQLite are never modified;
5. A2.6 factor/Gate/fold evidence is navigable;
6. A4 gross/net NAV, costs and execution reasons are navigable;
7. derived browser series are labelled derived;
8. lineage is rendered from authoritative identities;
9. hidden reasoning is absent;
10. reserve and promotion status remain visible;
11. Python API, TypeScript, component, production-build and Playwright smoke tests pass;
12. legacy Streamlit tests remain green.

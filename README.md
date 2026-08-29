# FinAgent

FinAgent is an auditable Agent-assisted quantitative research framework. LLMs propose hypotheses and bounded feature code; deterministic components own data chronology, factor evaluation, portfolio construction, statistical validation, execution simulation and operational state.

## Current scope

The current baseline supports:

- point-in-time `ResearchDataset` / `ResearchSplit` contracts;
- bounded Agent-generated features with validation, restricted execution, repair and checkpointing;
- factor IC/RankIC/decay/quantile/turnover and stability/inference diagnostics;
- A2.6 immutable A-share ResearchPrograms with expanding walk-forward, robust gates, explicit no-alpha outcomes and exact replay;
- A3 exact-session A-share execution semantics including T+1, board quantity rules, suspension/price limits and asymmetric fees;
- A4 execution-aware internal portfolio validation with frozen-factor Alpha, risk, optimizer targets, gross/net ledgers and replay;
- A5 eligibility sealing, one-shot evaluation, crash-safe `CONSUMED`, terminal/ledger persistence and replay/audit;
- Alpaca SIP US reference ingestion and local A-share Parquet research;
- V2/A5 evidence review, V3 Agent Project → Thread → Run navigation and the V3-2 Workbench foundation;
- an explicit two-plane Workbench architecture: GET-only Evidence + local governed Control;
- legacy Streamlit/Plotly and optional Phoenix diagnostics retained.

The market priority remains **A-share historical research first**. A-share live capital/realtime acceptance remains deferred until frozen research, execution-aware validation, reserve governance and repeated PAPER gates are complete.

The next Workbench milestone is **V3-3 — Evidence / Artifact / Config Deep Link**. V3-2 is now complete as a governed command substrate; it does not promote unfinished research CLIs into remote execution authority.

## Quick start

Python 3.11+ is required.

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q
```

Optional dependencies:

```bash
python -m pip install -e ".[llm]"           # DeepSeek / SiliconFlow / OpenAI transport
python -m pip install -e ".[us-market]"     # Alpaca
python -m pip install -e ".[cn-free]"       # AKShare
python -m pip install -e ".[a-share]"       # Tushare
python -m pip install -e ".[local-parquet]" # local A-share Parquet / DuckDB
python -m pip install -e ".[observability]" # OTLP Agent trace exporter
python -m pip install -e ".[visualization]" # legacy Streamlit / Plotly inspector
python -m pip install -e ".[workspace]"     # FastAPI / Uvicorn Workbench APIs
```

## A-share research-to-execution flow

```text
Frozen local Parquet
        ↓
A2.6 robust ResearchProgram
        ↓
Frozen factor family / explicit no-alpha result
        ↓
A3 target-to-executable-order semantics
        ↓
A4 internal gross/net portfolio validation
        ↓
Visualization V2 + human review
        ↓
A5 eligibility / one-shot reserve governance
        ↓
Independent human-authorized production reserve operation
        ↓
RESERVE_PASS → A6 Strategy Freeze / PAPER
RESERVE_FAIL → no promotion; same reserve never reused for modified-strategy validation
```

A completed A4 report remains `promotion_eligible=false`. No production 2025+ reserve is consumed by development or CI.

## FinAgent Workbench V3-2

V3-2 implements two independent authority planes:

```text
Evidence Plane  127.0.0.1:8765
  GET-only / read-only projections

Control Plane   127.0.0.1:8766
  explicit local opt-in
  typed application_service_ready L0/L1 commands only
  durable CommandIntent → CommandRun → CommandResult audit
```

The Evidence Plane never acquires a command mutation route. Starting Control is a separate user action.

### Build the frontend

```bash
python -m pip install -e ".[workspace]"
cd workspace
npm ci
npm run build
cd ..
```

### Start the Evidence Plane

```bash
python scripts/run_workspace.py \
  --reports reports \
  --configs configs \
  --agent-audit .finagent/agent_audit.sqlite \
  --open-browser
```

Open `http://127.0.0.1:8765`.

### Explicitly start the local Control Plane

```bash
python scripts/run_workbench_control.py \
  --configs configs \
  --reports reports
```

Defaults:

```text
Control URL   http://127.0.0.1:8766
Command DB    .finagent/workbench/commands.sqlite
Export dir    .finagent/workbench/exports
```

The Control launcher refuses non-loopback hosts. When it is absent, the Workbench Commands button stays disabled and there is no fallback execution path.

### Current command readiness

Executable through the generic V3-2 Control Plane:

```text
config.validate              L0  application_service_ready
data.certify_local_ashare    L0  application_service_ready
review.export_bundle         L0  application_service_ready
```

Visible but deliberately non-executable:

```text
research.run_development     L1  adapter_required
research.run_a2p6            L1  adapter_required
portfolio.run_a4             L1  adapter_required
```

A2/A2.6/A4 remain `adapter_required` because their current scripts still own substantial orchestration. V3-2 does **not** use `subprocess`, arbitrary shell or browser-supplied Python to make them appear ready. Their readiness can change only in a reviewed change that extracts the real typed application service.

### Durable command semantics

`SQLiteCommandStore` persists intent/run/result/event state before and during execution. Request IDs are idempotency keys; conflicting reuse fails closed. On process restart, incomplete `planned`/`running` work becomes explicit terminal `failed` and is never automatically retried.

The Command Palette binds only typed inputs:

- exact `command_id`;
- approved ConfigSnapshot when required;
- allowlisted `WorkbenchContext`;
- explicit confirmation where required.

The browser cannot submit generic executable arguments, output filesystem paths, shell commands or Python code. Review-bundle report/output paths are injected server-side.

Generic Control authority explicitly excludes:

```text
production reserve
strategy promotion
PAPER mutation
broker order
live capital
arbitrary shell
arbitrary Python
```

## Current Workbench capabilities

- rebuildable derived Evidence Catalog and protocol comparison;
- A2.6 lifecycle, Gate matrix, statistical forest and fold evidence;
- A4 gross/net NAV, economic evidence and execution realization;
- A5 eligibility/consumption/terminal/ledger/audit inspection;
- Agent Project → Thread → Run navigation and verified artifact links;
- typed URL-backed `WorkbenchContext` across research/portfolio/Agent selections;
- public Config Registry with secret-file exclusion and recursive credential redaction;
- read-only Command Catalog with real readiness metadata;
- separate local Command Palette and persisted Run Inspector;
- context-preserving navigation and typed server-state cache/de-duplication boundary.

Configuration editing remains read-only. Protocol changes must become new governed identities/forks rather than rewriting historical evidence.

## Core boundary

```text
Provider / local data
        ↓
DataAdapter → ResearchDataset
        ↓
Agent hypothesis / generated feature
        ↓
Factor Quant / robust ResearchProgram
        ↓
Frozen multi-factor AlphaModel
        ↓
RiskModel → Portfolio Optimizer
        ↓
Market-specific execution rules
        ↓
Internal validation / reserve governance
        ↓
Human-approved paper/shadow operations
```

The Agent never owns positions, fills, risk limits, validation thresholds or broker state. The Evidence Plane never owns prompts, numerical evidence or lifecycle transitions. The generic Control Plane owns only allowlisted application-service invocation and its command audit; it does not become trading authority.

## Research / governance invariants

1. Features use only information available at `asof`.
2. Forward labels never define formation eligibility.
3. Failed/weak trials remain in the search denominator.
4. Frozen families replay without silent mutation.
5. Provider changes create new evidence identities; fallback is never silent.
6. Research and executable prices remain separate where required.
7. A software test pass or Control success is not evidence of persistent alpha/live readiness.
8. Viewing validation evidence cannot make the same window clean for a modified program.
9. A4 cannot consume reserve, alter A2.6 factor direction/weight or bypass A3 rules.
10. Portfolio/execution evidence must reproduce through exact identities.
11. Presentation derivatives never replace authoritative evidence.
12. Durable reserve `CONSUMED` is irreversible.
13. Protocol edits create new identities/forks rather than rewriting prior evidence.
14. Generic Workbench commands never receive reserve/promotion/PAPER/broker/live authority.
15. Workbench config projection never exposes credential values.
16. `application_service_ready` must match a real registered in-process service binding.
17. Command restart recovery never silently retries incomplete execution.

## Documentation

- [Getting started](docs/guides/getting-started.md)
- [Market data and local A-share datasets](docs/guides/data-sources.md)
- [Agent research workflow](docs/guides/agent-research.md)
- [A-share execution semantics](docs/guides/ashare-execution.md)
- [A-share portfolio validation](docs/guides/ashare-portfolio-validation.md)
- [FinAgent Workspace / Workbench](docs/guides/workspace.md)
- [A-share reserve governance](docs/guides/ashare-reserve.md)
- [Testing and acceptance](docs/testing/testing.md)
- [Architecture overview](docs/architecture/overview.md)
- [Workbench architecture v3.1](docs/architecture/workbench-v3.md)
- [Roadmap](docs/development/roadmap.md)
- [Changelog](docs/development/changelog.md)

## Data note

The local A-share database is treated as immutable vendor raw data. FinAgent normalizes units and time semantics but does not automatically trust undocumented vendor factors or claim survivorship-free coverage when delisting/list-status history is incomplete. Supplemental historical reference data remains separate from raw vendor data.

## License and data rights

FinAgent code and third-party market data have separate licensing/usage constraints. Users are responsible for complying with provider terms and entitlements. Do not commit API keys or paid/raw datasets to the repository.

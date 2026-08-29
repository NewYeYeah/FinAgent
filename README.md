# FinAgent

FinAgent is an auditable Agent-assisted quantitative research framework. LLMs propose hypotheses and bounded feature code; deterministic components own data chronology, factor evaluation, portfolio construction, statistical validation, execution simulation and operational state.

## Current scope

The current development baseline supports:

- point-in-time `ResearchDataset` / `ResearchSplit` contracts;
- Agent-generated features with AST validation, restricted execution, repair and checkpointing;
- factor diagnostics including IC, RankIC, IC decay, quantile portfolios and turnover;
- rolling/subperiod stability, HAC, block bootstrap and candidate-family multiplicity control;
- A2.6 immutable A-share ResearchPrograms with expanding walk-forward, preregistered robust gates, explicit no-alpha outcomes and exact replay;
- A3 exact-session A-share execution semantics including T+1, board quantity rules, suspension/price limits and asymmetric fees;
- A4 execution-aware internal portfolio validation with frozen-factor Alpha, historical risk, optimizer targets, gross/net ledgers and byte-identical replay;
- A5 eligibility sealing, deterministic one-shot evaluation, crash-safe pre-access `CONSUMED` state, terminal/ledger persistence and replay/audit;
- nested validation, DSR, PBO and Reality Check on the existing general research path;
- supervised paper/shadow operations and sealed-holdout/promotion primitives;
- US market ingestion through Alpaca SIP and best-effort AKShare validation;
- local A-share Parquet research through DuckDB-backed adapters;
- a read-only FastAPI + React/TypeScript Workbench with V2/A5-4 research/governance evidence, V3-1 deterministic Agent Project → Thread → Run indexing, and the V3-2A shared Workbench shell/context foundation;
- legacy Streamlit/Plotly and optional Phoenix low-level diagnostics retained.

The current market priority is **A-share historical research first**, with **Alpaca SIP as the US reference/regression path**. A-share live-capital or realtime acceptance is intentionally deferred until frozen research, execution-aware internal validation, one-shot reserve and repeated PAPER gates are complete.

The next product-development milestone is **Visualization V3-2B — Config Registry + Command Catalog**. V3-2A establishes the shared shell, context, panel registry and read-only Agent workbench substrate; V3-2B will add typed configuration and command catalog contracts without enabling a general execution endpoint. Production reserve execution remains a separate explicit human-authorized operation and is never triggered by development or CI.

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
python -m pip install -e ".[workspace]"     # FastAPI / Uvicorn Evidence API
```

For Windows and Ubuntu setup, credential configuration and provider-specific commands, see the guides below.

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
Visualization V2 acceptance + human review
        ↓
A5-1 ReserveEligibilitySeal
        ↓
A5-2 one-shot runner + terminal evidence
        ↓
A5-3 crash-safe CONSUMED state + replay/audit
        ↓
A5-4 read-only Workspace reserve evidence
        ↓
Independent human-authorized production reserve operation
        ↓
RESERVE_PASS → A6 Strategy Freeze / PAPER
RESERVE_FAIL → no promotion; same reserve never reused for modified-strategy validation
```

Run A4 only from an immutable A2.6 report:

```powershell
python scripts\run_ashare_portfolio_validation.py `
  configs\execution\ashare_portfolio_validation_a4.local.toml `
  --verify-content
```

A completed A4 report remains `promotion_eligible=false`. A5-1 seals the exact frozen A2.6/A4/replay/V2-review identity; A5-2 implements the deterministic final-training/reserve evaluation engine; A5-3 adds an irreversible, SQLite-transactional pre-access `CONSUMED` claim, durable terminal/ledger persistence, crash recovery without reserve re-access and lifecycle replay/audit; A5-4 projects those authoritative seal/claim/terminal/ledger/audit stores into the read-only Workspace. No production 2025+ reserve has been consumed by development or CI; actual execution still requires a reviewed production seal and explicit human authorization. See [`docs/guides/ashare-reserve.md`](docs/guides/ashare-reserve.md).

## FinAgent Workspace / Workbench direction

The current product surface remains a **read-only Evidence Plane** presented through the FinAgent Workbench shell. V2 provides governed A2.6/A4/ledger review projections; A5-4 adds reserve lifecycle inspection; V3-1 adds deterministic Agent Project/Thread/Run indexing; V3-2A adds the shared Workbench shell, URL-backed context bus, panel registry and Agent activity/inspector integration. Authoritative calculations and state transitions remain owned by FinAgent core.

Install and build:

```bash
python -m pip install -e ".[workspace]"
cd workspace
npm ci
npm run build
cd ..
```

Launch:

```bash
python scripts/run_workspace.py \
  --reports reports \
  --agent-audit .finagent/agent_audit.sqlite \
  --open-browser
```

Windows PowerShell uses the same command with backticks. Open `http://127.0.0.1:8765`.

Current Workbench capabilities include:

- a rebuildable derived SQLite Evidence Catalog and deterministic frozen-protocol comparison;
- ResearchProgram lifecycle, Gate matrix, statistical forest and fold evidence;
- A4 gross/net NAV, derived rolling review series, fold/economic evidence;
- digest-matched A4 JSONL desired → compiled/adjusted → executable → fill review;
- T+1/lot/suspension/limit/cash attribution, fill-level fee components and target-versus-realized weights;
- combined immutable A2.6 → A4 lineage, with A3 binding explicitly marked `derived` where no standalone A3 identity exists;
- downloadable human-review evidence bundles;
- authoritative A5 eligibility/consumption/terminal/ledger/audit inspection;
- a registry-driven Workbench shell with stable extension positions for Strategy, Factors, Portfolio, Execution, Risk, Operations, Evidence/Governance, Configuration and future Live surfaces;
- a typed `WorkbenchContext` with deterministic URL identity for Project/Thread/Run, Program/Factor/Portfolio/Strategy/Reserve, Asset/Date/Session/Fold and Environment selections;
- context-preserving module navigation and explicit linked-selection events that remain presentation state rather than evidence authority;
- V3-1 Agent Project → Thread → Run navigation, canonical persisted activity review and a Run Inspector with Workspace-verified artifact links;
- a shared identity-keyed typed server-state query provider with cache, request de-duplication, refetch and invalidation boundaries;
- disabled Config drawer and Command palette extension slots reserved for V3-2B/V3-2C;
- the `FinWidgetSpec` catalog.

It currently provides no endpoint or control for research reruns, prompt edits, Gate changes, reserve execution/recovery, promotion, PAPER mutation or order submission.

The active v3.1 plan preserves the GET-only **Evidence Plane** and introduces a future explicit opt-in **Control Plane**. V3-2B first adds read-only typed Config/Command catalogs; V3-2C then adds only allowlisted L0/L1 research control. The Control Plane will call FinAgent application services and will not expose arbitrary shell/Python execution. Research/execution protocol edits create new identities/forks rather than mutating historical evidence.

The same Workbench shell is planned to host linked quant charts. Large/authoritative financial series such as strategy decision paths and factor tear-sheet time series will be persisted by core before their interactive charts are implemented.

The earlier Streamlit/Plotly UI remains available as a diagnostic viewer:

```bash
python scripts/run_research_ui.py \
  --report reports/local_ashare_factor_research_a2p5.json \
  --feature-store .finagent/local-ashare-factor-a2p5/generated_features.sqlite \
  --trace .finagent/a2-agent-trace.jsonl
```

## Documentation

- [Getting started](docs/guides/getting-started.md)
- [Market data and local A-share datasets](docs/guides/data-sources.md)
- [Agent research workflow](docs/guides/agent-research.md)
- [A-share execution semantics](docs/guides/ashare-execution.md)
- [A-share execution-aware portfolio validation](docs/guides/ashare-portfolio-validation.md)
- [FinAgent Workspace](docs/guides/workspace.md)
- [Legacy research visualization and Phoenix](docs/guides/research-visualization.md)
- [Paper/shadow operations](docs/guides/paper-trading.md)
- [Testing and system acceptance](docs/testing/testing.md)
- [Architecture overview](docs/architecture/overview.md)
- [Visualization architecture V2](docs/architecture/visualization-v2.md)
- [FinAgent Workbench architecture v3.1](docs/architecture/workbench-v3.md)
- [Architecture decisions](docs/architecture/decisions.md)
- [Current development planning baseline v3.1](docs/development/current-development-plan-v3.1.md)
- [Historical post-A5 planning baseline v3](docs/development/current-development-plan-v3.md)
- [Historical V2/A5 development plan](docs/development/current-development-plan-v2.md)
- [Roadmap](docs/development/roadmap.md)
- [Changelog](docs/development/changelog.md)
- [Automatic parallel runtime](docs/development/parallel-runtime.md)
- [Risk register](docs/development/risks.md)

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
Market-specific target-to-executable-order rules
        ↓
Internal portfolio validation / reserve governance
        ↓
Human-approved paper/shadow operations
```

The Agent never owns positions, fills, risk limits, validation thresholds or broker state. The Evidence Plane never owns prompts, candidate generation, numerical evidence or lifecycle transitions. Future Workbench control actions must use typed command/config contracts and the existing governed application services rather than bypassing them.

## Research invariants

1. Features use only information available at `asof`.
2. Forward labels never define formation eligibility.
3. Failed and weak trials remain in the search denominator.
4. Frozen families are replayed without silent mutation.
5. Provider changes create new evidence identities; fallback is never silent.
6. Research prices and executable prices remain separate when corporate-action adjustment is required.
7. A software test pass is not evidence of persistent alpha or live-capital readiness.
8. Viewing validation evidence cannot turn the same window into clean validation for a modified ResearchProgram.
9. A4 cannot consume reserve, alter A2.6 weights/directions or bypass A3 execution rules.
10. Portfolio and execution evidence must reproduce through exact report and ledger identities.
11. Workspace presentation derivatives never replace authoritative FinAgent evidence.
12. A durable `CONSUMED` reserve is never made clean again by rename, restart or model mutation.
13. A Workbench protocol edit creates a new identity/fork; it never rewrites the protocol behind existing evidence.
14. Generic Workbench commands never receive production reserve or unrestricted broker/live-capital authority.

## Data note

The local A-share database is treated as immutable vendor raw data. FinAgent normalizes units and time semantics but does not automatically trust undocumented vendor factors or claim survivorship-free coverage when delisting/list-status history is incomplete. Supplemental historical reference data is maintained separately from the raw vendor dataset.

## License and data rights

FinAgent code and third-party market data have separate licensing/usage constraints. Users are responsible for complying with each provider's terms and entitlements. Do not commit API keys or paid/raw datasets to the repository.

# FinAgent

FinAgent is an auditable Agent-assisted quantitative research framework. LLMs may propose bounded hypotheses and feature code; deterministic components own chronology, data identity, factor evaluation, portfolio construction, statistical validation, execution simulation and operational state.

> **Project stage:** read [`docs/status.toml`](docs/status.toml). It is the only current-stage authority.
> **Development plan:** [`docs/development/current-plan.md`](docs/development/current-plan.md).

## What the repository currently provides

- point-in-time `ResearchDataset` / `ResearchSplit` contracts with separate `event_time` and `available_at` clocks;
- bounded Agent feature generation, validation, repair, checkpointing, audit and replay;
- factor IC/RankIC, decay, quantile, turnover, stability, HAC/bootstrap and multiplicity diagnostics;
- immutable A-share A2.6 ResearchPrograms with explicit robust-factor and no-alpha terminals;
- A-share A3 execution semantics and A4 execution-aware historical portfolio validation;
- immutable StrategyDecisionSeries, FactorSeries and MarketBarSeries evidence;
- A5 one-shot reserve governance infrastructure with crash-safe consumption semantics;
- a React/FastAPI Workbench with a GET-only Evidence Plane and separately governed local L0/L1 Control Plane;
- provider-neutral market-data ingestion scaffolding, local Parquet/DuckDB support and U.S. reference ingestion.

The A-share Historical v1.0 line is being closed as a historical release. New development then pivots to certified U.S. minute data, controlled Agent incremental-value experiments, broker-aware CFD historical validation, provider-neutral realtime contracts and MT5 demo/PAPER. Live-capital acceptance remains a separate human-governed milestone.

## Architecture

```text
External data / broker sources
        ↓
Provider adapters and immutable source evidence
        ↓
Bounded Data Plane → ResearchDataset materialization
        ↓
Research / Agent candidate generation
        ↓
Alpha / Risk / Portfolio / historical execution
        ↓
Immutable evidence and acceptance gates
        ↓
Workbench projections

future operational path:
Realtime events → replay/state projections → broker gateway → reconciliation/safety
```

The Agent never owns final portfolio or broker authority. Evidence is immutable and identity-bound; missing evidence remains unavailable rather than inferred.

## Install

Python 3.11+ is required.

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q
```

Optional extras:

```bash
python -m pip install -e ".[llm]"           # DeepSeek / OpenAI-compatible transport
python -m pip install -e ".[us-market]"     # Alpaca reference provider
python -m pip install -e ".[cn-free]"       # AKShare
python -m pip install -e ".[a-share]"       # Tushare
python -m pip install -e ".[local-parquet]" # DuckDB / local Parquet
python -m pip install -e ".[observability]" # OTLP Agent traces
python -m pip install -e ".[visualization]" # legacy read-only Streamlit viewer
python -m pip install -e ".[workspace]"     # FastAPI / Uvicorn Workbench API
```

Frontend:

```bash
cd workspace
npm ci
npm run typecheck
npm run test
npm run build
```

## Documentation

Start at [`docs/README.md`](docs/README.md).

- current status: [`docs/status.toml`](docs/status.toml)
- development plan: [`docs/development/current-plan.md`](docs/development/current-plan.md)
- architecture: [`docs/architecture/overview.md`](docs/architecture/overview.md)
- design decisions: [`docs/architecture/decisions.md`](docs/architecture/decisions.md)
- test strategy: [`docs/testing/strategy.md`](docs/testing/strategy.md)
- guides: [`docs/guides/`](docs/guides/)
- historical release records: [`docs/releases/`](docs/releases/)

Detailed phase-by-phase implementation history is intentionally not duplicated in the active documentation tree; use the aggregate changelog, Git commits and pull requests.

## Safety / authority boundary

FinAgent research completion, Alpha acceptance, portfolio acceptance, PAPER acceptance and live-capital acceptance are distinct states. A successful platform acceptance does not imply profitable Alpha, and a demo/PAPER result never grants live-capital authority automatically.

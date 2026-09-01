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

A-share Historical v1.0 is preserved as the accepted historical release `finagent-ashare-historical-v1.0`. New development pivots to certified U.S. minute data, controlled Agent incremental-value experiments, broker-aware CFD historical validation, provider-neutral realtime contracts and MT5 demo/PAPER. Live-capital acceptance remains a separate human-governed milestone.

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

The canonical development baseline is Python 3.11 (`.python-version`) resolved by uv 0.12.1 into `uv.lock`. `pyproject.toml` remains dependency intent; the lock is the reproducible resolution authority.

```bash
python -m pip install "uv==0.12.1"
uv lock --check
uv sync --frozen --extra dev
uv pip check
uv run --frozen python -m pytest -q
```

Optional extras use the same lock, for example:

```bash
uv sync --frozen --extra dev --extra llm
uv sync --frozen --extra dev --extra us-market
uv sync --frozen --extra dev --extra cn-free
uv sync --frozen --extra dev --extra a-share
uv sync --frozen --extra dev --extra local-parquet
uv sync --frozen --extra dev --extra observability
uv sync --frozen --extra dev --extra visualization
uv sync --frozen --extra dev --extra workspace
```

Frontend uses Node 22 (`.nvmrc`) with `workspace/package-lock.json` as the npm resolution authority:

```bash
cd workspace
npm ci
npm run typecheck
npm run test
npm run build
```

See [`docs/guides/getting-started.md`](docs/guides/getting-started.md) for the reproducible Ubuntu/Windows baseline and the MT5-prep boundary.

## Documentation

Start at [`docs/README.md`](docs/README.md). First-time readers should use [`docs/guides/project-onboarding.md`](docs/guides/project-onboarding.md); Agents may load [`skills/finagent-project/SKILL.md`](skills/finagent-project/SKILL.md) as the repository reading/documentation protocol.

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

# FinAgent

FinAgent is an Agent-driven quantitative research and trading workstation under active development. The current system combines deterministic minute-data research, typed factor/Agent experimentation, historical portfolio/execution evidence, an interactive Workbench, and reusable realtime/PAPER infrastructure.

The project currently has **no confirmed deployable Alpha and no PAPER/live-capital authority**. Read [`docs/status.toml`](docs/status.toml) for the only current-stage/authority statement.

## Start here

For a new developer or AI agent:

1. [`AGENTS.md`](AGENTS.md) — repository reading and implementation protocol;
2. [`docs/status.toml`](docs/status.toml) — current stage and compact accepted baseline;
3. [`docs/development/current-plan.md`](docs/development/current-plan.md) — active end-to-end roadmap;
4. the detailed stage file named by `stage_plan` in `docs/status.toml`.

Documentation index: [`docs/README.md`](docs/README.md).

## Current capability

The repository already includes:

- causal research/data contracts and out-of-core Parquet/DuckDB minute access;
- certified/local U.S. minute research infrastructure;
- typed FactorGraph and shared-DAG factor execution;
- statistical/economic factor evaluation;
- bounded Agent research runtime with typed actions and durable trial/budget accounting;
- deterministic portfolio and historical execution evidence;
- React/Vite Workbench with Strategy, Factor, Portfolio, Execution and Agent/evidence surfaces;
- provider-neutral realtime events, replay/database sources and projections;
- MT5 adapter work;
- PAPER, approval, reconciliation, safety and durable operation modules.

The next research program focuses on **MarketState + FactorLibrary + adaptive factor allocation + stronger Agent research agency**, followed by genuinely independent confirmation. See the active plan for exact stage state rather than treating this paragraph as stage authority.

## Architecture

```text
Historical/broker sources
        ↓
Data Plane / causal research materialization
        ↓
FactorGraph + Research Core ↔ Agent Runtime
        ↓
MarketState / Factor allocation (next research layer)
        ↓
Models / Portfolio / Historical Execution
        ↓
Evidence / application services
        ↓
Workbench

existing operational substrate:
Replay / MT5 → canonical events → projections → PAPER/reconciliation/safety
```

The Agent may gain substantial authority over **development research decisions**, but deterministic/human boundaries retain final statistical gates, sealed confirmation data, broker/account truth, reconciliation, safety and live-capital authority.

## Install

Canonical Python baseline:

```bash
python -m pip install "uv==0.12.1"
uv lock --check
uv sync --frozen --extra dev
uv pip check
uv run --frozen python -m pytest -q
```

Frontend baseline:

```bash
cd workspace
npm ci
npm run typecheck
npm run test
npm run build
```

See [`docs/guides/getting-started.md`](docs/guides/getting-started.md) for optional extras and Workbench startup.

## Documentation

The active documentation tree intentionally avoids historical stage-guide sprawl:

- current facts: [`docs/status.toml`](docs/status.toml)
- roadmap: [`docs/development/current-plan.md`](docs/development/current-plan.md)
- stage plans: [`docs/development/stages/`](docs/development/stages/)
- prior progress: [`docs/development/history.md`](docs/development/history.md)
- open limitations/debt: [`docs/development/backlog.md`](docs/development/backlog.md)
- architecture: [`docs/architecture/overview.md`](docs/architecture/overview.md)
- active decisions: [`docs/architecture/decisions.md`](docs/architecture/decisions.md)
- test strategy: [`docs/testing/strategy.md`](docs/testing/strategy.md)
- operator guides: [`docs/guides/`](docs/guides/)
- frozen release records: [`docs/releases/`](docs/releases/)

Exact implementation history belongs to Git commits and pull requests, not duplicate Markdown stage documents.

# Getting started

## Reproducible development baseline

ENG-0 defines one canonical developer environment identity while compatibility CI may still exercise newer supported Python versions.

```text
Python baseline: 3.11            (.python-version)
Python resolver: uv 0.12.1       ([tool.uv].required-version)
Python resolution: uv.lock
Node baseline: 22                (.nvmrc)
Frontend resolution: workspace/package-lock.json
```

`pyproject.toml` remains dependency intent. `uv.lock` is the resolved Python environment authority. Do not maintain a second hand-written requirements/conda lock as a competing authority.

Install the canonical resolver, verify the lock, reproduce the development environment, and run the suite:

```bash
python -m pip install "uv==0.12.1"
uv lock --check
uv sync --frozen --extra dev
uv pip check
uv run --frozen python -m pytest -q
```

Common optional extras remain part of the same lock and are enabled explicitly, for example:

```bash
uv sync --frozen --extra dev --extra llm
uv sync --frozen --extra dev --extra local-parquet
uv sync --frozen --extra dev --extra workspace
uv sync --frozen --extra dev --extra us-market
```

Python 3.12/3.13 CI is compatibility coverage, not a second canonical resolution authority.

## Workbench frontend

Use Node 22.x. `.nvmrc` records the current frontend developer/CI major baseline; `workspace/package-lock.json` is the npm resolution authority.

```bash
cd workspace
npm ci
npm run typecheck
npm run test
npm run build
```

Do not change npm install-script policy merely to silence warnings; dependency install scripts require an explicit review.

## Windows broker-prep boundary

The reproducibility gate also exercises the locked Python 3.11 environment and Node 22 frontend on Windows. The official `MetaTrader5` SDK is intentionally **not** an ENG-0 dependency: its optional dependency/import-safety and real terminal capability evidence belong to `MT5-P0`.

## Run the Workbench

Start the read-only Evidence Plane after installing the Workspace dependencies:

```bash
uv sync --frozen --extra dev --extra workspace --extra local-parquet
python scripts/run_workspace.py --reports reports --configs configs --open-browser
```

The separately governed local Control Plane is started explicitly:

```bash
python scripts/run_workbench_control.py --configs configs --reports reports
```

Do not treat Control as a generic shell or live-trading interface.

## Before starting new work

1. read [`../status.toml`](../status.toml);
2. read the active stage in [`../development/current-plan.md`](../development/current-plan.md);
3. preserve current architecture decisions unless the PR explicitly revises them;
4. declare documentation impact in the PR template;
5. run `python scripts/check_docs.py` when documentation changes.

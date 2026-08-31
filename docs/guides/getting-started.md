# Getting started

## Core development

Python 3.11+:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q
```

Common optional extras:

```bash
python -m pip install -e ".[llm]"
python -m pip install -e ".[local-parquet]"
python -m pip install -e ".[workspace]"
python -m pip install -e ".[us-market]"
```

## Workbench frontend

```bash
cd workspace
npm ci
npm run typecheck
npm run test
npm run build
```

Start the read-only Evidence Plane after installing the Workspace dependencies:

```bash
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

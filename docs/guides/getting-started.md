# Getting started

## 1. Read project context first

Before installing or changing code, read [`../../AGENTS.md`](../../AGENTS.md), then [`../status.toml`](../status.toml) and the current stage plan named there.

Do not infer the active stage from README prose, old PRs or historical release docs.

## 2. Python environment

Canonical baseline:

```text
Python 3.11
uv 0.12.1
uv.lock
```

Install and verify:

```bash
python -m pip install "uv==0.12.1"
uv lock --check
uv sync --frozen --extra dev
uv pip check
uv run --frozen python -m pytest -q
```

Common optional extras:

```bash
uv sync --frozen --extra dev --extra llm
uv sync --frozen --extra dev --extra local-parquet
uv sync --frozen --extra dev --extra workspace
uv sync --frozen --extra dev --extra us-market
```

`pyproject.toml` expresses dependency intent; `uv.lock` is the resolved environment authority.

## 3. Frontend environment

Canonical frontend baseline:

```text
Node 22
workspace/package-lock.json
```

```bash
cd workspace
npm ci
npm run typecheck
npm run test
npm run build
```

Use Playwright when the changed surface has browser acceptance requirements.

## 4. Workbench

Install Workspace dependencies:

```bash
uv sync --frozen --extra dev --extra workspace --extra local-parquet
```

Start the read-only Evidence Plane:

```bash
python scripts/run_workspace.py --reports reports --configs configs --open-browser
```

Start the separately governed local Control Plane only when needed:

```bash
python scripts/run_workbench_control.py --configs configs --reports reports
```

Control is typed application-service access, not a generic shell or broker/live interface.

See [`workbench.md`](workbench.md).

## 5. Broker/MT5 environment

Official MetaTrader5 integration remains environment-specific and is normally exercised on Windows with a terminal/account. Core research and replay development must remain usable without MT5.

See [`mt5-paper.md`](mt5-paper.md) before running broker-facing work.

## 6. Documentation check

After changing documentation:

```bash
python scripts/check_docs.py
python -m pytest -q tests/test_docs_governance.py
```

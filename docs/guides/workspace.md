# FinAgent Workspace

The FinAgent Workspace is the primary read-only product surface for immutable research, portfolio, execution and Agent-audit evidence. It does not own numerical calculations or lifecycle transitions.

## 1. Scope

V1 supports:

```text
A2 / A2.5 factor-acceptance reports
A2.6 robust ResearchProgram reports
A4 execution-aware portfolio-validation reports
canonical Agent audit SQLite
```

It provides:

- an Evidence catalog;
- A2.6 factor, fold, Gate and frozen-selection views;
- A4 gross/net NAV and portfolio metrics;
- derived drawdown clearly labelled as presentation-only;
- desired → executable → filled order realization;
- T+1, lot, suspension, limit, cash and other reason-code attribution;
- immutable lineage navigation;
- canonical Agent run timelines;
- the `FinWidgetSpec` product-question catalog.

It does not provide:

```text
LLM calls
prompt or feature-code editing
research reruns
Gate/threshold mutation
reserve access
promotion
PAPER control
order submission
```

## 2. Architecture

```text
Immutable A2/A2.6/A4 JSON
Canonical Agent audit SQLite
             │
             ▼
Visualization Semantic Contract
             │
             ▼
Read-only FastAPI /api/v1
             │
             ▼
React + TypeScript Workspace
```

Phoenix remains an optional, separate low-level inspector for LLM/provider/repair/sandbox traces. The Workspace consumes the canonical Agent audit projection, not Phoenix spans.

## 3. Prerequisites

- Python 3.11 or later;
- Node.js compatible with the committed Vite toolchain;
- npm;
- at least one supported report JSON for meaningful research pages.

Install the API surface:

```bash
python -m pip install -e ".[workspace]"
```

For development and tests:

```bash
python -m pip install -e ".[dev,workspace]"
```

## 4. Build the frontend

Ubuntu/macOS shell:

```bash
cd workspace
npm ci
npm run typecheck
npm run test
npm run build
cd ..
```

Windows PowerShell:

```powershell
Set-Location workspace
npm ci
npm run typecheck
npm run test
npm run build
Set-Location ..
```

The production bundle is written to:

```text
workspace/dist/
```

`node_modules/`, `dist/`, Playwright reports and test outputs are ignored by Git.

## 5. Launch

### Basic report catalog

Ubuntu:

```bash
python scripts/run_workspace.py \
  --reports reports \
  --open-browser
```

Windows PowerShell:

```powershell
python scripts\run_workspace.py `
  --reports reports `
  --open-browser
```

Open:

```text
http://127.0.0.1:8765
```

### Multiple report roots

Repeat `--reports`:

```powershell
python scripts\run_workspace.py `
  --reports reports `
  --reports D:\FinAgentEvidence\approved
```

Only `.json` files under configured roots are scanned. JSONL execution ledgers are represented through the A4 report's immutable ledger identity; V1 does not expose arbitrary filesystem paths.

### Agent audit

```powershell
python scripts\run_workspace.py `
  --reports reports `
  --agent-audit .finagent\agent_audit.sqlite
```

The SQLite database is opened with:

```text
mode=ro
PRAGMA query_only=ON
```

The Workspace cannot create or modify Agent audit rows.

### API-only mode

```bash
python scripts/run_workspace.py --reports reports --api-only
```

FastAPI documentation is available at:

```text
http://127.0.0.1:8765/docs
```

### Development mode

Terminal A:

```bash
python scripts/run_workspace.py --reports reports --api-only --reload
```

Terminal B:

```bash
cd workspace
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to `127.0.0.1:8765`.

## 6. Pages

### Project Cockpit

Shows all supported evidence roots with separate:

```text
system status
research/economic outcome
reserve status
promotion eligibility
```

Unsupported or malformed files appear as catalog warnings and are not silently rendered.

### Research

Shows A2/A2.5 and A2.6 artifacts. A2.6 factor rows retain the full candidate denominator, Gate status, selection, weights, directions, fold evidence and statistical metrics projected by FinAgent core.

### Portfolio

Shows A4 evidence:

```text
gross/net NAV
net/gross return
Sharpe
drawdown
cost drag
order realization
cash fallback
participation
reason-code attribution
```

The NAV series and A4 metrics are authoritative. Drawdown series drawn by the browser are labelled `DERIVED PRESENTATION SERIES`; they do not replace A4's authoritative maximum-drawdown metric.

### Agent Runs

Shows the canonical Action / Tool / Guardrail / Approval / Result / Error projection. Hidden reasoning is not persisted or displayed. Evidence identities in tool results can link back to research pages.

### Widget Catalog

Displays the frozen `FinWidgetSpec` definitions, including the question, data endpoint, renderer, authority and shared deep-link keys.

## 7. API overview

All product endpoints are GET-only:

```text
GET /api/v1/health
GET /api/v1/catalog
GET /api/v1/evidence/{evidence_id}
GET /api/v1/programs
GET /api/v1/programs/{program_id}
GET /api/v1/portfolio-validations
GET /api/v1/portfolio-validations/{validation_id}
GET /api/v1/factors/{feature_digest}
GET /api/v1/lineage/{evidence_id}
GET /api/v1/widgets
GET /api/v1/agent/runs
GET /api/v1/agent/runs/{run_id}
```

There are no write endpoints. `POST`, `PUT`, `PATCH` and `DELETE` are not part of the V1 contract.

## 8. Catalog behavior

The catalog is a disposable, in-memory read model rebuilt at service start.

- supported schemas are parsed through `finagent.visualization.semantic`;
- unsupported/malformed files become warnings;
- equivalent replay copies with the same identity are deduplicated;
- conflicting payloads sharing one evidence identity are omitted until resolved;
- adding a report requires a Workspace restart in V1.

Report JSON and canonical SQLite stores remain authoritative.

## 9. Tests

Python API tests:

```bash
python -m pytest -q tests/test_workspace_api_v1.py
```

Frontend tests:

```bash
cd workspace
npm ci
npm run typecheck
npm run test
npm run build
npx playwright install chromium
npm run e2e
```

Full test instructions and acceptance criteria are in `docs/testing/testing.md`.

## 10. Troubleshooting

### Frontend absent

```text
Workspace frontend is absent at workspace/dist
```

Run:

```bash
cd workspace
npm ci
npm run build
```

or start with `--api-only`.

### Empty catalog

Confirm that `--reports` points to a directory containing supported A2/A2.5, A2.6 or A4 `.json` reports. Check `/api/v1/catalog` for warnings.

### Agent page empty

Pass the canonical `SQLiteAgentAuditStore` path using `--agent-audit`. Phoenix trace databases are not valid Agent audit inputs.

### Identity conflict warning

Two non-equivalent files claim the same root evidence identity. Do not select one manually in the UI. Remove or archive the conflicting file after checking the upstream exact-replay and identity logic.

### Browser route returns the app shell

This is expected for frontend routes such as `/evidence/...`. Paths under `/api/v1` remain API-only and do not fall back to the SPA.

## 11. Governance

1. UI code does not calculate authoritative IC, Sharpe, Gate, reserve or execution decisions.
2. Presentation-only derivatives are labelled derived.
3. No page mutates ResearchProgram, A4, Agent audit or broker state.
4. Every product result remains lineage-addressable.
5. Reserve and `promotion_eligible=false` remain visible.
6. Viewing evidence does not create a new clean validation window.

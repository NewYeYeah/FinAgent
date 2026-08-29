# FinAgent Workspace

The FinAgent Workspace is the primary read-only product surface for immutable research, portfolio, execution and Agent-audit evidence. It does not own numerical calculations or lifecycle transitions.

## 1. Scope

V2/A5-4 supports:

```text
A2 / A2.5 factor-acceptance reports
A2.6 robust ResearchProgram reports
A4 execution-aware portfolio-validation reports
digest-matched A4 execution-ledger JSONL
A5 ReserveEligibilitySeal SQLite
A5 durable CONSUMED / consumption-audit SQLite
A5 terminal-evidence / immutable reserve-ledger SQLite
canonical Agent audit SQLite
```

It provides:

- a rebuildable derived SQLite Evidence Catalog in addition to the V1 in-memory catalog;
- governed Project lifecycle and immutable protocol comparison;
- A2.6 Gate Matrix, statistical forest and fold-evidence views;
- A4 gross/net NAV, portfolio/economic evidence and explicitly derived rolling review series;
- digest-matched desired → compiled/adjusted → executable → filled execution realization;
- T+1, lot, suspension, limit, cash, session/data and detailed fee attribution;
- target-versus-realized close weights and implementation-shortfall review;
- immutable lineage navigation plus an explicitly derived A3 protocol binding when no standalone A3 evidence identity exists;
- raw evidence inspection and downloadable human-review bundles;
- A5 Reserve Cockpit with eligibility, durable CONSUMED claim, terminal PASS/FAIL, ledger integrity and replay audit;
- canonical Agent run timelines and the `FinWidgetSpec` product-question catalog.

It does not provide:

```text
LLM calls
prompt or feature-code editing
research reruns
Gate/threshold mutation
reserve execution / recovery / retry
promotion
PAPER control
order submission
```

## 2. Architecture

```text
Immutable A2/A2.6/A4 JSON
A4 execution ledger JSONL
Canonical Agent audit SQLite
A5 lifecycle SQLite stores
             │
             ▼
Visualization Semantic Contract
             │
             ▼
Read-only FastAPI /api/v1 + /api/v2
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

By default V2 also rebuilds a disposable review index at `.finagent/visualization/evidence_catalog.sqlite`. Use `--no-catalog-db` to keep the derived index in memory only, or `--catalog-db <path>` to select another disposable index location. The authoritative report/ledger artifacts are never modified.

A5-4 auto-discovers these files when they exist:

```text
.finagent/a5/reserve_eligibility.sqlite
.finagent/a5/reserve_consumption.sqlite
.finagent/a5/reserve_terminal.sqlite
```

Override them with `--reserve-eligibility`, `--reserve-consumption` and `--reserve-terminal`. All three are opened by the Workspace with SQLite `mode=ro` / `PRAGMA query_only=ON`; the UI cannot create a claim, recover an interrupted run or execute the reserve.

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

### Agent Index (V3-1)

V3-1 adds a derived, read-only Project → Thread → Run index over the same canonical Agent audit SQLite. It does not add Project or Thread tables to the canonical store. Missing grouping metadata is resolved with deterministic fallback identities derived from existing audit identities only.

```text
Canonical Agent audit SQLite
        ↓
AgentRunProjection
        ↓
AgentProjectProjection
  └─ AgentThreadProjection
       └─ AgentRunSummary
```

Rules:

- explicit `project_id` / `thread_id` remain authoritative grouping hints from `AgentRunContext.metadata`;
- missing IDs use deterministic derived identities and never write back to SQLite;
- one thread resolving to conflicting projects fails closed;
- project/thread/run ordering is deterministic;
- artifact refs are emitted only when the ID is verified against Workspace evidence/factor identities; unknown audit strings remain unresolved rather than becoming product links;
- Phoenix/OTLP is not used to construct Project or Thread identity.

V3-1 is an index contract only. The Codex-style three-column Workbench UI is V3-2.

### Widget Catalog

Displays the frozen `FinWidgetSpec` definitions, including the question, data endpoint, renderer, authority and shared deep-link keys.

## 6.1 V2 review pages

The primary V2 navigation is:

```text
Research Governance Cockpit
A2.6 ResearchProgram Cockpit
A4 Portfolio Cockpit
Execution Realization Cockpit
Governance / Protocol Review
Raw Evidence Inspector
Review Bundle Export
```

The A3 lifecycle stage is shown as a `derived` protocol binding to A4 because the current core does not persist a standalone authoritative A3 certification evidence identity. V2 does not fabricate that identity in lineage.

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

V3-1 Agent Index endpoints are:

```text
GET /api/v3/agent/projects
GET /api/v3/agent/projects/{project_id}
GET /api/v3/agent/threads/{thread_id}
GET /api/v3/agent/runs/{run_id}
```

There are no write endpoints. `POST`, `PUT`, `PATCH` and `DELETE` are not part of the V1/V2/V3-1 product contract.

V2 review endpoints are:

```text
GET /api/v2/catalog
GET /api/v2/projects
GET /api/v2/programs/{program_id}/cockpit
GET /api/v2/programs/{program_id}/gates
GET /api/v2/programs/{program_id}/statistics
GET /api/v2/a4/{validation_id}/cockpit
GET /api/v2/a4/{validation_id}/execution
GET /api/v2/governance/{evidence_id}
GET /api/v2/protocol-diff?left=...&right=...
GET /api/v2/evidence/{evidence_id}/raw
GET /api/v2/a4/{validation_id}/review-bundle
```

The CLI equivalent of the review-bundle download is:

```bash
python scripts/export_workspace_review_bundle.py <validation_id> --reports reports
```

## 8. Catalog behavior

The catalog is a disposable, in-memory read model rebuilt at service start.

- A2/A2.6/A4 evidence plus local-data certification, local system-smoke and A3
  execution-smoke reports are parsed through `finagent.visualization.semantic`;
- unsupported/malformed files become warnings;
- equivalent replay copies with the same identity are deduplicated and exposed as
  informational notices rather than warnings;
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

Confirm that `--reports` points to a directory containing supported FinAgent evidence or
diagnostic `.json` reports. Check `/api/v1/catalog` separately for `warnings` (action
required) and `notices` (for example an equivalent replay that was safely deduplicated).

### Pytest crashes while importing Phoenix

If a local observability environment contains an old Phoenix pytest plugin, pytest may
fail before FinAgent tests are collected. FinAgent's `pytest.ini` blocks the `phoenix`
plugin because the project test suite does not depend on it. `python -m pytest ...` from
the repository root should therefore work directly. For a fully isolated diagnostic run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q tests/test_workspace_api_v1.py
```

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


### Reserve (A5-4)

The Reserve page separates historical A4 report-time status from current one-shot lifecycle state and shows:

```text
ReserveEligibilitySeal
  → durable CONSUMED claim
  → RESERVE_PASS / RESERVE_FAIL terminal
  → immutable reserve ledger (when completed)
  → replay / consumption audit
```

A consumed claim without terminal evidence is displayed as `CONSUMED_INTERRUPTED`. Workspace intentionally exposes no retry or recovery button; recovery remains an explicit core governance operation that must not re-open reserve observations.

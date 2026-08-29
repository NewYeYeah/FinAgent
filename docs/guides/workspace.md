# FinAgent Workspace / Workbench

FinAgent Workbench is the primary product surface for immutable research, portfolio, execution, reserve-governance and Agent-audit evidence. V3-2 adds a separately launched governed command plane without moving numerical authority into the browser.

## 1. Frozen authority model

V3-2 runs as two independent local processes:

```text
Evidence Plane  http://127.0.0.1:8765
  → default
  → GET-only product APIs
  → immutable evidence/config/command projections

Control Plane   http://127.0.0.1:8766
  → explicit opt-in launcher
  → local-loopback only
  → allowlisted application_service_ready L0/L1 commands
  → durable CommandIntent / CommandRun / CommandResult audit
```

The Evidence Plane never calls the Control Plane on the server and never gains a command mutation endpoint. The React client may connect to both processes, but execution is available only while the user explicitly runs the local Control Plane.

Generic Control Plane authority excludes:

```text
production reserve
strategy promotion
PAPER mutation
broker order
live capital
arbitrary shell
arbitrary Python
```

## 2. Current evidence scope

The Workbench projects:

```text
A2 / A2.5 factor-acceptance reports
A2.6 robust ResearchProgram reports
A4 execution-aware portfolio-validation reports
digest-matched A4 execution-ledger JSONL
A5 ReserveEligibilitySeal / CONSUMED / terminal / ledger stores
canonical Agent audit SQLite
public ConfigSnapshot / ConfigDiff metadata
CommandSpec metadata
persisted Control Plane CommandRun lifecycle
```

Existing V2/A5 functionality remains read-only: research/economic review, A2.6 gates/statistics/folds, A4 gross/net and execution realization, A5 lifecycle evidence, raw evidence inspection, review bundles, Agent Project → Thread → Run navigation and lineage.

## 3. Prerequisites

- Python 3.11+;
- Node.js compatible with the committed Vite toolchain;
- npm.

Install:

```bash
python -m pip install -e ".[dev,workspace]"
```

Build the frontend:

```bash
cd workspace
npm ci
npm run typecheck
npm run test
npm run build
cd ..
```

## 4. Launch the Evidence Plane

Ubuntu/macOS:

```bash
python scripts/run_workspace.py \
  --reports reports \
  --configs configs \
  --agent-audit .finagent/agent_audit.sqlite \
  --open-browser
```

Windows PowerShell:

```powershell
python scripts\run_workspace.py `
  --reports reports `
  --configs configs `
  --agent-audit .finagent\agent_audit.sqlite `
  --open-browser
```

Open `http://127.0.0.1:8765`.

This process remains GET-only. A5 SQLite stores, when present, are opened read-only. The V2 Evidence Catalog is disposable and rebuildable; report/ledger artifacts remain authoritative.

## 5. Explicitly enable the local Control Plane

The Control Plane is **not** started by `run_workspace.py`.

Ubuntu/macOS:

```bash
python scripts/run_workbench_control.py \
  --configs configs \
  --reports reports
```

Windows PowerShell:

```powershell
python scripts\run_workbench_control.py `
  --configs configs `
  --reports reports
```

Defaults:

```text
host        127.0.0.1
port        8766
store       .finagent/workbench/commands.sqlite
export dir  .finagent/workbench/exports
workers     2
```

`run_workbench_control.py` refuses non-loopback `--host` values. It is intentionally a local workstation control surface, not a remotely deployable broker/control service.

When the process is absent, the Workbench Commands button remains disabled and there is no fallback execution path.

## 6. V3-2 command semantics

The read-only Command Catalog currently contains:

```text
config.validate
data.certify_local_ashare
research.run_development
research.run_a2p6
portfolio.run_a4
review.export_bundle
```

Only code-backed `application_service_ready` entries may execute. At V3-2 completion those are:

```text
config.validate
data.certify_local_ashare
review.export_bundle
```

The following remain deliberately non-executable:

```text
research.run_development  adapter_required
research.run_a2p6         adapter_required
portfolio.run_a4           adapter_required
```

Their existing CLIs are still fat orchestration surfaces. V3-2 does **not** call them with `subprocess`, shell commands or browser-supplied Python. Each command must be separately extracted behind a reviewed typed application service before its readiness can change.

## 7. Durable command lifecycle

The Control Plane persists the lifecycle before execution:

```text
CommandIntent(validated/rejected)
        ↓
CommandRun(planned)
        ↓
CommandRun(running)
        ↓
CommandResult(succeeded/rejected/failed)
        └── ordered CommandEvent audit
```

The SQLite store uses transactional writes, WAL and `synchronous=FULL`.

Properties:

- client `request_id` is the idempotency key;
- replaying the same immutable request returns the same CommandRun;
- reusing the key with different command/config/context fails closed;
- exact `command_id`, `config_snapshot_id`, `WorkbenchContext` and actor are retained;
- evidence IDs, artifact paths and typed outputs are persisted as result metadata;
- an interrupted `planned`/`running` run becomes explicit `failed` on Control Plane restart;
- restart recovery never automatically retries the command.

V3-4 will replace UI polling with stable CommandRun SSE; the persistence model does not depend on SSE.

## 8. Command Palette / Run Inspector

The top-bar **Commands** button activates only after `GET :8766/api/v3/control/status` and the Control command projection are available.

The Palette shows:

- CommandSpec L0/L1 authority;
- `application_service_ready` versus `adapter_required`;
- ConfigSnapshot binding where required;
- current WorkbenchContext;
- explicit confirmation for commands that require it;
- produced evidence/artifact types;
- persisted CommandRun state and event history.

The browser does not send report-root or output filesystem paths for review export. The server injects configured report roots and writes bundles under the configured Control export directory.

Configuration itself remains read-only. V3-2 command execution does not provide in-place protocol editing; future protocol changes must use a governed identity/fork workflow.

## 9. API overview

### Evidence Plane — GET-only

Representative endpoints:

```text
GET /api/v1/catalog
GET /api/v1/evidence/{evidence_id}
GET /api/v2/projects
GET /api/v2/programs/{program_id}/cockpit
GET /api/v2/a4/{validation_id}/cockpit
GET /api/v2/a4/{validation_id}/execution
GET /api/v2/reserves/{reserve_id}
GET /api/v3/agent/projects
GET /api/v3/agent/threads/{thread_id}
GET /api/v3/agent/runs/{run_id}
GET /api/v3/config
GET /api/v3/config/diff
GET /api/v3/commands
```

`POST`, `PUT`, `PATCH` and `DELETE` remain outside the Evidence product contract.

### Control Plane — local and bounded

```text
GET  /api/v3/control/status
GET  /api/v3/control/commands
GET  /api/v3/control/runs
GET  /api/v3/control/runs/{command_run_id}
POST /api/v3/control/runs
```

The POST model uses `extra=forbid`. There is no generic `args`, `shell`, `python`, `executable`, `cwd`, arbitrary path or arbitrary environment field.

Unknown command IDs and catalogued `adapter_required` commands do not execute. When their request schema is otherwise valid, they are persisted as rejected audit records.

## 10. Development mode

Terminal A — Evidence API:

```bash
python scripts/run_workspace.py --reports reports --configs configs --api-only --reload
```

Terminal B — explicit Control API when needed:

```bash
python scripts/run_workbench_control.py --configs configs --reports reports --reload
```

Terminal C — frontend:

```bash
cd workspace
npm run dev
```

The frontend defaults Control discovery to `http://127.0.0.1:8766`. Override only for local development with `VITE_CONTROL_API_BASE`; the production launcher itself remains loopback-only.

## 11. Reserve / production boundary

A5 reserve lifecycle remains evidence-only in the Workbench. There is no generic Control command for reserve execution, recovery or retry.

```text
ReserveEligibilitySeal
  → durable CONSUMED claim
  → RESERVE_PASS / RESERVE_FAIL terminal
  → immutable reserve ledger
  → replay / consumption audit
```

A consumed claim without terminal evidence is shown as interrupted evidence. The Control Plane cannot reopen it.

## 12. Tests

Backend control/evidence tests are part of repository pytest. Frontend acceptance includes typecheck, Vitest, production build and Playwright.

Useful focused commands:

```bash
python -m pytest -q \
  tests/test_command_store_v32c2.py \
  tests/test_workbench_control_api_v32c.py \
  tests/test_workbench_config_command_v32b.py

cd workspace
npm run typecheck
npm run test
npm run build
npm run e2e
```

## 13. Governance invariants

1. UI code never recalculates authoritative IC, Sharpe, Gate, reserve or execution decisions.
2. Evidence Plane remains GET-only even when Control is running.
3. Control resolves exact allowlisted application services only.
4. No generic L2/L3 execution path exists.
5. Protocol/config edits do not mutate historical evidence identities.
6. Secret values remain host-bound; Workbench config projection never exposes credentials.
7. A software/Control command success is not evidence of alpha or live-capital readiness.
8. Production reserve and broker authority require their own later governance path.

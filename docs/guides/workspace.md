# FinAgent Workspace / Workbench

FinAgent Workbench is the primary product surface for immutable research, portfolio, execution, reserve-governance and Agent-audit evidence. V3-2 established a separately launched governed command plane; V3-3 added fail-closed typed deep links; V3-4 adds sanitized Agent/CommandRun SSE without moving numerical or execution authority into the browser.

## 1. Frozen authority model

The V3 Workbench runs as two independent local processes:

```text
Evidence Plane  http://127.0.0.1:8765
  → default
  → GET-only product APIs
  → immutable evidence/config/command projections
  → typed deep links / Artifact Inspector
  → sanitized Agent + CommandRun SSE

Control Plane   http://127.0.0.1:8766
  → explicit opt-in launcher
  → local-loopback only
  → allowlisted application_service_ready L0/L1 commands
  → durable CommandIntent / CommandRun / CommandResult audit
```

The Evidence Plane never calls the Control Plane on the server and never gains a command mutation endpoint. The React client may connect to both processes, but execution is available only while the user explicitly runs the local Control Plane. SSE is notification-only and never becomes execution authority.

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
V3-3 WorkbenchReference / bounded Artifact metadata
V3-4 AgentActiveRunProjection / CommandRunStreamProjection
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
  --command-store .finagent/workbench/commands.sqlite \
  --open-browser
```

Windows PowerShell:

```powershell
python scripts\run_workspace.py `
  --reports reports `
  --configs configs `
  --agent-audit .finagent\agent_audit.sqlite `
  --command-store .finagent\workbench\commands.sqlite `
  --open-browser
```

Open `http://127.0.0.1:8765`.

This process remains GET-only. A5 SQLite stores and CommandRun state are opened read-only. The command-store path can be configured before the Control Plane creates the file; when it appears, CommandRun deep-link/SSE reads become available without restarting Workspace. The V2 Evidence Catalog is disposable and rebuildable; report/ledger artifacts remain authoritative.

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

## 6. V3 command semantics

The read-only Command Catalog currently contains:

```text
config.validate
data.certify_local_ashare
research.run_development
research.run_a2p6
portfolio.run_a4
review.export_bundle
```

Only code-backed `application_service_ready` entries may execute. The current executable generic commands are:

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

Their existing CLIs are still fat orchestration surfaces. V3 does **not** call them with `subprocess`, shell commands or browser-supplied Python. Each command must be separately extracted behind a reviewed typed application service before its readiness can change.

## 7. Durable command lifecycle and V3-4 streaming

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

V3-4 replaces active-CommandRun 600 ms UI polling with Evidence Plane SSE. The stream contains a normalized product projection only; on change, the client explicitly reloads the complete durable Control record. If SSE is unavailable, no timed polling fallback is started automatically; the Run Inspector exposes an explicit manual refresh action.

SSE excludes CommandRun parameters, outputs, artifact paths, free-form result/event messages and host filesystem paths. Agent streams likewise exclude prompts, hidden reasoning, raw provider callbacks and raw OTLP/Phoenix spans.

## 8. Command Palette / Run Inspector

The top-bar **Commands** button activates only after `GET :8766/api/v3/control/status` and the Control command projection are available.

The Palette shows:

- CommandSpec L0/L1 authority;
- `application_service_ready` versus `adapter_required`;
- ConfigSnapshot binding where required;
- current WorkbenchContext;
- explicit confirmation for commands that require it;
- produced evidence/artifact types;
- persisted CommandRun state and event history;
- V3-4 CommandRun SSE connection state and explicit manual refresh.

The browser does not send report-root or output filesystem paths for review export. The server injects configured report roots and writes bundles under the configured Control export directory.

Configuration itself remains read-only. Command execution does not provide in-place protocol editing; future protocol changes must use a governed identity/fork workflow.

## 9. Typed deep links / Artifact Inspector

V3-3 introduces a common read-only reference vocabulary covering:

```text
Evidence
Artifact
Factor
ResearchProgram
A4 PortfolioValidation
A5 Reserve
AgentRun
ConfigSnapshot / ConfigDiff
CommandRun
```

Canonical root evidence is preferred over duplicate external references; ambiguous non-root identities fail closed. A5 navigation is exposed only when authoritative reserve lifecycle stores resolve the target.

The Artifact Inspector accepts a registered artifact ID, never a browser-supplied filesystem path. Source-report previews are bounded to configured report roots and server-side size limits; generated-feature artifacts are metadata-only identities.

## 10. API overview

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
GET /api/v3/refs/{kind}/{identity}
GET /api/v3/artifacts/{artifact_id}
GET /api/v3/command-runs/{command_run_id}
GET /api/v3/streams/status
GET /api/v3/streams/agent/runs/{run_id}
GET /api/v3/streams/command-runs/{command_run_id}
```

`POST`, `PUT`, `PATCH` and `DELETE` remain outside the Evidence product contract. The stream endpoints are also GET-only.

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

## 11. Development mode

Terminal A — Evidence API:

```bash
python scripts/run_workspace.py \
  --reports reports \
  --configs configs \
  --command-store .finagent/workbench/commands.sqlite \
  --api-only --reload
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

The frontend defaults Control discovery to `http://127.0.0.1:8766`. Override only for local development with `VITE_CONTROL_API_BASE`; the production launcher itself remains loopback-only. Evidence SSE uses the normal Workspace origin and native `EventSource` reconnect semantics.

## 12. Reserve / production boundary

A5 reserve lifecycle remains evidence-only in the Workbench. There is no generic Control command for reserve execution, recovery or retry.

```text
ReserveEligibilitySeal
  → durable CONSUMED claim
  → RESERVE_PASS / RESERVE_FAIL terminal
  → immutable reserve ledger
  → replay / consumption audit
```

A consumed claim without terminal evidence is shown as interrupted evidence. The Control Plane cannot reopen it.

## 13. Tests

Backend control/evidence/stream tests are part of repository pytest. Frontend acceptance includes typecheck, Vitest, production build and Playwright. Workspace API CI retains both Ubuntu and Windows Python 3.11 jobs; repository-wide Windows pytest is also retained. Local Windows execution may be repeated manually after delivery.

Useful focused commands:

```bash
python -m pytest -q \
  tests/test_command_store_v32c2.py \
  tests/test_workbench_control_api_v32c.py \
  tests/test_workbench_config_command_v32b.py \
  tests/test_workbench_deep_links_v33.py \
  tests/test_workbench_stream_v34.py

cd workspace
npm run typecheck
npm run test
npm run build
npm run e2e
```

## 14. Governance invariants

1. UI code never recalculates authoritative IC, Sharpe, Gate, reserve or execution decisions.
2. Evidence Plane remains GET-only even when Control is running.
3. Control resolves exact allowlisted application services only.
4. No generic L2/L3 execution path exists.
5. Protocol/config edits do not mutate historical evidence identities.
6. Secret values remain host-bound; Workbench config projection never exposes credentials.
7. A software/Control command success is not evidence of alpha or live-capital readiness.
8. Production reserve and broker authority require their own later governance path.
9. Typed deep links fail closed on unresolved or ambiguous identity instead of guessing a target.
10. SSE is notification-only and never becomes a second Agent/evidence/Control authority.
11. Product streams never expose hidden reasoning, raw provider/OTLP/Phoenix payloads, arbitrary command outputs or host paths.

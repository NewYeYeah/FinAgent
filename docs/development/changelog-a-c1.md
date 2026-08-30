# A-C1 Historical Workbench Operational Closure

Status: **Completed implementation / acceptance pending one Ubuntu Python 3.11 gate**  
Stage: **A-C1 — Historical Workbench Operational Closure**  
Planning authority: [`current-development-plan-v4.0.md`](current-development-plan-v4.0.md)  
Next stage after acceptance: **A-C2 — MarketBarSeriesEvidence + Frequency Contract**

## Purpose

A-C1 closes the main product gap left after V4-5: the Workbench can now initiate the bounded historical research pipeline instead of acting only as a result-review surface.

The newly operational historical commands are:

```text
research.run_development
research.run_a2p6
portfolio.run_a4
```

They remain L1 commands and require explicit confirmation. A-C1 does not add reserve execution, strategy promotion, PAPER mutation, broker orders, live capital, arbitrary shell or arbitrary Python authority.

## Two-step implementation

### Step 1 — Historical research application workflows

The former fat CLIs for A2/A2.5 and A2.6 were extracted into reusable in-process application workflows:

```text
src/finagent/application/ashare_research_workflows.py
```

Shared entry points:

```text
run_development_factor_research(...)
run_robust_research(...)
```

The existing scripts remain supported as thin CLI wrappers:

```text
scripts/run_local_ashare_factor_research.py
scripts/run_local_ashare_robust_research.py
```

The historical Workbench services consume server-owned `ConfigSnapshot` values only. Browser requests cannot provide filesystem paths, shell fragments, Python code, replay files or research parameter overrides.

### Step 2 — A4 application workflow

The former fat A4 CLI was extracted into:

```text
src/finagent/application/ashare_portfolio_workflow.py
```

Shared entry point:

```text
run_portfolio_validation(...)
```

`scripts/run_ashare_portfolio_validation.py` is now a thin wrapper over the same workflow.

The A4 workflow preserves the existing source boundary:

- source A2.6 report must be a completed robust ResearchProgram;
- source program must be frozen;
- production reserve must still be `untouched`;
- A4 remains internal execution-aware validation only;
- no promotion or PAPER eligibility is inferred by the application service.

## Control Plane composition

A-C1 intentionally preserves the original V3 command vocabulary as the frozen Evidence metadata record and adds a separate operational composition:

```text
src/finagent/visualization/historical_command_catalog.py
src/finagent/visualization/historical_workbench_control_api.py
```

The Historical Control Plane exposes the existing local protocol:

```text
GET  /api/v3/control/status
GET  /api/v3/control/commands
GET  /api/v3/control/runs
GET  /api/v3/control/runs/{command_run_id}
POST /api/v3/control/runs
```

Its reviewed service set is exactly:

```text
config.validate
data.certify_local_ashare
research.run_development
research.run_a2p6
portfolio.run_a4
review.export_bundle
```

All execution remains in-process through typed application services. There is no subprocess, shell or arbitrary Python fallback.

## Durable audit

The existing `SQLiteCommandStore` remains authoritative for command lifecycle:

```text
CommandIntent
→ CommandRun planned
→ running
→ succeeded / failed / rejected
→ CommandResult
→ evidence_ids / artifact_paths
```

Historical workflow failures become durable failed CommandRuns rather than escaping the Control API lifecycle.

## Windows / PowerShell compatibility

A-C1 adds:

```text
scripts/run_workbench_control.ps1
```

The PowerShell launcher:

- resolves `run_workbench_control.py` through `$PSScriptRoot`;
- honors `FINAGENT_PYTHON` when explicitly configured;
- otherwise uses `python`, then Windows `py -3.11` fallback;
- forwards arguments as PowerShell argument values rather than Bash command strings;
- never requires `finagent.sh` or a Bash shell.

The historical workflows themselves use `pathlib.Path`, Python APIs and the existing HTTP/JSON Control protocol, so Windows-specific shell quoting is not part of the execution contract.

## Workbench frontend

`CommandPalette` already uses the separately connected Control Plane catalog as the execution authority. The Command Catalog surface now also prefers live Control metadata when available, so the A-C1 L1 commands display their actual application-service binding/readiness instead of the frozen pre-A-C1 adapter state.

The Evidence Plane remains GET-only.

## Acceptance gate

Per the A-C1 development policy, implementation was completed in two steps before running the unified gate. The required blocking acceptance is one Ubuntu / Python 3.11 pass covering:

```text
A-C1 focused backend tests
existing Workspace/V4 backend regression
py_compile
Ruff / mypy / pip check
frontend TypeScript / Vitest / build / Playwright
```

Windows is considered at implementation level through the PowerShell launcher and path-safe Python APIs, but Windows CI is not an A-C1 blocking gate.

## Completion rule

A-C1 is accepted when the Ubuntu/Python 3.11 Workspace API + quality gates and Ubuntu frontend gate pass. After that, merge to `main` and advance the roadmap to A-C2.

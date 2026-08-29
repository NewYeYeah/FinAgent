# Visualization V3-2 Completion Record

Status: **completed implementation candidate; acceptance is the V3-2 completion PR CI**

This record supplements the condensed changelog without rewriting historical entries.

## Delivered

### V3-2C-2 Durable Command Store

- application-owned `CommandIntent`, `CommandRun`, `CommandResult`, `CommandEvent` and `CommandRecord` contracts;
- transactional SQLite command store with idempotent request keys;
- strict state transitions and ordered audit events;
- evidence/artifact/output result references;
- crash-visible restart recovery that fails incomplete work and never auto-retries.

### V3-2C-3 Explicit Control Plane

- separate FastAPI process on loopback `:8766`;
- launcher refuses non-loopback binding;
- exact allowlisted L0/L1 CommandSpec and application-service resolution;
- config/context/confirmation validation;
- POST accepts typed command intent only; no generic shell/Python/args/path surface;
- rejected/adapter-required command attempts become durable rejected audit records;
- production reserve, promotion, PAPER, broker and live capital remain out of scope.

### V3-2C-4 Command Palette / Run Inspector

- Control availability is discovered independently from Evidence;
- Commands slot is disabled when Control is absent;
- catalog readiness, ConfigSnapshot, WorkbenchContext and confirmation are visible before launch;
- adapter-required research commands are visible but disabled;
- persisted CommandRun/event/result state is inspected from Control rather than browser-local state;
- polling is temporary until V3-4 product SSE.

## Current execution allowlist

```text
config.validate
data.certify_local_ashare
review.export_bundle
```

Still non-executable:

```text
research.run_development
research.run_a2p6
portfolio.run_a4
```

Those research commands require separate typed application-service extraction. V3-2 never substitutes subprocess execution for that missing boundary.

## Acceptance boundary

V3-2 acceptance requires:

- repository-wide Python tests on supported Linux/Windows/Python versions;
- static quality and typing gates;
- Workspace API tests on Linux and Windows;
- frontend typecheck, Vitest, production build and Playwright;
- A2.6 and research-UI regression workflows;
- Evidence Plane mutation methods remain unavailable;
- no generic L2/L3 authority path.

After acceptance, the roadmap advances to **V3-3 Evidence / Artifact / Config Deep Link**.

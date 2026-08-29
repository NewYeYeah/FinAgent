# Visualization V3-5 Workbench Foundation Acceptance

## Status

V3-5 is the completion gate for the V3 Workbench foundation. It adds no new research, reserve, promotion, PAPER, broker or live-capital authority. Its purpose is to prove that the V3-1 through V3-4 contracts operate together without weakening the previously frozen evidence and governance boundaries.

The accepted foundation consists of:

```text
V3-1  Agent Project → Thread → Run index
V3-2  WorkbenchContext + Config/Command contracts + governed local Control
V3-3  typed Evidence / Artifact / Config / CommandRun deep links
V3-4  sanitized Agent + CommandRun product SSE
```

## Acceptance matrix

| Contract | Required evidence |
| --- | --- |
| URL-backed WorkbenchContext | deterministic parse/serialize/patch tests; browser back/forward and reload restore canonical context; unrelated query parameters remain intact |
| Context-preserving navigation | module links retain supported Project/Run/Program/Portfolio/Reserve/asset/date/environment identity without promoting presentation state into evidence |
| Typed deep links | Agent, Factor, ResearchProgram, A4, A5, ConfigSnapshot/ConfigDiff and CommandRun identities resolve through verified projections; ambiguous or missing identity fails closed |
| Evidence Plane authority | every `/api/*` Evidence route is free of POST/PUT/PATCH/DELETE methods; representative mutation attempts return 404/405 and do not change canonical SQLite/report state |
| Control Plane authority | the only POST route is `POST /api/v3/control/runs`; only exact `application_service_ready` L0/L1 commands can run; unknown, adapter-required, L2/L3-like and executable-text payloads fail closed |
| Reserve isolation | no generic command or route performs reserve execution, recovery, retry, promotion, PAPER mutation, broker action or live-capital action |
| Durable cross-plane identity | Control persists CommandIntent/CommandRun/CommandResult first; Evidence observes the same command/config/context identity read-only through typed refs and SSE |
| SSE transport | deterministic projection-derived event IDs, `Last-Event-ID` replay suppression, disconnect handling, source-disappearance closure, sanitized payloads and native EventSource lifecycle |
| SSE authority | Agent SSE only invalidates the canonical Agent projection; CommandRun SSE only triggers an explicit full Control-record refresh; transport payloads are not a second state authority |
| Browser operating modes | Evidence-only keeps Commands disabled with no fallback; both-plane mode enables only the allowlisted palette; terminal streams close in the client; manual refresh remains available when SSE is unavailable |
| Cross-platform/toolchain | Ubuntu and Windows Workspace API, repository Python 3.11/3.12/3.13 and Windows pytest, ruff, mypy, dependency consistency, TypeScript, Vitest, production build and Playwright |

## Dedicated V3-5 tests

Backend integration:

```text
tests/test_workbench_foundation_v35.py
```

It verifies:

- complete Evidence and Control route inventories;
- absence of generic reserve/promotion/PAPER/broker/live authority;
- persisted rejection of forbidden command identities;
- a real `config.validate` CommandRun observed through the separate read-only Evidence Plane;
- CommandRun → ConfigSnapshot typed identity;
- sanitized terminal CommandRun SSE;
- no Evidence-side SQLite mutation;
- reconnect replay suppression, disconnect and disappearing-source behavior.

Frontend unit acceptance:

```text
workspace/src/workbench/foundation.test.tsx
```

It verifies browser-history restoration of `WorkbenchContext` and native EventSource shutdown when a terminal CommandRun disables streaming.

Browser acceptance:

```text
workspace/e2e/foundation-v3.spec.ts
```

It verifies Evidence-only context persistence across module navigation, back/forward and reload, plus the both-plane allowlisted-command surface with forbidden L2/L3/A5 actions absent.

## Authority freeze

The generic Workbench Control Plane remains limited to:

```text
config.validate
data.certify_local_ashare
review.export_bundle
```

The following remain visible but non-executable until separately reviewed application-service extraction exists:

```text
research.run_development
research.run_a2p6
portfolio.run_a4
```

The following remain outside generic Workbench authority:

```text
production reserve
strategy promotion
PAPER mutation
broker order
live capital
arbitrary shell
arbitrary Python
```

## Completion rule

V3-5 is complete only when the pull-request head passes all repository, Workspace, A2.6 and legacy Research UI workflows and is merged to `main`. A local Windows run may be retained as an additional human acceptance step, but it does not replace the committed Windows CI matrix.

After V3-5, development moves to **V4-0 StrategyDecisionSeriesEvidence**. V4 must continue the frozen order:

```text
core calculation
→ immutable authoritative series evidence
→ bounded projection API
→ FinWidgetSpec / WorkbenchContext semantics
→ interactive chart
```

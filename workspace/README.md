# FinAgent Workspace Frontend

This directory contains the React/TypeScript client for the read-only FinAgent Visualization V2 Evidence Workspace.

```bash
npm ci
npm run typecheck
npm run test
npm run build
npm run e2e
```

Development mode expects the FastAPI service on `127.0.0.1:8765` and runs Vite on `127.0.0.1:5173`:

```bash
npm run dev
```

V2 provides the Research Governance Cockpit, A2.6 Gate/statistical/fold review, A4 portfolio/economic review, digest-matched execution-ledger realization, Governance/Protocol review and review-bundle download. The browser consumes `/api/v1` compatibility projections plus GET-only `/api/v2` review projections.

The browser must not parse internal A2.6/A4 files, Phoenix spans or SQLite tables directly. It contains no prompt/code/Gate mutation, research rerun, reserve access, promotion/PAPER control or order-submission authority. Presentation-only rolling series, Gate criterion cells, realized weights and A3 protocol binding are explicitly `derived`.

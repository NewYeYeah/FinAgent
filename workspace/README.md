# FinAgent Workspace Frontend

This directory contains the React/TypeScript client for the read-only FinAgent Evidence Workspace.

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

The browser consumes only `/api/v1` semantic projections. It must not parse internal A2.6/A4 files, Phoenix spans or SQLite tables directly. It contains no research, reserve, promotion or trading write control.

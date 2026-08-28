from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def ensure_replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"missing release patch anchor: {path}: {old!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def finalize_frontend() -> None:
    ensure_replace(
        "workspace/vite.config.ts",
        'import { defineConfig } from "vite";',
        'import { defineConfig } from "vitest/config";',
    )
    path = ROOT / "workspace/src/App.test.tsx"
    text = path.read_text(encoding="utf-8")
    marker = 'vi.mock("echarts-for-react"'
    if marker not in text:
        anchor = 'import App from "./App";\n'
        replacement = '''vi.mock("echarts-for-react", () => ({\n  default: () => <div data-testid="echarts" />,\n}));\n\nvi.mock("@xyflow/react", () => ({\n  ReactFlow: ({ children }: { children?: React.ReactNode }) => (\n    <div data-testid="react-flow">{children}</div>\n  ),\n  Background: () => null,\n  Controls: () => null,\n  MarkerType: { ArrowClosed: "arrowclosed" },\n}));\n\nimport App from "./App";\n'''
        if anchor not in text:
            raise RuntimeError("App test import anchor is absent")
        path.write_text(text.replace(anchor, replacement, 1), encoding="utf-8")


def finalize_testing() -> None:
    path = ROOT / "docs/testing/testing.md"
    text = path.read_text(encoding="utf-8")
    marker = "### T-A7 — FinAgent Workspace V1 acceptance"
    if marker in text:
        return
    section = r'''

### T-A7 — FinAgent Workspace V1 acceptance

Run after Visualization V0/V1 changes and before relying on the Workspace for A5 review.

#### T-A7.1 Install and build

Ubuntu:

```bash
python -m pip install -e ".[dev,workspace]"
cd workspace
npm ci
npm run typecheck
npm run test
npm run build
cd ..
```

Windows PowerShell:

```powershell
python -m pip install -e ".[dev,workspace]"
Set-Location workspace
npm ci
npm run typecheck
npm run test
npm run build
Set-Location ..
```

#### T-A7.2 API and semantic regression

```bash
python -m pytest -q \
  tests/test_workspace_api_v1.py \
  tests/test_visualization_semantic_contract_v2.py \
  tests/test_research_visualization.py \
  tests/test_research_ui_app.py
```

Acceptance:

- A2/A2.5, A2.6 and A4 reports project through the semantic contract;
- unsupported/malformed files become warnings rather than silent partial rendering;
- conflicting payloads sharing one identity are omitted;
- catalog/evidence/program/factor/lineage/widget/Agent GET endpoints work;
- product POST requests return method-not-allowed;
- report JSON and Agent audit SQLite are unchanged;
- Agent audit uses SQLite read-only/query-only access;
- hidden reasoning is absent;
- reserve status and `promotion_eligible=false` remain visible.

#### T-A7.3 Browser smoke

```bash
cd workspace
npx playwright install chromium
npm run e2e
cd ..
```

The browser smoke must confirm the read-only banner, evidence deep-link navigation, factor/A4 views, derived-series labels and the absence of promotion/rerun/reserve/order controls.

#### T-A7.4 Launch with real evidence

Ubuntu:

```bash
python scripts/run_workspace.py \
  --reports reports \
  --agent-audit .finagent/agent_audit.sqlite \
  --open-browser
```

Windows PowerShell:

```powershell
python scripts\run_workspace.py `
  --reports reports `
  --agent-audit .finagent\agent_audit.sqlite `
  --open-browser
```

Open `http://127.0.0.1:8765`. Manually compare one frozen A2.6 report and one A4 report against the Workspace: statuses, denominator, Gate reasons, weights/directions, NAV, costs, order counts, reason codes and lineage IDs must agree. Browser navigation must not change report or SQLite hashes.

#### T-A7.5 API-only/debug modes

```bash
python scripts/run_workspace.py --reports reports --api-only
python scripts/run_workspace.py --reports reports --api-only --reload
```

The V1 catalog is rebuilt only at process start. Restart after creating a new authoritative report; there is deliberately no refresh/write endpoint.
'''
    anchor = "\n## 4. Interpretation boundary"
    if anchor not in text:
        raise RuntimeError("testing.md interpretation-boundary anchor is absent")
    path.write_text(text.replace(anchor, section + anchor, 1), encoding="utf-8")


def finalize_legacy_guide() -> None:
    path = ROOT / "docs/guides/research-visualization.md"
    text = path.read_text(encoding="utf-8")
    marker = "Workspace V1 is now the primary product surface"
    if marker in text:
        return
    newline = text.find("\n")
    if newline < 0:
        raise RuntimeError("legacy visualization guide title is absent")
    note = (
        "\n\n> **Status:** Workspace V1 is now the primary product surface for A2.6/A4 "
        "evidence. This guide documents the retained legacy Streamlit/Phoenix diagnostic "
        "path. See `docs/guides/workspace.md`.\n"
    )
    path.write_text(text[:newline] + note + text[newline:], encoding="utf-8")


if __name__ == "__main__":
    finalize_frontend()
    finalize_testing()
    finalize_legacy_guide()

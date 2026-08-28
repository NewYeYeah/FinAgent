from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def update_testing() -> None:
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
- unsupported/malformed report files appear as warnings and are not silently rendered;
- conflicting payloads sharing one evidence identity are omitted;
- catalog, evidence, program, factor, lineage, widget and Agent GET endpoints work;
- product POST requests return method-not-allowed;
- report JSON and Agent audit SQLite modification times remain unchanged;
- Agent audit uses `mode=ro` and `PRAGMA query_only=ON`;
- hidden reasoning is absent;
- reserve status and `promotion_eligible=false` remain visible.

#### T-A7.3 Browser smoke

Install Chromium once:

```bash
cd workspace
npx playwright install chromium
npm run e2e
cd ..
```

The browser smoke must confirm:

- the read-only authority banner is visible;
- catalog evidence opens through a deep link;
- A2.6 factor evidence is visible;
- A4 NAV/execution surfaces render when A4 evidence is supplied;
- derived presentation series are labelled derived;
- no promote/rerun/reserve/order action exists.

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

Open `http://127.0.0.1:8765` and inspect:

```text
Project Cockpit
Research Programs
Portfolio Validations
Factor Evidence
Agent Runs
Widget Catalog
```

Manually verify at least one frozen A2.6 report and one A4 report:

- `system_status`, research/economic status and reserve status are distinct;
- factor denominator, Gate failures, selected weights/directions and fold metrics match JSON;
- gross/net NAV endpoints match A4 report points;
- execution counts, costs and reason codes match A4 aggregate evidence;
- lineage identities match A2.6/A4 report IDs;
- the Agent timeline matches canonical audit events;
- browser navigation does not change report or SQLite hashes.

#### T-A7.5 API-only/debug modes

```bash
python scripts/run_workspace.py --reports reports --api-only
python scripts/run_workspace.py --reports reports --api-only --reload
```

FastAPI docs are available at `http://127.0.0.1:8765/docs`. Vite development mode runs separately from `workspace/` with `npm run dev` and proxies `/api` to port 8765.

The catalog is rebuilt only at process start in V1. Restart after creating a new authoritative report. There is deliberately no refresh/write endpoint.
'''
    anchor = "\n## 4. Interpretation boundary"
    if anchor not in text:
        raise RuntimeError("testing.md interpretation-boundary anchor is absent")
    path.write_text(text.replace(anchor, section + anchor, 1), encoding="utf-8")


def update_legacy_guide() -> None:
    path = ROOT / "docs/guides/research-visualization.md"
    text = path.read_text(encoding="utf-8")
    marker = "Workspace V1 is now the primary product surface"
    if marker in text:
        return
    first_newline = text.find("\n")
    if first_newline < 0:
        raise RuntimeError("research-visualization.md has no title line")
    note = (
        "\n\n> **Status:** Workspace V1 is now the primary product surface for A2.6/A4 "
        "evidence. This guide documents the retained legacy Streamlit/Phoenix diagnostic "
        "path. See `docs/guides/workspace.md` for the FastAPI/React Workspace.\n"
    )
    path.write_text(text[:first_newline] + note + text[first_newline:], encoding="utf-8")


if __name__ == "__main__":
    update_testing()
    update_legacy_guide()

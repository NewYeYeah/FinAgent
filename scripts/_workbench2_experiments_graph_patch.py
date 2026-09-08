from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"patch anchor missing: {path}: {old[:80]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace(
    "src/finagent/visualization/workspace_api.py",
    "from .agent_projection import load_agent_run_projection\n",
    "from .agent_projection import load_agent_run_projection\nfrom .research_workspace import ResearchWorkspaceProjection\nfrom .research_workspace_routes import attach_research_workspace_routes\n",
)
replace(
    "src/finagent/visualization/workspace_api.py",
    "    agent_path = Path(agent_audit_path).expanduser() if agent_audit_path else None\n    static_root = Path(frontend_dir).expanduser() if frontend_dir else None\n",
    "    agent_path = Path(agent_audit_path).expanduser() if agent_audit_path else None\n    research_workspace = ResearchWorkspaceProjection(agent_path)\n    static_root = Path(frontend_dir).expanduser() if frontend_dir else None\n",
)
replace(
    "src/finagent/visualization/workspace_api.py",
    "    app.state.agent_audit_path = agent_path\n    app.state.read_only = True\n",
    "    app.state.agent_audit_path = agent_path\n    app.state.research_workspace = research_workspace\n    app.state.read_only = True\n",
)
replace(
    "src/finagent/visualization/workspace_api.py",
    "    @app.get(\"/api/v1/health\")\n",
    "    attach_research_workspace_routes(app, research_workspace)\n\n    @app.get(\"/api/v1/health\")\n",
)
replace(
    "src/finagent/visualization/workspace_api.py",
    '            "agent_audit_configured": agent_path is not None,\n            "workspace_v2": True,\n',
    '            "agent_audit_configured": agent_path is not None,\n            "research_workspace": research_workspace.status(),\n            "workspace_v2": True,\n',
)

replace(
    "src/finagent/application/research_controller.py",
    '            "controller": "r4",\n            "binding_id": identity(request, "r4-research-request"),\n',
    '            "controller": "r4",\n            "provider_id": provider_id,\n            "model_id": model_id,\n            "binding_id": identity(request, "r4-research-request"),\n',
)

replace(
    "workspace/src/workbench/context.tsx",
    "  run_id?: string;\n  program_id?: string;\n",
    "  run_id?: string;\n  experiment_id?: string;\n  comparison_ids?: string;\n  research_cycle_id?: string;\n  graph_node_id?: string;\n  program_id?: string;\n",
)
replace(
    "workspace/src/workbench/context.tsx",
    '  | "run_selected"\n  | "asset_selected"\n',
    '  | "run_selected"\n  | "experiment_selected"\n  | "graph_node_selected"\n  | "asset_selected"\n',
)
replace(
    "workspace/src/workbench/context.tsx",
    '  run_id: "run",\n  program_id: "program",\n',
    '  run_id: "run",\n  experiment_id: "experiment",\n  comparison_ids: "compare",\n  research_cycle_id: "cycle",\n  graph_node_id: "graph_node",\n  program_id: "program",\n',
)

replace(
    "workspace/src/workbench/panels.ts",
    '  | "agent"\n  | "strategy"\n',
    '  | "agent"\n  | "experiments"\n  | "research-graph"\n  | "strategy"\n',
)
replace(
    "workspace/src/workbench/panels.ts",
    '  { panel_id: "agent", module: "agent", title: "Agent", route: "/agent", status: "available", context_keys: ["project_id", "thread_id", "run_id"], slot: "main" },\n',
    '  { panel_id: "agent", module: "agent", title: "Agent", route: "/agent", status: "available", context_keys: ["project_id", "thread_id", "run_id"], slot: "main" },\n  { panel_id: "experiments", module: "experiments", title: "Experiments", route: "/experiments", status: "available", context_keys: ["project_id", "thread_id", "run_id", "experiment_id", "comparison_ids"], slot: "main" },\n  { panel_id: "research-graph", module: "research-graph", title: "Research Graph", route: "/research-graph", status: "available", context_keys: ["project_id", "thread_id", "run_id", "experiment_id", "factor_id", "research_cycle_id", "graph_node_id"], slot: "chart" },\n',
)

replace(
    "workspace/src/workbench/shell.tsx",
    '  agent: <Boxes size={17} />,\n  strategy: <ChartCandlestick size={17} />,\n',
    '  agent: <Boxes size={17} />,\n  experiments: <FlaskConical size={17} />,\n  "research-graph": <GitBranch size={17} />,\n  strategy: <ChartCandlestick size={17} />,\n',
)
replace(
    "workspace/src/workbench/shell.tsx",
    '  run_id: "Run",\n  program_id: "Program",\n',
    '  run_id: "Run",\n  experiment_id: "Experiment",\n  comparison_ids: "Compare",\n  research_cycle_id: "Research cycle",\n  graph_node_id: "Graph node",\n  program_id: "Program",\n',
)

replace(
    "workspace/src/App.tsx",
    'import { AgentWorkbenchPage, LegacyAgentRunRedirect } from "./workbench/agent";\n',
    'import { AgentWorkbenchPage, LegacyAgentRunRedirect } from "./workbench/agent";\nimport { ExperimentsPage } from "./workbench/experiments";\nimport { ResearchGraphPage } from "./workbench/researchGraph";\n',
)
replace(
    "workspace/src/App.tsx",
    '            <Route path="/agent" element={<AgentWorkbenchPage />} />\n            <Route path="/agent/:runId" element={<LegacyAgentRunRedirect />} />\n',
    '            <Route path="/agent" element={<AgentWorkbenchPage />} />\n            <Route path="/agent/:runId" element={<LegacyAgentRunRedirect />} />\n            <Route path="/experiments" element={<ExperimentsPage />} />\n            <Route path="/research-graph" element={<ResearchGraphPage />} />\n',
)

replace(
    "docs/status.toml",
    'current_stage_status = "development_in_progress_agent_workspace_first_slice"\n',
    'current_stage_status = "development_in_progress_experiments_graph_slice"\n',
)
replace(
    "docs/status.toml",
    'workbench2_agent_workspace = "first_vertical_slice_in_development"\n',
    'workbench2_agent_workspace = "first_vertical_slice_in_development"\nworkbench2_experiments_graph = "second_vertical_slice_in_development"\n',
)

replace(
    "docs/development/stages/workbench-2.md",
    "WORKBENCH-2 is now the active development stage. The first slice is the Agent Workspace only; this does **not** mean the stage or its exit gate is accepted.\n\nThis slice upgrades the Agent surface around the existing `ResearchCapabilityRuntime`, R4 Controller, persisted audit projection, AG-UI adapter, normalized SSE, WorkbenchContext and Evidence Plane. Touched Agent server-state uses `@tanstack/react-query`; untouched Workbench pages may still use the custom query client until they are naturally migrated.\n",
    "WORKBENCH-2 is the active development stage. The Agent Workspace first slice is implemented, and the second development slice now adds the Experiments surface plus canonical Research Graph. This does **not** mean the stage or its exit gate is accepted.\n\nThe first slice upgraded the Agent surface around the existing `ResearchCapabilityRuntime`, R4 Controller, persisted audit projection, AG-UI adapter, normalized SSE, WorkbenchContext and Evidence Plane. The second slice projects persisted experiment attempts/comparisons and versioned accepted research cycles into GET-only Workbench V3 APIs, then links them through React Flow using canonical identities only. Touched Agent/Experiments/Graph server-state uses `@tanstack/react-query`; untouched Workbench pages may still use the custom query client until naturally migrated.\n",
)

replace(
    "docs/development/backlog.md",
    "The pre-WORKBENCH-2 Agent baseline was audit-oriented. The first WORKBENCH-2 slice now reorganizes that surface around a research objective/session, Project → Thread → Run navigation, persisted Agent action/result/decision cards, research context, accepted negative terminal state and evidence/config identities. This is an implementation milestone only: no fresh task-based human usability baseline has been recorded, so B-101 remains open until the stage's real-artifact human acceptance work is completed.\n",
    "The pre-WORKBENCH-2 Agent baseline was audit-oriented. The first WORKBENCH-2 slice reorganized that surface around a research objective/session, Project → Thread → Run navigation, persisted Agent action/result/decision cards, research context, accepted negative terminal state and evidence/config identities. The second slice adds first-class persisted Experiments/comparison and a canonical Research Graph with unresolved-lineage handling. These are implementation milestones only: no fresh task-based human usability baseline has been recorded, so B-101 remains open until the stage's real-artifact human acceptance work is completed.\n",
)
replace(
    "docs/development/backlog.md",
    "`workspace/src/workbench/query.tsx` still implements cache/stale/in-flight/invalidation behavior for untouched surfaces. The first WORKBENCH-2 Agent Workspace slice migrates its touched Agent/Research server-state reads and invalidation flow to `@tanstack/react-query` without expanding the custom client. Other Workbench consumers remain on the existing wrapper, so B-102 is only partially progressed and remains OPEN; continue migration only when those surfaces are touched for product work.\n",
    "`workspace/src/workbench/query.tsx` still implements cache/stale/in-flight/invalidation behavior for untouched surfaces. The Agent Workspace first slice migrated its touched Agent/Research reads, and the Experiments/Research Graph slice also uses `@tanstack/react-query` for list/detail/comparison/graph/cycle server-state plus SSE-driven graph invalidation. No new custom-query consumer is added. Other Workbench consumers remain on the existing wrapper, so B-102 is only partially progressed and remains OPEN; continue migration only when those surfaces are touched for product work.\n",
)

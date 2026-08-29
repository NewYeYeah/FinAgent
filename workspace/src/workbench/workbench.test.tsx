import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("echarts-for-react", () => ({ default: () => <div data-testid="echarts" /> }));
vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ children }: { children?: React.ReactNode }) => <div data-testid="react-flow">{children}</div>,
  Background: () => null,
  Controls: () => null,
  MarkerType: { ArrowClosed: "arrowclosed" },
}));

import App from "../App";

function response(payload: unknown) {
  return Promise.resolve(new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }));
}

const projects = {
  schema_version: "finagent.workspace.agent-project-index.v1",
  configured: true,
  read_only: true,
  hidden_reasoning: "not_persisted_not_projected",
  items: [{
    project_id: "project-a",
    identity_source: "explicit",
    label: "A-share research",
    status: "completed",
    started_at: "2026-08-29T08:00:00+00:00",
    updated_at: "2026-08-29T08:05:00+00:00",
    thread_count: 1,
    run_count: 1,
    artifact_count: 1,
    detail_url: "/api/v3/agent/projects/project-a",
  }],
};

const project = {
  schema_version: "finagent.visualization.agent-project-projection.v1",
  ...projects.items[0],
  threads: [{
    thread_id: "thread-a",
    project_id: "project-a",
    identity_source: "explicit",
    label: "Factor discovery",
    status: "completed",
    started_at: "2026-08-29T08:00:00+00:00",
    updated_at: "2026-08-29T08:05:00+00:00",
    run_count: 1,
    artifact_count: 1,
    detail_url: "/api/v3/agent/threads/thread-a",
  }],
  artifact_refs: [],
  read_only: true,
};

const runSummary = {
  run_id: "run-a",
  task_id: "task-a",
  project_id: "project-a",
  thread_id: "thread-a",
  project_identity_source: "explicit",
  thread_identity_source: "explicit",
  objective: "Inspect factor evidence",
  actor: "research-agent",
  trigger_type: "research_program",
  status: "completed",
  started_at: "2026-08-29T08:00:00+00:00",
  finished_at: "2026-08-29T08:05:00+00:00",
  updated_at: "2026-08-29T08:05:00+00:00",
  item_count: 2,
  artifact_count: 1,
  artifact_refs: [],
  unresolved_artifact_count: 1,
  error: "",
  detail_url: "/api/v3/agent/runs/run-a",
};

const thread = {
  schema_version: "finagent.visualization.agent-thread-projection.v1",
  ...project.threads[0],
  runs: [runSummary],
  artifact_refs: [],
  read_only: true,
};

const run = {
  schema_version: "finagent.workspace.agent-run-detail.v1",
  summary: runSummary,
  run: {
    schema_version: "finagent.visualization.agent-run-projection.v1",
    run_id: "run-a",
    task_id: "task-a",
    project_id: "project-a",
    thread_id: "thread-a",
    actor: "research-agent",
    trigger_type: "research_program",
    status: "completed",
    started_at: "2026-08-29T08:00:00+00:00",
    finished_at: "2026-08-29T08:05:00+00:00",
    objective: "Inspect factor evidence",
    items: [
      { item_id: "evt-1", item_type: "plan", occurred_at: "2026-08-29T08:00:00+00:00", title: "Run started", status: "started", summary: "Agent started", call_id: "", evidence_ids: [], metadata: {} },
      { item_id: "evt-2", item_type: "tool", occurred_at: "2026-08-29T08:01:00+00:00", title: "Tool succeeded", status: "succeeded", summary: "Evidence inspected", call_id: "call-a", evidence_ids: ["verified-evidence", "unknown-audit-id"], metadata: {} },
    ],
    artifact_ids: ["verified-evidence", "unknown-audit-id"],
    token_usage: {},
    latency_ms: 300000,
    governance: { audit_access: "sqlite_read_only" },
    error: "",
    hidden_reasoning: "not_persisted_not_projected",
  },
  artifact_refs: [{
    artifact_id: "verified-evidence",
    artifact_type: "evidence",
    authority: "authoritative",
    detail_url: "/evidence/verified-evidence",
    verification: "workspace_catalog",
    evidence_ids: ["verified-evidence"],
    source_uris: ["reports/a26.json"],
  }],
  unresolved_artifact_count: 1,
  read_only: true,
  hidden_reasoning: "not_persisted_not_projected",
};

describe("V3-2A Agent Workbench", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/agent");
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v3/agent/projects")) return response(projects);
      if (url.endsWith("/api/v3/agent/projects/project-a")) return response(project);
      if (url.endsWith("/api/v3/agent/threads/thread-a")) return response(thread);
      if (url.endsWith("/api/v3/agent/runs/run-a")) return response(run);
      throw new Error(`unexpected URL: ${url}`);
    }));
  });

  afterEach(() => vi.unstubAllGlobals());

  it("navigates Project → Thread → Run through linked URL context", async () => {
    render(<App />);
    expect(await screen.findByText("Project → Thread → Run")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /A-share research/i }));
    await waitFor(() => expect(window.location.search).toContain("project=project-a"));
    await userEvent.click(await screen.findByRole("button", { name: /Factor discovery/i }));
    await waitFor(() => expect(window.location.search).toContain("thread=thread-a"));
    await userEvent.click(await screen.findByRole("button", { name: /Inspect factor evidence/i }));
    await waitFor(() => expect(window.location.search).toContain("run=run-a"));
    expect(await screen.findByText("Run started")).toBeInTheDocument();
    expect(screen.getByText("Run Inspector")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /verified-evidence/i })).toHaveAttribute("href", "/evidence/verified-evidence");
    expect(screen.getByText(/unresolved:unknown-audit-id/i)).toBeInTheDocument();
    expect(screen.getByText(/not_persisted_not_projected/i)).toBeInTheDocument();
    expect(screen.getByTestId("workbench-context-bar")).toHaveTextContent("run-a");
  });

  it("keeps control-plane affordances visibly disabled", async () => {
    render(<App />);
    await screen.findByText("Project → Thread → Run");
    expect(screen.getByRole("button", { name: "Config" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Commands" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /execute|promote|order|reserve/i })).not.toBeInTheDocument();
  });
});

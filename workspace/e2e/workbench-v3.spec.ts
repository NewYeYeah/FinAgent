import { expect, test } from "@playwright/test";

const projects = {
  schema_version: "finagent.workspace.agent-project-index.v1",
  configured: true,
  read_only: true,
  hidden_reasoning: "not_persisted_not_projected",
  items: [{
    project_id: "project-v3",
    identity_source: "explicit",
    label: "Workbench research",
    status: "completed",
    started_at: "2026-08-29T08:00:00+00:00",
    updated_at: "2026-08-29T08:05:00+00:00",
    thread_count: 1,
    run_count: 1,
    artifact_count: 1,
    detail_url: "/api/v3/agent/projects/project-v3",
  }],
};

const project = {
  schema_version: "finagent.visualization.agent-project-projection.v1",
  ...projects.items[0],
  threads: [{
    thread_id: "thread-v3",
    project_id: "project-v3",
    identity_source: "explicit",
    label: "Research thread",
    status: "completed",
    started_at: "2026-08-29T08:00:00+00:00",
    updated_at: "2026-08-29T08:05:00+00:00",
    run_count: 1,
    artifact_count: 1,
    detail_url: "/api/v3/agent/threads/thread-v3",
  }],
  artifact_refs: [],
  read_only: true,
};

const summary = {
  run_id: "run-v3",
  task_id: "task-v3",
  project_id: "project-v3",
  thread_id: "thread-v3",
  project_identity_source: "explicit",
  thread_identity_source: "explicit",
  objective: "Review V3 evidence",
  actor: "research-agent",
  trigger_type: "research_program",
  status: "completed",
  started_at: "2026-08-29T08:00:00+00:00",
  finished_at: "2026-08-29T08:05:00+00:00",
  updated_at: "2026-08-29T08:05:00+00:00",
  item_count: 1,
  artifact_count: 0,
  artifact_refs: [],
  unresolved_artifact_count: 0,
  error: "",
  detail_url: "/api/v3/agent/runs/run-v3",
};

const thread = {
  schema_version: "finagent.visualization.agent-thread-projection.v1",
  ...project.threads[0],
  runs: [summary],
  artifact_refs: [],
  read_only: true,
};

const run = {
  schema_version: "finagent.workspace.agent-run-detail.v1",
  summary,
  run: {
    schema_version: "finagent.visualization.agent-run-projection.v1",
    run_id: "run-v3",
    task_id: "task-v3",
    project_id: "project-v3",
    thread_id: "thread-v3",
    actor: "research-agent",
    trigger_type: "research_program",
    status: "completed",
    started_at: "2026-08-29T08:00:00+00:00",
    finished_at: "2026-08-29T08:05:00+00:00",
    objective: "Review V3 evidence",
    items: [{ item_id: "evt-v3", item_type: "result", occurred_at: "2026-08-29T08:05:00+00:00", title: "Run finished", status: "completed", summary: "Review complete", call_id: "", evidence_ids: [], metadata: {} }],
    artifact_ids: [],
    token_usage: {},
    latency_ms: 300000,
    governance: { audit_access: "sqlite_read_only" },
    error: "",
    hidden_reasoning: "not_persisted_not_projected",
  },
  artifact_refs: [],
  unresolved_artifact_count: 0,
  read_only: true,
  hidden_reasoning: "not_persisted_not_projected",
};

test("V3-2A provides deterministic linked Agent navigation without control authority", async ({ page }) => {
  await page.route("**/api/v3/agent/projects", (route) => route.fulfill({ json: projects }));
  await page.route("**/api/v3/agent/projects/project-v3", (route) => route.fulfill({ json: project }));
  await page.route("**/api/v3/agent/threads/thread-v3", (route) => route.fulfill({ json: thread }));
  await page.route("**/api/v3/agent/runs/run-v3", (route) => route.fulfill({ json: run }));
  await page.goto("/agent");

  await expect(page.getByText("Project → Thread → Run")).toBeVisible();
  await page.getByRole("button", { name: /Workbench research/i }).click();
  await expect(page).toHaveURL(/project=project-v3/);
  await page.getByRole("button", { name: /Research thread/i }).click();
  await expect(page).toHaveURL(/thread=thread-v3/);
  await page.getByRole("button", { name: /Review V3 evidence/i }).click();
  await expect(page).toHaveURL(/run=run-v3/);
  await expect(page.getByText("Run finished")).toBeVisible();
  await expect(page.getByText("Run Inspector")).toBeVisible();
  await expect(page.getByTestId("workbench-context-bar")).toContainText("run-v3");
  await expect(page.getByRole("button", { name: "Config" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Commands" })).toBeDisabled();
});

import { expect, test } from "@playwright/test";

const evidenceCommands = {
  schema_version: "finagent.workbench.command-catalog.v1",
  read_only: true,
  execution_enabled: false,
  control_plane_enabled: false,
  forbidden_authority: [
    "production_reserve",
    "strategy_promotion",
    "paper_mutation",
    "broker_order",
    "live_capital",
    "arbitrary_shell",
    "arbitrary_python",
  ],
  items: [
    {
      schema_version: "finagent.workbench.command-spec.v1",
      command_id: "review.export_bundle",
      title: "Export review bundle",
      description: "Deterministic read-only human-review bundle export.",
      level: "L0",
      config_descriptor_ids: [],
      binding_kind: "application_service",
      binding_ref:
        "finagent.application.control_services.ReviewBundleExportApplicationService",
      gateway_readiness: "application_service_ready",
      produces: ["HumanReviewBundle"],
      requires_confirmation: false,
      execution_enabled: false,
      catalog_only: true,
    },
    {
      schema_version: "finagent.workbench.command-spec.v1",
      command_id: "research.run_a2p6",
      title: "Run A2.6 robust research",
      description: "Preregistered robust ResearchProgram execution.",
      level: "L1",
      config_descriptor_ids: ["local_ashare_robust_research"],
      binding_kind: "cli_orchestration",
      binding_ref: "scripts/run_local_ashare_robust_research.py",
      gateway_readiness: "adapter_required",
      produces: ["AshareRobustResearchProgramResult"],
      requires_confirmation: true,
      execution_enabled: false,
      catalog_only: true,
    },
  ],
};

const controlStatus = {
  schema_version: "finagent.workbench.control-status.v1",
  version: "finagent-workbench-control-api-v3.2",
  control_plane_enabled: true,
  local_only: true,
  remote_binding_supported: false,
  requested_by: "browser-test",
  application_service_ready: ["review.export_bundle"],
  recovered_incomplete_runs: [],
  store: {
    schema_version: "finagent.workbench.command-store.v1",
    run_counts: {},
    terminal_states: ["failed", "rejected", "succeeded"],
  },
  forbidden_authority: evidenceCommands.forbidden_authority,
};

const controlCommands = {
  schema_version: "finagent.workbench.control-command-catalog.v1",
  control_plane_enabled: true,
  local_only: true,
  forbidden_authority: evidenceCommands.forbidden_authority,
  items: evidenceCommands.items.map((item) => ({
    ...item,
    control_plane_enabled: true,
    control_execution_enabled: item.command_id === "review.export_bundle",
  })),
};

const configRegistry = {
  schema_version: "finagent.workbench.config-registry.v1",
  read_only: true,
  descriptors: [],
  snapshots: [],
  warnings: [],
};

const terminalRun = {
  schema_version: "finagent.workbench.command-record.v1",
  intent: {
    schema_version: "finagent.workbench.command-intent.v1",
    intent_id: "command-intent-browser",
    command_id: "review.export_bundle",
    config_snapshot_id: null,
    context: { portfolio_validation_id: "a4-browser" },
    requested_by: "browser-test",
    state: "validated",
  },
  run: {
    schema_version: "finagent.workbench.command-run.v1",
    command_run_id: "command-run-browser",
    intent_id: "command-intent-browser",
    command_id: "review.export_bundle",
    state: "succeeded",
    started_at: "2026-08-29T12:10:00+00:00",
    finished_at: "2026-08-29T12:10:01+00:00",
  },
  parameters: { validation_id: "a4-browser" },
  created_at: "2026-08-29T12:10:00+00:00",
  updated_at: "2026-08-29T12:10:01+00:00",
  result: {
    schema_version: "finagent.workbench.command-result.v1",
    command_run_id: "command-run-browser",
    status: "succeeded",
    evidence_ids: ["a4-browser"],
    message: "human-review bundle exported",
  },
  artifact_paths: [
    ".finagent/workbench/exports/finagent-review-a4-browser.zip",
  ],
  outputs: {},
  events: [
    {
      schema_version: "finagent.workbench.command-event.v1",
      event_id: "event-browser-1",
      command_run_id: "command-run-browser",
      sequence: 1,
      event_type: "RUN_PLANNED",
      state: "planned",
      occurred_at: "2026-08-29T12:10:00+00:00",
      message: "command accepted for execution",
    },
    {
      schema_version: "finagent.workbench.command-event.v1",
      event_id: "event-browser-2",
      command_run_id: "command-run-browser",
      sequence: 2,
      event_type: "RUN_SUCCEEDED",
      state: "succeeded",
      occurred_at: "2026-08-29T12:10:01+00:00",
      message: "human-review bundle exported",
    },
  ],
};

test("V3-2 connects a local governed palette without changing Evidence authority", async ({
  page,
}) => {
  await page.route("**/api/v3/commands", (route) =>
    route.fulfill({ json: evidenceCommands }),
  );
  await page.route("**/api/v3/config", (route) =>
    route.fulfill({ json: configRegistry }),
  );
  await page.route("http://127.0.0.1:8766/api/v3/control/status", (route) =>
    route.fulfill({ json: controlStatus }),
  );
  await page.route("http://127.0.0.1:8766/api/v3/control/commands", (route) =>
    route.fulfill({ json: controlCommands }),
  );
  await page.route(
    "http://127.0.0.1:8766/api/v3/control/runs?limit=20",
    (route) => route.fulfill({ json: { schema_version: "list", items: [] } }),
  );
  await page.route("http://127.0.0.1:8766/api/v3/control/runs", async (route) => {
    const request = route.request();
    expect(request.method()).toBe("POST");
    const payload = request.postDataJSON();
    expect(payload.command_id).toBe("review.export_bundle");
    expect(payload.validation_id).toBe("a4-browser");
    expect(payload.context.portfolio_validation_id).toBe("a4-browser");
    expect(payload.shell).toBeUndefined();
    expect(payload.output).toBeUndefined();
    await route.fulfill({ status: 200, json: terminalRun });
  });

  await page.goto("/widgets?surface=commands&portfolio=a4-browser");
  await expect(page.getByRole("heading", { name: "Command Catalog" })).toBeVisible();
  await expect(page.getByText(/Evidence metadata remains read-only/i)).toBeVisible();
  await expect(page.getByText(/Local Control Plane connected/i)).toBeVisible();

  const commandsButton = page.getByRole("button", { name: "Commands" });
  await expect(commandsButton).toBeEnabled();
  await commandsButton.click();
  await expect(
    page.getByRole("dialog", { name: "FinAgent Command Palette" }),
  ).toBeVisible();

  await page.getByRole("button", { name: /Run A2.6 robust research/i }).click();
  await expect(
    page.getByText(/application-service adapter is not ready/i),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /Create governed CommandRun/i }),
  ).toBeDisabled();

  await page.getByRole("button", { name: /Export review bundle/i }).click();
  await expect(page.getByText("a4-browser")).toBeVisible();
  await page.getByRole("button", { name: /Create governed CommandRun/i }).click();
  await expect(page.getByText("RUN_SUCCEEDED")).toBeVisible();
  await expect(
    page.getByText("human-review bundle exported").last(),
  ).toBeVisible();
});

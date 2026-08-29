import { expect, test } from "@playwright/test";

const registry = {
  schema_version: "finagent.workbench.config-registry.v1",
  read_only: true,
  warnings: [],
  descriptors: [{
    schema_version: "finagent.workbench.config-descriptor.v1",
    descriptor_id: "local_ashare",
    title: "Local A-share dataset certification",
    section: "local_ashare",
    default_domain: "runtime",
    snapshot_ids: ["config-snapshot-v35"],
    read_only: true,
    fields: [{
      field_path: "root",
      label: "root",
      value_type: "string",
      domain: "runtime",
      mutation_policy: "restart_or_new_run",
      required: true,
      secret_redacted: false,
      description: "",
    }],
  }],
  snapshots: [{
    schema_version: "finagent.workbench.config-snapshot.v1",
    snapshot_id: "config-snapshot-v35",
    descriptor_id: "local_ashare",
    section: "local_ashare",
    source_uri: "config://root-0/local.toml",
    source_sha256: "a".repeat(64),
    values: { root: "D:/Data/A-Share" },
    domains: { root: "runtime" },
    mutation_policies: { root: "restart_or_new_run" },
    redacted_fields: [],
    read_only: true,
  }],
};

const forbiddenAuthority = [
  "production_reserve",
  "strategy_promotion",
  "paper_mutation",
  "broker_order",
  "live_capital",
  "arbitrary_shell",
  "arbitrary_python",
];

const command = (
  commandId: string,
  title: string,
  readiness: "application_service_ready" | "adapter_required",
  level: "L0" | "L1",
) => ({
  schema_version: "finagent.workbench.command-spec.v1",
  command_id: commandId,
  title,
  description: `${title} acceptance description`,
  level,
  config_descriptor_ids: commandId === "config.validate" ? ["local_ashare"] : [],
  binding_kind: readiness === "application_service_ready" ? "application_service" : "cli_orchestration",
  binding_ref: readiness === "application_service_ready"
    ? "finagent.application.control_services.ConfigValidationApplicationService"
    : "scripts/run_local_ashare_robust_research.py",
  gateway_readiness: readiness,
  produces: [],
  requires_confirmation: level === "L1",
  execution_enabled: false,
  catalog_only: true,
});

const evidenceCommands = {
  schema_version: "finagent.workbench.command-catalog.v1",
  read_only: true,
  execution_enabled: false,
  control_plane_enabled: false,
  forbidden_authority: forbiddenAuthority,
  items: [
    command("config.validate", "Validate configuration", "application_service_ready", "L0"),
    command("research.run_a2p6", "Run A2.6 robust research", "adapter_required", "L1"),
  ],
};

const controlStatus = {
  schema_version: "finagent.workbench.control-status.v1",
  version: "finagent-workbench-control-api-v3.2",
  control_plane_enabled: true,
  local_only: true,
  remote_binding_supported: false,
  requested_by: "browser-acceptance",
  application_service_ready: ["config.validate"],
  recovered_incomplete_runs: [],
  store: {
    schema_version: "finagent.workbench.command-store.v1",
    run_counts: {},
    terminal_states: ["failed", "rejected", "succeeded"],
  },
  forbidden_authority: forbiddenAuthority,
};

const controlCommands = {
  schema_version: "finagent.workbench.control-command-catalog.v1",
  control_plane_enabled: true,
  local_only: true,
  forbidden_authority: forbiddenAuthority,
  items: evidenceCommands.items.map((item) => ({
    ...item,
    control_plane_enabled: true,
    control_execution_enabled: item.command_id === "config.validate",
  })),
};

test("V3-5 restores context across module navigation, history and reload with Evidence only", async ({
  page,
}) => {
  await page.route("**/api/v3/config", (route) => route.fulfill({ json: registry }));
  await page.route("**/api/v3/commands", (route) => route.fulfill({ json: evidenceCommands }));
  await page.route("http://127.0.0.1:8766/api/v3/control/**", (route) =>
    route.abort("connectionrefused"),
  );

  await page.goto(
    "/widgets?surface=configs&project=project-v35&run=run-v35&env=research",
  );
  await expect(page.getByText("Configuration Registry")).toBeVisible();
  const context = page.getByTestId("workbench-context-bar");
  await expect(context).toContainText("project-v35");
  await expect(context).toContainText("run-v35");
  await expect(context).toContainText("research");
  await expect(page.getByRole("button", { name: "Commands" })).toBeDisabled();

  await page.getByRole("link", { name: "Command Catalog" }).click();
  await expect(page).toHaveURL(/surface=commands/);
  await expect(page).toHaveURL(/project=project-v35/);
  await expect(page).toHaveURL(/run=run-v35/);
  await expect(page.getByRole("heading", { name: "Command Catalog" })).toBeVisible();
  await expect(context).toContainText("project-v35");

  await page.goBack();
  await expect(page).toHaveURL(/surface=configs/);
  await expect(page.getByText("Configuration Registry")).toBeVisible();
  await expect(context).toContainText("run-v35");

  await page.goForward();
  await expect(page).toHaveURL(/surface=commands/);
  await expect(page.getByRole("heading", { name: "Command Catalog" })).toBeVisible();
  await expect(context).toContainText("research");

  await page.reload();
  await expect(page.getByRole("heading", { name: "Command Catalog" })).toBeVisible();
  await expect(context).toContainText("project-v35");
  await expect(context).toContainText("run-v35");
  await expect(page.getByRole("button", { name: "Commands" })).toBeDisabled();
});

test("V3-5 exposes only allowlisted L0/L1 commands when both planes are present", async ({
  page,
}) => {
  await page.route("**/api/v3/config", (route) => route.fulfill({ json: registry }));
  await page.route("**/api/v3/commands", (route) => route.fulfill({ json: evidenceCommands }));
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

  await page.goto("/widgets?surface=commands&project=project-v35&env=research");
  const commandsButton = page.getByRole("button", { name: "Commands" });
  await expect(commandsButton).toBeEnabled();
  await commandsButton.click();

  const palette = page.getByRole("dialog", { name: "FinAgent Command Palette" });
  await expect(palette).toBeVisible();
  await expect(palette.getByText(/application_service_ready only/i)).toBeVisible();
  await expect(palette.getByText(/production reserve/i)).toBeVisible();
  await expect(palette.getByText(/PAPER mutation/i)).toBeVisible();
  await expect(palette.getByText(/broker order/i)).toBeVisible();
  await expect(palette.getByText(/arbitrary shell\/Python/i)).toBeVisible();

  await palette.getByRole("button", { name: /Run A2.6 robust research/i }).click();
  await expect(
    palette.getByText(/application-service adapter is not ready/i),
  ).toBeVisible();
  await expect(
    palette.getByRole("button", { name: /Create governed CommandRun/i }),
  ).toBeDisabled();

  await expect(
    palette.getByRole("button", {
      name: /reserve|promote|paper|broker|live|python|shell/i,
    }),
  ).toHaveCount(0);
});

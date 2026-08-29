import { expect, test } from "@playwright/test";

const registry = {
  schema_version: "finagent.workbench.config-registry.v1",
  read_only: true,
  warnings: ["secret-like config excluded without parsing: config-root-0/secrets.toml"],
  descriptors: [{
    schema_version: "finagent.workbench.config-descriptor.v1",
    descriptor_id: "ashare_portfolio_validation",
    title: "A4 portfolio validation",
    section: "ashare_portfolio_validation",
    default_domain: "research_protocol",
    snapshot_ids: ["config-snapshot-a4"],
    read_only: true,
    fields: [
      { field_path: "risk_aversion", label: "risk aversion", value_type: "number", domain: "research_protocol", mutation_policy: "new_identity_required", required: true, secret_redacted: false, description: "" },
      { field_path: "broker_commission_rate", label: "broker commission rate", value_type: "number", domain: "execution_protocol", mutation_policy: "new_identity_required", required: true, secret_redacted: false, description: "" },
      { field_path: "policy_min_net_sharpe", label: "policy min net sharpe", value_type: "number", domain: "operational_guardrail", mutation_policy: "governed_change_required", required: true, secret_redacted: false, description: "" },
      { field_path: "secrets_file", label: "secrets file", value_type: "string", domain: "secret_reference", mutation_policy: "host_secret_binding_only", required: true, secret_redacted: true, description: "" },
    ],
  }],
  snapshots: [{
    schema_version: "finagent.workbench.config-snapshot.v1",
    snapshot_id: "config-snapshot-a4",
    descriptor_id: "ashare_portfolio_validation",
    section: "ashare_portfolio_validation",
    source_uri: "config://root-0/a4.toml",
    source_sha256: "a".repeat(64),
    values: { risk_aversion: 3.0, broker_commission_rate: 0.0003, policy_min_net_sharpe: 0.5, secrets_file: "<secret-file-reference>" },
    domains: { risk_aversion: "research_protocol", broker_commission_rate: "execution_protocol", policy_min_net_sharpe: "operational_guardrail", secrets_file: "secret_reference" },
    mutation_policies: { risk_aversion: "new_identity_required", broker_commission_rate: "new_identity_required", policy_min_net_sharpe: "governed_change_required", secrets_file: "host_secret_binding_only" },
    redacted_fields: ["secrets_file"],
    read_only: true,
  }],
};

const commands = {
  schema_version: "finagent.workbench.command-catalog.v1",
  read_only: true,
  execution_enabled: false,
  control_plane_enabled: false,
  forbidden_authority: ["production_reserve", "strategy_promotion", "broker_order", "live_capital", "arbitrary_shell", "arbitrary_python"],
  items: [{
    schema_version: "finagent.workbench.command-spec.v1",
    command_id: "portfolio.run_a4",
    title: "Run A4 portfolio validation",
    description: "Future governed L1 entry for execution-aware internal A4 validation.",
    level: "L1",
    config_descriptor_ids: ["ashare_portfolio_validation"],
    binding_kind: "cli_orchestration",
    binding_ref: "scripts/run_ashare_portfolio_validation.py",
    gateway_readiness: "adapter_required",
    produces: ["AsharePortfolioValidationResult"],
    requires_confirmation: true,
    execution_enabled: false,
    catalog_only: true,
  }],
};

test("V3-2B exposes read-only config and command catalogs without control authority", async ({ page }) => {
  await page.route("**/api/v3/config", (route) => route.fulfill({ json: registry }));
  await page.route("**/api/v3/commands", (route) => route.fulfill({ json: commands }));

  await page.goto("/widgets?surface=configs&program=program-a26");
  await expect(page.getByText("Configuration Registry")).toBeVisible();
  await expect(page.getByRole("heading", { name: "A4 portfolio validation" })).toBeVisible();
  await expect(page.getByText("<secret-file-reference>")).toBeVisible();
  await expect(page.getByText("new_identity_required").first()).toBeVisible();
  await expect(page.getByText("governed_change_required")).toBeVisible();
  await expect(page.getByTestId("workbench-context-bar")).toContainText("program-a26");
  await expect(page.getByRole("button", { name: "Config" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Commands" })).toBeDisabled();

  await page.getByRole("link", { name: "Command Catalog" }).click();
  await expect(page.getByText("Command Catalog", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Run A4 portfolio validation")).toBeVisible();
  await expect(page.getByText("adapter_required")).toBeVisible();
  await expect(page.getByText(/Control Plane disabled/i)).toBeVisible();
  await expect(page.getByRole("button", { name: /Run A4 portfolio validation execution disabled/i })).toBeDisabled();
  await expect(page.getByText(/production_reserve/)).toBeVisible();
  await expect(page.getByRole("button", { name: /execute|promote|reserve|broker|order/i })).toHaveCount(0);
});

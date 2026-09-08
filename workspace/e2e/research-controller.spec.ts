import { expect, test } from "@playwright/test";

// An actual scripted provider + Parquet evaluator + SQLite audit fixture server.
// No API interception or synthetic result payloads are used here.
test.skip(!process.env.FINAGENT_R4_CONSOLE_URL, "Requires scripts/r4_console_fixture.py --serve");
test("shows Agent-first workspace, proposal provenance, negative terminal, economics and authority", async ({ page }) => {
  await page.goto(`${process.env.FINAGENT_R4_CONSOLE_URL}/agent?run=offline-proposal`);
  await expect(page.getByRole("heading", { name: "Research Workspace" })).toBeVisible();
  const terminal = page.getByRole("region", { name: "Accepted R4 terminal" });
  await expect(terminal.getByText("NO_ADAPTIVE_CANDIDATE")).toBeVisible();
  await expect(terminal.getByText("AgentValue INCONCLUSIVE")).toBeVisible();
  await expect(terminal.getByText("SLOT_ATTEMPTS_EXHAUSTED")).toBeVisible();
  await expect(page.getByText("Inspect and test a newly proposed factor on historical development data").first()).toBeVisible();
  const tools = page.locator(".research-tool-card");
  await expect(tools).toHaveCount(9);
  for (const title of ["MarketState inspection", "Literature inspection", "Factor proposal", "Factor development evaluation", "Factor set proposal", "Allocator proposal", "Portfolio evaluation", "Final candidate decision"]) {
    await expect(page.getByRole("article", { name: title, exact: true })).toBeVisible();
  }
  await expect(page.getByText("Proposed now")).toBeVisible();
  await expect(page.getByText(/Tested retrospectively/).first()).toBeVisible();
  await expect(page.getByText(/Not historically known/).first()).toBeVisible();
  const table = page.getByRole("table", { name: "5bp development comparison" });
  await expect(table.getByRole("row")).toHaveCount(6);
  await expect(table.getByRole("rowheader", { name: "ridge_meta", exact: true })).toBeVisible();
  const context = page.locator(".research-context");
  await expect(context.getByRole("heading", { name: "Remaining budget" })).toBeVisible();
  await expect(context.getByRole("heading", { name: "Current factor set" })).toBeVisible();
  await expect(context.getByText("equal_weight", { exact: true })).toBeVisible();
  await expect(context.getByText("No candidate; retrospective development fixture.")).toBeVisible();
  await expect(context.getByText(/Alpha: not confirmed/)).toBeVisible();
  await expect(context.getByText(/PAPER: not accepted/)).toBeVisible();
  await expect(context.getByText(/Live: not authorized/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Accepted R4 campaign attestation" })).toBeVisible();
  await page.screenshot({ path: "test-results/r4-controller-proposal.png", fullPage: true });
});

test("starts a bounded offline run from a human objective through the Control Plane without fabricating navigation identity", async ({ page }) => {
  test.setTimeout(120000);
  await page.goto(`${process.env.FINAGENT_R4_CONSOLE_URL}/agent`);
  await expect(page.getByText("scripted-offline · fixture")).toBeVisible();
  await page.getByLabel("Set the research objective").fill("Compare controlled development factor allocations; recommend no candidate");
  await page.getByRole("button", { name: "Start bounded research run" }).click();
  await expect(page.getByRole("article", { name: "Final candidate decision", exact: true })).toBeVisible({ timeout: 100000 });
  await expect(page.getByRole("article", { name: "Portfolio evaluation", exact: true })).toBeVisible();
  await expect(page.getByRole("article", { name: "Experiment comparison", exact: true })).toBeVisible();
  await expect(page.locator(".research-context").getByText("regime_conditional", { exact: true })).toBeVisible();
  await expect(page.locator(".research-context").getByText("NO_CANDIDATE_RECOMMENDED: controlled fixture only.")).toBeVisible();
  await expect(page.locator(".research-context").getByText(/Alpha: not confirmed/)).toBeVisible();
  await expect(page.getByRole("region", { name: "Accepted R4 terminal" }).getByText("NO_ADAPTIVE_CANDIDATE")).toBeVisible();
  await page.screenshot({ path: "test-results/r4-controller-start.png", fullPage: true });
});

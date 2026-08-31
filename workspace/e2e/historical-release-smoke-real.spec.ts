import { expect, test } from "@playwright/test";

const realSmokeEnabled = [
  "FINAGENT_HW_RS_OUTCOME",
  "FINAGENT_HW_RS_PORTFOLIO_VALIDATION_ID",
  "FINAGENT_HW_RS_STRATEGY_SERIES_ID",
  "FINAGENT_HW_RS_FACTOR_SERIES_ID",
  "FINAGENT_HW_RS_PROGRAM_RESULT_ID",
].every((name) => Boolean(process.env[name]?.trim()));

test.skip(
  !realSmokeEnabled,
  "real frozen-evidence smoke is executed only by the HW-1.0-RS local orchestrator",
);

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required by HW-1.0-RS`);
  return value;
}

test("Historical Workbench 1.0 renders the frozen release without inventing unavailable evidence", async ({ page }) => {
  test.setTimeout(90_000);
  const outcome = required("FINAGENT_HW_RS_OUTCOME");
  const validationId = required("FINAGENT_HW_RS_PORTFOLIO_VALIDATION_ID");
  const strategySeriesId = required("FINAGENT_HW_RS_STRATEGY_SERIES_ID");
  const factorSeriesId = required("FINAGENT_HW_RS_FACTOR_SERIES_ID");
  const programResultId = required("FINAGENT_HW_RS_PROGRAM_RESULT_ID");

  await page.goto(`/strategy/${encodeURIComponent(strategySeriesId)}?portfolio=${encodeURIComponent(validationId)}`);
  await expect(page.getByRole("heading", { name: "Signal → target → order → fill → realized PnL" })).toBeVisible();
  await expect(page.getByTestId("workbench-context-bar")).toContainText(validationId);
  await expect(page.getByText(/React performs no financial-fact recomputation/i)).toBeVisible();

  if (outcome === "NO_ROBUST_FACTOR_FAMILY") {
    await expect(page.locator(".metric-card", { hasText: "Rows in evidence" })).toContainText("0");
    await expect(page.locator(".metric-card", { hasText: "Assets" })).toContainText("0");
    await expect(page.locator(".metric-card", { hasText: "Market bars" })).toContainText("Unavailable");
    await expect(page.getByText("No decision rows in this slice")).toBeVisible();

    await page.goto("/portfolio");
    await expect(page.getByRole("heading", { name: "Portfolio" })).toBeVisible();
    await expect(page.getByText("No linked A4 + V4-0 evidence")).toBeVisible();

    await page.goto("/execution");
    await expect(page.getByRole("heading", { name: "Execution" })).toBeVisible();
    await expect(page.getByText("No linked A4 + V4-0 evidence")).toBeVisible();
  } else {
    await expect(page.locator(".metric-card", { hasText: "Rows in evidence" })).not.toContainText("0");
    await page.goto(`/portfolio/${encodeURIComponent(validationId)}`);
    await expect(page.getByText(validationId).first()).toBeVisible();
    await page.goto(`/execution/${encodeURIComponent(validationId)}`);
    await expect(page.getByText(validationId).first()).toBeVisible();
  }

  await page.goto(`/factors/${encodeURIComponent(factorSeriesId)}`);
  await expect(page.getByText("Verified V4-1 period rows + frozen A2.6 inference")).toBeVisible();
  await expect(page.getByText(/No factor statistics are reconstructed in React/i)).toBeVisible();
  await expect(page).toHaveURL(/program=/);
  await expect(page).toHaveURL(/factor=/);
  if (outcome === "NO_ROBUST_FACTOR_FAMILY") {
    await expect(page.locator(".metric-card", { hasText: "Gate" })).toContainText("REJECT");
  }
  await page.reload();
  await expect(page.getByText("Verified V4-1 period rows + frozen A2.6 inference")).toBeVisible();

  await page.goto("/catalog");
  await expect(page.getByRole("heading", { name: "Evidence catalog" })).toBeVisible();
  await expect(page.getByText("Immutable evidence")).toBeVisible();
  await expect(page.getByText(programResultId).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Commands" })).toBeDisabled();
});

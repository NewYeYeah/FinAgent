import { expect, test } from "@playwright/test";

const programId = "program-v45";
const factorId = "factor-v45";
const validationId = "portfolio-v45";
const assetId = "equity:SSE:600000:CNY";
const orderId = "order-v45";
const dateRange = "2024-01-02..2024-01-31";
const sessionDate = "2024-01-03";
const foldId = "wf-v45";

const emptyStrategyCatalog = {
  schema_version: "finagent.strategy-explorer.catalog.v1",
  read_only: true,
  items: [],
  warnings: [],
  notices: [],
};

const emptyFactorCatalog = {
  schema_version: "finagent.factor-tear-sheet.catalog.v1",
  read_only: true,
  items: [],
  warnings: [],
  notices: [],
};

const emptyPortfolioCatalog = {
  schema_version: "finagent.portfolio-execution.catalog.v1",
  read_only: true,
  items: [],
  warnings: [],
};

function expectLinkedContext(url: string): void {
  const parsed = new URL(url);
  expect(parsed.searchParams.get("program")).toBe(programId);
  expect(parsed.searchParams.get("factor")).toBe(factorId);
  expect(parsed.searchParams.get("portfolio")).toBe(validationId);
  expect(parsed.searchParams.get("asset")).toBe(assetId);
  expect(parsed.searchParams.get("order")).toBe(orderId);
  expect(parsed.searchParams.get("range")).toBe(dateRange);
  expect(parsed.searchParams.get("session")).toBe(sessionDate);
  expect(parsed.searchParams.get("fold")).toBe(foldId);
}

test("V4-5 preserves the complete linked analytics context through modules, history and reload", async ({ page }) => {
  await page.route("http://127.0.0.1:8766/api/v3/control/**", (route) =>
    route.abort("connectionrefused"),
  );
  await page.route("**/api/v4/strategy-series", (route) =>
    route.fulfill({ json: emptyStrategyCatalog }),
  );
  await page.route("**/api/v4/factor-series", (route) =>
    route.fulfill({ json: emptyFactorCatalog }),
  );
  await page.route("**/api/v4/portfolio-execution", (route) =>
    route.fulfill({ json: emptyPortfolioCatalog }),
  );

  const search = new URLSearchParams({
    program: programId,
    factor: factorId,
    portfolio: validationId,
    asset: assetId,
    order: orderId,
    range: dateRange,
    session: sessionDate,
    fold: foldId,
  });
  await page.goto(`/strategy?${search.toString()}`);

  const context = page.getByTestId("workbench-context-bar");
  for (const value of [
    programId,
    factorId,
    validationId,
    assetId,
    orderId,
    dateRange,
    sessionDate,
    foldId,
  ]) {
    await expect(context).toContainText(value);
  }
  await expect(page.getByRole("button", { name: "Commands" })).toBeDisabled();
  await expect(page.getByText("Evidence Plane")).toBeVisible();
  expectLinkedContext(page.url());

  await page.getByRole("link", { name: "Factors" }).click();
  await expect(page).toHaveURL(/\/factors\?/);
  expectLinkedContext(page.url());

  await page.getByRole("link", { name: "Portfolio" }).click();
  await expect(page).toHaveURL(/\/portfolio\?/);
  expectLinkedContext(page.url());

  await page.getByRole("link", { name: "Execution" }).click();
  await expect(page).toHaveURL(/\/execution\?/);
  expectLinkedContext(page.url());

  await page.goBack();
  await expect(page).toHaveURL(/\/portfolio\?/);
  expectLinkedContext(page.url());

  await page.goBack();
  await expect(page).toHaveURL(/\/factors\?/);
  expectLinkedContext(page.url());

  await page.goForward();
  await expect(page).toHaveURL(/\/portfolio\?/);
  expectLinkedContext(page.url());

  await page.reload();
  expectLinkedContext(page.url());
  for (const value of [programId, factorId, validationId, assetId, orderId, sessionDate, foldId]) {
    await expect(context).toContainText(value);
  }
});

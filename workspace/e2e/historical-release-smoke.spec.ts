import { expect, test } from "@playwright/test";

const validationId = "hw1-no-alpha-validation";
const strategySeriesId = "hw1-no-alpha-strategy";
const factorSeriesId = "hw1-no-alpha-factors";
const programResultId = "hw1-no-alpha-program-result";

const strategyItem = {
  series_id: strategySeriesId,
  portfolio_validation_id: validationId,
  source_program_result_id: programResultId,
  source_selection_id: "hw1-no-alpha-selection",
  data_version: "hw1-data",
  selected_feature_digests: [],
  alpha_model_ids: [],
  row_count: 0,
  session_count: 0,
  asset_count: 0,
  start_date: null,
  end_date: null,
  market_bar_series_id: null,
  market_bar_interval: null,
  ohlc_available: false,
  authority: "authoritative",
  detail_url: `/api/v4/strategy-series/${strategySeriesId}`,
};

const strategyCatalog = {
  schema_version: "finagent.strategy-explorer.catalog.v1",
  read_only: true,
  items: [strategyItem],
  warnings: [],
  notices: [],
};

const strategyDetail = {
  schema_version: "finagent.strategy-explorer.series.v1",
  read_only: true,
  item: strategyItem,
  manifest: {
    schema_version: "finagent.strategy-decision-series.manifest.v1",
    authority: "authoritative",
    series_id: strategySeriesId,
    portfolio_validation_id: validationId,
    a4_spec_id: "hw1-a4-spec",
    source_program_result_id: programResultId,
    source_program_spec_id: "hw1-program-spec",
    source_program_report_digest: "a".repeat(64),
    source_selection_id: "hw1-no-alpha-selection",
    data_version: "hw1-data",
    execution_ledger_digest: "hw1-empty-ledger",
    selected_feature_digests: [],
    alpha_model_ids: [],
    rows_digest: "hw1-empty-rows",
    source_report_file: "a4.json",
    source_report_sha256: "b".repeat(64),
    source_ledger_file: "a4.jsonl",
    source_ledger_sha256: "c".repeat(64),
    data_file: "a4.strategy-decisions.parquet",
    data_sha256: "d".repeat(64),
    row_count: 0,
    source_session_count: 0,
    row_session_count: 0,
    asset_count: 0,
    start_date: null,
    end_date: null,
    columns: [],
    nullable_columns: [],
  },
  presentation: {
    price_semantics: "authoritative_close_only",
    ohlc_available: false,
    ohlc_authority: "unavailable",
    market_bar_binding: null,
    browser_recomputation: false,
    factor_contribution_semantics: "combined alpha context and frozen component identities only",
  },
};

const strategyDimensions = {
  schema_version: "finagent.strategy-explorer.dimensions.v1",
  read_only: true,
  authority: "authoritative",
  series_id: strategySeriesId,
  portfolio_validation_id: validationId,
  assets: [],
  folds: [],
  start_date: null,
  end_date: null,
  session_count: 0,
  price_semantics: "close_price from authoritative A4 close marks",
  ohlc_available: false,
};

const factorCatalog = {
  schema_version: "finagent.factor-tear-sheet.catalog.v1",
  read_only: true,
  items: [
    {
      series_id: factorSeriesId,
      program_result_id: programResultId,
      program_id: "hw1-program",
      data_version: "hw1-data",
      candidate_feature_digests: ["factor-a", "factor-b"],
      selected_feature_digests: [],
      primary_label: "forward_simple_return_1",
      decay_labels: ["forward_simple_return_5"],
      row_count: 100,
      factor_count: 2,
      fold_count: 4,
      session_count: 20,
      start_date: "2021-01-01",
      end_date: "2024-12-31",
      authority: "authoritative",
      detail_url: `/api/v4/factor-series/${factorSeriesId}`,
    },
  ],
  warnings: [],
  notices: [],
};

const emptyPortfolio = {
  schema_version: "finagent.portfolio-execution.catalog.v1",
  read_only: true,
  items: [],
  warnings: [],
  notices: [],
};

test("HW-1.0-RS no-alpha UX stays complete and explicit instead of fabricating a portfolio", async ({ page }) => {
  await page.route("http://127.0.0.1:8766/api/v3/control/**", (route) => route.abort("connectionrefused"));
  await page.route("**/api/v4/strategy-series", (route) => route.fulfill({ json: strategyCatalog }));
  await page.route(`**/api/v4/strategy-series/${strategySeriesId}`, (route) => route.fulfill({ json: strategyDetail }));
  await page.route(`**/api/v4/strategy-series/${strategySeriesId}/dimensions`, (route) => route.fulfill({ json: strategyDimensions }));
  await page.route("**/api/v4/factor-series", (route) => route.fulfill({ json: factorCatalog }));
  await page.route("**/api/v4/portfolio-execution", (route) => route.fulfill({ json: emptyPortfolio }));

  await page.goto(`/strategy/${strategySeriesId}?portfolio=${validationId}`);
  await expect(page.getByRole("heading", { name: "Signal → target → order → fill → realized PnL" })).toBeVisible();
  await expect(page.locator(".metric-card", { hasText: "Rows in evidence" })).toContainText("0");
  await expect(page.locator(".metric-card", { hasText: "Assets" })).toContainText("0");
  await expect(page.locator(".metric-card", { hasText: "Market bars" })).toContainText("Unavailable");
  await expect(page.getByText("No decision rows in this slice")).toBeVisible();
  await expect(page.getByText(/OHLC is not fabricated/i)).toBeVisible();
  await expect(page.getByTestId("workbench-context-bar")).toContainText(validationId);

  await page.reload();
  await expect(page.getByText("No decision rows in this slice")).toBeVisible();
  await expect(page.getByTestId("workbench-context-bar")).toContainText(validationId);

  await page.goto("/portfolio");
  await expect(page.getByRole("heading", { name: "Portfolio" })).toBeVisible();
  await expect(page.getByText("No linked A4 + V4-0 evidence")).toBeVisible();

  await page.goto("/execution");
  await expect(page.getByRole("heading", { name: "Execution" })).toBeVisible();
  await expect(page.getByText("No linked A4 + V4-0 evidence")).toBeVisible();

  await page.goto("/factors");
  await expect(page.getByRole("heading", { name: "Factor Tear Sheet" })).toBeVisible();
  await expect(page.getByText("2 factors · 4 folds · 20 sessions")).toBeVisible();
  await expect(page.getByText(factorSeriesId)).toBeVisible();

  await expect(page.getByRole("button", { name: "Commands" })).toBeDisabled();
});

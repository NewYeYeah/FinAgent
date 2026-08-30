import { expect, test } from "@playwright/test";

const seriesId = "strategy-decision-series-e2e-v42";
const validationId = "a4-validation-e2e-v42";
const asset = "equity:SSE:600000:CNY";

const item = {
  series_id: seriesId,
  portfolio_validation_id: validationId,
  source_program_result_id: "program-result-e2e-v42",
  source_selection_id: "selection-e2e-v42",
  data_version: "data-e2e-v42",
  selected_feature_digests: ["factor-e2e-v42"],
  alpha_model_ids: ["alpha-model-e2e-v42"],
  row_count: 2,
  session_count: 2,
  asset_count: 1,
  start_date: "2024-01-02",
  end_date: "2024-01-03",
  authority: "authoritative",
  detail_url: `/api/v4/strategy-series/${seriesId}`,
};

const catalog = {
  schema_version: "finagent.strategy-explorer.catalog.v1",
  read_only: true,
  items: [item],
  warnings: [],
  notices: [],
};

const detail = {
  schema_version: "finagent.strategy-explorer.series.v1",
  read_only: true,
  item,
  manifest: {
    schema_version: "finagent.strategy-decision-series.manifest.v1",
    authority: "authoritative",
    series_id: seriesId,
    portfolio_validation_id: validationId,
    a4_spec_id: "a4-spec-e2e-v42",
    source_program_result_id: item.source_program_result_id,
    source_program_spec_id: "program-spec-e2e-v42",
    source_program_report_digest: "a".repeat(64),
    source_selection_id: item.source_selection_id,
    data_version: item.data_version,
    execution_ledger_digest: "ledger-e2e-v42",
    selected_feature_digests: item.selected_feature_digests,
    alpha_model_ids: item.alpha_model_ids,
    rows_digest: "rows-e2e-v42",
    source_report_file: "a4.json",
    source_report_sha256: "b".repeat(64),
    source_ledger_file: "a4.jsonl",
    source_ledger_sha256: "c".repeat(64),
    data_file: "a4.strategy-decisions.parquet",
    data_sha256: "d".repeat(64),
    row_count: 2,
    source_session_count: 2,
    row_session_count: 2,
    asset_count: 1,
    start_date: "2024-01-02",
    end_date: "2024-01-03",
    columns: [],
    nullable_columns: [],
  },
  presentation: {
    price_semantics: "authoritative_close_only",
    ohlc_available: false,
    browser_recomputation: false,
    factor_contribution_semantics: "combined alpha context and frozen component identities only",
  },
};

const dimensions = {
  schema_version: "finagent.strategy-explorer.dimensions.v1",
  read_only: true,
  authority: "authoritative",
  series_id: seriesId,
  portfolio_validation_id: validationId,
  assets: [asset],
  folds: ["wf-2024"],
  start_date: "2024-01-02",
  end_date: "2024-01-03",
  session_count: 2,
  price_semantics: "close_price from authoritative A4 close marks",
  ohlc_available: false,
};

const rows = [
  {
    sequence: 0,
    row_id: "row-e2e-v42-0",
    fold_id: "wf-2024",
    session_date: "2024-01-02",
    signal_asof: "2024-01-02T01:29:59.999999+00:00",
    asset,
    rebalanced: true,
    cash_fallback: false,
    target_id: "target-e2e-v42",
    alpha_score: 1.1,
    alpha_rank: 1,
    alpha_expected_return: 0.015,
    alpha_uncertainty: 0.008,
    pre_trade_weight: 0,
    target_weight: 0.4,
    realized_weight: 0.38,
    desired_side: "buy",
    desired_quantity: 100,
    executable_quantity: 100,
    filled_quantity: 100,
    reference_price: 10,
    fill_price: 10.05,
    close_price: 10.8,
    fees: 2,
    slippage: 5,
    gross_pnl: 80,
    net_pnl: 73,
    decision_status: "accepted",
    client_order_id: "order-e2e-v42",
    constraint_codes: ["ACCEPTED"],
  },
  {
    sequence: 1,
    row_id: "row-e2e-v42-1",
    fold_id: "wf-2024",
    session_date: "2024-01-03",
    signal_asof: "2024-01-03T01:29:59.999999+00:00",
    asset,
    rebalanced: false,
    cash_fallback: false,
    target_id: "",
    alpha_score: null,
    alpha_rank: null,
    alpha_expected_return: null,
    alpha_uncertainty: null,
    pre_trade_weight: null,
    target_weight: null,
    realized_weight: 0.39,
    desired_side: null,
    desired_quantity: 0,
    executable_quantity: 0,
    filled_quantity: 0,
    reference_price: null,
    fill_price: null,
    close_price: 11.1,
    fees: 0,
    slippage: 0,
    gross_pnl: 30,
    net_pnl: 30,
    decision_status: null,
    client_order_id: null,
    constraint_codes: [],
  },
];

const decisions = {
  schema_version: "finagent.strategy-decision-series.query.v1",
  read_only: true,
  authority: "authoritative",
  series_id: seriesId,
  portfolio_validation_id: validationId,
  filters: { asset, start: "2024-01-02", end: "2024-01-03", fold_id: null, limit: 5000, offset: 0 },
  total: 2,
  items: rows,
};

test("V4-2 exposes linked authoritative strategy decisions without synthetic OHLC", async ({ page }) => {
  await page.route("http://127.0.0.1:8766/api/v3/control/**", (route) =>
    route.abort("connectionrefused"),
  );
  await page.route("**/api/v4/strategy-series", (route) => route.fulfill({ json: catalog }));
  await page.route(`**/api/v4/strategy-series/${seriesId}/dimensions`, (route) => route.fulfill({ json: dimensions }));
  await page.route(`**/api/v4/strategy-series/${seriesId}/decisions?*`, (route) => route.fulfill({ json: decisions }));
  await page.route(`**/api/v4/strategy-series/${seriesId}`, (route) => route.fulfill({ json: detail }));

  await page.goto(`/strategy/${seriesId}?portfolio=${validationId}&asset=${encodeURIComponent(asset)}`);

  await expect(page.getByRole("heading", { name: "Signal → target → order → fill → realized PnL" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Strategy" })).toBeVisible();
  await expect(page.getByText(/OHLC is not present in V4-0 and is not fabricated/i)).toBeVisible();
  await expect(page.getByText("Authoritative close-price & execution timeline")).toBeVisible();
  await expect(page.getByText("Target vs realized weight")).toBeVisible();
  await expect(page.getByText("Frozen alpha context")).toBeVisible();
  await expect(page.getByText("Gross-to-net PnL & execution costs")).toBeVisible();
  await expect(page.locator(".strategy-code-list code", { hasText: /^ACCEPTED$/ })).toBeVisible();

  const context = page.getByTestId("workbench-context-bar");
  await expect(context).toContainText(validationId);
  await expect(context).toContainText(asset);
  await expect(page.getByRole("button", { name: "Commands" })).toBeDisabled();

  await page.getByLabel("Fold").selectOption("wf-2024");
  await expect(page).toHaveURL(/fold=wf-2024/);
  await expect(page).toHaveURL(new RegExp(`portfolio=${validationId}`));
  await expect(page).toHaveURL(/asset=equity%3ASSE%3A600000%3ACNY/);

  await page.reload();
  await expect(page.getByText("Authoritative close-price & execution timeline")).toBeVisible();
  await expect(context).toContainText("wf-2024");
});

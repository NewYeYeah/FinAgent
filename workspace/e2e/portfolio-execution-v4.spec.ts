import { expect, test } from "@playwright/test";

const validationId = "a4-validation-e2e-v44";
const seriesId = "strategy-series-e2e-v44";
const asset = "equity:SSE:600000:CNY";
const orderId = "net-e2e-1";

const item = {
  portfolio_validation_id: validationId,
  strategy_series_id: seriesId,
  source_program_result_id: "program-result-e2e-v44",
  source_selection_id: "selection-e2e-v44",
  row_count: 2,
  asset_count: 1,
  fold_count: 1,
  session_count: 2,
  start_date: "2024-01-02",
  end_date: "2024-01-03",
  status: "EXECUTION_VALIDATION_PASSED_INTERNAL",
  authority: "authoritative_identity_binding",
  detail_url: `/api/v4/portfolio-execution/${validationId}`,
};

const catalog = {
  schema_version: "finagent.portfolio-execution.catalog.v1",
  read_only: true,
  items: [item],
  warnings: [],
};

const detail = {
  schema_version: "finagent.portfolio-execution.detail.v1",
  read_only: true,
  item,
  portfolio_metrics: {
    gross_return: 0.1,
    net_return: 0.094,
    gross_annualized_return: 0.22,
    net_annualized_return: 0.2,
    gross_sharpe: 1.7,
    net_sharpe: 1.5,
    max_drawdown: 0,
    gross_to_net_drag: 0.006,
    one_way_turnover: 0.25,
    implementation_shortfall: 0.005,
    cash_fallback_ratio: 0,
    rejected_order_ratio: 0,
    maximum_ex_post_participation: 0.05,
    authority: "authoritative",
  },
  economic_evidence: {},
  folds: [{ fold_id: "wf-1" }],
  ledger: { available: true, row_count: 2, authority: "authoritative" },
  authority: {
    portfolio_metrics: "authoritative_a4_report",
    economic_evidence: "authoritative_a4_report",
    folds: "authoritative_a4_report",
    ledger: "authoritative_a4_execution_ledger",
  },
  presentation: {
    browser_recomputation: false,
    drawdown: "derived_presentation_from_authoritative_a4_nav",
    rolling: "derived_presentation_from_authoritative_a4_returns",
    monthly_returns: "derived_presentation_from_authoritative_a4_returns",
    filtered_costs: "derived_presentation_sum_of_authoritative_v4_0_cost_rows",
    constraint_counts: "derived_presentation_count_of_authoritative_v4_0_constraint_codes",
    target_realized: "authoritative_v4_0_rows",
    benchmark_available: false,
    order_id_available: true,
    benchmark_note: "No immutable benchmark return/NAV evidence is persisted for V4-4",
    order_identity_note: "V4-0 client_order_id is retained.",
  },
};

const series = {
  schema_version: "finagent.portfolio-execution.series.v1",
  read_only: true,
  authority: "authoritative_a4_points",
  portfolio_validation_id: validationId,
  total: 2,
  offset: 0,
  limit: 5000,
  items: [
    { session_date: "2024-01-02", fold_id: "wf-1", net_nav: 1044, gross_nav: 1050, net_return: 0.044, gross_return: 0.05, authority: "authoritative_a4_point" },
    { session_date: "2024-01-03", fold_id: "wf-1", net_nav: 1094, gross_nav: 1100, net_return: 0.0478927, gross_return: 0.047619, authority: "authoritative_a4_point" },
  ],
};

const allDecisions = [
  {
    row_id: "row-e2e-1",
    schema_version: "finagent.strategy-decision-row.v1",
    fold_id: "wf-1",
    session_date: "2024-01-02",
    signal_asof: "2024-01-02T01:29:59+00:00",
    asset,
    rebalanced: true,
    cash_fallback: false,
    target_id: "target-1",
    alpha_score: 1.2,
    alpha_rank: 1,
    alpha_expected_return: 0.02,
    alpha_uncertainty: 0.01,
    pre_trade_weight: 0,
    target_weight: 0.5,
    realized_weight: 0.5268,
    desired_side: "buy",
    desired_quantity: 50,
    executable_quantity: 50,
    filled_quantity: 50,
    reference_price: 10,
    fill_price: 10.1,
    close_price: 11,
    fees: 1,
    slippage: 5,
    gross_pnl: 50,
    net_pnl: 44,
    decision_status: "accepted",
    client_order_id: orderId,
    constraint_codes: ["ACCEPTED"],
  },
  {
    row_id: "row-e2e-2",
    schema_version: "finagent.strategy-decision-row.v1",
    fold_id: "wf-1",
    session_date: "2024-01-03",
    signal_asof: "2024-01-03T01:29:59+00:00",
    asset,
    rebalanced: false,
    cash_fallback: false,
    target_id: "",
    alpha_score: null,
    alpha_rank: null,
    alpha_expected_return: null,
    alpha_uncertainty: null,
    pre_trade_weight: 0.5268,
    target_weight: null,
    realized_weight: 0.5484,
    desired_side: null,
    desired_quantity: 0,
    executable_quantity: 0,
    filled_quantity: 0,
    reference_price: null,
    fill_price: null,
    close_price: 12,
    fees: 0,
    slippage: 0,
    gross_pnl: 50,
    net_pnl: 50,
    decision_status: null,
    client_order_id: null,
    constraint_codes: [],
  },
];

function decisionPayload(url: string) {
  const request = new URL(url);
  const requestedOrder = request.searchParams.get("order_id");
  const session = request.searchParams.get("session_date");
  const requestedAsset = request.searchParams.get("asset");
  const start = request.searchParams.get("start");
  const end = request.searchParams.get("end");
  const rows = allDecisions.filter((row) =>
    (!requestedOrder || row.client_order_id === requestedOrder)
    && (!session || row.session_date === session)
    && (!requestedAsset || row.asset === requestedAsset)
    && (!start || row.session_date >= start)
    && (!end || row.session_date <= end),
  );
  return {
    schema_version: "finagent.strategy-decision-series.query.v1",
    read_only: true,
    authority: "authoritative",
    series_id: seriesId,
    total: rows.length,
    offset: 0,
    limit: 5000,
    items: rows,
  };
}

function analyticsPayload(url: string) {
  const request = new URL(url);
  const requestedOrder = request.searchParams.get("order_id");
  const requestedAsset = request.searchParams.get("asset");
  const start = request.searchParams.get("start");
  const end = request.searchParams.get("end");
  const rows = allDecisions.filter((row) =>
    (!requestedOrder || row.client_order_id === requestedOrder)
    && (!requestedAsset || row.asset === requestedAsset)
    && (!start || row.session_date >= start)
    && (!end || row.session_date <= end),
  );
  const fees = rows.reduce((total, row) => total + row.fees, 0);
  const slippage = rows.reduce((total, row) => total + row.slippage, 0);
  return {
    schema_version: "finagent.portfolio-execution.analytics.v1",
    read_only: true,
    portfolio_validation_id: validationId,
    filters: { asset: requestedAsset, order_id: requestedOrder, fold_id: "wf-1", start, end, window: 20 },
    drawdown: {
      authority: "derived_presentation",
      source_authority: "authoritative_a4_points",
      formula: "nav / running_peak_nav - 1",
      items: series.items.filter((row) => (!start || row.session_date >= start) && (!end || row.session_date <= end)).map((row) => ({ session_date: row.session_date, fold_id: row.fold_id, net_drawdown: 0, gross_drawdown: 0 })),
    },
    rolling: {
      authority: "derived_presentation",
      source_authority: "authoritative_a4_net_returns",
      annualization: 252,
      window: 20,
      items: series.items.filter((row) => (!start || row.session_date >= start) && (!end || row.session_date <= end)).map((row, index) => ({ session_date: row.session_date, fold_id: row.fold_id, window_periods: index + 1, rolling_return: row.net_return, rolling_volatility: 0, rolling_sharpe: 0 })),
    },
    monthly_returns: {
      authority: "derived_presentation",
      source_authority: "authoritative_a4_period_returns",
      formula: "product(1 + period_return) - 1 by calendar month",
      items: [{ month: "2024-01", year: 2024, month_number: 1, net_return: 0.094, gross_return: 0.1, periods: 2 }],
    },
    filtered_costs: {
      authority: "derived_presentation",
      source_authority: "authoritative_v4_0_cost_rows",
      fees,
      slippage,
      total_cost: fees + slippage,
      decision_row_count: rows.length,
    },
    order_funnel: {
      authority: "derived_presentation",
      source_authority: "authoritative_v4_0_order_quantity_rows",
      desired: rows.filter((row) => row.desired_quantity > 0).length,
      executable: rows.filter((row) => row.executable_quantity > 0).length,
      filled: rows.filter((row) => row.filled_quantity > 0).length,
      decision_status_counts: { accepted: rows.filter((row) => row.decision_status === "accepted").length },
      order_id_available: true,
    },
    constraint_attribution: {
      authority: "derived_presentation",
      source_authority: "authoritative_v4_0_constraint_code_rows",
      reason_counts: rows.some((row) => row.constraint_codes.includes("ACCEPTED")) ? { ACCEPTED: 1 } : {},
    },
    benchmark: {
      available: false,
      authority: "unavailable_not_inferred",
      note: "No immutable benchmark return/NAV evidence is persisted for V4-4",
    },
  };
}

test("V4-4 links execution identities into portfolio analytics without browser financial recomputation", async ({ page }) => {
  await page.route("http://127.0.0.1:8766/api/v3/control/**", (route) => route.abort("connectionrefused"));
  await page.route("**/api/v4/portfolio-execution", (route) => route.fulfill({ json: catalog }));
  await page.route(`**/api/v4/portfolio-execution/${validationId}/series?*`, (route) => route.fulfill({ json: series }));
  await page.route(`**/api/v4/portfolio-execution/${validationId}/analytics?*`, (route) => route.fulfill({ json: analyticsPayload(route.request().url()) }));
  await page.route(`**/api/v4/portfolio-execution/${validationId}/decisions?*`, (route) => route.fulfill({ json: decisionPayload(route.request().url()) }));
  await page.route(`**/api/v4/portfolio-execution/${validationId}`, (route) => route.fulfill({ json: detail }));

  await page.goto(`/execution/${validationId}?portfolio=${validationId}`);

  await expect(page.getByRole("heading", { name: validationId })).toBeVisible();
  await expect(page.getByText("Target vs realized portfolio state")).toBeVisible();
  await expect(page.getByText("A3 constraint attribution")).toBeVisible();
  await expect(page.getByRole("button", { name: "Commands" })).toBeDisabled();

  const context = page.getByTestId("workbench-context-bar");
  await expect(context).toContainText(validationId);
  await expect(context).toContainText(asset);

  await page.locator("label").filter({ hasText: /^Order/ }).locator("select").selectOption(orderId);
  await expect(page).toHaveURL(new RegExp(`order=${orderId}`));
  await expect(context).toContainText(orderId);

  await page.locator("label").filter({ hasText: /^Session/ }).locator("select").selectOption("2024-01-02");
  await expect(page).toHaveURL(/session=2024-01-02/);
  await expect(context).toContainText("2024-01-02");
  await expect(page.getByText("Decision rows", { exact: true }).locator("..")).toContainText("1");

  await page.getByRole("link", { name: /Open Portfolio/i }).click();
  await expect(page).toHaveURL(new RegExp(`/portfolio/${validationId}`));
  await expect(page).toHaveURL(new RegExp(`order=${orderId}`));
  await expect(page).toHaveURL(/session=2024-01-02/);
  await expect(page.getByText("NAV & drawdown")).toBeVisible();
  await expect(page.getByText("Monthly return matrix")).toBeVisible();
  await expect(page.getByText("benchmark unavailable")).toBeVisible();
  await expect(page.getByText(/No NAV, return, drawdown, rolling statistic, monthly return or cost aggregate is reconstructed in React/i)).toBeVisible();

  await page.reload();
  await expect(page.getByText("NAV & drawdown")).toBeVisible();
  await expect(context).toContainText(orderId);
  await expect(context).toContainText("2024-01-02");
});
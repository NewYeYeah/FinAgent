import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

vi.mock("echarts-for-react", () => ({
  default: ({ option }: { option: { series?: Array<{ name?: string; type?: string }> } }) => (
    <div data-testid="echarts">
      {(option.series ?? []).map((series) => series.name ?? series.type ?? "series").join("|")}
    </div>
  ),
}));

import { WorkbenchContextProvider } from "./context";
import {
  ExecutionInteractivePage,
  PortfolioInteractivePage,
} from "./portfolioExecution";
import { WorkbenchQueryProvider } from "./query";

const validationId = "a4-validation-v44";
const seriesId = "strategy-series-v44";
const asset = "equity:SSE:600000:CNY";
const orderId = "net-1";

function response(payload: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const item = {
  portfolio_validation_id: validationId,
  strategy_series_id: seriesId,
  source_program_result_id: "program-result-v44",
  source_selection_id: "selection-v44",
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
  ledger: { row_count: 2, authority: "authoritative" },
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

const analytics = {
  schema_version: "finagent.portfolio-execution.analytics.v1",
  read_only: true,
  portfolio_validation_id: validationId,
  filters: { asset: null, order_id: null, fold_id: "wf-1", start: "2024-01-02", end: "2024-01-03", window: 20 },
  drawdown: {
    authority: "derived_presentation",
    source_authority: "authoritative_a4_points",
    formula: "nav / running_peak_nav - 1",
    items: [
      { session_date: "2024-01-02", fold_id: "wf-1", net_drawdown: 0, gross_drawdown: 0 },
      { session_date: "2024-01-03", fold_id: "wf-1", net_drawdown: 0, gross_drawdown: 0 },
    ],
  },
  rolling: {
    authority: "derived_presentation",
    source_authority: "authoritative_a4_net_returns",
    annualization: 252,
    window: 20,
    items: [
      { session_date: "2024-01-02", fold_id: "wf-1", window_periods: 1, rolling_return: 0.044, rolling_volatility: 0, rolling_sharpe: 0 },
      { session_date: "2024-01-03", fold_id: "wf-1", window_periods: 2, rolling_return: 0.094, rolling_volatility: 0.043, rolling_sharpe: 17.2 },
    ],
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
    fees: 1,
    slippage: 5,
    total_cost: 6,
    decision_row_count: 2,
  },
  order_funnel: {
    authority: "derived_presentation",
    source_authority: "authoritative_v4_0_order_quantity_rows",
    desired: 1,
    executable: 1,
    filled: 1,
    decision_status_counts: { accepted: 1 },
    order_id_available: true,
  },
  constraint_attribution: {
    authority: "derived_presentation",
    source_authority: "authoritative_v4_0_constraint_code_rows",
    reason_counts: { ACCEPTED: 1 },
  },
  benchmark: {
    available: false,
    authority: "unavailable_not_inferred",
    note: "No immutable benchmark return/NAV evidence is persisted for V4-4",
  },
};

const decisions = {
  schema_version: "finagent.strategy-decision-series.query.v1",
  read_only: true,
  authority: "authoritative",
  series_id: seriesId,
  total: 2,
  offset: 0,
  limit: 5000,
  items: [
    {
      row_id: "row-1",
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
      row_id: "row-2",
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
  ],
};

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

function renderPage(mode: "portfolio" | "execution", initial: string) {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <WorkbenchQueryProvider>
        <WorkbenchContextProvider>
          <LocationProbe />
          <Routes>
            <Route path="/portfolio/:validationId" element={<PortfolioInteractivePage />} />
            <Route path="/execution/:validationId" element={<ExecutionInteractivePage />} />
          </Routes>
        </WorkbenchContextProvider>
      </WorkbenchQueryProvider>
    </MemoryRouter>,
  );
}

describe("V4-4 Portfolio / Execution Interactive Pack", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v4/portfolio-execution") return response(catalog);
      if (url === `/api/v4/portfolio-execution/${validationId}`) return response(detail);
      if (url.includes(`/api/v4/portfolio-execution/${validationId}/series?`)) return response(series);
      if (url.includes(`/api/v4/portfolio-execution/${validationId}/analytics?`)) return response(analytics);
      if (url.includes(`/api/v4/portfolio-execution/${validationId}/decisions?`)) {
        const request = new URL(url, "http://localhost");
        const order = request.searchParams.get("order_id");
        const session = request.searchParams.get("session_date");
        const items = decisions.items.filter((row) =>
          (!order || row.client_order_id === order) && (!session || row.session_date === session),
        );
        return response({ ...decisions, total: items.length, items });
      }
      throw new Error(`unexpected request: ${url}`);
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders A4 authority and labels all portfolio transforms as server-side derived", async () => {
    renderPage(
      "portfolio",
      `/portfolio/${validationId}?portfolio=${validationId}&fold=wf-1&range=2024-01-02..2024-01-03`,
    );

    expect(await screen.findByText("NAV & drawdown")).toBeInTheDocument();
    expect(screen.getByText(/A4 portfolio authority/i)).toBeInTheDocument();
    expect(screen.getByText(/No NAV, return, drawdown, rolling statistic, monthly return or cost aggregate is reconstructed in React/i)).toBeInTheDocument();
    expect(screen.getByText("Monthly return matrix")).toBeInTheDocument();
    expect(screen.getByText("Filtered cost waterfall")).toBeInTheDocument();
    expect(screen.getByText("benchmark unavailable")).toBeInTheDocument();
    expect(screen.getAllByTestId("echarts").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByTestId("location").textContent).toContain(`portfolio=${validationId}`);
    expect(screen.getByTestId("location").textContent).toContain("fold=wf-1");
  });

  it("binds asset/order/session through WorkbenchContext and forwards one session to authoritative and derived queries", async () => {
    renderPage("execution", `/execution/${validationId}?portfolio=${validationId}`);
    expect(await screen.findByText("Target vs realized portfolio state")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("location").textContent).toContain(`asset=${encodeURIComponent(asset)}`);
    });

    fireEvent.change(screen.getByLabelText(/^Order/), { target: { value: orderId } });
    await waitFor(() => expect(screen.getByTestId("location").textContent).toContain(`order=${orderId}`));

    fireEvent.change(screen.getByLabelText(/^Session/), { target: { value: "2024-01-02" } });
    await waitFor(() => {
      const location = screen.getByTestId("location").textContent ?? "";
      expect(location).toContain("session=2024-01-02");
      const calls = vi.mocked(fetch).mock.calls.map(([value]) => String(value));
      expect(calls.some((value) => value.includes("order_id=net-1"))).toBe(true);
      expect(calls.some((value) => value.includes("session_date=2024-01-02"))).toBe(true);
      expect(calls.some((value) => value.includes("start=2024-01-02") && value.includes("end=2024-01-02") && value.includes("/analytics?"))).toBe(true);
      expect(calls.some((value) => value.includes("limit=5000"))).toBe(true);
    });

    expect(screen.getByText(orderId)).toBeInTheDocument();
    expect(screen.getByText("A3 constraint attribution")).toBeInTheDocument();
    expect(screen.getByText(/no order identity is synthesized/i)).toBeInTheDocument();
  });
});

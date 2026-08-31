import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("echarts-for-react", () => ({
  default: ({ option }: { option: { series?: Array<{ name?: string }> } }) => (
    <div data-testid="echarts">
      {(option.series ?? []).map((series) => series.name).filter(Boolean).join("|")}
    </div>
  ),
}));

import { WorkbenchContextProvider } from "./context";
import { WorkbenchQueryProvider } from "./query";
import { StrategyDecisionExplorerPage } from "./strategy";

function json(payload: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const seriesId = "strategy-decision-series-ac2";
const validationId = "a4-validation-ac2";
const marketBarSeriesId = "market-bar-series-ac2";
const asset = "equity:SSE:600000:CNY";

const item = {
  series_id: seriesId,
  portfolio_validation_id: validationId,
  source_program_result_id: "program-result-ac2",
  source_selection_id: "selection-ac2",
  data_version: "data-ac2",
  selected_feature_digests: ["factor-ac2"],
  alpha_model_ids: ["alpha-ac2"],
  row_count: 2,
  session_count: 2,
  asset_count: 1,
  start_date: "2024-01-02",
  end_date: "2024-01-03",
  market_bar_series_id: marketBarSeriesId,
  market_bar_interval: "1d",
  ohlc_available: true,
  authority: "authoritative",
  detail_url: `/api/v4/strategy-series/${seriesId}`,
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
    a4_spec_id: "a4-spec-ac2",
    source_program_result_id: "program-result-ac2",
    source_program_spec_id: "program-spec-ac2",
    source_program_report_digest: "a".repeat(64),
    source_selection_id: "selection-ac2",
    data_version: "data-ac2",
    execution_ledger_digest: "ledger-ac2",
    selected_feature_digests: item.selected_feature_digests,
    alpha_model_ids: item.alpha_model_ids,
    rows_digest: "rows-ac2",
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
    factor_contribution_semantics: "identity only",
  },
};

const dimensions = {
  schema_version: "finagent.strategy-explorer.dimensions.v1",
  read_only: true,
  authority: "authoritative",
  series_id: seriesId,
  portfolio_validation_id: validationId,
  assets: [asset],
  folds: ["wf-1"],
  start_date: "2024-01-02",
  end_date: "2024-01-03",
  session_count: 2,
  price_semantics: "OHLC from bound MarketBarSeriesEvidence",
  ohlc_available: true,
  market_bar_series_id: marketBarSeriesId,
  market_bar_interval: "1d",
};

const decisionRows = [
  {
    sequence: 0,
    row_id: "decision-0",
    fold_id: "wf-1",
    session_date: "2024-01-02",
    signal_asof: "2024-01-02T01:29:59+00:00",
    asset,
    rebalanced: true,
    cash_fallback: false,
    target_id: "target-ac2",
    alpha_score: 1.0,
    alpha_rank: 1,
    alpha_expected_return: 0.02,
    alpha_uncertainty: 0.01,
    pre_trade_weight: 0,
    target_weight: 0.5,
    realized_weight: 0.48,
    desired_side: "buy",
    desired_quantity: 100,
    executable_quantity: 100,
    filled_quantity: 100,
    reference_price: 10,
    fill_price: 10.1,
    close_price: 11,
    fees: 1,
    slippage: 10,
    gross_pnl: 100,
    net_pnl: 89,
    decision_status: "accepted",
    client_order_id: "order-ac2",
    constraint_codes: [],
  },
  {
    sequence: 1,
    row_id: "decision-1",
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
    pre_trade_weight: null,
    target_weight: null,
    realized_weight: 0.49,
    desired_side: null,
    desired_quantity: 0,
    executable_quantity: 0,
    filled_quantity: 0,
    reference_price: null,
    fill_price: null,
    close_price: 12,
    fees: 0,
    slippage: 0,
    gross_pnl: 80,
    net_pnl: 80,
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
  items: decisionRows,
};

const marketBars = {
  schema_version: "finagent.market-bar-series.query.v1",
  read_only: true,
  authority: "authoritative",
  series_id: marketBarSeriesId,
  linked_strategy_series_id: seriesId,
  portfolio_validation_id: validationId,
  interval: "1d",
  timestamp_convention: "session_open",
  session_spec: {
    market_id: "CN_A_SHARE",
    timezone: "Asia/Shanghai",
    segments: [
      { name: "morning", start: "09:30", end: "11:30", session_type: "regular" },
      { name: "afternoon", start: "13:00", end: "15:00", session_type: "regular" },
    ],
  },
  label_horizon_policy: { mode: "trading_days", value: 1, allow_cross_session: true },
  filters: { asset, start: "2024-01-02", end: "2024-01-03", limit: 5000, offset: 0 },
  total: 2,
  items: [
    {
      sequence: 0,
      row_id: "bar-0",
      asset,
      session_date: "2024-01-02",
      event_time: "2024-01-02T01:30:00+00:00",
      available_at: "2024-01-02T08:00:00+00:00",
      interval: "1d",
      open: 10,
      high: 11.5,
      low: 9.8,
      close: 11,
      volume: 1_000_000,
      session_id: "CN_A_SHARE:2024-01-02",
      session_type: "regular",
      source: "certified",
      data_version: "data-ac2",
    },
    {
      sequence: 1,
      row_id: "bar-1",
      asset,
      session_date: "2024-01-03",
      event_time: "2024-01-03T01:30:00+00:00",
      available_at: "2024-01-03T08:00:00+00:00",
      interval: "1d",
      open: 11.1,
      high: 12.4,
      low: 10.9,
      close: 12,
      volume: 1_200_000,
      session_id: "CN_A_SHARE:2024-01-03",
      session_type: "regular",
      source: "certified",
      data_version: "data-ac2",
    },
  ],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/strategy/${seriesId}?portfolio=${validationId}&asset=${encodeURIComponent(asset)}`]}>
      <WorkbenchQueryProvider>
        <WorkbenchContextProvider>
          <Routes>
            <Route path="/strategy/:seriesId" element={<StrategyDecisionExplorerPage />} />
          </Routes>
        </WorkbenchContextProvider>
      </WorkbenchQueryProvider>
    </MemoryRouter>,
  );
}

describe("A-C2 Strategy MarketBarSeries", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v4/strategy-series") return json({
        schema_version: "finagent.strategy-explorer.catalog.v1",
        read_only: true,
        items: [item],
        warnings: [],
        notices: [],
      });
      if (url.endsWith(`/api/v4/strategy-series/${seriesId}`)) return json(detail);
      if (url.endsWith(`/api/v4/strategy-series/${seriesId}/dimensions`)) return json(dimensions);
      if (url.includes(`/api/v4/strategy-series/${seriesId}/decisions?`)) return json(decisions);
      if (url.includes(`/api/v4/strategy-series/${seriesId}/market-bars?`)) return json(marketBars);
      throw new Error(`unexpected request: ${url}`);
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders direct MarketBarSeries OHLC with V4-0 execution overlays", async () => {
    renderPage();

    expect(await screen.findByText("Authoritative OHLC & execution timeline")).toBeInTheDocument();
    expect(screen.getByText(/OHLCV is passed through from the bound MarketBarSeriesEvidence/i)).toBeInTheDocument();
    expect(screen.getByText("1d")).toBeInTheDocument();

    await waitFor(() => {
      const charts = screen.getAllByTestId("echarts");
      expect(charts).toHaveLength(4);
      expect(charts[0]).toHaveTextContent("OHLC|Reference|Buy fill|Sell fill");
      expect(charts[0]).not.toHaveTextContent("Close|");
    });

    const calls = vi.mocked(fetch).mock.calls.map(([value]) => String(value));
    const barsCall = calls.find((value) => value.includes("/market-bars?"));
    expect(barsCall).toContain(`asset=${encodeURIComponent(asset)}`);
    expect(barsCall).toContain("limit=5000");
  });
});

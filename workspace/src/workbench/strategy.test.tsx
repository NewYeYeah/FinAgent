import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

const seriesId = "strategy-decision-series-v42";
const validationId = "a4-validation-v42";
const asset = "equity:SSE:600000:CNY";

const item = {
  series_id: seriesId,
  portfolio_validation_id: validationId,
  source_program_result_id: "program-result-v42",
  source_selection_id: "selection-v42",
  data_version: "data-v42",
  selected_feature_digests: ["factor-alpha-v42", "factor-beta-v42"],
  alpha_model_ids: ["alpha-model-v42"],
  row_count: 2,
  session_count: 2,
  asset_count: 1,
  start_date: "2024-01-02",
  end_date: "2024-01-03",
  ohlc_available: false,
  market_bar_series_id: null,
  market_bar_interval: null,
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
    a4_spec_id: "a4-spec-v42",
    source_program_result_id: "program-result-v42",
    source_program_spec_id: "program-spec-v42",
    source_program_report_digest: "a".repeat(64),
    source_selection_id: "selection-v42",
    data_version: "data-v42",
    execution_ledger_digest: "ledger-v42",
    selected_feature_digests: item.selected_feature_digests,
    alpha_model_ids: item.alpha_model_ids,
    rows_digest: "rows-v42",
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
  folds: ["wf-1"],
  start_date: "2024-01-02",
  end_date: "2024-01-03",
  session_count: 2,
  price_semantics: "close_price from authoritative A4 close marks",
  ohlc_available: false,
  market_bar_series_id: null,
  market_bar_interval: null,
};

const decisionRows = [
  {
    sequence: 0,
    row_id: "row-v42-0",
    fold_id: "wf-1",
    session_date: "2024-01-02",
    signal_asof: "2024-01-02T01:29:59.999999+00:00",
    asset,
    rebalanced: true,
    cash_fallback: false,
    target_id: "target-v42",
    alpha_score: 1.25,
    alpha_rank: 1,
    alpha_expected_return: 0.02,
    alpha_uncertainty: 0.01,
    pre_trade_weight: 0,
    target_weight: 0.5,
    realized_weight: 0.48,
    desired_side: "buy",
    desired_quantity: 100,
    executable_quantity: 80,
    filled_quantity: 80,
    reference_price: 10,
    fill_price: 10.1,
    close_price: 11,
    fees: 1.2,
    slippage: 8,
    gross_pnl: 100,
    net_pnl: 90.8,
    decision_status: "partially_adjusted",
    client_order_id: "order-v42",
    constraint_codes: ["LOT_ROUNDED"],
  },
  {
    sequence: 1,
    row_id: "row-v42-1",
    fold_id: "wf-1",
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
  filters: {
    asset,
    start: "2024-01-02",
    end: "2024-01-03",
    fold_id: null,
    limit: 5000,
    offset: 0,
  },
  total: 2,
  items: decisionRows,
};

function renderPage(initial = `/strategy/${seriesId}?portfolio=${validationId}&asset=${encodeURIComponent(asset)}`) {
  return render(
    <MemoryRouter initialEntries={[initial]}>
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

describe("StrategyDecisionExplorerPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v4/strategy-series") return json(catalog);
      if (url.endsWith(`/api/v4/strategy-series/${seriesId}`)) return json(detail);
      if (url.endsWith(`/api/v4/strategy-series/${seriesId}/dimensions`)) return json(dimensions);
      if (url.includes(`/api/v4/strategy-series/${seriesId}/decisions?`)) return json(decisions);
      throw new Error(`unexpected request: ${url}`);
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders authoritative V4-0 decision rows without fabricating OHLC or factor contributions", async () => {
    renderPage();

    expect(await screen.findByText("Signal → target → order → fill → realized PnL")).toBeInTheDocument();
    expect(screen.getByText(/No verified MarketBarSeries is bound/i)).toBeInTheDocument();
    expect(screen.getByText("Authoritative close-price & execution timeline")).toBeInTheDocument();
    expect(screen.getByText("Target vs realized weight")).toBeInTheDocument();
    expect(screen.getByText("Frozen alpha context")).toBeInTheDocument();
    expect(screen.getByText("Gross-to-net PnL & execution costs")).toBeInTheDocument();
    expect(screen.getByText(/Per-asset component contributions are not persisted/i)).toBeInTheDocument();
    expect(screen.getByText("100 / 80 / 80")).toBeInTheDocument();
    expect(screen.getByText("LOT_ROUNDED")).toBeInTheDocument();
    expect(screen.getAllByTestId("echarts")).toHaveLength(4);

    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls.map(([value]) => String(value));
      const decisionCall = calls.find((value) => value.includes("/decisions?"));
      expect(decisionCall).toContain(`asset=${encodeURIComponent(asset)}`);
      expect(decisionCall).toContain("limit=5000");
      expect(calls.some((value) => value.includes("/market-bars?"))).toBe(false);
    });
  });

  it("binds the selected date range into WorkbenchContext and the bounded query", async () => {
    renderPage();
    await screen.findByText("Selected session inspector");

    const startInput = screen.getByLabelText("Start");
    fireEvent.change(startInput, { target: { value: "2024-01-03" } });

    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls.map(([value]) => String(value));
      expect(calls.some((value) => value.includes("start=2024-01-03"))).toBe(true);
    });
  });
});

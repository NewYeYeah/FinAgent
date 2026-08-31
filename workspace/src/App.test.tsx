import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="echarts" />,
}));

vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="react-flow">{children}</div>
  ),
  Background: () => null,
  Controls: () => null,
  MarkerType: { ArrowClosed: "arrowclosed" },
}));

import App from "./App";

const projects = {
  schema_version: "finagent.workspace.projects.v2",
  read_only: true,
  warnings: [],
  items: [
    {
      project_id: "program-a26",
      program_id: "program-a26",
      program_evidence_id: "program-result-v1",
      program_spec_id: "program-spec-v1",
      selection_id: "selection-v1",
      data_version: "data-v1",
      git_sha: "abc123",
      system_status: "PASS",
      research_status: "ROBUST_FACTOR_FAMILY_FROZEN",
      protocol_frozen: true,
      a3_status: "BOUND_IN_A4_PROTOCOL",
      a3_authority: "derived",
      a4_validation_id: "a4-validation-v1",
      a4_spec_id: "a4-spec-v1",
      a4_status: "EXECUTION_VALIDATION_PASSED_INTERNAL",
      a4_execution_validation_passed: true,
      reserve: { reserve_id: "reserve-v1", status: "untouched" },
      promotion_eligible: false,
      a5_status: "LOCKED_NOT_CONSUMED",
      lifecycle: [
        { stage: "A2.6", label: "Research frozen", status: "complete", authority: "authoritative" },
        { stage: "A3", label: "Execution protocol bound", status: "complete", authority: "derived" },
        { stage: "A4", label: "Internal validation", status: "complete", authority: "authoritative" },
        { stage: "A5", label: "One-shot reserve", status: "locked", authority: "authoritative" },
      ],
    },
  ],
};

const portfolioItem = {
  portfolio_validation_id: "a4-validation-v1",
  strategy_series_id: "strategy-series-v44",
  source_program_result_id: "program-result-v1",
  source_selection_id: "selection-v1",
  row_count: 1,
  asset_count: 1,
  fold_count: 1,
  session_count: 1,
  start_date: "2024-01-02",
  end_date: "2024-01-02",
  status: "EXECUTION_VALIDATION_PASSED_INTERNAL",
  authority: "authoritative_identity_binding",
  detail_url: "/api/v4/portfolio-execution/a4-validation-v1",
};

const portfolioCatalog = {
  schema_version: "finagent.portfolio-execution.catalog.v1",
  read_only: true,
  items: [portfolioItem],
  warnings: [],
};

const portfolioDetail = {
  schema_version: "finagent.portfolio-execution.detail.v1",
  read_only: true,
  item: portfolioItem,
  portfolio_metrics: {
    gross_return: 0.12,
    net_return: 0.1,
    gross_annualized_return: 0.15,
    net_annualized_return: 0.12,
    gross_sharpe: 1.1,
    net_sharpe: 0.9,
    max_drawdown: -0.08,
    gross_to_net_drag: 0.02,
    one_way_turnover: 0.3,
    implementation_shortfall: 0.01,
    cash_fallback_ratio: 0,
    rejected_order_ratio: 0.05,
    maximum_ex_post_participation: 0.02,
    authority: "authoritative",
  },
  economic_evidence: { hac_pvalue: 0.04 },
  folds: [{ fold_id: "wf-2024" }],
  ledger: { available: true, row_count: 1, authority: "authoritative" },
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

const portfolioSeries = {
  schema_version: "finagent.portfolio-execution.series.v1",
  read_only: true,
  authority: "authoritative_a4_points",
  portfolio_validation_id: "a4-validation-v1",
  total: 1,
  offset: 0,
  limit: 5000,
  items: [
    {
      session_date: "2024-01-02",
      fold_id: "wf-2024",
      net_nav: 101,
      gross_nav: 102,
      net_return: 0.01,
      gross_return: 0.02,
      authority: "authoritative_a4_point",
    },
  ],
};

const portfolioAnalytics = {
  schema_version: "finagent.portfolio-execution.analytics.v1",
  read_only: true,
  portfolio_validation_id: "a4-validation-v1",
  filters: { asset: null, order_id: null, fold_id: null, start: null, end: null, window: 20 },
  drawdown: {
    authority: "derived_presentation",
    source_authority: "authoritative_a4_points",
    formula: "nav / running_peak_nav - 1",
    items: [{ session_date: "2024-01-02", fold_id: "wf-2024", net_drawdown: 0, gross_drawdown: 0 }],
  },
  rolling: {
    authority: "derived_presentation",
    source_authority: "authoritative_a4_net_returns",
    annualization: 252,
    window: 20,
    items: [{ session_date: "2024-01-02", fold_id: "wf-2024", window_periods: 1, rolling_return: 0.01, rolling_volatility: 0, rolling_sharpe: 0 }],
  },
  monthly_returns: {
    authority: "derived_presentation",
    source_authority: "authoritative_a4_period_returns",
    formula: "product(1 + period_return) - 1 by calendar month",
    items: [{ month: "2024-01", year: 2024, month_number: 1, net_return: 0.01, gross_return: 0.02, periods: 1 }],
  },
  filtered_costs: {
    authority: "derived_presentation",
    source_authority: "authoritative_v4_0_cost_rows",
    fees: 1,
    slippage: 2,
    total_cost: 3,
    decision_row_count: 1,
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

const reserve = {
  schema_version: "finagent.workspace.reserve-lifecycle.v1",
  read_only: true,
  authority: "authoritative",
  reserve_id: "reserve-v1",
  state: "CONSUMED",
  a5_status: "RESERVE_PASS",
  promotion_eligible: false,
  automatic_retry_allowed: false,
  program_result_id: "program-result-v1",
  portfolio_validation_id: "a4-validation-v1",
  seal: { seal_id: "seal-v1" },
  claim: { claim_id: "claim-v1", state: "CONSUMED" },
  terminal: { status: "RESERVE_PASS", reason_codes: ["RESERVE_PASS_TERMINAL"], aggregate: { net_metrics: { total_return: 0.12, sharpe: 1.1 }, gross_metrics: { total_return: 0.14, sharpe: 1.2 } } },
  audit: { audit_id: "audit-v1" },
  ledger: { available: true, row_count: 2, semantic_digest: "ledger-digest", file_sha256: "a".repeat(64), authority: "authoritative" },
  integrity: { status: "PASS", checks: [{ name: "claim.seal_id", passed: true, detail: "bound" }], failed_count: 0, fully_audited: true },
  lineage: {
    nodes: [
      { evidence_id: "seal-v1", evidence_type: "ReserveEligibilitySeal", stage: "A5-1", authority: "authoritative", status: "complete", label: "Eligibility seal" },
      { evidence_id: "claim-v1", evidence_type: "ReserveConsumptionClaim", stage: "A5-3", authority: "authoritative", status: "CONSUMED", label: "Durable CONSUMED claim" },
    ],
    edges: [{ parent_id: "seal-v1", child_id: "claim-v1", relation: "authorizes_pre_access_consumption" }],
  },
};

const reserveLedger = {
  schema_version: "finagent.workspace.reserve-ledger.v1",
  read_only: true,
  authority: "authoritative",
  reserve_id: "reserve-v1",
  terminal_evidence_id: "terminal-v1",
  row_count: 2,
  semantic_digest: "ledger-digest",
  file_sha256: "a".repeat(64),
  rows: [{ session: "2025-01-02", net_nav: 1.0 }, { session: "2025-01-03", net_nav: 1.01 }],
};

function response(payload: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("FinAgent Workspace V2", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/");
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/v2/projects")) return response(projects);
        if (url === "/api/v4/portfolio-execution") return response(portfolioCatalog);
        if (url === "/api/v4/portfolio-execution/a4-validation-v1") return response(portfolioDetail);
        if (url.includes("/api/v4/portfolio-execution/a4-validation-v1/series?")) return response(portfolioSeries);
        if (url.includes("/api/v4/portfolio-execution/a4-validation-v1/analytics?")) return response(portfolioAnalytics);
        if (url.endsWith("/api/v2/reserves/reserve-v1/ledger")) return response(reserveLedger);
        if (url.endsWith("/api/v2/reserves/reserve-v1")) return response(reserve);
        throw new Error(`unexpected URL: ${url}`);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the governed lifecycle and opens the canonical V4-4 portfolio cockpit", async () => {
    render(<App />);
    expect(screen.getByText(/Evidence Plane is GET-only/i)).toBeInTheDocument();
    expect(await screen.findByText("Research governance cockpit")).toBeInTheDocument();
    expect(screen.getByText("One-shot reserve")).toBeInTheDocument();
    expect(screen.getByText("LOCKED_NOT_CONSUMED")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "A4" }));

    // V4-4 first resolves the detail route without an explicit range, then writes
    // the authoritative A4 start/end dates into URL-backed WorkbenchContext. The
    // series/analytics keys change and refetch once. Wait for that canonical context
    // transition before treating the analytical surface as stable.
    await waitFor(() => {
      expect(screen.getByTestId("workbench-context-bar")).toHaveTextContent(
        "2024-01-02..2024-01-02",
      );
    });

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "NAV & drawdown" })).toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "Monthly return matrix" })).toBeInTheDocument();
      expect(screen.getByText(/A4 portfolio authority/i)).toBeInTheDocument();
      expect(screen.getByText("benchmark unavailable")).toBeInTheDocument();
      expect(
        screen.getByText(
          /No NAV, return, drawdown, rolling statistic, monthly return or cost aggregate is reconstructed in React/i,
        ),
      ).toBeInTheDocument();
    });
  });

  it("opens the A5-4 reserve cockpit without mutation controls", async () => {
    render(<App />);
    await screen.findByText("Research governance cockpit");
    const reserveLinks = screen.getAllByRole("link", { name: "Reserve" });
    await userEvent.click(reserveLinks[reserveLinks.length - 1]);
    await waitFor(() => expect(screen.getByText("A5 One-shot Reserve")).toBeInTheDocument());
    expect(screen.getAllByText("RESERVE_PASS").length).toBeGreaterThan(0);
    expect(screen.getByText("Lifecycle integrity")).toBeInTheDocument();
    expect(screen.getByText(/retry:false/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry|promote|execute|order/i })).not.toBeInTheDocument();
  });
});

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

const portfolio = {
  schema_version: "finagent.workspace.a4-cockpit.v2",
  read_only: true,
  validation_id: "a4-validation-v1",
  status: "EXECUTION_VALIDATION_PASSED_INTERNAL",
  system_status: "PASS",
  reserve: { reserve_id: "reserve-v1", status: "untouched" },
  promotion_eligible: false,
  metrics: {
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
  },
  nav_series: [
    {
      session_date: "2024-01-02",
      net_nav: 101,
      gross_nav: 102,
      net_return: 0.01,
      gross_return: 0.02,
      fold_id: "wf-2024",
    },
  ],
  derived_rolling: {
    authority: "derived",
    window: 20,
    annualization: 252,
    items: [
      {
        session_date: "2024-01-02",
        window_periods: 1,
        rolling_return: 0.01,
        rolling_volatility: 0,
        rolling_sharpe: 0,
      },
    ],
  },
  folds: [],
  economic_evidence: { hac_pvalue: 0.04 },
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
        if (url.endsWith("/api/v2/a4/a4-validation-v1/cockpit")) return response(portfolio);
        throw new Error(`unexpected URL: ${url}`);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the governed lifecycle and opens the A4 cockpit", async () => {
    render(<App />);
    expect(screen.getByText(/Read-only evidence workspace/i)).toBeInTheDocument();
    expect(await screen.findByText("Research governance cockpit")).toBeInTheDocument();
    expect(screen.getByText("One-shot reserve")).toBeInTheDocument();
    expect(screen.getByText("LOCKED_NOT_CONSUMED")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "A4" }));
    await waitFor(() => expect(screen.getByText("A4 Portfolio Validation")).toBeInTheDocument());
    expect(screen.getByText("Gross / net NAV")).toBeInTheDocument();
    expect(screen.getAllByText("DERIVED PRESENTATION SERIES").length).toBeGreaterThan(0);
    expect(screen.getByText(/reserve:untouched/i)).toBeInTheDocument();
  });
});

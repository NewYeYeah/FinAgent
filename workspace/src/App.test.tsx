import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const catalog = {
  schema_version: "finagent.workspace.catalog.v1",
  read_only: true,
  warnings: [],
  items: [
    {
      evidence_id: "a4-validation-v1",
      evidence_type: "ashare_portfolio_validation",
      stage: "a4_portfolio_validation",
      authority: "authoritative",
      system_status: "PASS",
      research_status: "EXECUTION_VALIDATION_PASSED_INTERNAL",
      reserve_status: "untouched",
      promotion_eligible: false,
      program_id: "",
      spec_id: "a4-spec-v1",
      data_version: "data-v1",
      source_uri: "reports/a4.json",
      factor_count: 0,
      has_portfolio: true,
      has_execution: true,
      detail_url: "/api/v1/evidence/a4-validation-v1",
    },
  ],
};

const evidence = {
  schema_version: "finagent.visualization.evidence-bundle.v1",
  root: {
    evidence_id: "a4-validation-v1",
    evidence_type: "ashare_portfolio_validation",
    schema_version: "finagent.ashare-portfolio-validation.v1",
    stage: "a4_portfolio_validation",
    authority: "authoritative",
    artifact_digest: "digest",
    source_uri: "reports/a4.json",
    parent_ids: ["ledger-v1"],
    program_id: "",
    spec_id: "a4-spec-v1",
    data_version: "data-v1",
    git_sha: "",
    metadata: { label: "A4 portfolio validation" },
  },
  refs: [],
  system_status: "PASS",
  research_status: "EXECUTION_VALIDATION_PASSED_INTERNAL",
  reserve_status: "untouched",
  promotion_eligible: false,
  factors: [],
  portfolio: {
    metrics: {
      net_total_return: 0.1,
      gross_total_return: 0.12,
      net_sharpe: 0.9,
      net_max_drawdown: -0.08,
      gross_to_net_return_drag: 0.02,
    },
    points: [
      {
        session_date: "2024-01-02",
        net_nav: 101,
        gross_nav: 102,
        net_return: 0.01,
        gross_return: 0.02,
        fees: 1,
        slippage: 1,
        one_way_turnover: 0.1,
        implementation_shortfall: 0.01,
        maximum_ex_post_participation: 0.02,
        desired_order_count: 3,
        order_count: 2,
        fill_count: 2,
        rejected_order_count: 1,
        cash_fallback: false,
      },
    ],
    fold_metrics: [],
  },
  execution: {
    desired_order_count: 3,
    order_count: 2,
    fill_count: 2,
    rejected_order_count: 1,
    rejected_order_ratio: 0.333,
    cash_fallback_count: 0,
    cash_fallback_ratio: 0,
    reason_counts: { T1_SELLABLE_QUANTITY_CLIPPED: 1 },
    costs: { fees: 1, slippage: 1, gross_to_net_return_drag: 0.02 },
    maximum_ex_post_participation: 0.02,
  },
  lineage: {
    nodes: [
      {
        evidence_id: "a4-validation-v1",
        evidence_type: "ashare_portfolio_validation",
        stage: "a4_portfolio_validation",
        authority: "authoritative",
        status: "PASS",
        label: "A4 portfolio validation",
      },
    ],
    edges: [],
  },
  metadata: {},
};

function response(payload: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("FinAgent Workspace", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/");
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith("/api/v1/catalog")) return response(catalog);
        if (url.endsWith("/api/v1/evidence/a4-validation-v1")) return response(evidence);
        if (url.endsWith("/api/v1/widgets")) return response({ items: [] });
        throw new Error(`unexpected URL: ${url}`);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows immutable evidence and opens the A4 cockpit", async () => {
    render(<App />);
    expect(screen.getByText(/Read-only evidence workspace/i)).toBeInTheDocument();
    expect(await screen.findByText("ashare_portfolio_validation")).toBeInTheDocument();
    await userEvent.click(screen.getByText("ashare_portfolio_validation"));
    await waitFor(() => {
      expect(screen.getByText("Gross / net NAV")).toBeInTheDocument();
    });
    expect(screen.getByText("Order realization")).toBeInTheDocument();
    expect(screen.getByText("DERIVED PRESENTATION SERIES")).toBeInTheDocument();
    expect(screen.getByText(/reserve:untouched/i)).toBeInTheDocument();
  });
});

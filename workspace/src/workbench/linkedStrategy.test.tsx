import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("echarts-for-react", () => ({ default: () => <div data-testid="echarts" /> }));

import App from "../App";

function response(payload: unknown) {
  return Promise.resolve(new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }));
}

const noCandidate = {
  schema_version: "linked",
  cycle: {
    cycle_id: "cycle-no",
    accepted: true,
    review_disposition: "R4_RESULT_ACCEPTED",
    terminal: "NO_ADAPTIVE_CANDIDATE",
    agent_value: "INCONCLUSIVE",
    candidate_id: null,
    economic_evidence: { deterministic_strategy_count: 20, complete_deterministic_strategy_count: 0, deterministic_evidence_complete: false, interpretation: "coverage/completeness-driven" },
    agent_reliability: { rejected_action_attempts: 62 },
    authority: { r5_eligible: false },
  },
  mode: "no_candidate",
  explanation: { basis: "coverage/completeness-driven", claims_not_supported: ["all_strategies_lost_money", "market_state_failed", "agent_proved_ineffective"] },
  candidate: null,
  strategy_binding: { status: "unavailable", reason: "accepted_cycle_has_no_adaptive_candidate" },
  combined_strategy_evidence: { available: false, reason: "no_persisted_candidate_strategy_binding" },
  target_portfolio: { available: false, reason: "no_persisted_candidate_strategy_binding" },
  execution_pnl: { available: false, reason: "no_persisted_candidate_strategy_binding" },
  attribution: { available: false, reason: "unavailable_not_persisted" },
  available_evidence: {
    market_state_model_ids: ["market-model-a"],
    factors: [{ factor_id: "factor-a", status: "ACTIVE" }],
    canonical_experiment_ids: ["exp-a"],
    historical_strategy_series: [{ strategy_series_id: "historical-a", relation_to_cycle: "unbound_historical_evidence" }],
  },
  r5: { status: "not_started_not_eligible", eligible: false },
  links: { research_graph: "/research-graph?cycle=cycle-no" },
  unresolved: [],
  read_only: true,
  canonical_identity_only: true,
  browser_recomputation: false,
  hidden_reasoning: "not_persisted_not_projected",
};

const candidate = {
  ...noCandidate,
  cycle: { ...noCandidate.cycle, cycle_id: "cycle-candidate", terminal: "DEVELOPMENT_CANDIDATE_PROPOSED", candidate_id: "candidate-a", authority: { r5_eligible: true } },
  mode: "candidate",
  explanation: { reason: "accepted_development_candidate_persisted", binding_semantics: "explicit_canonical_references_only" },
  candidate: { candidate_id: "candidate-a", market_state_model_id: "market-model-a", factor_ids: ["factor-a"], experiment_ids: ["exp-a"], agent_run_id: "run-r4", evidence_ids: ["evidence-a"] },
  strategy_binding: { status: "resolved", binding: { binding_id: "binding-a", strategy_series_id: "strategy-series-a", portfolio_validation_id: "portfolio-a" } },
  combined_strategy_evidence: { available: true, strategy_series_id: "strategy-series-a" },
  target_portfolio: { available: true, portfolio_validation_id: "portfolio-a" },
  execution_pnl: { available: true, portfolio_validation_id: "portfolio-a" },
  attribution: { available: false, evidence_id: null, reason: "unavailable_not_persisted" },
  r5: { status: "not_started_eligible", eligible: true },
  links: {
    market: "/market?market_model=market-model-a&cycle=cycle-candidate&strategy=candidate-a",
    factors: ["/factors?factor=factor-a&cycle=cycle-candidate&strategy=candidate-a"],
    experiments: ["/experiments?experiment=exp-a&cycle=cycle-candidate&strategy=candidate-a"],
    strategy: "/strategy/strategy-series-a?strategy=candidate-a&cycle=cycle-candidate&portfolio=portfolio-a",
    portfolio: "/portfolio/portfolio-a?portfolio=portfolio-a&strategy=candidate-a&cycle=cycle-candidate",
    execution: "/execution/portfolio-a?portfolio=portfolio-a&strategy=candidate-a&cycle=cycle-candidate",
    research_graph: "/research-graph?cycle=cycle-candidate&strategy=candidate-a",
    agent: "/agent?run=run-r4&strategy=candidate-a",
    evidence: ["/evidence/evidence-a"],
  },
};

let detail: typeof noCandidate | typeof candidate = noCandidate;

class EventSourceStub { close() {}; addEventListener() {}; removeEventListener() {}; onerror = null; onopen = null; constructor(_url: string) {} }

describe("Workbench-2 linked strategy analytics", () => {
  beforeEach(() => {
    detail = noCandidate;
    vi.stubGlobal("EventSource", EventSourceStub);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("127.0.0.1:8766/api/v3/control/")) return Promise.reject(new TypeError("control unavailable"));
      if (url === "/api/v4/strategy-series") return response({ schema_version: "strategy", read_only: true, items: [], warnings: [] });
      if (url === "/api/v3/linked-strategy") return response({ schema_version: "index", items: [{ cycle_id: detail.cycle.cycle_id, mode: detail.mode, strategy_binding_status: detail.strategy_binding.status, r5_eligible: detail.r5.eligible }], default_cycle_id: detail.cycle.cycle_id, historical_strategy_series_count: 1, historical_strategy_relation: "unbound_unless_explicit_candidate_binding", read_only: true, canonical_identity_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected" });
      if (url === `/api/v3/linked-strategy/cycles/${detail.cycle.cycle_id}`) return response(detail);
      throw new Error(`unexpected URL: ${url}`);
    }));
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("treats the accepted NO_ADAPTIVE_CANDIDATE path as first-class evidence", async () => {
    window.history.pushState({}, "", "/strategy?cycle=cycle-no");
    render(<App />);
    await screen.findByText("NO_ADAPTIVE_CANDIDATE");
    const panel = screen.getByRole("region", { name: "Linked strategy analytics" });
    expect(panel).toHaveTextContent("NO_ADAPTIVE_CANDIDATE");
    expect(panel).toHaveTextContent("AgentValue INCONCLUSIVE");
    expect(panel).toHaveTextContent("0/20 complete deterministic strategies");
    expect(panel).toHaveTextContent("62 rejected Agent actions");
    expect(panel).toHaveTextContent("not_started_not_eligible");
    expect(panel).toHaveTextContent("not bound to this R4 terminal");
    expect(panel).toHaveTextContent("does not mean all strategies lost money");
    expect(screen.getByTestId("workbench-context-bar")).toHaveTextContent("cycle-no");
    expect(panel).toHaveTextContent("Browser financial/statistical recomputation = false");
  });

  it("restores an explicit persisted candidate and canonical downstream links", async () => {
    detail = candidate;
    window.history.pushState({}, "", "/strategy?cycle=cycle-candidate&strategy=candidate-a");
    render(<App />);
    await screen.findByText("candidate-a");
    const panel = screen.getByRole("region", { name: "Linked strategy analytics" });
    expect(panel).toHaveTextContent("candidate-a");
    expect(panel).toHaveTextContent("resolved");
    expect(panel).toHaveTextContent("Strategy evidence persisted");
    expect(panel).toHaveTextContent("Portfolio / execution persisted");
    expect(panel).toHaveTextContent("Attribution: unavailable");
    expect(screen.getByRole("link", { name: /Portfolio/ })).toHaveAttribute("href", expect.stringContaining("/portfolio/portfolio-a"));
    expect(screen.getByRole("link", { name: /Execution \/ PnL/ })).toHaveAttribute("href", expect.stringContaining("/execution/portfolio-a"));
    await waitFor(() => expect(screen.getByTestId("workbench-context-bar")).toHaveTextContent("candidate-a"));
    expect(screen.getByTestId("workbench-context-bar")).toHaveTextContent("cycle-candidate");
  });
});

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("echarts-for-react", () => ({ default: () => <div data-testid="echarts" /> }));

import App from "../App";

function response(payload: unknown) {
  return Promise.resolve(new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }));
}

const marketItem = {
  model_id: "market-model-a", model_artifact_id: "model-artifact-a", result_artifact_id: "result-artifact-a",
  model: { version: "finagent.market-state-gmm.v1", estimator: "sklearn.mixture.GaussianMixture", available_at: "2026-01-03T00:00:00+00:00", fit_window: { start: "2026-01-01", end: "2026-01-03" }, implementation_id: "impl-a" },
  historical_states: [
    { event_time: "2026-01-03T10:00:00+00:00", available_at: "2026-01-03T10:15:00+00:00", state: 0, probabilities: [0.8, 0.2], unavailable_reason: null },
    { event_time: "2026-01-03T10:15:00+00:00", available_at: "2026-01-03T10:30:00+00:00", state: 1, probabilities: [0.2, 0.8], unavailable_reason: null },
    { event_time: "2026-01-03T10:30:00+00:00", available_at: "2026-01-03T10:45:00+00:00", state: null, probabilities: null, unavailable_reason: "OBSERVATION_NOT_AVAILABLE" },
  ], current_snapshot: { event_time: "2026-01-03T10:30:00+00:00", available_at: "2026-01-03T10:45:00+00:00", state: null, probabilities: null, unavailable_reason: "OBSERVATION_NOT_AVAILABLE" },
  transitions: [{ from_state: 0, to_state: 1, event_time: "2026-01-03T10:15:00+00:00", available_at: "2026-01-03T10:30:00+00:00", semantics: "adjacent_persisted_available_snapshots_no_smoothing" }],
  unavailable_snapshot_count: 1, available_snapshot_count: 2, run_id: "slice-a", evaluation_data_status: "EVALUABLE", interpretation: "development diagnostics",
  feature_definitions: ["proxy_close[t]/proxy_close[t-lookback_returns]-1", "sqrt(mean(square(adjacent_proxy_simple_returns)))"], feature_identities: null, feature_identity_status: "unavailable_not_persisted",
  causal: { inference: "P(S_t|X_<=t); frozen_train_parameters; no_sequence_smoothing", browser_refit: false, future_fill: false, smoothing: false },
  factor_state_evidence: [{ factor_id: "factor-a", status: "ACTIVE", evaluations: [{ evaluation_id: "eval-a", by_market_state: { state_0: { coverage: 0.9 } }, conditioning: "soft_probability_weighted_IC_coverage_decay_similarity" }], allocator_weight_observations: [{ as_of: "2026-01-04T10:15:00+00:00", allocator: "regime_conditional", weight: 0.7 }] }], linked_experiment_ids: ["exp-a"], unavailable: { feature_identities: "not_persisted" },
};
const markets = { schema_version: "market", items: [marketItem], warnings: [], read_only: true, browser_recomputation: false, causal_projection: true, hidden_reasoning: "not_persisted_not_projected" };
const cycles = { schema_version: "cycles", items: [{ cycle_id: "cycle-a", accepted: true, review_status: "accepted", review_disposition: "R4_RESULT_ACCEPTED", terminal: "NO_ADAPTIVE_CANDIDATE", agent_value: "INCONCLUSIVE", economic_evidence: { deterministic_strategy_count: 20, complete_deterministic_strategy_count: 0 }, agent_reliability: { rejected_action_attempts: 62 }, provider_usage: {}, resource_summary: {}, authority: {}, evidence: {} }], read_only: true, browser_recomputation: false };
const factorSummary = { factor_id: "factor-a", status: "ACTIVE", status_reason: "latest_persisted_lifecycle_event", family: "flow", mechanism: "causal mechanism", hypothesis: "state-aware hypothesis", origin: "agent", provenance: { source: "fixture" }, created_at: "2026-01-01", definition_conflict: false, library_ids: ["library-a"], lifecycle: [{ status: "PROPOSED" }, { status: "ACTIVE" }], evaluation_count: 1, latest_model_id: "market-model-a", evaluation_selection_reason: "latest_by_persisted_available_at" };
const factorDormant = { ...factorSummary, factor_id: "factor-b", status: "DORMANT", origin: "programmatic" };
const factorRejected = { ...factorSummary, factor_id: "factor-c", status: "REJECTED", origin: "manual", evaluation_count: 0, latest_model_id: null };
const factorDetail = { ...factorSummary, evaluations: [{ evaluation_id: "eval-a" }], latest_evaluation: { evaluation_id: "eval-a" }, global_metrics: { coverage: 0.8, turnover: 0.2, decay_rank_ic: { "15": 0.03 } }, state_metrics: { state_0: { coverage: 0.9, turnover: 0.1 } }, cost_sensitive_economics: { "5.0": { compounded_return: 0.01 } }, similarity: { "factor-c": 0.1 }, novelty: null, novelty_status: "unavailable_not_persisted", allocator_weights: [{ as_of: "2026-01-04T10:15:00+00:00", allocator: "regime_conditional", weight: 0.7, state_link_status: "persisted" }], allocator_weight_status: "persisted", linked_market_state_model_ids: ["market-model-a"], linked_experiments: [{ identity: "exp-a", experiment_id: "exp-a", run_id: "run-a" }], agent_decision_history: [{ node_id: "decision-a", run_id: "run-a", status: "recorded" }], evidence_identities: ["eval-a"], unavailable: { novelty: "not_persisted" } };

class EventSourceStub { close() {}; addEventListener() {}; removeEventListener() {}; onerror = null; onopen = null; constructor(_url: string) {} }

describe("Workbench-2 Market State + Factor Intelligence", () => {
  beforeEach(() => {
    vi.stubGlobal("EventSource", EventSourceStub);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("127.0.0.1:8766/api/v3/control/")) return Promise.reject(new TypeError("control unavailable"));
      if (url === "/api/v3/market-state") return response(markets);
      if (url === "/api/v3/market-state/market-model-a") return response({ ...markets, item: marketItem });
      if (url === "/api/v3/research-cycles") return response(cycles);
      if (url === "/api/v3/factor-intelligence") return response({ schema_version: "factors", items: [factorSummary, factorDormant, factorRejected], warnings: [], read_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected" });
      if (url === "/api/v3/factor-intelligence/factor-a") return response({ schema_version: "factor", item: factorDetail, warnings: [], read_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected" });
      if (url === "/api/v4/factor-series") return response({ schema_version: "catalog", items: [], read_only: true });
      throw new Error(`unexpected URL: ${url}`);
    }));
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("renders persisted MarketState probabilities/transitions/unavailable state without refit", async () => {
    window.history.pushState({}, "", "/market?market_model=market-model-a");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Market State" })).toBeInTheDocument();
    expect(screen.getByText("NO_ADAPTIVE_CANDIDATE")).toBeInTheDocument();
    expect(screen.getByText("AgentValue INCONCLUSIVE")).toBeInTheDocument();
    expect(screen.getByText("0/20 complete deterministic strategies")).toBeInTheDocument();
    expect(screen.getByText("62 rejected actions")).toBeInTheDocument();
    expect(screen.getAllByText("OBSERVATION_NOT_AVAILABLE")).toHaveLength(2);
    expect(screen.getByText("0 → 1")).toBeInTheDocument();
    expect(screen.getByText(/browser_refit=false/)).toBeInTheDocument();
    expect(screen.getByText(/feature identities: unavailable_not_persisted/)).toBeInTheDocument();
    expect(screen.getByTestId("workbench-context-bar")).toHaveTextContent("market-model-a");
  });

  it("extends the Factor Tear Sheet with lifecycle/state metrics/provenance/weights and canonical links", async () => {
    window.history.pushState({}, "", "/factors?factor=factor-a&market_model=market-model-a");
    render(<App />);
    expect(await screen.findByRole("region", { name: "Factor Intelligence" })).toBeInTheDocument();
    expect(screen.getByText("DORMANT")).toBeInTheDocument();
    expect(screen.getByText("REJECTED")).toBeInTheDocument();
    expect(await screen.findByTestId("factor-state-metrics")).toHaveTextContent('"coverage": 0.9');
    expect(screen.getByTestId("factor-global-metrics")).toHaveTextContent('"turnover": 0.2');
    expect(screen.getByTestId("factor-provenance")).toHaveTextContent('"source": "fixture"');
    expect(screen.getByTestId("factor-weights")).toHaveTextContent("weight=0.7");
    const marketLink = screen.getByRole("link", { name: /MarketState:market-model-a/ });
    await userEvent.click(marketLink);
    await waitFor(() => expect(window.location.pathname).toBe("/market"));
    expect(window.location.search).toContain("market_model=market-model-a");
    expect(window.location.search).toContain("factor=factor-a");
  });
});

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("echarts-for-react", () => ({ default: () => <div data-testid="echarts" /> }));
vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ nodes, onNodeClick }: { nodes: Array<{ id: string; data: unknown }>; onNodeClick?: (event: unknown, node: { id: string; data: unknown }) => void }) => <div data-testid="react-flow">{nodes.map((node) => <button key={node.id} type="button" aria-label={`graph-node-${node.id}`} onClick={() => onNodeClick?.({}, node)}>{node.id}</button>)}</div>,
  Background: () => null,
  Controls: () => null,
  MarkerType: { ArrowClosed: "arrowclosed" },
}));

import App from "../App";

function response(payload: unknown) {
  return Promise.resolve(new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }));
}

const experimentA = {
  attempt_id: "call-exp-a", experiment_id: "exp-a", identity: "exp-a", identity_kind: "experiment_id", canonical_experiment_identity_available: true,
  run_id: "run-r4", project_id: "r4-research", thread_id: "thread-run-r4", objective: "Evaluate bounded evidence", hypothesis_id: "hyp-a",
  factor_set_id: "set-a", factor_ids: ["factor-a", "factor-b"], allocator_proposal_id: "alloc-a", allocator: "equal_weight", status: "completed", outcome: "PORTFOLIO_EVALUATED",
  evaluation_scope: { compatibility_id: "compat-a", evaluation_mode: "development_descriptive" }, authoritative_metrics: { mean_fold_return_5bp: 0.01, evaluable_folds: 3 }, metrics_source: "persisted_research_result",
  provider_id: "scripted-offline", model_id: "fixture-model", resource_snapshot: { evaluations: 1, remaining_evaluations: 2 }, evaluation_budget: { used: 1, remaining: 2 }, tokens: 1500, cost_microusd: 2800,
  agent_decision: { action_id: "call-final", kind: "finalize_candidate", recommendation: "reject", decision: "Reject incomplete evidence", terminal: "NO_CANDIDATE_RECOMMENDED" },
  related_identities: [], error: null, read_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected",
};
const experimentB = { ...experimentA, attempt_id: "call-exp-b", experiment_id: "exp-b", identity: "exp-b", authoritative_metrics: { mean_fold_return_5bp: 0.02, evaluable_folds: 3 } };
const failed = { ...experimentA, attempt_id: "call-failed", experiment_id: null, identity: "call-failed", identity_kind: "attempt_call_id", canonical_experiment_identity_available: false, status: "failed", authoritative_metrics: null, error: "unknown_run_local_proposal", agent_decision: null };
const rejected = { ...failed, attempt_id: "call-rejected", identity: "call-rejected", status: "rejected", error: "campaign_evaluation_budget_denied" };

const cycles = {
  schema_version: "finagent.workspace.research-cycles.v1", read_only: true, browser_recomputation: false,
  items: [{ cycle_id: "cycle-a", accepted: true, review_status: "accepted", protocol_id: "protocol-a", protocol_version: "r4-matched-v3", review_disposition: "R4_RESULT_ACCEPTED", terminal: "NO_ADAPTIVE_CANDIDATE", agent_value: "INCONCLUSIVE", candidate_id: null,
    economic_evidence: { deterministic_strategy_count: 20, complete_deterministic_strategy_count: 0, deterministic_evidence_complete: false }, provider_usage: {}, agent_reliability: { rejected_action_attempts: 62 }, resource_summary: {}, authority: { alpha_authority: false, paper_authority: false, live_authority: false }, evidence: {} }],
};

const experiments = { schema_version: "finagent.workspace.research-experiments.v1", configured: true, items: [experimentA, experimentB, failed, rejected], read_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected" };
const comparison = { schema_version: "finagent.workspace.research-experiment-comparison.v1", experiment_ids: ["exp-a", "exp-b"], comparison_call_id: "call-compare", comparable: true, reason: null,
  persisted_comparison: { outcome: "EXPERIMENTS_COMPARED", experiments: [{ experiment_id: "exp-a", metrics_5bp: { mean_fold_return_5bp: 0.01 } }, { experiment_id: "exp-b", metrics_5bp: { mean_fold_return_5bp: 0.02 } }] }, items: [experimentA, experimentB], ranking: null, read_only: true, browser_recomputation: false };

const graph = {
  schema_version: "finagent.workspace.research-graph.v1", read_only: true, canonical_identity_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected",
  nodes: [
    { node_id: "hypothesis:hyp-a", kind: "hypothesis", identity: "hyp-a", label: "hyp-a", status: "persisted", href: null, context: { run_id: "run-r4", project_id: "r4-research", thread_id: "thread-run-r4" }, details: {} },
    { node_id: "experiment:exp-a", kind: "experiment", identity: "exp-a", label: "exp-a", status: "completed", href: "/experiments?experiment=exp-a", context: { run_id: "run-r4", project_id: "r4-research", thread_id: "thread-run-r4", experiment_id: "exp-a" }, details: {} },
    { node_id: "terminal:cycle-a", kind: "terminal", identity: "cycle-a", label: "NO_ADAPTIVE_CANDIDATE", status: "accepted_terminal", href: null, context: {}, details: { agent_value: "INCONCLUSIVE", candidate_id: null } },
  ],
  edges: [{ edge_id: "hyp-exp", source: "hypothesis:hyp-a", target: "experiment:exp-a", relation: "persisted_relation" }],
  unresolved: [{ cycle_id: "cycle-a", relation: "campaign_run_experiment_lineage", reason: "accepted_attestation_does_not_embed_run_local_experiment_identities" }],
};

class EventSourceStub {
  close() {}
  addEventListener() {}
  removeEventListener() {}
  onerror: ((event: Event) => void) | null = null;
  onopen: ((event: Event) => void) | null = null;
  constructor(_url: string) {}
}

describe("Workbench-2 Experiments + Research Graph", () => {
  beforeEach(() => {
    vi.stubGlobal("EventSource", EventSourceStub);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("127.0.0.1:8766/api/v3/control/")) return Promise.reject(new TypeError("control unavailable"));
      if (url === "/api/v3/research-experiments?run_id=run-r4") return response(experiments);
      if (url === "/api/v3/research-cycles") return response(cycles);
      if (url === "/api/v3/research-experiments/exp-a") return response({ schema_version: "detail", item: experimentA, read_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected" });
      if (url.startsWith("/api/v3/research-experiments/compare?")) return response(comparison);
      if (url === "/api/v3/research-graph?run_id=run-r4") return response(graph);
      throw new Error(`unexpected URL: ${url}`);
    }));
  });

  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("renders experiment detail, failed/rejected states and persisted two-experiment comparison without recomputation", async () => {
    window.history.pushState({}, "", "/experiments?run=run-r4&experiment=exp-a&compare=exp-a%2Cexp-b");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Experiments" })).toBeInTheDocument();
    expect(screen.getByText("NO_ADAPTIVE_CANDIDATE")).toBeInTheDocument();
    expect(screen.getByText("AgentValue INCONCLUSIVE")).toBeInTheDocument();
    expect(screen.getByText("0/20 complete deterministic strategies")).toBeInTheDocument();
    expect(screen.getByText("62 rejected actions")).toBeInTheDocument();
    expect(await screen.findByTestId("authoritative-metrics")).toHaveTextContent('"mean_fold_return_5bp": 0.01');
    expect(screen.getByText("unknown_run_local_proposal")).toBeInTheDocument();
    expect(screen.getByText("campaign_evaluation_budget_denied")).toBeInTheDocument();
    const compared = await screen.findByTestId("experiment-comparison");
    expect(compared).toHaveTextContent('"mean_fold_return_5bp": 0.02');
    expect(compared).toHaveTextContent("ranking = null");
    expect(screen.getByText(/Hidden chain-of-thought is not persisted or projected/i)).toBeInTheDocument();
  });

  it("renders canonical graph/unresolved lineage and restores node selection through WorkbenchContext", async () => {
    window.history.pushState({}, "", "/research-graph?run=run-r4&graph_node=terminal%3Acycle-a&cycle=cycle-a");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Research Graph" })).toBeInTheDocument();
    expect(screen.getByTestId("react-flow")).toBeInTheDocument();
    expect(screen.getByText("accepted_attestation_does_not_embed_run_local_experiment_identities")).toBeInTheDocument();
    expect(screen.getByTestId("workbench-context-bar")).toHaveTextContent("terminal:cycle-a");
    await userEvent.click(screen.getByRole("button", { name: "graph-node-experiment:exp-a" }));
    await waitFor(() => expect(window.location.pathname).toBe("/experiments"));
    expect(window.location.search).toContain("experiment=exp-a");
    expect(window.location.search).toContain("run=run-r4");
  });
});

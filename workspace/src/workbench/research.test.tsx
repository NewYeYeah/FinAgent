import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { controlApi } from "../api";
import { ResearchContext, ResearchObjective, ResearchToolCard } from "./research";
import type { ResearchMetrics, ResearchState } from "./researchTypes";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const metrics: ResearchMetrics = { mean_fold_return_5bp: .01, worst_fold_return_5bp: -.02,
  drawdown_5bp: .03, turnover_5bp: 12, fallback_rate: .25, factor_concentration: .5,
  evaluable_folds: 3, difference_to_equal_weight_5bp: 0,
  cost_sensitivity: { "0.0": { mean_fold_return: .02, worst_fold_return: -.01 }, "5.0": { mean_fold_return: .01, worst_fold_return: -.02 } } };
const state: ResearchState = { objective: "Evaluate controlled development hypotheses", factor_set: { factor_set_id: "set-a", factor_ids: ["factor-a", "factor-b"], hypothesis_id: "diversify" },
  allocator: { allocator: "regime_conditional", allocator_proposal_id: "alloc-a", lookback_sessions: 20, minimum_observations: 5, ridge_alpha: 1 },
  market_state: { model_id: "model-a", snapshot: { available_at: "2020-01-01T19:00:00Z", probabilities: [.25, .75], unavailable_reason: null }, availability: "historical" },
  resources: { status: "ACTIVE", attempts: 8, evaluations: 1, tokens: 800, cost_microusd: 80, remaining_tool_calls: 22, remaining_evaluations: 3, remaining_tokens: 1000, remaining_cost_microusd: 10000 },
  latest_experiment: { experiment_id: "experiment-a", preferred_allocator: "regime_conditional", metrics, evaluation_mode: "adaptive_development_retrospective" },
  explicit_decision: { critique: "Fixture establishes no independent evidence", next_action: "Stop the hypothesis" },
  candidate: { outcome: "NO_CANDIDATE_RECOMMENDED", decision: "No candidate: fixture only" }, history_cutoff: "step-7", development_only: true, alpha_authority: false, paper_authority: false, live_authority: false };

function renderWithQuery(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

it("shows admission unavailable and never starts a fake run", async () => {
  vi.spyOn(controlApi, "researchStatus").mockResolvedValue({ provider_available: false, cancel_supported: false });
  const start = vi.spyOn(controlApi, "startResearch");
  renderWithQuery(<ResearchObjective onStarted={vi.fn()} />);
  expect(await screen.findByText("Provider unavailable / not admitted")).toBeVisible();
  await userEvent.type(screen.getByLabelText("Set the research objective"), "Research objective");
  expect(screen.getByRole("button", { name: "Start bounded research run" })).toBeDisabled();
  expect(start).not.toHaveBeenCalled();
});

it("sends only a high-level objective and reuses the request identity on uncertain retry", async () => {
  vi.spyOn(controlApi, "researchStatus").mockResolvedValue({ provider_available: true, cancel_supported: false, provider_id: "admitted", model_id: "bounded" });
  const start = vi.spyOn(controlApi, "startResearch").mockRejectedValueOnce(new Error("Transport interrupted"))
    .mockResolvedValueOnce({ status: 202, data: { run_id: "run-a", command_run_id: "cmd-a", state: "accepted", provider: { provider_available: true, cancel_supported: false } } });
  const onStarted = vi.fn();
  renderWithQuery(<ResearchObjective onStarted={onStarted} />);
  await screen.findByText("admitted · bounded");
  await userEvent.type(screen.getByLabelText("Set the research objective"), "Investigate diversification");
  await userEvent.click(screen.getByRole("button", { name: "Start bounded research run" }));
  await screen.findByText("Transport interrupted");
  await userEvent.click(screen.getByRole("button", { name: "Start bounded research run" }));
  await screen.findByText("Research run accepted");
  expect(start.mock.calls[0][0]).toEqual(start.mock.calls[1][0]);
  expect(Object.keys(start.mock.calls[0][0]).sort()).toEqual(["objective", "request_id"]);
  expect(onStarted).toHaveBeenCalledWith("run-a");
});

it("shows retrospective evidence, comparator economics and policy without a raw dump", () => {
  render(<ResearchToolCard status="succeeded" tool={{ tool: "evaluate_portfolio", arguments: { factor_set_id: "set-a" }, policy: { outcome: "allow", reason: "Frozen host economics; all comparators required" }, result: { outcome: "PORTFOLIO_EVALUATED", evaluation_mode: "adaptive_development_retrospective", preferred_allocator: "regime_conditional", summary: { arms: Object.fromEntries(["equal_weight", "rolling_ic", "rolling_net_return", "regime_conditional", "ridge_meta"].map(a => [a, metrics])) } } }} />);
  expect(screen.getByText(/Tested retrospectively/)).toBeVisible();
  expect(screen.getByText(/Not historically known/)).toBeVisible();
  const table = screen.getByRole("table", { name: "5bp development comparison" });
  expect(within(table).getAllByRole("row")).toHaveLength(6);
  expect(within(table).getAllByText("-2.00%")).toHaveLength(5);
  expect(screen.getByText(/Frozen host economics/)).toBeVisible();
  expect(screen.getByText(/"factor_set_id":/)).not.toBeVisible();
});

it("shows real proposal time and explicit current research state", () => {
  render(<><ResearchToolCard status="succeeded" tool={{ tool: "propose_factor", arguments: {}, policy: { outcome: "allow", reason: "Typed graph" }, result: { outcome: "VALIDATED", proposal: { factor_id: "factor-new", proposed_at: "2026-09-06T12:00:00Z", proposal_context_id: "context-a", history_cutoff: "step-3" } } }} /><ResearchContext state={state} /></>);
  for (const text of ["Proposed now", "2026-09-06T12:00:00Z", "Current factor set", "factor-a", "factor-b", "regime_conditional", "Remaining budget", "Stop the hypothesis", "No candidate: fixture only", "model-a"]) expect(screen.getByText(text)).toBeVisible();
  expect(screen.getByText(/Alpha: not confirmed/)).toBeVisible();
  expect(screen.getByText(/PAPER: not accepted/)).toBeVisible();
  expect(screen.getByText(/Live: not authorized/)).toBeVisible();
});

it("makes a rejected lifecycle request and its policy reason visible", () => {
  render(<ResearchToolCard status="denied" tool={{ tool: "retire_hypothesis", arguments: { factor_id: "factor-a", status: "ACTIVE", reason: "Promote" }, policy: { outcome: "deny", reason: "invalid_lifecycle_transition" }, result: { outcome: "REJECTED", code: "invalid_lifecycle_transition" } }} />);
  expect(screen.getByText(/Action rejected/)).toBeVisible();
  expect(screen.getByText("Policy deny")).toBeVisible();
  expect(screen.getAllByText(/invalid_lifecycle_transition/).length).toBeGreaterThan(0);
});

it("treats exhausted resource state as first-class product state", () => {
  const exhausted: ResearchState = { ...state, resources: { ...state.resources, status: "SLOT_ATTEMPTS_EXHAUSTED", remaining_evaluations: 0 } };
  render(<ResearchContext state={exhausted} />);
  expect(screen.getByText(/Budget \/ slot exhaustion/)).toBeVisible();
  expect(screen.getByText(/SLOT_ATTEMPTS_EXHAUSTED/)).toBeVisible();
});

import { expect, test } from "@playwright/test";

const experiment = (id: string, mean: number) => ({
  attempt_id: `call-${id}`,
  experiment_id: id,
  identity: id,
  identity_kind: "experiment_id",
  canonical_experiment_identity_available: true,
  run_id: "run-r4",
  project_id: "r4-research",
  thread_id: "thread-run-r4",
  objective: "Evaluate bounded factor-set evidence",
  hypothesis_id: "hypothesis-a",
  factor_set_id: "factor-set-a",
  factor_ids: ["factor-a", "factor-b"],
  allocator_proposal_id: "allocator-a",
  allocator: "equal_weight",
  status: "completed",
  outcome: "PORTFOLIO_EVALUATED",
  evaluation_scope: { compatibility_id: "compat-a", evaluation_mode: "development_descriptive" },
  authoritative_metrics: { mean_fold_return_5bp: mean, evaluable_folds: 3 },
  metrics_source: "persisted_research_result",
  provider_id: "persisted-provider",
  model_id: "persisted-model",
  resource_snapshot: { evaluations: 1, remaining_evaluations: 2 },
  evaluation_budget: { used: 1, remaining: 2 },
  tokens: 1500,
  cost_microusd: 2800,
  agent_decision: { action_id: "call-final", kind: "finalize_candidate", recommendation: "reject", decision: "Reject incomplete evidence", terminal: "NO_CANDIDATE_RECOMMENDED" },
  related_identities: [],
  error: null,
  read_only: true,
  browser_recomputation: false,
  hidden_reasoning: "not_persisted_not_projected",
});

const expA = experiment("exp-a", 0.01);
const expB = experiment("exp-b", 0.02);
const failed = { ...expA, attempt_id: "call-failed", experiment_id: null, identity: "call-failed", identity_kind: "attempt_call_id", canonical_experiment_identity_available: false, status: "failed", authoritative_metrics: null, error: "unknown_run_local_proposal", agent_decision: null };

const cycles = {
  schema_version: "finagent.workspace.research-cycles.v1",
  read_only: true,
  browser_recomputation: false,
  items: [{
    cycle_id: "cycle-a",
    protocol_version: "r4-matched-v3",
    terminal: "NO_ADAPTIVE_CANDIDATE",
    agent_value: "INCONCLUSIVE",
    candidate_id: null,
    economic_evidence: { deterministic_strategy_count: 20, complete_deterministic_strategy_count: 0, deterministic_evidence_complete: false },
    provider_usage: {},
    agent_reliability: { rejected_action_attempts: 62 },
    resource_summary: {},
    authority: { alpha_authority: false, paper_authority: false, live_authority: false },
    evidence: {},
  }],
};

const graph = {
  schema_version: "finagent.workspace.research-graph.v1",
  read_only: true,
  canonical_identity_only: true,
  browser_recomputation: false,
  hidden_reasoning: "not_persisted_not_projected",
  nodes: [
    { node_id: "hypothesis:hypothesis-a", kind: "hypothesis", identity: "hypothesis-a", label: "hypothesis-a", status: "persisted", href: null, context: { run_id: "run-r4", project_id: "r4-research", thread_id: "thread-run-r4" }, details: {} },
    { node_id: "experiment:exp-a", kind: "experiment", identity: "exp-a", label: "exp-a", status: "completed", href: "/experiments?experiment=exp-a", context: { run_id: "run-r4", project_id: "r4-research", thread_id: "thread-run-r4", experiment_id: "exp-a" }, details: {} },
    { node_id: "terminal:cycle-a", kind: "terminal", identity: "cycle-a", label: "NO_ADAPTIVE_CANDIDATE", status: "accepted_terminal", href: null, context: {}, details: { agent_value: "INCONCLUSIVE", candidate_id: null } },
  ],
  edges: [{ edge_id: "hyp-exp", source: "hypothesis:hypothesis-a", target: "experiment:exp-a", relation: "persisted_relation" }],
  unresolved: [{ cycle_id: "cycle-a", relation: "campaign_run_experiment_lineage", reason: "accepted_attestation_does_not_embed_run_local_experiment_identities" }],
};

test("Experiments compares persisted results and Research Graph preserves canonical context", async ({ page }) => {
  await page.route("**/api/v3/research-experiments?run_id=run-r4", (route) => route.fulfill({ json: { schema_version: "experiments", configured: true, items: [expA, expB, failed], read_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected" } }));
  await page.route("**/api/v3/research-cycles", (route) => route.fulfill({ json: cycles }));
  await page.route("**/api/v3/research-experiments/exp-a", (route) => route.fulfill({ json: { schema_version: "detail", item: expA, read_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected" } }));
  await page.route("**/api/v3/research-experiments/compare?**", (route) => route.fulfill({ json: { schema_version: "comparison", experiment_ids: ["exp-a", "exp-b"], comparison_call_id: "call-compare", comparable: true, reason: null, persisted_comparison: { outcome: "EXPERIMENTS_COMPARED", experiments: [{ experiment_id: "exp-a", metrics_5bp: { mean_fold_return_5bp: 0.01 } }, { experiment_id: "exp-b", metrics_5bp: { mean_fold_return_5bp: 0.02 } }] }, items: [expA, expB], ranking: null, read_only: true, browser_recomputation: false } }));
  await page.route("**/api/v3/research-graph?run_id=run-r4", (route) => route.fulfill({ json: graph }));

  await page.goto("/experiments?run=run-r4&experiment=exp-a&compare=exp-a%2Cexp-b");
  await expect(page.getByRole("heading", { name: "Experiments" })).toBeVisible();
  await expect(page.getByText("NO_ADAPTIVE_CANDIDATE")).toBeVisible();
  await expect(page.getByText("0/20 complete deterministic strategies")).toBeVisible();
  await expect(page.getByText("unknown_run_local_proposal")).toBeVisible();
  await expect(page.getByTestId("experiment-comparison")).toContainText("ranking = null");
  await expect(page.getByTestId("experiment-comparison")).toContainText("0.02");

  await page.goto("/research-graph?run=run-r4&graph_node=terminal%3Acycle-a&cycle=cycle-a");
  await expect(page.getByRole("heading", { name: "Research Graph" })).toBeVisible();
  await expect(page.getByText("accepted_attestation_does_not_embed_run_local_experiment_identities")).toBeVisible();
  await expect(page.getByTestId("workbench-context-bar")).toContainText("terminal:cycle-a");
  await expect(page.getByTestId("research-graph")).toContainText("NO_ADAPTIVE_CANDIDATE");
});

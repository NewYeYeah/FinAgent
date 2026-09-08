import { expect, test, type Page } from "@playwright/test";

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
  combined_strategy_evidence: { available: false },
  target_portfolio: { available: false },
  execution_pnl: { available: false },
  attribution: { available: false, reason: "unavailable_not_persisted" },
  available_evidence: { market_state_model_ids: ["market-model-a"], factors: [{ factor_id: "factor-a", status: "ACTIVE" }], canonical_experiment_ids: ["exp-a"], historical_strategy_series: [{ strategy_series_id: "historical-a", relation_to_cycle: "unbound_historical_evidence" }] },
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

async function routeCommon(page: Page, detail: typeof noCandidate | typeof candidate) {
  await page.route("**/api/v4/strategy-series", (route) => route.fulfill({ json: { schema_version: "strategy", read_only: true, items: [], warnings: [] } }));
  await page.route("**/api/v3/linked-strategy", (route) => route.fulfill({ json: { schema_version: "index", items: [{ cycle_id: detail.cycle.cycle_id, mode: detail.mode, strategy_binding_status: detail.strategy_binding.status, r5_eligible: detail.r5.eligible }], default_cycle_id: detail.cycle.cycle_id, historical_strategy_series_count: 1, historical_strategy_relation: "unbound_unless_explicit_candidate_binding", read_only: true, canonical_identity_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected" } }));
  await page.route(`**/api/v3/linked-strategy/cycles/${detail.cycle.cycle_id}`, (route) => route.fulfill({ json: detail }));
}

test("accepted no-candidate terminal explains available evidence without fabricating a strategy", async ({ page }) => {
  await routeCommon(page, noCandidate);
  await page.goto("/strategy?cycle=cycle-no");
  const panel = page.getByTestId("linked-strategy-panel");
  await expect(panel).toContainText("NO_ADAPTIVE_CANDIDATE");
  await expect(panel).toContainText("AgentValue INCONCLUSIVE");
  await expect(panel).toContainText("0/20 complete deterministic strategies");
  await expect(panel).toContainText("62 rejected Agent actions");
  await expect(panel).toContainText("not bound to this R4 terminal");
  await expect(panel).toContainText("does not mean all strategies lost money");
  await expect(panel).toContainText("Browser financial/statistical recomputation = false");
  await expect(page.getByTestId("workbench-context-bar")).toContainText("cycle-no");
});

test("persisted candidate exposes exact Strategy Portfolio Execution and evidence deep links", async ({ page }) => {
  await routeCommon(page, candidate);
  await page.goto("/strategy?cycle=cycle-candidate&strategy=candidate-a");
  const panel = page.getByTestId("linked-strategy-panel");
  await expect(panel).toContainText("candidate-a");
  await expect(panel).toContainText("resolved");
  await expect(panel).toContainText("Portfolio / execution persisted");
  await expect(panel).toContainText("Attribution: unavailable");
  await expect(panel.getByRole("link", { name: /Market State/ })).toHaveAttribute("href", /market_model=market-model-a/);
  await expect(panel.getByRole("link", { name: /Factor 1/ })).toHaveAttribute("href", /factor=factor-a/);
  await expect(panel.getByRole("link", { name: /Experiment 1/ })).toHaveAttribute("href", /experiment=exp-a/);
  await expect(panel.getByRole("link", { name: /Strategy evidence/ })).toHaveAttribute("href", /\/strategy\/strategy-series-a/);
  await expect(panel.getByRole("link", { name: /^Portfolio/ })).toHaveAttribute("href", /\/portfolio\/portfolio-a/);
  await expect(panel.getByRole("link", { name: /Execution \/ PnL/ })).toHaveAttribute("href", /\/execution\/portfolio-a/);
  await expect(panel.getByRole("link", { name: /Research Graph/ })).toHaveAttribute("href", /strategy=candidate-a/);
  await expect(panel.getByRole("link", { name: /Agent run/ })).toHaveAttribute("href", /run=run-r4/);
  await expect(panel).toContainText("Browser financial/statistical recomputation = false");
  await expect(page.getByTestId("workbench-context-bar")).toContainText("candidate-a");
  await expect(page.getByTestId("workbench-context-bar")).toContainText("cycle-candidate");
});

import { expect, test } from "@playwright/test";

const cycles = { schema_version: "cycles", items: [{ cycle_id: "cycle-a", accepted: true, review_status: "accepted", review_disposition: "R4_RESULT_ACCEPTED", terminal: "NO_ADAPTIVE_CANDIDATE", agent_value: "INCONCLUSIVE", economic_evidence: { deterministic_strategy_count: 20, complete_deterministic_strategy_count: 0 }, agent_reliability: { rejected_action_attempts: 62 }, provider_usage: {}, resource_summary: {}, authority: {}, evidence: {} }], read_only: true, browser_recomputation: false };
const market = { model_id: "market-model-a", model_artifact_id: "model-a", result_artifact_id: "result-a", model: { version: "finagent.market-state-gmm.v1", estimator: "GaussianMixture", available_at: "2026-01-03T00:00:00+00:00", fit_window: { start: "2026-01-01", end: "2026-01-03" }, implementation_id: "impl-a" }, historical_states: [{ event_time: "2026-01-03T10:00:00+00:00", available_at: "2026-01-03T10:15:00+00:00", state: 0, probabilities: [0.8, 0.2], unavailable_reason: null }, { event_time: "2026-01-03T10:15:00+00:00", available_at: "2026-01-03T10:30:00+00:00", state: 1, probabilities: [0.2, 0.8], unavailable_reason: null }], current_snapshot: { event_time: "2026-01-03T10:15:00+00:00", available_at: "2026-01-03T10:30:00+00:00", state: 1, probabilities: [0.2, 0.8], unavailable_reason: null }, transitions: [{ from_state: 0, to_state: 1, available_at: "2026-01-03T10:30:00+00:00", semantics: "adjacent_persisted_available_snapshots_no_smoothing" }], unavailable_snapshot_count: 0, available_snapshot_count: 2, feature_definitions: ["persisted feature"], feature_identities: null, feature_identity_status: "unavailable_not_persisted", causal: { browser_refit: false, smoothing: false, future_fill: false }, factor_state_evidence: [{ factor_id: "factor-a", status: "ACTIVE", evaluations: [{ evaluation_id: "eval-a", by_market_state: { state_1: { coverage: 0.9 } } }], allocator_weight_observations: [] }], linked_experiment_ids: ["exp-a"], unavailable: {} };
const markets = { schema_version: "market", items: [market], warnings: [], read_only: true, browser_recomputation: false, causal_projection: true, hidden_reasoning: "not_persisted_not_projected" };
const factorSummary = { factor_id: "factor-a", status: "ACTIVE", status_reason: "latest_persisted_lifecycle_event", family: "flow", mechanism: "causal", hypothesis: "hypothesis", origin: "agent", provenance: { source: "fixture" }, definition_conflict: false, library_ids: ["library-a"], lifecycle: [{ status: "ACTIVE" }], evaluation_count: 1, latest_model_id: "market-model-a", evaluation_selection_reason: "latest_by_persisted_available_at" };
const factor = { ...factorSummary, evaluations: [], latest_evaluation: {}, global_metrics: { coverage: 0.8 }, state_metrics: { state_1: { coverage: 0.9 } }, cost_sensitive_economics: null, similarity: null, novelty: null, novelty_status: "unavailable_not_persisted", allocator_weights: [], allocator_weight_status: "unavailable_not_persisted", linked_market_state_model_ids: ["market-model-a"], linked_experiments: [{ identity: "exp-a", experiment_id: "exp-a", run_id: "run-a" }], agent_decision_history: [{ node_id: "decision-a", run_id: "run-a", status: "recorded" }], evidence_identities: ["eval-a"], unavailable: { allocator_weights: "not_persisted" } };

 test("Market State and Factor Intelligence retain canonical deep links without browser authority", async ({ page }) => {
  await page.route("**/api/v3/market-state", (route) => route.fulfill({ json: markets }));
  await page.route("**/api/v3/market-state/market-model-a", (route) => route.fulfill({ json: { ...markets, item: market } }));
  await page.route("**/api/v3/research-cycles", (route) => route.fulfill({ json: cycles }));
  await page.route("**/api/v3/factor-intelligence", (route) => route.fulfill({ json: { schema_version: "factors", items: [factorSummary], warnings: [], read_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected" } }));
  await page.route("**/api/v3/factor-intelligence/factor-a", (route) => route.fulfill({ json: { schema_version: "factor", item: factor, warnings: [], read_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected" } }));
  await page.route("**/api/v4/factor-series", (route) => route.fulfill({ json: { schema_version: "catalog", items: [], read_only: true } }));
  await page.goto("/market?market_model=market-model-a");
  await expect(page.getByRole("heading", { name: "Market State" })).toBeVisible();
  await expect(page.getByText("NO_ADAPTIVE_CANDIDATE")).toBeVisible();
  await page.getByRole("link", { name: /factor-a/ }).click();
  await expect(page).toHaveURL(/factor=factor-a/);
  await page.goto("/factors?factor=factor-a&market_model=market-model-a");
  await expect(page.getByRole("region", { name: "Factor Intelligence" })).toBeVisible();
  await expect(page.getByText(/Hidden chain-of-thought is not persisted or projected/)).toBeVisible();
  await page.getByRole("link", { name: /experiment:exp-a/ }).click();
  await expect(page).toHaveURL(/experiment=exp-a/);
});

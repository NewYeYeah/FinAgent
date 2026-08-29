import { expect, test } from "@playwright/test";

const projects = {
  schema_version: "finagent.workspace.projects.v2",
  read_only: true,
  warnings: [],
  items: [
    {
      project_id: "program-v2",
      program_id: "program-v2",
      program_evidence_id: "program-result-v2",
      program_spec_id: "spec-v2",
      selection_id: "selection-v2",
      data_version: "data-v2",
      git_sha: "abc123",
      system_status: "PASS",
      research_status: "ROBUST_FACTOR_FAMILY_FROZEN",
      protocol_frozen: true,
      a3_status: "BOUND_IN_A4_PROTOCOL",
      a3_authority: "derived",
      a4_validation_id: "a4-v2",
      a4_spec_id: "a4-spec-v2",
      a4_status: "EXECUTION_VALIDATION_PASSED_INTERNAL",
      a4_execution_validation_passed: true,
      reserve: { reserve_id: "reserve-v2", status: "untouched" },
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

test("V2 governance cockpit is visibly read-only and reserve-safe", async ({ page }) => {
  await page.route("**/api/v2/projects", (route) => route.fulfill({ json: projects }));
  await page.goto("/");
  await expect(page.getByText(/Evidence Plane is GET-only/i)).toBeVisible();
  await expect(page.getByText("Research governance cockpit")).toBeVisible();
  await expect(page.getByText("One-shot reserve", { exact: true })).toBeVisible();
  await expect(page.getByText("LOCKED_NOT_CONSUMED")).toBeVisible();
  await expect(page.getByText("reserve:untouched")).toBeVisible();
  await expect(page.getByRole("button", { name: /promote|reserve|order|rerun/i })).toHaveCount(0);
});

const reserveDetail = {
  schema_version: "finagent.workspace.reserve-lifecycle.v1",
  read_only: true,
  authority: "authoritative",
  reserve_id: "reserve-v2",
  state: "CONSUMED",
  a5_status: "RESERVE_PASS",
  promotion_eligible: false,
  automatic_retry_allowed: false,
  program_result_id: "program-result-v2",
  portfolio_validation_id: "a4-v2",
  seal: { seal_id: "seal-v2" },
  claim: { claim_id: "claim-v2", state: "CONSUMED" },
  terminal: {
    terminal_evidence_id: "terminal-v2",
    status: "RESERVE_PASS",
    reason_codes: ["RESERVE_PASS_TERMINAL"],
    aggregate: {
      net_metrics: { total_return: 0.08, sharpe: 0.9, max_drawdown: -0.06 },
      gross_metrics: { total_return: 0.1, sharpe: 1.0 },
    },
  },
  audit: { audit_id: "audit-v2" },
  ledger: {
    available: true,
    row_count: 1,
    semantic_digest: "a5-ledger-v2",
    file_sha256: "a".repeat(64),
    authority: "authoritative",
  },
  integrity: {
    status: "PASS",
    checks: [{ name: "claim.seal_id", passed: true, detail: "bound" }],
    failed_count: 0,
    fully_audited: true,
  },
  lineage: {
    nodes: [
      { evidence_id: "seal-v2", evidence_type: "ReserveEligibilitySeal", stage: "A5-1", authority: "authoritative", status: "complete", label: "Eligibility seal" },
      { evidence_id: "claim-v2", evidence_type: "ReserveConsumptionClaim", stage: "A5-3", authority: "authoritative", status: "CONSUMED", label: "Durable CONSUMED claim" },
      { evidence_id: "terminal-v2", evidence_type: "ReserveTerminalEvidence", stage: "A5-2/A5-3", authority: "authoritative", status: "RESERVE_PASS", label: "Terminal result" },
      { evidence_id: "audit-v2", evidence_type: "ReserveConsumptionAudit", stage: "A5-3", authority: "authoritative", status: "PASS", label: "Replay audit" },
    ],
    edges: [
      { parent_id: "seal-v2", child_id: "claim-v2", relation: "authorizes_pre_access_consumption" },
      { parent_id: "claim-v2", child_id: "terminal-v2", relation: "consumed_before_terminal_evaluation" },
      { parent_id: "terminal-v2", child_id: "audit-v2", relation: "verified_by_replay_audit" },
    ],
  },
};

const reserveLedger = {
  schema_version: "finagent.workspace.reserve-ledger.v1",
  read_only: true,
  authority: "authoritative",
  reserve_id: "reserve-v2",
  terminal_evidence_id: "terminal-v2",
  row_count: 1,
  semantic_digest: "a5-ledger-v2",
  file_sha256: "a".repeat(64),
  rows: [{ session_date: "2025-01-02", net_nav: 1.01 }],
};

test("A5-4 reserve cockpit renders authoritative lifecycle without mutation controls", async ({ page }) => {
  await page.route("**/api/v2/reserves/reserve-v2/ledger", (route) => route.fulfill({ json: reserveLedger }));
  await page.route("**/api/v2/reserves/reserve-v2", (route) => route.fulfill({ json: reserveDetail }));
  await page.goto("/reserve/reserve-v2");
  await expect(page.getByText("A5 One-shot Reserve")).toBeVisible();
  await expect(page.getByText("Lifecycle integrity")).toBeVisible();
  await expect(page.getByText("retry:false")).toBeVisible();
  await expect(page.getByText("RESERVE_PASS").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /retry|promote|execute|order|recover/i })).toHaveCount(0);
});

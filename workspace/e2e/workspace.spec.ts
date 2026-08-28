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
  await expect(page.getByText("Read-only evidence workspace")).toBeVisible();
  await expect(page.getByText("Research governance cockpit")).toBeVisible();
  await expect(page.getByText("One-shot reserve")).toBeVisible();
  await expect(page.getByText("LOCKED_NOT_CONSUMED")).toBeVisible();
  await expect(page.getByText("reserve:untouched")).toBeVisible();
  await expect(page.getByRole("button", { name: /promote|reserve|order|rerun/i })).toHaveCount(0);
});

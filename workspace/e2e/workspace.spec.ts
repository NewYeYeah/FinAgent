import { expect, test } from "@playwright/test";

const catalog = {
  schema_version: "finagent.workspace.catalog.v1",
  read_only: true,
  warnings: [],
  items: [
    {
      evidence_id: "program-v1",
      evidence_type: "ashare_robust_research_program",
      stage: "a2p6_robust_research",
      authority: "authoritative",
      system_status: "PASS",
      research_status: "ROBUST_FACTOR_FAMILY_FROZEN",
      reserve_status: "untouched",
      promotion_eligible: false,
      program_id: "program-v1",
      spec_id: "spec-v1",
      data_version: "data-v1",
      source_uri: "reports/a26.json",
      factor_count: 1,
      has_portfolio: false,
      has_execution: false,
      detail_url: "/api/v1/evidence/program-v1",
    },
  ],
};

const bundle = {
  schema_version: "finagent.visualization.evidence-bundle.v1",
  root: {
    evidence_id: "program-v1",
    evidence_type: "ashare_robust_research_program",
    schema_version: "finagent.ashare-robust-research-program.v1",
    stage: "a2p6_robust_research",
    authority: "authoritative",
    artifact_digest: "digest-v1",
    source_uri: "reports/a26.json",
    parent_ids: ["selection-v1"],
    program_id: "program-v1",
    spec_id: "spec-v1",
    data_version: "data-v1",
    git_sha: "",
    metadata: { label: "A2.6 robust ResearchProgram" },
  },
  refs: [],
  system_status: "PASS",
  research_status: "ROBUST_FACTOR_FAMILY_FROZEN",
  reserve_status: "untouched",
  promotion_eligible: false,
  factors: [
    {
      feature_id: "momentum-20",
      feature_digest: "a".repeat(64),
      hypothesis: "medium-horizon continuation",
      selected: true,
      weight: 1,
      direction: 1,
      status: "PASS",
      reason_codes: [],
      metrics: {
        pooled_rank_icir: 0.11,
        worst_fold_rank_icir: 0.04,
        bh_qvalue: 0.08,
      },
      folds: [],
    },
  ],
  portfolio: null,
  execution: null,
  lineage: {
    nodes: [
      {
        evidence_id: "program-v1",
        evidence_type: "ashare_robust_research_program",
        stage: "a2p6_robust_research",
        authority: "authoritative",
        status: "ROBUST_FACTOR_FAMILY_FROZEN",
        label: "A2.6 robust ResearchProgram",
      },
    ],
    edges: [],
  },
  metadata: {},
};

test("research evidence is navigable and visibly read-only", async ({ page }) => {
  await page.route("**/api/v1/catalog", (route) => route.fulfill({ json: catalog }));
  await page.route("**/api/v1/widgets", (route) => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/v1/evidence/program-v1", (route) => route.fulfill({ json: bundle }));
  await page.goto("/");
  await expect(page.getByText("Read-only evidence workspace")).toBeVisible();
  await expect(page.getByText("ashare_robust_research_program")).toBeVisible();
  await page.getByText("ashare_robust_research_program").click();
  await expect(page.getByText("Factor family")).toBeVisible();
  await expect(page.getByText("momentum-20")).toBeVisible();
  await expect(page.getByText("reserve:untouched")).toBeVisible();
  await expect(page.getByRole("button", { name: /promote/i })).toHaveCount(0);
});

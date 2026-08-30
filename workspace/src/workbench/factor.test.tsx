import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

vi.mock("echarts-for-react", () => ({
  default: ({ option }: { option: { series?: Array<{ name?: string }> } }) => (
    <div data-testid="echarts">
      {(option.series ?? []).map((series) => series.name).filter(Boolean).join("|")}
    </div>
  ),
}));

import { WorkbenchContextProvider } from "./context";
import { FactorTearSheetPage } from "./factor";
import { WorkbenchQueryProvider } from "./query";

const seriesId = "factor-series-v43";
const programId = "program-v43";
const factorA = "factor-a-v43";
const factorB = "factor-b-v43";

function response(payload: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const item = {
  series_id: seriesId,
  program_result_id: "program-result-v43",
  program_id: programId,
  data_version: "data-v43",
  candidate_feature_digests: [factorA, factorB],
  selected_feature_digests: [factorA],
  primary_label: "ret_5d",
  decay_labels: ["ret_10d"],
  row_count: 100,
  factor_count: 2,
  fold_count: 2,
  session_count: 20,
  start_date: "2024-01-02",
  end_date: "2024-02-02",
  authority: "authoritative",
  detail_url: `/api/v4/factor-series/${seriesId}`,
};

const catalog = {
  schema_version: "finagent.factor-tear-sheet.catalog.v1",
  read_only: true,
  items: [item],
  warnings: [],
  notices: [],
};

const detail = {
  schema_version: "finagent.factor-tear-sheet.series.v1",
  read_only: true,
  item,
  manifest: {
    ...item,
    schema_version: "finagent.factor-series.manifest.v1",
    program_spec_id: "program-spec-v43",
    walk_forward_report_id: "walk-v43",
    gate_report_id: "gate-v43",
    selection_id: "selection-v43",
    plan_id: "plan-v43",
    candidate_selection_id: "candidate-selection-v43",
    universe_policy_version: "universe-v43",
    quantiles: 3,
    min_cross_section: 20,
    min_periods: 5,
    annualization: 252,
    winsor_lower_quantile: 0.01,
    winsor_upper_quantile: 0.99,
    rolling_window: 20,
    quant_config_digest: "quant-v43",
    rows_digest: "rows-v43",
    source_report_content_digest: "source-v43",
    source_report_file: "a2p6.json",
    source_report_sha256: "a".repeat(64),
    data_file: "factor.parquet",
    data_sha256: "b".repeat(64),
    columns: [],
    nullable_columns: [],
  },
  presentation: {
    browser_recomputation: false,
    period_series_source: "verified V4-1 FactorSeries",
    statistical_summary_source: "frozen A2.6 walk-forward report",
    heatmap_authority: "derived_presentation",
    correlation_cluster_authority: "derived_presentation",
    agent_chronology_available: false,
  },
};

const dimensions = {
  schema_version: "finagent.factor-tear-sheet.dimensions.v1",
  read_only: true,
  authority: "authoritative_identity_dimensions",
  series_id: seriesId,
  program_result_id: item.program_result_id,
  program_id: programId,
  factors: [
    { ordinal: 0, feature_id: "Alpha A", feature_digest: factorA, hypothesis: "A hypothesis", generator_id: "agent-v43", selected: true },
    { ordinal: 1, feature_id: "Alpha B", feature_digest: factorB, hypothesis: "B hypothesis", generator_id: "agent-v43", selected: false },
  ],
  folds: ["wf-1", "wf-2"],
  labels: ["ret_5d", "ret_10d"],
  primary_label: "ret_5d",
  decay_labels: ["ret_10d"],
  quantiles: [1, 2, 3],
  start_date: "2024-01-02",
  end_date: "2024-02-02",
  session_count: 20,
  rolling_window: 20,
  metric_authority: { authoritative: ["rank_ic", "coverage"], derived: ["rolling_rank_ic", "nav"] },
};

const candidate = (digest: string, id: string, selected: boolean) => ({
  ordinal: selected ? 0 : 1,
  feature_id: id,
  feature_digest: digest,
  hypothesis: `${id} hypothesis`,
  generator_id: "agent-v43",
  input_fields: ["close"],
  lookback: 20,
  selected,
  selection: { direction: selected ? 1 : null, robust_score: selected ? 1.2 : null, weight: selected ? 1 : null },
  gate: { passed: selected, reason_codes: selected ? [] : ["POOLED_RANK_ICIR_BELOW_THRESHOLD"], robust_score: selected ? 1.2 : 0.2 },
  metrics: {
    dominant_direction: 1,
    direction_consistency: 1,
    pooled_rank_ic: selected ? 0.04 : 0.01,
    pooled_rank_icir: selected ? 0.6 : 0.1,
    mean_fold_rank_icir: selected ? 0.55 : 0.1,
    worst_fold_rank_icir: selected ? 0.45 : -0.05,
    positive_fold_ratio: selected ? 1 : 0.5,
    mean_fold_long_short_sharpe: selected ? 1.1 : 0.2,
    worst_fold_long_short_sharpe: selected ? 0.8 : -0.1,
    coverage_mean: 0.95,
    coverage_min: 0.92,
    quantile_monotonicity: 0.8,
    mean_one_way_turnover: 0.15,
    horizon_sign_consistency: 1,
  },
  hac: { tstat: 2.1, raw_pvalue: 0.03, holm_adjusted_pvalue: 0.06, bh_qvalue: 0.04 },
  block_bootstrap: { pvalue: 0.04, ci_lower: 0.01, ci_upper: 0.07 },
  folds: [
    { fold_id: "wf-1", train_direction: 1, train_rank_ic: 0.05, train_rank_icir: 0.7, test_raw_rank_ic: 0.04, test_raw_rank_icir: 0.5, test_rank_ic: 0.04, test_rank_icir: 0.5, test_raw_long_short_sharpe: 1, test_long_short_sharpe: 1, coverage: 0.95, quantile_monotonicity: 0.8, mean_one_way_turnover: 0.15, periods: 10 },
    { fold_id: "wf-2", train_direction: 1, train_rank_ic: 0.05, train_rank_icir: 0.7, test_raw_rank_ic: 0.03, test_raw_rank_icir: 0.45, test_rank_ic: 0.03, test_rank_icir: 0.45, test_raw_long_short_sharpe: 0.8, test_long_short_sharpe: 0.8, coverage: 0.92, quantile_monotonicity: 0.7, mean_one_way_turnover: 0.16, periods: 10 },
  ],
});

const summary = {
  schema_version: "finagent.factor-tear-sheet.summary.v1",
  read_only: true,
  authority: "authoritative_frozen_a2p6_summary",
  series_id: seriesId,
  program_result_id: item.program_result_id,
  selection_status: "ROBUST_FACTOR_FAMILY_FROZEN",
  gate_report_id: "gate-v43",
  selection_id: "selection-v43",
  items: [candidate(factorA, "Alpha A", true), candidate(factorB, "Alpha B", false)],
};

const correlation = {
  schema_version: "finagent.factor-tear-sheet.correlation.v1",
  read_only: true,
  series_id: seriesId,
  factors: [factorA, factorB],
  cells: [
    { left: factorA, right: factorA, value: 1 },
    { left: factorA, right: factorB, value: 0.25 },
    { left: factorB, right: factorA, value: 0.25 },
    { left: factorB, right: factorB, value: 1 },
  ],
  correlation_authority: "authoritative_frozen_a2p6_summary",
  cluster_order: [factorB, factorA],
  cluster_authority: "derived_presentation",
  cluster_method: "average_linkage_on_1_minus_absolute_correlation",
};

const heatmap = {
  schema_version: "finagent.factor-tear-sheet.heatmap.v1",
  read_only: true,
  authority: "derived_presentation",
  source_authority: "authoritative_v4_1_period_rows",
  aggregation: "arithmetic_mean_by_factor_fold_calendar_year",
  series_id: seriesId,
  metric: "rank_ic",
  label_name: "ret_5d",
  cells: [
    { feature_digest: factorA, fold_id: "wf-1", year: 2024, value: 0.04, observations: 10 },
    { feature_digest: factorA, fold_id: "wf-2", year: 2024, value: 0.03, observations: 10 },
  ],
};

const provenance = {
  schema_version: "finagent.factor-tear-sheet.provenance.v1",
  read_only: true,
  authority: "authoritative_frozen_candidate_denominator",
  ordering_semantics: "frozen_candidate_denominator_order_only",
  agent_chronology_available: false,
  chronology_note: "Agent generation timestamp/round timeline is not persisted; V4-3 does not infer one.",
  series_id: seriesId,
  items: [
    { ordinal: 0, feature_id: "Alpha A", feature_digest: factorA, hypothesis: "A hypothesis", generator_id: "agent-v43", input_fields: ["close"], lookback: 20, gate_passed: true, gate_reason_codes: [], selected: true },
    { ordinal: 1, feature_id: "Alpha B", feature_digest: factorB, hypothesis: "B hypothesis", generator_id: "agent-v43", input_fields: ["close"], lookback: 20, gate_passed: false, gate_reason_codes: ["POOLED_RANK_ICIR_BELOW_THRESHOLD"], selected: false },
  ],
};

function rowPayload(url: string) {
  const request = new URL(url, "http://localhost");
  const metric = request.searchParams.get("metric") ?? "rank_ic";
  const kind = request.searchParams.get("series_kind") ?? "ic";
  const label = request.searchParams.get("label_name") ?? "";
  const quantile = request.searchParams.get("quantile");
  const fold = request.searchParams.get("fold_id") ?? "wf-1";
  const authority = metric.startsWith("rolling_") || metric === "nav" ? "derived" : "authoritative";
  const items = ["2024-01-02", "2024-01-03"].map((session, index) => ({
    sequence: index,
    row_id: `${kind}-${metric}-${label}-${quantile ?? "none"}-${index}`,
    feature_id: "Alpha A",
    feature_digest: factorA,
    fold_id: fold,
    session_date: session,
    train_direction: 1,
    series_kind: kind,
    metric,
    authority,
    label_name: label,
    quantile: quantile == null ? null : Number(quantile),
    value: metric === "coverage" ? 0.95 : metric === "one_way_turnover" ? 0.15 : metric === "nav" ? 1 + index * 0.02 : 0.04 + index * 0.01,
    sample_count: 100,
    window_count: metric.startsWith("rolling_") ? 20 : 1,
  }));
  return {
    schema_version: "finagent.factor-series.query.v1",
    read_only: true,
    authority: "mixed_persisted_metrics",
    series_id: seriesId,
    program_result_id: item.program_result_id,
    total: items.length,
    offset: 0,
    limit: 5000,
    items,
  };
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

function renderPage(initial = `/factors/${seriesId}`) {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <WorkbenchQueryProvider>
        <WorkbenchContextProvider>
          <LocationProbe />
          <Routes>
            <Route path="/factors/:seriesId" element={<FactorTearSheetPage />} />
          </Routes>
        </WorkbenchContextProvider>
      </WorkbenchQueryProvider>
    </MemoryRouter>,
  );
}

describe("V4-3 Factor Tear Sheet", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v4/factor-series") return response(catalog);
      if (url.endsWith(`/api/v4/factor-series/${seriesId}`)) return response(detail);
      if (url.endsWith(`/api/v4/factor-series/${seriesId}/dimensions`)) return response(dimensions);
      if (url.includes(`/api/v4/factor-series/${seriesId}/summary`)) return response(summary);
      if (url.endsWith(`/api/v4/factor-series/${seriesId}/correlations`)) return response(correlation);
      if (url.includes(`/api/v4/factor-series/${seriesId}/heatmap`)) return response(heatmap);
      if (url.endsWith(`/api/v4/factor-series/${seriesId}/provenance`)) return response(provenance);
      if (url.includes(`/api/v4/factor-series/${seriesId}/rows?`)) return response(rowPayload(url));
      throw new Error(`unexpected request: ${url}`);
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders V4-1 series and frozen A2.6 inference without inventing Agent chronology", async () => {
    renderPage();

    expect(await screen.findByText("Alpha A")).toBeInTheDocument();
    expect(screen.getByText("IC & rolling IC")).toBeInTheDocument();
    expect(screen.getByText("IC decay")).toBeInTheDocument();
    expect(screen.getByText("Quantile & long-short NAV")).toBeInTheDocument();
    expect(screen.getByText("Turnover & coverage")).toBeInTheDocument();
    expect(screen.getByText("Fold / year RankIC heatmap")).toBeInTheDocument();
    expect(screen.getByText("HAC / block-bootstrap inference forest")).toBeInTheDocument();
    expect(screen.getByText("Holm / BH multiplicity matrix")).toBeInTheDocument();
    expect(screen.getByText("Factor correlation cluster")).toBeInTheDocument();
    expect(screen.getByText("Candidate provenance")).toBeInTheDocument();
    expect(screen.getByText(/AGENT CHRONOLOGY NOT PERSISTED/i)).toBeInTheDocument();
    expect(screen.getByText(/does not infer one/i)).toBeInTheDocument();
    expect(screen.getByText(/No factor statistics are reconstructed in React/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("location").textContent).toContain(`program=${programId}`);
      expect(screen.getByTestId("location").textContent).toContain(`factor=${factorA}`);
    });
    expect(screen.getAllByTestId("echarts").length).toBeGreaterThanOrEqual(7);
  });

  it("binds fold and date filters through WorkbenchContext and forwards them to bounded rows", async () => {
    renderPage(`/factors/${seriesId}?program=${programId}&factor=${factorA}`);
    await screen.findByText("IC & rolling IC");

    fireEvent.change(screen.getByLabelText("Fold"), { target: { value: "wf-2" } });
    await waitFor(() => expect(screen.getByTestId("location").textContent).toContain("fold=wf-2"));

    fireEvent.change(screen.getByLabelText("Start"), { target: { value: "2024-01-03" } });
    await waitFor(() => {
      const location = screen.getByTestId("location").textContent ?? "";
      expect(location).toContain("range=2024-01-03..2024-02-02");
      const calls = vi.mocked(fetch).mock.calls.map(([value]) => String(value));
      expect(calls.some((value) => value.includes("fold_id=wf-2"))).toBe(true);
      expect(calls.some((value) => value.includes("start=2024-01-03"))).toBe(true);
      expect(calls.some((value) => value.includes("limit=5000"))).toBe(true);
    });
  });
});

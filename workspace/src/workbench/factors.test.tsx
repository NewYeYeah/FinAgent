import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

vi.mock("echarts-for-react", () => ({
  default: ({ option }: { option: { series?: Array<{ name?: string }> } }) => (
    <div data-testid="echarts">
      {(option.series ?? []).map((series) => series.name).filter(Boolean).join("|")}
    </div>
  ),
}));

import { WorkbenchContextProvider } from "./context";
import { FactorTearSheetPage } from "./factors";
import { WorkbenchQueryProvider } from "./query";

function json(payload: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const seriesId = "factor-series-v43a";
const programId = "a2p6-program-v43a";
const factorA = "a".repeat(64);
const factorB = "b".repeat(64);

const item = {
  series_id: seriesId,
  program_result_id: "program-result-v43a",
  program_id: programId,
  selection_id: "selection-v43a",
  data_version: "data-v43a",
  candidate_feature_digests: [factorA, factorB],
  selected_feature_digests: [factorA],
  primary_label: "forward_simple_return_1",
  decay_labels: ["forward_simple_return_5"],
  quantiles: 3,
  row_count: 200,
  factor_count: 2,
  fold_count: 1,
  session_count: 2,
  start_date: "2024-01-02",
  end_date: "2024-01-03",
  source_report_content_digest: "c".repeat(64),
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
    schema_version: "finagent.factor-series.manifest.v1",
    authority: "authoritative",
    series_id: seriesId,
    program_result_id: item.program_result_id,
    program_id: programId,
    program_spec_id: "program-spec-v43a",
    walk_forward_report_id: "walk-v43a",
    gate_report_id: "gate-v43a",
    selection_id: item.selection_id,
    plan_id: "plan-v43a",
    data_version: item.data_version,
    candidate_selection_id: "candidate-selection-v43a",
    universe_policy_version: "universe-v43a",
    candidate_feature_digests: item.candidate_feature_digests,
    selected_feature_digests: item.selected_feature_digests,
    primary_label: item.primary_label,
    decay_labels: item.decay_labels,
    quantiles: 3,
    min_cross_section: 5,
    min_periods: 20,
    annualization: 252,
    winsor_lower_quantile: 0.01,
    winsor_upper_quantile: 0.99,
    rolling_window: 20,
    quant_config_digest: "d".repeat(40),
    rows_digest: "e".repeat(64),
    source_report_content_digest: item.source_report_content_digest,
    source_report_file: "robust.json",
    source_report_sha256: "f".repeat(64),
    data_file: "robust.factor-series.parquet",
    data_sha256: "1".repeat(64),
    row_count: 200,
    factor_count: 2,
    fold_count: 1,
    session_count: 2,
    start_date: item.start_date,
    end_date: item.end_date,
    columns: [],
    nullable_columns: [],
    metric_authority: {
      authoritative: ["rank_ic", "return", "one_way_turnover", "coverage"],
      derived: ["rolling_rank_ic", "nav"],
    },
  },
  presentation: {
    browser_recomputation: false,
    period_evidence: "persisted V4-1 rows",
    statistical_summary: "frozen A2.6",
    derived_metrics: ["rolling_pearson_ic", "rolling_rank_ic", "nav"],
  },
};

const dimensions = {
  schema_version: "finagent.factor-tear-sheet.dimensions.v1",
  read_only: true,
  series_id: seriesId,
  program_id: programId,
  program_result_id: item.program_result_id,
  factors: [
    { feature_digest: factorA, feature_id: "momentum", selected: true },
    { feature_digest: factorB, feature_id: "reversal", selected: false },
  ],
  folds: ["wf-2024"],
  labels: [item.primary_label, item.decay_labels[0]],
  primary_label: item.primary_label,
  decay_labels: item.decay_labels,
  quantiles: [1, 2, 3],
  start_date: item.start_date,
  end_date: item.end_date,
  session_count: 2,
  metric_authority: detail.manifest.metric_authority,
};

function summaryFactor(feature_digest: string, feature_id: string, selected: boolean) {
  return {
    feature_id,
    feature_digest,
    selected,
    statistics: {
      pooled_rank_icir: 0.25,
      mean_fold_long_short_sharpe: 0.5,
      hac_tstat: 2.2,
      bootstrap_pvalue: 0.03,
      bootstrap_ci_lower: 0.001,
      bootstrap_ci_upper: 0.02,
      holm_adjusted_pvalue: 0.04,
      bh_qvalue: 0.05,
    },
    folds: [{ fold_id: "wf-2024", test_rank_icir: 0.25 }],
    gate: { passed: true },
    selection_component: selected ? { weight: 1 } : null,
  };
}

const summary = {
  schema_version: "finagent.factor-tear-sheet.summary.v1",
  read_only: true,
  authority: "authoritative_frozen_a2p6_summary",
  statistics_recomputed: false,
  series_id: seriesId,
  program_id: programId,
  program_result_id: item.program_result_id,
  items: [
    summaryFactor(factorA, "momentum", true),
    summaryFactor(factorB, "reversal", false),
  ],
  factor_value_correlations: { [`${factorA}|${factorB}`]: 0.2 },
  selection: { selection_id: item.selection_id },
};

function row(
  feature_digest: string,
  metric: string,
  authority: "authoritative" | "derived",
  value: number,
  date: string,
  options: { seriesKind?: string; label?: string; quantile?: number | null; sequence?: number } = {},
) {
  return {
    sequence: options.sequence ?? 0,
    row_id: `${feature_digest.slice(0, 4)}-${metric}-${date}-${options.quantile ?? "x"}`,
    feature_id: feature_digest === factorA ? "momentum" : "reversal",
    feature_digest,
    fold_id: "wf-2024",
    session_date: date,
    train_direction: 1,
    series_kind: options.seriesKind ?? "ic",
    metric,
    authority,
    label_name: options.label ?? item.primary_label,
    quantile: options.quantile ?? null,
    value,
    sample_count: 8,
    window_count: authority === "derived" && metric.startsWith("rolling_") ? 20 : 0,
  };
}

function queryPayload(items: unknown[]) {
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

function rowsFor(url: string) {
  const parsed = new URL(url, "http://workspace.local");
  const params = parsed.searchParams;
  const digest = params.get("feature_digest") ?? factorA;
  const metric = params.get("metric");
  const kind = params.get("series_kind");
  const label = params.get("label_name");
  if (metric === "rolling_rank_ic") {
    return [
      row(digest, metric, "derived", 0.02, "2024-01-02"),
      row(digest, metric, "derived", 0.03, "2024-01-03", { sequence: 1 }),
    ];
  }
  if (kind === "ic" && metric === "rank_ic" && label == null) {
    return [
      row(digest, metric, "authoritative", 0.04, "2024-01-02"),
      row(digest, metric, "authoritative", 0.01, "2024-01-03", { sequence: 1 }),
      row(digest, metric, "authoritative", 0.02, "2024-01-02", { label: item.decay_labels[0], sequence: 2 }),
      row(digest, metric, "authoritative", -0.01, "2024-01-03", { label: item.decay_labels[0], sequence: 3 }),
    ];
  }
  if (metric === "rank_ic") {
    return [
      row(digest, metric, "authoritative", 0.04, "2024-01-02"),
      row(digest, metric, "authoritative", 0.01, "2024-01-03", { sequence: 1 }),
    ];
  }
  if (kind === "quantile" && metric === "nav") {
    return [1, 2, 3].flatMap((quantile, index) => [
      row(digest, metric, "derived", 1 + quantile * 0.01, "2024-01-02", { seriesKind: kind, quantile, sequence: index * 2 }),
      row(digest, metric, "derived", 1 + quantile * 0.02, "2024-01-03", { seriesKind: kind, quantile, sequence: index * 2 + 1 }),
    ]);
  }
  if (kind === "long_short" && metric === "nav") {
    return [
      row(digest, metric, "derived", 1.01, "2024-01-02", { seriesKind: kind }),
      row(digest, metric, "derived", 1.03, "2024-01-03", { seriesKind: kind, sequence: 1 }),
    ];
  }
  if (metric === "one_way_turnover") {
    return [
      row(digest, metric, "authoritative", 0.2, "2024-01-02", { seriesKind: "turnover" }),
      row(digest, metric, "authoritative", 0.3, "2024-01-03", { seriesKind: "turnover", sequence: 1 }),
    ];
  }
  if (metric === "coverage") {
    return [
      row(digest, metric, "authoritative", 0.95, "2024-01-02", { seriesKind: "coverage", label: "" }),
      row(digest, metric, "authoritative", 0.97, "2024-01-03", { seriesKind: "coverage", label: "", sequence: 1 }),
    ];
  }
  throw new Error(`unexpected factor row query: ${url}`);
}

function renderPage(initial = `/factors/${seriesId}?program=${programId}&factor=${factorA}&fold=wf-2024&range=2024-01-02..2024-01-03`) {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <WorkbenchQueryProvider>
        <WorkbenchContextProvider>
          <Routes>
            <Route path="/factors/:seriesId" element={<FactorTearSheetPage />} />
          </Routes>
        </WorkbenchContextProvider>
      </WorkbenchQueryProvider>
    </MemoryRouter>,
  );
}

describe("FactorTearSheetPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v4/factor-series") return json(catalog);
      if (url.endsWith(`/api/v4/factor-series/${seriesId}`)) return json(detail);
      if (url.endsWith(`/api/v4/factor-series/${seriesId}/dimensions`)) return json(dimensions);
      if (url.endsWith(`/api/v4/factor-series/${seriesId}/summary`)) return json(summary);
      if (url.includes(`/api/v4/factor-series/${seriesId}/rows?`)) return json(queryPayload(rowsFor(url)));
      throw new Error(`unexpected request: ${url}`);
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders persisted V4-1 authority classes and frozen A2.6 statistics without browser recomputation", async () => {
    renderPage();

    expect(await screen.findByText("momentum")).toBeInTheDocument();
    expect(screen.getByText(/React groups rows for display only and does not recompute IC, NAV, HAC\/bootstrap or multiple-testing statistics/i)).toBeInTheDocument();
    expect(screen.getByText("IC & persisted rolling IC")).toBeInTheDocument();
    expect(screen.getByText("Decay by frozen horizon")).toBeInTheDocument();
    expect(screen.getByText("Frozen fold RankICIR heatmap")).toBeInTheDocument();
    expect(screen.getByText("Quantile & long-short performance")).toBeInTheDocument();
    expect(screen.getByText("Turnover & coverage")).toBeInTheDocument();
    expect(screen.getByText("2.200")).toBeInTheDocument();
    expect(screen.getByText("0.0300")).toBeInTheDocument();
    expect(screen.getAllByTestId("echarts")).toHaveLength(5);

    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls.map(([value]) => String(value));
      expect(calls.some((value) => value.includes("metric=rank_ic") && value.includes(`feature_digest=${factorA}`))).toBe(true);
      expect(calls.some((value) => value.includes("metric=rolling_rank_ic"))).toBe(true);
      expect(calls.some((value) => value.includes("metric=nav"))).toBe(true);
    });
  });

  it("keeps fold/date context when factor selection changes and sends only semantic filters", async () => {
    renderPage();
    await screen.findByText("IC & persisted rolling IC");

    fireEvent.change(screen.getByLabelText("Factor"), { target: { value: factorB } });

    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls.map(([value]) => String(value));
      const changed = calls.filter((value) => value.includes(`/rows?`) && value.includes(`feature_digest=${factorB}`));
      expect(changed.length).toBeGreaterThan(0);
      expect(changed.every((value) => value.includes("fold_id=wf-2024"))).toBe(true);
      expect(changed.every((value) => value.includes("start=2024-01-02"))).toBe(true);
      expect(changed.every((value) => value.includes("end=2024-01-03"))).toBe(true);
      expect(changed.every((value) => !value.includes("path=") && !value.includes("source="))).toBe(true);
    });
  });

  it("binds date_range changes into bounded factor queries", async () => {
    renderPage();
    await screen.findByText("Selected session evidence");

    fireEvent.change(screen.getByLabelText("Start"), { target: { value: "2024-01-03" } });

    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls.map(([value]) => String(value));
      expect(calls.some((value) => value.includes("/rows?") && value.includes("start=2024-01-03"))).toBe(true);
    });
  });
});

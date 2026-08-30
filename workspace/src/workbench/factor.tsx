import { useEffect, useMemo, useState } from "react";
import ReactECharts from "echarts-for-react";
import { ArrowRight, FlaskConical, ShieldCheck } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  AuthorityBadge,
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageHeader,
  Panel,
  StatusBadge,
} from "../components";
import {
  patchWorkbenchContext,
  useWorkbenchContext,
  workbenchContextSearch,
  type WorkbenchContextKey,
} from "./context";
import { factorTearSheetApi } from "./factorApi";
import type {
  FactorCandidateSummaryV4,
  FactorCorrelationV4,
  FactorHeatmapV4,
  FactorProvenanceV4,
  FactorSeriesDimensionsV4,
  FactorSeriesItemV4,
  FactorSeriesRowV4,
} from "./factorTypes";
import { useWorkbenchQuery } from "./query";
import "./factor.css";

function number(value: number | null | undefined, digits = 3): string {
  return value == null ? "—" : value.toFixed(digits);
}

function percent(value: number | null | undefined, digits = 1): string {
  return value == null ? "—" : `${(value * 100).toFixed(digits)}%`;
}

function dateRange(value: string | undefined): { start?: string; end?: string } {
  if (!value) return {};
  const [start, end] = value.split("..");
  return { start: start?.trim() || undefined, end: end?.trim() || undefined };
}

function rangeValue(start?: string | null, end?: string | null): string | undefined {
  if (!start && !end) return undefined;
  return `${start ?? ""}..${end ?? ""}`;
}

function seriesLabel(item: FactorSeriesItemV4): string {
  return `${item.program_id} · ${item.factor_count} factors · ${item.fold_count} folds`;
}

function LineChart({
  series,
  yName,
  percentAxis = false,
  height = 300,
}: {
  series: Array<{ name: string; rows: FactorSeriesRowV4[]; lineType?: "solid" | "dashed" }>;
  yName: string;
  percentAxis?: boolean;
  height?: number;
}) {
  const dates = useMemo(
    () => [...new Set(series.flatMap((item) => item.rows.map((row) => row.session_date)))].sort(),
    [series],
  );
  const option = useMemo(() => ({
    animation: false,
    grid: { left: 64, right: 24, top: 42, bottom: 54 },
    tooltip: { trigger: "axis", confine: true },
    legend: { data: series.map((item) => item.name) },
    xAxis: { type: "category", data: dates, boundaryGap: false },
    yAxis: {
      type: "value",
      name: yName,
      scale: true,
      axisLabel: percentAxis ? { formatter: (value: number) => `${(value * 100).toFixed(0)}%` } : undefined,
    },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 16, bottom: 8 }],
    series: series.map((item) => {
      const values = new Map(item.rows.map((row) => [row.session_date, row.value]));
      return {
        name: item.name,
        type: "line",
        showSymbol: false,
        connectNulls: false,
        data: dates.map((current) => values.get(current) ?? null),
        lineStyle: item.lineType === "dashed" ? { type: "dashed" } : undefined,
      };
    }),
  }), [dates, percentAxis, series, yName]);
  return <ReactECharts option={option} style={{ height }} />;
}

function HeatmapChart({ heatmap }: { heatmap: FactorHeatmapV4 }) {
  const folds = [...new Set(heatmap.cells.map((cell) => cell.fold_id))];
  const years = [...new Set(heatmap.cells.map((cell) => String(cell.year)))];
  const values = heatmap.cells.map((cell) => cell.value);
  const maxAbs = Math.max(0.01, ...values.map((value) => Math.abs(value)));
  const data = heatmap.cells.map((cell) => [
    years.indexOf(String(cell.year)),
    folds.indexOf(cell.fold_id),
    cell.value,
    cell.observations,
  ]);
  const option = {
    animation: false,
    tooltip: {
      formatter: (params: { data?: unknown[] }) => {
        const raw = params.data ?? [];
        return `${folds[Number(raw[1])]} · ${years[Number(raw[0])]}<br/>mean ${number(Number(raw[2]), 4)} · n=${raw[3]}`;
      },
    },
    grid: { left: 90, right: 36, top: 30, bottom: 54 },
    xAxis: { type: "category", data: years, name: "Year" },
    yAxis: { type: "category", data: folds, name: "Fold" },
    visualMap: { min: -maxAbs, max: maxAbs, calculable: true, orient: "horizontal", left: "center", bottom: 0 },
    series: [{ type: "heatmap", data, label: { show: true, formatter: (params: { data?: unknown[] }) => number(Number(params.data?.[2]), 3) } }],
  };
  return <ReactECharts option={option} style={{ height: 300 }} />;
}

function InferenceForest({ candidates }: { candidates: FactorCandidateSummaryV4[] }) {
  const labels = candidates.map((item) => item.feature_id);
  const data = candidates.map((item, index) => [
    item.block_bootstrap.ci_lower,
    item.block_bootstrap.ci_upper,
    item.metrics.pooled_rank_ic,
    index,
  ]);
  const option = {
    animation: false,
    tooltip: {
      formatter: (params: { data?: number[] }) => {
        const raw = params.data ?? [];
        const candidate = candidates[Number(raw[3])];
        return `${candidate?.feature_id ?? "factor"}<br/>RankIC ${number(raw[2], 4)}<br/>95% CI [${number(raw[0], 4)}, ${number(raw[1], 4)}]`;
      },
    },
    grid: { left: 150, right: 42, top: 24, bottom: 42 },
    xAxis: { type: "value", name: "Pooled RankIC / bootstrap CI", scale: true },
    yAxis: { type: "category", data: labels },
    series: [{
      name: "Bootstrap 95% CI",
      type: "custom",
      data,
      renderItem: (params: { dataIndex: number; coordSys?: { x?: number } }, api: { value: (index: number) => number; coord: (value: number[]) => number[] }) => {
        const low = api.coord([api.value(0), api.value(3)]);
        const high = api.coord([api.value(1), api.value(3)]);
        const point = api.coord([api.value(2), api.value(3)]);
        return {
          type: "group",
          children: [
            { type: "line", shape: { x1: low[0], y1: low[1], x2: high[0], y2: high[1] }, style: { stroke: "currentColor", lineWidth: 2 } },
            { type: "circle", shape: { cx: point[0], cy: point[1], r: 4 }, style: { fill: "currentColor" } },
          ],
        };
      },
    }],
  };
  return <ReactECharts option={option} style={{ height: Math.max(280, candidates.length * 42 + 80) }} />;
}

function MultiplicityHeatmap({ candidates }: { candidates: FactorCandidateSummaryV4[] }) {
  const columns = ["HAC raw", "Holm", "BH q", "Bootstrap"];
  const data = candidates.flatMap((item, rowIndex) => [
    [0, rowIndex, item.hac.raw_pvalue],
    [1, rowIndex, item.hac.holm_adjusted_pvalue],
    [2, rowIndex, item.hac.bh_qvalue],
    [3, rowIndex, item.block_bootstrap.pvalue],
  ]);
  const option = {
    animation: false,
    tooltip: { formatter: (params: { data?: unknown[] }) => `${candidates[Number(params.data?.[1])]?.feature_id}<br/>${columns[Number(params.data?.[0])]}: ${number(Number(params.data?.[2]), 4)}` },
    grid: { left: 150, right: 28, top: 24, bottom: 50 },
    xAxis: { type: "category", data: columns },
    yAxis: { type: "category", data: candidates.map((item) => item.feature_id) },
    visualMap: { min: 0, max: 1, calculable: true, orient: "horizontal", left: "center", bottom: 0 },
    series: [{ type: "heatmap", data, label: { show: true, formatter: (params: { data?: unknown[] }) => number(Number(params.data?.[2]), 3) } }],
  };
  return <ReactECharts option={option} style={{ height: Math.max(300, candidates.length * 42 + 90) }} />;
}

function CorrelationHeatmap({ correlation }: { correlation: FactorCorrelationV4 }) {
  const order = correlation.cluster_order;
  const data = correlation.cells.map((cell) => [
    order.indexOf(cell.right),
    order.indexOf(cell.left),
    cell.value,
  ]);
  const option = {
    animation: false,
    tooltip: { formatter: (params: { data?: unknown[] }) => `${order[Number(params.data?.[1])]}<br/>${order[Number(params.data?.[0])]}: ${number(Number(params.data?.[2]), 3)}` },
    grid: { left: 130, right: 38, top: 24, bottom: 80 },
    xAxis: { type: "category", data: order, axisLabel: { rotate: 35, formatter: (value: string) => `${value.slice(0, 10)}…` } },
    yAxis: { type: "category", data: order, axisLabel: { formatter: (value: string) => `${value.slice(0, 10)}…` } },
    visualMap: { min: -1, max: 1, calculable: true, orient: "horizontal", left: "center", bottom: 0 },
    series: [{ type: "heatmap", data }],
  };
  return <ReactECharts option={option} style={{ height: Math.max(330, order.length * 52 + 120) }} />;
}

function ProvenanceLane({ provenance }: { provenance: FactorProvenanceV4 }) {
  return (
    <div className="factor-provenance-list">
      {provenance.items.map((item) => (
        <article key={item.feature_digest} className="factor-provenance-card">
          <div className="factor-provenance-index">{item.ordinal + 1}</div>
          <div>
            <div className="factor-provenance-title">
              <strong>{item.feature_id}</strong>
              <StatusBadge value={item.selected ? "selected" : item.gate_passed ? "gate-pass" : "rejected"} tone={item.selected ? "good" : item.gate_passed ? "neutral" : "bad"} />
            </div>
            <p>{item.hypothesis || "No frozen hypothesis text."}</p>
            <span className="mono subtle">{item.generator_id || "generator unavailable"} · lookback {item.lookback}</span>
            {item.gate_reason_codes.length ? <div className="factor-reason-list">{item.gate_reason_codes.map((reason) => <code key={reason}>{reason}</code>)}</div> : null}
          </div>
        </article>
      ))}
    </div>
  );
}

export function FactorTearSheetIndexPage() {
  const navigate = useNavigate();
  const query = useWorkbenchQuery({ key: ["factor-series-v4"], queryFn: factorTearSheetApi.catalog });
  if (query.isPending) return <LoadingState />;
  if (query.error) return <ErrorState error={query.error} />;
  const catalog = query.data;
  if (!catalog?.items.length) {
    return (
      <div className="page">
        <PageHeader eyebrow="V4.3 · Factors" title="Factor Tear Sheet" description="No verified V4-1 FactorSeries is configured." />
        <EmptyState title="No FactorSeriesEvidence" detail="Materialize V4-1 beside a frozen A2.6 report under a configured report root, then restart the Evidence Plane." />
      </div>
    );
  }
  return (
    <div className="page factor-tearsheet">
      <PageHeader eyebrow="V4.3 · Factors" title="Factor Tear Sheet" description="Verified V4-1 period evidence + frozen A2.6 inference and multiplicity summaries." />
      <div className="factor-series-grid">
        {catalog.items.map((item) => (
          <button key={item.series_id} type="button" className="factor-series-card" onClick={() => navigate(`/factors/${encodeURIComponent(item.series_id)}`)}>
            <FlaskConical size={19} />
            <div><strong>{item.program_id}</strong><span>{item.factor_count} factors · {item.fold_count} folds · {item.session_count} sessions</span><code>{item.series_id}</code></div>
            <ArrowRight size={16} />
          </button>
        ))}
      </div>
    </div>
  );
}

export function FactorTearSheetPage() {
  const { seriesId: encodedSeriesId } = useParams();
  const navigate = useNavigate();
  const { context, select } = useWorkbenchContext();
  const seriesId = encodedSeriesId ? decodeURIComponent(encodedSeriesId) : "";
  const [labelName, setLabelName] = useState<string>("");

  const catalogQuery = useWorkbenchQuery({ key: ["factor-series-v4"], queryFn: factorTearSheetApi.catalog });
  const detailQuery = useWorkbenchQuery({ key: ["factor-series-detail-v4", seriesId], queryFn: () => factorTearSheetApi.detail(seriesId), enabled: Boolean(seriesId) });
  const dimensionsQuery = useWorkbenchQuery({ key: ["factor-series-dimensions-v4", seriesId], queryFn: () => factorTearSheetApi.dimensions(seriesId), enabled: Boolean(seriesId) });
  const dimensions = dimensionsQuery.data;
  const activeFactor = context.factor_id && dimensions?.factors.some((item) => item.feature_digest === context.factor_id)
    ? context.factor_id
    : dimensions?.factors.find((item) => item.selected)?.feature_digest ?? dimensions?.factors[0]?.feature_digest;
  const foldId = context.fold_id && dimensions?.folds.includes(context.fold_id) ? context.fold_id : undefined;
  const range = dateRange(context.date_range);
  const start = range.start ?? dimensions?.start_date ?? undefined;
  const end = range.end ?? dimensions?.end_date ?? undefined;
  const activeLabel = labelName || dimensions?.primary_label || "";

  useEffect(() => {
    if (!dimensions || !seriesId) return;
    const patch: Partial<Record<WorkbenchContextKey, string | null | undefined>> = {};
    if (context.program_id !== dimensions.program_id) patch.program_id = dimensions.program_id;
    if (activeFactor && context.factor_id !== activeFactor) patch.factor_id = activeFactor;
    if (Object.keys(patch).length) select(patch, "factor_selected", { replace: true });
  }, [activeFactor, context.factor_id, context.program_id, dimensions, select, seriesId]);

  useEffect(() => {
    if (dimensions && !labelName) setLabelName(dimensions.primary_label);
  }, [dimensions, labelName]);

  const summaryQuery = useWorkbenchQuery({ key: ["factor-summary-v4", seriesId], queryFn: () => factorTearSheetApi.summary(seriesId), enabled: Boolean(seriesId) });
  const correlationQuery = useWorkbenchQuery({ key: ["factor-correlation-v4", seriesId], queryFn: () => factorTearSheetApi.correlations(seriesId), enabled: Boolean(seriesId) });
  const provenanceQuery = useWorkbenchQuery({ key: ["factor-provenance-v4", seriesId], queryFn: () => factorTearSheetApi.provenance(seriesId), enabled: Boolean(seriesId) });
  const heatmapQuery = useWorkbenchQuery({ key: ["factor-heatmap-v4", seriesId, activeFactor, activeLabel], queryFn: () => factorTearSheetApi.heatmap(seriesId, { featureDigest: activeFactor, labelName: activeLabel, metric: "rank_ic" }), enabled: Boolean(seriesId && activeFactor && activeLabel) });

  const rowFilters = { featureDigest: activeFactor, foldId, start, end, limit: 5000 };
  const icQuery = useWorkbenchQuery({ key: ["factor-ic-v4", seriesId, activeFactor, foldId, start, end, activeLabel], queryFn: () => factorTearSheetApi.rows(seriesId, { ...rowFilters, seriesKind: "ic", metric: "rank_ic", labelName: activeLabel }), enabled: Boolean(seriesId && activeFactor && activeLabel) });
  const rollingQuery = useWorkbenchQuery({ key: ["factor-rolling-v4", seriesId, activeFactor, foldId, start, end, activeLabel], queryFn: () => factorTearSheetApi.rows(seriesId, { ...rowFilters, seriesKind: "ic", metric: "rolling_rank_ic", labelName: activeLabel }), enabled: Boolean(seriesId && activeFactor && activeLabel) });
  const turnoverQuery = useWorkbenchQuery({ key: ["factor-turnover-v4", seriesId, activeFactor, foldId, start, end], queryFn: () => factorTearSheetApi.rows(seriesId, { ...rowFilters, seriesKind: "turnover", metric: "one_way_turnover", labelName: dimensions?.primary_label }), enabled: Boolean(seriesId && activeFactor && dimensions?.primary_label) });
  const coverageQuery = useWorkbenchQuery({ key: ["factor-coverage-v4", seriesId, activeFactor, foldId, start, end], queryFn: () => factorTearSheetApi.rows(seriesId, { ...rowFilters, seriesKind: "coverage", metric: "coverage" }), enabled: Boolean(seriesId && activeFactor) });

  const decayQuery = useWorkbenchQuery({
    key: ["factor-decay-v4", seriesId, activeFactor, foldId, start, end, dimensions?.labels.join("|")],
    queryFn: async () => Promise.all((dimensions?.labels ?? []).map(async (label) => ({ label, data: await factorTearSheetApi.rows(seriesId, { ...rowFilters, seriesKind: "ic", metric: "rank_ic", labelName: label }) }))),
    enabled: Boolean(seriesId && activeFactor && dimensions?.labels.length),
  });

  const navQuery = useWorkbenchQuery({
    key: ["factor-nav-v4", seriesId, activeFactor, foldId, start, end, dimensions?.quantiles.join("|")],
    queryFn: async () => {
      const quantiles = await Promise.all((dimensions?.quantiles ?? []).map(async (quantile) => ({ name: `Q${quantile}`, data: await factorTearSheetApi.rows(seriesId, { ...rowFilters, seriesKind: "quantile", metric: "nav", labelName: dimensions?.primary_label, quantile }) })));
      const longShort = await factorTearSheetApi.rows(seriesId, { ...rowFilters, seriesKind: "long_short", metric: "nav", labelName: dimensions?.primary_label });
      return [...quantiles, { name: "Long-short", data: longShort }];
    },
    enabled: Boolean(seriesId && activeFactor && dimensions?.primary_label && dimensions?.quantiles.length),
  });

  if (catalogQuery.isPending || detailQuery.isPending || dimensionsQuery.isPending) return <LoadingState />;
  const topError = catalogQuery.error ?? detailQuery.error ?? dimensionsQuery.error;
  if (topError) return <ErrorState error={topError} />;
  if (!seriesId || !detailQuery.data || !dimensions) return <ErrorState error={new Error("factor series not found")} />;

  const summary = summaryQuery.data;
  const candidate = summary?.items.find((item) => item.feature_digest === activeFactor);
  const activeFactorMeta = dimensions.factors.find((item) => item.feature_digest === activeFactor);
  const chartError = icQuery.error ?? rollingQuery.error ?? turnoverQuery.error ?? coverageQuery.error ?? decayQuery.error ?? navQuery.error ?? heatmapQuery.error ?? correlationQuery.error ?? provenanceQuery.error ?? summaryQuery.error;
  if (chartError) return <ErrorState error={chartError} />;

  const chooseSeries = (nextSeries: string) => {
    const item = catalogQuery.data?.items.find((value) => value.series_id === nextSeries);
    if (!item) return;
    const nextContext = patchWorkbenchContext(context, { program_id: item.program_id, factor_id: null, fold_id: null, date_range: null, session_date: null });
    navigate(`/factors/${encodeURIComponent(item.series_id)}${workbenchContextSearch(nextContext)}`);
  };

  const chooseFactor = (digest: string) => select({ factor_id: digest }, "factor_selected");
  const chooseFold = (fold: string) => select({ fold_id: fold || null }, "factor_selected");
  const chooseRange = (nextStart: string | undefined, nextEnd: string | undefined) => select({ date_range: rangeValue(nextStart, nextEnd) }, "date_range_selected");

  const allCandidates = summary?.items ?? [];
  const icRows = icQuery.data?.items ?? [];
  const rollingRows = rollingQuery.data?.items ?? [];
  const turnoverRows = turnoverQuery.data?.items ?? [];
  const coverageRows = coverageQuery.data?.items ?? [];

  return (
    <div className="page factor-tearsheet">
      <PageHeader eyebrow="V4.3 · Factor Tear Sheet" title={activeFactorMeta?.feature_id ?? "Factor"} description={seriesId}>
        <Link className="button secondary" to={`/program/${encodeURIComponent(dimensions.program_id)}${workbenchContextSearch(context)}`}>Open A2.6 cockpit <ArrowRight size={15} /></Link>
      </PageHeader>

      <div className="factor-authority-banner">
        <ShieldCheck size={18} />
        <div><strong>Verified V4-1 period rows + frozen A2.6 inference</strong><span>No factor statistics are reconstructed in React. Fold/year means and correlation ordering are explicitly derived server-side presentation projections.</span></div>
        <AuthorityBadge value="authoritative + derived" />
      </div>

      <div className="factor-toolbar">
        <label><span>Series</span><select value={seriesId} onChange={(event) => chooseSeries(event.target.value)}>{catalogQuery.data?.items.map((item) => <option key={item.series_id} value={item.series_id}>{seriesLabel(item)}</option>)}</select></label>
        <label><span>Factor</span><select value={activeFactor ?? ""} onChange={(event) => chooseFactor(event.target.value)}>{dimensions.factors.map((item) => <option key={item.feature_digest} value={item.feature_digest}>{item.feature_id}{item.selected ? " · selected" : ""}</option>)}</select></label>
        <label><span>Fold</span><select value={foldId ?? ""} onChange={(event) => chooseFold(event.target.value)}><option value="">All folds</option>{dimensions.folds.map((fold) => <option key={fold} value={fold}>{fold}</option>)}</select></label>
        <label><span>Label / horizon</span><select value={activeLabel} onChange={(event) => setLabelName(event.target.value)}>{dimensions.labels.map((label) => <option key={label} value={label}>{label}{label === dimensions.primary_label ? " · primary" : ""}</option>)}</select></label>
        <label><span>Start</span><input type="date" min={dimensions.start_date ?? undefined} max={dimensions.end_date ?? undefined} value={start ?? ""} onChange={(event) => chooseRange(event.target.value || undefined, end)} /></label>
        <label><span>End</span><input type="date" min={dimensions.start_date ?? undefined} max={dimensions.end_date ?? undefined} value={end ?? ""} onChange={(event) => chooseRange(start, event.target.value || undefined)} /></label>
      </div>

      {candidate ? (
        <div className="metric-grid six">
          <MetricCard label="Gate" value={candidate.gate.passed ? "PASS" : "REJECT"} detail={candidate.selected ? "selected" : candidate.gate.reason_codes[0] ?? "not selected"} />
          <MetricCard label="Pooled RankICIR" value={number(candidate.metrics.pooled_rank_icir)} detail={`RankIC ${number(candidate.metrics.pooled_rank_ic, 4)}`} />
          <MetricCard label="Worst-fold ICIR" value={number(candidate.metrics.worst_fold_rank_icir)} detail={`positive ${percent(candidate.metrics.positive_fold_ratio)}`} />
          <MetricCard label="Coverage min" value={percent(candidate.metrics.coverage_min)} detail={`mean ${percent(candidate.metrics.coverage_mean)}`} />
          <MetricCard label="Turnover" value={percent(candidate.metrics.mean_one_way_turnover)} detail={`monotonicity ${number(candidate.metrics.quantile_monotonicity)}`} />
          <MetricCard label="Holm / BH q" value={`${number(candidate.hac.holm_adjusted_pvalue, 4)} / ${number(candidate.hac.bh_qvalue, 4)}`} detail={`bootstrap p ${number(candidate.block_bootstrap.pvalue, 4)}`} />
        </div>
      ) : null}

      <div className="two-column">
        <Panel title="IC & rolling IC" subtitle="RankIC is authoritative V4-1 period evidence; rolling RankIC is the V4-1 persisted derived window series.">
          <LineChart series={[{ name: "RankIC", rows: icRows }, { name: `Rolling ${dimensions.rolling_window}`, rows: rollingRows, lineType: "dashed" }]} yName="IC" />
        </Panel>
        <Panel title="IC decay" subtitle="Each horizon is frozen V4-1 oriented RankIC; no horizon statistic is recomputed in React.">
          <LineChart series={(decayQuery.data ?? []).map((item) => ({ name: item.label, rows: item.data.items }))} yName="RankIC" />
        </Panel>
      </div>

      <div className="two-column">
        <Panel title="Quantile & long-short NAV" subtitle="Persisted V4-1 derived NAV transforms over authoritative period returns.">
          <LineChart series={(navQuery.data ?? []).map((item) => ({ name: item.name, rows: item.data.items }))} yName="NAV" />
        </Panel>
        <Panel title="Turnover & coverage" subtitle="Authoritative period diagnostics from V4-1.">
          <LineChart series={[{ name: "One-way turnover", rows: turnoverRows }, { name: "Coverage", rows: coverageRows, lineType: "dashed" }]} yName="Ratio" percentAxis />
        </Panel>
      </div>

      <Panel title="Fold / year RankIC heatmap" subtitle="DERIVED PRESENTATION: arithmetic mean of authoritative V4-1 period RankIC grouped on the server.">
        {heatmapQuery.data?.cells.length ? <HeatmapChart heatmap={heatmapQuery.data} /> : <EmptyState title="No heatmap cells" detail="No valid period IC observations match the selected factor/horizon." />}
      </Panel>

      <div className="two-column">
        <Panel title="HAC / block-bootstrap inference forest" subtitle="Authoritative frozen A2.6 pooled RankIC and block-bootstrap 95% confidence intervals.">
          {allCandidates.length ? <InferenceForest candidates={allCandidates} /> : <EmptyState title="No frozen inference" detail="A2.6 summary contains no candidates." />}
        </Panel>
        <Panel title="Holm / BH multiplicity matrix" subtitle="Authoritative frozen A2.6 p-values and multiple-testing adjustments.">
          {allCandidates.length ? <MultiplicityHeatmap candidates={allCandidates} /> : <EmptyState title="No multiplicity evidence" detail="A2.6 summary contains no candidates." />}
        </Panel>
      </div>

      <Panel title="Factor correlation cluster" subtitle="Correlation values are authoritative frozen A2.6 summaries; hierarchical ordering is a server-side derived presentation transform.">
        {correlationQuery.data ? <CorrelationHeatmap correlation={correlationQuery.data} /> : <LoadingState />}
      </Panel>

      <Panel title="Candidate provenance" subtitle="Frozen A2.6 denominator identity/provenance only. The denominator order is not presented as Agent generation chronology.">
        {provenanceQuery.data ? <><div className="derived-note">AGENT CHRONOLOGY NOT PERSISTED · NO TIMELINE INFERENCE</div><p className="subtle factor-provenance-note">{provenanceQuery.data.chronology_note}</p><ProvenanceLane provenance={provenanceQuery.data} /></> : <LoadingState />}
      </Panel>
    </div>
  );
}

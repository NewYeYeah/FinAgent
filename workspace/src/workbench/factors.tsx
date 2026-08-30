import { useEffect, useMemo } from "react";
import ReactECharts from "echarts-for-react";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { workspaceApi } from "../api";
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
import type {
  FactorSeriesRowV4,
  FrozenFactorSummaryItemV4,
} from "./factorTypes";
import { useWorkbenchQuery } from "./query";
import "./factors.css";

function number(value: number | null | undefined, digits = 3): string {
  return value == null ? "—" : value.toFixed(digits);
}

function percent(value: number | null | undefined, digits = 2): string {
  return value == null ? "—" : `${(value * 100).toFixed(digits)}%`;
}

function dateRange(value: string | undefined): { start?: string; end?: string } {
  if (!value) return {};
  const [start, end] = value.split("..");
  return {
    start: start?.trim() || undefined,
    end: end?.trim() || undefined,
  };
}

function rangeValue(start?: string | null, end?: string | null): string | undefined {
  if (!start && !end) return undefined;
  return `${start ?? ""}..${end ?? ""}`;
}

function eventDate(params: unknown): string | null {
  if (!params || typeof params !== "object") return null;
  const raw = params as { data?: unknown; name?: unknown };
  if (raw.data && typeof raw.data === "object") {
    const data = raw.data as { session_date?: unknown; value?: unknown };
    if (typeof data.session_date === "string") return data.session_date;
    if (Array.isArray(data.value) && typeof data.value[0] === "string") {
      return data.value[0];
    }
  }
  return typeof raw.name === "string" ? raw.name : null;
}

function lineData(rows: FactorSeriesRowV4[]) {
  return rows.map((row) => ({
    value: [row.session_date, row.value],
    session_date: row.session_date,
    authority: row.authority,
    sample_count: row.sample_count,
  }));
}

function FactorIcChart({
  rankRows,
  rollingRows,
  selectedSession,
  onSession,
}: {
  rankRows: FactorSeriesRowV4[];
  rollingRows: FactorSeriesRowV4[];
  selectedSession?: string;
  onSession: (session: string) => void;
}) {
  const option = useMemo(() => ({
    animation: false,
    grid: { left: 58, right: 24, top: 52, bottom: 52 },
    legend: { data: ["RankIC · authoritative", "Rolling RankIC · derived"] },
    tooltip: { trigger: "axis", confine: true },
    xAxis: { type: "time" },
    yAxis: { type: "value", name: "IC", scale: true },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
    series: [
      {
        name: "RankIC · authoritative",
        type: "line",
        showSymbol: false,
        data: lineData(rankRows),
        lineStyle: { width: 1 },
      },
      {
        name: "Rolling RankIC · derived",
        type: "line",
        showSymbol: false,
        data: lineData(rollingRows),
        lineStyle: { width: 2, type: "dashed" },
        markLine: selectedSession
          ? { silent: true, symbol: "none", data: [{ xAxis: selectedSession }] }
          : undefined,
      },
    ],
  }), [rankRows, rollingRows, selectedSession]);
  return (
    <ReactECharts
      option={option}
      style={{ height: 350 }}
      onEvents={{
        click: (params: unknown) => {
          const session = eventDate(params);
          if (session) onSession(session);
        },
      }}
    />
  );
}

function DecayChart({ rows }: { rows: FactorSeriesRowV4[] }) {
  const labels = useMemo(
    () => [...new Set(rows.map((row) => row.label_name))],
    [rows],
  );
  const option = useMemo(() => ({
    animation: false,
    grid: { left: 58, right: 24, top: 52, bottom: 48 },
    legend: { data: labels },
    tooltip: { trigger: "axis", confine: true },
    xAxis: { type: "time" },
    yAxis: { type: "value", name: "RankIC", scale: true },
    series: labels.map((label) => ({
      name: label,
      type: "line",
      showSymbol: false,
      data: lineData(rows.filter((row) => row.label_name === label)),
    })),
  }), [labels, rows]);
  return <ReactECharts option={option} style={{ height: 300 }} />;
}

function PerformanceChart({
  quantileRows,
  longShortRows,
}: {
  quantileRows: FactorSeriesRowV4[];
  longShortRows: FactorSeriesRowV4[];
}) {
  const quantiles = useMemo(
    () => [...new Set(quantileRows.map((row) => row.quantile).filter((value): value is number => value != null))].sort((a, b) => a - b),
    [quantileRows],
  );
  const option = useMemo(() => ({
    animation: false,
    grid: { left: 58, right: 24, top: 52, bottom: 48 },
    legend: { data: [...quantiles.map((value) => `Q${value}`), "Long-short"] },
    tooltip: { trigger: "axis", confine: true },
    xAxis: { type: "time" },
    yAxis: { type: "value", name: "Persisted NAV", scale: true },
    series: [
      ...quantiles.map((quantile) => ({
        name: `Q${quantile}`,
        type: "line",
        showSymbol: false,
        data: lineData(quantileRows.filter((row) => row.quantile === quantile)),
      })),
      {
        name: "Long-short",
        type: "line",
        showSymbol: false,
        data: lineData(longShortRows),
        lineStyle: { width: 2 },
      },
    ],
  }), [longShortRows, quantileRows, quantiles]);
  return <ReactECharts option={option} style={{ height: 320 }} />;
}

function TurnoverCoverageChart({
  turnoverRows,
  coverageRows,
}: {
  turnoverRows: FactorSeriesRowV4[];
  coverageRows: FactorSeriesRowV4[];
}) {
  const option = useMemo(() => ({
    animation: false,
    grid: { left: 60, right: 60, top: 52, bottom: 48 },
    legend: { data: ["One-way turnover", "Coverage"] },
    tooltip: { trigger: "axis", confine: true },
    xAxis: { type: "time" },
    yAxis: [
      { type: "value", name: "Turnover", min: 0 },
      { type: "value", name: "Coverage", min: 0, max: 1, axisLabel: { formatter: (value: number) => `${(value * 100).toFixed(0)}%` } },
    ],
    series: [
      {
        name: "One-way turnover",
        type: "line",
        showSymbol: false,
        data: lineData(turnoverRows),
      },
      {
        name: "Coverage",
        type: "line",
        yAxisIndex: 1,
        showSymbol: false,
        data: lineData(coverageRows),
      },
    ],
  }), [coverageRows, turnoverRows]);
  return <ReactECharts option={option} style={{ height: 300 }} />;
}

function FoldHeatmap({ item }: { item: FrozenFactorSummaryItemV4 }) {
  const folds = item.folds;
  const data = folds.flatMap((fold, index) =>
    typeof fold.test_rank_icir === "number" ? [[index, 0, fold.test_rank_icir]] : [],
  );
  const values = data.map((entry) => Number(entry[2]));
  const absMax = Math.max(0.01, ...values.map((value) => Math.abs(value)));
  const option = {
    animation: false,
    grid: { left: 86, right: 30, top: 28, bottom: 42 },
    tooltip: { formatter: (params: { value?: unknown }) => {
      const value = Array.isArray(params.value) ? params.value : [];
      const fold = folds[Number(value[0])];
      return `${fold?.fold_id ?? "fold"}<br/>Frozen test RankICIR: ${number(Number(value[2]))}`;
    } },
    xAxis: { type: "category", data: folds.map((fold) => fold.fold_id), splitArea: { show: true } },
    yAxis: { type: "category", data: ["test RankICIR"], splitArea: { show: true } },
    visualMap: { min: -absMax, max: absMax, calculable: false, orient: "horizontal", left: "center", bottom: 0 },
    series: [{ name: "Frozen fold RankICIR", type: "heatmap", data, label: { show: true, formatter: (params: { value?: unknown }) => {
      const value = Array.isArray(params.value) ? params.value : [];
      return number(Number(value[2]), 2);
    } } }],
  };
  return <ReactECharts option={option} style={{ height: 210 }} />;
}

function FrozenStatistics({ item }: { item: FrozenFactorSummaryItemV4 }) {
  const stats = item.statistics;
  return (
    <div className="metric-grid six">
      <MetricCard label="Pooled RankICIR" value={number(stats.pooled_rank_icir)} />
      <MetricCard label="Mean fold L/S Sharpe" value={number(stats.mean_fold_long_short_sharpe)} />
      <MetricCard label="HAC t-stat" value={number(stats.hac_tstat)} />
      <MetricCard label="Bootstrap p" value={number(stats.bootstrap_pvalue, 4)} detail={`CI ${number(stats.bootstrap_ci_lower, 4)} … ${number(stats.bootstrap_ci_upper, 4)}`} />
      <MetricCard label="Holm adjusted p" value={number(stats.holm_adjusted_pvalue, 4)} />
      <MetricCard label="BH q-value" value={number(stats.bh_qvalue, 4)} />
    </div>
  );
}

function SessionInspector({
  session,
  rankRows,
  rollingRows,
  turnoverRows,
  coverageRows,
}: {
  session?: string;
  rankRows: FactorSeriesRowV4[];
  rollingRows: FactorSeriesRowV4[];
  turnoverRows: FactorSeriesRowV4[];
  coverageRows: FactorSeriesRowV4[];
}) {
  if (!session) {
    return <EmptyState title="No session selected" detail="Select an IC point to bind session_date into WorkbenchContext." />;
  }
  const rank = rankRows.find((row) => row.session_date === session);
  const rolling = rollingRows.find((row) => row.session_date === session);
  const turnover = turnoverRows.find((row) => row.session_date === session);
  const coverage = coverageRows.find((row) => row.session_date === session);
  return (
    <div className="factor-session-grid">
      <MetricCard label="Session" value={session} detail={rank?.fold_id ?? rolling?.fold_id ?? "—"} />
      <MetricCard label="RankIC" value={number(rank?.value)} detail="authoritative V4-1 row" />
      <MetricCard label="Rolling RankIC" value={number(rolling?.value)} detail={rolling ? `derived · window ${rolling.window_count}` : "no persisted row"} />
      <MetricCard label="Turnover" value={percent(turnover?.value)} detail="authoritative V4-1 row" />
      <MetricCard label="Coverage" value={percent(coverage?.value)} detail="authoritative V4-1 row" />
    </div>
  );
}

export function FactorTearSheetPage() {
  const { seriesId: encodedSeriesId } = useParams();
  const navigate = useNavigate();
  const { context, select } = useWorkbenchContext();
  const routeSeriesId = encodedSeriesId ? decodeURIComponent(encodedSeriesId) : undefined;

  const catalogQuery = useWorkbenchQuery({
    key: ["factor-series-v4"],
    queryFn: workspaceApi.factorSeriesV4,
  });
  const catalog = catalogQuery.data;
  const contextSeries = context.program_id
    ? catalog?.items.find((item) => item.program_id === context.program_id)
    : undefined;
  const activeSeries = routeSeriesId
    ? catalog?.items.find((item) => item.series_id === routeSeriesId)
    : contextSeries ?? catalog?.items[0];
  const seriesId = activeSeries?.series_id ?? routeSeriesId ?? "";

  const detailQuery = useWorkbenchQuery({
    key: ["factor-series-detail-v4", seriesId],
    queryFn: () => workspaceApi.factorSeriesDetailV4(seriesId),
    enabled: Boolean(seriesId),
  });
  const dimensionsQuery = useWorkbenchQuery({
    key: ["factor-series-dimensions-v4", seriesId],
    queryFn: () => workspaceApi.factorSeriesDimensionsV4(seriesId),
    enabled: Boolean(seriesId),
  });
  const summaryQuery = useWorkbenchQuery({
    key: ["factor-series-summary-v4", seriesId],
    queryFn: () => workspaceApi.factorSeriesSummaryV4(seriesId),
    enabled: Boolean(seriesId),
  });
  const dimensions = dimensionsQuery.data;
  const contextFactor = dimensions?.factors.find((item) => item.feature_digest === context.factor_id);
  const defaultFactor = dimensions?.factors.find((item) => item.selected) ?? dimensions?.factors[0];
  const factor = contextFactor ?? defaultFactor;
  const factorDigest = factor?.feature_digest;
  const foldId = context.fold_id && dimensions?.folds.includes(context.fold_id)
    ? context.fold_id
    : undefined;
  const range = dateRange(context.date_range);
  const start = range.start ?? dimensions?.start_date ?? undefined;
  const end = range.end ?? dimensions?.end_date ?? undefined;

  useEffect(() => {
    if (!activeSeries) return;
    const patch: Partial<Record<WorkbenchContextKey, string | null | undefined>> = {};
    if (context.program_id !== activeSeries.program_id) patch.program_id = activeSeries.program_id;
    if (factorDigest && context.factor_id !== factorDigest) patch.factor_id = factorDigest;
    if (Object.keys(patch).length) select(patch, "factor_selected", { replace: true });
  }, [activeSeries, context.factor_id, context.program_id, factorDigest, select]);

  const commonFilters = {
    featureDigest: factorDigest,
    foldId,
    start,
    end,
    limit: 5000,
  };
  const rankQuery = useWorkbenchQuery({
    key: ["factor-rank-ic-v4", seriesId, factorDigest, foldId, start, end],
    queryFn: () => workspaceApi.factorSeriesRowsV4(seriesId, {
      ...commonFilters,
      seriesKind: "ic",
      metric: "rank_ic",
      labelName: dimensions?.primary_label,
    }),
    enabled: Boolean(seriesId && factorDigest && dimensions?.primary_label),
  });
  const rollingQuery = useWorkbenchQuery({
    key: ["factor-rolling-rank-ic-v4", seriesId, factorDigest, foldId, start, end],
    queryFn: () => workspaceApi.factorSeriesRowsV4(seriesId, {
      ...commonFilters,
      seriesKind: "ic",
      metric: "rolling_rank_ic",
      labelName: dimensions?.primary_label,
    }),
    enabled: Boolean(seriesId && factorDigest && dimensions?.primary_label),
  });
  const decayQuery = useWorkbenchQuery({
    key: ["factor-decay-v4", seriesId, factorDigest, foldId, start, end],
    queryFn: () => workspaceApi.factorSeriesRowsV4(seriesId, {
      ...commonFilters,
      seriesKind: "ic",
      metric: "rank_ic",
    }),
    enabled: Boolean(seriesId && factorDigest),
  });
  const quantileQuery = useWorkbenchQuery({
    key: ["factor-quantile-nav-v4", seriesId, factorDigest, foldId, start, end],
    queryFn: () => workspaceApi.factorSeriesRowsV4(seriesId, {
      ...commonFilters,
      seriesKind: "quantile",
      metric: "nav",
      labelName: dimensions?.primary_label,
    }),
    enabled: Boolean(seriesId && factorDigest && dimensions?.primary_label),
  });
  const longShortQuery = useWorkbenchQuery({
    key: ["factor-long-short-nav-v4", seriesId, factorDigest, foldId, start, end],
    queryFn: () => workspaceApi.factorSeriesRowsV4(seriesId, {
      ...commonFilters,
      seriesKind: "long_short",
      metric: "nav",
      labelName: dimensions?.primary_label,
    }),
    enabled: Boolean(seriesId && factorDigest && dimensions?.primary_label),
  });
  const turnoverQuery = useWorkbenchQuery({
    key: ["factor-turnover-v4", seriesId, factorDigest, foldId, start, end],
    queryFn: () => workspaceApi.factorSeriesRowsV4(seriesId, {
      ...commonFilters,
      seriesKind: "turnover",
      metric: "one_way_turnover",
      labelName: dimensions?.primary_label,
    }),
    enabled: Boolean(seriesId && factorDigest && dimensions?.primary_label),
  });
  const coverageQuery = useWorkbenchQuery({
    key: ["factor-coverage-v4", seriesId, factorDigest, foldId, start, end],
    queryFn: () => workspaceApi.factorSeriesRowsV4(seriesId, {
      ...commonFilters,
      seriesKind: "coverage",
      metric: "coverage",
    }),
    enabled: Boolean(seriesId && factorDigest),
  });

  const rankRows = rankQuery.data?.items ?? [];
  const rollingRows = rollingQuery.data?.items ?? [];
  const decayRows = decayQuery.data?.items ?? [];
  const quantileRows = quantileQuery.data?.items ?? [];
  const longShortRows = longShortQuery.data?.items ?? [];
  const turnoverRows = turnoverQuery.data?.items ?? [];
  const coverageRows = coverageQuery.data?.items ?? [];
  const summaryItem = summaryQuery.data?.items.find((item) => item.feature_digest === factorDigest);
  const selectedSession = useMemo(() => {
    if (context.session_date && rankRows.some((row) => row.session_date === context.session_date)) {
      return context.session_date;
    }
    return rankRows[rankRows.length - 1]?.session_date;
  }, [context.session_date, rankRows]);

  if (catalogQuery.isPending) return <LoadingState />;
  if (catalogQuery.error) return <ErrorState error={catalogQuery.error} />;
  if (!catalog?.items.length) {
    return (
      <div className="page">
        <PageHeader eyebrow="V4.3A · Factors" title="Factor Tear Sheet" description="No verified V4-1 FactorSeriesEvidence is configured." />
        <EmptyState title="No FactorSeriesEvidence" detail="Materialize V4-1 beside a frozen A2.6 report under a configured Workspace report root, then restart the Evidence Plane." />
      </div>
    );
  }
  const identityError = detailQuery.error ?? dimensionsQuery.error ?? summaryQuery.error;
  if (!activeSeries || identityError) {
    return <ErrorState error={identityError ?? new Error("factor series not found")} />;
  }
  if (detailQuery.isPending || dimensionsQuery.isPending || summaryQuery.isPending) return <LoadingState />;
  if (!factor || !factorDigest || !summaryItem) {
    return <ErrorState error={new Error("selected factor is absent from verified V4-1/A2.6 denominator")} />;
  }

  const rowError = rankQuery.error ?? rollingQuery.error ?? decayQuery.error ?? quantileQuery.error
    ?? longShortQuery.error ?? turnoverQuery.error ?? coverageQuery.error;
  const rowPending = rankQuery.isPending || rollingQuery.isPending || decayQuery.isPending
    || quantileQuery.isPending || longShortQuery.isPending || turnoverQuery.isPending
    || coverageQuery.isPending;

  const chooseSeries = (nextId: string) => {
    const item = catalog.items.find((candidate) => candidate.series_id === nextId);
    if (!item) return;
    const nextContext = patchWorkbenchContext(context, {
      program_id: item.program_id,
      factor_id: null,
      fold_id: null,
      session_date: null,
      date_range: null,
    });
    navigate(`/factors/${encodeURIComponent(item.series_id)}${workbenchContextSearch(nextContext)}`);
  };
  const chooseFactor = (nextFactor: string) => {
    select({ factor_id: nextFactor, session_date: null }, "factor_selected");
  };
  const chooseFold = (nextFold: string) => {
    select({ fold_id: nextFold || null, session_date: null }, "date_range_selected");
  };
  const chooseRange = (nextStart: string, nextEnd: string) => {
    select({ date_range: rangeValue(nextStart || null, nextEnd || null), session_date: null }, "date_range_selected");
  };
  const chooseSession = (session: string) => {
    select({ session_date: session }, "session_selected");
  };

  return (
    <div className="page factor-tear-sheet">
      <PageHeader
        eyebrow="V4.3A · Factor Tear Sheet"
        title={factor.feature_id}
        description={factor.feature_digest}
      >
        <Link className="button secondary" to={`/program/${encodeURIComponent(activeSeries.program_id)}${workbenchContextSearch(context)}`}>
          Open A2.6 program <ArrowRight size={15} />
        </Link>
      </PageHeader>

      <div className="factor-authority-banner">
        <ShieldCheck size={18} />
        <div>
          <strong>Verified V4-1 period evidence + frozen A2.6 statistical evidence</strong>
          <span>Solid period rows retain authoritative status; rolling IC and NAV retain persisted derived status. React groups rows for display only and does not recompute IC, NAV, HAC/bootstrap or multiple-testing statistics.</span>
        </div>
        <StatusBadge value="no browser recompute" />
      </div>

      <div className="factor-toolbar">
        <label>
          <span>Factor series</span>
          <select value={activeSeries.series_id} onChange={(event) => chooseSeries(event.target.value)}>
            {catalog.items.map((item) => <option key={item.series_id} value={item.series_id}>{item.program_id} · {item.factor_count} factors</option>)}
          </select>
        </label>
        <label>
          <span>Factor</span>
          <select value={factorDigest} onChange={(event) => chooseFactor(event.target.value)}>
            {dimensions?.factors.map((item) => <option key={item.feature_digest} value={item.feature_digest}>{item.feature_id}{item.selected ? " · selected" : ""}</option>)}
          </select>
        </label>
        <label>
          <span>Fold</span>
          <select value={foldId ?? ""} onChange={(event) => chooseFold(event.target.value)}>
            <option value="">All folds</option>
            {dimensions?.folds.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label>
          <span>Start</span>
          <input type="date" value={start ?? ""} min={dimensions?.start_date ?? undefined} max={dimensions?.end_date ?? undefined} onChange={(event) => chooseRange(event.target.value, end ?? "")} />
        </label>
        <label>
          <span>End</span>
          <input type="date" value={end ?? ""} min={dimensions?.start_date ?? undefined} max={dimensions?.end_date ?? undefined} onChange={(event) => chooseRange(start ?? "", event.target.value)} />
        </label>
      </div>

      <FrozenStatistics item={summaryItem} />

      {catalog.warnings.length ? (
        <Panel title="Factor-series warnings" subtitle="Invalid or identity-conflicting V4-1 packages are excluded from the tear sheet.">
          <ul className="warning-list">{catalog.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </Panel>
      ) : null}

      {rowPending ? <LoadingState /> : rowError ? <ErrorState error={rowError} /> : (
        <>
          <Panel
            title="IC & persisted rolling IC"
            subtitle="RankIC is authoritative V4-1 period evidence. Rolling RankIC is the V4-1 persisted deterministic transform; the browser does not recalculate the rolling window."
            actions={<div className="factor-authority-pair"><AuthorityBadge value="authoritative" /><AuthorityBadge value="derived" /></div>}
          >
            {rankRows.length ? <FactorIcChart rankRows={rankRows} rollingRows={rollingRows} selectedSession={selectedSession} onSession={chooseSession} /> : <EmptyState title="No IC rows" detail="No authoritative RankIC rows exist for this factor/fold/date slice." />}
          </Panel>

          <div className="two-column factor-two-column">
            <Panel title="Decay by frozen horizon" subtitle="Oriented RankIC rows for the primary and decay labels; no browser-side horizon statistic is calculated." actions={<AuthorityBadge value="authoritative" />}>
              {decayRows.length ? <DecayChart rows={decayRows} /> : <EmptyState title="No decay rows" detail="No persisted RankIC rows exist in this slice." />}
            </Panel>
            <Panel title="Frozen fold RankICIR heatmap" subtitle="Direct A2.6 fold summaries. Fold labels may encode calendar years; values are not re-aggregated from period IC in React." actions={<AuthorityBadge value="authoritative_frozen_a2p6_summary" />}>
              <FoldHeatmap item={summaryItem} />
            </Panel>
          </div>

          <Panel title="Quantile & long-short performance" subtitle="Cumulative NAV rows are persisted V4-1 derived evidence. React does not cumulate period returns." actions={<AuthorityBadge value="derived" />}>
            {quantileRows.length || longShortRows.length ? <PerformanceChart quantileRows={quantileRows} longShortRows={longShortRows} /> : <EmptyState title="No persisted NAV rows" detail="No quantile/long-short NAV evidence exists for this slice." />}
          </Panel>

          <Panel title="Turnover & coverage" subtitle="Direct V4-1 period evidence for one-way turnover and valid-factor coverage." actions={<AuthorityBadge value="authoritative" />}>
            {turnoverRows.length || coverageRows.length ? <TurnoverCoverageChart turnoverRows={turnoverRows} coverageRows={coverageRows} /> : <EmptyState title="No turnover/coverage rows" detail="No authoritative turnover or coverage evidence exists for this slice." />}
          </Panel>

          <Panel title="Selected session evidence" subtitle="Chart selection binds session_date through WorkbenchContext without creating a new statistic.">
            <SessionInspector session={selectedSession} rankRows={rankRows} rollingRows={rollingRows} turnoverRows={turnoverRows} coverageRows={coverageRows} />
          </Panel>

          <div className="two-column factor-two-column">
            <Panel title="Frozen evidence identity" subtitle="The V4-1 package physically binds the source A2.6 report and period Parquet.">
              <dl className="identity-grid compact">
                <div><dt>Series</dt><dd>{activeSeries.series_id}</dd></div>
                <div><dt>Program result</dt><dd>{activeSeries.program_result_id}</dd></div>
                <div><dt>Selection</dt><dd>{activeSeries.selection_id}</dd></div>
                <div><dt>Data version</dt><dd>{activeSeries.data_version}</dd></div>
                <div><dt>Rows</dt><dd>{activeSeries.row_count}</dd></div>
                <div><dt>Rolling window</dt><dd>{detailQuery.data?.manifest.rolling_window ?? "—"}</dd></div>
              </dl>
            </Panel>
            <Panel title="V4-3 remaining analytical surfaces" subtitle="The foundation exposes frozen summary/correlation payloads without inventing new authority.">
              <div className="factor-status-list">
                <StatusBadge value="HAC/bootstrap summary exposed" />
                <StatusBadge value="Holm/BH summary exposed" />
                <StatusBadge value="factor correlations exposed" />
                <StatusBadge value="correlation clustering pending" />
                <StatusBadge value="Agent discovery evolution pending" />
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

export { FactorIcChart, DecayChart, PerformanceChart, TurnoverCoverageChart, FoldHeatmap };

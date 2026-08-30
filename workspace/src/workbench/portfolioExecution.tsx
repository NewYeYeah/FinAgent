import { useEffect, useMemo } from "react";
import ReactECharts from "echarts-for-react";
import { ArrowRight, BriefcaseBusiness, ListTree, ShieldCheck } from "lucide-react";
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
} from "./context";
import { portfolioExecutionApi } from "./portfolioExecutionApi";
import type {
  MonthlyReturnV4,
  PortfolioExecutionAnalyticsV4,
  PortfolioExecutionItemV4,
  PortfolioSeriesPointV4,
  StrategyDecisionRowV4,
} from "./portfolioExecutionTypes";
import { useWorkbenchQuery } from "./query";
import "./portfolioExecution.css";

function pct(value: number | null | undefined, digits = 2): string {
  return value == null ? "—" : `${(value * 100).toFixed(digits)}%`;
}

function num(value: number | null | undefined, digits = 3): string {
  return value == null ? "—" : value.toFixed(digits);
}

function money(value: number | null | undefined): string {
  return value == null ? "—" : value.toLocaleString(undefined, { maximumFractionDigits: 2 });
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

function itemLabel(item: PortfolioExecutionItemV4): string {
  return `${item.portfolio_validation_id} · ${item.asset_count} assets · ${item.fold_count} folds`;
}

function NavDrawdownChart({
  points,
  analytics,
}: {
  points: PortfolioSeriesPointV4[];
  analytics: PortfolioExecutionAnalyticsV4;
}) {
  const drawdown = new Map(
    analytics.drawdown.items.map((point) => [point.session_date, point]),
  );
  const dates = points.map((point) => point.session_date);
  const option = {
    animation: false,
    grid: [
      { left: 64, right: 30, top: 38, height: "52%" },
      { left: 64, right: 30, top: "70%", height: "17%" },
    ],
    tooltip: { trigger: "axis", confine: true },
    legend: { data: ["Net NAV", "Gross NAV", "Net drawdown", "Gross drawdown"] },
    xAxis: [
      { type: "category", data: dates, boundaryGap: false, gridIndex: 0, axisLabel: { show: false } },
      { type: "category", data: dates, boundaryGap: false, gridIndex: 1 },
    ],
    yAxis: [
      { type: "value", gridIndex: 0, scale: true, name: "NAV" },
      { type: "value", gridIndex: 1, max: 0, name: "DD", axisLabel: { formatter: (value: number) => `${(value * 100).toFixed(0)}%` } },
    ],
    dataZoom: [{ type: "inside", xAxisIndex: [0, 1] }, { type: "slider", xAxisIndex: [0, 1], height: 15, bottom: 4 }],
    series: [
      { name: "Net NAV", type: "line", showSymbol: false, data: points.map((point) => point.net_nav), xAxisIndex: 0, yAxisIndex: 0 },
      { name: "Gross NAV", type: "line", showSymbol: false, data: points.map((point) => point.gross_nav), xAxisIndex: 0, yAxisIndex: 0 },
      { name: "Net drawdown", type: "line", showSymbol: false, data: dates.map((current) => drawdown.get(current)?.net_drawdown ?? null), xAxisIndex: 1, yAxisIndex: 1, areaStyle: {} },
      { name: "Gross drawdown", type: "line", showSymbol: false, data: dates.map((current) => drawdown.get(current)?.gross_drawdown ?? null), xAxisIndex: 1, yAxisIndex: 1 },
    ],
  };
  return <ReactECharts option={option} style={{ height: 430 }} />;
}

function RollingChart({ analytics }: { analytics: PortfolioExecutionAnalyticsV4 }) {
  const rows = analytics.rolling.items;
  const dates = rows.map((row) => row.session_date);
  const option = {
    animation: false,
    grid: { left: 64, right: 54, top: 44, bottom: 52 },
    tooltip: { trigger: "axis", confine: true },
    legend: { data: ["Rolling return", "Rolling volatility", "Rolling Sharpe"] },
    xAxis: { type: "category", data: dates, boundaryGap: false },
    yAxis: [
      { type: "value", name: "Return / vol", axisLabel: { formatter: (value: number) => `${(value * 100).toFixed(0)}%` } },
      { type: "value", name: "Sharpe" },
    ],
    dataZoom: [{ type: "inside" }, { type: "slider", height: 15, bottom: 5 }],
    series: [
      { name: "Rolling return", type: "line", showSymbol: false, data: rows.map((row) => row.rolling_return), yAxisIndex: 0 },
      { name: "Rolling volatility", type: "line", showSymbol: false, data: rows.map((row) => row.rolling_volatility), yAxisIndex: 0 },
      { name: "Rolling Sharpe", type: "line", showSymbol: false, data: rows.map((row) => row.rolling_sharpe), yAxisIndex: 1 },
    ],
  };
  return <ReactECharts option={option} style={{ height: 320 }} />;
}

function MonthlyHeatmap({ rows }: { rows: MonthlyReturnV4[] }) {
  const years = [...new Set(rows.map((row) => String(row.year)))];
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const values = rows.map((row) => row.net_return);
  const maxAbs = Math.max(0.01, ...values.map((value) => Math.abs(value)));
  const data = rows.map((row) => [row.month_number - 1, years.indexOf(String(row.year)), row.net_return, row.periods]);
  const option = {
    animation: false,
    tooltip: { formatter: (params: { data?: unknown[] }) => `${years[Number(params.data?.[1])]} ${months[Number(params.data?.[0])]}<br/>net ${pct(Number(params.data?.[2]))} · n=${params.data?.[3]}` },
    grid: { left: 64, right: 30, top: 24, bottom: 54 },
    xAxis: { type: "category", data: months },
    yAxis: { type: "category", data: years },
    visualMap: { min: -maxAbs, max: maxAbs, calculable: true, orient: "horizontal", left: "center", bottom: 0 },
    series: [{ type: "heatmap", data, label: { show: true, formatter: (params: { data?: unknown[] }) => pct(Number(params.data?.[2]), 1) } }],
  };
  return <ReactECharts option={option} style={{ height: Math.max(270, years.length * 46 + 130) }} />;
}

function CostChart({ analytics }: { analytics: PortfolioExecutionAnalyticsV4 }) {
  const costs = analytics.filtered_costs;
  const option = {
    animation: false,
    grid: { left: 80, right: 24, top: 28, bottom: 44 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: { type: "category", data: ["Fees", "Slippage", "Total"] },
    yAxis: { type: "value", name: "Cost" },
    series: [{ type: "bar", data: [costs.fees, costs.slippage, costs.total_cost] }],
  };
  return <ReactECharts option={option} style={{ height: 280 }} />;
}

function FunnelChart({ analytics }: { analytics: PortfolioExecutionAnalyticsV4 }) {
  const funnel = analytics.order_funnel;
  const option = {
    animation: false,
    tooltip: { trigger: "item" },
    series: [{
      type: "funnel",
      left: "12%",
      width: "76%",
      sort: "none",
      data: [
        { name: "Desired", value: funnel.desired },
        { name: "Executable", value: funnel.executable },
        { name: "Filled", value: funnel.filled },
      ],
    }],
  };
  return <ReactECharts option={option} style={{ height: 280 }} />;
}

function ConstraintChart({ analytics }: { analytics: PortfolioExecutionAnalyticsV4 }) {
  const entries = Object.entries(analytics.constraint_attribution.reason_counts).sort((left, right) => right[1] - left[1]);
  if (!entries.length) return <EmptyState title="No constraint codes" detail="The selected authoritative V4-0 decision rows contain no A3 constraint codes." />;
  const option = {
    animation: false,
    grid: { left: 180, right: 28, top: 24, bottom: 36 },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: { type: "value", minInterval: 1 },
    yAxis: { type: "category", data: entries.map(([key]) => key) },
    series: [{ type: "bar", data: entries.map(([, value]) => value) }],
  };
  return <ReactECharts option={option} style={{ height: Math.max(280, entries.length * 34 + 90) }} />;
}

function WeightChart({ rows }: { rows: StrategyDecisionRowV4[] }) {
  const dates = [...new Set(rows.map((row) => row.session_date))].sort();
  const target = new Map(rows.map((row) => [row.session_date, row.target_weight]));
  const realized = new Map(rows.map((row) => [row.session_date, row.realized_weight]));
  const option = {
    animation: false,
    grid: { left: 64, right: 24, top: 40, bottom: 50 },
    tooltip: { trigger: "axis", confine: true },
    legend: { data: ["Target", "Realized"] },
    xAxis: { type: "category", data: dates, boundaryGap: false },
    yAxis: { type: "value", name: "Weight", axisLabel: { formatter: (value: number) => `${(value * 100).toFixed(0)}%` } },
    series: [
      { name: "Target", type: "line", connectNulls: false, data: dates.map((current) => target.get(current) ?? null) },
      { name: "Realized", type: "line", connectNulls: false, data: dates.map((current) => realized.get(current) ?? null) },
    ],
  };
  return <ReactECharts option={option} style={{ height: 300 }} />;
}

export function PortfolioExecutionIndexPage({ mode }: { mode: "portfolio" | "execution" }) {
  const navigate = useNavigate();
  const query = useWorkbenchQuery({ key: ["portfolio-execution-v44"], queryFn: portfolioExecutionApi.catalog });
  if (query.isPending) return <LoadingState />;
  if (query.error) return <ErrorState error={query.error} />;
  const catalog = query.data;
  if (!catalog?.items.length) {
    return (
      <div className="page">
        <PageHeader eyebrow="V4.4 · Linked analytics" title={mode === "portfolio" ? "Portfolio" : "Execution"} description="No A4 validation with a verified V4-0 StrategyDecisionSeries is configured." />
        <EmptyState title="No linked A4 + V4-0 evidence" detail="Materialize V4-0 beside the immutable A4 report and ledger, then restart the Evidence Plane." />
      </div>
    );
  }
  return (
    <div className="page v44-page">
      <PageHeader eyebrow="V4.4 · Linked analytics" title={mode === "portfolio" ? "Portfolio Interactive Pack" : "Execution Interactive Pack"} description="A4 portfolio authority linked to immutable V4-0 decision evidence." />
      <div className="v44-card-grid">
        {catalog.items.map((item) => (
          <button key={item.portfolio_validation_id} type="button" className="v44-select-card" onClick={() => navigate(`/${mode}/${encodeURIComponent(item.portfolio_validation_id)}`)}>
            {mode === "portfolio" ? <BriefcaseBusiness size={19} /> : <ListTree size={19} />}
            <div><strong>{item.portfolio_validation_id}</strong><span>{item.asset_count} assets · {item.fold_count} folds · {item.session_count} sessions</span><code>{item.strategy_series_id}</code></div>
            <ArrowRight size={16} />
          </button>
        ))}
      </div>
    </div>
  );
}

export function PortfolioInteractivePage() {
  const { validationId: encodedValidationId = "" } = useParams();
  const validationId = decodeURIComponent(encodedValidationId);
  const { context, select } = useWorkbenchContext();
  const range = dateRange(context.date_range);
  const catalog = useWorkbenchQuery({ key: ["portfolio-execution-v44"], queryFn: portfolioExecutionApi.catalog });
  const detail = useWorkbenchQuery({ key: ["portfolio-execution-detail", validationId], enabled: Boolean(validationId), queryFn: () => portfolioExecutionApi.detail(validationId) });
  const series = useWorkbenchQuery({ key: ["portfolio-execution-series", validationId, context.fold_id, range.start, range.end], enabled: Boolean(validationId), queryFn: () => portfolioExecutionApi.series(validationId, { foldId: context.fold_id, start: range.start, end: range.end, limit: 5000 }) });
  const analytics = useWorkbenchQuery({ key: ["portfolio-execution-analytics", validationId, context.fold_id, range.start, range.end], enabled: Boolean(validationId), queryFn: () => portfolioExecutionApi.analytics(validationId, { foldId: context.fold_id, start: range.start, end: range.end }) });

  useEffect(() => {
    const item = detail.data?.item;
    if (!item) return;
    const patch: Record<string, string | null | undefined> = {};
    if (context.portfolio_validation_id !== validationId) patch.portfolio_validation_id = validationId;
    if (!context.date_range && (item.start_date || item.end_date)) patch.date_range = rangeValue(item.start_date, item.end_date);
    if (Object.keys(patch).length) select(patch, "evidence_selected", { replace: true });
  }, [context.date_range, context.portfolio_validation_id, detail.data?.item, select, validationId]);

  if (detail.isPending || series.isPending || analytics.isPending || catalog.isPending) return <LoadingState />;
  const error = detail.error ?? series.error ?? analytics.error ?? catalog.error;
  if (error) return <ErrorState error={error} />;
  if (!detail.data || !series.data || !analytics.data) return <EmptyState title="Portfolio evidence unavailable" detail="The linked A4/V4-0 projection did not resolve." />;

  const folds = detail.data.folds.map((fold) => String(fold.fold_id ?? "")).filter(Boolean);
  const item = detail.data.item;
  const metrics = detail.data.portfolio_metrics;
  const nextContext = patchWorkbenchContext(context, { portfolio_validation_id: validationId });

  return (
    <div className="page v44-page">
      <PageHeader eyebrow="V4.4 · Portfolio" title={validationId} description="Authoritative A4 NAV/aggregate evidence with explicitly derived linked performance views.">
        <Link className="button secondary" to={`/execution/${encodeURIComponent(validationId)}${workbenchContextSearch(nextContext)}`}>Open Execution <ArrowRight size={15} /></Link>
      </PageHeader>
      <div className="v44-authority-banner"><ShieldCheck size={18} /><div><strong>A4 portfolio authority + server-side presentation derivatives</strong><span>No NAV, return, drawdown, rolling statistic, monthly return or cost aggregate is reconstructed in React.</span></div><AuthorityBadge value="authoritative + derived" /></div>
      <div className="v44-toolbar">
        <label><span>Portfolio</span><select value={validationId} onChange={(event) => { const value = event.target.value; select({ portfolio_validation_id: value, asset_id: null, order_id: null, session_date: null, fold_id: null, date_range: null }, "evidence_selected"); window.location.assign(`/portfolio/${encodeURIComponent(value)}`); }}>{(catalog.data?.items ?? []).map((entry) => <option key={entry.portfolio_validation_id} value={entry.portfolio_validation_id}>{itemLabel(entry)}</option>)}</select></label>
        <label><span>Fold</span><select value={context.fold_id ?? ""} onChange={(event) => select({ fold_id: event.target.value || null }, "date_range_selected")}><option value="">All folds</option>{folds.map((fold) => <option key={fold} value={fold}>{fold}</option>)}</select></label>
        <label><span>Start</span><input type="date" min={item.start_date ?? undefined} max={item.end_date ?? undefined} value={range.start ?? item.start_date ?? ""} onChange={(event) => select({ date_range: rangeValue(event.target.value, range.end ?? item.end_date) }, "date_range_selected")} /></label>
        <label><span>End</span><input type="date" min={item.start_date ?? undefined} max={item.end_date ?? undefined} value={range.end ?? item.end_date ?? ""} onChange={(event) => select({ date_range: rangeValue(range.start ?? item.start_date, event.target.value) }, "date_range_selected")} /></label>
      </div>
      <div className="metric-grid six">
        <MetricCard label="Net return" value={pct(metrics.net_return)} />
        <MetricCard label="Gross return" value={pct(metrics.gross_return)} />
        <MetricCard label="Net Sharpe" value={num(metrics.net_sharpe)} />
        <MetricCard label="Frozen max DD" value={pct(metrics.max_drawdown)} />
        <MetricCard label="Gross→net drag" value={pct(metrics.gross_to_net_drag)} />
        <MetricCard label="Turnover" value={pct(metrics.one_way_turnover)} />
      </div>
      <Panel title="NAV & drawdown" subtitle="NAV/period returns are authoritative A4 points. Drawdown is a labeled server-side presentation transform."><NavDrawdownChart points={series.data.items} analytics={analytics.data} /></Panel>
      <div className="two-column">
        <Panel title={`Rolling performance · ${analytics.data.rolling.window}`} subtitle="DERIVED PRESENTATION from selected authoritative A4 net returns."><RollingChart analytics={analytics.data} /></Panel>
        <Panel title="Monthly return matrix" subtitle="DERIVED PRESENTATION: calendar-month compounding is performed by the Evidence Plane."><MonthlyHeatmap rows={analytics.data.monthly_returns.items} /></Panel>
      </div>
      <div className="two-column">
        <Panel title="Filtered cost waterfall" subtitle="DERIVED PRESENTATION sum over authoritative V4-0 per-asset fees/slippage rows."><CostChart analytics={analytics.data} /></Panel>
        <Panel title="Evidence availability" subtitle="Missing evidence remains unavailable rather than inferred."><div className="v44-availability"><StatusBadge value={detail.data.presentation.benchmark_available ? "benchmark available" : "benchmark unavailable"} tone="neutral" /><p>{detail.data.presentation.benchmark_note}</p><AuthorityBadge value={analytics.data.benchmark.authority} /></div></Panel>
      </div>
    </div>
  );
}

export function ExecutionInteractivePage() {
  const { validationId: encodedValidationId = "" } = useParams();
  const validationId = decodeURIComponent(encodedValidationId);
  const { context, select } = useWorkbenchContext();
  const range = dateRange(context.date_range);
  const detail = useWorkbenchQuery({ key: ["portfolio-execution-detail", validationId], enabled: Boolean(validationId), queryFn: () => portfolioExecutionApi.detail(validationId) });
  const allRows = useWorkbenchQuery({ key: ["portfolio-execution-decisions-all", validationId], enabled: Boolean(validationId), queryFn: () => portfolioExecutionApi.decisions(validationId, { limit: 5000 }) });

  const assets = useMemo(() => [...new Set((allRows.data?.items ?? []).map((row) => row.asset))].sort(), [allRows.data?.items]);
  const orders = useMemo(() => [...new Set((allRows.data?.items ?? []).map((row) => row.client_order_id).filter((value): value is string => Boolean(value)))].sort(), [allRows.data?.items]);
  const sessions = useMemo(() => [...new Set((allRows.data?.items ?? []).map((row) => row.session_date))].sort(), [allRows.data?.items]);
  const folds = useMemo(() => [...new Set((allRows.data?.items ?? []).map((row) => row.fold_id))].sort(), [allRows.data?.items]);

  useEffect(() => {
    const item = detail.data?.item;
    if (!item) return;
    const patch: Record<string, string | null | undefined> = {};
    if (context.portfolio_validation_id !== validationId) patch.portfolio_validation_id = validationId;
    if (!context.asset_id && assets[0]) patch.asset_id = assets[0];
    if (!context.date_range && (item.start_date || item.end_date)) patch.date_range = rangeValue(item.start_date, item.end_date);
    if (Object.keys(patch).length) select(patch, "evidence_selected", { replace: true });
  }, [assets, context.asset_id, context.date_range, context.portfolio_validation_id, detail.data?.item, select, validationId]);

  const decisions = useWorkbenchQuery({
    key: ["portfolio-execution-decisions", validationId, context.asset_id, context.order_id, context.session_date, context.fold_id, range.start, range.end],
    enabled: Boolean(validationId),
    queryFn: () => portfolioExecutionApi.decisions(validationId, {
      asset: context.asset_id,
      orderId: context.order_id,
      sessionDate: context.session_date,
      foldId: context.fold_id,
      start: context.session_date ? undefined : range.start,
      end: context.session_date ? undefined : range.end,
      limit: 5000,
    }),
  });
  const analytics = useWorkbenchQuery({
    key: ["portfolio-execution-analytics-execution", validationId, context.asset_id, context.order_id, context.fold_id, range.start, range.end],
    enabled: Boolean(validationId),
    queryFn: () => portfolioExecutionApi.analytics(validationId, { asset: context.asset_id, orderId: context.order_id, foldId: context.fold_id, start: range.start, end: range.end }),
  });

  if (detail.isPending || allRows.isPending || decisions.isPending || analytics.isPending) return <LoadingState />;
  const error = detail.error ?? allRows.error ?? decisions.error ?? analytics.error;
  if (error) return <ErrorState error={error} />;
  if (!detail.data || !decisions.data || !analytics.data) return <EmptyState title="Execution evidence unavailable" detail="The linked V4-0 decision projection did not resolve." />;

  const item = detail.data.item;
  const contextForPortfolio = patchWorkbenchContext(context, { portfolio_validation_id: validationId });

  return (
    <div className="page v44-page">
      <PageHeader eyebrow="V4.4 · Execution" title={validationId} description="Authoritative V4-0 target/order/fill/weight/PnL rows with derived filtered attribution.">
        <Link className="button secondary" to={`/portfolio/${encodeURIComponent(validationId)}${workbenchContextSearch(contextForPortfolio)}`}>Open Portfolio <ArrowRight size={15} /></Link>
      </PageHeader>
      <div className="v44-authority-banner"><ShieldCheck size={18} /><div><strong>V4-0 StrategyDecisionSeries is the execution authority</strong><span>Target/realized weights, client_order_id, quantities, prices, costs, PnL and constraint codes are consumed directly; aggregation is server-side and labeled derived.</span></div><AuthorityBadge value="authoritative + derived" /></div>
      <div className="v44-toolbar execution">
        <label><span>Asset</span><select value={context.asset_id ?? ""} onChange={(event) => select({ asset_id: event.target.value || null, order_id: null }, "asset_selected")}><option value="">All assets</option>{assets.map((asset) => <option key={asset} value={asset}>{asset}</option>)}</select></label>
        <label><span>Order</span><select value={context.order_id ?? ""} onChange={(event) => select({ order_id: event.target.value || null }, "order_selected")}><option value="">All orders</option>{orders.map((order) => <option key={order} value={order}>{order}</option>)}</select></label>
        <label><span>Session</span><select value={context.session_date ?? ""} onChange={(event) => select({ session_date: event.target.value || null }, "session_selected")}><option value="">All sessions</option>{sessions.map((session) => <option key={session} value={session}>{session}</option>)}</select></label>
        <label><span>Fold</span><select value={context.fold_id ?? ""} onChange={(event) => select({ fold_id: event.target.value || null }, "date_range_selected")}><option value="">All folds</option>{folds.map((fold) => <option key={fold} value={fold}>{fold}</option>)}</select></label>
        <label><span>Start</span><input type="date" disabled={Boolean(context.session_date)} min={item.start_date ?? undefined} max={item.end_date ?? undefined} value={range.start ?? item.start_date ?? ""} onChange={(event) => select({ date_range: rangeValue(event.target.value, range.end ?? item.end_date) }, "date_range_selected")} /></label>
        <label><span>End</span><input type="date" disabled={Boolean(context.session_date)} min={item.start_date ?? undefined} max={item.end_date ?? undefined} value={range.end ?? item.end_date ?? ""} onChange={(event) => select({ date_range: rangeValue(range.start ?? item.start_date, event.target.value) }, "date_range_selected")} /></label>
      </div>
      <div className="metric-grid six">
        <MetricCard label="Decision rows" value={String(decisions.data.total)} />
        <MetricCard label="Desired" value={String(analytics.data.order_funnel.desired)} derived />
        <MetricCard label="Executable" value={String(analytics.data.order_funnel.executable)} derived />
        <MetricCard label="Filled" value={String(analytics.data.order_funnel.filled)} derived />
        <MetricCard label="Filtered fees" value={money(analytics.data.filtered_costs.fees)} derived />
        <MetricCard label="Filtered slippage" value={money(analytics.data.filtered_costs.slippage)} derived />
      </div>
      <div className="two-column">
        <Panel title="Target vs realized portfolio state" subtitle="Both series are authoritative values persisted in V4-0 rows; React only aligns dates for rendering."><WeightChart rows={decisions.data.items} /></Panel>
        <Panel title="Order lifecycle" subtitle="DERIVED PRESENTATION counts over authoritative desired/executable/filled quantities."><FunnelChart analytics={analytics.data} /></Panel>
      </div>
      <div className="two-column">
        <Panel title="A3 constraint attribution" subtitle="DERIVED PRESENTATION counts over authoritative V4-0 constraint_codes."><ConstraintChart analytics={analytics.data} /></Panel>
        <Panel title="Fee / slippage waterfall" subtitle="DERIVED PRESENTATION sums over authoritative V4-0 row costs."><CostChart analytics={analytics.data} /></Panel>
      </div>
      <Panel title="Authoritative decision rows" subtitle="Selecting a row updates asset / order / session in WorkbenchContext; no order identity is synthesized.">
        <div className="v44-table-wrap">
          <table className="v44-table">
            <thead><tr><th>Session</th><th>Asset</th><th>Order</th><th>Status</th><th>Desired</th><th>Executable</th><th>Filled</th><th>Target</th><th>Realized</th><th>Fees</th><th>Slippage</th><th>Net PnL</th><th>Constraints</th></tr></thead>
            <tbody>{decisions.data.items.map((row) => <tr key={row.row_id} onClick={() => select({ asset_id: row.asset, order_id: row.client_order_id, session_date: row.session_date }, "order_selected")}><td>{row.session_date}</td><td><code>{row.asset}</code></td><td><code>{row.client_order_id ?? "—"}</code></td><td><StatusBadge value={row.decision_status ?? "no action"} tone="neutral" /></td><td>{num(row.desired_quantity, 0)}</td><td>{row.executable_quantity}</td><td>{row.filled_quantity}</td><td>{pct(row.target_weight)}</td><td>{pct(row.realized_weight)}</td><td>{money(row.fees)}</td><td>{money(row.slippage)}</td><td>{money(row.net_pnl)}</td><td>{row.constraint_codes.length ? row.constraint_codes.map((code) => <code key={code} className="v44-code">{code}</code>) : "—"}</td></tr>)}</tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

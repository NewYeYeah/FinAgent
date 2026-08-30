import { useEffect, useMemo } from "react";
import ReactECharts from "echarts-for-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowRight, Database, ShieldCheck } from "lucide-react";

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
import { patchWorkbenchContext, useWorkbenchContext, workbenchContextSearch } from "./context";
import { useWorkbenchQuery, workbenchQueryKeys } from "./query";
import type {
  StrategyDecisionRowV4,
  StrategySeriesItemV4,
} from "./strategyTypes";
import "./strategy.css";

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

function seriesLabel(item: StrategySeriesItemV4): string {
  return `${item.portfolio_validation_id} · ${item.asset_count} assets · ${item.session_count} sessions`;
}

function eventDate(params: unknown): string | null {
  if (!params || typeof params !== "object") return null;
  const raw = params as { data?: unknown; name?: unknown };
  if (raw.data && typeof raw.data === "object") {
    const data = raw.data as { session_date?: unknown };
    if (typeof data.session_date === "string") return data.session_date;
  }
  return typeof raw.name === "string" ? raw.name : null;
}

function PriceExecutionChart({
  rows,
  selectedSession,
  onSession,
}: {
  rows: StrategyDecisionRowV4[];
  selectedSession?: string;
  onSession: (session: string) => void;
}) {
  const option = useMemo(() => {
    const dates = rows.map((row) => row.session_date);
    const close = rows.map((row) => row.close_price);
    const reference = rows.map((row) => row.reference_price);
    const buys = rows
      .filter((row) => row.desired_side?.toLowerCase() === "buy" && row.fill_price != null)
      .map((row) => ({
        value: [row.session_date, row.fill_price],
        session_date: row.session_date,
        filled_quantity: row.filled_quantity,
        constraint_codes: row.constraint_codes,
      }));
    const sells = rows
      .filter((row) => row.desired_side?.toLowerCase() === "sell" && row.fill_price != null)
      .map((row) => ({
        value: [row.session_date, row.fill_price],
        session_date: row.session_date,
        filled_quantity: row.filled_quantity,
        constraint_codes: row.constraint_codes,
      }));
    return {
      animation: false,
      grid: { left: 56, right: 24, top: 52, bottom: 56 },
      legend: { data: ["Close", "Reference", "Buy fill", "Sell fill"] },
      tooltip: { trigger: "axis", confine: true },
      xAxis: { type: "category", data: dates, boundaryGap: false },
      yAxis: { type: "value", scale: true, name: "Price" },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
      series: [
        {
          name: "Close",
          type: "line",
          data: close,
          showSymbol: false,
          connectNulls: false,
          lineStyle: { width: 2 },
          markLine: selectedSession
            ? {
                silent: true,
                symbol: "none",
                data: [{ xAxis: selectedSession }],
              }
            : undefined,
        },
        {
          name: "Reference",
          type: "line",
          data: reference,
          showSymbol: false,
          connectNulls: false,
          lineStyle: { type: "dashed", width: 1 },
        },
        { name: "Buy fill", type: "scatter", symbol: "triangle", symbolSize: 11, data: buys },
        { name: "Sell fill", type: "scatter", symbol: "triangle", symbolRotate: 180, symbolSize: 11, data: sells },
      ],
    };
  }, [rows, selectedSession]);
  return (
    <ReactECharts
      option={option}
      style={{ height: 390 }}
      onEvents={{ click: (params: unknown) => {
        const session = eventDate(params);
        if (session) onSession(session);
      } }}
    />
  );
}

function WeightChart({ rows }: { rows: StrategyDecisionRowV4[] }) {
  const option = useMemo(() => ({
    animation: false,
    grid: { left: 58, right: 20, top: 38, bottom: 42 },
    tooltip: { trigger: "axis" },
    legend: { data: ["Pre-trade", "Target", "Realized"] },
    xAxis: { type: "category", data: rows.map((row) => row.session_date), boundaryGap: false },
    yAxis: { type: "value", name: "Weight", axisLabel: { formatter: (value: number) => `${(value * 100).toFixed(0)}%` } },
    series: [
      { name: "Pre-trade", type: "line", showSymbol: false, data: rows.map((row) => row.pre_trade_weight), lineStyle: { type: "dotted" } },
      { name: "Target", type: "line", showSymbol: false, data: rows.map((row) => row.target_weight), connectNulls: false },
      { name: "Realized", type: "line", showSymbol: false, data: rows.map((row) => row.realized_weight) },
    ],
  }), [rows]);
  return <ReactECharts option={option} style={{ height: 280 }} />;
}

function AlphaChart({ rows }: { rows: StrategyDecisionRowV4[] }) {
  const option = useMemo(() => ({
    animation: false,
    grid: { left: 58, right: 54, top: 38, bottom: 42 },
    tooltip: { trigger: "axis" },
    legend: { data: ["Alpha score", "Expected return"] },
    xAxis: { type: "category", data: rows.map((row) => row.session_date), boundaryGap: false },
    yAxis: [
      { type: "value", name: "Score", scale: true },
      { type: "value", name: "Expected", axisLabel: { formatter: (value: number) => `${(value * 100).toFixed(1)}%` } },
    ],
    series: [
      { name: "Alpha score", type: "line", showSymbol: false, connectNulls: false, data: rows.map((row) => row.alpha_score) },
      { name: "Expected return", type: "line", yAxisIndex: 1, showSymbol: false, connectNulls: false, data: rows.map((row) => row.alpha_expected_return) },
    ],
  }), [rows]);
  return <ReactECharts option={option} style={{ height: 280 }} />;
}

function PnlCostChart({ rows }: { rows: StrategyDecisionRowV4[] }) {
  const option = useMemo(() => ({
    animation: false,
    grid: { left: 66, right: 24, top: 42, bottom: 48 },
    tooltip: { trigger: "axis" },
    legend: { data: ["Gross PnL", "Net PnL", "Fees", "Slippage"] },
    xAxis: { type: "category", data: rows.map((row) => row.session_date },
    yAxis: { type: "value", name: "Currency" },
    series: [
      { name: "Gross PnL", type: "bar", data: rows.map((row) => row.gross_pnl) },
      { name: "Net PnL", type: "bar", data: rows.map((row) => row.net_pnl) },
      { name: "Fees", type: "line", showSymbol: false, data: rows.map((row) => row.fees) },
      { name: "Slippage", type: "line", showSymbol: false, data: rows.map((row) => row.slippage) },
    ],
  }), [rows]);
  return <ReactECharts option={option} style={{ height: 300 }} />;
}

function DecisionInspector({ row }: { row: StrategyDecisionRowV4 | undefined }) {
  if (!row) {
    return <EmptyState title="No session selected" detail="Select a session on the timeline or choose a date from WorkbenchContext." />;
  }
  return (
    <div className="strategy-inspector-grid">
      <MetricCard label="Session" value={row.session_date} detail={row.fold_id} />
      <MetricCard label="Alpha rank" value={row.alpha_rank == null ? "—" : String(row.alpha_rank)} detail={`score ${number(row.alpha_score)}`} />
      <MetricCard label="Expected return" value={percent(row.alpha_expected_return)} detail={`uncertainty ${percent(row.alpha_uncertainty)}`} />
      <MetricCard label="Target / realized" value={`${percent(row.target_weight)} / ${percent(row.realized_weight)}`} />
      <MetricCard label="Desired / executable / fill" value={`${number(row.desired_quantity, 0)} / ${row.executable_quantity} / ${row.filled_quantity}`} detail={row.desired_side ?? "no order"} />
      <MetricCard label="Reference / fill / close" value={`${number(row.reference_price, 2)} / ${number(row.fill_price, 2)} / ${number(row.close_price, 2)}`} />
      <MetricCard label="Gross / net PnL" value={`${number(row.gross_pnl, 2)} / ${number(row.net_pnl, 2)}`} />
      <MetricCard label="Fees / slippage" value={`${number(row.fees, 2)} / ${number(row.slippage, 2)}`} />
      <div className="strategy-constraint-card">
        <span>Execution status</span>
        <strong>{row.decision_status ?? (row.rebalanced ? "no executable decision" : "not rebalanced")}</strong>
        <div className="strategy-code-list">
          {row.constraint_codes.length ? row.constraint_codes.map((code) => <code key={code}>{code}</code>) : <em>No constraint codes</em>}
        </div>
      </div>
    </div>
  );
}

export function StrategyDecisionExplorerPage() {
  const { seriesId: encodedSeriesId } = useParams();
  const navigate = useNavigate();
  const { context, select } = useWorkbenchContext();
  const routeSeriesId = encodedSeriesId ? decodeURIComponent(encodedSeriesId) : undefined;

  const catalogQuery = useWorkbenchQuery({
    key: ["strategy-series-v4"],
    queryFn: workspaceApi.strategySeriesV4,
  });
  const catalog = catalogQuery.data;
  const contextSeries = context.portfolio_validation_id
    ? catalog?.items.find((item) => item.portfolio_validation_id === context.portfolio_validation_id)
    : undefined;
  const activeSeries = routeSeriesId
    ? catalog?.items.find((item) => item.series_id === routeSeriesId)
    : contextSeries ?? catalog?.items[0];
  const seriesId = activeSeries?.series_id ?? routeSeriesId ?? "";

  const detailQuery = useWorkbenchQuery({
    key: ["strategy-series-detail-v4", seriesId],
    queryFn: () => workspaceApi.strategySeriesDetailV4(seriesId),
    enabled: Boolean(seriesId),
  });
  const dimensionsQuery = useWorkbenchQuery({
    key: ["strategy-series-dimensions-v4", seriesId],
    queryFn: () => workspaceApi.strategySeriesDimensionsV4(seriesId),
    enabled: Boolean(seriesId),
  });
  const dimensions = dimensionsQuery.data;
  const asset = context.asset_id && dimensions?.assets.includes(context.asset_id)
    ? context.asset_id
    : dimensions?.assets[0];
  const foldId = context.fold_id && dimensions?.folds.includes(context.fold_id)
    ? context.fold_id
    : undefined;
  const range = dateRange(context.date_range);
  const start = range.start ?? dimensions?.start_date ?? undefined;
  const end = range.end ?? dimensions?.end_date ?? undefined;

  useEffect(() => {
    if (!activeSeries) return;
    const patch: Record<string, string | null | undefined> = {};
    if (context.portfolio_validation_id !== activeSeries.portfolio_validation_id) {
      patch.portfolio_validation_id = activeSeries.portfolio_validation_id;
    }
    if (asset && context.asset_id !== asset) patch.asset_id = asset;
    if (Object.keys(patch).length) {
      select(patch, "asset_selected", { replace: true });
    }
  }, [activeSeries, asset, context.asset_id, context.portfolio_validation_id, select]);

  const decisionsQuery = useWorkbenchQuery({
    key: ["strategy-decisions-v4", seriesId, asset, start, end, foldId],
    queryFn: () => workspaceApi.strategyDecisionsV4(seriesId, {
      asset,
      start,
      end,
      foldId,
      limit: 5000,
    }),
    enabled: Boolean(seriesId && asset),
    staleTime: 60_000,
  });
  const rows = decisionsQuery.data?.items ?? [];
  const selectedRow = useMemo(() => {
    if (!rows.length) return undefined;
    if (context.session_date) {
      const exact = rows.find((row) => row.session_date === context.session_date);
      if (exact) return exact;
    }
    return [...rows].reverse().find((row) => row.rebalanced) ?? rows[rows.length - 1];
  }, [context.session_date, rows]);

  if (catalogQuery.isPending) return <LoadingState />;
  if (catalogQuery.error) return <ErrorState error={catalogQuery.error} />;
  if (!catalog?.items.length) {
    return (
      <div className="page">
        <PageHeader eyebrow="V4.2 · Strategy" title="Strategy Decision Explorer" description="No verified V4-0 StrategyDecisionSeries is configured." />
        <EmptyState title="No StrategyDecisionSeries" detail="Materialize V4-0 beside an A4 report under a configured Workspace report root, then restart the Evidence Plane." />
      </div>
    );
  }
  if (!activeSeries || detailQuery.error || dimensionsQuery.error) {
    return <ErrorState error={detailQuery.error ?? dimensionsQuery.error ?? new Error("strategy series not found")} />;
  }
  if (detailQuery.isPending || dimensionsQuery.isPending) return <LoadingState />;

  const chooseSeries = (nextId: string) => {
    const item = catalog.items.find((candidate) => candidate.series_id === nextId);
    if (!item) return;
    const nextContext = patchWorkbenchContext(context, {
      portfolio_validation_id: item.portfolio_validation_id,
      asset_id: null,
      fold_id: null,
      session_date: null,
      date_range: null,
    });
    navigate(`/strategy/${encodeURIComponent(item.series_id)}${workbenchContextSearch(nextContext)}`);
  };

  const chooseAsset = (nextAsset: string) => {
    select({ asset_id: nextAsset, session_date: null }, "asset_selected");
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
    <div className="page strategy-explorer">
      <PageHeader
        eyebrow="V4.2 · Strategy Decision Explorer"
        title="Signal → target → order → fill → realized PnL"
        description={activeSeries.series_id}
      >
        <Link className="button secondary" to={`/portfolio/${encodeURIComponent(activeSeries.portfolio_validation_id)}${workbenchContextSearch(context)}`}>
          Open A4 cockpit <ArrowRight size={15} />
        </Link>
      </PageHeader>

      <div className="strategy-authority-banner">
        <ShieldCheck size={18} />
        <div>
          <strong>Verified V4-0 authoritative rows</strong>
          <span>Price is close-only authority. OHLC is not present in V4-0 and is not fabricated. React performs no financial-fact recomputation.</span>
        </div>
        <AuthorityBadge value="authoritative" />
      </div>

      <div className="strategy-toolbar">
        <label>
          <span>Decision series</span>
          <select value={activeSeries.series_id} onChange={(event) => chooseSeries(event.target.value)}>
            {catalog.items.map((item) => <option key={item.series_id} value={item.series_id}>{seriesLabel(item)}</option>)}
          </select>
        </label>
        <label>
          <span>Asset</span>
          <select value={asset ?? ""} onChange={(event) => chooseAsset(event.target.value)}>
            {dimensions?.assets.map((value) => <option key={value} value={value}>{value}</option>)}
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

      <div className="metric-grid six">
        <MetricCard label="Portfolio validation" value={activeSeries.portfolio_validation_id} />
        <MetricCard label="Rows in evidence" value={String(activeSeries.row_count)} />
        <MetricCard label="Sessions" value={String(activeSeries.session_count)} />
        <MetricCard label="Assets" value={String(activeSeries.asset_count)} />
        <MetricCard label="Selected factors" value={String(activeSeries.selected_feature_digests.length)} />
        <MetricCard label="Loaded asset rows" value={String(rows.length)} detail={decisionsQuery.data && decisionsQuery.data.total > rows.length ? `bounded from ${decisionsQuery.data.total}` : "bounded server projection"} />
      </div>

      {catalog.warnings.length ? (
        <Panel title="Strategy-series warnings" subtitle="Invalid or identity-conflicting V4-0 manifests are excluded from the explorer.">
          <ul className="warning-list">{catalog.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </Panel>
      ) : null}

      {decisionsQuery.isPending ? <LoadingState /> : decisionsQuery.error ? <ErrorState error={decisionsQuery.error} /> : rows.length ? (
        <>
          <Panel title="Authoritative close-price & execution timeline" subtitle="Close marks, reference prices and fill prices come directly from V4-0 rows; no synthetic OHLC/candlesticks are rendered.">
            <PriceExecutionChart rows={rows} selectedSession={selectedRow?.session_date} onSession={chooseSession} />
          </Panel>

          <div className="two-column strategy-two-column">
            <Panel title="Target vs realized weight" subtitle="Per-session V4-0 weights.">
              <WeightChart rows={rows} />
            </Panel>
            <Panel title="Frozen alpha context" subtitle="Combined A4 AlphaModel score and calibrated expected return; no browser-side factor recomputation.">
              <AlphaChart rows={rows} />
            </Panel>
          </div>

          <Panel title="Gross-to-net PnL & execution costs" subtitle="Per-session authoritative asset PnL, fees and slippage. No browser-side cumulative PnL is synthesized.">
            <PnlCostChart rows={rows} />
          </Panel>

          <Panel title="Selected session inspector" subtitle="Click the execution timeline to bind session_date into WorkbenchContext.">
            <DecisionInspector row={selectedRow} />
          </Panel>

          <div className="two-column strategy-two-column">
            <Panel title="Frozen factor family" subtitle="Identity context only. Per-asset component contributions are not persisted by V4-0 and are deliberately not inferred here.">
              <div className="strategy-factor-list">
                {activeSeries.selected_feature_digests.map((digest) => (
                  <Link key={digest} to={`/factor/${encodeURIComponent(digest)}${workbenchContextSearch(context)}`} className="strategy-factor-chip">
                    <Database size={14} /><span className="mono">{digest}</span>
                  </Link>
                ))}
              </div>
            </Panel>
            <Panel title="Evidence identity" subtitle="Immutable V4-0 bindings used by every rendered row.">
              <dl className="identity-grid compact">
                <div><dt>Data version</dt><dd>{activeSeries.data_version}</dd></div>
                <div><dt>Program result</dt><dd>{activeSeries.source_program_result_id}</dd></div>
                <div><dt>Selection</dt><dd>{activeSeries.source_selection_id}</dd></div>
                <div><dt>Alpha models</dt><dd>{activeSeries.alpha_model_ids.length}</dd></div>
              </dl>
              <div className="strategy-status-row">
                <StatusBadge value="read-only" />
                <StatusBadge value="close-only price" />
                <StatusBadge value="no browser recompute" />
              </div>
            </Panel>
          </div>
        </>
      ) : (
        <EmptyState title="No decision rows in this slice" detail="Choose another asset, fold or date range. The API does not backfill or fabricate missing sessions." />
      )}
    </div>
  );
}

export { PriceExecutionChart, WeightChart, AlphaChart, PnlCostChart };

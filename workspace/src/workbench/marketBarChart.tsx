import { useMemo } from "react";
import ReactECharts from "echarts-for-react";

import type { StrategyDecisionRowV4 } from "./strategyTypes";
import type { MarketBarRowAC2 } from "./marketBars";

function barAxisKey(row: MarketBarRowAC2): string {
  return row.interval === "1d" ? row.session_date : row.event_time;
}

function eventSession(params: unknown): string | null {
  if (!params || typeof params !== "object") return null;
  const raw = params as { data?: unknown };
  if (!raw.data || typeof raw.data !== "object") return null;
  const data = raw.data as { session_date?: unknown };
  return typeof data.session_date === "string" ? data.session_date : null;
}

export function MarketBarExecutionChart({
  bars,
  decisions,
  selectedSession,
  onSession,
}: {
  bars: MarketBarRowAC2[];
  decisions: StrategyDecisionRowV4[];
  selectedSession?: string;
  onSession: (session: string) => void;
}) {
  const option = useMemo(() => {
    const categories = bars.map(barAxisKey);
    const lastBarBySession = new Map<string, string>();
    for (const bar of bars) lastBarBySession.set(bar.session_date, barAxisKey(bar));

    const reference = decisions
      .filter((row) => row.reference_price != null && lastBarBySession.has(row.session_date))
      .map((row) => ({
        value: [lastBarBySession.get(row.session_date), row.reference_price],
        session_date: row.session_date,
      }));
    const buys = decisions
      .filter(
        (row) =>
          row.desired_side?.toLowerCase() === "buy" &&
          row.fill_price != null &&
          lastBarBySession.has(row.session_date),
      )
      .map((row) => ({
        value: [lastBarBySession.get(row.session_date), row.fill_price],
        session_date: row.session_date,
        filled_quantity: row.filled_quantity,
        client_order_id: row.client_order_id,
        constraint_codes: row.constraint_codes,
      }));
    const sells = decisions
      .filter(
        (row) =>
          row.desired_side?.toLowerCase() === "sell" &&
          row.fill_price != null &&
          lastBarBySession.has(row.session_date),
      )
      .map((row) => ({
        value: [lastBarBySession.get(row.session_date), row.fill_price],
        session_date: row.session_date,
        filled_quantity: row.filled_quantity,
        client_order_id: row.client_order_id,
        constraint_codes: row.constraint_codes,
      }));

    const selectedAxis = selectedSession
      ? lastBarBySession.get(selectedSession)
      : undefined;

    return {
      animation: false,
      grid: { left: 58, right: 24, top: 52, bottom: 62 },
      legend: { data: ["OHLC", "Reference", "Buy fill", "Sell fill"] },
      tooltip: { trigger: "axis", confine: true },
      xAxis: {
        type: "category",
        data: categories,
        boundaryGap: true,
        axisLabel: { hideOverlap: true },
      },
      yAxis: { type: "value", scale: true, name: "Price" },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }],
      series: [
        {
          name: "OHLC",
          type: "candlestick",
          data: bars.map((row) => ({
            // ECharts candlestick order is [open, close, low, high]. The values are
            // passed through directly from authoritative MarketBarSeries evidence.
            value: [row.open, row.close, row.low, row.high],
            session_date: row.session_date,
            event_time: row.event_time,
            available_at: row.available_at,
            volume: row.volume,
          })),
          markLine: selectedAxis
            ? {
                silent: true,
                symbol: "none",
                data: [{ xAxis: selectedAxis }],
              }
            : undefined,
        },
        {
          name: "Reference",
          type: "scatter",
          symbol: "diamond",
          symbolSize: 8,
          data: reference,
        },
        {
          name: "Buy fill",
          type: "scatter",
          symbol: "triangle",
          symbolSize: 11,
          data: buys,
        },
        {
          name: "Sell fill",
          type: "scatter",
          symbol: "triangle",
          symbolRotate: 180,
          symbolSize: 11,
          data: sells,
        },
      ],
    };
  }, [bars, decisions, selectedSession]);

  return (
    <ReactECharts
      option={option}
      style={{ height: 410 }}
      onEvents={{
        click: (params: unknown) => {
          const session = eventSession(params);
          if (session) onSession(session);
        },
      }}
    />
  );
}

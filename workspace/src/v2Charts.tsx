import ReactECharts from "echarts-for-react";

import type {
  ExecutionCockpitResponse,
  FoldEvidenceCell,
  RollingPoint,
  StatisticalEvidence,
} from "./types";

const TEXT = "#a8b4c7";
const GRID = "rgba(130, 148, 177, 0.16)";

export function StatisticalForestChart({ items }: { items: StatisticalEvidence[] }) {
  const ordered = [...items].sort((left, right) => left.effect - right.effect);
  const option: any = {
    animation: false,
    tooltip: {
      trigger: "item",
      formatter: (params: any) => {
        const value = ordered[params.dataIndex];
        return `${value.feature_id}<br/>effect ${value.effect.toFixed(4)}<br/>95% bootstrap CI [${value.bootstrap_ci_lower.toFixed(4)}, ${value.bootstrap_ci_upper.toFixed(4)}]<br/>HAC p ${value.hac_pvalue.toFixed(4)} · BH q ${value.bh_qvalue.toFixed(4)}`;
      },
    },
    grid: { left: 180, right: 36, top: 18, bottom: 42 },
    xAxis: {
      type: "value",
      axisLabel: { color: TEXT },
      splitLine: { lineStyle: { color: GRID } },
    },
    yAxis: {
      type: "category",
      data: ordered.map((item) => item.feature_id),
      axisLabel: { color: TEXT, width: 160, overflow: "truncate" },
    },
    series: [
      {
        type: "custom",
        data: ordered.map((item, index) => [item.effect, index, item.bootstrap_ci_lower, item.bootstrap_ci_upper]),
        renderItem: (_params: any, api: any) => {
          const y = api.coord([0, api.value(1)])[1];
          const low = api.coord([api.value(2), api.value(1)])[0];
          const high = api.coord([api.value(3), api.value(1)])[0];
          const center = api.coord([api.value(0), api.value(1)])[0];
          return {
            type: "group",
            children: [
              { type: "line", shape: { x1: low, y1: y, x2: high, y2: y }, style: { stroke: "#7f93b2", lineWidth: 2 } },
              { type: "line", shape: { x1: low, y1: y - 5, x2: low, y2: y + 5 }, style: { stroke: "#7f93b2" } },
              { type: "line", shape: { x1: high, y1: y - 5, x2: high, y2: y + 5 }, style: { stroke: "#7f93b2" } },
              { type: "circle", shape: { cx: center, cy: y, r: 5 }, style: { fill: "#69a9ff" } },
            ],
          };
        },
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: Math.max(300, ordered.length * 42) }} />;
}

export function FoldEvidenceHeatmap({ items, foldIds }: { items: FoldEvidenceCell[]; foldIds: string[] }) {
  const factors = [...new Set(items.map((item) => item.feature_id))];
  const factorIndex = new Map(factors.map((value, index) => [value, index]));
  const foldIndex = new Map(foldIds.map((value, index) => [value, index]));
  const values = items.map((item) => [
    foldIndex.get(item.fold_id) ?? 0,
    factorIndex.get(item.feature_id) ?? 0,
    item.test_rank_icir,
    item.train_direction,
    item.coverage,
    item.turnover,
  ]);
  const absolute = Math.max(0.05, ...items.map((item) => Math.abs(item.test_rank_icir)));
  const option = {
    animation: false,
    tooltip: {
      formatter: (params: any) => {
        const cell = items[params.dataIndex];
        return `${cell.feature_id} · ${cell.fold_id}<br/>test RankICIR ${cell.test_rank_icir.toFixed(3)}<br/>train direction ${cell.train_direction}<br/>coverage ${(cell.coverage * 100).toFixed(1)}% · turnover ${cell.turnover.toFixed(3)}`;
      },
    },
    grid: { left: 175, right: 36, top: 28, bottom: 54 },
    xAxis: { type: "category", data: foldIds, axisLabel: { color: TEXT } },
    yAxis: { type: "category", data: factors, axisLabel: { color: TEXT, width: 155, overflow: "truncate" } },
    visualMap: {
      min: -absolute,
      max: absolute,
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      textStyle: { color: TEXT },
    },
    series: [{ type: "heatmap", data: values, label: { show: true, formatter: (params: any) => Number(params.value[2]).toFixed(2) } }],
  };
  return <ReactECharts option={option} style={{ height: Math.max(330, factors.length * 45) }} />;
}

export function RollingEvidenceChart({ items }: { items: RollingPoint[] }) {
  const option = {
    animation: false,
    tooltip: { trigger: "axis" },
    legend: { data: ["Rolling return", "Rolling volatility", "Rolling Sharpe"], textStyle: { color: TEXT } },
    grid: { left: 60, right: 64, top: 45, bottom: 48 },
    xAxis: { type: "category", data: items.map((item) => item.session_date), axisLabel: { color: TEXT } },
    yAxis: [
      { type: "value", axisLabel: { color: TEXT, formatter: (value: number) => `${(value * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: GRID } } },
      { type: "value", axisLabel: { color: TEXT } },
    ],
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18 }],
    series: [
      { name: "Rolling return", type: "line", showSymbol: false, data: items.map((item) => item.rolling_return), yAxisIndex: 0 },
      { name: "Rolling volatility", type: "line", showSymbol: false, data: items.map((item) => item.rolling_volatility), yAxisIndex: 0 },
      { name: "Rolling Sharpe", type: "line", showSymbol: false, data: items.map((item) => item.rolling_sharpe), yAxisIndex: 1 },
    ],
  };
  return <ReactECharts option={option} style={{ height: 330 }} />;
}

export function ExecutionLifecycleChart({ execution }: { execution: ExecutionCockpitResponse }) {
  const funnel = execution.funnel;
  const values = [
    { name: "Desired", value: funnel.desired },
    ...(funnel.compiled_adjusted === null ? [] : [{ name: "Compiled / Adjusted", value: funnel.compiled_adjusted }]),
    { name: "Executable", value: funnel.executable },
    { name: "Filled", value: funnel.filled },
  ];
  const option = {
    animation: false,
    tooltip: { trigger: "item" },
    series: [
      {
        type: "funnel",
        left: "8%",
        width: "84%",
        minSize: "18%",
        maxSize: "100%",
        sort: "descending",
        label: { color: "#e8eef8", formatter: "{b}: {c}" },
        data: values,
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 320 }} />;
}

export function AttributionBar({ values, label = "Count" }: { values: Record<string, number>; label?: string }) {
  const entries = Object.entries(values).sort((left, right) => right[1] - left[1]);
  const option = {
    animation: false,
    tooltip: { trigger: "axis" },
    grid: { left: 170, right: 28, top: 20, bottom: 36 },
    xAxis: { type: "value", axisLabel: { color: TEXT }, splitLine: { lineStyle: { color: GRID } }, name: label },
    yAxis: { type: "category", data: entries.map(([key]) => key), axisLabel: { color: TEXT, width: 150, overflow: "truncate" } },
    series: [{ type: "bar", data: entries.map(([, value]) => value) }],
  };
  return <ReactECharts option={option} style={{ height: Math.max(280, entries.length * 34) }} />;
}

export function TargetRealizedChart({ items }: { items: ExecutionCockpitResponse["target_vs_realized"]["items"] }) {
  const option = {
    animation: false,
    tooltip: {
      formatter: (params: any) => {
        const item = items[params.dataIndex];
        return `${item.asset}<br/>target ${(item.target_weight * 100).toFixed(2)}%<br/>realized ${(item.realized_weight * 100).toFixed(2)}%<br/>drift ${(item.drift * 100).toFixed(2)}%`;
      },
    },
    grid: { left: 60, right: 32, top: 25, bottom: 48 },
    xAxis: { type: "value", name: "Target weight", axisLabel: { color: TEXT, formatter: (value: number) => `${(value * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: GRID } } },
    yAxis: { type: "value", name: "Realized weight", axisLabel: { color: TEXT, formatter: (value: number) => `${(value * 100).toFixed(0)}%` }, splitLine: { lineStyle: { color: GRID } } },
    series: [
      { type: "scatter", symbolSize: 10, data: items.map((item) => [item.target_weight, item.realized_weight]) },
      { type: "line", showSymbol: false, data: [[0, 0], [1, 1]], lineStyle: { type: "dashed" } },
    ],
  };
  return <ReactECharts option={option} style={{ height: 340 }} />;
}

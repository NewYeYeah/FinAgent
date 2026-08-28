import ReactECharts from "echarts-for-react";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import type {
  ExecutionEvidence,
  FactorEvidence,
  LineageGraph,
  PortfolioPoint,
} from "./types";

const CHART_TEXT = "#a8b4c7";
const GRID = "rgba(130, 148, 177, 0.16)";

export function NavChart({ points }: { points: PortfolioPoint[] }) {
  const option = {
    animation: false,
    tooltip: { trigger: "axis" },
    legend: { data: ["Net NAV", "Gross NAV"], textStyle: { color: CHART_TEXT } },
    grid: { left: 58, right: 24, top: 42, bottom: 48 },
    xAxis: {
      type: "category",
      data: points.map((point) => point.session_date),
      axisLabel: { color: CHART_TEXT },
      axisLine: { lineStyle: { color: GRID } },
    },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { color: CHART_TEXT },
      splitLine: { lineStyle: { color: GRID } },
    },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 20 }],
    series: [
      {
        name: "Net NAV",
        type: "line",
        showSymbol: false,
        data: points.map((point) => point.net_nav),
        lineStyle: { width: 2 },
      },
      {
        name: "Gross NAV",
        type: "line",
        showSymbol: false,
        data: points.map((point) => point.gross_nav),
        lineStyle: { width: 2, type: "dashed" },
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 360 }} />;
}

function drawdown(values: number[]): number[] {
  let peak = -Infinity;
  return values.map((value) => {
    peak = Math.max(peak, value);
    return peak > 0 ? value / peak - 1 : 0;
  });
}

export function DrawdownChart({ points }: { points: PortfolioPoint[] }) {
  const net = drawdown(points.map((point) => point.net_nav));
  const gross = drawdown(points.map((point) => point.gross_nav));
  const option = {
    animation: false,
    tooltip: { trigger: "axis", valueFormatter: (value: number) => `${(value * 100).toFixed(2)}%` },
    legend: { data: ["Net drawdown", "Gross drawdown"], textStyle: { color: CHART_TEXT } },
    grid: { left: 58, right: 24, top: 42, bottom: 48 },
    xAxis: {
      type: "category",
      data: points.map((point) => point.session_date),
      axisLabel: { color: CHART_TEXT },
      axisLine: { lineStyle: { color: GRID } },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: CHART_TEXT, formatter: (value: number) => `${(value * 100).toFixed(0)}%` },
      splitLine: { lineStyle: { color: GRID } },
    },
    dataZoom: [{ type: "inside" }, { type: "slider", height: 20 }],
    series: [
      { name: "Net drawdown", type: "line", showSymbol: false, areaStyle: {}, data: net },
      { name: "Gross drawdown", type: "line", showSymbol: false, data: gross },
    ],
  };
  return <ReactECharts option={option} style={{ height: 320 }} />;
}

export function ExecutionFunnel({ execution }: { execution: ExecutionEvidence }) {
  const option = {
    animation: false,
    tooltip: { trigger: "item" },
    series: [
      {
        type: "funnel",
        left: "10%",
        width: "80%",
        minSize: "20%",
        maxSize: "100%",
        sort: "descending",
        label: { color: "#e8eef8" },
        data: [
          { name: "Desired", value: execution.desired_order_count },
          { name: "Executable", value: execution.order_count },
          { name: "Filled", value: execution.fill_count },
        ],
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: 300 }} />;
}

export function RejectionChart({ execution }: { execution: ExecutionEvidence }) {
  const entries = Object.entries(execution.reason_counts).sort((left, right) => right[1] - left[1]);
  const option = {
    animation: false,
    tooltip: { trigger: "axis" },
    grid: { left: 180, right: 24, top: 20, bottom: 36 },
    xAxis: {
      type: "value",
      axisLabel: { color: CHART_TEXT },
      splitLine: { lineStyle: { color: GRID } },
    },
    yAxis: {
      type: "category",
      data: entries.map(([name]) => name),
      axisLabel: { color: CHART_TEXT, width: 160, overflow: "truncate" },
    },
    series: [{ type: "bar", data: entries.map(([, value]) => value) }],
  };
  return <ReactECharts option={option} style={{ height: Math.max(280, entries.length * 30) }} />;
}

export function FactorEvidenceChart({ factors }: { factors: FactorEvidence[] }) {
  const option = {
    animation: false,
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { data: ["Pooled RankICIR", "Worst-fold RankICIR"], textStyle: { color: CHART_TEXT } },
    grid: { left: 170, right: 24, top: 48, bottom: 36 },
    xAxis: {
      type: "value",
      axisLabel: { color: CHART_TEXT },
      splitLine: { lineStyle: { color: GRID } },
    },
    yAxis: {
      type: "category",
      data: factors.map((factor) => factor.feature_id),
      axisLabel: { color: CHART_TEXT, width: 150, overflow: "truncate" },
    },
    series: [
      {
        name: "Pooled RankICIR",
        type: "bar",
        data: factors.map((factor) => factor.metrics.pooled_rank_icir ?? factor.metrics.validation_rank_icir ?? 0),
      },
      {
        name: "Worst-fold RankICIR",
        type: "bar",
        data: factors.map((factor) => factor.metrics.worst_fold_rank_icir ?? 0),
      },
    ],
  };
  return <ReactECharts option={option} style={{ height: Math.max(300, factors.length * 38) }} />;
}

export function LineageDiagram({ graph }: { graph: LineageGraph }) {
  const levels = new Map<string, number>();
  const parents = new Map<string, string[]>();
  graph.edges.forEach((edge) => {
    parents.set(edge.child_id, [...(parents.get(edge.child_id) ?? []), edge.parent_id]);
  });
  const level = (id: string, trail = new Set<string>()): number => {
    if (levels.has(id)) return levels.get(id) ?? 0;
    if (trail.has(id)) return 0;
    const next = new Set(trail).add(id);
    const value = Math.max(0, ...(parents.get(id) ?? []).map((parent) => level(parent, next) + 1));
    levels.set(id, value);
    return value;
  };
  graph.nodes.forEach((node) => level(node.evidence_id));
  const grouped = new Map<number, string[]>();
  graph.nodes.forEach((node) => {
    const current = levels.get(node.evidence_id) ?? 0;
    grouped.set(current, [...(grouped.get(current) ?? []), node.evidence_id]);
  });
  const nodes: Node[] = graph.nodes.map((node) => {
    const current = levels.get(node.evidence_id) ?? 0;
    const index = (grouped.get(current) ?? []).indexOf(node.evidence_id);
    return {
      id: node.evidence_id,
      position: { x: current * 280, y: index * 120 },
      data: {
        label: (
          <div className="lineage-node">
            <strong>{node.label || node.evidence_type}</strong>
            <small>{node.status || node.stage}</small>
          </div>
        ),
      },
      style: {
        background: "#121c2d",
        border: "1px solid #31415f",
        color: "#eef4ff",
        borderRadius: 10,
        width: 220,
      },
    };
  });
  const edges: Edge[] = graph.edges.map((edge, index) => ({
    id: `${edge.parent_id}-${edge.child_id}-${index}`,
    source: edge.parent_id,
    target: edge.child_id,
    label: edge.relation,
    markerEnd: { type: MarkerType.ArrowClosed },
    style: { stroke: "#6d89b6" },
    labelStyle: { fill: "#9fb0c8" },
  }));
  return (
    <div className="lineage-canvas">
      <ReactFlow nodes={nodes} edges={edges} fitView nodesDraggable={false} nodesConnectable={false}>
        <Background gap={22} size={1} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Link2, LockKeyhole, Network } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ErrorState, LoadingState } from "../components";
import { patchWorkbenchContext, useWorkbenchContext, workbenchContextSearch, type WorkbenchContextState } from "./context";
import { researchQueryKeys, researchWorkspaceApi, type ResearchGraphNode } from "./researchWorkspaceApi";
import { WorkbenchInspectorSlot } from "./shell";
import { useWorkbenchSse } from "./stream";
import type { AgentActiveRunProjectionV3 } from "./streamTypes";
import "./experiments.css";

const LANE: Record<string, number> = {
  literature: 0,
  evidence: 0,
  research_cycle: 0,
  market_state: 1,
  hypothesis: 1,
  factor: 2,
  factor_set: 2,
  experiment: 3,
  evaluation: 4,
  agent_decision: 5,
  allocator: 6,
  strategy_candidate: 7,
  strategy: 8,
  portfolio: 9,
  execution: 10,
  agent_run: 6,
  terminal: 7,
};

function layoutNodes(items: ResearchGraphNode[]): Node[] {
  const counts = new Map<number, number>();
  return items.map((item) => {
    const lane = LANE[item.kind] ?? 8;
    const index = counts.get(lane) ?? 0;
    counts.set(lane, index + 1);
    return {
      id: item.node_id,
      position: { x: lane * 245, y: index * 145 },
      data: {
        label: <div className="research-graph-node"><span>{item.kind}</span><strong>{item.label}</strong><small className="mono">{item.identity}</small><em>{item.status}</em></div>,
        canonical: item,
      },
    };
  });
}

function layoutEdges(items: Array<{ edge_id: string; source: string; target: string; relation: string }>): Edge[] {
  return items.map((item) => ({
    id: item.edge_id,
    source: item.source,
    target: item.target,
    label: item.relation,
    markerEnd: { type: MarkerType.ArrowClosed },
  }));
}

function canonicalPatch(node: ResearchGraphNode): Partial<Record<keyof WorkbenchContextState, string | null>> {
  const output: Partial<Record<keyof WorkbenchContextState, string | null>> = {
    graph_node_id: node.node_id,
  };
  const allowed: Array<keyof WorkbenchContextState> = [
    "project_id",
    "thread_id",
    "run_id",
    "factor_id",
    "experiment_id",
    "research_cycle_id",
    "market_state_model_id",
    "strategy_id",
    "portfolio_validation_id",
  ];
  for (const key of allowed) {
    const value = node.context[key];
    if (value) output[key] = value;
  }
  if (node.kind === "research_cycle" || (node.kind === "terminal" && !output.run_id)) {
    output.research_cycle_id = node.identity;
  }
  if ((node.kind === "experiment" || node.kind === "evaluation") && !output.experiment_id) {
    output.experiment_id = node.identity;
  }
  if (node.kind === "factor" && !output.factor_id) output.factor_id = node.identity;
  if (node.kind === "strategy_candidate" && !output.strategy_id) output.strategy_id = node.identity;
  if (node.kind === "portfolio" && !output.portfolio_validation_id) output.portfolio_validation_id = node.identity;
  if (node.kind === "execution" && !output.portfolio_validation_id) output.portfolio_validation_id = node.identity;
  return output;
}

function GraphContent() {
  const { context, select } = useWorkbenchContext();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const runId = context.run_id ?? "";
  const query = useQuery({
    queryKey: researchQueryKeys.graph(runId),
    queryFn: () => researchWorkspaceApi.graph(runId || undefined),
    retry: false,
  });
  useWorkbenchSse<AgentActiveRunProjectionV3>({
    path: runId ? `/api/v3/streams/agent/runs/${encodeURIComponent(runId)}` : "",
    eventType: "agent_run_snapshot",
    identity: runId,
    enabled: Boolean(runId),
    onProjection: (projection) => {
      if (projection.run_id === runId) void queryClient.invalidateQueries({ queryKey: researchQueryKeys.graph(runId), exact: true });
    },
  });

  const nodes = useMemo(() => layoutNodes(query.data?.nodes ?? []), [query.data?.nodes]);
  const edges = useMemo(() => layoutEdges(query.data?.edges ?? []), [query.data?.edges]);
  const byId = useMemo(() => new Map((query.data?.nodes ?? []).map((node) => [node.node_id, node])), [query.data?.nodes]);
  const selected = context.graph_node_id ? byId.get(context.graph_node_id) : undefined;

  const onNodeClick: NodeMouseHandler = (_event, flowNode) => {
    const canonical = byId.get(flowNode.id);
    if (!canonical) return;
    const patch = canonicalPatch(canonical);
    const nextContext = patchWorkbenchContext(context, patch);
    select(patch, "graph_node_selected");
    if (canonical.href) {
      const target = new URL(canonical.href, window.location.origin);
      navigate({ pathname: target.pathname, search: workbenchContextSearch(nextContext) });
    }
  };

  if (query.isPending) return <LoadingState label="Loading canonical research lineage" />;
  if (query.error) return <ErrorState error={query.error} />;
  const graph = query.data;
  if (!graph) return null;

  return <div className="research-graph-page">
    <header className="experiments-header"><div><span className="eyebrow">Workbench-2 · canonical lineage</span><h1>Research Graph</h1><p>Persisted identities only. Missing relationships remain unresolved; text and names are never used to guess lineage.</p></div><div className="experiment-contract-stack"><span>React Flow presentation</span><span>canonical_identity_only</span><span>no hidden reasoning</span></div></header>
    <div className="research-graph-layout">
      <section className="research-graph-canvas" data-testid="research-graph">
        {nodes.length ? <ReactFlow nodes={nodes} edges={edges} onNodeClick={onNodeClick} fitView nodesDraggable={false} nodesConnectable={false} elementsSelectable>
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow> : <div className="experiment-empty">No canonical graph nodes are available. No lineage is inferred.</div>}
      </section>
      <WorkbenchInspectorSlot title="Lineage Inspector">
        <div className="experiment-inspector">
          <h3><Network size={14} /> Selected node</h3>
          {selected ? <><p><strong>{selected.kind}</strong> · {selected.status}</p><p className="mono">{selected.identity}</p><pre className="json-view">{JSON.stringify(selected.details, null, 2)}</pre>{selected.href ? <Link to={selected.href}><Link2 size={12} /> Open linked inspector</Link> : <p>Inspector target unavailable for this persisted identity.</p>}</> : <p>Select a graph node. The selected node is stored in WorkbenchContext and remains recoverable from the deep link.</p>}
          <h3>Unresolved lineage</h3>
          {graph.unresolved.length ? <ul className="research-unresolved">{graph.unresolved.map((item, index) => <li key={`${String(item.call_id ?? item.cycle_id ?? "unresolved")}-${index}`}><code>{String(item.relation ?? "relationship")}</code><span>{String(item.reason ?? "unavailable")}</span></li>)}</ul> : <p>None reported.</p>}
          <Link to={`/experiments${workbenchContextSearch(context)}`}>Open Experiments</Link>
          <p><LockKeyhole size={12} /> Hidden chain-of-thought is not persisted or projected.</p>
          <small>Node positions are presentation layout only; nodes, edges, identities and metrics come from the server projection.</small>
        </div>
      </WorkbenchInspectorSlot>
    </div>
  </div>;
}

export function ResearchGraphPage() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 1_500 } } }));
  return <QueryClientProvider client={client}><GraphContent /></QueryClientProvider>;
}

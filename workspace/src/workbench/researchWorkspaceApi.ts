export interface ResearchExperiment {
  attempt_id: string;
  experiment_id: string | null;
  identity: string;
  identity_kind: "experiment_id" | "attempt_call_id";
  canonical_experiment_identity_available: boolean;
  run_id: string;
  project_id: string;
  thread_id: string;
  objective: string;
  hypothesis_id?: string | null;
  factor_set_id?: string | null;
  factor_ids: string[];
  allocator_proposal_id?: string | null;
  allocator?: string | null;
  status: "completed" | "failed" | "rejected" | "duplicate" | "repaired" | "incomplete";
  outcome?: string | null;
  evaluation_scope: Record<string, unknown>;
  authoritative_metrics: Record<string, unknown> | null;
  metrics_source: "persisted_research_result";
  provider_id: string;
  model_id: string;
  resource_snapshot: Record<string, unknown>;
  evaluation_budget: { used?: number | null; remaining?: number | null };
  tokens?: number | null;
  cost_microusd?: number | null;
  agent_decision?: {
    action_id: string;
    kind: string;
    recommendation: string;
    decision?: string | null;
    terminal?: string | null;
  } | null;
  related_identities: string[];
  error?: string | null;
  read_only: true;
  browser_recomputation: false;
  hidden_reasoning: "not_persisted_not_projected";
}

export interface ResearchExperimentsResponse {
  schema_version: string;
  configured: boolean;
  items: ResearchExperiment[];
  read_only: true;
  browser_recomputation: false;
  hidden_reasoning: "not_persisted_not_projected";
}

export interface ResearchExperimentDetailResponse {
  schema_version: string;
  item: ResearchExperiment;
  read_only: true;
  browser_recomputation: false;
  hidden_reasoning: "not_persisted_not_projected";
}

export interface ResearchComparisonResponse {
  schema_version: string;
  experiment_ids: string[];
  comparison_call_id: string | null;
  comparable: boolean;
  reason: string | null;
  persisted_comparison: Record<string, unknown> | null;
  items: Array<ResearchExperiment | { identity: string; experiment_id: string; status: "incomplete"; error: string }>;
  ranking: null;
  read_only: true;
  browser_recomputation: false;
}

export interface ResearchCycle {
  cycle_id: string;
  protocol_id?: string | null;
  protocol_version?: string | null;
  review_disposition?: string | null;
  terminal?: string | null;
  agent_value?: string | null;
  candidate_id?: string | null;
  economic_evidence: Record<string, unknown>;
  provider_usage: Record<string, unknown>;
  agent_reliability: Record<string, unknown>;
  resource_summary: Record<string, unknown>;
  authority: Record<string, boolean>;
  evidence: Record<string, string | null>;
}

export interface ResearchCyclesResponse {
  schema_version: string;
  items: ResearchCycle[];
  read_only: true;
  browser_recomputation: false;
}

export interface ResearchGraphNode {
  node_id: string;
  kind: string;
  identity: string;
  label: string;
  status: string;
  href: string | null;
  context: Record<string, string>;
  details: Record<string, unknown>;
}

export interface ResearchGraphEdge {
  edge_id: string;
  source: string;
  target: string;
  relation: string;
}

export interface ResearchGraphResponse {
  schema_version: string;
  nodes: ResearchGraphNode[];
  edges: ResearchGraphEdge[];
  unresolved: Array<Record<string, unknown>>;
  read_only: true;
  canonical_identity_only: true;
  browser_recomputation: false;
  hidden_reasoning: "not_persisted_not_projected";
}

async function json<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export const researchQueryKeys = {
  root: ["workbench2", "research"] as const,
  experiments: (runId = "") => [...researchQueryKeys.root, "experiments", runId] as const,
  experiment: (identity: string) => [...researchQueryKeys.root, "experiment", identity] as const,
  comparison: (ids: string[]) => [...researchQueryKeys.root, "comparison", ...[...ids].sort()] as const,
  graph: (runId = "") => [...researchQueryKeys.root, "graph", runId] as const,
  cycles: () => [...researchQueryKeys.root, "cycles"] as const,
};

export const researchWorkspaceApi = {
  experiments(runId?: string) {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return json<ResearchExperimentsResponse>(`/api/v3/research-experiments${query}`);
  },
  experiment(identity: string) {
    return json<ResearchExperimentDetailResponse>(`/api/v3/research-experiments/${encodeURIComponent(identity)}`);
  },
  comparison(ids: string[]) {
    const params = new URLSearchParams();
    for (const id of ids) params.append("experiment_id", id);
    return json<ResearchComparisonResponse>(`/api/v3/research-experiments/compare?${params.toString()}`);
  },
  graph(runId?: string) {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    return json<ResearchGraphResponse>(`/api/v3/research-graph${query}`);
  },
  cycles() {
    return json<ResearchCyclesResponse>("/api/v3/research-cycles");
  },
};

export interface MarketStateItem {
  model_id: string;
  model: Record<string, unknown>;
  model_artifact_id: string;
  result_artifact_id?: string | null;
  historical_states: Array<Record<string, unknown>>;
  current_snapshot: Record<string, unknown> | null;
  transitions: Array<Record<string, unknown>>;
  unavailable_snapshot_count: number;
  available_snapshot_count: number;
  run_id?: string | null;
  evaluation_data_status?: string | null;
  interpretation?: string | null;
  feature_definitions: string[];
  feature_identities: null;
  feature_identity_status: string;
  causal: Record<string, unknown>;
  factor_state_evidence: Array<{
    factor_id: string;
    status: string;
    evaluations: Array<Record<string, unknown>>;
    allocator_weight_observations: Array<Record<string, unknown>>;
  }>;
  linked_experiment_ids: string[];
  unavailable: Record<string, string | null>;
}

export interface MarketStateIndexResponse {
  schema_version: string;
  items: MarketStateItem[];
  warnings: string[];
  read_only: true;
  browser_recomputation: false;
  causal_projection: true;
  hidden_reasoning: "not_persisted_not_projected";
}

export interface MarketStateDetailResponse extends Omit<MarketStateIndexResponse, "items"> {
  item: MarketStateItem;
}

export interface FactorIntelligenceSummary {
  factor_id: string;
  status: string;
  status_reason: string;
  family?: string | null;
  mechanism?: string | null;
  hypothesis?: string | null;
  origin?: string | null;
  provenance: Record<string, string>;
  created_at?: string | null;
  definition_conflict: boolean;
  library_ids: string[];
  lifecycle: Array<Record<string, unknown>>;
  evaluation_count: number;
  latest_model_id?: string | null;
  evaluation_selection_reason: string;
}

export interface FactorIntelligenceDetail extends Omit<FactorIntelligenceSummary, "evaluation_count"> {
  evaluations: Array<Record<string, unknown>>;
  latest_evaluation: Record<string, unknown> | null;
  global_metrics: Record<string, unknown> | null;
  state_metrics: Record<string, unknown> | null;
  cost_sensitive_economics: Record<string, unknown> | null;
  similarity: unknown;
  novelty: null;
  novelty_status: string;
  allocator_weights: Array<Record<string, unknown>>;
  allocator_weight_status: string;
  linked_market_state_model_ids: string[];
  linked_experiments: Array<Record<string, unknown>>;
  agent_decision_history: Array<Record<string, unknown>>;
  evidence_identities: string[];
  unavailable: Record<string, string | null>;
}

export interface FactorIntelligenceIndexResponse {
  schema_version: string;
  items: FactorIntelligenceSummary[];
  warnings: string[];
  read_only: true;
  browser_recomputation: false;
  hidden_reasoning: "not_persisted_not_projected";
}

export interface FactorIntelligenceDetailResponse {
  schema_version: string;
  item: FactorIntelligenceDetail;
  warnings: string[];
  read_only: true;
  browser_recomputation: false;
  hidden_reasoning: "not_persisted_not_projected";
}

async function json<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export const marketFactorQueryKeys = {
  root: ["workbench2", "market-factor"] as const,
  markets: () => [...marketFactorQueryKeys.root, "markets"] as const,
  market: (modelId: string) => [...marketFactorQueryKeys.root, "market", modelId] as const,
  factors: () => [...marketFactorQueryKeys.root, "factors"] as const,
  factor: (factorId: string) => [...marketFactorQueryKeys.root, "factor", factorId] as const,
};

export const marketFactorApi = {
  markets() {
    return json<MarketStateIndexResponse>("/api/v3/market-state");
  },
  market(modelId: string) {
    return json<MarketStateDetailResponse>(`/api/v3/market-state/${encodeURIComponent(modelId)}`);
  },
  factors() {
    return json<FactorIntelligenceIndexResponse>("/api/v3/factor-intelligence");
  },
  factor(factorId: string) {
    return json<FactorIntelligenceDetailResponse>(`/api/v3/factor-intelligence/${encodeURIComponent(factorId)}`);
  },
};

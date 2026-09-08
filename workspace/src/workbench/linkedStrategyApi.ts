export interface LinkedStrategyCycleSummary {
  cycle_id: string;
  terminal?: string | null;
  agent_value?: string | null;
  candidate_id?: string | null;
  mode: "candidate" | "no_candidate" | "not_accepted";
  strategy_binding_status: string;
  r5_eligible: boolean;
}

export interface LinkedStrategyIndex {
  schema_version: string;
  items: LinkedStrategyCycleSummary[];
  default_cycle_id: string | null;
  historical_strategy_series_count: number;
  historical_strategy_relation: string;
  read_only: true;
  canonical_identity_only: true;
  browser_recomputation: false;
  hidden_reasoning: "not_persisted_not_projected";
}

export interface LinkedStrategyDetail {
  schema_version: string;
  cycle: {
    cycle_id: string;
    accepted: boolean;
    review_disposition?: string | null;
    terminal?: string | null;
    agent_value?: string | null;
    candidate_id?: string | null;
    economic_evidence: Record<string, unknown>;
    agent_reliability: Record<string, unknown>;
    authority: Record<string, unknown>;
  };
  mode: "candidate" | "no_candidate" | "not_accepted";
  explanation: Record<string, unknown>;
  candidate: Record<string, unknown> | null;
  strategy_binding: { status: string; reason?: string; binding?: Record<string, unknown> | null };
  combined_strategy_evidence: Record<string, unknown> & { available: boolean };
  target_portfolio: Record<string, unknown> & { available: boolean };
  execution_pnl: Record<string, unknown> & { available: boolean };
  attribution: Record<string, unknown> & { available: boolean };
  available_evidence: {
    market_state_model_ids: string[];
    factors: Array<{ factor_id: string; status: string }>;
    canonical_experiment_ids: string[];
    historical_strategy_series: Array<Record<string, unknown>>;
  };
  r5: { status: string; eligible: boolean };
  links: {
    market?: string | null;
    factors?: string[];
    experiments?: string[];
    strategy?: string | null;
    portfolio?: string | null;
    execution?: string | null;
    research_graph?: string | null;
    agent?: string | null;
    evidence?: string[];
  };
  unresolved: Array<Record<string, unknown>>;
  read_only: true;
  canonical_identity_only: true;
  browser_recomputation: false;
  hidden_reasoning: "not_persisted_not_projected";
}

async function json<T>(path: string): Promise<T> {
  const response = await fetch(path, { method: "GET", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export const linkedStrategyQueryKeys = {
  root: ["workbench2", "linked-strategy"] as const,
  index: () => [...linkedStrategyQueryKeys.root, "index"] as const,
  cycle: (cycleId: string) => [...linkedStrategyQueryKeys.root, "cycle", cycleId] as const,
};

export const linkedStrategyApi = {
  index: () => json<LinkedStrategyIndex>("/api/v3/linked-strategy"),
  cycle: (cycleId: string) =>
    json<LinkedStrategyDetail>(`/api/v3/linked-strategy/cycles/${encodeURIComponent(cycleId)}`),
};

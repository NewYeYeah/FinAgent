export interface ResearchMetrics {
  mean_fold_return_5bp: number | null;
  worst_fold_return_5bp: number | null;
  drawdown_5bp: number | null;
  turnover_5bp: number;
  fallback_rate: number | null;
  factor_concentration: number | null;
  evaluable_folds: number;
  difference_to_equal_weight_5bp: number | null;
  cost_sensitivity?: Record<string, { mean_fold_return: number | null; worst_fold_return: number | null }>;
}
export interface ResearchFactorSet { factor_set_id: string; factor_ids: string[]; hypothesis_id: string; }
export interface ResearchAllocator { allocator_proposal_id: string; allocator: string; lookback_sessions: number; minimum_observations: number; ridge_alpha: number; }
export interface ResearchMarketState {
  model_id: string;
  snapshot: { available_at: string; probabilities: number[] | null; unavailable_reason: string | null };
  availability: string;
}
export interface ResearchState {
  objective: string;
  factor_set: ResearchFactorSet | null;
  allocator: ResearchAllocator | null;
  market_state: ResearchMarketState | null;
  latest_experiment: { experiment_id: string; preferred_allocator: string; metrics: ResearchMetrics; evaluation_mode: string } | null;
  resources: { status: string; attempts: number; evaluations: number; tokens: number; cost_microusd: number; remaining_tool_calls: number; remaining_evaluations: number; remaining_tokens: number; remaining_cost_microusd: number };
  explicit_decision: { critique: string; next_action: string } | null;
  candidate: ResearchResult | null;
  history_cutoff: string | null;
  development_only: true;
  alpha_authority: false;
  paper_authority: false;
  live_authority: false;
}
export interface ResearchResult {
  outcome: string;
  evaluation_mode?: string;
  admission_semantics?: "PREDECLARED_STATIC" | "ADAPTIVE_RETROSPECTIVE";
  historically_predeclared?: boolean;
  adaptive_search_exposed?: boolean;
  experiment_id?: string;
  preferred_allocator?: string;
  factor_set?: ResearchFactorSet;
  allocator_proposal?: ResearchAllocator;
  market_state?: ResearchMarketState;
  summary?: { arms: Record<string, ResearchMetrics> };
  proposal?: { factor_id: string; proposed_at: string; proposal_context_id: string; history_cutoff: string | null; proposal_id?: string; visible_history_id?: string; factor_definition_digest?: string };
  record?: { payload: { title?: string; summary?: string; metrics?: { valid_count: number; rank_ic?: number } } };
  attempt_counts?: Record<string, number>;
  resource_cost?: { evaluation_slots: number; tokens: number; cost_microusd: number };
  total?: number;
  next_offset?: number | null;
  hypothesis_id?: string;
  factor?: { factor_id: string; hypothesis: string; status: string; family: string };
  factors?: { factor_id: string; hypothesis: string; status: string; family: string }[];
  candidate_id?: string;
  decision?: string;
  explicit_decision?: { critique: string; next_action: string };
  artifact_ref?: string;
  experiments?: { experiment_id: string; allocator: string; metrics_5bp: ResearchMetrics | null }[];
  status?: string;
  code?: string;
}
export interface ResearchTool {
  tool: string;
  arguments: Record<string, unknown>;
  result: ResearchResult | null;
  policy: { outcome: string; reason: string };
}
export interface ResearchProviderStatus { provider_available: boolean; provider_id?: string; model_id?: string; reason?: string; cancel_supported: boolean; }
export interface ResearchStartResponse { run_id: string; command_run_id: string; state: string; provider: ResearchProviderStatus; }
export interface ResearchAgUiEvent { type: string; snapshot?: ResearchState; [key: string]: unknown; }

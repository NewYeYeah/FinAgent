export type EvidenceStage =
  | "a2_factor_acceptance"
  | "a2p6_robust_research"
  | "a4_portfolio_validation"
  | "agent_run"
  | "unknown";

export interface CatalogItem {
  evidence_id: string;
  evidence_type: string;
  stage: EvidenceStage;
  authority: "authoritative" | "derived" | "diagnostic";
  system_status: string;
  research_status: string;
  reserve_status: string;
  promotion_eligible: boolean;
  program_id: string;
  spec_id: string;
  data_version: string;
  source_uri: string;
  factor_count: number;
  has_portfolio: boolean;
  has_execution: boolean;
  detail_url: string;
}

export interface CatalogResponse {
  schema_version: string;
  read_only: boolean;
  items: CatalogItem[];
  warnings: string[];
}

export interface EvidenceRef {
  evidence_id: string;
  evidence_type: string;
  schema_version: string;
  stage: EvidenceStage;
  authority: "authoritative" | "derived" | "diagnostic";
  artifact_digest: string;
  source_uri: string;
  parent_ids: string[];
  program_id: string;
  spec_id: string;
  data_version: string;
  git_sha: string;
  metadata: Record<string, unknown>;
}

export interface LineageNode {
  evidence_id: string;
  evidence_type: string;
  stage: EvidenceStage;
  authority: string;
  status: string;
  label: string;
}

export interface LineageEdge {
  parent_id: string;
  child_id: string;
  relation: string;
}

export interface LineageGraph {
  nodes: LineageNode[];
  edges: LineageEdge[];
}

export interface FoldEvidence {
  fold_id: string;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  metrics: Record<string, number>;
}

export interface FactorEvidence {
  feature_id: string;
  feature_digest: string;
  hypothesis: string;
  selected: boolean;
  weight: number;
  direction: number;
  status: string;
  reason_codes: string[];
  metrics: Record<string, number>;
  folds: FoldEvidence[];
}

export interface PortfolioPoint {
  session_date: string;
  net_nav: number;
  gross_nav: number;
  net_return: number;
  gross_return: number;
  fees: number;
  slippage: number;
  one_way_turnover: number;
  implementation_shortfall: number;
  maximum_ex_post_participation: number;
  desired_order_count: number;
  order_count: number;
  fill_count: number;
  rejected_order_count: number;
  cash_fallback: boolean;
}

export interface PortfolioEvidence {
  metrics: Record<string, number>;
  points: PortfolioPoint[];
  fold_metrics: FoldEvidence[];
}

export interface ExecutionEvidence {
  desired_order_count: number;
  order_count: number;
  fill_count: number;
  rejected_order_count: number;
  rejected_order_ratio: number;
  cash_fallback_count: number;
  cash_fallback_ratio: number;
  reason_counts: Record<string, number>;
  costs: Record<string, number>;
  maximum_ex_post_participation: number;
}

export interface EvidenceBundle {
  schema_version: string;
  root: EvidenceRef;
  refs: EvidenceRef[];
  system_status: string;
  research_status: string;
  reserve_status: string;
  promotion_eligible: boolean;
  factors: FactorEvidence[];
  portfolio: PortfolioEvidence | null;
  execution: ExecutionEvidence | null;
  lineage: LineageGraph;
  metadata: Record<string, unknown>;
}

export interface FactorOccurrence {
  parent_evidence_id: string;
  parent_stage: EvidenceStage;
  program_id: string;
  research_status: string;
  reserve_status: string;
  factor: FactorEvidence;
}

export interface FactorResponse {
  feature_digest: string;
  occurrences: FactorOccurrence[];
  read_only: boolean;
}

export interface AgentRunSummary {
  run_id: string;
  task_id: string;
  objective: string;
  actor: string;
  started_at: string;
  finished_at: string;
  status: string;
  project_id: string;
  thread_id: string;
  trigger_type: string;
}

export interface AgentProjectionItem {
  item_id: string;
  item_type: string;
  occurred_at: string;
  title: string;
  status: string;
  summary: string;
  call_id: string;
  evidence_ids: string[];
  metadata: Record<string, unknown>;
}

export interface AgentRunProjection {
  schema_version: string;
  run_id: string;
  task_id: string;
  project_id: string;
  thread_id: string;
  actor: string;
  trigger_type: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  objective: string;
  items: AgentProjectionItem[];
  artifact_ids: string[];
  token_usage: Record<string, number>;
  latency_ms: number;
  governance: Record<string, unknown>;
  error: string;
  hidden_reasoning: string;
}

export interface WidgetSpec {
  widget_id: string;
  version: string;
  surface: string;
  question: string;
  evidence_types: string[];
  data_endpoint: string;
  data_schema: string;
  renderer: string;
  parameters: Array<Record<string, unknown>>;
  link_keys: string[];
  lineage_refs: string[];
  authority: string;
  ai_visible: boolean;
  metadata: Record<string, unknown>;
}

export interface LifecycleStage {
  stage: string;
  label: string;
  status: string;
  authority: string;
}

export interface WorkspaceProject {
  project_id: string;
  program_id: string;
  program_evidence_id: string;
  program_spec_id: string;
  selection_id: string;
  data_version: string;
  git_sha: string;
  system_status: string;
  research_status: string;
  protocol_frozen: boolean;
  a3_status: string;
  a3_authority: string;
  a4_validation_id: string;
  a4_spec_id: string;
  a4_status: string;
  a4_execution_validation_passed: boolean;
  reserve: Record<string, unknown> & { status?: string; reserve_id?: string };
  promotion_eligible: boolean;
  a5_status: string;
  lifecycle: LifecycleStage[];
  warning?: string;
}

export interface ProjectsResponse {
  schema_version: string;
  read_only: boolean;
  items: WorkspaceProject[];
  warnings: string[];
}

export interface GateCheck {
  criterion: string;
  metric: number;
  metric_key: string;
  operator: string;
  threshold: number | null;
  threshold_key: string;
  passed: boolean | null;
  authority: string;
}

export interface GateRow {
  feature_id: string;
  feature_digest: string;
  passed: boolean;
  reason_codes: string[];
  robust_score: number;
  checks: GateCheck[];
}

export interface StatisticalEvidence {
  feature_id: string;
  feature_digest: string;
  passed: boolean;
  effect: number;
  effect_metric: string;
  bootstrap_ci_lower: number;
  bootstrap_ci_upper: number;
  hac_tstat: number;
  hac_pvalue: number;
  bootstrap_pvalue: number;
  holm_pvalue: number;
  bh_qvalue: number;
  authority: string;
}

export interface FoldEvidenceCell {
  feature_id: string;
  feature_digest: string;
  fold_id: string;
  train_direction: number;
  train_rank_icir: number;
  test_rank_icir: number;
  test_raw_rank_icir: number;
  coverage: number;
  turnover: number;
  authority: string;
}

export interface ProgramCockpitResponse {
  schema_version: string;
  read_only: boolean;
  program_id: string;
  evidence_id: string;
  system_status: string;
  research_status: string;
  reserve: Record<string, unknown> & { status?: string; reserve_id?: string };
  promotion_eligible: boolean;
  identity: Record<string, unknown>;
  gate_matrix: {
    gate_config: Record<string, unknown>;
    items: GateRow[];
    overall_authority: string;
    criterion_cell_authority: string;
  };
  statistics: { items: StatisticalEvidence[] };
  fold_evidence: { fold_ids: string[]; items: FoldEvidenceCell[]; authority: string };
  frozen_components: Array<Record<string, unknown>>;
}

export interface PortfolioNavPoint {
  session_date: string;
  net_nav: number;
  gross_nav: number;
  net_return: number;
  gross_return: number;
  fold_id: string;
}

export interface RollingPoint {
  session_date: string;
  window_periods: number;
  rolling_return: number;
  rolling_volatility: number;
  rolling_sharpe: number;
}

export interface PortfolioCockpitResponse {
  schema_version: string;
  read_only: boolean;
  validation_id: string;
  status: string;
  system_status?: string;
  reserve: Record<string, unknown> & { status?: string; reserve_id?: string };
  promotion_eligible?: boolean;
  no_portfolio?: boolean;
  metrics?: Record<string, number | string>;
  nav_series?: PortfolioNavPoint[];
  derived_rolling?: {
    authority: string;
    window: number;
    annualization: number;
    items: RollingPoint[];
  };
  folds?: Array<Record<string, unknown>>;
  economic_evidence?: Record<string, number | string>;
}

export interface ExecutionCockpitResponse {
  schema_version: string;
  read_only: boolean;
  validation_id: string;
  reserve_status: string;
  ledger: Record<string, unknown> & { row_count?: number; available?: boolean };
  funnel: {
    desired: number;
    compiled_adjusted: number | null;
    executable: number;
    filled: number;
    authority: string;
    note: string;
  };
  decision_status_counts: Record<string, number>;
  reason_counts: Record<string, number>;
  reason_categories: Record<string, number>;
  costs: {
    components: Record<string, number>;
    gross_to_net_return_drag: number;
    authority: string;
    component_detail_available: boolean;
  };
  sessions: Array<Record<string, unknown>>;
  target_vs_realized: {
    authority: string;
    definition: string;
    items: Array<{
      fold_id: string;
      session_date: string;
      asset: string;
      target_weight: number;
      realized_weight: number;
      drift: number;
      authority: string;
    }>;
  };
}

export interface GovernanceResponse {
  schema_version: string;
  read_only: boolean;
  evidence_id: string;
  source_program_evidence_id: string;
  lineage: LineageGraph;
  reserve_status: string;
  promotion_eligible: boolean;
  protocol: Record<string, unknown>;
  a3_protocol_binding: null | {
    binding_id: string;
    authority: string;
    label: string;
    payload: Record<string, unknown>;
    note: string;
  };
  authority_legend: Record<string, string>;
}

export interface ProtocolDiffResponse {
  schema_version: string;
  read_only: boolean;
  authority: string;
  left_evidence_id: string;
  right_evidence_id: string;
  changed_count: number;
  changes: Array<{
    field: string;
    left: unknown;
    right: unknown;
    changed: boolean;
  }>;
}

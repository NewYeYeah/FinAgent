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

import type { AgentRunProjection } from "../types";

export interface AgentArtifactRefV3 {
  artifact_id: string;
  artifact_type: string;
  authority: string;
  detail_url: string;
  verification: string;
  evidence_ids: string[];
  source_uris: string[];
}

export interface AgentRunSummaryV3 {
  run_id: string;
  task_id: string;
  project_id: string;
  thread_id: string;
  project_identity_source: string;
  thread_identity_source: string;
  objective: string;
  actor: string;
  trigger_type: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  updated_at: string;
  item_count: number;
  artifact_count: number;
  artifact_refs: AgentArtifactRefV3[];
  unresolved_artifact_count: number;
  error: string;
  detail_url: string;
}

export interface AgentProjectSummaryV3 {
  project_id: string;
  identity_source: string;
  label: string;
  status: string;
  started_at: string;
  updated_at: string;
  thread_count: number;
  run_count: number;
  artifact_count: number;
  detail_url: string;
}

export interface AgentThreadSummaryV3 {
  thread_id: string;
  project_id: string;
  identity_source: string;
  label: string;
  status: string;
  started_at: string;
  updated_at: string;
  run_count: number;
  artifact_count: number;
  detail_url: string;
}

export interface AgentProjectsResponseV3 {
  schema_version: string;
  items: AgentProjectSummaryV3[];
  configured: boolean;
  read_only: boolean;
  hidden_reasoning: string;
}

export interface AgentProjectResponseV3 extends AgentProjectSummaryV3 {
  schema_version: string;
  threads: AgentThreadSummaryV3[];
  artifact_refs: AgentArtifactRefV3[];
  read_only: boolean;
}

export interface AgentThreadResponseV3 extends AgentThreadSummaryV3 {
  schema_version: string;
  runs: AgentRunSummaryV3[];
  artifact_refs: AgentArtifactRefV3[];
  read_only: boolean;
}

export interface AgentRunResponseV3 {
  schema_version: string;
  summary: AgentRunSummaryV3;
  run: AgentRunProjection;
  artifact_refs: AgentArtifactRefV3[];
  unresolved_artifact_count: number;
  read_only: boolean;
  hidden_reasoning: string;
}

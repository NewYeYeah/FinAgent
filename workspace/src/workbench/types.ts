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

export type ConfigDomainV3 =
  | "presentation"
  | "runtime"
  | "research_protocol"
  | "execution_protocol"
  | "operational_guardrail"
  | "secret_reference";

export type ConfigMutationPolicyV3 =
  | "presentation_only"
  | "restart_or_new_run"
  | "new_identity_required"
  | "governed_change_required"
  | "host_secret_binding_only";

export type JsonValueV3 = string | number | boolean | null | JsonValueV3[] | { [key: string]: JsonValueV3 };

export interface ConfigFieldSpecV3 {
  field_path: string;
  label: string;
  value_type: string;
  domain: ConfigDomainV3;
  mutation_policy: ConfigMutationPolicyV3;
  required: boolean;
  secret_redacted: boolean;
  description: string;
}

export interface ConfigDescriptorV3 {
  schema_version: string;
  descriptor_id: string;
  title: string;
  section: string;
  default_domain: ConfigDomainV3;
  fields: ConfigFieldSpecV3[];
  snapshot_ids: string[];
  read_only: boolean;
}

export interface ConfigSnapshotV3 {
  schema_version: string;
  snapshot_id: string;
  descriptor_id: string;
  section: string;
  source_uri: string;
  source_sha256: string;
  values: Record<string, JsonValueV3>;
  domains: Record<string, ConfigDomainV3>;
  mutation_policies: Record<string, ConfigMutationPolicyV3>;
  redacted_fields: string[];
  read_only: boolean;
}

export interface ConfigRegistryResponseV3 {
  schema_version: string;
  read_only: boolean;
  descriptors: ConfigDescriptorV3[];
  snapshots: ConfigSnapshotV3[];
  warnings: string[];
}

export interface ConfigDiffItemV3 {
  field_path: string;
  before: JsonValueV3 | undefined;
  after: JsonValueV3 | undefined;
  domain: ConfigDomainV3;
  mutation_policy: ConfigMutationPolicyV3;
  requires_new_identity: boolean;
}

export interface ConfigDiffV3 {
  schema_version: string;
  diff_id: string;
  descriptor_id: string;
  left_snapshot_id: string;
  right_snapshot_id: string;
  changes: ConfigDiffItemV3[];
  requires_new_identity: boolean;
  read_only: boolean;
}

export interface CommandSpecV3 {
  schema_version: string;
  command_id: string;
  title: string;
  description: string;
  level: "L0" | "L1";
  config_descriptor_ids: string[];
  binding_kind: string;
  binding_ref: string;
  gateway_readiness: "catalog_only" | "adapter_required" | "application_service_ready";
  produces: string[];
  requires_confirmation: boolean;
  execution_enabled: false;
  catalog_only: true;
}

export interface CommandCatalogResponseV3 {
  schema_version: string;
  read_only: true;
  execution_enabled: false;
  control_plane_enabled: false;
  items: CommandSpecV3[];
  forbidden_authority: string[];
}

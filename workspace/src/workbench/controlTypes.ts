import type { CommandSpecV3 } from "./types";

export type CommandIntentStateV3 = "draft" | "validated" | "rejected";
export type CommandRunStateV3 = "planned" | "running" | "succeeded" | "failed" | "rejected";
export type CommandResultStatusV3 = "succeeded" | "failed" | "rejected";

export interface ControlStatusV3 {
  schema_version: string;
  version: string;
  control_plane_enabled: true;
  local_only: true;
  remote_binding_supported: false;
  requested_by: string;
  application_service_ready: string[];
  recovered_incomplete_runs: string[];
  store: {
    schema_version: string;
    run_counts: Record<string, number>;
    terminal_states: string[];
  };
  forbidden_authority: string[];
}

export interface ControlCommandSpecV3 extends CommandSpecV3 {
  control_execution_enabled: boolean;
  control_plane_enabled: true;
}

export interface ControlCommandCatalogV3 {
  schema_version: string;
  control_plane_enabled: true;
  local_only: true;
  items: ControlCommandSpecV3[];
  forbidden_authority: string[];
}

export interface CommandIntentV3 {
  schema_version: string;
  intent_id: string;
  command_id: string;
  config_snapshot_id: string | null;
  context: Record<string, string>;
  requested_by: string;
  state: CommandIntentStateV3;
}

export interface CommandRunV3 {
  schema_version: string;
  command_run_id: string;
  intent_id: string;
  command_id: string;
  state: CommandRunStateV3;
  started_at: string | null;
  finished_at: string | null;
}

export interface CommandResultV3 {
  schema_version: string;
  command_run_id: string;
  status: CommandResultStatusV3;
  evidence_ids: string[];
  message: string;
}

export interface CommandEventV3 {
  schema_version: string;
  event_id: string;
  command_run_id: string;
  sequence: number;
  event_type: string;
  state: CommandRunStateV3;
  occurred_at: string;
  message: string;
}

export interface CommandRecordV3 {
  schema_version: string;
  intent: CommandIntentV3;
  run: CommandRunV3;
  parameters: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  result: CommandResultV3 | null;
  artifact_paths: string[];
  outputs: Record<string, unknown>;
  events: CommandEventV3[];
}

export interface CommandRecordListV3 {
  schema_version: string;
  items: CommandRecordV3[];
}

export interface ControlRunRequestV3 {
  request_id: string;
  command_id: string;
  config_snapshot_id?: string;
  context: Record<string, string>;
  confirmed: boolean;
  validation_id?: string;
}

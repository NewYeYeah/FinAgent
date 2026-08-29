export type WorkbenchSseStatus =
  | "disabled"
  | "unavailable"
  | "connecting"
  | "open"
  | "reconnecting";

export type WorkbenchSseEventType =
  | "agent_run_snapshot"
  | "command_run_snapshot";

export interface StreamActivityV3 {
  item_id: string;
  item_type: string;
  occurred_at: string;
  title: string;
  status: string;
}

export interface AgentActiveRunProjectionV3 {
  schema_version: string;
  read_only: true;
  run_id: string;
  project_id: string;
  thread_id: string;
  objective: string;
  actor: string;
  trigger_type: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  updated_at: string;
  item_count: number;
  artifact_count: number;
  unresolved_artifact_count: number;
  latest_activity: StreamActivityV3 | null;
  terminal: boolean;
  hidden_reasoning: "not_persisted_not_projected";
}

export interface CommandRunStreamProjectionV3 {
  schema_version: string;
  read_only: true;
  command_run_id: string;
  command_id: string;
  state: string;
  config_snapshot_id: string | null;
  context: Record<string, string>;
  requested_by: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
  result_status: string | null;
  evidence_ids: string[];
  latest_event: null | {
    event_id: string;
    sequence: number;
    event_type: string;
    state: string;
    occurred_at: string;
  };
  terminal: boolean;
}

export interface WorkbenchSseEventV3<TProjection> {
  schema_version: string;
  event_id: string;
  event_type: WorkbenchSseEventType;
  identity: string;
  occurred_at: string;
  projection: TProjection;
}

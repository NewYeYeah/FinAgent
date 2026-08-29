import type {
  AgentRunProjection,
  AgentRunSummary,
  CatalogResponse,
  EvidenceBundle,
  FactorResponse,
  WidgetSpec,
  ExecutionCockpitResponse,
  GovernanceResponse,
  PortfolioCockpitResponse,
  ProgramCockpitResponse,
  ProjectsResponse,
  ProtocolDiffResponse,
  ReserveLedgerResponse,
  ReserveLifecycleResponse,
  ReserveListResponse,
} from "./types";
import type {
  AgentProjectResponseV3,
  AgentProjectsResponseV3,
  AgentRunResponseV3,
  AgentThreadResponseV3,
  CommandCatalogResponseV3,
  ConfigDiffV3,
  ConfigRegistryResponseV3,
} from "./workbench/types";
import type {
  CommandRecordListV3,
  CommandRecordV3,
  ControlCommandCatalogV3,
  ControlRunRequestV3,
  ControlStatusV3,
} from "./workbench/controlTypes";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
const CONTROL_API_BASE = (
  import.meta.env.VITE_CONTROL_API_BASE ?? "http://127.0.0.1:8766"
).replace(/\/$/, "");

async function responseError(response: Response): Promise<Error> {
  let detail = `${response.status} ${response.statusText}`;
  try {
    const payload = (await response.json()) as { detail?: string };
    if (payload.detail) detail = payload.detail;
  } catch {
    // Keep the HTTP fallback when the response is not JSON.
  }
  return new Error(detail);
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as T;
}

async function controlGetJson<T>(path: string): Promise<T> {
  const response = await fetch(`${CONTROL_API_BASE}${path}`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as T;
}

async function controlPostJson<TBody extends object, TResult>(
  path: string,
  body: TBody,
): Promise<{ status: number; data: TResult }> {
  const response = await fetch(`${CONTROL_API_BASE}${path}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok && response.status !== 422) throw await responseError(response);
  return { status: response.status, data: (await response.json()) as TResult };
}

export const workspaceApi = {
  catalog: () => getJson<CatalogResponse>("/api/v1/catalog"),
  widgets: async () => {
    const payload = await getJson<{ items: WidgetSpec[] }>("/api/v1/widgets");
    return payload.items;
  },
  evidence: (evidenceId: string) =>
    getJson<EvidenceBundle>(`/api/v1/evidence/${encodeURIComponent(evidenceId)}`),
  factor: (digest: string) =>
    getJson<FactorResponse>(`/api/v1/factors/${encodeURIComponent(digest)}`),
  agentRuns: async () => {
    const payload = await getJson<{
      items: AgentRunSummary[];
      configured: boolean;
    }>("/api/v1/agent/runs");
    return payload;
  },
  agentRun: (runId: string) =>
    getJson<AgentRunProjection>(`/api/v1/agent/runs/${encodeURIComponent(runId)}`),
  agentProjectsV3: () => getJson<AgentProjectsResponseV3>("/api/v3/agent/projects"),
  agentProjectV3: (projectId: string) =>
    getJson<AgentProjectResponseV3>(`/api/v3/agent/projects/${encodeURIComponent(projectId)}`),
  agentThreadV3: (threadId: string) =>
    getJson<AgentThreadResponseV3>(`/api/v3/agent/threads/${encodeURIComponent(threadId)}`),
  agentRunV3: (runId: string) =>
    getJson<AgentRunResponseV3>(`/api/v3/agent/runs/${encodeURIComponent(runId)}`),
  configRegistryV3: () => getJson<ConfigRegistryResponseV3>("/api/v3/config"),
  configDiffV3: (left: string, right: string) =>
    getJson<ConfigDiffV3>(
      `/api/v3/config/diff?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`,
    ),
  commandCatalogV3: () => getJson<CommandCatalogResponseV3>("/api/v3/commands"),
  projectsV2: () => getJson<ProjectsResponse>("/api/v2/projects"),
  programCockpitV2: (programId: string) =>
    getJson<ProgramCockpitResponse>(`/api/v2/programs/${encodeURIComponent(programId)}/cockpit`),
  portfolioCockpitV2: (validationId: string) =>
    getJson<PortfolioCockpitResponse>(`/api/v2/a4/${encodeURIComponent(validationId)}/cockpit`),
  executionCockpitV2: (validationId: string) =>
    getJson<ExecutionCockpitResponse>(`/api/v2/a4/${encodeURIComponent(validationId)}/execution`),
  governanceV2: (evidenceId: string) =>
    getJson<GovernanceResponse>(`/api/v2/governance/${encodeURIComponent(evidenceId)}`),
  reservesV2: () => getJson<ReserveListResponse>("/api/v2/reserves"),
  reserveV2: (reserveId: string) =>
    getJson<ReserveLifecycleResponse>(`/api/v2/reserves/${encodeURIComponent(reserveId)}`),
  reserveLedgerV2: (reserveId: string) =>
    getJson<ReserveLedgerResponse>(`/api/v2/reserves/${encodeURIComponent(reserveId)}/ledger`),
  protocolDiffV2: (left: string, right: string) =>
    getJson<ProtocolDiffResponse>(
      `/api/v2/protocol-diff?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`,
    ),
  rawEvidenceV2: (evidenceId: string) =>
    getJson<Record<string, unknown>>(`/api/v2/evidence/${encodeURIComponent(evidenceId)}/raw`),
};

export const controlApi = {
  status: () => controlGetJson<ControlStatusV3>("/api/v3/control/status"),
  commands: () => controlGetJson<ControlCommandCatalogV3>("/api/v3/control/commands"),
  runs: (limit = 100) =>
    controlGetJson<CommandRecordListV3>(`/api/v3/control/runs?limit=${limit}`),
  run: (runId: string) =>
    controlGetJson<CommandRecordV3>(`/api/v3/control/runs/${encodeURIComponent(runId)}`),
  createRun: (request: ControlRunRequestV3) =>
    controlPostJson<ControlRunRequestV3, CommandRecordV3>("/api/v3/control/runs", request),
};

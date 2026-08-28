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
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      // Keep the HTTP fallback when the response is not JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
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
  projectsV2: () => getJson<ProjectsResponse>("/api/v2/projects"),
  programCockpitV2: (programId: string) =>
    getJson<ProgramCockpitResponse>(`/api/v2/programs/${encodeURIComponent(programId)}/cockpit`),
  portfolioCockpitV2: (validationId: string) =>
    getJson<PortfolioCockpitResponse>(`/api/v2/a4/${encodeURIComponent(validationId)}/cockpit`),
  executionCockpitV2: (validationId: string) =>
    getJson<ExecutionCockpitResponse>(`/api/v2/a4/${encodeURIComponent(validationId)}/execution`),
  governanceV2: (evidenceId: string) =>
    getJson<GovernanceResponse>(`/api/v2/governance/${encodeURIComponent(evidenceId)}`),
  protocolDiffV2: (left: string, right: string) =>
    getJson<ProtocolDiffResponse>(
      `/api/v2/protocol-diff?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`,
    ),
  rawEvidenceV2: (evidenceId: string) =>
    getJson<Record<string, unknown>>(`/api/v2/evidence/${encodeURIComponent(evidenceId)}/raw`),
};

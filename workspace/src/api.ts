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
  ArtifactInspectionV3,
  CommandCatalogResponseV3,
  CommandRunProjectionV3,
  ConfigDiffV3,
  ConfigRegistryResponseV3,
  WorkbenchReferenceKindV3,
  WorkbenchReferenceV3,
} from "./workbench/types";
import type {
  CommandRecordListV3,
  CommandRecordV3,
  ControlCommandCatalogV3,
  ControlRunRequestV3,
  ControlStatusV3,
} from "./workbench/controlTypes";
import type {
  FactorSeriesCatalogV4,
  FactorSeriesDetailV4,
  FactorSeriesDimensionsV4,
  FactorSeriesItemV4,
  FactorSeriesQueryV4,
  FactorSeriesSummaryV4,
} from "./workbench/factorTypes";
import type {
  StrategyDecisionQueryV4,
  StrategySeriesCatalogV4,
  StrategySeriesDetailV4,
  StrategySeriesDimensionsV4,
  StrategySeriesItemV4,
} from "./workbench/strategyTypes";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");
const CONTROL_API_BASE = (
  import.meta.env.VITE_CONTROL_API_BASE ?? "http://127.0.0.1:8766"
).replace(/\/$/, "");

export function workspaceEventSourceUrl(path: string): string {
  return `${API_BASE}${path}`;
}

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

function strategyDecisionQueryPath(
  seriesId: string,
  filters: {
    asset?: string;
    start?: string;
    end?: string;
    foldId?: string;
    limit?: number;
    offset?: number;
  },
): string {
  const params = new URLSearchParams();
  if (filters.asset) params.set("asset", filters.asset);
  if (filters.start) params.set("start", filters.start);
  if (filters.end) params.set("end", filters.end);
  if (filters.foldId) params.set("fold_id", filters.foldId);
  params.set("limit", String(filters.limit ?? 1000));
  params.set("offset", String(filters.offset ?? 0));
  return `/api/v4/strategy-series/${encodeURIComponent(seriesId)}/decisions?${params.toString()}`;
}

function factorSeriesQueryPath(
  seriesId: string,
  filters: {
    featureDigest?: string;
    foldId?: string;
    seriesKind?: string;
    metric?: string;
    labelName?: string;
    quantile?: number;
    start?: string;
    end?: string;
    limit?: number;
    offset?: number;
  },
): string {
  const params = new URLSearchParams();
  if (filters.featureDigest) params.set("feature_digest", filters.featureDigest);
  if (filters.foldId) params.set("fold_id", filters.foldId);
  if (filters.seriesKind) params.set("series_kind", filters.seriesKind);
  if (filters.metric) params.set("metric", filters.metric);
  if (filters.labelName) params.set("label_name", filters.labelName);
  if (filters.quantile != null) params.set("quantile", String(filters.quantile));
  if (filters.start) params.set("start", filters.start);
  if (filters.end) params.set("end", filters.end);
  params.set("limit", String(filters.limit ?? 1000));
  params.set("offset", String(filters.offset ?? 0));
  return `/api/v4/factor-series/${encodeURIComponent(seriesId)}/rows?${params.toString()}`;
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
  referenceV3: (kind: WorkbenchReferenceKindV3, identity: string) =>
    getJson<WorkbenchReferenceV3>(
      `/api/v3/refs/${encodeURIComponent(kind)}/${encodeURIComponent(identity)}`,
    ),
  artifactV3: (artifactId: string) =>
    getJson<ArtifactInspectionV3>(`/api/v3/artifacts/${encodeURIComponent(artifactId)}`),
  commandRunsV3: (limit = 100) =>
    getJson<{
      schema_version: string;
      read_only: true;
      configured: boolean;
      available: boolean;
      items: CommandRunProjectionV3[];
    }>(`/api/v3/command-runs?limit=${limit}`),
  commandRunV3: (runId: string) =>
    getJson<CommandRunProjectionV3>(`/api/v3/command-runs/${encodeURIComponent(runId)}`),
  configRegistryV3: () => getJson<ConfigRegistryResponseV3>("/api/v3/config"),
  configDiffV3: (left: string, right: string) =>
    getJson<ConfigDiffV3>(
      `/api/v3/config/diff?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`,
    ),
  commandCatalogV3: () => getJson<CommandCatalogResponseV3>("/api/v3/commands"),
  strategySeriesV4: () => getJson<StrategySeriesCatalogV4>("/api/v4/strategy-series"),
  strategySeriesByPortfolioV4: (validationId: string) =>
    getJson<StrategySeriesItemV4>(
      `/api/v4/strategy-series/by-portfolio/${encodeURIComponent(validationId)}`,
    ),
  strategySeriesDetailV4: (seriesId: string) =>
    getJson<StrategySeriesDetailV4>(
      `/api/v4/strategy-series/${encodeURIComponent(seriesId)}`,
    ),
  strategySeriesDimensionsV4: (seriesId: string) =>
    getJson<StrategySeriesDimensionsV4>(
      `/api/v4/strategy-series/${encodeURIComponent(seriesId)}/dimensions`,
    ),
  strategyDecisionsV4: (
    seriesId: string,
    filters: {
      asset?: string;
      start?: string;
      end?: string;
      foldId?: string;
      limit?: number;
      offset?: number;
    },
  ) => getJson<StrategyDecisionQueryV4>(strategyDecisionQueryPath(seriesId, filters)),
  factorSeriesV4: () => getJson<FactorSeriesCatalogV4>("/api/v4/factor-series"),
  factorSeriesByProgramV4: (programId: string) =>
    getJson<FactorSeriesItemV4>(
      `/api/v4/factor-series/by-program/${encodeURIComponent(programId)}`,
    ),
  factorSeriesDetailV4: (seriesId: string) =>
    getJson<FactorSeriesDetailV4>(
      `/api/v4/factor-series/${encodeURIComponent(seriesId)}`,
    ),
  factorSeriesDimensionsV4: (seriesId: string) =>
    getJson<FactorSeriesDimensionsV4>(
      `/api/v4/factor-series/${encodeURIComponent(seriesId)}/dimensions`,
    ),
  factorSeriesSummaryV4: (seriesId: string) =>
    getJson<FactorSeriesSummaryV4>(
      `/api/v4/factor-series/${encodeURIComponent(seriesId)}/summary`,
    ),
  factorSeriesRowsV4: (
    seriesId: string,
    filters: {
      featureDigest?: string;
      foldId?: string;
      seriesKind?: string;
      metric?: string;
      labelName?: string;
      quantile?: number;
      start?: string;
      end?: string;
      limit?: number;
      offset?: number;
    },
  ) => getJson<FactorSeriesQueryV4>(factorSeriesQueryPath(seriesId, filters)),
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
